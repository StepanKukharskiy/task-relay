"""Request-derived workflow intent and receipt-driven continuation.

The model proposes the stages; this module knows transport/receipt contracts, not
business workflows. It never fabricates acceptance or replays failed submissions.
"""
import hashlib
import json
from pathlib import Path
import re
import time

from orchestrator.storage import transaction

ROUTES = {'conversation', 'production', 'browser_research', 'image'}
ACTIONS = {'plan_pipeline', 'pipeline_result', 'pipeline_decision', 'pipeline_control'}
INSTRUCTIONS = '''For a request with multiple dependent outcomes, create ONE durable
workflow with plan_pipeline instead of executing only its first operation or merely
writing a narrative plan. Infer the necessary stages from the request and available
capabilities; no particular sequence, application or domain is mandatory. Simple
single operations still use their direct actions. Do not create a pipeline for a
status question. Preserve explicitly named providers and user decision boundaries.
Action: {kind:"plan_pipeline", title:string, planning_only:boolean, stages:[
{id:string, instruction:string, route:"conversation"|"production"|"browser_research"|"image",
 gate:"none"|"choice"|"selection", capabilities:[registered graph operation IDs],
 deliverables:{stable_id:description}}]}.
Use 2–12 ordered stages, each with its own scope, covering ALL requested outcomes.
Stage IDs are unique: 1–50 letters/digits/underscores/hyphens, starting with a letter
or digit (for example 3d_model). Preserve these IDs throughout the workflow.
A stage can use all earlier exact outputs. Split at genuine dependencies/decisions,
not every tool call. Production stages can internally prepare/review host code and
then execute it; do not drop the eventual native deliverable. capabilities applies
only to that stage. Use conversation/choice for proposing alternatives before user
selection, production for bounded file/native work, browser_research for supported
website research, image for one managed visualization. Specify named providers in
stage instructions. planning_only=true only when execution was not requested.
A saved pipeline automatically advances within its scope after completion/selection.
Native scripts still need exact-code Start; unknown future code is not approved.

snapshot.pipeline_step, when present, is the current saved stage, not a new user
request. Complete ONLY that stage. Use its declared capabilities/deliverables in
plan_production, template custom, planning_only false. Do not create another pipeline
or repeat completed work. All frozen pipeline inputs are supplied to production
workers. For image work select exact supplied image artifact IDs; never substitute.
For conversation work return {kind:"pipeline_result", result:string, choices:[
{id:string,label:string,value:string}]} with full source-grounded result and complete
choice descriptions. A choice gate requires 2–6 choices; otherwise choices=[].
Read the brief/references with file tools before reporting their contents. The result
and selected choice become immutable source context for subsequent stages.
For a human response to a saved choice use {kind:"pipeline_decision",pipeline_id,
stage_id,choice_id}, matching the exact offered option; never guess ambiguous approval.
For workflow status answer from snapshot.pipelines; for pause/resume/cancel use
{kind:"pipeline_control",pipeline_id,verb:"pause"|"resume"|"cancel"|"recover_planning"|"retry_planning"}.
When the user explicitly asks to continue after Gemini request failed (429), use
retry_planning: it requests a new bounded plan from the identical frozen inputs
and provider, retaining the failed receipt and all completed work. It does not
approve host execution. Never schedule this retry without a new user request.
For an explicit request to recover a blocked unexecuted plan, recover_planning
revalidates its saved responses, keeping the original requests and receipts. It
does not repeat a model call or executed operation. A blocked or
uncertain operation needs explicit recovery, never automatic replay or provider
fallback. Do not instruct the user to ask for the next stage after a selection.
'''


def initialize(db):
    from . import procedures
    procedures.initialize(db)
    from . import production_repairs
    production_repairs.initialize(db)
    db.executescript('''CREATE TABLE IF NOT EXISTS relay_pipelines(
        id TEXT PRIMARY KEY, request_id INTEGER UNIQUE NOT NULL, request TEXT NOT NULL,
        title TEXT NOT NULL, spec TEXT NOT NULL, channel TEXT NOT NULL,
        provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
        created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS relay_pipeline_steps(
        pipeline TEXT NOT NULL, position INTEGER NOT NULL, id TEXT NOT NULL,
        status TEXT NOT NULL, request_id INTEGER UNIQUE, target_kind TEXT, target TEXT,
        result TEXT, choices TEXT, sources TEXT NOT NULL DEFAULT '[]', error TEXT,
        PRIMARY KEY(pipeline,id), UNIQUE(pipeline,position));
      CREATE TABLE IF NOT EXISTS relay_pipeline_requests(
        request_id INTEGER PRIMARY KEY, pipeline TEXT NOT NULL, step TEXT NOT NULL,
        inputs TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS relay_pipeline_events(
        id INTEGER PRIMARY KEY, pipeline TEXT NOT NULL, step TEXT, kind TEXT NOT NULL,
        detail TEXT NOT NULL, created REAL NOT NULL);''')


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def bounded(value, maximum):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=maximum


class PipelineValidationError(ValueError):
    """A parsed workflow violates its stage contract, not its JSON format."""


