"""Natural-language destination selection with exact-source, durable Codex dispatch."""
import hashlib
import json
from pathlib import Path
import secrets
import re
import time
from task_relay import routing_inputs

ACTIVE = ('queued', 'opening', 'submitting', 'uncertain')


def initialize(db):
    routing_inputs.initialize(db)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS task_routes (
            id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, prompt TEXT NOT NULL,
            candidates TEXT NOT NULL, task_id TEXT, cwd TEXT, status TEXT NOT NULL,
            created REAL NOT NULL, expires REAL NOT NULL, error TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_route_per_task ON task_routes(task_id)
            WHERE status IN ('queued','opening','submitting','uncertain');
        DROP INDEX IF EXISTS one_route_per_project;
    ''')
    if 'guide_proposal' not in {r[1] for r in db.execute('PRAGMA table_info(task_routes)')}:
        db.execute('ALTER TABLE task_routes ADD COLUMN guide_proposal TEXT')
    if 'guide_decision' not in {r[1] for r in db.execute('PRAGMA table_info(task_routes)')}:
        db.execute('ALTER TABLE task_routes ADD COLUMN guide_decision TEXT')
    if 'reference_pack_id' not in {r[1] for r in db.execute('PRAGMA table_info(task_routes)')}:
        db.execute('ALTER TABLE task_routes ADD COLUMN reference_pack_id TEXT')
    if 'input_manifest' not in {r[1] for r in db.execute('PRAGMA table_info(task_routes)')}:
        db.execute('ALTER TABLE task_routes ADD COLUMN input_manifest TEXT')


def task_conflict(state, task_id, excluding=None):
    """Reserve destinations, not every independent task sharing a checkout."""
    if state.db.execute("SELECT 1 FROM task_creations WHERE task_id=? AND status IN ('created_pending','naming','opening','submitting','uncertain','needs_inspection')",(task_id,)).fetchone():
        return 'A new-task creation or first turn needs inspection before more work can be sent.'
    if state.db.execute("SELECT 1 FROM task_routes WHERE task_id=? AND id!=? AND status='guides_pending' AND expires>?",(task_id,excluding if excluding is not None else -1,time.time())).fetchone():
        return 'A guide choice is waiting for this task. Use its Use guides, Continue without guides, or Cancel request button.'
    for row in state.db.execute('SELECT data FROM workflows'):
        d = json.loads(row[0])
        owned = {d.get('strategy_id'), d.get('executor_id'), (d.get('operation') or {}).get('thread_id')}
        if task_id in owned and (d['status'] == 'active' or (d.get('operation') and d['phase'] in ('dispatching','planning','executing','reviewing','recovery_planning'))):
            return 'A linked workflow owns this task; use its planning/run controls.'
    if state.db.execute("SELECT 1 FROM backend_jobs WHERE thread_id=? AND status IN ('queued','running','waiting')", (task_id,)).fetchone():
        return 'A provider job is active in this task.'
    if state.db.execute("SELECT 1 FROM task_routes WHERE task_id=? AND id!=? AND status IN ('queued','opening','submitting','uncertain')", (task_id, excluding if excluding is not None else -1)).fetchone():
        return 'Another routed request owns this task; inspect its status before sending more work.'
    return None


def catalog(state, task_source=None):
    from task_relay.bridge import local_tasks, recent_status
    result = []
    for t in (task_source or local_tasks)():
        cwd = str(Path(t['cwd']).resolve())
        path = Path(t['rollout_path'])
        try:
            stat = path.stat()
        except OSError:
            continue
        from .task_creation import task_status
        status = task_status(state,t['id'],path)
        watched = state.db.execute('SELECT status FROM watched WHERE id=?', (t['id'],)).fetchone()
        if status == 'idle' and watched and watched['status'] == 'running':
            status = 'running'  # Covers the gap before the new turn reaches the rollout.
        identity = [t['id'], cwd, str(path), stat.st_size, stat.st_mtime_ns, t.get('updated_at')]
        result.append({'id': t['id'], 'title': t.get('name') or t.get('title', '')[:150] or t['id'],
            'project': Path(cwd).name, 'cwd': cwd,
            'description_excerpt': (t.get('title') or '')[:800],
            'status': status,
            'routing_blocker': task_conflict(state, t['id']),
            'fingerprint': hashlib.sha256(json.dumps(identity).encode()).hexdigest()})
    if len(result) > 300:
        raise ValueError('Task catalog exceeds 300 tasks; narrow the catalog before routing.')
    return result


def validate_selection(state, candidate, task_source=None, excluding=None):
    current = catalog(state, task_source)
    target = next((t for t in current if t['id'] == candidate['id']), None)
    if target is None or target['fingerprint'] != candidate['fingerprint']:
        raise ValueError('The selected task changed or is no longer available. Send a fresh request.')
    if target['status'] != 'idle':
        raise ValueError('The selected task is busy or its state is unknown. No instruction was sent.')
    watched = state.db.execute('SELECT status FROM watched WHERE id=?', (target['id'],)).fetchone()
    if watched and watched['status']=='running':
        raise ValueError('This task has a running or just-submitted turn. Wait for completion before sending more work.')
    conflict = task_conflict(state, target['id'], excluding)
    if conflict:
        raise ValueError(conflict)
    if state.db.execute("SELECT 1 FROM incoming WHERE thread_id IN (SELECT id FROM watched WHERE path!='') AND status IN ('received','submitting') AND thread_id=?", (target['id'],)).fetchone():
        raise ValueError('An ordinary message is being submitted to this task.')
    return target


def register(state, job, candidates, choose, task_source=None, reference_pack_id=None, research_ids=None, artifact_ids=None):
    if reference_pack_id:
        from task_relay.reference_packs import handoff
        handoff(state,reference_pack_id)
    target = None if choose else validate_selection(state, candidates[0], task_source)
    try:
        if artifact_ids is None and routing_inputs.artifact_catalog(state):
            raise ValueError('Select artifact_ids explicitly, or [] for no generated files.')
        inputs = routing_inputs.freeze(state,job,candidates,research_ids,artifact_ids)
        from task_relay import orchestrator_guides
        # A conversation-level choice can intentionally use a guide from another
        # project. It has already been confirmed for this exact user request.
        inputs += [{**d,'project':None} for d in orchestrator_guides.selected(state,job['id'])]
    except (ValueError,OSError) as exc:
        from task_relay.capabilities import CapabilityError
        raise CapabilityError('Could not prepare the requested sources/guides: '+str(exc)) from exc
    state.db.execute('INSERT INTO task_routes(id,token,prompt,candidates,task_id,cwd,status,created,expires) VALUES (?,?,?,?,?,?,?,?,?)',
        (job['id'], secrets.token_hex(12), job['prompt'], json.dumps(candidates),
         target['id'] if target else None, target['cwd'] if target else None,
         'choosing' if choose else 'queued', time.time(), time.time() + 1800))
    state.db.execute('UPDATE task_routes SET input_manifest=? WHERE id=?',(json.dumps(inputs),job['id']))
    if reference_pack_id:
        state.db.execute('UPDATE task_routes SET reference_pack_id=? WHERE id=?',(reference_pack_id,job['id']))
    if target:
        proposal = prepare_guides(state,job,target)
        if proposal:return proposal
    return (('Choose the Codex task for this request. Your complete original message will be sent after your choice.' if choose else
            'Queued for Codex: ' + target['title'] + '\nProject: ' + target['project'] + '\nYour complete original message will be sent. This starts one task turn.')+
            ('\nRegistered inputs: '+', '.join(Path(d['name']).name for d in inputs) if inputs else ''))


def prepare_guides(state,job,target):
    if state.db.execute("SELECT 1 FROM orchestrator_guide_choices WHERE job_id=? AND status='selected'",(job['id'],)).fetchone():
        return None
    proposal=routing_inputs.propose_guides(state,job,target['cwd'])
    if not proposal['guides'] and not proposal['warnings']:return None
    state.db.execute("UPDATE task_routes SET status='guides_pending',guide_proposal=? WHERE id=?",(json.dumps(proposal),job['id']))
    names='\n'.join(str(i+1)+'. '+d['name'] for i,d in enumerate(proposal['guides']))
    return ('Found potentially relevant guides for '+target['title']+'.\nProject: '+target['cwd']+
            ('\n'+names if names else '\nNo guide match was found in the completed portion of the search.')+
            ('\n'+' '.join(proposal['warnings']) if proposal['warnings'] else '')+
            '\nUse these guides for this request? The listed versions are saved for your choice. '
            'No task turn has started. Existing project instructions still apply.')


def controls(state, event_id):
    if not event_id.startswith(('orchestrator:','capability-request:')):return None
    parts=event_id.split(':')
    row=state.db.execute("SELECT * FROM task_routes WHERE id=? AND status IN ('choosing','guides_pending') AND expires>?",(parts[1],time.time())).fetchone()
    if not row:return None
    prefix='route:'+row['token']+':'
    if row['status']=='guides_pending':
        # The original destination card must not turn into a guide approval card.
        if len(parts)==2 and row['guide_decision']=='destination_chosen':return None
        buttons=[]
        guides=json.loads(row['guide_proposal'])['guides']
        if len(guides)>1:
            buttons.extend([{'text':('Use '+str(i+1)+': '+Path(d['name']).name)[:100],
                             'callback_data':prefix+'guide-'+str(i)}] for i,d in enumerate(guides))
        if guides:
            buttons.append([{'text':'Use all guides' if len(guides)>1 else 'Use guides','callback_data':prefix+'use-guides'}])
        buttons.append([{'text':'Continue without guides','callback_data':prefix+'skip-guides'}])
    else:
        buttons=[[{'text':(c['title']+' · '+c['project'])[:100],'callback_data':prefix+str(i)}]
                 for i,c in enumerate(json.loads(row['candidates']))]
    return {'inline_keyboard':buttons+[[{'text':'Cancel request','callback_data':prefix+'cancel'}]]}


def callback(bridge, update, task_source=None):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith('route:'):return False
    state=bridge.state;user=q.get('from',{});chat=q.get('message',{}).get('chat',{})
    if user.get('is_bot') or user.get('id')!=state.get('user_id') or chat.get('id')!=state.get('chat_id') or chat.get('type')!='private':return True
    message='That choice expired or was already handled.'
    try:
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            parts=raw.split(':')
            row=state.db.execute("SELECT * FROM task_routes WHERE token=? AND status IN ('choosing','guides_pending') AND expires>?",(parts[1] if len(parts)==3 else '',time.time())).fetchone()
            if row:
                ident=str(row['id']);pending=row['status']=='guides_pending'
                events=['orchestrator:'+ident,'capability-request:'+ident]
                if pending and row['guide_decision']=='destination_chosen':events=['orchestrator:'+ident+':guides']
                delivered=any(state.db.execute('SELECT 1 FROM outbox WHERE id=? AND sent IS NOT NULL AND sent!=0',(event,)).fetchone() for event in events)
                if not delivered:raise ValueError('Wait for the complete choice card before selecting.')
                action=parts[2]
                if action=='cancel':
                    state.db.execute("UPDATE task_routes SET status='cancelled',guide_decision='cancelled' WHERE id=?",(row['id'],))
                    message='Cancelled. Nothing was sent.'
                else:
                    choices=json.loads(row['candidates'])
                    if pending:
                        guides=json.loads(row['guide_proposal'])['guides']
                        single=re.fullmatch(r'guide-(\d+)',action)
                        if action not in ('use-guides','skip-guides') and not (single and int(single[1])<len(guides)):
                            raise ValueError('Use the guide choice buttons on the latest card.')
                        candidate=next(c for c in choices if c['id']==row['task_id'])
                    else:
                        if not action.isdigit() or not 0<=int(action)<len(choices):raise ValueError('Invalid task choice.')
                        candidate=choices[int(action)]
                    target=validate_selection(state,candidate,task_source,excluding=row['id'])
                    if pending:
                        manifest=json.loads(row['input_manifest'] or '[]')
                        if action!='skip-guides':
                            manifest+=guides if action=='use-guides' else [guides[int(single[1])]]
                            if sum(d['bytes'] for d in manifest)>routing_inputs.MAX_BYTES:raise ValueError('Selected inputs exceed the 2 MB handoff limit.')
                            routing_inputs.handoff(state,{**dict(row),'input_manifest':json.dumps(manifest)})
                        state.db.execute("UPDATE task_routes SET status='queued',input_manifest=?,guide_decision=? WHERE id=?",(json.dumps(manifest),action,row['id']))
                        message='Queued for Codex: '+target['title']+(' with the selected guides.' if action!='skip-guides' else ' without optional guides.')
                        event='orchestrator:'+ident+':chosen'
                    else:
                        state.db.execute("UPDATE task_routes SET task_id=?,cwd=?,status='queued',guide_decision='destination_chosen' WHERE id=?",(target['id'],target['cwd'],row['id']))
                        proposal=prepare_guides(state,row,target)
                        message=proposal or 'Queued for Codex: '+target['title']
                        event='orchestrator:'+ident+(':guides' if proposal else ':chosen')
                    state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)',(event,message))
    except (ValueError,OSError) as exc:message=str(exc)
    from task_relay.bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=message[:200],show_alert=True)
    except BridgeError:pass
    return True


class Worker:
    def __init__(self,state,desktop_factory,task_source=None):
        self.state,self.desktop_factory,self.task_source=state,desktop_factory,task_source
        self.started=False

    def finish(self,row,status,text):
        with self.state.db:
            self.state.db.execute('UPDATE task_routes SET status=?,error=? WHERE id=?',(status,text if status!='submitted' else None,row['id']))
            self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                ('routed:'+str(row['id'])+':result',row['task_id'],text))

    def tick(self):
        state=self.state
        if not self.started:
            # No automatic replays across the boundary where IPC may have acted.
            for row in state.db.execute("SELECT * FROM task_routes WHERE status IN ('opening','submitting')").fetchall():
                self.finish(row,'uncertain' if row['status']=='submitting' else 'failed',
                    'Routed request interrupted during '+row['status']+'. No automatic retry was made. Inspect the task before sending again.')
            self.started=True
        row=state.db.execute("SELECT * FROM task_routes WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return
        try:
            if row['expires'] <= time.time():
                raise ValueError('The queued routing request expired before dispatch. Send a fresh request.')
            choices=json.loads(row['candidates']); candidate=next(c for c in choices if c['id']==row['task_id'])
            with state.db:
                state.db.execute('BEGIN IMMEDIATE')
                target=validate_selection(state,candidate,self.task_source,excluding=row['id'])
                changed=state.db.execute("UPDATE task_routes SET status='opening' WHERE id=? AND status='queued'",(row['id'],)).rowcount
            if not changed:
                return
            with self.desktop_factory() as desktop:
                owner=desktop.ready_owner(target['id'])
                reference_context = ''
                if row['reference_pack_id']:
                    from task_relay.reference_packs import handoff
                    reference_context = handoff(state,row['reference_pack_id'])
                reference_context += routing_inputs.handoff(state,row)
                # Opening and reloading can change history; never route stale work.
                with state.db:
                    state.db.execute('BEGIN IMMEDIATE')
                    validate_selection(state,candidate,self.task_source,excluding=row['id'])
                    state.db.execute("UPDATE task_routes SET status='submitting' WHERE id=?",(row['id'],))
                    from task_relay import relay_channels
                    relay_channels.bind(state, 'task', target['id'], relay_channels.request_channel(state, row['id']))
                prompt=('Task Relay routed this original user request to this Codex task. Address only the requested work; '
                        'preserve its constraints and existing project instructions. Other tasks may be working in the same project: inspect current changes, preserve edits you did not make, and stop to clarify any conflicting work. Do not start additional roadmap items or contact other tasks. '
                        'If this task is not the intended destination, explain the mismatch and stop.\n\n'
                        '--- ORIGINAL USER REQUEST ---\n'+row['prompt'])
                prompt += reference_context
                desktop.start(target['id'],prompt,owner)
            self.finish(row,'submitted','Sent to Codex: '+target['title']+'\nProject: '+target['project']+'\nYour original request was sent. Results will return on this task; reply here to continue it.')
            with state.db:
                state.db.execute("UPDATE watched SET status='running' WHERE id=?",(target['id'],))
        except Exception as exc:
            state.db.rollback()
            fresh=state.db.execute('SELECT status FROM task_routes WHERE id=?',(row['id'],)).fetchone()[0]
            uncertain=fresh=='submitting'
            self.finish(row,'uncertain' if uncertain else 'failed',
                ('Codex delivery is uncertain; inspect the task before resending. No automatic retry was made.' if uncertain else
                 'Request was not sent: '+str(exc)))
