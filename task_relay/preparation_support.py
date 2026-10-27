"""Admit missing registered data checkers under an existing delivery grant."""
import copy
import hashlib
import json


def documents(capability, frozen):
    if capability!='images.fetch':return {}
    from orchestrator.execution import REGISTRY
    if frozen.get('version')!=REGISTRY[capability]['version']:return {}
    from orchestrator.browser_images import validator_source
    return {'contract.json':json.dumps(frozen,ensure_ascii=False,indent=2)+'\n','validate.py':validator_source()}


def repair(rt,run,scope):
    """One confirmed failed local preparation; no active/unknown downstream work."""
    if not rt.db.in_transaction:raise ValueError('Preparation support recovery must be atomic.')
    row=rt.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()
    if not row or row['status']!='active' or scope.get('delivery_completion_policy_version')!=1:return None
    tasks=rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)).fetchall()
    if any(t['status'] in ('running','launching','cancelling','uncertain','cancelled') for t in tasks):return None
    blocked=[t for t in tasks if t['status']=='blocked']
    if len(blocked)!=1:return None
    task=blocked[0];spec=rt.spec(task)
    if spec.get('execution') or spec.get('review_of') or spec.get('user_gate') or not task['latest'] or task['attempts']>=spec['max_attempts']:return None
    attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
    receipt=json.loads(attempt['receipt'] or '{}')
    if (attempt['state']!='blocked' or receipt.get('status')!='finished' or receipt.get('exit_code')!=0
            or receipt.get('reason') is not None or receipt.get('pending_requests')
            or receipt.get('browser',{}).get('uncertain_actions')):return None
    if rt.db.execute("SELECT 1 FROM production_events WHERE run=? AND task=? AND kind='preparation_support_recovered'",(run,task['id'])).fetchone():return None
    frozen={s['id']:s for s in scope.get('graph_operations',[])}
    consumers=[t for t in tasks if any(i.get('from_task')==task['id'] for i in rt.spec(t).get('inputs',[]))
               and rt.spec(t).get('execution',{}).get('capability') in frozen]
    if not consumers or any(t['attempts'] for t in tasks if t['id']!=task['id']):return None
    specs=[];added=[]
    for consumer in consumers:
        operation=rt.spec(consumer)['execution'];capability=operation['capability'];contract=frozen[capability]
        if operation['version']!=contract['version']:return None
        files=documents(capability,contract)
        prefix='operation-support/'+capability+'/'
        if not files or any(i['path'].startswith(prefix) for i in spec['inputs']):continue
        for name,text in files.items():
            digest=hashlib.sha256(text.encode()).hexdigest();path=rt.root/'preparation-support'/digest/name
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                if path.is_symlink() or path.read_text()!=text:raise ValueError('Registered preparation support changed.')
            else:path.write_text(text)
            aid=rt.register(path,'Registered local preparation checker',run=run,path=prefix+name)
            item=dict(artifact=aid,path=prefix+name,purpose='Exact connector data contract and local validation',
                      authority='Registered schema only; no external execution permission',media_type='text/x-python' if name.endswith('.py') else 'application/json')
            added.append(dict(artifact=aid,path=item['path'],sha256=digest));specs.append(item)
    if not specs:return None
    replacement=copy.deepcopy(spec)
    replacement['inputs']+=specs
    for artifact in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(task['latest'],)):
        replacement['inputs'].append(dict(artifact=artifact['id'],path='previous/'+artifact['path'],
            purpose='Retained draft to convert and validate',authority='Prior candidate, not approval',previous_delivery=True))
    replacement['instruction']+='\nRead the supplied operation-support contract.json and validate.py. Convert the retained draft using observed source evidence only. Run the local validator on the exact declared output; it performs no network or downstream execution.'
    replacement['revision']=dict(source='registered_preparation_support',previous_attempt=task['latest'],instruction='Supply the omitted registered local input contract; preserve original sources, checks and limits.')
    from orchestrator.contracts import assignment
    replacement=assignment(replacement)
    from orchestrator.worker_capabilities import backend_for
    plan=json.loads(rt.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    rt.checked_inputs(run,replacement,backend_for(replacement,plan['backend']))
    aid=rt.new_assignment(run,replacement)
    rt.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,task['id']))
    for reviewer in tasks:
        review=rt.spec(reviewer)
        if review.get('review_of')!=task['id']:continue
        review['inputs']+=copy.deepcopy(specs)
        review_id=rt.new_assignment(run,assignment(review))
        rt.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(review_id,run,reviewer['id']))
    proof=dict(task=task['id'],previous_attempt=task['latest'],assignment=aid,added=added,
               provider_calls=0,attempts_reset=False,acceptance=False)
    rt.event(run,task['id'],task['latest'],'preparation_support_recovered',proof)
    return proof


def reconcile(state):
    from orchestrator.runtime import Runtime
    from orchestrator.storage import transaction
    from . import pipelines,production_control as pc
    from .relay_channels import ScopedState
    for p in state.db.execute("SELECT p.* FROM relay_pipelines p JOIN completion_recovery_grants g ON g.pipeline=p.id WHERE p.status='blocked'").fetchall():
        s=state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND status NOT IN ('completed','skipped') ORDER BY position LIMIT 1",(p['id'],)).fetchone()
        if not s or s['status']!='blocked' or s['target_kind']!='plan_production':continue
        current=state.db.execute('SELECT * FROM production_plans WHERE id=?',(s['target'],)).fetchone()
        if not current:continue
        parent=json.loads(current['context']).get('completion_recovery',{}).get('parent')
        if current['status']=='started':original=current
        elif current['status'] in ('blocked','needs_input') and not current['run'] and parent:
            original=state.db.execute("SELECT * FROM production_plans WHERE run=? AND status='started'",(parent,)).fetchone()
        else:continue
        if not original or original['channel']!=p['channel']:continue
        scoped=ScopedState(state,p['channel']);run=original['run'];scope=json.loads(original['context'])
        if scope.get('delivery_completion_policy_version')!=1 or scoped.get('production-control-epoch:'+run,0)!=0:continue
        if scope.get('pipeline_step')!=json.loads(p['spec'])['stages'][s['position']]:continue
        owner=state.db.execute('SELECT pipeline,step FROM relay_pipeline_requests WHERE request_id=?',
                               (json.loads(original['options']).get('job_request_id',original['request_id']),)).fetchone()
        if not owner or owner['pipeline']!=p['id'] or owner['step']!=s['id']:continue
        rt=Runtime(pc.root(scoped),connection=state.db)
        if rt.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0]!='active':continue
        expected={t['id']:t for t in json.loads(original['plan'])['tasks']}
        if {t['id']:rt.spec(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))}!=expected:continue
        try:
            with transaction(state.db):
                if not pipelines.check_plan(scoped,p,s,original):continue
                proof=repair(rt,run,scope)
                if not proof:continue
                scoped.put('production-enabled:'+run,pc.runtime_digest(rt,run))
                state.db.execute("UPDATE relay_pipeline_steps SET status='running',target=?,error=NULL WHERE pipeline=? AND id=?",(original['id'],p['id'],s['id']))
                state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
                pipelines.event(state,p['id'],s['id'],'preparation_support_recovered',dict(run=run,proof=proof,superseded_unexecuted_plan=current['id'],authority='existing delivery and remaining attempt grant'))
        except (ValueError,OSError):continue