def validate(action, snap):
    kind=action.get('kind')
    if kind=='plan_pipeline':
        if (set(action)!={'kind','title','planning_only','stages'} or not bounded(action['title'],200)
                or type(action['planning_only']) is not bool or not isinstance(action['stages'],list)
                or not 2<=len(action['stages'])<=12):raise PipelineValidationError('Provide a bounded ordered workflow with 2–12 stages.')
        if snap.get('pipeline_step'):raise PipelineValidationError('Continue the saved workflow; do not create a nested one.')
        known={x['id'] for x in snap.get('capabilities',{}).get('graph_operations',[])}
        ids=set()
        for s in action['stages']:
            if (not isinstance(s,dict) or set(s)!={'id','instruction','route','gate','capabilities','deliverables'}
                    or not isinstance(s['id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,49}',s['id'])
                    or s['id'] in ids or not bounded(s['instruction'],3000) or s['route'] not in ROUTES
                    or s['gate'] not in ('none','choice','selection') or not isinstance(s['capabilities'],list)
                    or any(not isinstance(v,str) for v in s['capabilities'])
                    or len(set(s['capabilities']))!=len(s['capabilities']) or not set(s['capabilities'])<=known
                    or not isinstance(s['deliverables'],dict) or not 1<=len(s['deliverables'])<=8
                    or any(not bounded(k,80) or not bounded(v,500) for k,v in s['deliverables'].items())):
                raise PipelineValidationError('Invalid workflow stage, capability or deliverable.')
            if s['route'] in ('conversation','browser_research') and s['capabilities']:
                raise PipelineValidationError('Only production/image stages declare graph operations.')
            if s['gate']=='choice' and s['route']!='conversation':
                raise PipelineValidationError('Choice gates belong to conversation stages.')
            if s['route']=='conversation' and s['gate']=='selection':raise PipelineValidationError('Conversation choices use a choice gate.')
            if s['route']=='browser_research' and s['gate']!='none':raise PipelineValidationError('Research produces receipt-backed source context.')
            ids.add(s['id'])
    elif kind=='pipeline_result':
        step=snap.get('pipeline_step',{}).get('stage',{})
        if (set(action)!={'kind','result','choices'} or step.get('route')!='conversation'
                or not bounded(action['result'],10000) or not isinstance(action['choices'],list)):
            raise PipelineValidationError('A saved conversation stage requires a bounded result.')
        choices=action['choices'];ids=set()
        if (step['gate']=='choice' and not 2<=len(choices)<=6) or (step['gate']!='choice' and choices):
            raise PipelineValidationError('Use the declared choice boundary.')
        for choice in choices:
            if (not isinstance(choice,dict) or set(choice)!={'id','label','value'}
                    or not bounded(choice['id'],50) or choice['id'] in ids
                    or not bounded(choice['label'],150) or not bounded(choice['value'],4000)):
                raise PipelineValidationError('Invalid or duplicate workflow choice.')
            ids.add(choice['id'])
    elif kind in ('pipeline_decision','pipeline_control'):
        required={'kind','pipeline_id','stage_id','choice_id'} if kind=='pipeline_decision' else {'kind','pipeline_id','verb'}
        if set(action)!=required:raise PipelineValidationError('Choose an exact saved workflow decision.')
        p=next((p for p in snap.get('pipelines',[]) if p['id']==action['pipeline_id']),None)
        if not p:raise PipelineValidationError('Workflow is not in this channel.')
        if kind=='pipeline_decision':
            s=next((s for s in p['stages'] if s['id']==action['stage_id']),None)
            if not s or s['status']!='awaiting_choice' or action['choice_id'] not in {c['id'] for c in s['choices']}:
                raise PipelineValidationError('That choice is no longer pending.')
        elif action['verb'] not in ('pause','resume','cancel','recover_planning','retry_planning'):raise PipelineValidationError('Unknown workflow control.')
    else:raise PipelineValidationError('Unknown workflow action.')


def event(state, pid, sid, kind, detail):
    state.db.execute('INSERT INTO relay_pipeline_events(pipeline,step,kind,detail,created) VALUES (?,?,?,?,?)',
                     (pid,sid,kind,encoded(detail),time.time()))


def notice(state,pid,sid,kind,text):
    from .workflow_files import location_text
    text+='\n\n'+location_text(state,pid)
    channel=state.db.execute('SELECT channel FROM relay_pipelines WHERE id=?',(pid,)).fetchone()[0]
    key=f'pipeline:{pid}:{sid or "workflow"}:{kind}'
    state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)',(key,text))
    state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)',(key,channel))
    return key


def catalog(state):
    channel=getattr(state,'channel','telegram')
    result=[]
    for r in state.db.execute('SELECT * FROM relay_pipelines WHERE channel=? ORDER BY created DESC LIMIT 20',(channel,)):
        stages=[]
        for s in state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(r['id'],)):
            stages.append({**{k:s[k] for k in ('id','status','target_kind','target','error')},'choices':json.loads(s['choices'] or '[]')})
        from .workflow_files import folder_path
        result.append(dict(id=r['id'],title=r['title'],status=r['status'],stages=stages,files_path=str(folder_path(state,r['id']))))
    return result


def request_context(state, ident):
    r=state.db.execute('SELECT * FROM relay_pipeline_requests WHERE request_id=?',(ident,)).fetchone()
    if not r:return None
    p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(r['pipeline'],)).fetchone()
    s=state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(r['pipeline'],r['step'])).fetchone()
    return dict(pipeline_id=p['id'],stage=json.loads(p['spec'])['stages'][s['position']],
                original_request=p['request'],inputs=json.loads(r['inputs']),status=p['status'])


def guard(state, job, action):
    ctx=request_context(state,job['id'])
    if not ctx:return
    if ctx['status']!='active':raise ValueError('Workflow was paused or cancelled; no stage action dispatched.')
    for source in ctx['inputs']['sources']:
        if artifact_source(state,source['artifact'])!=source:raise ValueError('Workflow input version changed before dispatch.')
    stage=ctx['stage'];kind=(action or {}).get('kind')
    if action is None:return # A real clarification waits; it is never treated as completion.
    allowed={'conversation':{'pipeline_result'},'production':{'plan_production'},
             'browser_research':{'browser_research'},'image':{'generate_image','plan_production'}}
    if kind not in allowed[stage['route']]:raise ValueError('Action changes the saved workflow stage scope.')
    if kind=='plan_production':
        if (action.get('planning_only') or action.get('previous_run') or action.get('parent_id')
                or set(action.get('step_capabilities',[]))!=set(stage['capabilities'])
                or action.get('deliverables')!=stage['deliverables']):
            raise ValueError('Stage planning must retain its declared capabilities and deliverables.')
    if kind=='generate_image':
        required={s['artifact'] for s in ctx['inputs']['sources'] if s.get('media_type','').startswith('image/')}
        if set(action.get('artifact_ids',[]))!=required or action.get('reference_ids'):
            raise ValueError('Image stage must use the exact frozen upstream image versions.')


