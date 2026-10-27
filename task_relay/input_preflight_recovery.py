"""Recover confirmed local admission failures; never replay a worker attempt."""
import json
import copy
import hashlib


def validate_dispatch(rt,task,inputs):
    """Recheck the committed zero-dispatch recovery before spending an attempt."""
    if task['attempts'] or task['latest'] is not None:return
    row=rt.db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND kind='input_preflight_recovered' ORDER BY id DESC LIMIT 1",(task['run'],task['id'])).fetchone()
    if not row:return
    receipt=json.loads(row[0])
    if receipt.get('capacity'):
        proof=receipt['capacity']
        if receipt['assignment']!=task['assignment'] or rt.spec(task)!=proof['replacement']:
            raise ValueError('Recovered review assignment changed before dispatch.')
        planner=rt.db.execute('SELECT * FROM production_plans WHERE id=?',(proof['planner'],)).fetchone()
        if not planner or hashlib.sha256((planner['plan']+planner['context']+planner['options']).encode()).hexdigest()!=proof['authority_sha256']:
            raise ValueError('Recovered review authority changed before dispatch.')
        original=dict(task,assignment=proof['original_assignment'])
        expected=budget_replacement(rt,original,planner)
        if not expected or expected[0]!=proof['replacement'] or expected[2]!=proof:
            raise ValueError('Recovered review capacity proof changed before dispatch.')
    elif receipt['assignment']!=task['assignment']:return
    current=[dict(artifact=i['artifact'],path=i['path'],sha256=i['sha256'],bytes=i['bytes']) for i in inputs]
    if current!=receipt['inputs']:
        raise ValueError('Recovered input versions changed before dispatch; no attempt spent.')


def authorized_budget(db, run, spec, original):
    """Project only an exact recorded local allocation onto its original grant."""
    row=db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND kind='input_preflight_recovered' ORDER BY id DESC LIMIT 1",(run,spec['id'])).fetchone()
    proof=json.loads(row[0]).get('capacity') if row else None
    if not proof or spec!=proof['replacement']:return False
    if {k:v for k,v in spec.items() if k!='limits'}!={k:v for k,v in original.items() if k!='limits'}:return False
    old=db.execute('SELECT spec FROM production_assignments WHERE id=?',(proof['original_assignment'],)).fetchone()
    planner=db.execute('SELECT plan,context,options FROM production_plans WHERE id=?',(proof['planner'],)).fetchone()
    return bool(old and json.loads(old[0])==original and planner and hashlib.sha256(
        (planner['plan']+planner['context']+planner['options']).encode()).hexdigest()==proof['authority_sha256'])


def budget_replacement(rt, task, planner):
    """Recompute a never-dispatched review allocation within its saved ceiling."""
    from .review_budget_recovery import budgets
    from orchestrator.worker_capabilities import backend_for
    from orchestrator.evidence_context import EvidenceCapacityError
    if not planner or planner['status']!='started' or planner['run']!=task['run']:return None
    spec=rt.spec(task)
    if not spec.get('review_of') or any(spec.get(k) for k in ('user_gate','browser','computer','execution','operation_contract')):return None
    plan=json.loads(planner['plan']);original=next((t for t in plan['tasks'] if t['id']==task['id']),None)
    if original!=spec:return None
    backend=backend_for(spec,plan['backend'])
    try:rt.checked_inputs(task['run'],copy.deepcopy(spec),backend)
    except EvidenceCapacityError:pass
    else:return None
    # Bind all estimates against the frozen graph, then select only this worker.
    budgets(plan,json.loads(planner['context']),json.loads(planner['options']))
    replacement=next(t for t in plan['tasks'] if t['id']==task['id'])
    if replacement==spec:return None
    inputs=rt.checked_inputs(task['run'],replacement,backend)
    replacement.pop('evidence_context',None)
    target=rt.task(task['run'],spec['review_of'])
    attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    if target['status']!='awaiting_review' or not attempt or attempt['state']!='completed':return None
    done=json.loads(attempt['receipt'] or '{}')
    if done.get('status')!='finished' or done.get('exit_code') or done.get('pending_requests') or done.get('cleanup_error'):return None
    proof=dict(kind='review_capacity',original_assignment=task['assignment'],replacement=replacement,
               planner=planner['id'],authority_sha256=hashlib.sha256(
                   (planner['plan']+planner['context']+planner['options']).encode()).hexdigest(),
               candidate=target['latest'],candidate_receipt=hashlib.sha256(attempt['receipt'].encode()).hexdigest())
    return replacement,inputs,proof


