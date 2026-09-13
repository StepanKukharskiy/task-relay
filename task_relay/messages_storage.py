"""Messages tables and an offline, backed-up migration to Relay's one database."""
from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from task_relay.host import HOST

MIGRATION = 'messages-shared-state-v1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS messages_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages_commands(guid TEXT PRIMARY KEY,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages_delivery(id TEXT PRIMARY KEY,text TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages_provider_requests(
    guid TEXT PRIMARY KEY,update_id INTEGER UNIQUE NOT NULL,job_id TEXT NOT NULL);
'''
# Only provider-owned records with explicit keys are portable. Unknown populated
# tables stop migration rather than disappearing or importing unrelated state.
PROVIDER_TABLES = {
    'watched', 'watch_checkpoints', 'outbox', 'outbox_parts', 'incoming',
    'media_outbox', 'backend_tasks', 'backend_jobs', 'tool_requests', 'speech_tasks',
    'gemini_runs', 'gemini_models', 'artifacts', 'gemini_history', 'incoming_files',
    'gemini_tool_runs', 'api_runs', 'api_history', 'api_tool_calls', 'api_steps',
}


def initialize(db):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            db.execute(statement)


def receipt(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='storage_migrations'").fetchone():
        return None
    row = db.execute('SELECT evidence FROM storage_migrations WHERE id=?', (MIGRATION,)).fetchone()
    return json.loads(row[0]) if row else None


def require_consolidated(target, folder):
    legacy = [Path(folder) / name for name in ('state.sqlite', 'providers.sqlite')]
    if not any(p.exists() for p in legacy):
        return
    # Never silently open an empty replacement or run two independent workers.
    raise ValueError('Messages databases need offline consolidation. Stop both Relay services and run '
                     'task-relay storage consolidate-messages, then restart them. Existing records are preserved.')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def digest(db):
    """Fingerprint committed logical content, independent of WAL layout."""
    h = hashlib.sha256()
    for table in tables(db):
        h.update(table.encode())
        h.update(db.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0].encode())
        for row in db.execute('SELECT * FROM ' + quote(table) + ' ORDER BY rowid'):
            h.update(repr(tuple(row)).encode())
    return h.hexdigest()


def snapshot(path, destination):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(destination)) as backup:
            src.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup integrity check failed; migration was not applied.')
            checksum = digest(backup)
    destination.chmod(0o600)
    return {'source': str(path), 'backup': str(destination), 'digest': checksum}


def insert(db, table, columns, values):
    # No REPLACE/IGNORE: conflicting identities must roll back the entire import.
    db.execute('INSERT INTO ' + quote(table) + '(' + ','.join(map(quote, columns)) + ') VALUES ('
               + ','.join('?' for _ in columns) + ')', values)


def copy_table(db, src, source, target=None):
    target = target or source
    columns = [r[1] for r in src.execute('PRAGMA table_info(' + quote(source) + ')')]
    count = 0
    for row in src.execute('SELECT * FROM ' + quote(source) + ' ORDER BY rowid'):
        insert(db, target, columns, row)
        count += 1
    return count


def idle(db):
    # Queued/uncertain records can be moved unchanged. Processes holding the
    # service locks or an unfinished external operation cannot be migrated.
    checks = {
        'backend_jobs': ('running', 'waiting'), 'provider_jobs': ('running',),
        'production_attempts': ('launching', 'running', 'cancelling'),
        'orchestrator_chats': ('sending',), 'production_plans': ('planning',),
        'task_routes': ('opening', 'submitting'), 'browser_jobs': ('submitting',),
        'media_outbox': ('sending',),
    }
    existing = tables(db)
    for table, statuses in checks.items():
        column = 'state' if table == 'production_attempts' else 'status'
        if table in existing and db.execute('SELECT 1 FROM ' + quote(table) + ' WHERE ' + column + ' IN ('
                                            + ','.join('?' for _ in statuses) + ') LIMIT 1', statuses).fetchone():
            raise ValueError(f'{table} has in-flight work. Stop or resolve it before consolidation; nothing was replayed.')


def import_provider(state, src, source_path, target, evidence):
    db = state.db
    special = {'kv', 'message_requests', 'task_emojis', 'relay_request_channels',
               'relay_event_channels', 'relay_channel_bindings'}
    populated = [t for t in tables(src) if src.execute('SELECT 1 FROM ' + quote(t) + ' LIMIT 1').fetchone()]
    unknown = set(populated) - PROVIDER_TABLES - special
    if unknown:
        raise ValueError('Unsupported populated provider tables: ' + ', '.join(sorted(unknown)))
    after = db.execute('SELECT COALESCE(max(rowid),0) FROM outbox').fetchone()[0]
    for table in populated:
        if table in PROVIDER_TABLES:
            evidence['rows']['provider:' + table] = copy_table(db, src, table)
    if 'message_requests' in populated:
        evidence['rows']['provider:message_requests'] = copy_table(db, src, 'message_requests', 'messages_provider_requests')
    if 'kv' in populated:
        for key, value in src.execute('SELECT key,value FROM kv'):
            mapped = (key if key.startswith(('messages:', 'gemini-reply-capability:')) else
                      'messages:' + key if key in ('selected', 'orchestrator_mode') else 'messages:legacy:' + key)
            old = db.execute('SELECT value FROM kv WHERE key=?', (mapped,)).fetchone()
            if old and old[0] != value:
                raise ValueError('Conflicting shared setting: ' + mapped)
            if not old:
                insert(db, 'kv', ['key', 'value'], [mapped, value])
    if 'task_emojis' in populated:
        for row in src.execute('SELECT * FROM task_emojis'):
            if db.execute('SELECT 1 FROM task_emojis WHERE emoji_key=?', (row['emoji_key'],)).fetchone():
                if row['custom']:
                    raise ValueError('A custom task emoji conflicts; resolve that choice before consolidation.')
                new = state.emoji(row['thread_id'])
                evidence['emoji_changes'].append({'task': row['thread_id'], 'previous': row['emoji'], 'current': new})
            else:
                insert(db, 'task_emojis', row.keys(), tuple(row))
    # Explicit ownership covers historical notices without a task ID, too. Row
    # offsets in the old database cannot be reused in the merged outbox.
    for row in src.execute('SELECT id FROM outbox'):
        insert(db, 'relay_event_channels', ['event_id', 'channel'], [row[0], 'messages'])
    for row in src.execute('SELECT id FROM incoming'):
        insert(db, 'relay_request_channels', ['request_id', 'channel'], [row[0], 'messages'])
    for row in src.execute('SELECT id FROM backend_tasks'):
        insert(db, 'relay_channel_bindings', ['kind', 'entity', 'after_row', 'channel'], ['task', row[0], after, 'messages'])
    # Keep the existing usage amounts but adopt their new source identity so the
    # next normal refresh updates each receipt instead of counting it twice.
    prefix = lambda p: 'relay:' + hashlib.sha256(str(p).encode()).hexdigest()[:16] + ':'
    aliases = {str(source_path)}
    for row in db.execute('SELECT source FROM usage_health').fetchall():
        if Path(row[0]).is_absolute() and Path(row[0]).resolve() == source_path:
            aliases.add(row[0])
    for alias in aliases:
        old_prefix, new_prefix = prefix(alias), prefix(target)
        for row in db.execute('SELECT id FROM usage_events WHERE substr(id,1,?)=?', (len(old_prefix), old_prefix)).fetchall():
            new = new_prefix + row[0][len(old_prefix):]
            db.execute('UPDATE usage_events SET id=? WHERE id=?', (new, row[0]))
            evidence['usage_ids_rebound'] += 1
        db.execute('DELETE FROM usage_health WHERE source=?', (alias,))


def archive_sources(evidence):
    # Runs only after the merged records and receipt commit. On interruption the
    # next call resumes retirement; it never reimports already migrated rows.
    for entry in evidence['sources']:
        path = Path(entry['source'])
        if not path.exists():
            continue
        readonly = not path.stat().st_mode & 0o200
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) if readonly else sqlite3.connect(path)
        with closing(connection) as db:
            if digest(db) != entry['digest']:
                raise ValueError('A legacy database changed after consolidation; it was preserved for manual review.')
            if readonly:
                wal = Path(str(path) + '-wal')
                if wal.exists() and wal.stat().st_size:
                    raise ValueError('Read-only legacy database has an uncheckpointed WAL; its verified backup is retained.')
            else:
                result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if result and result[0]:
                    raise ValueError('Legacy database is still in use; retirement is pending.')
        destination = Path(entry['backup']).with_suffix('.retired.sqlite')
        if destination.exists():
            raise ValueError('Retirement destination already exists; source was preserved.')
        path.replace(destination)
        for suffix in ('-wal', '-shm'):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                sidecar.replace(Path(str(destination) + suffix))


def consolidate(target, folder):
    from task_relay.bridge import State
    from orchestrator.storage import transaction
    usage_target = Path(target).absolute()
    target, folder = Path(target).resolve(), Path(folder).resolve()
    if target in (folder / 'state.sqlite', folder / 'providers.sqlite'):
        raise ValueError('Main and legacy database paths must be different.')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ExitStack() as stack:
        for path in (target.parent / 'bridge.lock', folder / 'pilot.lock'):
            lock = stack.enter_context(path.open('a'))
            try:
                HOST.lock(lock)
            except BlockingIOError:
                raise ValueError('Stop both Relay services before consolidating their databases.') from None
        if target.exists():
            with closing(sqlite3.connect(target)) as db:
                old = receipt(db)
                if old:
                    archive_sources(old)
                    return old
                idle(db)
        paths = [folder / name for name in ('state.sqlite', 'providers.sqlite') if (folder / name).exists()]
        for path in paths:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                idle(db)
        backup_dir = target.parent / 'backups' / ('messages-consolidation-' + uuid.uuid4().hex)
        backup_dir.mkdir(parents=True, mode=0o700)
        evidence = {'migration': MIGRATION, 'created': time.time(), 'target': str(target),
                    'sources': [], 'rows': {}, 'emoji_changes': [], 'usage_ids_rebound': 0,
                    'main_backup': snapshot(target, backup_dir / 'main.sqlite') if target.exists() else None}
        for path in paths:
            evidence['sources'].append(snapshot(path, backup_dir / ('messages-' + path.name)))
        # The earlier production migration already preserved its source. Retire
        # that inactive copy too, only when its committed migration is verified.
        runtime = target.parent / 'orchestrator/runtime.sqlite'
        if runtime.exists():
            with closing(sqlite3.connect(target)) as db:
                if not db.execute("SELECT 1 FROM storage_migrations WHERE id='production-runtime-v1'").fetchone():
                    raise ValueError('The older production database must be migrated first.')
            evidence['sources'].append(snapshot(runtime, backup_dir / 'legacy-runtime.sqlite'))
        state = State(target)
        stack.callback(state.db.close)
        state.db.commit()
        with transaction(state.db):
            for entry in evidence['sources']:
                path = Path(entry['source'])
                with closing(sqlite3.connect(Path(entry['backup']).as_uri() + '?mode=ro', uri=True)) as src:
                    src.row_factory = sqlite3.Row
                    if path == folder / 'state.sqlite':
                        unknown = set(tables(src)) - {'settings', 'commands', 'delivery'}
                        if any(src.execute('SELECT 1 FROM ' + quote(t) + ' LIMIT 1').fetchone() for t in unknown):
                            raise ValueError('Unknown populated Messages transport tables; source preserved.')
                        for table in ('settings', 'commands', 'delivery'):
                            evidence['rows']['transport:' + table] = copy_table(state.db, src, table, 'messages_' + table)
                    elif path == folder / 'providers.sqlite':
                        import_provider(state, src, path, usage_target, evidence)
            state.db.execute('INSERT INTO storage_migrations VALUES (?,?,?)', (MIGRATION, time.time(), json.dumps(evidence)))
            if state.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Merged database integrity check failed.')
        archive_sources(evidence)
        return evidence


def main():
    import argparse
    from task_relay.relay_paths import PATHS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['consolidate-messages'])
    parser.parse_args()
    try:
        print(json.dumps(consolidate(PATHS.state, PATHS.messages), indent=2))
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
