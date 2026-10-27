"""Route confirmed consumer coverage defects back to the declared source port."""
import hashlib
import json
from pathlib import Path

from orchestrator.contracts import encoded
from orchestrator.storage import transaction


def run_for(state, step):
    if step['target_kind']=='production_run':return step['target']
    if step['target_kind']=='plan_production':
        row=state.db.execute('SELECT status,run FROM production_plans WHERE id=?',(step['target'],)).fetchone()
        if row and row['status']=='started':return row['run']


def coverage_findings(findings):
    """A source rewind requires a source-coverage finding, not any requirement."""
    return (any(f.get('category')=='requirements' and f.get('code')=='missing_substantive_source' for f in findings)
            and all(f.get('category')=='advisory' or
                    f.get('category')=='requirements' and f.get('code')=='missing_substantive_source' for f in findings))


def review_proof(state,run,*,coverage_only=True):
    """Only the finished review of the current candidate can seed read recovery."""
    from .production_control import root
    from orchestrator.runtime import Runtime
    rt=Runtime(root(state),connection=state.db,read_only=True)
    if rt.status(run)['status']!='blocked':return None
    if state.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')",(run,)).fetchone():return None
    for task in state.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)):
        spec=rt.spec(task)
        if not spec.get('review_of') or not task['latest']:continue
        attempt=state.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
        receipt=json.loads(attempt['receipt'] or '{}');frozen=json.loads(attempt['frozen'])
        target=rt.task(run,spec['review_of'])
        if (attempt['state'] not in ('completed','blocked') or receipt.get('status')!='finished'
                or receipt.get('pending_requests') or receipt.get('exit_code')
                or frozen.get('review_target')!=target['latest']):continue
        for event in state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(attempt['id'],)):
            data=json.loads(event[0]);result=data.get('result',{});findings=result.get('findings',[])
            if (data.get('kind')!='model_review' or result.get('assignment_id')!=attempt['id']
                    or result.get('decision') not in ('revise','blocked')
                    or not any(f.get('category')=='requirements' for f in findings)
                    or any(f.get('category') not in ('requirements','advisory') for f in findings)):continue
            if coverage_only and not coverage_findings(findings):continue
            return dict(run=run,attempt=attempt['id'],candidate=target['latest'],
                        receipt_sha256=hashlib.sha256(attempt['receipt'].encode()).hexdigest(),
                        report_sha256=hashlib.sha256(event[0].encode()).hexdigest(),findings=findings)


