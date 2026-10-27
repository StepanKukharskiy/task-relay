"""Code-proved native revisions within an existing completion-cycle allocation."""
import copy,hashlib,importlib,json
from pathlib import Path
from orchestrator import contracts as c


def proof(rt,baseline):
    from . import saved_evidence_revision
    return native_proof(rt,baseline) or saved_evidence_revision.proof(rt,baseline)


def native_proof(rt,baseline):
    from orchestrator.execution import REGISTRY
    prepared=projection_proof(rt,baseline)
    if prepared:return prepared
    derived=derived_projection_proof(rt,baseline)
    if derived:return derived
    if len(baseline['gaps'])!=1 or len(baseline['tasks'])!=2:return None
    if [dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(baseline['run'],))]!=baseline['tasks']:return None
    gap=baseline['gaps'][0]
    if (gap.get('kind')!='review_gaps' or gap.get('reported_decision')!='revise'
            or any(f['category'] not in ('integrity','requirements','advisory') for f in gap['findings'])):return None
    review=rt.task(baseline['run'],gap['task']);rs=rt.spec(review)
    producer=rt.task(baseline['run'],rs['review_of']);ps=rt.spec(producer)
    if producer['status']!='awaiting_review' or review['status']!='blocked':return None
    if any(t.get('user_gate') or t.get('computer') or t.get('browser') for t in (ps,rs)):return None
    hook=REGISTRY.get(ps.get('execution',{}).get('capability'),{}).get('revision_preview')
    if not hook:return None
    attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(producer['latest'],)).fetchone()
    frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if (attempt['state']!='completed' or receipt.get('status')!='finished' or receipt.get('exit_code')!=0
            or receipt.get('pending_requests') or receipt.get('cleanup_error') or receipt.get('operation',{}).get('outcome')!='completed'):return None
    module,name=hook.split(':');adapter=importlib.import_module(module);path=Path(adapter.__file__)
    current=hashlib.sha256(path.read_bytes()).hexdigest();prior=frozen.get('runtime_sources',{}).get(path.name)
    if not prior or prior==current:return None
    data={}
    for artifact in baseline['artifacts']:
        blob=Path(artifact['blob'])
        if blob.is_symlink() or hashlib.sha256(blob.read_bytes()).hexdigest()!=artifact['sha256']:return None
    for item in frozen['inputs']:
        artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
        if blob.is_symlink():return None
        raw=blob.read_bytes()
        if artifact['sha256']!=item['sha256'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:return None
        data[item['path']]=raw
    result=getattr(adapter,name)(frozen,receipt,lambda p:data[p])
    if not result:return None
    return dict(producer=producer['id'],reviewer=review['id'],attempt=attempt['id'],
        previous_runtime_sha256=prior,current_runtime_sha256=current,preview=result)


def graph(baseline,receipt,evidence):
    from .completion_recovery import DELIVERY_POLICY
    if evidence.get('kind')=='saved_evidence':
        from .saved_evidence_revision import graph as saved_graph
        return saved_graph(baseline,receipt,evidence)
    if evidence.get('kind')=='prepared_data':return projection_graph(baseline,receipt,evidence)
    plan=copy.deepcopy(baseline['plan']);plan['id']='registered-revision-'+c.digest(dict(parent=baseline['run'],cycle=receipt['cycle'],proof=evidence))[:24]
    if len(plan['tasks'])>DELIVERY_POLICY['tasks_per_cycle']:raise ValueError('Revision graph exceeds allocation')
    for task in plan['tasks']:
        if task['max_attempts']!=1 or task['limits']['seconds']>DELIVERY_POLICY['seconds'] or task['limits']['tool_calls']>DELIVERY_POLICY['tool_calls']:raise ValueError('Revision exceeds existing worker allocation')
        if task['id']==evidence['reviewer']:task['instruction']+='\n'+evidence['preview']['instruction']
    plan['origin']={**plan.get('origin',{}),'registered_revision':dict(parent=baseline['run'],cycle=receipt['cycle'],baseline_sha256=hashlib.sha256(receipt['baseline'].encode()).hexdigest(),proof=evidence)}
    return c.plan(plan)


def projection_proof(rt,baseline):
    """A completed native JSON preparation can be corrected as data locally.

    The exact independent finding, source bytes and undispatched descendants
    are required. The already authorized reviewer executor authors a new JSON
    version; native binary creation and independent reviews remain in place.
    """
    from orchestrator.execution import REGISTRY
    from orchestrator.worker_capabilities import backend_for
    if len(baseline['gaps'])!=1:return None
    gap=baseline['gaps'][0]
    if (gap.get('kind')!='review_gaps' or gap.get('reported_decision')!='revise'
            or not gap.get('candidate_task') or not gap.get('instruction')
            or not any(f.get('category') in ('requirements','integrity') for f in gap['findings'])
            or any(f.get('category') not in ('requirements','integrity','advisory') for f in gap['findings'])):return None
    tasks=[dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(baseline['run'],))]
    if tasks!=baseline['tasks']:return None
    producer=rt.task(baseline['run'],gap['candidate_task']);review=rt.task(baseline['run'],gap['task'])
    ps=rt.spec(producer);rs=rt.spec(review);meta=REGISTRY.get(ps.get('execution',{}).get('capability'),{})
    if (meta.get('data_revision')!='application/json' or meta.get('kind')!='procedure' or meta.get('external_requests')!=0
            or producer['status']!='blocked' or review['status']!='completed' or rs.get('review_of')!=producer['id']
            or len(ps['outputs'])!=1 or ps['outputs'][0].get('media_type')!='application/json'
            or backend_for(rs,baseline['plan']['backend']).get('type')!='codex-cli'):return None
    for task in tasks:
        spec=rt.spec(task);cap=REGISTRY.get(spec.get('execution',{}).get('capability'),{})
        if any(spec.get(k) for k in ('user_gate','browser','computer','operation_contract')):return None
        if task['id'] not in (producer['id'],review['id']) and task['attempts']:return None
        if spec.get('execution') and cap.get('completion_recovery')!='local_artifact':return None
    originals={}
    for task in (producer,review):
        a=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
        f=json.loads(a['frozen']);r=json.loads(a['receipt'] or '{}')
        if a['state']!='completed' or r.get('status')!='finished' or r.get('exit_code') or r.get('pending_requests') or r.get('cleanup_error'):return None
        originals[task['id']]=f
    if originals[review['id']].get('review_target')!=producer['latest']:return None
    reports=[json.loads(row[0]) for row in rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(review['latest'],))]
    report=next((r['result'] for r in reports if r.get('kind')=='model_review'),{})
    if (report.get('assignment_id')!=review['latest'] or report.get('decision')!='revise'
            or report.get('findings')!=gap['findings'] or report.get('instruction')!=gap['instruction']):return None
    candidate=rt.output(baseline['run'],producer['id'],ps['outputs'][0]['path'])
    if not candidate or candidate['attempt']!=producer['latest']:return None
    inputs={}
    for frozen in originals.values():
        for item in frozen['inputs']:
            artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
            if blob.is_symlink() or artifact['sha256']!=item['sha256'] or hashlib.sha256(blob.read_bytes()).hexdigest()!=item['sha256']:return None
            item={k:copy.deepcopy(v) for k,v in item.items() if k not in ('from_task','output')}
            if item['path'] in inputs and inputs[item['path']]['artifact']!=item['artifact']:return None
            inputs[item['path']]=item
    feedback=[]
    for artifact in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(review['latest'],)):
        blob=Path(artifact['blob'])
        if blob.is_symlink() or hashlib.sha256(blob.read_bytes()).hexdigest()!=artifact['sha256']:return None
        feedback.append(dict(artifact=artifact['id'],path='correction-review/'+artifact['path'],
            purpose='Exact independent correction findings',authority='Review evidence; original request controls scope',media_type='text/markdown'))
    if not feedback:return None
    return dict(kind='prepared_data',producer=producer['id'],reviewer=review['id'],attempt=producer['latest'],
        candidate=dict(artifact=candidate['id'],sha256=candidate['sha256'],path=candidate['path']),
        inputs=list(inputs.values()),feedback=feedback,instruction=gap['instruction'],
        **({'capacity_authority':authority} if (authority:=capacity_authority(rt,baseline)) else {}))