def dispatch(state,job,action,snap):
    from . import relay_channels
    validate(action,snap)
    if not state.db.in_transaction:raise ValueError('Workflow dispatch requires an atomic transaction.')
    kind=action['kind']
    if kind=='plan_pipeline':
        pid='pipe-'+hashlib.sha256(str(job['id']).encode()).hexdigest()[:24]
        old=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(pid,)).fetchone()
        if old:
            if old['spec']!=encoded(action) or old['request']!=job['prompt']:raise ValueError('Workflow identity conflict.')
            return 'Workflow already saved: '+pid,None
        channel=relay_channels.request_channel(state,job['id'])
        state.db.execute('INSERT INTO relay_pipelines VALUES (?,?,?,?,?,?,?,?,?,?)',
            (pid,job['id'],job['prompt'],action['title'],encoded(action),channel,job['provider'],job['model'],
             'planned' if action['planning_only'] else 'active',time.time()))
        for i,s in enumerate(action['stages']):
            state.db.execute('INSERT INTO relay_pipeline_steps(pipeline,position,id,status) VALUES (?,?,?,?)',(pid,i,s['id'],'pending'))
        from .production_repairs import POLICY
        event(state,pid,None,'created',{**action,'automatic_task_seconds':1800,'automatic_script_repair':POLICY})
        state.db.execute('UPDATE orchestrator_chats SET focus=? WHERE id=?',(pid,job['id']))
        text='Workflow saved: '+action['title']+'\n'+'\n'.join(f'{i+1}. {s["instruction"]}' for i,s in enumerate(action['stages']))
        text+='\n'+('Planning only; use Resume to start.' if action['planning_only'] else 'Relay will continue after completed steps and your selections. Each task has its own planned deadline, up to 30 minutes. Exact host-code approvals remain separate.')
        text+='\nConfirmed script failures allow one bounded repair preparation and independent review per stage using its existing model, up to 10 minutes and 24 tools each. Corrected code waits for a new Start.'
        notice(state,pid,None,'created',text)
        return text,None
    if kind=='pipeline_control':
        control(state,action['pipeline_id'],action['verb'],request=job['prompt']);return 'Workflow '+action['verb']+' recorded.',None
    if kind=='pipeline_decision':
        choose(state,action['pipeline_id'],action['stage_id'],action['choice_id'])
        return 'Choice saved. Relay will continue the saved workflow.',None
    ctx=request_context(state,job['id']);pid=ctx['pipeline_id'];sid=ctx['stage']['id']
    status='awaiting_choice' if action['choices'] else 'completed'
    state.db.execute('UPDATE relay_pipeline_steps SET status=?,result=?,choices=? WHERE pipeline=? AND id=?',
                     (status,action['result'],encoded(action['choices']),pid,sid))
    event(state,pid,sid,'result',action)
    notice(state,pid,sid,'result',action['result'])
    return action['result'],None


def choose(state,pid,sid,choice):
    p=state.db.execute('SELECT channel,status FROM relay_pipelines WHERE id=?',(pid,)).fetchone()
    if not p or p['channel']!=getattr(state,'channel','telegram') or p['status'] not in ('active','paused'):raise ValueError('Workflow choice is not available in this channel.')
    s=state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(pid,sid)).fetchone()
    if not s or s['status']!='awaiting_choice':raise ValueError('This workflow decision is no longer pending.')
    option=next((c for c in json.loads(s['choices']) if c['id']==choice),None)
    if not option:raise ValueError('Choose an exact offered option.')
    sources=json.loads(s['sources'])
    if sources:
        sources=[a for a in sources if a['artifact']==choice]
        sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(f'pipeline:{pid}:{sid}:result',)).fetchone()
        delivered=state.db.execute('SELECT status FROM media_outbox WHERE id=?',(f'pipeline:{pid}:{sid}:image:{choice}',)).fetchone()
        allowed=('sent','skipped') if p['channel']=='messages' else ('sent',)
        if not sent or not sent[0] or not delivered or delivered[0] not in allowed:raise ValueError('Wait for the complete image and selection card.')
        if len(sources)!=1 or artifact_source(state,choice)!=sources[0]:raise ValueError('Selected workflow artifact changed.')
    state.db.execute("UPDATE relay_pipeline_steps SET status='completed',result=?,sources=? WHERE pipeline=? AND id=?",
                     (s['result']+'\n\nUSER SELECTED:\n'+encoded(option),encoded(sources),pid,sid))
    event(state,pid,sid,'user_choice',option)


