"""Explicit new Codex tasks with durable creation and first-turn boundaries."""
import json
import hashlib
from pathlib import Path
import time
import uuid

from .host import HOST
from . import codex_app_server, relay_channels, routing_inputs

INSTRUCTIONS = '''For an explicit request to CREATE a new Codex task, use
{"kind":"create_codex_task","project":"exact cwd from codex_projects",
 "title":"short task title","start_work":false,"research_ids":[],"artifact_ids":[]}.
Set start_work=true only when the current user asks to create a task AND perform
work there. The original request, not your rewrite, is sent as its first turn.
Creation-only does not start a model. "Can you start a new Codex task in PROJECT
to research QUESTION?" is a create-and-start request, even if QUESTION compares
several alternatives. It is not merely a capabilities question.
Do not choose this action for general capability questions,
hypotheticals, requests to build task-creation support, or work in an existing task.
Resolve the project from the user's request/context; ask if ambiguous. Never choose
an unrelated project. Each offered cwd is an existing local checkout, not a new
worktree. Honor requests for isolation/branches/remote projects by explaining that
this creation adapter cannot yet supply them; do not silently use a local checkout.
Codex's configured model and permissions are inherited; explicit model overrides
are not supported by this adapter. Do not silently substitute them. Selected guides
and registered source versions accompany start_work. Existing project instructions
apply. New tasks and first turns have separate receipts in created_tasks. A queued
request is not a created task. Never replay an uncertain creation or turn. A known
task ID survives rename/start failure; direct subsequent work to that existing task.
'''