def derived_projection_proof(rt,baseline):
    """Carry specification or derived-artifact findings to its authorized author.

    This continues an exact registered data graph, never invents a new producer
    or grants a host operation. Every executed node must have a confirmed stop.
    """
    from orchestrator.execution import REGISTRY
    marker=baseline['plan'].get('origin',{}).get('registered_revision',{})
    prior=marker.get('proof',{})
    if prior.get('kind')!='prepared_data' or len(baseline['gaps'])!=1:return None
    gap=baseline['gaps'][0]
    if (gap.get('kind')!='review_gaps' or gap.get('reported_decision')!='revise' or not gap.get('instruction')
            or not any(f.get('category') in ('requirements','integrity') for f in gap['findings'])
            or any(f.get('category') not in ('requirements','integrity','advisory') for f in gap['findings'])):return None
    tasks=[dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(baseline['run'],))]
    if tasks!=baseline['tasks']:return None
    author=rt.task(baseline['run'],prior['producer']);review=rt.task(baseline['run'],gap['task'])
    ps=rt.spec(author);rs=rt.spec(review)
    if (author['status'] not in ('completed','awaiting_review','blocked') or ps.get('execution') or len(ps['outputs'])!=1
            or ps['outputs'][0].get('media_type')!='application/json' or not rs.get('review_of')):return None
    target=rt.task(baseline['run'],rs['review_of'])
    ancestors=set();pending=[target['id']]
    while pending:
        ident=pending.pop()
        if ident in ancestors:continue
        ancestors.add(ident);pending.extend(rt.spec(rt.task(baseline['run'],ident))['dependencies'])
    if author['id'] not in ancestors:return None
    frozen={}
    for task in tasks:
        spec=rt.spec(task);cap=REGISTRY.get(spec.get('execution',{}).get('capability'),{})
        if any(spec.get(k) for k in ('user_gate','browser','computer','operation_contract')):return None
        if spec.get('execution'):
            if cap.get('completion_recovery')!='local_artifact' or cap.get('external_requests')!=0:return None
        elif task['id']!=author['id'] and not spec.get('review_of'):return None
        if not task['attempts'] and task['status'] in ('pending','queued'):
            continue
        attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
        if not attempt:return None
        receipt=json.loads(attempt['receipt'] or '{}');frozen[task['id']]=json.loads(attempt['frozen'])
        if (attempt['state'] not in ('completed','blocked') or receipt.get('status')!='finished'
                or receipt.get('exit_code')!=0 or receipt.get('pending_requests') or receipt.get('cleanup_error')):return None
        if spec.get('execution') and receipt.get('operation',{}).get('outcome')!='completed':return None
    if frozen[review['id']].get('review_target')!=target['latest']:return None
    reports=[json.loads(r[0]) for r in rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(review['latest'],))]
    report=next((r['result'] for r in reports if r.get('kind')=='model_review'),{})
    if (report.get('decision')!='revise' or report.get('assignment_id')!=review['latest']
            or report.get('findings')!=gap['findings'] or report.get('instruction')!=gap['instruction']):return None
    # Revalidate the grant and all earlier graph/receipt identities as well.
    validate_dispatch(rt,baseline['plan'])
    candidate=rt.output(baseline['run'],author['id'],ps['outputs'][0]['path'])
    if not candidate or candidate['attempt']!=author['latest']:return None
    inputs=copy.deepcopy(frozen[author['id']]['inputs']);replaced=False
    for item in inputs:
        if item['artifact']==prior['candidate']['artifact']:
            item['artifact']=candidate['id'];item['sha256']=candidate['sha256'];replaced=True
        for key in ('from_task','output'):item.pop(key,None)
    if not replaced:return None
    feedback=[]
    for artifact in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(review['latest'],)):
        feedback.append(dict(artifact=artifact['id'],path='correction-review/'+review['latest']+'/'+artifact['path'],
            purpose='Exact final-artifact correction findings',authority='Review evidence; original request controls scope',media_type='text/markdown'))
    if not feedback:return None
    for item in inputs+feedback:
        artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
        if blob.is_symlink() or hashlib.sha256(blob.read_bytes()).hexdigest()!=artifact['sha256']:return None
        if item.get('sha256',artifact['sha256'])!=artifact['sha256']:return None
    return dict(kind='prepared_data',producer=author['id'],reviewer=review['id'],attempt=author['latest'],
        candidate=dict(artifact=candidate['id'],sha256=candidate['sha256'],path=candidate['path']),
        inputs=inputs,feedback=feedback,instruction=gap['instruction'],derived_target=target['latest'],
        **({'capacity_authority':authority} if (authority:=capacity_authority(rt,baseline)) else {}))