def control(state,pid,verb,*,request=None):
    row=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(pid,)).fetchone()
    if not row or row['channel']!=getattr(state,'channel','telegram'):raise ValueError('Use the workflow original channel.')
    if verb in ('recover_planning','retry_planning'):
        if row['status']!='blocked':raise ValueError('Only blocked planning can be recovered.')
        step=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status='blocked' ORDER BY position LIMIT 1",(pid,)).fetchone()
        if not step or step['target_kind']!='plan_production':raise ValueError('This is not an unexecuted planning failure; inspect its receipt.')
        from . import production_planning
        if verb=='retry_planning':
            target,receipt=production_planning.retry_rate_limited_plan(state,step['target'],request)
        else:
            target,receipt=production_planning.recover_validated_response(state,step['target'])
        state.db.execute("UPDATE relay_pipeline_steps SET status='running',target=?,error=NULL WHERE pipeline=? AND id=?",(target,pid,step['id']))
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(pid,))
        event(state,pid,step['id'],'planning_retry_requested' if verb=='retry_planning' else 'planning_recovered',{'successor':target,**receipt})
        if verb=='retry_planning':
            notice(state,pid,step['id'],'retry-'+target,
                   'Planning retry queued using the same model and exact saved inputs. Completed work is preserved. '
                   'Host execution still requires its exact Start approval. No workers have started.')
        return
    if row['status'] in ('cancelled','completed'):raise ValueError('Workflow is already finished.')
    if verb=='resume' and row['status'] not in ('paused','planned'):raise ValueError('Blocked work needs explicit recovery, not replay.')
    new={'pause':'paused','resume':'active','cancel':'cancelled'}[verb]
    state.db.execute('UPDATE relay_pipelines SET status=? WHERE id=?',(new,pid))
    event(state,pid,None,verb,{'running_work':'May finish; further workflow dispatch is stopped.'})


def observe_dispatch(state,job,action):
    ctx=request_context(state,job['id'])
    if not ctx:return
    pid=ctx['pipeline_id'];sid=ctx['stage']['id']
    if action is None:
        state.db.execute("UPDATE relay_pipeline_steps SET status='awaiting_input',error=? WHERE pipeline=? AND id=?",
                         ('Reply with the missing information; no next stage was inferred.',pid,sid));return
    kind=action['kind']
    if kind=='pipeline_result':return
    if kind=='plan_production':target='plan-'+str(job['id'])
    elif kind=='browser_research':
        target=state.db.execute('SELECT id FROM browser_research_requests WHERE source=?',('orchestrator:'+str(job['id']),)).fetchone()[0]
    else:target=state.db.execute('SELECT backend_job_id FROM orchestrator_image_requests WHERE job_id=?',(job['id'],)).fetchone()[0]
    state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind=?,target=? WHERE pipeline=? AND id=?",(kind,target,pid,sid))
    event(state,pid,sid,'dispatched',{'request_id':job['id'],'kind':kind,'target':target})


def response_event(state,job,action):
    """Use the already queued workflow card as the single delivered response."""
    kind=(action or {}).get('kind')
    if kind=='pipeline_result':
        ctx=request_context(state,job['id'])
        return f'pipeline:{ctx["pipeline_id"]}:{ctx["stage"]["id"]}:result'
    if kind in ('plan_pipeline','run_procedure'):
        row=state.db.execute('SELECT id FROM relay_pipelines WHERE request_id=?',(job['id'],)).fetchone()
        return f'pipeline:{row[0]}:workflow:created'
    return None


def artifact_source(state,ident):
    from . import production_control as pc, gemini
    from orchestrator.runtime import Runtime, safe_file, file_hash
    if ident.startswith('media-'):
        r=state.db.execute("SELECT * FROM artifacts WHERE id=? AND role='output'",(ident[6:],)).fetchone()
        if not r:raise ValueError('Workflow media version is missing.')
        root=gemini.GENERATED.resolve();p=Path(r['path']);p=safe_file(root,str(p.relative_to(root)))
        source=dict(artifact=ident,path=str(p),name=r['filename'],sha256=r['sha256'],bytes=r['size'],media_type=r['mime'])
    else:
        a=Runtime(pc.root(state),connection=state.db).artifact(ident)
        p=safe_file(pc.root(state)/'artifacts',ident+'/content')
        import mimetypes
        source=dict(artifact=ident,path=str(p),name=a['path'],sha256=a['sha256'],bytes=a['bytes'],media_type=mimetypes.guess_type(a['path'])[0] or 'application/octet-stream')
    if p.stat().st_size!=source['bytes'] or file_hash(p)!=source['sha256']:raise ValueError('Workflow input version changed.')
    return source


def frozen_sources(state,job):
    ctx=request_context(state,job['id'])
    if not ctx:return []
    from . import routing_inputs
    values=[]
    for i,s in enumerate(ctx['inputs']['sources']):
        current=artifact_source(state,s['artifact'])
        if current!=s:raise ValueError('Workflow handoff changed after queueing.')
        values.append((Path(s['path']),str(i)+'-'+Path(s['name']).name,'exact workflow source',None,s['sha256']))
    root=state.media_dir.parent/'pipeline-context';root.mkdir(parents=True,exist_ok=True)
    p=root/(str(job['id'])+'.json');raw=encoded(ctx).encode()
    if p.exists():
        if p.is_symlink() or p.read_bytes()!=raw:raise ValueError('Workflow context identity changed.')
    else:
        with p.open('xb') as f:f.write(raw)
    values.append((p,'pipeline-context.json','workflow source context',None,hashlib.sha256(raw).hexdigest()))
    return routing_inputs.capture(state,job,values,section='pipeline',max_bytes=150_000_000)


