"""Compile local, independently reviewed projections of confirmed read results.

Transport is never re-dispatched. Registered format adapters decide admission
and validate the projection; the persistent revision owner retains authority.
"""
import copy
import hashlib
import importlib
import json
import shlex
import sys
from pathlib import Path
from orchestrator import contracts as c


def resolve(hook):
    module,name=hook.split(':')
    return getattr(importlib.import_module(module),name)


def proof(rt,baseline):
    if baseline['plan'].get('origin',{}).get('registered_revision',{}).get('proof',{}).get('kind')=='saved_evidence':
        return repair_proof(rt,baseline)
    from orchestrator.execution import REGISTRY
    from orchestrator.worker_capabilities import backend_for
    if len(baseline['gaps'])!=1 or len(baseline['tasks'])!=2:return None
    gap=baseline['gaps'][0]
    if (gap.get('kind')!='review_gaps' or gap.get('reported_decision')!='revise'
            or not gap.get('instruction') or not gap.get('findings')
            or not any(f['category']=='integrity' for f in gap['findings'])
            or any(f['category'] not in ('integrity','advisory') for f in gap['findings'])):return None
    tasks=[dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(baseline['run'],))]
    if tasks!=baseline['tasks']:return None
    review=rt.task(baseline['run'],gap['task']);rs=rt.spec(review)
    if not rs.get('review_of'):return None
    producer=rt.task(baseline['run'],rs['review_of']);ps=rt.spec(producer)
    cap=ps.get('execution',{}).get('capability');meta=REGISTRY.get(cap,{})
    adapter=meta.get('evidence_revision')
    if (not adapter or not meta.get('saved_evidence') or len(ps['outputs'])!=1
            or ps['outputs'][0].get('media_type')!=adapter['media_type']
            or producer['status']!='awaiting_review' or review['status']!='blocked'
            or backend_for(rs,baseline['plan']['backend']).get('type')!='codex-cli'
            or any(t.get(k) for t in (ps,rs) for k in ('user_gate','browser','computer','operation_contract'))):return None
    frozen={}
    for task in (producer,review):
        a=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
        if not a:return None
        r=json.loads(a['receipt'] or '{}');frozen[task['id']]=json.loads(a['frozen'])
        if (a['state'] not in ('completed','blocked') or r.get('status')!='finished'
                or r.get('exit_code')!=0 or r.get('pending_requests') or r.get('cleanup_error')):return None
        if task['id']==producer['id'] and r.get('operation',{}).get('outcome')!='completed':return None
    if frozen[review['id']].get('review_target')!=producer['latest']:return None
    reports=[json.loads(r[0]) for r in rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(review['latest'],))]
    report=next((r['result'] for r in reports if r.get('kind')=='model_review'),{})
    if (report.get('assignment_id')!=review['latest'] or report.get('decision')!='revise'
            or report.get('findings')!=gap['findings'] or report.get('instruction')!=gap['instruction']):return None
    inputs={}
    for f in frozen.values():
        for item in f['inputs']:
            item={k:copy.deepcopy(v) for k,v in item.items() if k not in ('from_task','output')}
            if item['path'] in inputs and inputs[item['path']]['artifact']!=item['artifact']:return None
            inputs[item['path']]=item
    for artifact in baseline['artifacts']:
        blob=Path(artifact['blob'])
        if blob.is_symlink() or hashlib.sha256(blob.read_bytes()).hexdigest()!=artifact['sha256']:return None
    for item in inputs.values():
        artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
        if blob.is_symlink() or artifact['sha256']!=item['sha256'] or hashlib.sha256(blob.read_bytes()).hexdigest()!=item['sha256']:return None
    candidate=rt.output(baseline['run'],producer['id'],ps['outputs'][0]['path'])
    if not candidate or candidate['attempt']!=producer['latest']:return None
    contract=resolve(adapter['admit'])(frozen[producer['id']],Path(candidate['blob']).read_bytes())
    if not contract:return None
    path='revision-base/'+candidate['path']
    # Avoid colliding with the producer's output path in its new workspace.
    inputs={k:v for k,v in inputs.items() if v['artifact']!=candidate['id']}
    inputs[path]=dict(artifact=candidate['id'],path=path,purpose='Exact rejected candidate',authority='Unaccepted evidence; preserve source bytes',media_type=adapter['media_type'])
    feedback=[]
    for a in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(review['latest'],)):
        # Reports are sufficient; large inspection images remain in history.
        if not a['path'].endswith(('.md','.json','.txt')):continue
        feedback.append(dict(artifact=a['id'],path='revision-review/'+a['path'],purpose='Exact independent findings',authority='Review evidence; original scope remains binding',media_type='text/markdown'))
    if not feedback:return None
    implementation={}
    for hook in ('admit','validate','project'):
        module=importlib.import_module(adapter[hook].split(':')[0]);file=Path(module.__file__)
        implementation[module.__name__]=hashlib.sha256(file.read_bytes()).hexdigest()
    return dict(kind='saved_evidence',producer=producer['id'],reviewer=review['id'],attempt=producer['latest'],
        adapter=adapter,implementation=implementation,contract=contract,inputs=list(inputs.values()),feedback=feedback,
        candidate=dict(artifact=candidate['id'],path=path,sha256=candidate['sha256']),instruction=gap['instruction'])