def capacity_authority(rt, baseline):
    """Bind pooled reservations to the original admitted stage, not a new grant."""
    from .completion_recovery import DELIVERY_POLICY as policy
    if not any(not t.get('execution') and any(t['limits'][k]>policy[k] for k in ('seconds','tool_calls'))
               for t in baseline['plan']['tasks']):
        return None
    run=baseline['run'];seen=set()
    while run not in seen and len(seen)<50:
        seen.add(run)
        planner=rt.db.execute('SELECT id,plan,context,options FROM production_plans WHERE run=?',(run,)).fetchall()
        if len(planner)==1:
            row=planner[0];options=json.loads(row['options'])
            return dict(planner=row['id'],sha256=hashlib.sha256((row['plan']+row['context']+row['options']).encode()).hexdigest(),
                        limits=options.get('limits',{}),workers=options.get('worker_catalog',[]))
        saved=rt.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()
        if not saved:break
        run=json.loads(saved[0]).get('origin',{}).get('registered_revision',{}).get('parent')
        if not run:break
    return dict(limits={},workers=[])


def reserve_capacity(plan, authority, policy):
    """A local worker may reserve multiple slots, never more total work.

    Task semantics, provider, attempt count and the original admitted ceiling
    remain binding. The exact reservation is part of the committed graph hash.
    """
    import math
    from orchestrator.worker_capabilities import backend_for
    from .workflow_state import Hold
    reservations=[]
    for task in plan['tasks']:
        required=copy.deepcopy(task['limits'])
        if not task.get('execution'):
            for key in ('seconds','tool_calls'):
                task['limits'][key]=max(required[key],policy[key])
            # A smaller explicit provider limit is not a spare capacity slot.
        bounds=authority.get('limits',{})
        workers=authority.get('workers',[])
        if workers and not task.get('execution'):
            backend=backend_for(task,plan['backend'])
            matches=[w for w in workers if w.get('backend')==backend]
            if len(matches)!=1:raise Hold('capacity_unproven','Correction worker has no exact frozen capacity profile.','inspect_receipt')
            bounds={k:min(v,matches[0]['limits'].get(k,v)) for k,v in bounds.items()}
        for key in ('seconds','tool_calls'):
            if task['limits'][key]>bounds.get(key,0):
                raise Hold('capacity_exhausted','Correction workload exceeds the original admitted stage or worker ceiling.','partition_or_review_authorization')
        requests=task['limits'].get('provider_requests',task['limits']['tool_calls'])
        if requests>bounds.get('provider_requests',bounds.get('tool_calls',0)):
            raise Hold('capacity_exhausted','Correction provider allowance exceeds the original admitted ceiling.','partition_or_review_authorization')
        slots=max(1,math.ceil(task['limits']['seconds']/policy['seconds']),
                  math.ceil(task['limits']['tool_calls']/policy['tool_calls']),math.ceil(requests/policy['tool_calls']))
        reservations.append(dict(task=task['id'],slots=slots,required=required,limits=copy.deepcopy(task['limits'])))
    total=sum(r['slots'] for r in reservations)
    if total>policy['tasks_per_cycle']:
        raise Hold('capacity_exhausted','Correction workload exceeds the total existing recovery reserve. Partition the work or review its authorization.','partition_or_review_authorization')
    return dict(version=1,authority=authority,slot_limits={k:policy[k] for k in ('seconds','tool_calls')},
                available_slots=policy['tasks_per_cycle'],reserved_slots=total,tasks=reservations)