def enqueue_step(state,p,s):
    # Stable identity + intent in the SAME commit as the queue. No provider here.
    ident=-int(hashlib.sha256((p['id']+':'+s['id']).encode()).hexdigest()[:15],16)-1
    prior=[dict(r) for r in state.db.execute("SELECT id,result,sources FROM relay_pipeline_steps WHERE pipeline=? AND position<? ORDER BY position",(p['id'],s['position']))]
    sources={a['artifact']:a for r in prior for a in json.loads(r['sources'])}
    for a in sources.values():
        if artifact_source(state,a['artifact'])!=a:raise ValueError('An upstream artifact changed; workflow stopped.')
    inputs={'prior_results':[dict(id=r['id'],result=r['result']) for r in prior], 'sources':list(sources.values())}
    from . import procedures
    procedure=procedures.run_context(state,p['id'])
    if procedure:inputs['procedure']=procedure
    stage=json.loads(p['spec'])['stages'][s['position']]
    prompt=stage['instruction']+'\n\nOriginal user request:\n'+p['request']+'\n\nSaved workflow stage and exact upstream context:\n'+encoded({'stage':stage,**inputs})
    if json.loads(p['spec'])['planning_only']:
        prompt+='\nThe user subsequently selected Resume for this saved workflow, authorizing its scoped execution.'
    state.db.execute('INSERT INTO relay_pipeline_requests VALUES (?,?,?,?)',(ident,p['id'],s['id'],encoded(inputs)))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,p['channel']))
    state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (?,?,?,?,?,?)',
                     (ident,prompt,p['id'],p['provider'],p['model'],time.time()))
    state.db.execute("UPDATE relay_pipeline_steps SET status='queued',request_id=? WHERE pipeline=? AND id=?",(ident,p['id'],s['id']))
    event(state,p['id'],s['id'],'queued',{'request_id':ident,'inputs':inputs})


def complete(state,p,s,sources,result):
    state.db.execute("UPDATE relay_pipeline_steps SET status='completed',sources=?,result=? WHERE pipeline=? AND id=?",(encoded(sources),result,p['id'],s['id']))
    event(state,p['id'],s['id'],'completed',{'sources':sources,'result':result})


def check_plan(state,p,s,row):
    """Whole-workflow intent covers bounded preparation, never unknown host code."""
    spec=json.loads(p['spec'])['stages'][s['position']];plan=json.loads(row['plan'])
    from orchestrator import host_code
    from orchestrator.execution import REGISTRY
    from orchestrator.worker_capabilities import needs_approval as worker_approval
    caps=set(spec['capabilities']);needs_approval=worker_approval(plan)
    receipt=state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND kind='created' ORDER BY id LIMIT 1",(p['id'],)).fetchone()
    automatic_seconds=json.loads(receipt[0]).get('automatic_task_seconds',600) if receipt else 600
    for t in plan['tasks']:
        if t.get('execution',{}).get('capability') not in caps|{None}:raise ValueError('Plan expanded workflow capabilities.')
        if t['max_attempts']!=1 or t['limits']['seconds']>1800 or t['limits']['tool_calls']>60:raise ValueError('Plan expanded workflow attempt bounds.')
        if t['limits']['seconds']>automatic_seconds:needs_approval=True
        if host_code.required(t) or REGISTRY.get(t.get('execution',{}).get('capability'),{}).get('requires_registered_inputs'):
            needs_approval=True
    return not needs_approval


def advance_running(state,p,s):
    if s['target_kind']=='browser_research':
        r=state.db.execute('SELECT * FROM browser_jobs WHERE id=?',(s['target'],)).fetchone()
        if r['status']=='completed':complete(state,p,s,[],encoded({'receipt':r['id'],'query':r['prompt'],'url':r['url'],'answer':r['result']}))
        elif r['status'] in ('blocked','uncertain'):raise ValueError(r['error'] or r['status'])
    elif s['target_kind']=='generate_image':
        r=state.db.execute('SELECT * FROM backend_jobs WHERE id=?',(s['target'],)).fetchone()
        if r['status']=='completed':
            ids=['media-'+r[0] for r in state.db.execute("SELECT id FROM artifacts WHERE job_id=? AND role='output' AND mime LIKE 'image/%' ORDER BY id",(s['target'],))]
            if not ids:raise ValueError('Completed image job has no registered image.')
            sources=[artifact_source(state,i) for i in ids]
            spec=json.loads(p['spec'])['stages'][s['position']]
            if spec['gate']=='selection':
                choices=[dict(id=a['artifact'],label=Path(a['name']).name,value=a['artifact']) for a in sources]
                state.db.execute("UPDATE relay_pipeline_steps SET status='awaiting_choice',choices=?,sources=?,result=? WHERE pipeline=? AND id=?",
                    (encoded(choices),encoded(sources),'Image candidate ready for selection.',p['id'],s['id']))
                selection_event=notice(state,p['id'],s['id'],'result','Image ready. Select the exact candidate to continue the workflow.')
                for a in sources:
                    state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                        (f'pipeline:{p["id"]}:{s["id"]}:image:{a["artifact"]}',selection_event,a['path'],Path(a['name']).name,'original','Exact candidate for workflow selection'))
            else:complete(state,p,s,sources,'Image generated; no user acceptance was inferred.')
        elif r['status'] in ('failed','uncertain','cancelled','blocked'):raise ValueError('Image job '+r['status']+'; inspect its receipt. No replay.')
    elif s['target_kind']=='plan_production':
        from . import production_planning as planning, production_control as pc, production_status
        from orchestrator.runtime import Runtime
        row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(s['target'],)).fetchone()
        if row['status'] in ('blocked','uncertain','discarded'):raise ValueError(row['error'] or 'Stage plan '+row['status'])
        if row['status']=='needs_input':return
        if row['status']=='superseded':
            child=state.db.execute('SELECT id FROM production_plans WHERE parent_id=? ORDER BY created DESC LIMIT 1',(row['id'],)).fetchone()
            if child:state.db.execute('UPDATE relay_pipeline_steps SET target=? WHERE pipeline=? AND id=?',(child[0],p['id'],s['id']))
            return
        if row['status']=='ready':
            if check_plan(state,p,s,row):
                sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(row['event_id'],)).fetchone()
                if sent and sent[0]:planning.apply(state,row['token'],'start',pipeline_grant=p['id'])
            return
        if row['status']!='started':return
        advance_production(state,p,s,row['run'],row['id'])
    elif s['target_kind']=='production_run':
        advance_production(state,p,s,s['target'])


