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


def code_preparation_failure(attempt):
    """Classify stopped preparation; legacy incomplete receipts need saved evidence."""
    receipt=json.loads(attempt['receipt'] or '{}');reason=str(receipt.get('reason',''))
    if (reason.startswith('Model service unavailable (HTTP 503)') and receipt.get('status')=='finished' and receipt.get('external_outcome')=='no_pending_response'
            and not receipt.get('pending_requests') and receipt.get('provider_failures')
            and all(f.get('kind')=='synchronous_service_unavailable' and f.get('http_status')==503 for f in receipt['provider_failures'])):
        return 'provider_unavailable'
    if 'Provider request budget exhausted' in reason:return 'budget'
    if not any(s in reason for s in ('Incomplete provider response;', 'Provider generation output limit reached;', 'Provider response rejected: MALFORMED_FUNCTION_CALL;',
                                     'provider returned incomplete or unsupported tool calls.')):return None
    from pathlib import Path
    from orchestrator.gemini_worker import generation_failure
    from orchestrator import executors
    try:
        session=json.loads(attempt['session']);folder=Path(session['control'])
        requests=sorted(folder.glob('api-*.request.json'))
        if not requests:return None
        response=requests[-1].with_name(requests[-1].name.replace('.request.json','.response.json'))
        if response.is_symlink() or response.stat().st_size>1000000:return None
        if generation_failure(executors.provider_for(session['backend']),json.loads(response.read_text())):
            return 'generation_limit'
    except (KeyError,ValueError,TypeError,OSError):pass
    return None


def failed_execution_snapshot(state,rt,run,channel,kind=None):
    bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    if (bound[0] if bound else 'telegram')!=channel:raise ValueError('Recover execution in its original channel.')
    status=rt.status(run)
    if status['status']!='blocked' or any(a['state'] in ('launching','running','cancelling','uncertain') for a in status['attempts']):
        raise ValueError('Recovery requires a confirmed stopped, blocked execution; no uncertain replay.')
    failed=[t for t in status['tasks'] if t['status']=='blocked']
    if kind=='code_budget':
        from orchestrator import executors
        if len(failed)!=1:raise ValueError('Preparation recovery requires one failed producer.')
        task=failed[0];spec=rt.spec(task)
        attempt=next(a for a in status['attempts'] if a['id']==task['latest'])
        receipt=json.loads(attempt['receipt'] or '{}')
        saved=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(attempt['id'],)).fetchone()
        frozen=json.loads(saved['frozen'])
        if (spec.get('tools')!=['files','python'] or spec.get('execution') or spec.get('browser') or spec.get('review_of')
                or frozen['backend']['type'] not in executors.CODE_TYPES
                or receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
                or receipt.get('pending_requests') or not code_preparation_failure(saved)):
            raise ValueError('A confirmed local preparation budget or generation-limit failure with no pending effects is required.')
        if any(t['status'] not in ('blocked','queued','completed') or (t['status']=='queued' and t['attempts']) for t in status['tasks']):
            raise ValueError('Other task states require review first.')
        if any(t['attempts'] and task['id'] in rt.spec(t)['dependencies'] for t in status['tasks']):
            raise ValueError('Downstream work already started.')
        return {'run':run,'tasks':status['tasks'],'attempts':status['attempts'],
                'contract_digest':pc.runtime_digest(rt,run),'control_epoch':state.get('production-control-epoch:'+run,0)}
    if kind=='browser_setup':
        if not failed:
            raise ValueError('Browser setup recovery requires a failed task.')
        for task in failed:
            spec=rt.spec(task)
            attempt=next(a for a in status['attempts'] if a['id']==task['latest'])
            receipt=json.loads(attempt['receipt'] or '{}')
            if receipt.get('status')!='finished':raise ValueError('Worker exit is not confirmed.')
            if spec.get('browser'):
                actions=receipt.get('browser',{}).get('actions')
                if (not isinstance(actions,list) or any(a.get('status')!='observed' for a in actions)
                        or receipt.get('browser',{}).get('uncertain_actions') or receipt.get('pending_requests')):
                    raise ValueError('Browser setup recovery requires read-only observed actions; no submission replay.')
            elif spec.get('execution',{}).get('capability')=='images.collect':
                if receipt.get('operation',{}).get('reason')!='Registered operation input byte limit exceeded.':
                    raise ValueError('Image collection may already have dispatched; no setup replay.')
            else:raise ValueError('Unsupported failed task in browser setup recovery.')
        if any(t['status'] not in ('blocked','queued','completed') for t in status['tasks']):
            raise ValueError('Other task states require review first.')
        return {'run':run,'tasks':status['tasks'],'attempts':status['attempts'],
                'contract_digest':pc.runtime_digest(rt,run),'control_epoch':state.get('production-control-epoch:'+run,0)}
    if len(failed)!=1:raise ValueError('Recovery requires one failed operation.')
    capability=rt.spec(failed[0]).get('execution',{}).get('capability')
    if kind=='review_revision':
        if capability or rt.spec(failed[0]).get('browser'):
            raise ValueError('Review correction recovery cannot replay an operation or browser task.')
        reviewer=rt.reviewer(run,failed[0]['id'])
        if not reviewer or reviewer['status']!='completed':
            raise ValueError('A completed independent review is required.')
        repairing={failed[0]['id'],reviewer['id']}
        by_id={t['id']:rt.spec(t) for t in status['tasks']}
        def depends_on_repair(ident):
            return ident in repairing or any(depends_on_repair(d) for d in by_id[ident]['dependencies'])
        if any(t['attempts'] and t['id'] not in repairing
               and (t['status']!='completed' or depends_on_repair(t['id'])) for t in status['tasks']):
            raise ValueError('Other work already started; do not replay downstream tasks.')
        if not state.db.execute("SELECT 1 FROM production_events WHERE run=? AND task=? AND attempt=? AND kind='revision_limit'",(run,failed[0]['id'],failed[0]['latest'])).fetchone():
            raise ValueError('A saved exhausted review correction receipt is required.')
    elif kind=='local_inputs':
        from orchestrator.execution import REGISTRY
        spec=REGISTRY.get(capability,{})
        if spec.get('kind')!='procedure' or spec.get('external_requests')!=0:
            raise ValueError('Input recovery is limited to local procedures without external requests.')
    elif capability not in ('rhino.run_python','blender.run_python','rhino3dm.run_python'):
        raise ValueError('Script repair requires one failed host Python operation.')
    attempt=next(a for a in status['attempts'] if a['id']==failed[0]['latest'])
    receipt=json.loads(attempt['receipt'] or '{}')
    if kind=='review_revision':
        if attempt['state']!='completed' or receipt.get('status')!='finished':
            raise ValueError('The reviewed draft must be confirmed finished.')
    elif receipt.get('status')!='finished' or receipt.get('operation',{}).get('outcome')!='failed':
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
        if task['latest']!=a['attempt'] or a['task']!=task['id'] or d['purpose']!=rt.decision_purpose(task):
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
    # Preserve workflow port identities through preparation -> exact host execution.
    # They identify selected versions, not interchangeable files with equal bytes.
    if plan:
        identities={s['artifact']:s['workflow_artifact'] for s in json.loads(plan['context']).get('sources',[]) if s.get('workflow_artifact')}
        for ident,source in inputs.items():
            if ident in identities:source['workflow_artifact']=identities[ident]
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