def graph(baseline,receipt,evidence):
    from .completion_recovery import DELIVERY_POLICY as policy
    plan=copy.deepcopy(baseline['plan'])
    plan['id']='evidence-revision-'+c.digest(dict(parent=baseline['run'],cycle=receipt['cycle'],proof=evidence))[:24]
    tasks={t['id']:t for t in plan['tasks']};author=tasks[evidence['producer']];review=tasks[evidence['reviewer']]
    from orchestrator.deliverable_outputs import review_criteria
    criteria=list(dict.fromkeys(review_criteria(author)+review['criteria']))
    author['criteria']=criteria;review['criteria']=copy.deepcopy(criteria)
    author.pop('execution',None);author['dependencies']=[]
    author['inputs']=copy.deepcopy(evidence['inputs']+evidence['feedback'])
    for key in ('worker','backend','tools'):
        if key in review:author[key]=copy.deepcopy(review[key])
        else:author.pop(key,None)
    author.pop('output_contracts',None)
    author['role']='Local saved-evidence correction'
    # The helper is frozen by Runtime, using only the registered projection hook.
    helper_command=shlex.join([sys.executable,'-B','.relay/revise-evidence.py','rejections.json',author['outputs'][0]['path']])
    author['instruction']=evidence['adapter']['instruction']+'\nWrite only the bounded rejection decisions to rejections.json, then run '+helper_command+'. The helper constructs the versioned artifact and preserves valid bytes. Do not edit the ZIP manually. No external requests or source collection are authorized.\n'+evidence['instruction']
    if 'locked_rejections' in evidence['contract']:
        author['instruction']+='\nThis is a deterministic format repair. Use exactly these already recorded rejection decisions, without changes: '+c.encoded(evidence['contract']['locked_rejections'])
    review['inputs']=unique_inputs(review['inputs']+copy.deepcopy(evidence['feedback']))
    review['instruction']+='\nReview the corrected candidate against the exact previous report and original evidence. Check that rejected entries are now honestly missing, all usable source bytes remain intact, and only review-supported exclusions were made. Preserve advisory qualifications. Missing target coverage does not require new discovery. Never infer acceptance from the previous review.'
    for task in plan['tasks']:
        task.pop('revision',None);task.pop('review_correction',None);task['max_attempts']=1
        # New local projection/review work, not a reset of the transport attempt.
        task['limits'].update(seconds=policy['seconds'],tool_calls=policy['tool_calls'])
        if 'provider_requests' in task['limits']:task['limits']['provider_requests']=policy['tool_calls']
    plan['origin']={**plan.get('origin',{}),'registered_revision':dict(parent=baseline['run'],cycle=receipt['cycle'],baseline_sha256=hashlib.sha256(receipt['baseline'].encode()).hexdigest(),proof=evidence)}
    return c.plan(plan)


def stage_helper(plan,frozen,relay):
    evidence=plan.get('origin',{}).get('registered_revision',{}).get('proof',{})
    if evidence.get('kind')!='saved_evidence' or frozen['id']!=evidence['producer']:return
    hook=evidence['adapter']['project'];module,name=hook.split(':')
    root=str(Path(__file__).resolve().parent.parent)
    source=('import sys,json\nfrom pathlib import Path\n'
        +'sys.path.insert(0,'+repr(root)+')\n'
        +'from '+module+' import '+name+'\n'
        +'raw=Path('+repr(evidence['candidate']['path'])+').read_bytes()\n'
        +'decisions=json.loads(Path(sys.argv[1]).read_text())\n'
        +('assert decisions=='+repr(evidence['contract']['locked_rejections'])+', "Recorded rejection decisions changed"\n' if 'locked_rejections' in evidence['contract'] else '')
        +'output=Path(sys.argv[2]); output.parent.mkdir(parents=True,exist_ok=True)\n'
        +'output.write_bytes('+name+'(raw,decisions))\n')
    path=relay/'revise-evidence.py';path.write_text(source);path.chmod(0o400)


