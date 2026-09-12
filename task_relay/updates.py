"""Explicit release installation, guarded service activation and code rollback."""
import argparse
import base64
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import venv
import zipfile

from . import credentials, releases
from .filesystem import FILES, Grant
from .host import HOST
from .host_updates import Service
from .relay_paths import PATHS

SAFE_STATES = frozenset(('done', 'completed', 'failed', 'cancelled', 'canceled', 'rejected', 'accepted',
                        'resolved', 'sent', 'ignored', 'expired', 'disabled', 'idle', 'closed', 'handled',
                        'delivered', 'superseded', 'skipped', 'approved', 'consumed', 'succeeded', 'finished'))

# Saved buttons/key prompts are metadata, not running assignments. Their owning
# job/task tables remain authoritative for unfinished or uncertain execution.
METADATA_STATES = frozenset(('tool_requests', 'codex_approvals', 'provider_key_sessions',
    'provider_deletions', 'production_replacement_cards', 'production_selection_cards',
    'production_control_cards', 'orchestrator_guide_choices', 'orchestrator_proposals'))
TERMINAL_EXTRAS = {
    'incoming': {'submitted', 'attached', 'stopped', 'incomplete'},
    'incoming_files': {'attached'}, 'codex_inputs': {'ready', 'used', 'forgotten'},
    'production_uploads': {'ready', 'used', 'replaced'},
    'production_revisions': {'applied'}, 'production_continuations': {'registered'},
    'reference_packs': {'ready'}, 'production_plans': {'started', 'discarded', 'blocked'},
    'production_attempts': {'blocked'},
    'task_routes': {'submitted'}, 'workflow_dispatches': {'submitted'},
    'backend_jobs': {'stopped', 'incomplete'}, 'internal_jobs': {'stopped'},
}


def load(path):
    return credentials.private_json(path) if path.exists() or path.is_symlink() else None


@contextmanager
def lock(path, timeout=0):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    grant = Grant(path.parent, 'exclusive update coordination', writes=frozenset({path.name}))
    with FILES.parent(grant, path.name, write=True) as (parent, name):
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    with os.fdopen(fd, 'r+') as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                HOST.lock(stream)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError('An update or another relay process is still running; no switch was made.') from None
                time.sleep(.1)
        yield


def code_hash(install):
    root = Path(install)
    files = list(root.glob('*.py'))
    for package in ('task_relay', 'orchestrator'):
        files.extend(p for p in (root / package).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    digest = hashlib.sha256()
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError('Runtime contains linked files; automatic switching is unavailable.')
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


def current(paths=PATHS):
    return dict(python=sys.executable, install=str(paths.install), version=releases.VERSION,
                protocol=releases.PROTOCOL, code_hash=code_hash(paths.install))


def verify_target(target):
    if target['protocol'] != releases.PROTOCOL or not Path(target['python']).is_file():
        raise ValueError('This installation cannot be switched by this updater.')
    if code_hash(target['install']) != target['code_hash']:
        raise ValueError('Retained runtime files changed; automatic switching was refused.')


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != 'https' or url.hostname not in ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com') or url.username or url.password:
            raise ValueError('Unexpected release download redirect.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(release, path):
    req = urllib.request.Request(release['wheel_url'], headers={'User-Agent': 'Task-Relay-updater'})
    with releases.https_opener(AssetRedirect).open(req, timeout=30) as res:
        raw = res.read(100_000_001)
    if len(raw) != release['size'] or hashlib.sha256(raw).hexdigest() != release['sha256']:
        raise ValueError('Release download size or SHA-256 differs from GitHub metadata.')
    path.write_bytes(raw)


def validate_wheel(path, release):
    if hashlib.sha256(path.read_bytes()).hexdigest() != release['sha256']:
        raise ValueError('Wheel checksum mismatch.')
    import re
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        prefix = 'task_relay-' + release['version'] + '.dist-info/'
        if len(set(names)) != len(names) or sum(i.file_size for i in archive.infolist()) > 150_000_000:
            raise ValueError('Wheel contains duplicate or oversized content.')
        for name in names:
            if ('..' in Path(name).parts or name.startswith('/') or '\\' in name
                    or not (name.startswith(('task_relay/', 'orchestrator/', prefix)) or re.fullmatch(r'[a-z_][a-z0-9_]*\.py', name))):
                raise ValueError('Wheel has unsupported installation paths.')
        from email.parser import BytesParser
        metadata = BytesParser().parsebytes(archive.read(prefix + 'METADATA'))
        if metadata['Name'] != 'task-relay' or metadata['Version'] != release['version']:
            raise ValueError('Wheel package/version does not match the selected release.')
        if any('extra ==' not in dep for dep in metadata.get_all('Requires-Dist', [])):
            raise ValueError('This updater supports dependency-free core releases only.')


def prepare(release, paths=PATHS, downloader=download):
    root = paths.data.with_name(paths.data.name.lstrip('.') + '-releases')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = root / (release['version'] + '-' + release['sha256'][:16])
    receipt = folder / 'prepared.json'
    if receipt.exists():
        target = load(receipt)
        if target.get('wheel_sha256') != release['sha256']:
            raise ValueError('Prepared release identity differs; it was preserved.')
        verify_target(target)
        return target
    marker = folder / 'preparing.json'
    if folder.exists():
        if load(marker) != release:
            raise ValueError('Existing preparation directory is not owned by this release.')
    else:
        folder.mkdir(mode=0o700)
        credentials.save(marker, release)
    wheel = folder / release['filename']
    downloader(release, wheel)
    validate_wheel(wheel, release)
    environment = folder / 'venv'
    venv.EnvBuilder(with_pip=True).create(environment)
    python = str(environment / 'bin/python')
    subprocess.run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], check=True, timeout=60)
    code = ('import json; from task_relay.releases import VERSION,PROTOCOL; '
            'from task_relay.relay_paths import PATHS; '
            'print(json.dumps(dict(version=VERSION,protocol=PROTOCOL,install=str(PATHS.install))))')
    result = subprocess.run([python, '-I', '-c', code], capture_output=True, text=True, check=True,
                            env={**os.environ, **paths.environment()}, timeout=20)
    target = json.loads(result.stdout)
    if target['version'] != release['version'] or target['protocol'] != releases.PROTOCOL:
        raise ValueError('The installed release has an incompatible update protocol/version.')
    target.update(python=python, code_hash=code_hash(target['install']), wheel_sha256=release['sha256'])
    credentials.save(receipt, target)
    return target