def advance_production(state,p,s,run,plan_id=None):
    from . import production_control as pc, production_status
    from orchestrator.runtime import Runtime
    rt=Runtime(pc.root(state),connection=state.db);status=rt.status(run)
    if status['status']=='blocked':
        from . import production_repairs
        if production_repairs.begin(state,p,s,run):return
    if status['status'] in ('blocked','uncertain','cancelled'):raise ValueError('Production '+status['status']+'; no attempts reset.')
    if status['status']!='completed':return
    plan=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    if plan.get('deferred_operations'):
        # Same logical stage, now using the selected prepared code. A ready
        # native plan will wait for its existing exact-code Start approval.
        production_status.plan_execution(state,run)
        target=state.db.execute('SELECT plan_id FROM production_stage_links WHERE parent=?',(run,)).fetchone()[0]
        state.db.execute("UPDATE relay_pipeline_steps SET target_kind='plan_production',target=? WHERE pipeline=? AND id=?",(target,p['id'],s['id']))
        event(state,p['id'],s['id'],'execution_planned',{'plan':target,'parent':run});return
    decisions=state.db.execute('SELECT artifact FROM production_decisions WHERE run=? ORDER BY id',(run,)).fetchall()
    ids=[r[0] for r in decisions]
    if not ids:
        spec=json.loads(p['spec'])['stages'][s['position']]
        if spec['gate']=='selection':raise ValueError('Stage completed without its required output selection.')
        ids=[r[0] for r in state.db.execute('SELECT a.id FROM production_artifacts a JOIN production_tasks t ON t.latest=a.attempt AND t.run=a.run AND t.id=a.task WHERE a.run=?',(run,))]
    complete(state,p,s,[artifact_source(state,i) for i in ids],encoded({'plan':plan_id,'run':run,'user_selected':bool(decisions)}))

def attach_continuations(state):
    """Recover workflow ownership only through an explicit registered successor.

    Also reconciles continuations created by older versions. No attempt is reset,
    no selection is inferred, and paused/cancelled workflows stay stopped.
    """
    rows=state.db.execute('''SELECT s.*,p.channel,p.status AS workflow_status,
        CASE WHEN s.target_kind='production_run' THEN s.target ELSE x.run END AS parent_run
        FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline
        LEFT JOIN production_plans x ON s.target_kind='plan_production' AND x.id=s.target
        WHERE p.status IN ('active','blocked') AND s.status IN ('running','blocked')
        AND s.target_kind IN ('plan_production','production_run')''').fetchall()
    for s in rows:
        link=state.db.execute("SELECT * FROM production_continuations WHERE parent=? AND status='registered'",(s['parent_run'],)).fetchone()
        if not link:continue
        receipt=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='production_continuation_created' AND json_extract(data,'$.request_id')=?",(link['child'],link['id'])).fetchone()
        if not receipt or json.loads(receipt[0]).get('parent')!=s['parent_run']:continue
        from . import relay_channels
        if relay_channels.request_channel(state,link['id'])!=s['channel']:continue
        bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(link['child'],)).fetchone()
        if (bound[0] if bound else 'telegram')!=s['channel']:continue
        parent=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(s['parent_run'],)).fetchone()
        child=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(link['child'],)).fetchone()
        if not parent or not child:continue
        old,new=json.loads(parent[0]),json.loads(child[0])
        # A continuation can revise draft instructions, never discard the saved
        # stage's pending native outputs or add execution capabilities.
        if any(old.get(k)!=new.get(k) for k in ('deferred_operations','deliverables')):continue
        if any(t.get('execution') for t in new['tasks']):continue
        state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target=?,status='running',error=NULL WHERE pipeline=? AND id=?",(link['child'],s['pipeline'],s['id']))
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=? AND status='blocked'",(s['pipeline'],))
        event(state,s['pipeline'],s['id'],'continuation_attached',
              {'request_id':link['id'],'parent':s['parent_run'],'child':link['child'],'previous_target':s['target']})


def reconcile_completed_production(state):
    """Observe successful recovery of a linked run, without retrying any work.

    A production blocker stops the parent scheduler, but does not detach the run.
    Only its completed, reviewed/selected state may clear that stale blocker.
    Explicit workflow pauses and cancellation always remain in force.
    """
    from . import production_control as pc, relay_channels
    from orchestrator.runtime import Runtime
    rows=state.db.execute("SELECT id FROM relay_pipelines WHERE status='blocked' ORDER BY created LIMIT 20").fetchall()
    for row in rows:
        try:
            with transaction(state.db):
                p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(row['id'],)).fetchone()
                if p['status']!='blocked':continue
                s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status!='completed' ORDER BY position LIMIT 1",(p['id'],)).fetchone()
                if not s or s['status']!='blocked' or s['error']!='Production blocked; no attempts reset.':continue
                plan_id=None
                if s['target_kind']=='plan_production':
                    plan=state.db.execute('SELECT * FROM production_plans WHERE id=?',(s['target'],)).fetchone()
                    if not plan or plan['status']!='started' or plan['channel']!=p['channel'] or not plan['run']:continue
                    run=plan['run'];plan_id=plan['id']
                elif s['target_kind']=='production_run':run=s['target']
                else:continue
                bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
                if (bound[0] if bound else 'telegram')!=p['channel']:continue
                scoped=relay_channels.ScopedState(state,p['channel'])
                if Runtime(pc.root(scoped),connection=state.db).status(run)['status']!='completed':continue
                # Validate/freeze exact selected artifacts before clearing the blocker.
                # A failure rolls this transaction back; no candidate is substituted.
                advance_production(scoped,p,s,run,plan_id)
                state.db.execute("UPDATE relay_pipeline_steps SET error=NULL,status=CASE WHEN status='blocked' THEN 'running' ELSE status END WHERE pipeline=? AND id=?",(p['id'],s['id']))
                state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
                event(state,p['id'],s['id'],'production_recovery_reconciled',
                      {'run':run,'target':s['target'],'previous_error':s['error'],'attempts_reset':False})
        except (ValueError,OSError,KeyError,TypeError):
            # Retain the original blocked state for missing/changed evidence.
            # Reconciliation never resets attempts or submits an external request.
            continue