def requeue(rt,run,planner=None):
    if not rt.db.in_transaction:raise ValueError('Input admission recovery must be atomic.')
    from orchestrator import executors,worker_capabilities
    row=rt.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()
    tasks=rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)).fetchall()
    if not row or row['status']!='active' or any(t['status'] in ('launching','running','cancelling','uncertain','cancelled') for t in tasks):return []
    plan=json.loads(rt.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    candidates=[]
    for task in tasks:
        if task['status']!='blocked' or task['attempts']!=0 or task['latest'] is not None:continue
        spec=rt.spec(task);backend=worker_capabilities.backend_for(spec,plan['backend'])
        if backend['type'] not in executors.FILE_TYPES:continue
        event=rt.db.execute("SELECT id,data FROM production_events WHERE run=? AND task=? AND kind='input_preflight_blocked' ORDER BY id DESC LIMIT 1",(run,task['id'])).fetchone()
        proof=json.loads(event['data']) if event else {}
        if proof.get('assignment')!=task['assignment'] or proof.get('dispatched') is not False:continue
        replacement=None;capacity=None
        try:
            revised=budget_replacement(rt,task,planner)
            if revised:
                replacement,inputs,capacity=revised
            else:
                from orchestrator.evidence_context import recoverable_admission
                if not recoverable_admission(proof):continue
                inputs=rt.checked_inputs(run,spec,backend)
                if not spec.get('evidence_context') and not (
                        executors.text_input_limit(backend,spec)>executors.MAX_INPUT_BYTES and
                        sum(i['bytes'] for i in inputs)>executors.MAX_INPUT_BYTES):continue
        except (ValueError,OSError):continue
        # Historical preflight events have no input manifest. Prove that each
        # exact current artifact was registered before that stopped boundary.
        sealed=True
        for item in inputs:
            registered=rt.db.execute("SELECT id,data FROM production_events WHERE kind='artifact_registered' AND json_extract(data,'$.artifact')=? ORDER BY id LIMIT 1",(item['artifact'],)).fetchone()
            if not registered or registered['id']>=event['id'] or json.loads(registered['data']).get('sha256')!=item['sha256']:
                sealed=False;break
        if not sealed:continue
        candidates.append((task,inputs,spec.get('evidence_context'),replacement,capacity))
    receipts=[]
    for task,inputs,context,replacement,capacity in candidates:
        assignment=task['assignment']
        if replacement:
            assignment=rt.new_assignment(run,replacement)
            rt.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?',(assignment,run,task['id']))
        receipt=dict(task=task['id'],assignment=assignment,dispatched=False,attempts_reset=False,
                     provider_calls=0,evidence_context=context,
                     inputs=[dict(artifact=i['artifact'],path=i['path'],sha256=i['sha256'],bytes=i['bytes']) for i in inputs])
        if capacity:receipt['capacity']=capacity
        rt.db.execute("UPDATE production_tasks SET status='queued' WHERE run=? AND id=?",(run,task['id']))
        rt.event(run,task['id'],None,'input_preflight_recovered',receipt)
        receipts.append(receipt)
    return receipts


def reconcile(state):
    from orchestrator.runtime import Runtime
    from orchestrator.storage import transaction
    from . import pipelines,production_control as pc
    from .relay_channels import ScopedState
    rows=state.db.execute("SELECT p.* FROM relay_pipelines p JOIN completion_recovery_grants g ON g.pipeline=p.id WHERE p.status='blocked' ORDER BY p.created LIMIT 20").fetchall()
    for p in rows:
        s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status NOT IN ('completed','skipped') ORDER BY position LIMIT 1",(p['id'],)).fetchone()
        if not s or s['status']!='blocked' or s['target_kind'] not in ('plan_production','production_run') or s['error']!='Production blocked; no attempts reset.':continue
        stage=json.loads(p['spec']).get('stages',[])
        if s['position']>=len(stage) or stage[s['position']].get('gate')!='none':continue
        if s['target_kind']=='plan_production':
            plan=state.db.execute('SELECT * FROM production_plans WHERE id=?',(s['target'],)).fetchone()
        else:
            plans=state.db.execute("SELECT * FROM production_plans WHERE run=? AND status='started' AND channel=?",(s['target'],p['channel'])).fetchall()
            plan=plans[0] if len(plans)==1 else None
        if not plan or plan['status']!='started' or not plan['run'] or plan['channel']!=p['channel']:continue
        scoped=ScopedState(state,p['channel']);run=plan['run']
        if scoped.get('production-control-epoch:'+run,0)!=0:continue
        rt=Runtime(pc.root(scoped),connection=state.db)
        current=state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()
        expected=json.loads(plan['plan'])
        expected_digest=pc.contract_digest(state.db,run,current[0],sorted(expected['tasks'],key=lambda t:t['id'])) if current else None
        if not current or json.loads(current[0])!=expected or pc.runtime_digest(rt,run)!=expected_digest:continue
        try:
            with transaction(state.db):
                if not pipelines.check_plan(scoped,p,s,plan):continue
                receipts=requeue(rt,run,plan)
                if receipts:
                    revised=json.loads(current[0]);revised['tasks']=[rt.spec(t) for t in state.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(run,))]
                    if not pipelines.check_plan(scoped,p,s,dict(plan,plan=json.dumps(revised))):
                        raise ValueError('Review allocation exceeds the original automatic stage authority.')
                if not receipts:continue
                scoped.put('production-enabled:'+run,pc.runtime_digest(rt,run))
                state.db.execute("UPDATE relay_pipeline_steps SET status='running',error=NULL WHERE pipeline=? AND id=?",(p['id'],s['id']))
                state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
                pipelines.event(state,p['id'],s['id'],'input_preflight_recovered',dict(run=run,receipts=receipts,authority='unchanged started plan and existing completion grant'))
        except (ValueError,OSError):continue
