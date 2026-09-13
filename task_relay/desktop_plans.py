"""Desktop entry and review for the existing bounded production planner."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .relay_paths import PATHS


class DesktopPlanError(ValueError):
    pass


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_plan_requests (
        request_id TEXT PRIMARY KEY, job_id INTEGER NOT NULL UNIQUE,
        prompt TEXT NOT NULL, project TEXT, parent_id TEXT,
        status TEXT NOT NULL, result TEXT, created REAL NOT NULL)''')


def _database(paths=PATHS, writable=False):
    if not paths.state.is_file():
        raise DesktopPlanError('Start Relay before planning a workflow.')
    db = sqlite3.connect(str(paths.state) if writable else paths.state.as_uri() + '?mode=ro',
                         uri=not writable, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    return db


def _ready(db):
    row = db.execute("SELECT value FROM kv WHERE key='health:desktop-plans'").fetchone()
    if not row:
        return False
    try:
        value = json.loads(row[0])
        return value.get('interface_version') == 1 and 0 <= time.time() - value.get('last_success', 0) < 20
    except (ValueError, TypeError):
        return False


def _request_id(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise DesktopPlanError('The planning request needs a valid identity.') from None
    if str(parsed) != value:
        raise DesktopPlanError('The planning request identity is invalid.')
    return -int(parsed.hex[:15], 16)


def _prompt(goal, constraints):
    if not isinstance(goal, str) or not goal.strip():
        raise DesktopPlanError('Describe the outcome you want to plan.')
    if not isinstance(constraints, str):
        raise DesktopPlanError('Enter constraints as text.')
    text = goal.strip()
    if constraints.strip():
        text += '\n\nConstraints and boundaries:\n' + constraints.strip()
    if len(text.encode('utf-8')) > 12000 or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
        raise DesktopPlanError('Keep the request under 12 KB without control characters.')
    return text


def create(goal, constraints, project, parent_id, request_id, paths=PATHS):
    job_id = _request_id(request_id)
    prompt = _prompt(goal, constraints)
    if project is not None:
        if not isinstance(project, str) or not Path(project).is_absolute() or not Path(project).is_dir():
            raise DesktopPlanError('Choose an existing absolute project folder or a standalone plan.')
        project = str(Path(project).resolve())
    if parent_id is not None and (not isinstance(parent_id, str) or len(parent_id) > 80):
        raise DesktopPlanError('Choose a saved plan to revise.')
    with closing(_database(paths, writable=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not _ready(db) or not db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_plan_requests'").fetchone():
                raise DesktopPlanError('Restart the current Relay service to enable desktop planning.')
            existing = db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?', (request_id,)).fetchone()
            if existing:
                if (existing['prompt'], existing['project'], existing['parent_id']) != (prompt, project, parent_id):
                    raise DesktopPlanError('That request identity belongs to different planning content.')
                return dict(request_id=request_id, plan_id='plan-' + str(job_id), status=existing['status'],
                            message=existing['result'] or 'Planning request saved.')
            if parent_id:
                parent = db.execute('SELECT id,status,channel FROM production_plans WHERE id=?', (parent_id,)).fetchone()
                if not parent or parent['channel'] != 'desktop' or parent['status'] not in ('ready', 'needs_input', 'blocked'):
                    raise DesktopPlanError('The selected desktop plan cannot be revised. Refresh it first.')
            db.execute('''INSERT INTO desktop_plan_requests VALUES (?,?,?,?,?,'queued',NULL,?)''',
                       (request_id, job_id, prompt, project, parent_id, time.time()))
    return dict(request_id=request_id, plan_id='plan-' + str(job_id), status='queued',
                message='Planning request saved. The planner may use your configured API provider; no workers have started.')


def process_requests(state, clock=time.time):
    """Service-owned admission; a crash cannot duplicate a saved plan identity."""
    from . import orchestrator_chat, production_planning, relay_channels
    for _ in range(1):
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            row = state.db.execute("SELECT * FROM desktop_plan_requests WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                break
            admission_started = False
            try:
                provider, model = orchestrator_chat.provider(state)
                state.db.execute('SAVEPOINT desktop_plan_admission')
                admission_started = True
                state.db.execute('INSERT OR REPLACE INTO relay_request_channels VALUES (?,?)', (row['job_id'], 'desktop'))
                action = dict(kind='plan_production', template='custom', project=row['project'],
                              reference_pack_id=None, research_ids=[], planning_only=True)
                if row['parent_id']:
                    action['parent_id'] = row['parent_id']
                prior = production_planning.context(relay_channels.ScopedState(state, 'desktop'))
                if row['parent_id'] and not any(plan['id'] == row['parent_id'] for plan in prior):
                    saved = state.db.execute("SELECT id,status,channel FROM production_plans WHERE id=?", (row['parent_id'],)).fetchone()
                    if saved and saved['channel'] == 'desktop':
                        prior.append({'id': saved['id'], 'status': saved['status']})
                snapshot = {'project_roadmaps': {'available_projects': [row['project']] if row['project'] else []},
                            'production_plans': prior,
                            'research_documents': [], 'production_artifacts': [],
                            'capabilities': {'graph_executors': [], 'graph_operations': []}}
                message = production_planning.enqueue(state,
                    {'id': row['job_id'], 'prompt': row['prompt'], 'provider': provider, 'model': model}, action, snapshot)
                state.db.execute('RELEASE desktop_plan_admission')
                admission_started = False
                state.db.execute("UPDATE desktop_plan_requests SET status='accepted',result=? WHERE request_id=?",
                                 (message, row['request_id']))
            except (ValueError, OSError) as exc:
                if admission_started:
                    # Only the admission work is reversed; retain its rejection receipt.
                    state.db.execute('ROLLBACK TO desktop_plan_admission')
                    state.db.execute('RELEASE desktop_plan_admission')
                state.db.execute("UPDATE desktop_plan_requests SET status='rejected',result=? WHERE request_id=?",
                                 (str(exc), row['request_id']))
    with state.db:
        state.put('health:desktop-plans', {'interface_version': 1, 'last_success': clock()})


def list_plans(paths=PATHS):
    if not paths.state.is_file():
        return {'plans': [], 'can_plan': False}
    with closing(_database(paths)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_plan_requests'").fetchone():
            return {'plans': [], 'can_plan': False}
        rows = db.execute('''SELECT d.request_id,d.job_id,d.prompt,d.project,d.status AS request_status,d.result,
                            p.id,p.status,p.plan_hash,p.run,p.error,p.created
                            FROM desktop_plan_requests d LEFT JOIN production_plans p ON p.request_id=d.job_id
                            ORDER BY d.created DESC LIMIT 24''').fetchall()
        return {'can_plan': _ready(db), 'plans': [dict(r) for r in rows]}


def _plan(db, ident):
    if not isinstance(ident, str) or len(ident) > 80:
        raise DesktopPlanError('Choose a saved plan.')
    row = db.execute("SELECT * FROM production_plans WHERE id=? AND channel='desktop'", (ident,)).fetchone()
    if row is None:
        raise DesktopPlanError('That desktop plan is unavailable. Refresh the list.')
    return row


def _documents(db, row):
    """Return exact text attachments needed to review this plan; never truncate."""
    result = []
    if not row['event_id']:
        return result
    total = 0
    original = 'planner:' + row['id'] + ':ready'
    for item in db.execute('SELECT id,path,filename,caption FROM media_outbox WHERE event_id IN (?,?) ORDER BY id',
                           (row['event_id'], original)):
        path = Path(item['path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 250000:
            raise DesktopPlanError('A plan document is unavailable or too large for desktop review. No work can start here.')
        raw = path.read_bytes()
        total += len(raw)
        if total > 450000:
            raise DesktopPlanError('Plan documents exceed desktop review size. No work can start here.')
        try:
            content = raw.decode('utf-8')
        except UnicodeError:
            raise DesktopPlanError('A plan document is not readable text. No work can start here.') from None
        result.append(dict(id=item['id'], filename=item['filename'], caption=item['caption'],
                           sha256=hashlib.sha256(raw).hexdigest(), content=content))
    return result


def _review_digest(row, documents):
    from orchestrator.contracts import digest
    return digest({'id': row['id'], 'event': row['event_id'], 'plan_hash': row['plan_hash'],
                   'context_hash': row['context_hash'],
                   'documents': [(d['id'], d['sha256']) for d in documents]})


def detail(ident, paths=PATHS):
    from . import production_planning
    with closing(_database(paths)) as db:
        row = _plan(db, ident)
        documents = []
        review_error = None
        if row['status'] == 'ready':
            try:
                documents = _documents(db, row)
            except DesktopPlanError as exc:
                review_error = str(exc)
        options = json.loads(row['options'])
        result = json.loads(row['result']) if row['result'] else None
        return {'id': row['id'], 'request': row['request'], 'status': row['status'],
                'project': options.get('project'),
                'error': row['error'], 'run': row['run'], 'planning_only': options['planning_only'],
                'preview': production_planning.preview(row) if row['plan'] else result.get('message') if result else None,
                'plan': json.loads(row['plan']) if row['plan'] else None,
                'documents': documents, 'review_error': review_error,
                'review_digest': _review_digest(row, documents) if row['status'] == 'ready' and not review_error else None}


def prepare(ident, paths=PATHS):
    from .bridge import State
    from . import production_planning, relay_channels
    state = State(paths.state)
    try:
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            if not _ready(state.db):
                raise DesktopPlanError('Restart the current Relay service to review a desktop plan.')
            row = _plan(state.db, ident)
            if row['status'] != 'ready':
                raise DesktopPlanError('The planner has not produced a ready draft.')
            if json.loads(row['options'])['planning_only']:
                production_planning.authorize(relay_channels.ScopedState(state, 'desktop'),
                                              {'id': row['request_id']}, ident)
        return detail(ident, paths)
    finally:
        state.db.close()


def decide(ident, verb, review_digest, paths=PATHS):
    from .bridge import State
    from . import production_planning, relay_channels
    if verb not in ('start', 'discard'):
        raise DesktopPlanError('Choose Start or Discard.')
    state = State(paths.state)
    try:
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            if not _ready(state.db):
                raise DesktopPlanError('Restart the current Relay service before deciding.')
            row = _plan(state.db, ident)
            if row['status'] != 'ready':
                raise DesktopPlanError('This draft changed or was already handled.')
            if verb == 'start' and not (state.get('user_id') and state.get('chat_id')):
                raise DesktopPlanError('Pair Telegram in Setup before starting; progress and output decisions continue there.')
            documents = _documents(state.db, row)
            if not isinstance(review_digest, str) or review_digest != _review_digest(row, documents):
                raise DesktopPlanError('The plan or its documents changed. Refresh and review them again.')
            message = production_planning.apply(relay_channels.ScopedState(state, 'desktop'),
                row['token'], verb, reviewed_event=row['event_id'],
                reviewed_attachments={d['id'] for d in documents},
                followup_channel='telegram' if verb == 'start' else None)
        return {'message': message, 'status': 'started' if verb == 'start' else 'discarded'}
    finally:
        state.db.close()
