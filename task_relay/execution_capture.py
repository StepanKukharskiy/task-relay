"""Completion observations and explicitly bound work capture, with durable retry.

Owning completion transactions call notify. Projection/capture failures remain
pending here, never become worker failures or permission to repeat execution.
"""
import json
import time
import uuid

from . import execution_results as results, work_state as ws
from .project_context import encoded, model_evidence

ROOTS = {
    'production_attempt': ('production_attempts', 'id'), 'backend_job': ('backend_jobs', 'id'),
    'native_candidate': ('relay_agent_candidates', 'id'), 'xlsx_candidate': ('relay_fact_external_submissions', 'id'),
    'revision_bundle': ('relay_revision_bundles', 'id'), 'bundle_continuation': ('relay_bundle_continuations', 'id'),
    'work_text_run': ('work_text_runs', 'id'), 'plugin_capture': ('work_result_captures', 'hash')}


def initialize(db):
    for statement in '''
    CREATE TABLE IF NOT EXISTS execution_result_intents(
      id TEXT PRIMARY KEY,kind TEXT NOT NULL,source_id TEXT NOT NULL,source_project TEXT NOT NULL,
      root_sha256 TEXT NOT NULL,status TEXT NOT NULL,error TEXT,created REAL NOT NULL,
      UNIQUE(kind,source_id,source_project,root_sha256));
    CREATE TABLE IF NOT EXISTS execution_result_observations(
      id TEXT PRIMARY KEY,intent TEXT NOT NULL UNIQUE,result TEXT NOT NULL,
      sha256 TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS execution_result_links(
      id TEXT PRIMARY KEY,project TEXT NOT NULL,packet_id TEXT NOT NULL,kind TEXT NOT NULL,
      source_id TEXT NOT NULL,source_project TEXT NOT NULL,request_key TEXT NOT NULL,request TEXT NOT NULL,
      UNIQUE(project,request_key));
    CREATE TABLE IF NOT EXISTS execution_result_deliveries(
      observation TEXT NOT NULL,link TEXT NOT NULL,status TEXT NOT NULL,error TEXT,receipt TEXT,
      PRIMARY KEY(observation,link))
    '''.split(';'):
        if statement.strip(): db.execute(statement)


def root(db, kind, ident, source_project=None):
    if kind not in ROOTS: raise ValueError('Unsupported completion source')
    ws.identity(ident)
    table, key = ROOTS[kind]
    where, args = key + '=?', (ident,)
    if kind == 'plugin_capture':
        ws.identity(source_project)
        where += ' AND project=?'; args += (source_project,)
    return results.Reader(db).one(table, where, args)


def observation(db, ident):
    row = db.execute('SELECT * FROM execution_result_observations WHERE id=?', (ident,)).fetchone()
    if row is None: raise ValueError('Unknown saved execution observation')
    value = json.loads(row['result'])
    if (value['sha256'] != row['sha256'] or ws.digest(value['envelope']) != row['sha256']
            or ws.digest(value['original']) != value['envelope']['source_record_sha256']):
        raise ValueError('Saved execution observation hash mismatch')
    return value


def _deliver(db, oid, link):
    previous = db.execute('SELECT status FROM execution_result_deliveries WHERE observation=? AND link=?', (oid, link['id'])).fetchone()
    if previous and previous['status'] == 'captured': return
    db.execute('INSERT OR IGNORE INTO execution_result_deliveries VALUES (?, ?, ?, NULL, NULL)', (oid, link['id'], 'pending'))
    try:
        with ws.transaction(db):
            saved = observation(db, oid)
            receipt = results.capture(db, link['project'], link['packet_id'], source_db=db, kind=link['kind'],
                ident=link['source_id'], source_project=link['source_project'] or None,
                expected_sha256=saved['sha256'], request_key='completion:' + ws.digest([oid, link['id']]),
                request=link['request'], observation_id=oid, request_authority='relay_completion_link')
            db.execute("UPDATE execution_result_deliveries SET status='captured',error=NULL,receipt=? WHERE observation=? AND link=?",
                       (encoded(receipt), oid, link['id']))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        db.execute("UPDATE execution_result_deliveries SET status='pending',error=? WHERE observation=? AND link=?",
                   (str(exc)[:2000], oid, link['id']))


def _links(db, intent, oid):
    for link in db.execute('SELECT * FROM execution_result_links WHERE kind=? AND source_id=? AND source_project=?',
                           (intent['kind'], intent['source_id'], intent['source_project'])).fetchall():
        _deliver(db, oid, link)


def _project(db, intent):
    old = db.execute('SELECT id FROM execution_result_observations WHERE intent=?', (intent['id'],)).fetchone()
    if old:
        _links(db, intent, old['id']); return old['id']
    try:
        with ws.transaction(db):
            current = root(db, intent['kind'], intent['source_id'], intent['source_project'] or None)
            if ws.digest(current) != intent['root_sha256']:
                raise ValueError('Completion source changed before projection; preserve the pending intent')
            saved = results._inspect(db, intent['kind'], intent['source_id'], intent['source_project'] or None)
            oid = 'result:' + uuid.uuid4().hex
            db.execute('INSERT INTO execution_result_observations VALUES (?,?,?,?,?)',
                       (oid, intent['id'], encoded(saved), saved['sha256'], time.time()))
            db.execute("UPDATE execution_result_intents SET status='recorded',error=NULL WHERE id=?", (intent['id'],))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        db.execute("UPDATE execution_result_intents SET status='pending',error=? WHERE id=?", (str(exc)[:2000], intent['id']))
        return None
    _links(db, intent, oid)
    return oid


