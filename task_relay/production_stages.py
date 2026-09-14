"""Selected-stage lineage for the bounded planner, with one successor per stage."""
import json

from task_relay import production_control as pc
from task_relay import relay_channels
from orchestrator import contracts as c


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS production_stage_links (
        parent TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE, child TEXT UNIQUE)''')


def planning_origin(state,run):
    """Resolve recorded continuation ancestry without inventing a planning row."""
    seen=set()
    while run not in seen:
        seen.add(run)
        plan=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
        if plan:return plan
        link=state.db.execute("SELECT * FROM production_continuations WHERE child=? AND status='registered'",(run,)).fetchone()
        if not link:return None
        receipt=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='production_continuation_created' AND json_extract(data,'$.request_id')=?",(run,link['id'])).fetchone()
        if not receipt or json.loads(receipt['data']).get('parent')!=link['parent']:
            raise ValueError('Continuation lineage receipt is missing or inconsistent.')
        run=link['parent']
    raise ValueError('Continuation lineage contains a cycle.')


def failed_execution_snapshot(state,rt,run,channel,kind=None):
    bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    if (bound[0] if bound else 'telegram')!=channel:raise ValueError('Recover execution in its original channel.')
    status=rt.status(run)
    if status['status']!='blocked' or any(a['state'] in ('launching','running','cancelling','uncertain') for a in status['attempts']):
        raise ValueError('Recovery requires a confirmed stopped, blocked execution; no uncertain replay.')
    failed=[t for t in status['tasks'] if t['status']=='blocked']
    if len(failed)!=1:raise ValueError('Recovery requires one failed operation.')
    capability=rt.spec(failed[0]).get('execution',{}).get('capability')
    if kind=='local_inputs':
        from orchestrator.execution import REGISTRY
        spec=REGISTRY.get(capability,{})
        if spec.get('kind')!='procedure' or spec.get('external_requests')!=0:
            raise ValueError('Input recovery is limited to local procedures without external requests.')
    elif capability not in ('rhino.run_python','blender.run_python'):
        raise ValueError('Script repair requires one failed host Python operation.')
    attempt=next(a for a in status['attempts'] if a['id']==failed[0]['latest'])
    receipt=json.loads(attempt['receipt'] or '{}')
    if receipt.get('status')!='finished' or receipt.get('operation',{}).get('outcome')!='failed':
        raise ValueError('A completed host failure receipt is required before proposing a repair.')
    if any(t['status'] not in ('blocked','queued','completed') for t in status['tasks']):
        raise ValueError('Other user decisions or execution states need resolution first.')
    return {'run':run,'tasks':status['tasks'],'attempts':status['attempts'],
            'contract_digest':pc.runtime_digest(rt,run),'control_epoch':state.get('production-control-epoch:'+run,0)}


def snapshot(state,rt,run,channel):
    bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    if (bound['channel'] if bound else 'telegram')!=channel:
        raise ValueError('Continue the stage in its original channel.')
    status=rt.status(run)
    if status['status']!='completed':raise ValueError('Select the current outputs before planning the next stage.')
    decisions=[dict(r) for r in state.db.execute('SELECT * FROM production_decisions WHERE run=? ORDER BY task,id',(run,))]
    if not decisions:raise ValueError('A next stage requires a recorded exact-output selection.')
    for d in decisions:
        task=rt.task(run,d['task']);a=rt.artifact(d['artifact'])
        if task['latest']!=a['attempt'] or a['task']!=task['id'] or d['purpose']!=rt.spec(task).get('user_gate'):
            raise ValueError('A selected output is no longer current.')
    if state.db.execute("SELECT 1 FROM production_revisions WHERE run=? AND status='queued'",(run,)).fetchone():
        raise ValueError('A revision is pending for this stage.')
    from orchestrator.artifact_replacements import scope
    replacement_revisions=[dict(h) for h in state.db.execute('SELECT id,revision,current_decision FROM production_replacement_heads WHERE scope=? ORDER BY id',(scope(state.db,run),))]
    return {'run':run,'tasks':status['tasks'],'decisions':decisions,
            'replacement_revisions':replacement_revisions,
            'contract_digest':pc.runtime_digest(rt,run),
            'control_epoch':state.get('production-control-epoch:'+run,0)}


def sources(state,rt,run,channel,request_id):
    from task_relay import production_planning as planning
    from task_relay import production_feedback
    prior=snapshot(state,rt,run,channel)
    original=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    plan=planning_origin(state,run)
    job_id=json.loads(plan['options']).get('job_request_id',plan['request_id']) if plan else original.get('origin',{}).get('job_request_id',run)
    inputs={}
    support={s['artifact']:s['operation_support'] for s in json.loads(plan['context']).get('sources',[])
             if s.get('operation_support')} if plan else {}
    assignments=[rt.spec(t) for t in prior['tasks']]
    for spec in assignments:
        for item in spec['inputs']:
            if 'artifact' not in item:continue
            path=item['path']
            if path in ('request/USER-REQUEST.txt','previous-stage/CONTEXT.json'):
                path='previous-stage/'+run+'/'+path
            inputs[item['artifact']]=planning.source_entry(rt,item['artifact'],path,item['purpose'],item['authority'])
            if item['artifact'] in support:inputs[item['artifact']]['operation_support']=support[item['artifact']]
    for d in prior['decisions']:
        a=rt.artifact(d['artifact'])
        inputs[a['id']]=planning.source_entry(rt,a['id'],'previous-stage/'+run+'/selected/'+d['task']+'/'+a['path'],
            'User-selected output for '+d['purpose'],
            'Exact user-selected version for the stated purpose; selection does not authorize further scope or validate unrelated claims.')
    # Include current explicit replacements without rewriting the preserved prior plan
    # or discarding source context. The new plan still needs its own approval.
    from orchestrator.artifact_replacements import selected,scope
    for head in state.db.execute('SELECT * FROM production_replacement_heads WHERE scope=? ORDER BY id',(scope(state.db,run),)):
        members=[selected(rt,d) for d in json.loads(head['members'])]
        if not any(d['artifact'] in inputs for d in members):continue
        decision=selected(rt,head['current_decision']);a=rt.artifact(decision['artifact'])
        inputs[a['id']]=planning.source_entry(rt,a['id'],'current-selection/'+head['id']+'/'+a['path'],
            'Current replacement selection for '+head['purpose'],
            'Exact current version selected by the recorded replacement decision. Earlier versions are historical context. New work still needs approval.')
    # Carry complete instructions and feedback, not a model summary of the job.
    history={'job_request_id':job_id,'previous_stage':prior,'original_plan':original,'assignments':assignments,
             'original_request':plan['request'] if plan else None,
             'user_feedback':production_feedback.collect(state,run,request_id)}
    from orchestrator.artifact_replacements import view as replacement_view
    history['artifact_replacements']=replacement_view(state.db,run)
    root=state.media_dir.parent/'production-planning'/('plan-'+str(request_id));root.mkdir(parents=True,exist_ok=True)
    path=root/'previous-stage.json';encoded=c.encoded(history)
    if path.exists() and (path.is_symlink() or path.read_text()!=encoded):raise ValueError('Stage context identity changed.')
    path.write_text(encoded)
    aid=rt.register(path,'Exact previous-stage decisions and instructions',run='plan-'+str(request_id),path='previous-stage/CONTEXT.json')
    inputs[aid]=planning.source_entry(rt,aid,'previous-stage/CONTEXT.json','Prior job instructions, assignments and exact decisions',
        'Recorded job history; latest explicit user direction controls the next stage. Prior model text is context, not new authorization.')
    return prior,list(inputs.values()),job_id


def verify(state,rt,payload,plan_id,channel,ignore_request_id=None):
    recovery=payload.get('execution_recovery')
    if recovery:
        if recovery.get('reviewed_repair'):
            from .production_repairs import verify as verify_repair
            verify_repair(state,rt,recovery['reviewed_repair'])
        prior=recovery['baseline']
        link=state.db.execute('SELECT * FROM production_stage_links WHERE parent=?',(prior['run'],)).fetchone()
        if not link or link['plan_id']!=plan_id or link['child']:
            raise ValueError('Execution recovery was replaced or already started.')
        if failed_execution_snapshot(state,rt,prior['run'],channel,recovery.get('kind'))!=prior:
            raise ValueError('Failed execution changed after the repair plan was prepared.')
    prior=payload.get('previous_stage')
    if not prior:return
    if state.db.execute("SELECT 1 FROM orchestrator_chats WHERE focus=? AND id!=? AND status IN ('queued','sending','guides_pending')",(prior['run'],ignore_request_id if ignore_request_id is not None else -1)).fetchone():
        raise ValueError('A reply about the previous stage is still being processed.')
    link=state.db.execute('SELECT * FROM production_stage_links WHERE parent=?',(prior['run'],)).fetchone()
    if not link or link['plan_id']!=plan_id or link['child']:
        raise ValueError('This next-stage plan was replaced or already started.')
    if snapshot(state,rt,prior['run'],channel)!=prior:
        raise ValueError('Previous-stage decisions or instructions changed; plan the next stage again.')


def replace_unexecuted_plan(state,rt,payload,old_id,new_id,channel):
    """Move an unchanged stage handoff to its retry, before any host execution."""
    if not state.db.in_transaction:raise ValueError('Plan replacement requires an atomic transaction.')
    verify(state,rt,payload,old_id,channel)
    parents=set()
    if payload.get('previous_stage'):parents.add(payload['previous_stage']['run'])
    if payload.get('execution_recovery'):parents.add(payload['execution_recovery']['baseline']['run'])
    for parent in parents:
        changed=state.db.execute('UPDATE production_stage_links SET plan_id=? WHERE parent=? AND plan_id=? AND child IS NULL',
                                 (new_id,parent,old_id)).rowcount
        if changed!=1:raise ValueError('The stage handoff changed; no replacement was applied.')
        rt.event(parent,None,None,'planning_successor_linked',{'previous_plan':old_id,'successor_plan':new_id})


def register(state,rt,payload,plan_id,child):
    recovery=payload.get('execution_recovery')
    if recovery:
        parent=recovery['baseline']['run']
        if recovery.get('reviewed_repair'):
            state.db.execute("UPDATE production_auto_repairs SET status='resumed' WHERE parent=? AND plan_id=? AND status='awaiting_start'",(parent,plan_id))
        state.db.execute('UPDATE production_stage_links SET child=? WHERE parent=? AND plan_id=?',(child,parent,plan_id))
        rt.event(child,None,None,'execution_repair_started',{'parent':parent,'plan_id':plan_id,
                 'script_replacement':recovery.get('script_replacement'),'kind':recovery.get('kind'),'reused_completed_tasks':recovery['reused_completed_tasks']})
    prior=payload.get('previous_stage')
    if not prior:return
    state.db.execute('UPDATE production_stage_links SET child=? WHERE parent=? AND plan_id=?',(child,prior['run'],plan_id))
    rt.event(child,None,None,'selected_stage_created',{'parent':prior['run'],'plan_id':plan_id,
        'job_request_id':payload['options']['job_request_id'],'decisions':prior['decisions']})