def unfinished(db):
    blockers = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table in METADATA_STATES:
            continue
        if table == 'workflows':
            for (raw,) in db.execute('SELECT data FROM workflows'):
                if json.loads(raw).get('status') not in SAFE_STATES | {'stopped'}:
                    blockers[table] = blockers.get(table, 0) + 1
        quoted = '"' + table.replace('"', '""') + '"'
        columns = {r[1] for r in db.execute('PRAGMA table_info(' + quoted + ')')}
        if table in ('outbox', 'outbox_parts'):
            count = db.execute('SELECT count(*) FROM ' + quoted + ' WHERE sent=0').fetchone()[0]
            if count:
                blockers[table] = count
        for column in ('status', 'state'):
            if column in columns:
                terminal = SAFE_STATES | TERMINAL_EXTRAS.get(table, set())
                placeholders = ','.join('?' for _ in terminal)
                inactive_parent = (" AND run NOT IN (SELECT id FROM production_runs WHERE status IN ('completed','cancelled','failed'))"
                                   if table == 'production_tasks' else '')
                count = db.execute(f'SELECT count(*) FROM {quoted} WHERE ( "{column}" IS NULL OR "{column}" NOT IN ({placeholders})){inactive_parent}', tuple(terminal)).fetchone()[0]
                if count:
                    blockers[table] = count
    return blockers


def content(db):
    return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()