def gap(state,run,rt):
    """Revalidate exact source/candidate versions without changing count policy."""
    row=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='delivery_consumer_coverage_gap' ORDER BY id DESC LIMIT 1",(run,)).fetchone()
    if not row:return None
    detail=json.loads(row[0]);p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(detail['pipeline'],)).fetchone()
    if not p:return None
    policy=json.loads(p['spec']).get('completion',{}).get('coverage')
    if policy!=detail['coverage_policy'] or review_proof(state,detail['review']['run'])!=detail['review']:return None
    inventory_step=state.db.execute('SELECT status,result FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],policy['inventory']['stage'])).fetchone()
    if (not inventory_step or inventory_step['status']!='completed'
            or json.loads(inventory_step['result'] or '{}').get('deliverables',{}).get(policy['inventory']['output'])!=detail['inventory']):return None
    from .pipelines import artifact_source
    for source in (detail['inventory'],detail['catalog']):
        if source['bytes']>5000000 or artifact_source(state,source['artifact'])!=source:return None
    artifact=rt.artifact(detail['catalog']['artifact'])
    original=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    declared=original.get('deliverables',{}).get(policy['catalog']['output'],{})
    if (artifact['run']!=run or artifact['task']!=declared.get('task') or artifact['path']!=declared.get('output')
            or rt.task(run,artifact['task'])['latest']!=artifact['attempt']):return None
    from .delivery_completion import coverage_slots
    counts=coverage_slots(json.loads(Path(detail['inventory']['path']).read_text()),json.loads(Path(detail['catalog']['path']).read_text()),policy['options_per_item'],policy.get('count_policy','required'))
    if not counts['unresolved_items'] or counts['unresolved_items']!=detail['unresolved_items']:return None
    return dict(task=artifact['task'],kind='consumer_coverage',missing=[dict(item=i,option=1) for i in counts['unresolved_items']],
                consumer_review=detail['review'],
                instruction='A finished downstream review found missing substantive coverage. Retain every supported existing option and exact source receipt; research only these unresolved inventory groups. The alternative count remains its original target or requirement. Produce the same declared source deliverables for independent review. Downstream stages will rebuild from the new reviewed versions; the old deck and findings remain unaccepted and preserved.')


def reconcile(state):
    reconcile_inapplicable(state)
    from . import completion_recovery as recovery,pipelines as pipe,production_control as pc
    from .relay_channels import ScopedState
    from orchestrator.runtime import Runtime
    rows=state.db.execute("SELECT p.* FROM relay_pipelines p JOIN completion_recovery_grants g ON g.pipeline=p.id WHERE p.status='blocked'").fetchall()
    for p in rows:
        spec=json.loads(p['spec']);completion=spec.get('completion',{});policy=completion.get('coverage')
        if not policy:continue
        scoped=ScopedState(state,p['channel'])
        consumer=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=? AND status='blocked'",(p['id'],completion['stage'])).fetchone()
        source=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=? AND status='completed'",(p['id'],policy['catalog']['stage'])).fetchone()
        inventory=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=? AND status='completed'",(p['id'],policy['inventory']['stage'])).fetchone()
        if not consumer or not source or not inventory or source['position']>=consumer['position']:continue
        source_run=run_for(scoped,source);consumer_run=run_for(scoped,consumer)
        if not source_run or not consumer_run:continue
        proof=review_proof(scoped,consumer_run)
        if not proof:continue
        grant=state.db.execute('SELECT * FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone()
        if json.loads(grant['policy'])!=recovery.DELIVERY_POLICY:continue
        affected={source['id']}
        for stage in spec['stages']:
            if any(i['stage'] in affected for i in stage.get('handoff',{}).get('inputs',[])):affected.add(stage['id'])
        if consumer['id'] not in affected:continue
        stages=[dict(s) for s in state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(p['id'],)) if s['id'] in affected]
        definitions={s['id']:s for s in spec['stages']}
        if any(definitions[s['id']]['route']!='production' or definitions[s['id']]['gate']!='none' or s['status'] not in ('completed','blocked','pending') for s in stages):continue
        held=False
        for stage in stages:
            run=run_for(scoped,stage)
            if run and (scoped.get('production-control-epoch:'+run,0) or state.db.execute('SELECT 1 FROM production_decisions WHERE run=?',(run,)).fetchone()
                        or state.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')",(run,)).fetchone()):held=True
        if held:continue
        detail=dict(pipeline=p['id'],coverage_policy=policy,review=proof,
                    inventory=json.loads(inventory['result'])['deliverables'][policy['inventory']['output']],
                    catalog=json.loads(source['result'])['deliverables'][policy['catalog']['output']])
        from .delivery_completion import coverage_slots
        from .pipelines import artifact_source
        try:
            for binding in (detail['inventory'],detail['catalog']):
                if binding['bytes']>5000000 or artifact_source(scoped,binding['artifact'])!=binding:raise ValueError('Changed upstream binding')
            counts=coverage_slots(json.loads(Path(detail['inventory']['path']).read_text()),json.loads(Path(detail['catalog']['path']).read_text()),policy['options_per_item'],policy.get('count_policy','required'))
            if not counts['unresolved_items']:continue
            detail['unresolved_items']=counts['unresolved_items']
            with transaction(state.db):
                # Rollback archive, state changes and request together if the
                # original read-only source grant cannot admit this recovery.
                current=state.db.execute('SELECT status,spec FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()
                if current['status']!='blocked' or current['spec']!=p['spec']:continue
                if dict(state.db.execute('SELECT * FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone())!=dict(grant):continue
                if any(dict(state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],s['id'])).fetchone())!=s for s in stages):continue
                if any(scoped.get('production-control-epoch:'+r,0) or state.db.execute('SELECT 1 FROM production_decisions WHERE run=?',(r,)).fetchone()
                       or state.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')",(r,)).fetchone()
                       for s in stages if (r:=run_for(scoped,s))):continue
                rt=Runtime(pc.root(scoped),connection=state.db)
                rt.event(source_run,None,None,'delivery_consumer_coverage_gap',detail)
                if gap(scoped,source_run,rt) is None:raise ValueError('Consumer evidence changed')
                state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
                state.db.execute("UPDATE relay_pipeline_steps SET status='running',error=NULL WHERE pipeline=? AND id=?",(p['id'],source['id']))
                for stage in stages:
                    if stage['id']==source['id']:continue
                    state.db.execute("UPDATE relay_pipeline_steps SET status='pending',request_id=NULL,target_kind=NULL,target=NULL,error=NULL,sources='[]',result=NULL,choices='[]' WHERE pipeline=? AND id=?",(p['id'],stage['id']))
                if not recovery.begin(scoped,dict(p,status='active'),dict(source,status='running'),source_run):raise ValueError('Upstream recovery was not admitted')
                pipe.event(scoped,p['id'],source['id'],'upstream_coverage_recovery',dict(review=proof,prior_stages=stages,unresolved_items=counts['unresolved_items'],attempts_reset=False,grant_changed=False))
        except (ValueError,OSError,KeyError):continue


def reconcile_inapplicable(state):
    """Compensate an unexecuted source detour using its exact archived stages.

    Retain paid planner replies and the spent cycle. No worker, acceptance or
    completed artifact is reset; the consumer's semantic defect remains open.
    """
    from . import pipelines as pipe,production_control as pc
    from .relay_channels import ScopedState
    from orchestrator.runtime import Runtime
    rows=state.db.execute("SELECT * FROM relay_pipeline_events WHERE kind='upstream_coverage_recovery' ORDER BY id DESC").fetchall()
    for event in rows:
        if state.db.execute("SELECT 1 FROM relay_pipeline_events WHERE pipeline=? AND kind='inapplicable_upstream_recovery_restored' AND json_extract(detail,'$.recovery_event')=?",(event['pipeline'],event['id'])).fetchone():continue
        detail=json.loads(event['detail']);proof=detail['review']
        if coverage_findings(proof['findings']):continue
        p=state.db.execute("SELECT * FROM relay_pipelines WHERE id=? AND status='blocked'",(event['pipeline'],)).fetchone()
        if not p:continue
        scoped=ScopedState(state,p['channel']);prior=detail['prior_stages']
        current=[dict(state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],s['id'])).fetchone()) for s in prior]
        source=current[0]
        if source['status']!='blocked' or source['target_kind']!='plan_production':continue
        plan=state.db.execute('SELECT * FROM production_plans WHERE id=?',(source['target'],)).fetchone()
        if not plan or plan['status']!='blocked' or plan['run'] or plan['channel']!=p['channel']:continue
        calls=state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(plan['id'],)).fetchall()
        if len(calls)!=plan['calls'] or any(c['response'] is None or c['usage'] is None for c in calls):continue
        receipt=state.db.execute('SELECT * FROM completion_recoveries WHERE pipeline=? AND step=? AND request_id=?',(p['id'],source['id'],source['request_id'])).fetchone()
        if not receipt or receipt['parent']!=run_for(scoped,prior[0]):continue
        if any(s['status']!='pending' or s['target'] or s['request_id'] or s['result'] for s in current[1:]):continue
        if review_proof(scoped,proof['run'],coverage_only=False)!=proof:continue
        rt=Runtime(pc.root(scoped),connection=state.db,read_only=True)
        valid=True
        for stage in prior:
            run=run_for(scoped,stage)
            if not run or scoped.get('production-control-epoch:'+run,0) or state.db.execute('SELECT 1 FROM production_decisions WHERE run=?',(run,)).fetchone():valid=False;break
            if rt.status(run)['status']!=('completed' if stage['status']=='completed' else 'blocked'):valid=False;break
            try:
                for artifact in json.loads(stage['result'] or '{}').get('deliverables',{}).values():
                    if pipe.artifact_source(scoped,artifact['artifact'])!=artifact:valid=False;break
            except (ValueError,OSError,KeyError):valid=False;break
        if not valid:continue
        with transaction(state.db):
            if dict(state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone())!=dict(p):continue
            if any(dict(state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],s['id'])).fetchone())!=s for s in current):continue
            if dict(state.db.execute('SELECT * FROM production_plans WHERE id=?',(plan['id'],)).fetchone())!=dict(plan):continue
            if review_proof(scoped,proof['run'],coverage_only=False)!=proof:continue
            fields=('status','request_id','target_kind','target','error','sources','result','choices')
            for stage in prior:
                state.db.execute('UPDATE relay_pipeline_steps SET '+','.join(k+'=?' for k in fields)+' WHERE pipeline=? AND id=?',tuple(stage[k] for k in fields)+(p['id'],stage['id']))
            pipe.event(scoped,p['id'],prior[-1]['id'],'inapplicable_upstream_recovery_restored',dict(
                recovery_event=event['id'],rejected_plan=plan['id'],prior_transition_sha256=hashlib.sha256(event['detail'].encode()).hexdigest(),
                reason='Confirmed review contains a content defect, not a source-coverage request',
                attempts_reset=False,grant_changed=False,planner_replies_preserved=True))