def projection_graph(baseline,receipt,evidence):
    from .completion_recovery import DELIVERY_POLICY as policy
    plan=copy.deepcopy(baseline['plan']);plan['id']='data-revision-'+c.digest(dict(parent=baseline['run'],cycle=receipt['cycle'],proof=evidence))[:24]
    tasks={t['id']:t for t in plan['tasks']};author=tasks[evidence['producer']];review=tasks[evidence['reviewer']]
    # The replacement author must retain at least its paired review's workload.
    # Preserve computed requirements before removing procedural metadata.
    for key in ('seconds','tool_calls'):
        author['limits'][key]=max(author['limits'][key],review['limits'][key])
    author.pop('execution',None);author['role']='data correction';author['dependencies']=[]
    author['inputs']=copy.deepcopy(evidence['inputs']+evidence['feedback'])
    for key in ('worker','backend','tools'):
        if key in review:author[key]=copy.deepcopy(review[key])
        else:author.pop(key,None)
    author['instruction']='Correct the exact saved JSON specification supplied as a candidate. Write the new version only to '+author['outputs'][0]['path']+'. Preserve all source files, supported content, geometry, image bindings and unknowns except precise evidence-backed corrections required by the supplied independent review. Do not rebuild the specification from memory, author a binary presentation, perform research, fetch URLs, invoke applications or add unsupported facts. Use the supplied standalone operation validator and original source evidence. This is authorized internal data correction, not a human approval step.\n'+evidence['instruction']
    if evidence.get('derived_target'):
        for reviewer in plan['tasks']:
            if reviewer['id']==review['id'] or reviewer.get('review_of')==author['id']:
                reviewer['inputs']+=copy.deepcopy(evidence['feedback'])
                reviewer['instruction']+='\nIndependently verify the new corrected candidate against the exact latest saved review and source evidence, including final-artifact findings. Historical source files remain immutable; their unsupported claims may be explicitly qualified using the supplied evidence. A previous rejection is not acceptance; all original criteria still apply.'
    else:
        review['inputs']+=copy.deepcopy(evidence['feedback'])
        review['instruction']+='\nIndependently verify the new corrected specification against the exact saved review and source evidence. A previous rejection is not acceptance; all original criteria still apply.'
    pooled=evidence.get('capacity_authority')
    for task in plan['tasks']:
        task.pop('review_correction',None);task.pop('revision',None);task['max_attempts']=1
        if pooled:continue
        if not task.get('execution'):
            if task['limits']['seconds']>policy['seconds'] or task['limits']['tool_calls']>policy['tool_calls']:
                from .workflow_state import Hold
                raise Hold('capacity_exhausted','Required correction workload exceeds the existing recovery allocation. Partition the work or review its authorization before dispatch.','partition_or_review_authorization')
            task['limits']['seconds']=policy['seconds'];task['limits']['tool_calls']=policy['tool_calls']
            if 'provider_requests' in task['limits']:task['limits']['provider_requests']=policy['tool_calls']
        if task['limits']['seconds']>policy['seconds'] or task['limits']['tool_calls']>policy['tool_calls']:raise ValueError('Data correction exceeds existing worker allocation')
    capacity=reserve_capacity(plan,pooled,policy) if pooled else None
    if len(plan['tasks'])>policy['tasks_per_cycle']:raise ValueError('Data correction graph exceeds allocation')
    plan['origin']={**plan.get('origin',{}),'registered_revision':dict(parent=baseline['run'],cycle=receipt['cycle'],baseline_sha256=hashlib.sha256(receipt['baseline'].encode()).hexdigest(),proof=evidence,**({'capacity':capacity} if capacity else {}))}
    return c.plan(plan)


