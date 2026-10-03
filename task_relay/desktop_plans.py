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
    from .conversation_flow import initialize as initialize_flow
    initialize_flow(db)
    from .conversation_delete import initialize as initialize_conversation_delete
    initialize_conversation_delete(db)
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_request_modes (
        request_id TEXT PRIMARY KEY, entry_mode TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_plan_preferences (
        request_id TEXT PRIMARY KEY, research_mode TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_job_archives (
        kind TEXT NOT NULL, id TEXT NOT NULL, review_digest TEXT NOT NULL,
        created REAL NOT NULL, PRIMARY KEY(kind,id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_plan_requests (
        request_id TEXT PRIMARY KEY, job_id INTEGER NOT NULL UNIQUE,
        prompt TEXT NOT NULL, project TEXT, parent_id TEXT,
        status TEXT NOT NULL, result TEXT, created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_plan_inputs (
        request_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, previous_run TEXT,
        goal TEXT NOT NULL, constraints_text TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_workspace_commands (
        request_id TEXT PRIMARY KEY, run TEXT NOT NULL, verb TEXT NOT NULL,
        fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL,
        note TEXT NOT NULL, created REAL NOT NULL)''')


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
    text = goal
    if constraints.strip():
        text += '\n\nConstraints and boundaries:\n' + constraints
    if len(text.encode('utf-8')) > 12000 or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
        raise DesktopPlanError('Keep the request under 12 KB without control characters.')
    return text


def create(goal, constraints, project, parent_id, request_id, paths=PATHS, *, files=None, previous_run=None, research_mode='suggest', entry_mode='plan', followup=None):
    if entry_mode not in ('plan', 'conversation') or (entry_mode == 'conversation' and (parent_id or previous_run)):
        raise DesktopPlanError('Plan revisions and stage follow-ups retain their existing planning scope.')
    if research_mode not in ('suggest', 'none', 'sources'):
        raise DesktopPlanError('Choose suggested research, no new research, or a source-backed answer.')
    job_id = _request_id(request_id)
    prompt = _prompt(goal, constraints)
    if project is not None:
        if not isinstance(project, str) or not Path(project).is_absolute() or not Path(project).is_dir():
            raise DesktopPlanError('Choose an existing absolute project folder or a standalone plan.')
        project = str(Path(project).resolve())
    if parent_id is not None and (not isinstance(parent_id, str) or len(parent_id) > 80):
        raise DesktopPlanError('Choose a saved plan to revise.')
    files = [] if files is None else files
    if (not isinstance(files, list) or len(files) > 10 or any(not isinstance(p, str) or not Path(p).is_absolute() for p in files)
            or len(set(files)) != len(files)):
        raise DesktopPlanError('Choose up to ten distinct files with absolute paths.')
    if previous_run is not None and (parent_id or not isinstance(previous_run, str) or len(previous_run) > 80):
        raise DesktopPlanError('Choose one existing job for this follow-up.')
    with closing(_database(paths, writable=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not _ready(db) or not db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_plan_requests'").fetchone():
                raise DesktopPlanError('Restart the current Relay service to enable desktop planning.')
            if entry_mode == 'conversation':
                health = json.loads(db.execute("SELECT value FROM kv WHERE key='health:desktop-plans'").fetchone()[0])
                if health.get('orchestrator_entry_version') != 1:
                    raise DesktopPlanError('Restart Relay to enable the shared orchestrator entry before sending this request.')
            existing = db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?', (request_id,)).fetchone()
            if followup is not None:
                from . import conversation_flow
                known=conversation_flow.bind(db,followup,goal,constraints,project,files,request_id,entry_mode,research_mode)
                if known:return known
                if existing:raise DesktopPlanError('That request identity belongs to another submission.')
            if existing:
                if existing['status'] == 'deleted':
                    from .conversation_delete import submission_identity
                    receipt = db.execute('SELECT submission_sha256 FROM desktop_conversation_deletions WHERE request_id=?',(request_id,)).fetchone()
                    if not receipt or receipt[0] != submission_identity(goal,constraints,project,parent_id,previous_run,research_mode,entry_mode,files):
                        raise DesktopPlanError('That deleted request identity belongs to different exact content.')
                    return dict(request_id=request_id, status='deleted', message=existing['result'])
                mode = db.execute('SELECT entry_mode FROM desktop_request_modes WHERE request_id=?', (request_id,)).fetchone()
                if (mode[0] if mode else 'plan') != entry_mode:
                    raise DesktopPlanError('That request identity belongs to a different entry mode.')
                preference = db.execute('SELECT research_mode FROM desktop_plan_preferences WHERE request_id=?', (request_id,)).fetchone()
                if (preference[0] if preference else 'suggest') != research_mode:
                    raise DesktopPlanError('That request identity belongs to a different research choice.')
                if (existing['prompt'], existing['project'], existing['parent_id']) != (prompt, project, parent_id):
                    raise DesktopPlanError('That request identity belongs to different planning content.')
                saved = db.execute('SELECT * FROM desktop_plan_inputs WHERE request_id=?', (request_id,)).fetchone()
                if saved and (saved['goal'], saved['constraints_text']) != (goal, constraints):
                    raise DesktopPlanError('That request identity belongs to different exact input text.')
                manifest = json.loads(saved['manifest']) if saved else []
                if ([m['source'] for m in manifest], saved['previous_run'] if saved else None) != (files, previous_run):
                    raise DesktopPlanError('That request identity belongs to different files or job.')
                # Retrying the receipt never re-reads changing originals or queues again.
                return dict(request_id=request_id, plan_id='plan-' + str(job_id), status=existing['status'],
                            message=existing['result'] or 'Planning request saved.')
            if parent_id:
                parent = db.execute('SELECT id,status,channel FROM production_plans WHERE id=?', (parent_id,)).fetchone()
                if not parent or parent['channel'] != 'desktop' or parent['status'] not in ('ready', 'needs_input', 'blocked'):
                    raise DesktopPlanError('The selected desktop plan cannot be revised. Refresh it first.')
            if previous_run:
                from .desktop_workspace import require_local_run
                require_local_run(db, previous_run)
            from . import routing_inputs
            state = type('InputState', (), {'db': db, 'media_dir': paths.data / 'media'})()
            for path in files:
                source = Path(path)
                if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
                    raise DesktopPlanError('Attachments must be nonempty regular files.')
                if source.stat().st_size > 20_000_000:
                    raise DesktopPlanError('Each attachment must be at most 20 MB.')
            manifest = routing_inputs.capture(state, {'id': job_id},
                [(Path(p), Path(p).name, 'User-selected task attachment', None, None) for p in files],
                section='desktop-files', max_bytes=50_000_000)
            if followup is not None:
                original=conversation_flow.selected(db,followup['id'],followup['index'],followup['digest'])[1]
                frozen=json.loads(original['manifest'])
                if [(f['sha256'],f['bytes']) for f in manifest]!=[(f['sha256'],f['bytes']) for f in frozen]:
                    raise DesktopPlanError('A frozen attachment changed during capture. No follow-up was queued.')
            db.execute('INSERT INTO desktop_plan_inputs VALUES (?,?,?,?,?)',
                       (request_id, json.dumps(manifest), previous_run, goal, constraints))
            db.execute('INSERT INTO desktop_plan_preferences VALUES (?,?)', (request_id, research_mode))
            db.execute('INSERT INTO desktop_request_modes VALUES (?,?)', (request_id, entry_mode))
            db.execute('''INSERT INTO desktop_plan_requests VALUES (?,?,?,?,?,'queued',NULL,?)''',
                       (request_id, job_id, prompt, project, parent_id, time.time()))
            if followup is not None:
                db.execute('INSERT INTO conversation_followups VALUES (?,?,?,?,?,?,?)',
                           (request_id,int(conversation_flow.root_for(db,job_id=int(followup['id'])) or followup['id']),followup['index'],followup['digest'],
                            'research' if entry_mode=='conversation' else 'plan',time.time(),int(followup['id'])))
    return dict(request_id=request_id, plan_id='plan-' + str(job_id), status='queued',
                message=('Request saved for the shared orchestrator.' if entry_mode == 'conversation' else
                         'Planning request saved. The planner may use your configured API provider; no workers have started.'))


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
                mode = state.db.execute('SELECT entry_mode FROM desktop_request_modes WHERE request_id=?', (row['request_id'],)).fetchone()
                if mode and mode[0] == 'conversation':
                    state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (?,?,NULL,?,?,?)',
                                     (row['job_id'], row['prompt'], provider, model, row['created']))
                    state.db.execute('RELEASE desktop_plan_admission')
                    admission_started = False
                    state.db.execute("UPDATE desktop_plan_requests SET status='accepted',result=? WHERE request_id=?",
                                     ('Request queued for the shared orchestrator.', row['request_id']))
                    continue
                action = dict(kind='plan_production', template='custom', project=row['project'],
                              reference_pack_id=None, research_ids=[], planning_only=True)
                if row['parent_id']:
                    action['parent_id'] = row['parent_id']
                inputs = state.db.execute('SELECT previous_run FROM desktop_plan_inputs WHERE request_id=?', (row['request_id'],)).fetchone()
                if inputs and inputs['previous_run']:
                    action['previous_run'] = inputs['previous_run']
                prior = production_planning.context(relay_channels.ScopedState(state, 'desktop'))
                if row['parent_id'] and not any(plan['id'] == row['parent_id'] for plan in prior):
                    saved = state.db.execute("SELECT id,status,channel FROM production_plans WHERE id=?", (row['parent_id'],)).fetchone()
                    if saved and saved['channel'] == 'desktop':
                        prior.append({'id': saved['id'], 'status': saved['status']})
                snapshot = {'project_roadmaps': {'available_projects': [row['project']] if row['project'] else []},
                            'production_plans': prior,
                            'research_documents': [], 'production_artifacts': [],
                            'capabilities': {'graph_executors': [], 'graph_operations': []}}
                if inputs and inputs['previous_run']:
                    from . import production_control
                    snapshot['production_runs'] = [v for v in production_control.inspect(state, inputs['previous_run'], include_files=False)
                                                   if v['name'] == inputs['previous_run']]
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
        state.put('health:desktop-plans', {'interface_version': 1, 'orchestrator_entry_version': 1, 'last_success': clock()})


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


def _plan(db, ident, *, allow_transferred=False):
    if not isinstance(ident, str) or len(ident) > 80:
        raise DesktopPlanError('Choose a saved plan.')
    row = db.execute("SELECT * FROM production_plans WHERE id=? AND channel='desktop'", (ident,)).fetchone()
    if row is None and allow_transferred:
        candidate = db.execute("SELECT * FROM production_plans WHERE id=? AND channel='telegram'", (ident,)).fetchone()
        if candidate and candidate['run']:
            receipts = db.execute("SELECT data FROM production_events WHERE run=? AND kind='desktop_plan_transferred'", (candidate['run'],))
            for receipt in receipts:
                data = json.loads(receipt[0])
                if (data.get('version') == 1 and data.get('source') == 'desktop'
                    and data.get('destination') == 'telegram' and data.get('start_plan') == ident
                    and any(p['id'] == ident and p['plan_hash'] == candidate['plan_hash']
                            and p['previous_channel'] == 'desktop'
                            and p['request_sha256'] == hashlib.sha256(candidate['request'].encode()).hexdigest()
                       for p in data.get('plans', []))):
                    row = candidate
                    break
    if row is None:
        raise DesktopPlanError('That desktop plan is unavailable. Refresh the list.')
    return row


def transfer_to_telegram(state, runtime, plan_id, run):
    """Transfer unexecuted Desktop ancestry inside the exact Start commit."""
    if not state.db.in_transaction:
        raise DesktopPlanError('Desktop plan transfer requires the Start transaction.')
    records = []
    ident = plan_id
    while ident:
        if len(records) >= 100 or ident in {p['id'] for p in records}:
            raise DesktopPlanError('Desktop plan ancestry is cyclic or too large.')
        row = state.db.execute('SELECT * FROM production_plans WHERE id=?', (ident,)).fetchone()
        if not row or row['channel'] != 'desktop' or row['run']:
            raise DesktopPlanError('Desktop transfer requires unexecuted plans in one channel.')
        if state.db.execute("SELECT 1 FROM relay_pipeline_steps WHERE target_kind='plan_production' AND target=?", (ident,)).fetchone():
            raise DesktopPlanError('A saved workflow owns this plan; retain its channel.')
        records.append(dict(id=ident, parent_id=row['parent_id'], request_id=row['request_id'],
                            request_sha256=hashlib.sha256(row['request'].encode()).hexdigest(),
                            plan_hash=row['plan_hash'], previous_channel=row['channel']))
        ident = row['parent_id']
    runtime.event(run, None, None, 'desktop_plan_transferred',
                  dict(version=1, source='desktop', destination='telegram', start_plan=plan_id, plans=records))
    for record in records:
        state.db.execute("UPDATE production_plans SET channel='telegram' WHERE id=?", (record['id'],))


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


def _review_digest(row, documents, epoch=0, workflow=None):
    from orchestrator.contracts import digest
    return digest({'id': row['id'], 'epoch': epoch, 'workflow': workflow, 'status': row['status'], 'channel': row['channel'],
                   'request': row['request'], 'options': row['options'], 'expires': row['expires'],
                   'error': row['error'], 'result': row['result'],
                   'event': row['event_id'], 'plan_hash': row['plan_hash'],
                   'context_hash': row['context_hash'],
                   'documents': [(d['id'], d['sha256']) for d in documents]})


def _plan_digest(db, row, documents):
    saved = db.execute('SELECT value FROM kv WHERE key=?', ('desktop-plan-epoch:' + row['id'],)).fetchone()
    return _review_digest(row, documents, json.loads(saved[0]) if saved else 0, _workflow(db, row['id']))


def _workflow(db, ident):
    row = db.execute('''SELECT p.id,p.status,p.channel,s.id step,s.status step_status,s.error
        FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline
        WHERE s.target_kind='plan_production' AND s.target=?''', (ident,)).fetchone()
    return dict(row) if row else None


def _execution_blocker(workflow):
    if not workflow or workflow['status']=='active':
        return None
    if workflow['status']=='blocked' and workflow['step_status']=='blocked' and workflow['error']=='Plan expanded workflow attempt bounds.':
        return None
    return 'The owning workflow is '+workflow['status']+'. This stage cannot start. You can discard its unexecuted plan.'


def detail(ident, paths=PATHS, *, shared=False):
    from . import production_planning
    with closing(_database(paths)) as db:
        row = db.execute('SELECT * FROM production_plans WHERE id=?', (ident,)).fetchone() if shared else _plan(db, ident, allow_transferred=True)
        if not row:
            raise DesktopPlanError('That saved plan is unavailable.')
        documents = []
        review_error = None
        if row['status'] == 'ready':
            try:
                documents = _documents(db, row)
            except DesktopPlanError as exc:
                review_error = str(exc)
        options = json.loads(row['options'])
        result = json.loads(row['result']) if row['result'] else None
        attempts=[];rejected=None
        for call in db.execute('SELECT number,request,response,error FROM production_plan_calls WHERE plan_id=? ORDER BY number',(ident,)):
            try:sent=json.loads(call['request'])
            except (ValueError,TypeError):sent={}
            attempts.append({'number':call['number'],'error':call['error'],
                             'correction_error':sent.get('structural_correction',{}).get('error')})
            if call['response'] and call['error']:
                try:rejected=json.loads(call['response'])
                except (ValueError,TypeError):pass
        archived = bool(db.execute("SELECT 1 FROM desktop_job_archives WHERE kind='plan' AND id=?", (ident,)).fetchone())
        from . import desktop_sources
        from . import conversation_flow
        return {'id': row['id'], 'request': row['request'], 'status': row['status'], 'channel': row['channel'],
                'project': options.get('project'),
                'research_mode': json.loads(row['context']).get('research_mode', 'suggest'),
                'research_advice': result.get('research_advice') if result else None,
                'error': row['error'], 'run': row['run'], 'planning_only': options['planning_only'],
                'preview': production_planning.preview(row) if row['plan'] else result.get('message') if result else None,
                'plan': json.loads(row['plan']) if row['plan'] else None,
                'planner_attempts':attempts,'rejected_proposal':rejected,
                'proposed_tasks':conversation_flow.proposed_tasks(rejected),
                'research': desktop_sources.proposal(json.loads(row['plan']) if row['plan'] else None),
                'expired': row['expires'] <= time.time(),
                'archived': archived,
                'workflow': _workflow(db, ident), 'execution_blocker': _execution_blocker(_workflow(db, ident)),
                'documents': documents, 'review_error': review_error,
                'review_digest': _plan_digest(db, row, documents)}


def _shared_plan(db, ident):
    if not isinstance(ident, str) or len(ident) > 80:
        raise DesktopPlanError('Choose a saved plan.')
    row = db.execute('SELECT * FROM production_plans WHERE id=?', (ident,)).fetchone()
    if not row or row['channel'] not in ('desktop', 'telegram', 'messages'):
        raise DesktopPlanError('That saved plan is unavailable.')
    return row


def prepare(ident, paths=PATHS, *, review_digest=None):
    from .bridge import State
    from . import production_planning, relay_channels
    state = State(paths.state)
    try:
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            if not _ready(state.db):
                raise DesktopPlanError('Restart the current Relay service to review a desktop plan.')
            row = _shared_plan(state.db, ident)
            if row['status'] != 'ready':
                raise DesktopPlanError('The planner has not produced a ready draft.')
            if review_digest is not None and review_digest != _plan_digest(state.db, row, _documents(state.db, row)):
                raise DesktopPlanError('The plan changed. Refresh and review it again.')
            if json.loads(row['options'])['planning_only'] or row['expires'] <= time.time():
                production_planning.authorize(relay_channels.ScopedState(state, row['channel']),
                                              {'id': row['request_id']}, ident)
        return detail(ident, paths, shared=True)
    finally:
        state.db.close()


def decide(ident, verb, review_digest, paths=PATHS, *, request_id=None):
    from .bridge import State
    from . import production_planning, relay_channels
    if verb not in ('start', 'discard', 'archive', 'restore'):
        raise DesktopPlanError('Choose Start, Discard or Remove.')
    if request_id is not None:
        _request_id(request_id)
    fingerprint = hashlib.sha256(json.dumps([ident, verb, review_digest]).encode()).hexdigest()
    state = State(paths.state)
    try:
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            if not _ready(state.db):
                raise DesktopPlanError('Restart the current Relay service before deciding.')
            if request_id:
                prior = state.db.execute('SELECT * FROM desktop_workspace_commands WHERE request_id=?', (request_id,)).fetchone()
                if prior:
                    if prior['fingerprint'] != fingerprint:
                        raise DesktopPlanError('That action identity belongs to a different decision.')
                    return json.loads(prior['result'])
            row = _shared_plan(state.db, ident)
            if verb in ('archive', 'restore'):
                if verb == 'archive' and (row['run'] or row['status'] not in ('discarded', 'superseded', 'blocked', 'needs_input')):
                    raise DesktopPlanError('Discard the plan or cancel its work before removing it.')
                if review_digest != _plan_digest(state.db, row, []):
                    raise DesktopPlanError('The plan changed. Review it again.')
                if verb == 'archive':
                    state.db.execute('INSERT OR IGNORE INTO desktop_job_archives VALUES (?,?,?,?)',
                                 ('plan', ident, review_digest, time.time()))
                else:
                    state.db.execute("DELETE FROM desktop_job_archives WHERE kind='plan' AND id=?", (ident,))
                state.put('desktop-plan-epoch:' + ident, state.get('desktop-plan-epoch:' + ident, 0) + 1)
                result = dict(status='removed' if verb=='archive' else 'restored', message='Removed from Jobs. Files, decisions and recovery history are retained.' if verb=='archive' else 'Restored to Jobs.')
                if request_id:
                    state.db.execute('INSERT INTO desktop_workspace_commands VALUES (?,?,?,?,?,?,?,?)',
                                     (request_id, ident, verb, fingerprint, 'accepted', json.dumps(result), '', time.time()))
                return result
            if row['status'] != 'ready':
                raise DesktopPlanError('This draft changed or was already handled.')
            try:
                documents = _documents(state.db, row)
            except DesktopPlanError:
                if verb != 'discard':
                    raise
                documents = []
            if not isinstance(review_digest, str) or review_digest != _plan_digest(state.db, row, documents):
                raise DesktopPlanError('The plan or its documents changed. Refresh and review them again.')
            if verb == 'discard':
                state.db.execute("UPDATE production_plans SET status='discarded' WHERE id=?", (ident,))
                message = 'Plan discarded; no workers started.'
            else:
                message = production_planning.apply(relay_channels.ScopedState(state, row['channel']),
                    row['token'], verb, reviewed_event=row['event_id'],
                    reviewed_attachments={d['id'] for d in documents}, review_surface='desktop')
            result = {'message': message, 'status': 'started' if verb == 'start' else 'discarded'}
            if request_id:
                state.db.execute('INSERT INTO desktop_workspace_commands VALUES (?,?,?,?,?,?,?,?)',
                                 (request_id, ident, verb, fingerprint, 'accepted', json.dumps(result), '', time.time()))
        return result
    finally:
        state.db.close()