def unique_inputs(inputs):
    result={}
    for item in inputs:
        if item['path'] in result and result[item['path']]!=item:
            raise ValueError('Revision feedback input collision')
        result[item['path']]=item
    return list(result.values())


def repair_proof(rt,baseline):
    """Use a registered pure format repair after review of a saved projection.

    Old code need not be available, but its committed graph, allocation,
    source versions, completed attempts and independently rejected candidate do.
    The adapter must prove the candidate was exactly its old transformation.
    """
    from .registered_revision import validate_recorded_intent
    from orchestrator.execution import REGISTRY
    plan=baseline['plan'];prior=plan['origin']['registered_revision']['proof']
    if len(baseline['gaps'])!=1 or len(baseline['tasks'])!=2:return None
    gap=baseline['gaps'][0]
    if (gap.get('kind')!='review_gaps' or gap.get('reported_decision')!='revise'
            or not gap.get('instruction') or not any(f['category']=='integrity' for f in gap['findings'])
            or any(f['category'] not in ('integrity','advisory') for f in gap['findings'])):return None
    if [dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(baseline['run'],))]!=baseline['tasks']:return None
    receipt,original=validate_recorded_intent(rt,plan)
    original_task=next((t for t in original['plan']['tasks'] if t['id']==prior['producer']),{})
    cap=original_task.get('execution',{}).get('capability')
    adapter=REGISTRY.get(cap,{}).get('evidence_revision',{})
    if not adapter.get('repair'):return None
    producer=rt.task(baseline['run'],prior['producer']);review=rt.task(baseline['run'],gap['task'])
    if (producer['status']!='awaiting_review' or review['status']!='blocked'
            or rt.spec(review).get('review_of')!=producer['id'] or review['id']!=prior['reviewer']):return None
    frozen={}
    for task in (producer,review):
        attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
        if not attempt:return None
        r=json.loads(attempt['receipt'] or '{}');f=json.loads(attempt['frozen']);frozen[task['id']]=f
        if (attempt['state'] not in ('completed','blocked') or r.get('status')!='finished' or r.get('exit_code')!=0
                or r.get('pending_requests') or r.get('cleanup_error') or f.get('execution')
                or any(f.get(k) for k in ('browser','computer','user_gate'))):return None
        for item in f['inputs']:
            artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
            if blob.is_symlink() or artifact['sha256']!=item['sha256'] or hashlib.sha256(blob.read_bytes()).hexdigest()!=item['sha256']:return None
    if frozen[review['id']].get('review_target')!=producer['latest']:return None
    reports=[json.loads(r[0]) for r in rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC",(review['latest'],))]
    report=next((r['result'] for r in reports if r.get('kind')=='model_review'),{})
    if (report.get('assignment_id')!=review['latest'] or report.get('decision')!='revise'
            or report.get('findings')!=gap['findings'] or report.get('instruction')!=gap['instruction']):return None
    for artifact in baseline['artifacts']:
        blob=Path(artifact['blob'])
        if blob.is_symlink() or hashlib.sha256(blob.read_bytes()).hexdigest()!=artifact['sha256']:return None
    original_source=prior['candidate'];source=rt.artifact(original_source['artifact'])
    if (source['sha256']!=original_source['sha256'] or not any(i['artifact']==source['id'] and i['sha256']==source['sha256'] for i in frozen[producer['id']]['inputs'])):return None
    candidate=rt.output(baseline['run'],producer['id'],rt.spec(producer)['outputs'][0]['path'])
    if not candidate or candidate['attempt']!=producer['latest']:return None
    contract=resolve(adapter['repair'])(Path(source['blob']).read_bytes(),Path(candidate['blob']).read_bytes(),prior['contract'])
    if not contract:return None
    feedback=copy.deepcopy(prior['feedback'])
    for a in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(review['latest'],)):
        if a['path'].endswith(('.md','.json','.txt')):
            feedback.append(dict(artifact=a['id'],path='revision-review/'+review['latest']+'/'+a['path'],purpose='Exact format-repair findings',authority='Independent review; preserve current exclusions',media_type='text/markdown'))
    result=copy.deepcopy(prior)
    result.update(attempt=producer['latest'],adapter=adapter,contract=contract,feedback=unique_inputs(feedback),instruction=gap['instruction'],
        repair_candidate=dict(artifact=candidate['id'],sha256=candidate['sha256']),
        implementation={})
    for hook in ('admit','validate','project','repair'):
        module=importlib.import_module(adapter[hook].split(':')[0])
        result['implementation'][module.__name__]=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return result