def retain_completed_sources(rt,run,payload,options,result,done):
    """Bind completed inputs/deliverables by identity; never replay their producers."""
    import copy
    from . import production_planning as planning
    tasks=result['plan']['tasks']=[t for t in result['plan']['tasks'] if t['id'] not in done]
    for task in tasks:
        task['dependencies']=[d for d in task.get('dependencies',[]) if d not in done]
        for item in task.get('inputs',[]):
            if item.get('from_task') not in done:continue
            producer=item['from_task']
            artifact=rt.output(run,producer,item['output'])
            output=next(o for o in rt.spec(done[producer])['outputs'] if o['path']==item['output'])
            if output.get('media_type'):item['media_type']=output['media_type']
            source=planning.source_entry(rt,artifact['id'],'recovery/completed/'+producer+'/'+item['output'],
                item['purpose'],'Exact completed output; preserve its saved independent review receipt.')
            planning.verify_artifact(rt,source)
            if not any(s['artifact']==source['artifact'] for s in payload['sources']):payload['sources'].append(source)
            item.pop('from_task');item.pop('output');item['artifact']=artifact['id']
    options['step_capabilities']=sorted({t['execution']['capability'] for t in tasks if t.get('execution')})
    retained=copy.deepcopy(payload.get('execution_recovery',{}).get('completed_deliverables',{}))
    for binding in retained.values():
        source=planning.source_entry(rt,binding['artifact'],'recovery/retained/'+binding['artifact']+'/'+binding['output'],
            binding['description'],'Exact completed deliverable from an earlier recovery; preserve its identity.')
        planning.verify_artifact(rt,source)
        if source['sha256']!=binding['sha256']:raise ValueError('Previously retained deliverable changed.')
        if not any(s['artifact']==source['artifact'] for s in payload['sources']):payload['sources'].append(source)
    for name,binding in list(result.get('deliverable_map',{}).items()):
        if binding.get('task') not in done:continue
        artifact=rt.output(run,binding['task'],binding['output'])
        source=planning.source_entry(rt,artifact['id'],'recovery/completed/'+binding['task']+'/'+binding['output'],
            options['deliverables'][name],'Exact completed deliverable; keep its prior review and artifact identity.')
        planning.verify_artifact(rt,source)
        if not any(s['artifact']==source['artifact'] for s in payload['sources']):payload['sources'].append(source)
        retained[name]={'description':options['deliverables'].pop(name),'artifact':artifact['id'],
                        'sha256':artifact['sha256'],'run':run,**binding}
        result['deliverable_map'].pop(name)
    return retained