def tick(state):
    # Called by the existing single orchestrator service. Each queue/state
    # transition is atomic; all external work remains in existing workers.
    from .relay_channels import ScopedState
    with transaction(state.db):attach_continuations(state)
    reconcile_completed_production(state)
    from . import production_repairs
    production_repairs.tick(state)
    for p in state.db.execute("SELECT * FROM relay_pipelines WHERE status='active' ORDER BY created LIMIT 20").fetchall():
        scoped=ScopedState(state,p['channel'])
        s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status!='completed' ORDER BY position LIMIT 1",(p['id'],)).fetchone()
        try:
            with transaction(state.db):
                p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()
                if p['status']!='active':continue
                # Interpret queued human feedback before advancing any stage in
                # that channel. An internal stage request does not block itself.
                if state.db.execute('''SELECT 1 FROM orchestrator_chats c
                    LEFT JOIN relay_request_channels ch ON ch.request_id=c.id
                    WHERE c.status IN ('queued','sending') AND COALESCE(ch.channel,'telegram')=?
                    AND NOT EXISTS (SELECT 1 FROM relay_pipeline_requests r WHERE r.request_id=c.id)
                    LIMIT 1''',(p['channel'],)).fetchone():continue
                s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status!='completed' ORDER BY position LIMIT 1",(p['id'],)).fetchone()
                if not s:
                    state.db.execute("UPDATE relay_pipelines SET status='completed' WHERE id=?",(p['id'],));notice(state,p['id'],None,'completed','Workflow completed: '+p['title']);continue
                if s['status']=='pending':
                    if state.db.execute("SELECT count(*) FROM orchestrator_chats WHERE status IN ('queued','sending')").fetchone()[0]<5:enqueue_step(scoped,p,s)
                elif s['status']=='running':advance_running(scoped,p,s)
                elif s['status']=='queued':
                    job=state.db.execute('SELECT status FROM orchestrator_chats WHERE id=?',(s['request_id'],)).fetchone()
                    if job['status'] in ('failed','uncertain','cancelled'):raise ValueError('Stage interpretation '+job['status']+'; no automatic resubmission.')
        except (ValueError,OSError,KeyError,TypeError) as exc:
            with transaction(state.db):
                state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error=? WHERE pipeline=? AND id=?",(str(exc),p['id'],s['id']))
                state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
                event(state,p['id'],s['id'],'blocked',{'error':str(exc)})
                notice(state,p['id'],s['id'],'blocked','Workflow paused: '+str(exc))
    from .workflow_files import sync_recent
    sync_recent(state)


def controls(state,event_id):
    parts=event_id.split(':')
    if len(parts)!=4 or parts[0]!='pipeline':return None
    pid,sid=parts[1:3];p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(pid,)).fetchone()
    if not p:return None
    rows=[]
    s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=? AND status='awaiting_choice'",(pid,sid)).fetchone()
    if s and p['status'] in ('active','paused'):
        for i,c in enumerate(json.loads(s['choices'])):rows.append([{'text':c['label'][:100],'callback_data':f'pipe:{pid}:{s["position"]}:{i}'}])
    if p['status'] in ('planned','paused'):rows.append([{'text':'Resume workflow','callback_data':f'pipe:{pid}:resume'}])
    if p['status']=='active':rows.append([{'text':'Pause workflow','callback_data':f'pipe:{pid}:pause'}])
    if p['status']=='blocked' and state.db.execute("SELECT 1 FROM relay_pipeline_steps s JOIN production_plans x ON x.id=s.target WHERE s.pipeline=? AND s.status='blocked' AND s.target_kind='plan_production' AND x.status='blocked' AND x.run IS NULL",(pid,)).fetchone():
        from . import production_planning
        plan=state.db.execute("SELECT x.* FROM relay_pipeline_steps s JOIN production_plans x ON x.id=s.target WHERE s.pipeline=? AND s.status='blocked' ORDER BY s.position LIMIT 1",(pid,)).fetchone()
        if production_planning.rate_limited_plan(state,plan):
            rows.append([{'text':'Retry planning','callback_data':f'pipe:{pid}:retry:{plan["token"][:12]}'}])
        else:
            rows.append([{'text':'Recover saved plan','callback_data':f'pipe:{pid}:recover_planning'}])
    return {'inline_keyboard':rows} if rows else None