def compatible(target, snapshot, paths):
    # Run initialization only on a disposable snapshot. Exact logical contents must survive.
    test = snapshot.with_name('probe.sqlite')
    source = sqlite3.connect(snapshot)
    dest = sqlite3.connect(test)
    source.backup(dest)
    before = content(dest)
    dest.close(); source.close()
    probe_data = test.parent / 'probe-data'
    probe_data.mkdir(exist_ok=True)
    code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
            'from task_relay.bridge import State; s=State(Path(sys.argv[2])); s.db.close()')
    env = {**os.environ, **paths.environment(), 'TASK_RELAY_DATA_DIR': str(probe_data)}
    result = subprocess.run([target['python'], '-I', '-c', code, target['install'], str(test)],
                            env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Candidate cannot reopen the snapshot; live data was preserved.')
    check = sqlite3.connect(test)
    try:
        if before != content(check):
            raise ValueError('This release changes stored data/schema. An explicit migration is required; live data was preserved.')
    finally:
        check.close()


def wait_ready(record, paths, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = load(paths.data / 'updates' / 'ready.json')
        if ready and ready.get('nonce') == record['nonce'] and ready.get('install') == record['target']['install']:
            try:
                os.kill(ready['pid'], 0)
                return
            except ProcessLookupError:
                pass
        time.sleep(.1)
    raise ValueError('Candidate did not report startup readiness; provider workers remain gated.')


def activation_path(paths):
    return paths.data / 'updates' / 'activation.json'


def restore(record, service, paths, waiter=wait_ready):
    candidate = base64.b64decode(record['candidate']) if record['candidate'] else None
    service.verify(record['service'], candidate)
    service.stop(record['service'])
    verify_target(record['previous'])
    # Preserve the interrupted transaction separately before returning to its previous code.
    credentials.save(paths.data / 'updates' / ('failed-' + record['nonce'] + '.json'), record)
    old = base64.b64decode(record['service']['raw']) if record['service']['raw'] else None
    service.write(old)
    restored = dict(record, target=record['previous'], previous=record.get('fallback_previous', record['previous']), nonce=secrets.token_hex(16), phase='starting')
    credentials.save(activation_path(paths), restored)
    service.start(record['service'])
    if record['service']['active']:
        waiter(restored, paths)
    restored['phase'] = 'active'
    credentials.save(activation_path(paths), restored)
    return restored


def activate(target, paths=PATHS, service_factory=Service, waiter=wait_ready):
    HOST.require_posix('Release activation')
    path = activation_path(paths)
    with lock(path.parent / 'update.lock'):
        record = load(path)
        if record and record['phase'] != 'active':
            raise ValueError('An earlier switch is incomplete. Run task-relay update recover first.')
        if record and record['bindings'] != paths.environment():
            raise ValueError('Use the original data/project/output bindings; changing paths requires explicit migration.')
        if paths.state.exists():
            preflight = sqlite3.connect(paths.state.as_uri() + '?mode=ro', uri=True)
            try:
                blocked = unfinished(preflight)
                if blocked:
                    raise ValueError('Unfinished or uncertain records block switching: ' + ', '.join(sorted(blocked)))
            finally:
                preflight.close()
        previous = record['target'] if record else current(paths)
        verify_target(previous); verify_target(target)
        if previous == target:
            return record
        service = service_factory(paths, previous['install'])
        prior = service.capture()
        candidate = service.candidate(prior, target)
        # A separate Messages deployment has its own lifecycle and is not switched here.
        if (paths.data / 'messages-pilot').exists():
            raise ValueError('This updater supports Telegram-only installations; the separate Messages deployment was preserved.')
        receipt = dict(phase='prepared', nonce=secrets.token_hex(16), previous=previous, target=target,
                       fallback_previous=record['previous'] if record else previous,
                       service=prior, candidate=base64.b64encode(candidate).decode() if candidate else None,
                       bindings=paths.environment())
        credentials.save(path, receipt)
        commit_started = False
        try:
            service.verify(prior, candidate)
            receipt['phase'] = 'stopping'; credentials.save(path, receipt)
            service.stop(prior)
            with ExitStack() as stack:
                stack.enter_context(lock(paths.data / 'bridge.lock', timeout=30))
                stack.enter_context(lock(paths.data / 'setup.lock'))
                if paths.state.exists():
                    db = sqlite3.connect(paths.state, timeout=5)
                    stack.callback(db.close)
                    db.execute('BEGIN IMMEDIATE')
                    blocked = unfinished(db)
                    if blocked:
                        raise ValueError('Unfinished or uncertain records block switching: ' + ', '.join(sorted(blocked)))
                    backup_dir = path.parent / ('backup-' + receipt['nonce'])
                    backup_dir.mkdir(mode=0o700)
                    backup = backup_dir / 'state.sqlite'
                    source = sqlite3.connect(paths.state)
                    dest = sqlite3.connect(backup)
                    try:
                        source.backup(dest)
                    finally:
                        source.close(); dest.close()
                    os.chmod(backup, 0o600)
                    compatible(target, backup, paths)
                    receipt['backup'] = str(backup)
                service.verify(prior, candidate)
                service.write(candidate)
                receipt['phase'] = 'starting'; credentials.save(path, receipt)
            # Starting process reports readiness while update_gate holds provider workers.
            service.start(prior)
            if prior['active']:
                waiter(receipt, paths)
            credentials.save(path.parent / ('validated-' + receipt['nonce'] + '.json'), dict(receipt, phase='validated'))
            receipt['phase'] = 'active'
            commit_started = True
            credentials.save(path, receipt)
            return receipt
        except BaseException:
            if commit_started:
                raise RuntimeError('Activation commit may have completed. Inspect update status; no automatic rollback was attempted after the commit boundary.') from None
            try:
                restore(receipt, service, paths, waiter)
            except Exception:
                receipt['phase'] = 'recovery_required'
                credentials.save(path, receipt)
                raise RuntimeError('Activation and recovery are incomplete. Run task-relay update recover; stored task data was not restored or discarded.') from None
            raise


def recover(paths=PATHS):
    with lock(activation_path(paths).parent / 'update.lock'):
        record = load(activation_path(paths))
        if not record or record['phase'] == 'active':
            raise ValueError('There is no incomplete activation to recover.')
        if record['bindings'] != paths.environment():
            raise ValueError('Recovery requires the original data/project/output bindings.')
        return restore(record, Service(paths, record['previous']['install']), paths)


def redirect(argv):
    # Installed launchers continue to work after a switch; update commands retain the controller.
    from .relay_paths import CHECKOUT
    if CHECKOUT or (argv and argv[0] == 'update'):
        return
    record = load(activation_path(PATHS))
    if record and record['bindings'] != PATHS.environment():
        raise RuntimeError('Selected release uses different path bindings. Inspect task-relay update status before changing data roots.')
    if record and record['phase'] != 'active':
        raise RuntimeError('Release activation is incomplete. Run task-relay update recover.')
    if record and record['phase'] == 'active' and record['target']['install'] != str(PATHS.install):
        verify_target(record['target'])
        os.execve(record['target']['python'], [record['target']['python'], '-m', 'task_relay', *argv],
                  {**os.environ, **record['bindings']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('check', help='Fetch stable release metadata without downloading code')
    sub.add_parser('status', help='Read cached metadata and activation state')
    apply = sub.add_parser('apply', help='Download and activate one explicit stable release')
    apply.add_argument('--version', required=True)
    sub.add_parser('rollback', help='Switch to retained previous code without restoring old data')
    sub.add_parser('recover', help='Recover an interrupted service activation')
    prefs = sub.add_parser('notifications', help='Control daily checks and Telegram notices')
    prefs.add_argument('mode', choices=('on', 'off'))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command != 'status':
            HOST.require_posix('Release update/check operations')
        if args.command in (None, 'check'):
            store = releases.Store()
            try:
                store.check(force=True)
                print(json.dumps(releases.cached(), indent=2))
            finally:
                store.close()
        elif args.command == 'status':
            record = load(activation_path(PATHS))
            public = ({'phase': record['phase'], 'current_version': record['target']['version'],
                       'previous_version': record['previous']['version']} if record else None)
            print(json.dumps(dict(cache=releases.cached(), activation=public,
                                  notifications=releases.preferences()['notifications']), indent=2))
        elif args.command == 'notifications':
            credentials.save(PATHS.data / 'update-preferences.json', {'notifications': args.mode == 'on'})
            print('Release checks and notifications ' + args.mode + '.')
        elif args.command == 'apply':
            release = releases.fetch(args.version)
            if not release:
                raise ValueError('That stable release is not published.')
            record = load(activation_path(PATHS))
            existing = record['target']['version'] if record and record['phase'] == 'active' else releases.VERSION
            if releases.version(release['version']) <= releases.version(existing):
                raise ValueError('Choose a newer release; use rollback for retained previous code.')
            # Serialize preparation too, independently of activation's service lock.
            with lock(PATHS.data / 'updates' / 'prepare.lock'):
                target = prepare(release)
            result = activate(target)
            print('Selected Task Relay ' + result['target']['version'] + '. Previous code retained; task history preserved.')
        elif args.command == 'rollback':
            record = load(activation_path(PATHS))
            if not record or record['phase'] != 'active':
                raise ValueError('No completed update is available to roll back.')
            result = activate(record['previous'])
            print('Selected previous code ' + result['target']['version'] + '; current task data retained.')
        elif args.command == 'recover':
            recover()
            print('Previous service selection recovered; current task data retained.')
    except (Exception, KeyboardInterrupt) as exc:
        # Never print URL-bearing transport exceptions, which may contain signed asset URLs.
        print(str(exc) if type(exc) in (ValueError, RuntimeError) else 'Update stopped (' + type(exc).__name__ + '). Use update status; recover if activation is incomplete.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