def bind(db, pid, packet_id, *, kind, ident, request_key, request, source_project=None):
    """Explicit host link. It grants capture of this identity, never dispatch."""
    ws.identity(request_key); ws.text(request, 'exact completion link request')
    with ws.transaction(db):
        initialize(db); ws.project(db, pid)
        root(db, kind, ident, source_project)
        packet = db.execute('SELECT * FROM work_packets WHERE project=? AND id=?', (pid, packet_id)).fetchone()
        if packet is None or ws.digest(json.loads(packet['packet'])) != packet['sha256']:
            raise ValueError('Unknown or changed completion continuation in this project')
        values = (pid, packet_id, kind, ident, source_project or '', request_key, request)
        old = db.execute('SELECT * FROM execution_result_links WHERE project=? AND request_key=?', (pid, request_key)).fetchone()
        if old:
            if tuple(old[k] for k in ('project','packet_id','kind','source_id','source_project','request_key','request')) != values:
                raise ValueError('Completion link key conflicts with its saved request')
            link = old
        else:
            lid = 'link:' + uuid.uuid4().hex
            db.execute('INSERT INTO execution_result_links VALUES (?,?,?,?,?,?,?,?)', (lid, *values))
            link = db.execute('SELECT * FROM execution_result_links WHERE id=?', (lid,)).fetchone()
        # Binding a saved source captures its latest observed completion only;
        # future observations for this exact identity use the same explicit link.
        latest = db.execute('''SELECT o.id FROM execution_result_observations o JOIN execution_result_intents i ON i.id=o.intent
          WHERE i.kind=? AND i.source_id=? AND i.source_project=? ORDER BY o.created DESC,o.id DESC LIMIT 1''',
          (kind, ident, source_project or '')).fetchone()
        if latest: _deliver(db, latest['id'], link)
        return {'link_id': link['id'], 'project_id': pid, 'packet_id': packet_id, 'execution_dispatch': False}


def notify(db, kind, ident, source_project=None):
    """Retain completion intent in the caller's owning transaction; try capture."""
    with ws.transaction(db):
        initialize(db)
        current = root(db, kind, ident, source_project)
        terminal = {'production_attempt': ('state', {'completed','blocked','cancelled','uncertain'}),
                    'backend_job': ('status', {'completed','failed','stopped','uncertain'}),
                    'work_text_run': ('status', {'completed'})}.get(kind)
        if terminal and current[terminal[0]] not in terminal[1]:
            raise ValueError('Execution source has no completion or recovery outcome')
        sha = ws.digest(current)
        db.execute('INSERT OR IGNORE INTO execution_result_intents VALUES (?,?,?,?,?,?,NULL,?)',
            ('intent:' + uuid.uuid4().hex, kind, ident, source_project or '', sha, 'pending', time.time()))
        intent = db.execute('SELECT * FROM execution_result_intents WHERE kind=? AND source_id=? AND source_project=? AND root_sha256=?',
                            (kind, ident, source_project or '', sha)).fetchone()
        if kind in {'work_text_run', 'plugin_capture'}:
            # These sources already own an exact reviewed/supplied work packet.
            bind(db, current['project'], current['packet_id'], kind=kind, ident=ident,
                 source_project=source_project, request_key='owned:' + ws.digest([kind, ident]),
                 request=current['request'] if kind == 'work_text_run' else json.loads(current['original'])['notes'])
        return _project(db, intent)


def recover(db, limit=100):
    if type(limit) is not int or not 1 <= limit <= 1000: raise ValueError('Invalid completion recovery budget')
    with ws.transaction(db):
        initialize(db)
        for row in db.execute("SELECT * FROM execution_result_intents WHERE status='pending' ORDER BY created,id LIMIT ?", (limit,)).fetchall():
            _project(db, row)
        for row in db.execute("SELECT * FROM execution_result_deliveries WHERE status='pending' ORDER BY observation,link LIMIT ?", (limit,)).fetchall():
            link = db.execute('SELECT * FROM execution_result_links WHERE id=?', (row['link'],)).fetchone()
            if link: _deliver(db, row['observation'], link)
        return status(db)


def status(db):
    return model_evidence({'intents': [dict(row) for row in db.execute('SELECT id,kind,source_id,status,error FROM execution_result_intents ORDER BY created,id')],
                           'deliveries': [dict(row) for row in db.execute('SELECT observation,link,status,error FROM execution_result_deliveries')],
                           'execution_dispatch': False})


def project_status(db, pid):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_result_links'").fetchone():
        return {'items': [], 'truncated': False}
    rows = db.execute('''SELECT l.id AS link_id,l.packet_id,l.kind,l.source_id,
      i.id AS intent_id,o.id AS observation_id,
      CASE WHEN i.id IS NULL THEN 'awaiting_result' WHEN i.status='pending' THEN 'projection_pending'
           ELSE coalesce(d.status,'awaiting_capture') END AS status,
      coalesce(d.error,i.error) AS error
      FROM execution_result_links l
      LEFT JOIN execution_result_intents i ON i.kind=l.kind AND i.source_id=l.source_id AND i.source_project=l.source_project
      LEFT JOIN execution_result_observations o ON o.intent=i.id
      LEFT JOIN execution_result_deliveries d ON d.link=l.id AND d.observation=o.id
      WHERE l.project=? ORDER BY l.id,i.created,i.id LIMIT 1001''', (pid,)).fetchall()
    return {'items': [dict(row) for row in rows[:1000]], 'truncated': len(rows) > 1000}