def callback(bridge,update):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith('pipe:'):return False
    s=bridge.state;msg=q.get('message',{});chat=msg.get('chat',{});user=q.get('from',{})
    if user.get('is_bot') or user.get('id')!=s.get('user_id') or chat.get('id')!=s.get('chat_id') or chat.get('type')!='private':return True
    try:
        parts=raw.split(':');pid=parts[1]
        with transaction(s.db):
            p=s.db.execute('SELECT * FROM relay_pipelines WHERE id=? AND channel=?',(pid,getattr(s,'channel','telegram'))).fetchone()
            if not p:raise ValueError('Unknown workflow in this channel.')
            if len(parts)==3 and parts[2] in ('pause','resume','recover_planning'):control(s,pid,parts[2])
            elif len(parts)==4 and parts[2]=='retry':
                plan=s.db.execute("SELECT x.* FROM relay_pipeline_steps t JOIN production_plans x ON x.id=t.target WHERE t.pipeline=? AND t.status='blocked' ORDER BY t.position LIMIT 1",(pid,)).fetchone()
                if not plan or plan['token'][:12]!=parts[3]:raise ValueError('This retry card is stale. Inspect the current workflow.')
                control(s,pid,'retry_planning',request='Retry planning button for '+plan['id'])
            elif len(parts)==4:
                step=s.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND position=?',(pid,int(parts[2]))).fetchone()
                delivered=s.db.execute('SELECT sent FROM outbox WHERE id=?',(f'pipeline:{pid}:{step["id"]}:result',)).fetchone()
                if not delivered or not delivered[0]:raise ValueError('Wait for the complete decision card.')
                choices=json.loads(step['choices']);choice=choices[int(parts[3])]
                choose(s,pid,step['id'],choice['id'])
            else:raise ValueError('Invalid workflow control.')
        text='Decision saved. Relay will continue within the workflow scope.'
    except (ValueError,KeyError,IndexError,TypeError) as exc:text=str(exc)
    from .bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=text[:200],show_alert=True)
    except BridgeError:pass
    return True


def verify_start(state,row,grant=None):
    link=state.db.execute('SELECT s.*,p.status AS pipeline_status,p.channel AS pipeline_channel FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline WHERE s.target=?',(row['id'],)).fetchone()
    if not link:
        if grant:raise ValueError('No workflow authorization owns this plan.')
        return
    if link['pipeline_status']!='active':raise ValueError('Workflow is paused or cancelled; stage Start is disabled.')
    if grant:
        p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(grant,)).fetchone()
        if not p or grant!=link['pipeline'] or p['channel']!=getattr(state,'channel','telegram') or not check_plan(state,p,link,row):
            raise ValueError('Exact stage Start is required for its host code, worker backend or extended limits; the saved workflow grant does not cover this change.')


def bind_reply(state,ident,focus):
    """An addressed clarification resumes interpretation, never an executed attempt."""
    p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=? AND channel=?',(focus,getattr(state,'channel','telegram'))).fetchone()
    if not p or p['status']!='active':return
    s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status='awaiting_input' ORDER BY position LIMIT 1",(p['id'],)).fetchone()
    if not s:return
    old=state.db.execute('SELECT inputs FROM relay_pipeline_requests WHERE request_id=?',(s['request_id'],)).fetchone()
    state.db.execute('INSERT INTO relay_pipeline_requests VALUES (?,?,?,?)',(ident,p['id'],s['id'],old['inputs']))
    state.db.execute("UPDATE relay_pipeline_steps SET status='queued',request_id=?,error=NULL WHERE pipeline=? AND id=?",(ident,p['id'],s['id']))
    event(state,p['id'],s['id'],'clarification',{'request_id':ident,'previous_request':s['request_id']})


def owner_of_run(state,run):
    repair=state.db.execute('''SELECT p.id,p.status FROM production_auto_repairs r
        JOIN relay_pipelines p ON p.id=r.pipeline WHERE r.preparation=?''',(run,)).fetchone()
    if repair:return repair
    return state.db.execute('''SELECT p.id,p.status FROM relay_pipeline_steps s
        LEFT JOIN production_plans x ON s.target_kind='plan_production' AND x.id=s.target
        LEFT JOIN production_stage_links l ON s.target_kind='plan_production' AND l.plan_id=s.target
        JOIN relay_pipelines p ON p.id=s.pipeline
        WHERE (x.run=? OR l.parent=? OR (s.target_kind='production_run' AND s.target=?))''',(run,run,run)).fetchone()


def owns_run(state,run):
    owner=owner_of_run(state,run)
    return bool(owner and owner['status']=='active')


def continuation_text(state,run):
    repair=state.db.execute('SELECT status FROM production_auto_repairs WHERE preparation=?',(run,)).fetchone()
    if repair:
        return 'Relay will prepare the exact-code Start card after successful repair review. No host execution or user acceptance is inferred.'
    owner=owner_of_run(state,run)
    if not owner:return 'Next decision: describe the next stage when ready. Selection alone does not start further work.'
    if owner['status']=='paused':return 'The saved workflow is paused. Resume it to continue after selection.'
    if owner['status']=='cancelled':return 'The saved workflow is cancelled. No later stage will start.'
    if owner['status']=='completed':return 'The saved workflow is completed.'
    if owner['status']=='blocked':return 'This stage belongs to the saved workflow. Relay will reconcile its completed, selected outputs before continuing; an unresolved blocker remains stopped.'
    return 'Relay will continue the saved workflow after recording this stage and any required selection. No new continuation request is needed.'


def context_for_run(state,run):
    """Retain the workflow file-selection contract through native stage planning."""
    row=state.db.execute('''SELECT s.request_id FROM relay_pipeline_steps s
        LEFT JOIN production_plans x ON s.target_kind='plan_production' AND x.id=s.target
        LEFT JOIN production_stage_links l ON s.target_kind='plan_production' AND l.plan_id=s.target
        JOIN relay_pipelines p ON p.id=s.pipeline
        WHERE (x.run=? OR l.parent=? OR (s.target_kind='production_run' AND s.target=?))
        AND p.channel=?''',(run,run,run,getattr(state,'channel','telegram'))).fetchone()
    return request_context(state,row[0]) if row else None


def retained_artifact_ids(state):
    """Frozen pipeline references outlive the UI's recent-artifact window."""
    result=set()
    for row in state.db.execute('''SELECT r.inputs FROM relay_pipeline_requests r JOIN relay_pipelines p
        ON p.id=r.pipeline WHERE p.channel=? AND p.status IN ('active','paused','blocked')''',(getattr(state,'channel','telegram'),)):
        result.update(a['artifact'] for a in json.loads(row[0])['sources'])
    return result