SCHEMA = {'type':'object', 'additionalProperties':False,
    'required':['kind','project','title','start_work','research_ids','artifact_ids'],
    'properties':{'kind':{'const':'create_codex_task'}, 'project':{'type':'string'},
        'title':{'type':'string','minLength':1,'maxLength':150}, 'start_work':{'type':'boolean'},
        'research_ids':{'type':'array','items':{'type':'integer'},'uniqueItems':True},
        'artifact_ids':{'type':'array','items':{'type':'string'},'uniqueItems':True}}}


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS task_creations (
        id INTEGER PRIMARY KEY, prompt TEXT NOT NULL, action TEXT NOT NULL,
        cwd TEXT NOT NULL, project_identity TEXT NOT NULL, title TEXT NOT NULL,
        start_work INTEGER NOT NULL, input_manifest TEXT NOT NULL,
        status TEXT NOT NULL, task_id TEXT, rollout_path TEXT, history_sha256 TEXT, error TEXT,
        created REAL NOT NULL, expires REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS task_creation_calls (
        request_id INTEGER NOT NULL, method TEXT NOT NULL, params TEXT NOT NULL,
        response TEXT, error TEXT, PRIMARY KEY(request_id,method));''')
    if 'history_sha256' not in {r[1] for r in db.execute('PRAGMA table_info(task_creations)')}:
        db.execute('ALTER TABLE task_creations ADD COLUMN history_sha256 TEXT')


def identity(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Project must be an absolute existing folder.')
    path = path.resolve(strict=True)
    if not path.is_dir() or path in (Path('/'), Path.home(), Path.home()/'Documents'):
        raise ValueError('Choose a specific existing project folder.')
    stat = path.stat()
    return {'cwd':str(path), 'device':stat.st_dev, 'inode':stat.st_ino}


def projects(state):
    from .bridge import local_tasks, BridgeError
    roots = HOST.codex_projects()
    try:
        roots += [{'cwd':t['cwd'],'name':Path(t['cwd']).name} for t in local_tasks()]
    except (OSError, BridgeError):
        pass
    setup = state.media_dir.parent/'onboarding.json'
    if setup.is_file():
        project = json.loads(setup.read_text()).get('project')
        if project:
            roots.append({'cwd':project, 'name':Path(project).name})
    found = {}
    for root in roots:
        try:
            frozen = identity(root['cwd'])
        except (OSError, ValueError):
            continue
        found.setdefault(frozen['cwd'], dict(cwd=frozen['cwd'], name=root['name'],
            identity=frozen, environment='Existing local checkout; shared files, no automatic worktree.'))
    return sorted(found.values(), key=lambda p:p['cwd'])[:100]


def validate_action(action, snap):
    if set(action) != set(SCHEMA['required']) or type(action['start_work']) is not bool:
        raise ValueError('Specify project, title, creation/start intent and source selections.')
    if not isinstance(action['title'],str) or not action['title'].strip() or len(action['title'])>150 or any(ord(c)<32 for c in action['title']):
        raise ValueError('Use a nonempty task title of at most 150 characters without control characters.')
    target = next((p for p in snap.get('codex_projects',[]) if p['cwd']==action['project']),None)
    if target is None:
        raise ValueError('Choose an available local Codex project.')
    routing_inputs.validate_ids(action['research_ids'],snap.get('research_documents',[]))
    routing_inputs.validate_artifact_ids(action['artifact_ids'],snap.get('production_artifacts',[]))
    if not action['start_work'] and (action['research_ids'] or action['artifact_ids']):
        raise ValueError('Creation-only cannot send input files; select sources when requesting work.')
    return target


def task_status(state, tid, path):
    from .bridge import recent_status
    observed=recent_status(path)
    if observed!='unknown':return observed
    row=state.db.execute('SELECT rollout_path,history_sha256,status FROM task_creations WHERE task_id=?',(tid,)).fetchone()
    # A new task has no completion event yet. Only recognize the exact empty
    # history saved at creation, never arbitrary unknown or changed rollouts.
    if row and row['status'] in ('created','opening','naming') and row['history_sha256']:
        try:
            p=Path(path)
            if str(p)==row['rollout_path'] and p.stat().st_size<=1_000_000 and hashlib.sha256(p.read_bytes()).hexdigest()==row['history_sha256']:
                return 'idle'
        except OSError:pass
    return observed


def enqueue(state, job, action, snap):
    if not state.db.in_transaction:
        raise ValueError('Task creation requires an outer transaction.')
    if not state.get('orchestrator_routing_enabled',False):
        raise ValueError('Task routing is disabled.')
    target = validate_action(action,snap)
    HOST.codex()
    if identity(target['cwd']) != target['identity']:
        raise ValueError('Project changed; send a fresh request.')
    inputs = []
    if action['start_work']:
        from . import orchestrator_guides
        inputs = routing_inputs.freeze(state,job,[target],action['research_ids'],action['artifact_ids'])
        inputs += [{**d,'project':None} for d in orchestrator_guides.selected(state,job['id'])]
    state.db.execute('''INSERT INTO task_creations
        (id,prompt,action,cwd,project_identity,title,start_work,input_manifest,status,created,expires)
        VALUES (?,?,?,?,?,?,?,?, 'queued',?,?)''', (job['id'],job['prompt'],json.dumps(action),
        target['cwd'],json.dumps(target['identity']),action['title'],int(action['start_work']),
        json.dumps(inputs),time.time(),time.time()+1800))
    return ('Queued new Codex task: '+action['title']+'\nProject: '+target['cwd']+
        '\nExisting local checkout; Codex configuration is inherited. '+
        ('The original request will start one turn after creation.' if action['start_work'] else 'No model turn was requested.'))


class Worker:
    def __init__(self, state, desktop_factory, client_factory=codex_app_server.Client):
        self.state, self.desktop_factory, self.client_factory = state, desktop_factory, client_factory
        self.started = False

    def finish(self, ident, status, message):
        state = self.state
        with state.db:
            row = state.db.execute('SELECT * FROM task_creations WHERE id=?',(ident,)).fetchone()
            state.db.execute('UPDATE task_creations SET status=?,error=? WHERE id=?',
                (status,None if status in ('created','submitted') else message,ident))
            event = 'task-created:'+str(ident)+':result'
            text = message + ('\nTask: '+row['task_id'] if row['task_id'] else '')
            state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',(event,row['task_id'],text))
            state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)',
                (event,relay_channels.request_channel(state,ident)))

    def call(self, client, row, method, params, status):
        with self.state.db:
            self.state.db.execute('UPDATE task_creations SET status=? WHERE id=?',(status,row['id']))
            self.state.db.execute('INSERT INTO task_creation_calls(request_id,method,params) VALUES (?,?,?)',
                (row['id'],method,json.dumps(params)))
        try:
            result = client.request(method,params)
        except Exception as exc:
            with self.state.db:
                self.state.db.execute('UPDATE task_creation_calls SET error=? WHERE request_id=? AND method=?',
                    (str(exc),row['id'],method))
            raise
        with self.state.db:
            self.state.db.execute('UPDATE task_creation_calls SET response=? WHERE request_id=? AND method=?',
                (json.dumps(result),row['id'],method))
        if method == 'thread/start':
            with self.state.db:
                thread = result['thread']
                tid = str(uuid.UUID(thread['id']))
                # Retain identity before any validation, rename or desktop call.
                self.state.db.execute("UPDATE task_creations SET task_id=?,rollout_path=?,status='created_pending' WHERE id=?",
                    (tid,thread.get('path'),row['id']))
                relay_channels.bind(self.state,'task',tid,relay_channels.request_channel(self.state,row['id']))
                self.state.db.execute('UPDATE capability_dispatches SET thread_id=? WHERE job_id=?',(tid,row['id']))
        return result

    def tick(self):
        state = self.state
        if not self.started:
            for row in state.db.execute("SELECT * FROM task_creations WHERE status IN ('connecting','creating','created_pending','naming','opening','submitting')").fetchall():
                # A crash can occur between recording the RPC result and indexing
                # its ID. Recover identity from that receipt without another call.
                if row['status']=='creating' and not row['task_id']:
                    call=state.db.execute("SELECT response FROM task_creation_calls WHERE request_id=? AND method='thread/start'",(row['id'],)).fetchone()
                    if call and call['response']:
                        try:
                            thread=json.loads(call['response'])['thread'];tid=str(uuid.UUID(thread['id']))
                            with state.db:
                                state.db.execute("UPDATE task_creations SET task_id=?,rollout_path=?,status='created_pending' WHERE id=?",(tid,thread.get('path'),row['id']))
                                relay_channels.bind(state,'task',tid,relay_channels.request_channel(state,row['id']))
                                state.db.execute('UPDATE capability_dispatches SET thread_id=? WHERE job_id=?',(tid,row['id']))
                            row=state.db.execute('SELECT * FROM task_creations WHERE id=?',(row['id'],)).fetchone()
                        except (ValueError,TypeError,KeyError):pass
                status = 'uncertain' if row['status'] in ('creating','submitting') else 'needs_inspection' if row['task_id'] else 'failed'
                self.finish(row['id'],status,'Interrupted during '+row['status']+'. No creation or turn was replayed. Inspect the saved receipt before continuing.')
            self.started = True
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            row = state.db.execute("SELECT * FROM task_creations WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return
            state.db.execute("UPDATE task_creations SET status='connecting' WHERE id=?",(row['id'],))
        try:
            if not state.get('orchestrator_routing_enabled',False):
                raise ValueError('Task routing was disabled before creation.')
            if time.time()>=row['expires'] or identity(row['cwd'])!=json.loads(row['project_identity']):
                raise ValueError('Creation expired or project changed; no task was created.')
            context = routing_inputs.handoff(state,row)
            with self.client_factory() as client:
                if identity(row['cwd'])!=json.loads(row['project_identity']):
                    raise ValueError('Project changed during connection.')
                result = self.call(client,row,'thread/start',{'cwd':row['cwd'],'ephemeral':False},'creating')
                thread = result['thread']; tid = thread['id']
                if Path(thread['cwd']).resolve()!=Path(row['cwd']):
                    raise ValueError('Created task reports a different project; no work was sent.')
                self.call(client,row,'thread/name/set',{'threadId':tid,'name':row['title']},'naming')
                # Codex defers writing an empty rollout. A full history read on
                # its owning app-server flushes it; rename, waiting and shutdown
                # do not. Keep that connection alive until persistence is proven.
                saved = self.call(client,row,'thread/read',
                    {'threadId':tid,'includeTurns':True},'created_pending')['thread']
                if (saved.get('id')!=tid or saved.get('path')!=thread.get('path')
                        or Path(saved.get('cwd','')).resolve()!=Path(row['cwd'])
                        or saved.get('turns')!=[] or saved.get('status',{}).get('type')!='idle'):
                    raise ValueError('New task history does not confirm the same empty, idle task; no work was sent.')
                path = Path(thread['path']) if thread.get('path') else None
                if not path or not path.is_file():
                    raise ValueError('Codex returned a task ID but no readable persisted history. Inspect that task before continuing.')
                if path.stat().st_size>1_000_000:
                    raise ValueError('New task history unexpectedly exceeds the empty-history limit.')
                with state.db:
                    state.db.execute('UPDATE task_creations SET history_sha256=? WHERE id=?',
                        (hashlib.sha256(path.read_bytes()).hexdigest(),row['id']))
                    state.db.execute('INSERT OR IGNORE INTO watched(id,path,offset,title,status,updated_at) VALUES (?,?,?,?,?,?)',
                        (tid,str(path),path.stat().st_size,row['title'],'idle',int(time.time())))
            if row['start_work']:
                with state.db:
                    state.db.execute("UPDATE task_creations SET status='opening' WHERE id=?",(row['id'],))
                with self.desktop_factory() as desktop:
                    owner = desktop.ready_owner(tid)
                    if identity(row['cwd'])!=json.loads(row['project_identity']):
                        raise ValueError('Project changed before work submission.')
                    if routing_inputs.handoff(state,row)!=context:
                        raise ValueError('Registered inputs changed before work submission.')
                    if task_status(state,tid,path)!='idle':
                        raise ValueError('The new task is no longer idle; no work was sent.')
                    prompt = ('Task Relay created this Codex task for the following original user request. '
                        'The task is already created: do not create another task. Address only the requested work. '
                        'Preserve project instructions and existing edits; inspect current changes and stop to clarify conflicting work. '
                        'Do not start other roadmap items or contact other tasks.\n\n--- ORIGINAL USER REQUEST ---\n'+row['prompt']+context)
                    with state.db:
                        state.db.execute("UPDATE task_creations SET status='submitting' WHERE id=?",(row['id'],))
                        state.db.execute('INSERT INTO task_creation_calls(request_id,method,params) VALUES (?,?,?)',
                            (row['id'],'desktop.start',json.dumps({'threadId':tid,'prompt':prompt})))
                    response = desktop.start(tid,prompt,owner)
                    with state.db:
                        state.db.execute("UPDATE task_creation_calls SET response=? WHERE request_id=? AND method='desktop.start'",
                            (json.dumps(response),row['id']))
                        state.db.execute("UPDATE watched SET status='running' WHERE id=?",(tid,))
            self.finish(row['id'],'submitted' if row['start_work'] else 'created',
                'Created Codex task: '+row['title']+'\nProject: '+row['cwd']+
                ('\nOriginal request submitted. Reply here to continue this task.' if row['start_work'] else '\nNo model turn started. Reply here to begin work.'))
        except Exception as exc:
            state.db.rollback()
            fresh = state.db.execute('SELECT * FROM task_creations WHERE id=?',(row['id'],)).fetchone()
            uncertain = fresh['status']=='submitting' or (fresh['status']=='creating' and not isinstance(exc,codex_app_server.Rejected))
            status = 'uncertain' if uncertain else 'needs_inspection' if fresh['task_id'] else 'failed'
            self.finish(row['id'],status,str(exc)+'\n'+
                ('Outcome uncertain; inspect before continuing. ' if uncertain else '')+
                ('The known task was preserved. ' if fresh['task_id'] else '')+'No automatic retry or provider fallback was made.')
