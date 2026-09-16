"""Telegram controls for already registered worker-runtime production plans."""
import hashlib
import json
import sqlite3
import re
import time
from pathlib import Path


def artifact_filename(state, artifact):
    """Readable download identity; immutable artifact paths and hashes stay intact."""
    row=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(artifact['run'],)).fetchone()
    brief=json.loads(row['plan']).get('brief','') if row else ''
    def slug(value,limit):
        value=re.sub(r'[^\w.-]+','-',str(value),flags=re.UNICODE).strip('-._')
        while len(value.encode('utf-8'))>limit:value=value[:-1]
        return value.rstrip('-._')
    title=slug(brief,64) or slug(artifact['run'],64) or 'production'
    step=slug(artifact['task'],32) or 'output'
    original=Path(artifact['path'])
    stem=slug(original.stem,40) or 'file'
    # The artifact ID identifies the exact attempt even if two versions share bytes.
    return f'{title}-{step}-{artifact["id"][:8]}-{stem}{original.suffix.lower()}'


def initialize(db):
    from . import result_handoff
    result_handoff.initialize(db)
    from task_relay import production_folders
    production_folders.initialize(db)
    from task_relay import production_continuations
    production_continuations.initialize(db)
    from task_relay import production_feedback
    production_feedback.initialize(db)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS production_uploads (
      id INTEGER PRIMARY KEY, run TEXT NOT NULL, file_id TEXT NOT NULL, filename TEXT NOT NULL,
      caption TEXT NOT NULL, declared_size INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      path TEXT, sha256 TEXT, bytes INTEGER, error TEXT);
    CREATE TABLE IF NOT EXISTS production_revisions (
      id INTEGER PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL, request TEXT NOT NULL,
      baseline TEXT NOT NULL, files TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', error TEXT);
    CREATE TABLE IF NOT EXISTS production_albums (
      chat_id INTEGER NOT NULL, album_id TEXT NOT NULL, run TEXT NOT NULL,
      PRIMARY KEY(chat_id,album_id));
    ''')


def upload_views(state, name):
    return [dict(r) for r in state.db.execute(
        "SELECT id,filename,caption,status,sha256,bytes,error FROM production_uploads WHERE run=? AND status NOT IN ('used','replaced') ORDER BY id", (name,))]


def receive(bridge, message, name, update_id):
    from task_relay.codex_inputs import upload, MAX_TOTAL
    from task_relay.orchestrator_images import UPLOAD_SCOPE
    if name != UPLOAD_SCOPE and not any(r['name'] == name for r in inspect(bridge.state)):
        raise ValueError('Reply to a production result or document to attach its guides.')
    _, file_id, filename, size = upload(message)
    state = bridge.state
    with state.db:
        state.db.execute('INSERT INTO incoming VALUES (?,?,NULL)', (update_id, 'handled'))
        rows = state.db.execute("SELECT COALESCE(bytes,declared_size) FROM production_uploads WHERE run=? AND status IN ('pending','ready')", (name,)).fetchall()
        if len(rows) >= 10 or sum(r[0] for r in rows) + size > MAX_TOTAL:
            raise ValueError('Use at most 10 new production guides and 50 MB total per revision.')
        state.db.execute('INSERT INTO production_uploads(id,run,file_id,filename,caption,declared_size) VALUES (?,?,?,?,?,?)',
            (update_id, name, file_id, filename, message.get('caption', ''), size))
        if message.get('media_group_id'):
            prior = state.db.execute('SELECT run FROM production_albums WHERE chat_id=? AND album_id=?', (message['chat']['id'],message['media_group_id'])).fetchone()
            if prior and prior[0] != name:
                raise ValueError('This album has conflicting production replies. Resend it to one production.')
            state.db.execute('INSERT OR IGNORE INTO production_albums VALUES (?,?,?)', (message['chat']['id'],message['media_group_id'],name))
        if message.get('message_id') is not None:
            state.db.execute('INSERT OR REPLACE INTO orchestrator_messages VALUES (?,?,?)',
                (message['chat']['id'], message['message_id'], None if name == UPLOAD_SCOPE else name))
        notice(state, name, 'upload-queued:' + str(update_id),
            ('Downloading attachment: ' + filename + '\nWait for “Attached”, then tell the orchestrator what to do with it. This upload is not assigned to a production.' if name == UPLOAD_SCOPE else
             'Downloading guide: ' + filename + '\nWait for “Guide attached”, then reply with your revision instructions. Uploading saves the caption but does not start work.'))


def notice(state, name, key, text):
    from task_relay.orchestrator_images import UPLOAD_SCOPE
    if name == UPLOAD_SCOPE:
        from task_relay.orchestrator_chat import queue_notice
        queue_notice(state,key.split(':')[-1]+':'+key.split(':')[0],text)
        return
    from . import workflow_files
    owner=workflow_files.owner_for_run(state,name)
    if owner:
        location=workflow_files.location_text(state,owner['id'])
        if location not in text:text+='\n\n'+location
    state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)', ('production:' + name + ':' + key, text))
    if getattr(state, 'channel', None):
        state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)',
                         ('production:' + name + ':' + key, state.channel))


def pending_execution_text(view,workflow=False):
    if not view.get('deferred_operations'):return ''
    pending=[v['description'] for v in view.get('pending_deliverables',{}).values()]
    return ('\nNot generated yet: '+('; '.join(pending) or ', '.join(view['deferred_operations']))+
        ('\nThis stage prepares inputs only. After selection, Relay will prepare the execution plan for the saved workflow. Start approves its exact script and limits.' if workflow else
         '\nThis stage prepares inputs only. After selecting the reviewed set, use Plan execution to prepare the remaining work. Start approves its exact script and limits.'))


def root(state):
    return state.media_dir.parent / 'orchestrator'


def inspect(state, focus=None, include_files=True):
    from orchestrator.storage import transaction
    db = state.db
    with transaction(db,write=False):
        result = []
        for row in db.execute('SELECT * FROM production_runs ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END,rowid DESC LIMIT 20',(focus,)):
            tasks = [dict(t) for t in db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id', (row['id'],))]
            specs = [json.loads(db.execute('SELECT spec FROM production_assignments WHERE id=?', (t['assignment'],)).fetchone()[0]) for t in tasks]
            from orchestrator.runtime import run_status, dependencies_ready, failure_detail
            progress = []
            for task, spec in zip(tasks, specs):
                attempt = db.execute('SELECT id,state,error,frozen,receipt,session FROM production_attempts WHERE id=?', (task['latest'],)).fetchone()
                frozen = json.loads(attempt['frozen']) if attempt else {}
                unavailable=db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND kind='capability_unavailable' ORDER BY id DESC LIMIT 1",(row['id'],task['id'])).fetchone() if not attempt else None
                target = next((t for t in tasks if t['id'] == spec.get('review_of')), None)
                current = not target or (bool(attempt) and frozen.get('review_target') == target['latest'] and task['status'] == 'completed')
                error=failure_detail(db,attempt) if attempt else json.loads(unavailable['data'])['reason'] if unavailable else None
                if task['status']=='blocked':
                    preflight=db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND kind='input_preflight_blocked' AND json_extract(data,'$.assignment')=? ORDER BY id DESC LIMIT 1",
                                         (row['id'],task['id'],task['assignment'])).fetchone()
                    if preflight:error='Input check failed before dispatch: '+json.loads(preflight['data'])['reason']
                if attempt and task['status']=='blocked' and error and 'Incomplete provider response' in error:
                    from .production_activity import provider_failure_detail
                    error=provider_failure_detail(attempt) or error
                progress.append({'latest_attempt':task['latest'], 'attempt_state':attempt['state'] if attempt else None,
                    'error':error,
                    'dependencies':[{ 'task':dep, 'status':next(t['status'] for t in tasks if t['id']==dep)} for dep in spec['dependencies']],
                    'runnable':task['status']=='queued' and dependencies_ready(spec,tasks,specs),
                    'review_target':frozen.get('review_target'), 'review_is_current':bool(target and current),
                    'output_is_current':bool(task['latest'] and current)})
                from . import production_activity
                progress[-1]['activity']=production_activity.snapshot(root(state),attempt,spec,json.loads(row['plan'])['backend'])
            from . import production_review_corrections
            correction=production_review_corrections.details(state,row['id']) if any(t['status']=='blocked' for t in tasks) else None
            if correction:
                for task,item in zip(tasks,progress):
                    if task['status']=='blocked' and task['id'] in (correction['target'],correction['reviewer']):
                        item['error']='Review requested corrections: '+correction['summary']+'\nRequested correction: '+correction['instruction']
            enabled = bool(state.get('production-enabled:' + row['id']))
            uploads = upload_views(state, row['id'])
            pending = state.db.execute("SELECT id,status,error FROM production_revisions WHERE run=? ORDER BY id DESC LIMIT 3", (row['id'],)).fetchall()
            fingerprint = json.dumps([dict(row), tasks, specs, enabled, uploads, [dict(p) for p in pending]], sort_keys=True)
            contracts = [{k: v for k, v in a.items() if k != 'revision'} for a in specs]
            for a in contracts:
                a['inputs'] = [i for i in a['inputs'] if not i.get('previous_delivery')]
            digest = hashlib.sha256(json.dumps([row['plan'], contracts], sort_keys=True).encode()).hexdigest()
            from task_relay import production_folders
            view = {'research_folder': production_folders.view(state, row['id']), 'name': row['id'], 'revision': int(hashlib.sha256(fingerprint.encode()).hexdigest()[:15], 16),
                    'contract_digest': digest,
                    'status': run_status(row['status'],tasks,specs), 'captured_at':time.time(), 'scheduler_enabled': enabled,
                    'feedback_files': uploads, 'feedback_requests': [dict(p) for p in pending],
                    'task_state': tasks,
                    'brief': json.loads(row['plan'])['brief'],
                    'deferred_operations': json.loads(row['plan']).get('deferred_operations',{}),
                    'pending_deliverables': {k:v for k,v in json.loads(row['plan']).get('deliverables',{}).items() if v.get('deferred_operation')},
                    'tasks': [{**{k: t[k] for k in ('id', 'status', 'attempts')},
                               **{k: a.get(k) for k in ('role', 'objective', 'instruction', 'limits', 'max_attempts', 'user_gate', 'review_of', 'execution')}, **p}
                              for t, a, p in zip(tasks, specs, progress)]}
            try:
                revision_target(view)
                view['revision_available'] = True
                view['revision_unavailable_reason'] = None
            except ValueError as exc:
                view['revision_available'] = False
                view['revision_unavailable_reason'] = str(exc)
            view['user_selection_available'] = any(t['status']=='awaiting_user' for t in tasks)
            continuation = state.db.execute('SELECT child,status,error FROM production_continuations WHERE parent=?', (row['id'],)).fetchone()
            view['continuation'] = dict(continuation) if continuation else None
            stage = state.db.execute('''SELECT l.parent,l.plan_id,l.child,p.status FROM production_stage_links l
                JOIN production_plans p ON p.id=l.plan_id WHERE l.parent=?''',(row['id'],)).fetchone()
            view['next_stage'] = dict(stage) if stage else None
            from orchestrator.artifact_replacements import view as replacements_view
            view['artifact_replacements']=replacements_view(db,row['id'])
            view['selections'] = [dict(d) for d in state.db.execute('''SELECT d.id,d.task,d.artifact,d.purpose,a.path,a.sha256
                FROM production_decisions d JOIN production_artifacts a ON a.id=d.artifact WHERE d.run=?''',(row['id'],))]
            if row['id'] == focus and include_files:
                from orchestrator.artifact_dependencies import run_lineage
                view['artifact_lineage'] = run_lineage(db, row['id'], limit=40)
                artifacts = [dict(a) for a in db.execute('SELECT * FROM production_artifacts WHERE run=? AND attempt IS NULL ORDER BY path', (row['id'],))]
                view['registered_files'] = [{k: a[k] for k in ('id', 'path', 'purpose', 'sha256', 'bytes')} for a in artifacts]
                view['reference_texts'] = []
                outputs = [dict(a) for a in db.execute('SELECT a.* FROM production_artifacts a JOIN production_tasks t ON t.latest=a.attempt AND t.run=a.run AND t.id=a.task WHERE a.run=? ORDER BY a.path', (row['id'],))]
                current_tasks = {t['id'] for t,p in zip(tasks,progress) if p['output_is_current']}
                view['historical_outputs'] = [{k:a[k] for k in ('id','task','attempt','path','purpose','sha256','bytes')}
                                              for a in outputs if a['task'] not in current_tasks]
                outputs = [a for a in outputs if a['task'] in current_tasks]
                view['latest_outputs'] = [{k: a[k] for k in ('id', 'task', 'attempt', 'path', 'purpose', 'sha256', 'bytes')} for a in outputs]
                view['output_texts'] = []
                view['omitted_output_texts'] = []
                view['omitted_reference_texts'] = []
                total = 0
                output_chars = 0
                # Keep the conversation small and current. Full registered
                # sources still go to workers; old guides/history are not all
                # inlined into every new chat request.
                def priority(a):
                    path=a['path']
                    return (0 if path.startswith('continuation/') else 1 if path.startswith('request/') else
                            3 if path.startswith(('continuation-history/','previous-stage/')) else 2,path)
                for a in sorted(artifacts,key=priority) + outputs:
                    if not a['path'].endswith(('.md', '.json', '.txt')) or (a in artifacts and not a['path'].endswith('.md') and a['path'] not in ('continuation/REQUEST.txt','continuation/USER_FEEDBACK.json')):
                        continue
                    is_output = a in outputs
                    if not is_output:
                        if total + a['bytes'] > 48000:
                            view['omitted_reference_texts'].append({'path':a['path'], 'bytes':a['bytes'], 'reason':'Conversation context limit; full registered file remains available to workers.'})
                            continue
                        total += a['bytes']
                    try:
                        from orchestrator.runtime import safe_file
                        blob=Path(a['blob'])
                        safe_file(root(state),str(blob.relative_to(root(state).resolve())))
                        raw = blob.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != a['sha256']:
                            raise ValueError('Registered file checksum changed.')
                        value = raw.decode('utf-8')
                    except (ValueError,OSError) as exc:
                        view['omitted_output_texts' if is_output else 'omitted_reference_texts'].append(
                            {'path':a['path'],'bytes':a['bytes'],'reason':'Text preview unavailable: '+str(exc)})
                        continue
                    if is_output:
                        excerpt = value[:max(0,min(20000,60000-output_chars))]
                        output_chars += len(excerpt)
                        view['output_texts'].append({'path':a['path'], 'task':a['task'], 'attempt':a['attempt'], 'text':excerpt,
                            'truncated':len(excerpt)<len(value), 'full_chars':len(value)})
                    else:
                        view['reference_texts'].append({'path':a['path'], 'text':value})
            result.append(view)
        return result


def start(state, name, revision):
    """Called within the same relay transaction as the action-card receipt."""
    view = next((r for r in inspect(state) if r['name'] == name), None)
    if not view or view['revision'] != revision:
        raise ValueError('The production run changed. Ask for a fresh action card.')
    if view['status'] != 'active' or view['scheduler_enabled'] or any(t['attempts'] for t in view['tasks']):
        raise ValueError('Only a registered, never-started production run can start here. Existing attempts are not replayed.')
    state.put('production-enabled:' + name, view['contract_digest'])


def revision_target(view):
    if view['status']=='paused':raise ValueError('Scheduling is paused. Resume before requesting a revision.')
    if any(t['status'] in ('launching','running','cancelling','uncertain') for t in view['tasks']):
        raise ValueError('Production work is still active or queued. Wait for its review result before requesting a revision.')
    if view['status'] in ('blocked','cancelled') or any(t['status']=='blocked' for t in view['tasks']):
        reasons = '; '.join(t['id'] + ': ' + (t.get('error') or t['status']) for t in view['tasks'] if t['status'] in ('blocked','cancelled'))
        exhausted = any(t['attempts'] >= t['max_attempts'] for t in view['tasks'])
        raise ValueError('Production is '+view['status']+', not running. '+reasons+
                         (' The attempt budget is exhausted; a new bounded stage is needed.' if exhausted else ' A recovery step is needed before revision.')+
                         ' Queued dependent work cannot proceed while its prerequisites are blocked. Your request is saved; no revision has started.')
    if view['scheduler_enabled'] or any(t['status']=='queued' and t.get('runnable',True) for t in view['tasks']):
        raise ValueError('Production work is still active or queued. Wait for its review result before requesting a revision.')
    targets = [t for t in view['tasks'] if t['status'] == 'awaiting_user' and not t['review_of']]
    if len(targets) != 1:
        raise ValueError('This run has no single preparation stage awaiting your review. A new bounded stage needs separate setup.')
    target = targets[0]
    if any(t['attempts'] >= t['max_attempts'] for t in view['tasks'] if t['id'] == target['id'] or t['review_of'] == target['id']):
        raise ValueError('The preparation/review attempt budget is exhausted. A new bounded stage is needed; existing attempt limits were not reset.')
    if any(p['status'] == 'queued' for p in view['feedback_requests']):
        raise ValueError('A revision is already queued for this production.')
    if any(f['status'] == 'pending' for f in view['feedback_files']):
        raise ValueError('A guide is still downloading. Wait for “Guide attached”, then request the revision.')
    if any(f['status'] == 'failed' for f in view['feedback_files']):
        raise ValueError('A guide failed to download. Resend it with the same filename before requesting a revision.')
    return target


def queue_revision(state, name, revision, job_id):
    view = next((r for r in inspect(state) if r['name'] == name), None)
    if not view or view['revision'] != revision:
        raise ValueError('The production or its guides changed. Ask for a fresh revision card.')
    target = revision_target(view)
    job = state.db.execute('SELECT prompt FROM orchestrator_chats WHERE id=?', (job_id,)).fetchone()
    files = [dict(f) for f in state.db.execute("SELECT * FROM production_uploads WHERE run=? AND status='ready' ORDER BY id", (name,))]
    state.db.execute('INSERT INTO production_revisions(id,run,task,request,baseline,files) VALUES (?,?,?,?,?,?)',
        (job_id, name, target['id'], job['prompt'], json.dumps({'tasks':view['task_state'], 'contract_digest':view['contract_digest']}), json.dumps(files)))


def runtime_digest(rt, name):
    run = rt.db.execute('SELECT plan FROM production_runs WHERE id=?', (name,)).fetchone()
    specs = [rt.spec(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id', (name,))]
    contracts = [{k:v for k,v in a.items() if k!='revision'} for a in specs]
    for a in contracts:
        a['inputs'] = [i for i in a['inputs'] if not i.get('previous_delivery')]
    return hashlib.sha256(json.dumps([run['plan'],contracts],sort_keys=True).encode()).hexdigest()


def review_resume_digest(state, name, view=None, legacy=False):
    view=view or next(v for v in inspect(state,name,include_files=False) if v['name']==name)
    if view['status']!='active' or view['scheduler_enabled'] or not any(t['runnable'] for t in view['tasks']):return None
    if any(t['status'] in ('blocked','cancelled','uncertain','running','launching','cancelling') for t in view['tasks']):return None
    digest=view['contract_digest'];epoch=state.get('production-control-epoch:'+name,0)
    grant=state.get('production-review-grant:'+name)
    if grant:return digest if grant['digest']==digest and grant['epoch']==epoch else None
    if not legacy:return None
    # Older versions lost the scheduling grant at a review gate. Explicit resume
    # may recover it only from an unchanged, actually started plan and selection.
    saved=state.get('production-status:'+name,{})
    if saved.get('status')!='awaiting_user':return None
    if state.db.execute("SELECT 1 FROM production_control_cards WHERE run=? AND status='applied'",(name,)).fetchone():return None
    if not state.db.execute('SELECT 1 FROM production_decisions WHERE run=?',(name,)).fetchone():return None
    row=state.db.execute("SELECT plan FROM production_plans WHERE run=? AND status='started'",(name,)).fetchone()
    current=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(name,)).fetchone()
    if not row or json.loads(row[0])!=json.loads(current[0]):return None
    expected={t['id']:t for t in json.loads(row[0])['tasks']}
    actual={r['task']:json.loads(r['spec']) for r in state.db.execute('''SELECT a.task,a.spec FROM production_tasks t
        JOIN production_assignments a ON a.id=t.assignment WHERE t.run=?''',(name,))}
    return digest if actual==expected else None


def resume_review(state,name,legacy=False):
    from orchestrator.runtime import Runtime
    if not state.db.in_transaction:raise ValueError('Resume requires a transaction.')
    digest=review_resume_digest(state,name,legacy=legacy)
    if not digest:raise ValueError('This stage cannot resume from a review pause: its authorization, tasks or plan changed. No work was started.')
    state.put('production-enabled:'+name,digest)
    state.put('production-review-grant:'+name,False)
    Runtime(root(state),connection=state.db).event(name,None,None,'review_scheduling_resumed',{'contract_digest':digest,'legacy_recovery':legacy})
    return 'Scheduling resumed for '+name+' within its existing approved plan. Only remaining tasks may start; no attempts were reset.'


def resume_review_evidence(state, name, request):
    """Explicit recovery of an old scheduler deadlock; retain every assignment."""
    from orchestrator import contracts as c
    from orchestrator.runtime import Runtime
    if not state.db.in_transaction:
        raise ValueError('Resume requires a transaction.')
    c.nonempty(request, 'Exact recovery request')
    view = next(v for v in inspect(state, name, include_files=False) if v['name'] == name)
    saved = state.get('production-status:' + name, {})
    if (view['status'] != 'active' or view['scheduler_enabled'] or saved.get('status') != 'blocked'
        or state.get('production-control-epoch:' + name, 0) != 0
        or any(t['status'] not in ('queued', 'awaiting_review', 'completed') for t in view['tasks'])):
        raise ValueError('This is not an unchanged inspection/review scheduling deadlock.')
    current_tasks = sorted([[t['id'], t['status'], t['attempts']] for t in view['tasks']])
    if saved.get('tasks') != current_tasks:
        raise ValueError('Task state changed since the recorded scheduling blocker.')
    row = state.db.execute("SELECT plan FROM production_plans WHERE run=? AND status='started'", (name,)).fetchone()
    current = state.db.execute('SELECT plan,status FROM production_runs WHERE id=?', (name,)).fetchone()
    if not row or current['status'] != 'active' or json.loads(row[0]) != json.loads(current['plan']):
        raise ValueError('An unchanged, previously started plan is required.')
    rt = Runtime(root(state), connection=state.db)
    tasks = rt.db.execute('SELECT * FROM production_tasks WHERE run=?', (name,)).fetchall()
    specs = [rt.spec(t) for t in tasks]
    if {a['id']:a for a in specs} != {a['id']:a for a in json.loads(row[0])['tasks']}:
        raise ValueError('Approved assignments changed.')
    c.validate_review_order(specs)
    evidence = c.review_evidence_dependencies(specs)
    runnable = [t for t in view['tasks'] if t['runnable']]
    if not runnable or any(t['id'] not in evidence or t['attempts'] for t in runnable):
        raise ValueError('Only previously planned, unstarted review inspections may recover here.')
    if state.db.execute("SELECT 1 FROM production_control_cards WHERE run=? AND status='applied'", (name,)).fetchone():
        raise ValueError('An explicit control decision prevents automatic scheduling recovery.')
    for target in {d for t in runnable for d in evidence[t['id']]}:
        task = rt.task(name, target)
        attempt = state.db.execute('SELECT state,frozen FROM production_attempts WHERE id=?', (task['latest'],)).fetchone()
        if task['status'] != 'awaiting_review' or not attempt or attempt['state'] != 'completed':
            raise ValueError('A successfully delivered candidate is required; failed work cannot resume here.')
        for output in rt.spec(task)['outputs']:
            artifact = rt.output(name, target, output['path'])
            from orchestrator.runtime import file_hash
            if file_hash(artifact['blob']) != artifact['sha256']:
                raise ValueError('The candidate artifact changed.')
    state.put('production-enabled:' + name, view['contract_digest'])
    rt.event(name, None, None, 'review_evidence_scheduling_resumed',
             {'request': request, 'contract_digest': view['contract_digest'],
              'remaining_inspections': [t['id'] for t in runnable], 'attempts_reset': False})
    return 'Resumed the approved inspection and review; successful modeling is retained.'


class Worker:
    def __init__(self, state, runtime_factory=None, telegram=None):
        self.state, self.runtime, self.runtime_factory, self.cursor = state, None, runtime_factory, 0
        self.telegram = telegram

    def get_runtime(self):
        if self.runtime is None:
            from orchestrator.runtime import Runtime
            self.runtime = self.runtime_factory(root(self.state)) if self.runtime_factory else Runtime(root(self.state), connection=self.state.db)
            if self.runtime.db is not self.state.db:
                raise ValueError('Production workers must share the relay database connection.')
        return self.runtime

    def download(self):
        row = self.state.db.execute("SELECT * FROM production_uploads WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if not row or not self.telegram:
            return
        from task_relay.codex_inputs import MAX_FILE, MAX_TOTAL
        path = root(self.state).parent / 'production-guides' / str(row['id']) / row['filename']
        try:
            self.telegram.download_file(row['file_id'], path, MAX_FILE)
            data = path.read_bytes()
            if not data or len(data) > MAX_FILE:
                raise ValueError('Guide is empty or exceeds 20 MB.')
            with self.state.db:
                others = self.state.db.execute("SELECT COALESCE(bytes,declared_size) FROM production_uploads WHERE run=? AND id!=? AND status IN ('pending','ready')", (row['run'],row['id'])).fetchall()
                if len(data) + sum(r[0] for r in others) > MAX_TOTAL:
                    raise ValueError('Guides exceed 50 MB total.')
                path.chmod(0o400)
                self.state.db.execute("UPDATE production_uploads SET status='ready',path=?,sha256=?,bytes=? WHERE id=?",
                    (str(path.resolve()), hashlib.sha256(data).hexdigest(), len(data), row['id']))
                self.state.db.execute("UPDATE production_uploads SET status='replaced' WHERE run=? AND filename=? AND status='failed'", (row['run'],row['filename']))
                from task_relay.orchestrator_images import UPLOAD_SCOPE
                text = (f"Attached: {row['filename']}\nTell the orchestrator what to do with this file, for example ‘Make a logo based on this drawing’." if row['run']==UPLOAD_SCOPE else
                        f"Guide attached: {row['filename']}\nReply with the changes you want. The revision card will include this guide and its caption.")
                notice(self.state,row['run'],'upload:'+str(row['id']),text)
        except Exception:
            with self.state.db:
                self.state.db.execute("UPDATE production_uploads SET status='failed',error='Download failed; please resend this guide.' WHERE id=?", (row['id'],))
                notice(self.state,row['run'],'upload:'+str(row['id']),f"Could not attach {row['filename']}. Please resend it (up to 20 MB).")

    def apply_revision(self):
        row = self.state.db.execute("SELECT * FROM production_revisions WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return
        rt = self.get_runtime()
        try:
            # Assignment, input usage, request receipt and scheduling commit together.
            # Historical receipts still recognize handoffs committed before migration.
            with rt.transaction():
                if rt.status(row['run'])['status'] in ('paused','cancelled'):
                    raise ValueError('Production is paused or cancelled; revision was not dispatched.')
                receipt = rt.db.execute("SELECT data FROM production_events WHERE run=? AND kind='telegram_revision_applied' AND json_extract(data,'$.request_id')=?", (row['run'],row['id'])).fetchone()
                if receipt:
                    digest = json.loads(receipt[0])['contract_digest']
                else:
                    baseline = [dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id', (row['run'],))]
                    expected = json.loads(row['baseline'])
                    if baseline != expected['tasks'] or runtime_digest(rt, row['run']) != expected['contract_digest']:
                        raise ValueError('Production changed before revision dispatch. Request a fresh revision.')
                    files = json.loads(row['files'])
                    from orchestrator.runtime import safe_file, file_hash
                    for f in files:
                        p = safe_file(root(self.state).parent / 'production-guides', str(f['id']) + '/' + f['filename'])
                        if str(p.resolve()) != f['path'] or p.stat().st_size != f['bytes'] or file_hash(p) != f['sha256']:
                            raise ValueError('An attached guide changed. Resend it before revising.')
                    instruction = row['request']
                    if files:
                        instruction += '\n\nUser guide captions:\n' + '\n'.join(f["filename"] + ': ' + f['caption'] for f in files)
                    rt._revise(row['run'], row['task'], instruction, 'telegram:' + str(row['id']))
                    # Freeze the verbatim feedback as a shared producer/reviewer input.
                    feedback = root(self.state).parent / 'production-feedback' / (str(row['id']) + '.txt')
                    feedback.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    feedback.write_text(instruction)
                    inputs = []
                    for source, name in [(feedback, 'feedback.txt')] + [(Path(f['path']),str(f['id'])+'-'+f['filename']) for f in files]:
                        path = 'feedback/' + str(row['id']) + '/' + name
                        aid = rt.register(source.resolve(), 'User revision guidance', run=row['run'], path=path)
                        inputs.append(dict(artifact=aid,path=path,purpose='User revision guidance',authority='User guidance within the original stage bounds; conflicts require escalation'))
                    reviewer = rt.reviewer(row['run'],row['task'])
                    for tid in [row['task']] + ([reviewer['id']] if reviewer else []):
                        task = rt.task(row['run'],tid); spec = rt.spec(task)
                        spec['inputs'].extend(inputs)
                        from orchestrator import contracts
                        aid = rt.new_assignment(row['run'], contracts.assignment(spec))
                        rt.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?', (aid,row['run'],tid))
                    # Compute the same contract digest on the uncommitted runtime view.
                    digest = runtime_digest(rt, row['run'])
                    rt.event(row['run'],row['task'],None,'telegram_revision_applied',dict(request_id=row['id'],contract_digest=digest))
                self.state.db.execute("UPDATE production_revisions SET status='applied' WHERE id=?", (row['id'],))
                for f in json.loads(row['files']):
                    self.state.db.execute("UPDATE production_uploads SET status='used' WHERE id=?", (f['id'],))
                self.state.put('production-enabled:' + row['run'],digest)
                notice(self.state,row['run'],'revision:'+str(row['id']),'Revision scheduled: '+row['run']+'\nYour exact feedback and attached guides were registered for preparation and independent review. Existing attempt limits and the user review gate still apply.')
        except ValueError as exc:
            with self.state.db:
                self.state.db.execute("UPDATE production_revisions SET status='failed',error=? WHERE id=?", (str(exc),row['id']))
                notice(self.state,row['run'],'revision:'+str(row['id']),'Revision could not start: '+str(exc))

    def tick(self):
        self.download()
        from task_relay import production_continuations
        production_continuations.apply(self)
        self.apply_revision()
        # Always drain existing workers, including paused/cancelled stages and
        # stages whose scheduling authorization was disabled after a change.
        names = [r[0] for r in self.state.db.execute('SELECT id FROM production_runs')
                 if self.state.get('production-enabled:'+r[0]) or self.state.db.execute(
                     "SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')",(r[0],)).fetchone()]
        if not names:
            return
        self.get_runtime()
        name = names[self.cursor % len(names)]; self.cursor += 1
        view = next(r for r in inspect(self.state,name) if r['name'] == name)
        enabled=self.state.get('production-enabled:' + name)
        if enabled and enabled != view['contract_digest']:
            with self.state.db:
                self.state.put('production-enabled:' + name, False)
                self.state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)',
                    ('production:' + name + ':changed', 'Production plan changed: ' + name + '. Scheduling stopped; review its saved state.'))
            enabled=False
        from .production_repairs import dispatch_allowed
        result = self.runtime.tick(name,dispatch=bool(enabled) and dispatch_allowed(self.state,name))
        current = next(r for r in inspect(self.state,name) if r['name'] == name)
        summary = sorted([[t['id'], t['status'], t['attempts']] for t in result['tasks']])
        previous_status=self.state.get('production-status:'+name,{})
        previous_tasks={t[0]:t[1:] for t in previous_status.get('tasks',[])}
        with self.state.db:
            for task in current['tasks']:
                if task['status']=='running' and previous_tasks.get(task['id'])!=['running',task['attempts']]:
                    from .production_activity import lines as activity_lines
                    notice(self.state,name,'working:'+task['latest_attempt'],
                           'Production: '+name+'\n'+task['id']+': Running\n'+'\n'.join(activity_lines(task)))
            self.state.put('production-status:' + name, {'status': result['status'], 'tasks': summary})
            if result['status']=='paused':return
            if result['status'] != 'active':
                if result['status']=='awaiting_user' and enabled==current['contract_digest']:
                    self.state.put('production-review-grant:'+name,{'digest':enabled,
                        'epoch':self.state.get('production-control-epoch:'+name,0)})
                elif result['status']!='awaiting_user':
                    self.state.put('production-review-grant:'+name,False)
                self.state.put('production-enabled:' + name, False)
                # One terminal notification; no per-poll or per-tool chatter.
                status = 'Ready for your review' if result['status'] == 'awaiting_user' else result['status']
                if current['deferred_operations'] and result['status'] in ('awaiting_user','completed'):
                    status = 'Preparation ready; execution pending'
                if any(a['state'] in ('launching','running','cancelling','uncertain') for a in result['attempts']):return
                version = hashlib.sha256(json.dumps([result['status'],summary]).encode()).hexdigest()[:16]
                event = 'production:' + name + ':result:' + version
                details = []
                for task in current['tasks']:
                    line = f"{task['id']}: {task['status']}; attempts {task['attempts']}/{task['max_attempts']}"
                    if task['status']=='queued' and not task['runnable']:
                        line += ' (waiting on ' + ', '.join(d['task']+': '+d['status'] for d in task['dependencies']) + ')'
                    from .production_activity import lines as activity_lines,blocker_lines
                    reason=blocker_lines(task)
                    if reason:line+='\n'+'\n'.join(reason)
                    details.append(line+'\n'+'\n'.join(activity_lines(task)))
                ending = ('\nWorker termination is confirmed. Saved partial outputs follow where available; they are not accepted results.'
                          if result['status']=='cancelled' else
                          '\nCurrent draft outputs follow where available. They are not approved results. A recovery step is needed; waiting will not resolve this blocker.'
                          if result['status']=='blocked' else
                          '\nSaved outputs follow as documents. Use a Select button for the exact file or declared file set, or reply with feedback to request a revision. You can also attach guides and then send your instructions. A revision card shows what will run. No next stage starts automatically.')
                from . import pipelines
                workflow=pipelines.owns_run(self.state,name)
                if pipelines.owner_of_run(self.state,name):ending=ending.replace('No next stage starts automatically.',pipelines.continuation_text(self.state,name))
                from . import production_review_corrections
                correction=production_review_corrections.text(self.state,name) if result['status']=='blocked' else ''
                if correction:
                    details.insert(0,correction)
                    ending='\nExisting files remain available as unapproved candidates. Use Plan correction above.'
                self.state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)', (event, f'Production: {name}\n{status}\n\n' +
                    '\n\n'.join(details) + pending_execution_text(current,workflow) + '\n'+ending))
                current_outputs = {t['id'] for t in current['tasks'] if t['output_is_current']}
                for task in result['tasks']:
                    if task['id'] not in current_outputs:
                        continue
                    for a in result['artifacts']:
                        if not a['attempt'] or a['attempt'] != task['latest'] or a['task'] != task['id']:
                            continue
                        artifact = self.runtime.artifact(a['id'])
                        filename=artifact_filename(self.state,artifact)
                        queue_artifact_preview(self.state,event,artifact,filename,name)
                        self.state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                            ('production-output:' + a['id'], event, artifact['blob'],
                             filename, 'original', name + '\n' + task['id'] + ' · attempt ' + str(task['attempts']) + '\n' + filename + '\n' + a['purpose']))

    def close(self):
        if self.runtime is not None:
            self.runtime.close()


def queue_artifact_preview(state,event,artifact,filename,title):
    """Queue bounded image/video previews; original delivery remains independent."""
    from task_relay import media
    path=Path(artifact['blob']);suffix=Path(filename).suffix.lower()
    video=suffix=='.mp4'
    if suffix not in ('.png','.jpg','.jpeg','.webp','.mp4') or not 0<path.stat().st_size<=(media.MAX_FILE if video else media.MAX_PHOTO):return
    with path.open('rb') as stream:header=stream.read(16)
    if video:
        if header[4:8]!=b'ftyp':return
    elif not media.valid_image(header,suffix):return
    state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
        ('production-preview:'+artifact['id'],event,str(path),filename,'video' if video else 'preview',title+'\n'+filename+' — preview'))
