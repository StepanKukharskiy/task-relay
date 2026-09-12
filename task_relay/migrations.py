"""Reviewed additive SQLite migrations with atomic, retained reversal receipts."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

JOURNAL = 'relay_update_migrations'
JOURNAL_SQL = ('CREATE TABLE relay_update_migrations('
               'event TEXT PRIMARY KEY, plan TEXT NOT NULL, direction TEXT NOT NULL, evidence TEXT NOT NULL)')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def tokens(sql):
    # Preserve quoted literals/identifiers exactly; normalize only whitespace and
    # unquoted SQL case. Unsupported spellings are refused, never guessed equivalent.
    return re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`[^`]*`|\[[^\]]*\]|[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[^\s]", sql)


def canonical(sql):
    return [s if s[0] in "'\"`[" else s.upper() for s in tokens(sql)]


def objects(db):
    return {r[1]: {'kind': r[0], 'table': r[2], 'sql': r[3]} for r in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")
        if r[2] != JOURNAL}


def schema(db):
    return {k: {**v, 'sql': canonical(v['sql'])} for k, v in sorted(objects(db).items())}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fingerprint(db):
    """Schema and typed rows, including row identities and SQLite sequence state."""
    metadata = {name: db.execute('PRAGMA ' + name).fetchone()[0] for name in ('user_version', 'application_id')}
    h = hashlib.sha256(json.dumps({'schema': schema(db), 'metadata': metadata}, sort_keys=True).encode())
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for name in names:
        h.update(name.encode())
        # Stable rowid order preserves delivery offsets; WITHOUT ROWID tables use
        # all columns for a deterministic logical comparison.
        info = list(db.execute('PRAGMA table_xinfo(' + quote(name) + ')'))
        cols = {r[1].lower() for r in info}
        alias = next((v for v in ('rowid', '_rowid_', 'oid') if v not in cols), None)
        sql = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
        without = 'WITHOUT ROWID' in sql.upper()
        if not without and alias is None:
            raise ValueError('A table hides every row identity; migration is unsupported.')
        projection = '*' if without else quote(alias) + ',*'
        order = ','.join(str(i + 1) for i in range(len(info))) if without else quote(alias)
        for row in db.execute('SELECT ' + projection + ' FROM ' + quote(name) + ' ORDER BY ' + order):
            raw = repr(tuple(row)).encode()
            h.update(len(raw).to_bytes(8, 'big') + raw)
    return h.hexdigest()


def check(db):
    if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (JOURNAL,)).fetchone():
        journal(db)
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Database integrity or foreign-key check failed; migration refused.')


def execute(db, statements):
    for statement in statements:
        db.execute(statement)


def derive(before, after):
    """Infer a deliberately narrow plan, then prove it reproduces initialization."""
    old, new = objects(before), objects(after)
    if set(old) - set(new):
        raise ValueError('Destructive schema changes require a separately implemented migration.')
    forward, backward, additions = [], [], []
    for name, obj in old.items():
        changed = new[name]
        if obj == changed:
            continue
        if obj['kind'] != 'table' or changed['kind'] != 'table':
            raise ValueError('Replacing existing schema objects is unsupported.')
        a = list(before.execute('PRAGMA table_xinfo(' + quote(name) + ')'))
        b = list(after.execute('PRAGMA table_xinfo(' + quote(name) + ')'))
        if a != b[:len(a)] or len(b) <= len(a):
            raise ValueError('Changing existing columns is unsupported.')
        for col in b[len(a):]:
            _, column, kind, required, default, primary, hidden = col
            if (required or default is not None or primary or hidden or
                    not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', column) or
                    kind.upper() not in ('', 'TEXT', 'INTEGER', 'REAL', 'BLOB', 'NUMERIC')):
                raise ValueError('Only ordinary nullable columns without defaults can be migrated.')
            forward.append('ALTER TABLE ' + quote(name) + ' ADD COLUMN ' + column + (' ' + kind if kind else ''))
            backward.insert(0, 'ALTER TABLE ' + quote(name) + ' DROP COLUMN ' + quote(column))
            additions.append({'table': name, 'column': column})
    added = set(new) - set(old)
    for name in sorted(added, key=lambda n: (new[n]['kind'] != 'table', n)):
        obj = new[name]
        if obj['kind'] not in ('table', 'index') or (obj['kind'] == 'index' and obj['table'] not in added):
            raise ValueError('Only new ordinary tables and their indexes are supported.')
        if obj['kind'] == 'table':
            if re.search(r'\b(VIRTUAL|AUTOINCREMENT)\b', obj['sql'], re.I):
                raise ValueError('Virtual or auto-increment tables require a separate migration.')
            additions.append({'table': name})
        forward.append(obj['sql'])
        backward.insert(0, 'DROP ' + obj['kind'].upper() + ' ' + quote(name))
    if not forward:
        raise ValueError('No additive schema migration was found; use the ordinary update command.')
    with closing(sqlite3.connect(':memory:')) as trial:
        before.backup(trial)
        with trial:
            execute(trial, forward)
            check(trial)
        if fingerprint(trial) != fingerprint(after):
            raise ValueError('Initialization changes existing data or unsupported schema; no migration was authorized.')
        with trial:
            execute(trial, backward)
            check(trial)
        if fingerprint(trial) != fingerprint(before):
            raise ValueError('The proposed migration is not exactly reversible.')
    return {'before': schema(before), 'after': schema(after), 'forward': forward,
            'backward': backward, 'additions': additions}


def require_unused(db, plan):
    for entry in plan['additions']:
        query = 'SELECT 1 FROM ' + quote(entry['table'])
        if 'column' in entry:
            query += ' WHERE ' + quote(entry['column']) + ' IS NOT NULL'
        if db.execute(query + ' LIMIT 1').fetchone():
            raise ValueError('Reversal would discard newer data in ' + entry['table'] + '; current code and data were preserved.')


def journal(db):
    obj = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (JOURNAL,)).fetchone()
    if obj is None:
        db.execute(JOURNAL_SQL)
    elif canonical(obj[0]) != canonical(JOURNAL_SQL):
        raise ValueError('Migration receipt table has an unknown schema.')
    if db.execute('SELECT 1 FROM sqlite_master WHERE tbl_name=? AND name!=? AND sql IS NOT NULL', (JOURNAL, JOURNAL)).fetchone():
        raise ValueError('Migration receipt table has unrecognized indexes or triggers.')


def applied(db, event):
    if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (JOURNAL,)).fetchone():
        return None
    journal(db)
    row = db.execute('SELECT plan,direction,evidence FROM ' + JOURNAL + ' WHERE event=?', (event,)).fetchone()
    return tuple(row) if row else None


def transform(db, plan, direction):
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise ValueError('Reversible migration requires SQLite 3.35 or newer.')
    expected, result, key = ('before', 'after', 'forward') if direction == 'up' else ('after', 'before', 'backward')
    if schema(db) != plan[expected]:
        raise ValueError('Database schema changed since the reviewed migration plan.')
    check(db)
    if direction == 'down':
        require_unused(db, plan)
    execute(db, plan[key])
    if schema(db) != plan[result]:
        raise ValueError('Migration did not produce its reviewed schema.')
    check(db)


def transition(db, plan, direction, event):
    """Caller owns BEGIN IMMEDIATE; schema and immutable receipt commit together."""
    if not db.in_transaction:
        raise ValueError('Migration requires an owned database transaction.')
    prior = applied(db, event)
    evidence = json.dumps(plan, sort_keys=True)
    if prior:
        if prior != (plan['id'], direction, evidence):
            raise ValueError('Conflicting migration receipt identity.')
        return
    journal(db)
    transform(db, plan, direction)
    db.execute('INSERT INTO ' + JOURNAL + ' VALUES (?,?,?,?)', (event, plan['id'], direction, evidence))


def undo(db, record):
    """A missing receipt means the database transaction did not commit."""
    migration = record.get('migration')
    if not migration:
        return
    row = applied(db, record['nonce'])
    if not row:
        return
    plan = json.loads(row[2])
    if plan['id'] != migration['plan'] or row[1] != migration['direction']:
        raise ValueError('Recovery receipt does not match the interrupted migration.')
    transition(db, plan, 'down' if row[1] == 'up' else 'up', record['nonce'] + '-recovery')


def path(paths, identifier):
    if not re.fullmatch('[0-9a-f]{64}', identifier):
        raise ValueError('Use the exact migration plan ID shown by update plan.')
    return paths.data / 'updates' / 'migrations' / (identifier + '.json')


def read(paths, identifier):
    from .credentials import private_json
    plan = private_json(path(paths, identifier))
    if plan.get('id') != identifier or digest({k: v for k, v in plan.items() if k != 'id'}) != identifier:
        raise ValueError('Migration plan changed after review.')
    if plan['bindings'] != paths.environment():
        raise ValueError('Migration requires the reviewed data/project/output bindings.')
    return plan
