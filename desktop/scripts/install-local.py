"""Reviewed local app maintenance, not a public release updater. macOS only."""
import argparse
import shutil
from app_install import archive_bundle, retire_archived_bundle, replace_contents, restore_contents, finish_contents, bundle_digest
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import sqlite3
import subprocess
import sys
import time

LABELS = ['com.personal.codex-telegram', 'com.personal.taskrelay.messages']
PLISTS = [Path.home() / 'Library/LaunchAgents' / (label + '.plist') for label in LABELS]
DOMAIN = 'gui/' + str(os.getuid())


def run(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=40)
    if check and result.returncode:
        raise RuntimeError(str(args[:3]) + ': ' + result.stderr[-1000:])
    return result

digest = bundle_digest
def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check_versions(candidate, installed):
    from task_relay.app_updates import version
    values = [plistlib.loads((app / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']
              for app in (candidate, installed)]
    if version(values[0]) < version(values[1]):
        raise ValueError('Refusing app downgrade from ' + values[1] + ' to ' + values[0] + '. Build a newer version.')
    return {'candidate_version': values[0], 'installed_version': values[1]}

def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.chmod(0o600)
    temp.replace(path)

def maintain_backups(data, receipt, *, prune=False):
    # Retention failures must not roll back or relabel a healthy installation.
    from task_relay.installation_retention import maintain
    try:
        return maintain(data, receipt, prune=prune)
    except Exception as exc:
        return {'status': 'preserved', 'error': str(exc)}

def loaded(label):
    return run(['launchctl', 'print', DOMAIN + '/' + label], False).returncode == 0

def app_pids():
    result = run(['ps', '-axo', 'pid=,command='])
    targets = {str(app / 'Contents/MacOS/task-relay-desktop') for app in (INSTALLED, CANDIDATE)}
    return [int(parts[0]) for line in result.stdout.splitlines()
            if len(parts := line.strip().split(None, 1)) == 2 and parts[1] in targets]

def pending_deliveries():
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_delivery_effects'").fetchone():
            return []
        rows = [dict(r) for r in db.execute("SELECT * FROM relay_delivery_effects WHERE status='submitting' ORDER BY id")]
        if any(r['receipt'] is not None for r in rows):
            raise RuntimeError('Submitting delivery already has a receipt; inspect before maintenance.')
        return rows


def sender_processes():
    # Include development/candidate senders, not only the installed service.
    lines = run(['ps', '-axo', 'pid=,command=']).stdout.splitlines()
    return [line for line in lines if any(token in line for token in
            ('-m task_relay.bridge', '/bridge.py run', '/MessagesRelay',
             '/task-relay-desktop', str(INSTALLED) + '/Contents/', str(CANDIDATE) + '/Contents/'))]


def require_stopped_senders():
    if any(loaded(label) for label in LABELS) or sender_processes():
        raise RuntimeError('Delivery senders are not proven stopped; maintenance held.')


def maintenance_pause(ident, deliveries):
    from task_relay import channel_policy
    with sqlite3.connect(DB, timeout=5) as db:
        db.execute('BEGIN IMMEDIATE')
        if pending_deliveries() != deliveries:
            raise RuntimeError('Delivery intents changed after preparation.')
        db.execute('CREATE TABLE IF NOT EXISTS relay_install_maintenance(id TEXT PRIMARY KEY, record TEXT NOT NULL)')
        for row in db.execute('SELECT record FROM relay_install_maintenance'):
            if json.loads(row[0])['phase'] != 'released':
                raise RuntimeError('Earlier maintenance remains held; inspect its journal before continuing.')
        before = channel_policy.read(db)
        paused = dict(before, paused=True, revision=before['revision'] + 1)
        value = dict(id=ident, phase='paused', before_policy=before, paused_policy=paused,
                     deliveries=deliveries, created=time.time())
        store_policy(db, paused)
        db.execute('INSERT INTO relay_install_maintenance VALUES (?,?)', (ident, json.dumps(value)))
    return value


def store_policy(db, policy):
    db.execute('CREATE TABLE IF NOT EXISTS relay_channel_settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS relay_channel_changes(revision INTEGER PRIMARY KEY,created REAL NOT NULL,value TEXT NOT NULL)')
    raw = json.dumps(policy, sort_keys=True)
    db.execute('INSERT OR REPLACE INTO relay_channel_settings VALUES (1,?)', (raw,))
    db.execute('INSERT INTO relay_channel_changes VALUES (?,?,?)', (policy['revision'], time.time(), raw))


def quarantine_deliveries(ident):
    from task_relay import channel_policy
    require_stopped_senders()
    with sqlite3.connect(DB, timeout=5) as db:
        db.execute('BEGIN IMMEDIATE')
        value = json.loads(db.execute('SELECT record FROM relay_install_maintenance WHERE id=?', (ident,)).fetchone()[0])
        if value['phase'] != 'paused' or channel_policy.read(db) != value['paused_policy']:
            raise RuntimeError('Maintenance state changed; hold for inspection.')
        if pending_deliveries() != value['deliveries']:
            raise RuntimeError('Delivery intents changed before quarantine.')
        require_stopped_senders()
        now = time.time()
        for row in value['deliveries']:
            db.execute("UPDATE relay_delivery_effects SET status='uncertain',error=?,updated=? WHERE id=?",
                       ('Sender stopped for maintenance '+ident+'; delivery outcome unknown; no replay.', now, row['id']))
        value.update(phase='quarantined', quarantined_at=now)
        db.execute('UPDATE relay_install_maintenance SET record=? WHERE id=?', (json.dumps(value), ident))
    return value


def release_maintenance(ident):
    from task_relay import channel_policy
    with sqlite3.connect(DB, timeout=5) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        value = json.loads(db.execute('SELECT record FROM relay_install_maintenance WHERE id=?', (ident,)).fetchone()[0])
        if value['phase'] != 'quarantined' or channel_policy.read(db) != value['paused_policy']:
            raise RuntimeError('Maintenance state changed; messaging remains held.')
        for original in value['deliveries']:
            row = dict(db.execute('SELECT * FROM relay_delivery_effects WHERE id=?', (original['id'],)).fetchone())
            if row['status'] != 'uncertain' or any(row[k] != original[k] for k in original if k not in ('status','error','updated')):
                raise RuntimeError('Quarantined intent changed; messaging remains held.')
        # Maintenance is not a user pause: retain intake cursors and preferences.
        restored = dict(value['before_policy'], revision=value['paused_policy']['revision'] + 1)
        store_policy(db, restored)
        value.update(phase='released', released_at=time.time(), restored_policy=restored)
        db.execute('UPDATE relay_install_maintenance SET record=? WHERE id=?', (json.dumps(value), ident))
    return value


def idle(deliveries=(), maintenance_id=None):
    checks = {
        'backend_jobs': ('queued', 'running', 'waiting'),
        'provider_jobs': ('queued', 'running'),
        'production_attempts': ('launching', 'running', 'cancelling'),
        'orchestrator_chats': ('queued', 'sending', 'running', 'processing'),
        'production_plans': ('queued', 'planning'),
        'task_routes': ('queued', 'opening', 'submitting'),
        'browser_jobs': ('queued', 'submitting', 'running'),
        'internal_jobs': ('queued', 'running'),
        'task_creations': ('queued', 'connecting', 'creating', 'created_pending', 'naming', 'opening', 'submitting'),
        'relay_delivery_effects': ('submitting',),
        'media_outbox': ('sending',), 'messages_delivery': ('sending',),
        'outbox_parts': ('sending',),
        'desktop_commands': ('queued', 'submitting', 'sending', 'processing'),
    }
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_install_maintenance'").fetchone():
            for ident, raw in db.execute('SELECT id,record FROM relay_install_maintenance'):
                if json.loads(raw)['phase'] != 'released' and ident != maintenance_id:
                    raise RuntimeError('Earlier maintenance remains held; inspect its journal before continuing.')
        for table, states in checks.items():
            if table == 'relay_delivery_effects' and deliveries:
                if pending_deliveries() != deliveries:
                    raise RuntimeError('Delivery intents changed after preparation.')
                continue
            cols = [r[1] for r in db.execute('PRAGMA table_info(' + table + ')')]
            col = 'state' if table == 'production_attempts' else 'status'
            if col not in cols:
                continue
            count = db.execute('SELECT count(*) FROM ' + table + ' WHERE ' + col
                               + ' IN (' + ','.join('?' for _ in states) + ')', states).fetchone()[0]
            if count:
                raise RuntimeError('Active or queued work in ' + table + '; app preserved.')

def main():
    global CANDIDATE, INSTALLED, HERE, DATA, DB, MANIFEST, RECEIPT
    if not __debug__:
        raise RuntimeError('Local installation checks require Python without optimization.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path, help='New private recovery directory')
    parser.add_argument('--apply', type=Path, help='Prepared manifest')
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--installed', type=Path, default=Path('/Applications/Task Relay.app'))
    parser.add_argument('--hold-uncertain-deliveries', action='store_true',
                        help='Bind pending delivery intents for quarantine after verified sender shutdown')
    parser.add_argument('--retire', type=Path, action='append', default=[])
    args = parser.parse_args()
    if bool(args.prepare) == bool(args.apply):
        parser.error('Choose --prepare or --apply.')
    os.umask(0o077)
    if args.prepare:
        if not args.candidate: parser.error('--candidate is required for preparation.')
        CANDIDATE, INSTALLED, HERE = args.candidate.absolute(), args.installed.absolute(), args.prepare.absolute()
        if HERE.exists(): raise ValueError('Use a new recovery directory.')
        versions = check_versions(CANDIDATE, INSTALLED)
        specs = [plistlib.loads(p.read_bytes()) for p in PLISTS]
        runtime = INSTALLED / 'Contents/Resources/resources/runtime'
        for index, spec in enumerate(specs):
            if PLISTS[index].is_symlink() or spec['Label'] != LABELS[index]:
                raise ValueError('Unexpected service definition.')
            allowed = ('task-relay-desktop-v1',) if index == 0 else ('task-relay-companion-messages-v1', 'task-relay-app-messages-v2')
            if spec.get('TaskRelayDesktopOwner') not in allowed:
                raise ValueError('Only existing app-owned services can be updated.')
        expected_args = [[str(runtime / 'python/bin/python3'), str(runtime / 'app/bridge.py'), 'run'],
                         [str(runtime / 'helpers/Messages Relay.app/Contents/MacOS/MessagesRelay')]]
        package_args = [str(runtime / 'python/bin/python3'), '-m', 'task_relay.bridge', 'run']
        if specs[0]['ProgramArguments'] not in (expected_args[0], package_args): raise ValueError('Unknown Telegram execution path.')
        if specs[0].get('WorkingDirectory') != str(runtime / 'app'): raise ValueError('Unknown Telegram working directory.')
        if specs[1]['ProgramArguments'] not in (expected_args[1], [str(INSTALLED / 'Contents/MacOS/task-relay-desktop'), '--messages-service']):
            raise ValueError('Unknown Messages execution path.')
        bindings = ('TASK_RELAY_DATA_DIR', 'TASK_RELAY_WORKSPACE_DIR', 'TASK_RELAY_GENERATED_DIR')
        if any(specs[0]['EnvironmentVariables'].get(key) != specs[1]['EnvironmentVariables'].get(key) for key in bindings):
            raise ValueError('Services use different data bindings.')
        DATA = Path(specs[0]['EnvironmentVariables']['TASK_RELAY_DATA_DIR'])
        if not DATA.is_absolute(): raise ValueError('Absolute data binding required.')
        DB = DATA / 'state.sqlite'
        deliveries = pending_deliveries() if args.hold_uncertain_deliveries else []
        idle(deliveries)
        updated = specs[1]
        updated['TaskRelayDesktopOwner'] = 'task-relay-app-messages-v2'
        updated['ProgramArguments'] = [str(INSTALLED / 'Contents/MacOS/task-relay-desktop'), '--messages-service']
        updated['AssociatedBundleIdentifiers'] = ['com.taskrelay.desktop']
        updated['EnvironmentVariables']['TASK_RELAY_MESSAGES_OWNER'] = 'task-relay-app'
        updated_telegram = dict(specs[0], ProgramArguments=package_args,
                                AssociatedBundleIdentifiers=['com.taskrelay.desktop'],
                                LimitLoadToSessionType='Aqua')
        retired = []
        for path in args.retire:
            path = path.absolute()
            if path.parent != INSTALLED.parent or not path.name.startswith('.Task Relay.backup-') or path.suffix != '.app':
                raise ValueError('Only explicitly named old Task Relay backup apps can be retired.')
            retired.append({'path': str(path), 'digest': digest(path)})
        HERE.mkdir(parents=True, mode=0o700)
        MANIFEST = HERE / 'install-manifest.json'
        write(MANIFEST, {**versions, 'delivery_quarantine': deliveries, 'candidate': str(CANDIDATE), 'installed': str(INSTALLED), 'data': str(DATA),
                        'candidate_digest': digest(CANDIDATE), 'installed_digest': digest(INSTALLED),
                        'installed_inode': INSTALLED.stat().st_ino, 'retire': retired,
                        'updated_messages_spec': updated,
                        'updated_telegram_spec': updated_telegram,
                        'plist_hashes': [hashlib.sha256(p.read_bytes()).hexdigest() for p in PLISTS]})
        print('Prepared fixed app and service identities; no installed changes. Manifest: ' + str(MANIFEST))
        return
    MANIFEST = args.apply.absolute(); HERE = MANIFEST.parent
    expected = json.loads(MANIFEST.read_text())
    if 'updated_telegram_spec' not in expected:
        raise RuntimeError('Prepare a new installation manifest with package service commands; this older plan was preserved.')
    CANDIDATE, INSTALLED, DATA = [Path(expected[key]) for key in ('candidate', 'installed', 'data')]
    DB = DATA / 'state.sqlite'; RECEIPT = HERE / 'install-receipt.json'
    if RECEIPT.exists():
        raise RuntimeError('Installation receipt already exists; inspect it before any further action.')
    expected = json.loads(MANIFEST.read_text())
    assert digest(CANDIDATE) == expected['candidate_digest'], 'Candidate changed'
    assert digest(INSTALLED) == expected['installed_digest'], 'Installed app changed'
    check_versions(CANDIDATE, INSTALLED)
    for i, p in enumerate(PLISTS):
        assert not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == expected['plist_hashes'][i]
        spec = plistlib.loads(p.read_bytes())
        assert spec['Label'] == LABELS[i]
        assert spec['EnvironmentVariables']['TASK_RELAY_DATA_DIR'] == str(DATA)
        assert spec['ProgramArguments'][0].startswith(str(INSTALLED) + '/Contents/')
    run(['codesign', '--verify', '--deep', '--strict', str(CANDIDATE)])
    deliveries = expected.get('delivery_quarantine', [])
    idle(deliveries)
    ident = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    holding = INSTALLED.parent / ('.task-relay-update-' + ident)
    backup = HERE / 'previous-app.zip'
    assert INSTALLED.stat().st_ino == expected['installed_inode'], 'Installed root changed'
    for item in expected['retire']:
        assert digest(Path(item['path'])) == item['digest'], 'Backup app changed'
    old_loaded = {label: loaded(label) for label in LABELS}
    old_pids = app_pids()
    prior_messages=json.loads((DATA / 'messages-pilot/health.json').read_text())
    messages_was_healthy=prior_messages.get('status')=='running' and time.time()-prior_messages.get('updated_at',0)<20
    record = {'id': ident, 'phase': 'prepared', 'previous_loaded': old_loaded,
              'app_was_open': bool(old_pids), 'messages_was_healthy':messages_was_healthy, 'app_backup': str(backup), 'holding': str(holding),
              'candidate_digest': expected['candidate_digest'], 'started_at': time.time()}
    write(RECEIPT, record)
    record['backup_retention'] = maintain_backups(DATA, RECEIPT)
    write(RECEIPT, record)
    stopped = []
    replaced = False
    boot_started = False
    try:
        record['archive'] = archive_bundle(INSTALLED, backup)
        record['retired_archives'] = [archive_bundle(Path(item['path']), HERE / (Path(item['path']).stem + '.zip')) for item in expected['retire']]
        record['phase'] = 'archives_verified'; write(RECEIPT, record)
        idle(deliveries)
        if deliveries:
            before_pause = HERE / ('state-before-pause-' + ident + '.sqlite')
            with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(before_pause) as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            before_pause.chmod(0o600)
            record.update(pre_pause_backup=str(before_pause), pre_pause_backup_sha256=digest_file(before_pause))
            record['maintenance'] = maintenance_pause(ident, deliveries)
            write(RECEIPT, record)
        for pid in app_pids():
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while app_pids() and time.monotonic() < deadline:
            time.sleep(.2)
        assert not app_pids(), 'App did not exit cleanly'
        for label in reversed(LABELS):
            if old_loaded[label]:
                run(['launchctl', 'bootout', DOMAIN + '/' + label])
                stopped.append(label)
                deadline = time.monotonic() + 25
                while loaded(label) and time.monotonic() < deadline:
                    time.sleep(.3)
                assert not loaded(label), 'Service did not unload'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            remaining = sender_processes()
            if not remaining:
                break
            time.sleep(.3)
        assert not remaining, 'Owned runtime processes are still shutting down'
        require_stopped_senders()
        idle(deliveries, maintenance_id=ident)
        if deliveries:
            record['maintenance'] = quarantine_deliveries(ident)
            write(RECEIPT, record)
        idle(maintenance_id=ident)
        db_backup = HERE / ('state-before-' + ident + '.sqlite')
        with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(db_backup) as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        db_backup.chmod(0o600)
        for p in PLISTS:
            saved = HERE / (ident + '-' + p.name)
            saved.write_bytes(p.read_bytes()); saved.chmod(0o600)
        record.update(phase='backed_up', database_backup=str(db_backup),
                      database_backup_sha256=hashlib.sha256(db_backup.read_bytes()).hexdigest())
        write(RECEIPT, record)
        record['phase'] = 'replacing_contents'; write(RECEIPT, record)
        record['replacement'] = replace_contents(INSTALLED, CANDIDATE, holding)
        replaced = True
        for path, spec in zip(PLISTS, [expected['updated_telegram_spec'], expected['updated_messages_spec']]):
            temporary_plist = path.with_suffix('.plist.update')
            temporary_plist.write_bytes(plistlib.dumps(spec))
            temporary_plist.chmod(0o600)
            temporary_plist.replace(path)
        record['phase'] = 'installed'; write(RECEIPT, record)
        restarted = time.time()
        record['services_restart_at'] = restarted
        for label, p in zip(LABELS, PLISTS):
            if old_loaded[label]:
                boot_started = True
                run(['launchctl', 'bootstrap', DOMAIN, str(p)])
        record['phase'] = 'checking_health'; write(RECEIPT, record)
        deadline = time.monotonic() + 45
        healthy = False
        while time.monotonic() < deadline:
            health = {}
            if old_loaded[LABELS[0]]:
                with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
                    keys = ['health:desktop', 'health:desktop-plans', 'health:scan', 'health:production', 'health:orchestrator-chat']
                    if (DATA / 'config.json').exists(): keys.append('health:poll')
                    for key in keys:
                        row = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
                        health[key] = json.loads(row[0]).get('last_success', 0) if row else 0
            if old_loaded[LABELS[1]]:
                value = json.loads((DATA / 'messages-pilot/health.json').read_text())
                health['messages'] = value.get('updated_at', 0) if value.get('status') == 'running' or (not messages_was_healthy and value.get('status')=='needs_attention') else 0
                record['messages_health']=value
            healthy = all(t >= restarted and time.time() - t < 20 for t in health.values())
            healthy = healthy and all(not was or loaded(label) for label, was in old_loaded.items())
            if healthy:
                record['fresh_health'] = health
                break
            time.sleep(2)
        assert healthy, 'Services restarted but fresh health is not verified; inspect before recovery'
        if deliveries:
            record['maintenance'] = release_maintenance(ident)
            write(RECEIPT, record)
        if old_pids:
            run(['open', '-a', str(INSTALLED)])
            deadline = time.monotonic() + 10
            while not app_pids() and time.monotonic() < deadline:
                time.sleep(.3)
            assert app_pids(), 'Updated services healthy, app window startup not verified'
        record.update(phase='complete' if record.get('messages_health',{}).get('status')=='running' else 'installed_messages_permission_required', completed_at=time.time(), app_pids=app_pids())
        write(RECEIPT, record)
        finish_contents(holding)
        for archived in record['retired_archives']:
            retire_archived_bundle(Path(archived['source']), archived)
        record['runnable_backups_retired'] = True
        write(RECEIPT, record)
        record['backup_retention'] = maintain_backups(DATA, RECEIPT, prune=True)
        write(RECEIPT, record)
        print(json.dumps(record, indent=2))
    except BaseException as exc:
        record.update(phase='needs_inspection', error=str(exc))
        # Before new services run, restore the old executable without touching data.
        # After dispatch becomes possible, never restore an old database or replay jobs.
        if not boot_started:
            if replaced:
                restore_contents(INSTALLED, holding)
            for p in PLISTS:
                saved = HERE / (ident + '-' + p.name)
                if saved.is_file():
                    temporary = p.with_suffix('.plist.restore')
                    temporary.write_bytes(saved.read_bytes()); temporary.chmod(0o600); temporary.replace(p)
            for label, p in zip(LABELS, PLISTS):
                if label in stopped:
                    deadline = time.monotonic() + 25
                    while loaded(label) and time.monotonic() < deadline:
                        time.sleep(.3)
                    if not loaded(label):
                        restored = run(['launchctl', 'bootstrap', DOMAIN, str(p)], False)
                        record.setdefault('restore_results', {})[label] = restored.returncode
            if old_pids and not app_pids():
                run(['open', '-a', str(INSTALLED)], False)
            record['restored_before_new_service_start'] = True
        write(RECEIPT, record)
        raise

if __name__ == '__main__':
    main()