def queue(state,rt,p,s,baseline,cycle):
    from . import completion_recovery as recovery,pipelines,production_control as pc,relay_channels
    if not state.db.in_transaction:raise ValueError('Registered revision requires atomic intent')
    receipt=state.db.execute('SELECT * FROM completion_recoveries WHERE pipeline=? AND step=? AND cycle=?',(p['id'],s['id'],cycle)).fetchone()
    grant=state.db.execute('SELECT policy FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone()
    if not receipt or receipt['baseline']!=c.encoded(baseline) or not grant or json.loads(grant[0])!=recovery.DELIVERY_POLICY:raise ValueError('Revision allocation changed')
    if recovery.snapshot(state,baseline['run'],photo_recovery=True)!=baseline:raise ValueError('Revision baseline changed')
    evidence=proof(rt,baseline)
    if not evidence:return False
    plan=graph(baseline,receipt,evidence)
    if state.db.execute('SELECT 1 FROM production_runs WHERE id=?',(plan['id'],)).fetchone():return False
    rt.create(plan);state.put('production-enabled:'+plan['id'],pc.runtime_digest(rt,plan['id']))
    relay_channels.bind(state,'production',plan['id'],p['channel'])
    state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='production_run',target=?,error=NULL WHERE pipeline=? AND id=?",(plan['id'],p['id'],s['id']))
    state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
    pipelines.event(state,p['id'],s['id'],'registered_revision_queued',dict(parent=baseline['run'],successor=plan['id'],cycle=cycle,plan_sha256=c.digest(plan),proof=evidence,provider_planning_calls=0,attempts_reset=False,accepted=False))
    return True


def validate_dispatch(rt,plan):
    marker=plan.get('origin',{}).get('registered_revision')
    if not marker:return
    receipt,baseline=validate_recorded_intent(rt,plan)
    evidence=proof(rt,baseline)
    if evidence!=marker['proof'] or graph(baseline,receipt,evidence)!=plan:raise ValueError('Registered revision scope or implementation changed')


def validate_recorded_intent(rt,plan):
    """Validate immutable historical authority without re-running old code."""
    marker=plan['origin']['registered_revision']
    rows=rt.db.execute('SELECT * FROM completion_recoveries WHERE parent=? AND cycle=?',(marker['parent'],marker['cycle'])).fetchall()
    matched=[r for r in rows if hashlib.sha256(r['baseline'].encode()).hexdigest()==marker['baseline_sha256']]
    if len(matched)!=1:raise ValueError('Registered revision allocation missing')
    receipt=matched[0];baseline=json.loads(receipt['baseline'])
    from .completion_recovery import DELIVERY_POLICY
    grant=rt.db.execute('SELECT policy FROM completion_recovery_grants WHERE pipeline=?',(receipt['pipeline'],)).fetchone()
    if not grant or json.loads(grant[0])!=DELIVERY_POLICY:raise ValueError('Registered revision grant changed')
    for saved in baseline['attempts']:
        current=rt.db.execute('SELECT frozen,receipt FROM production_attempts WHERE id=?',(saved['id'],)).fetchone()
        if not current or any(hashlib.sha256(current[k].encode()).hexdigest()!=saved[k+'_sha256'] for k in ('frozen','receipt')):raise ValueError('Registered revision history changed')
    events=rt.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='registered_revision_queued' AND json_extract(detail,'$.successor')=?",(plan['id'],))
    if not any(json.loads(r[0]).get('plan_sha256')==c.digest(plan) for r in events):raise ValueError('Registered revision intent missing')
    return receipt,baseline


def check_output(rt,frozen,read):
    """Registered local revisions retain their adapter's evidence invariants."""
    plan=json.loads(rt.db.execute('SELECT plan FROM production_runs WHERE id=?',(frozen['run'],)).fetchone()[0])
    evidence=plan.get('origin',{}).get('registered_revision',{}).get('proof',{})
    if evidence.get('kind')!='saved_evidence' or frozen['id']!=evidence['producer']:return
    from .saved_evidence_revision import resolve
    resolve(evidence['adapter']['validate'])(read(evidence['candidate']['path']),read(frozen['outputs'][0]['path']),evidence['contract'])
