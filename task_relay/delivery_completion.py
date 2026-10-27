"""Explicit final-artifact contracts over the existing atomic workflow queue.

The ledger describes delivery slots, not inferred product facts or user acceptance.
Historical workflows without this contract retain their original policy.
"""
import json


def schema():
    from .planning_contract import obj
    reference=obj({'stage': {'type': 'string'}, 'output': {'type': 'string'}}, ('stage','output'))
    return obj({'version': {'type': 'integer', 'enum': [1]},
                'stage': {'type': 'string'}, 'output': {'type': 'string'},
                'photos': obj({'stage':{'type':'string'},'output':{'type':'string'},
                               'count_policy':{'type':'string','enum':['required','target']}},
                              ('stage','output','count_policy')),
                'coverage': obj({'inventory': reference, 'catalog': reference,
                                 'options_per_item': {'type':'integer','minimum':1,'maximum':10},
                                 'count_policy': {'type':'string','enum':['required','target']}},
                                ('inventory','catalog','options_per_item'))},
               ('version', 'stage', 'output'))


INSTRUCTIONS = '''For an authorized request to deliver a finished file without
intermediate choices, declare completion:{version:1,stage:final_production_stage,
output:final_deliverable_id}. The selected final stage must be the last stage,
have a typed artifact output and independent final-artifact review. Keep all
intermediate gates none. Do not add this mode when the user asks for planning
only or an intermediate choice. The original request remains the delivery goal;
an intermediate report does not complete it. Missing requirements must be repaired,
never relabeled as advisories. Optional disclosed differences may be advisory.
The contract authorizes bounded existing research recovery at each stage, not
unknown host code, purchases, expanded provider grants or replay of uncertain work.
For image sourcing include coverage:{inventory:{stage,output},catalog:{stage,output},
options_per_item:the_requested_count}. Both references select earlier reviewed JSON
production outputs. Inventory is {items:[{id,...}]}; catalog is
{items:[{id,options:[{product_url,...},...]}]}. Preserve every inventory ID and the
requested alternative count when count_policy is required (the historical default).
When the human permits best-available delivery, set count_policy:target. The count
is then a target: retain all valid options, including extras, and disclose shortfalls
and unresolved items without a count-based recovery gate. Never invent facts to
fill slots. Record identity, evidence, photos and actual inventory coverage still
require review. Different colors of one product are not substitutes
for distinct alternatives. Exact facts and photo correspondence still need review.
The final stage must explicitly consume both selected JSON versions as context.
When the human permits photo placeholders, declare photos:{stage:photo_stage,
output:photo_zip_output,count_policy:target}. This preserves exact catalog subject
identities and recorded failures without a missing-photo recovery gate. Omission
retains required coverage; this policy never permits wrong photos or acceptance
without independent review.
'''


def validate(action):
    policy = action.get('completion')
    if policy is None:
        return
    if (not isinstance(policy, dict) or set(policy)-{'coverage','photos'} != {'version', 'stage', 'output'}
            or type(policy['version']) is not int or policy['version'] != 1):
        raise ValueError('Invalid final delivery contract.')
    stages = action['stages']
    if any(s['gate'] != 'none' for s in stages):
        raise ValueError('Final delivery mode cannot silently bypass explicit choice gates.')
    final = stages[-1]
    output = final.get('handoff', {}).get('outputs', {}).get(policy['output'])
    if (policy['stage'] != final['id'] or final['route'] != 'production'
            or not output or policy['output'] not in final['deliverables']):
        raise ValueError('Final delivery must name a typed output of the last production stage.')
    coverage=policy.get('coverage')
    if coverage is not None:
        if (not isinstance(coverage,dict) or set(coverage)-{'count_policy'}!={'inventory','catalog','options_per_item'}
                or coverage.get('count_policy','required') not in ('required','target')
                or type(coverage['options_per_item']) is not int or not 1<=coverage['options_per_item']<=10):
            raise ValueError('Invalid sourcing coverage contract.')
        positions=[]
        for key in ('inventory','catalog'):
            ref=coverage[key]
            if not isinstance(ref,dict) or set(ref)!={'stage','output'}:
                raise ValueError('Coverage requires exact inventory/catalog output references.')
            stage=next((s for s in stages[:-1] if s['id']==ref['stage']),None)
            if (not stage or stage['route']!='production'
                    or stage.get('handoff',{}).get('outputs',{}).get(ref['output'],{}).get('media_type')!='application/json'
                    or not any(e['stage']==ref['stage'] and e['deliverable']==ref['output'] and e['consumer']=='context'
                               for e in final['handoff']['inputs'])):
                raise ValueError('Coverage must bind earlier JSON production outputs to final-stage context.')
            positions.append(stages.index(stage))
        if positions[0]>=positions[1]:
            raise ValueError('Catalog coverage must follow its inventory.')
    photos=policy.get('photos')
    if photos is not None:
        if (not isinstance(photos,dict) or set(photos)!={'stage','output','count_policy'}
                or photos['count_policy'] not in ('required','target')):
            raise ValueError('Invalid photo coverage contract.')
        stage=next((s for s in stages[:-1] if s['id']==photos['stage']),None)
        if (not stage or stage['route']!='production' or not set(stage.get('capabilities',[]))&{'images.fetch','images.products'}
                or stage.get('handoff',{}).get('outputs',{}).get(photos['output'],{}).get('media_type')!='application/zip'
                or not any(e['stage']==photos['stage'] and e['deliverable']==photos['output'] for e in final['handoff']['inputs'])):
            raise ValueError('Photo coverage must bind an earlier photo ZIP to the final stage.')


def coverage_slots(inventory,catalog,alternatives,count_policy='required'):
    """Deterministic coverage only; semantic evidence remains independently reviewed."""
    if count_policy not in ('required','target'):raise ValueError('Unknown count policy.')
    sealed_empty=isinstance(inventory,dict) and inventory.get('contract')=={'id':'sourcing.inventory','version':1} and inventory.get('complete') is True and inventory.get('items')==[]
    if sealed_empty:
        from orchestrator.sourcing_inventory import validate_document
        validate_document(inventory)
    if (not isinstance(inventory,dict) or not isinstance(catalog,dict)
            or not isinstance(inventory.get('items'),list) or not isinstance(catalog.get('items'),list)
            or not (0 if sealed_empty else 1)<=len(inventory['items'])<=100):
        raise ValueError('Coverage requires bounded inventory and catalog item arrays.')
    ids=[i.get('id') if isinstance(i,dict) else None for i in inventory['items']]
    actual=[i.get('id') if isinstance(i,dict) else None for i in catalog['items']]
    if any(not isinstance(i,str) or not i.strip() for i in ids+actual) or len(set(ids))!=len(ids) or len(set(actual))!=len(actual):
        raise ValueError('Inventory/catalog item identities must be unique and nonempty.')
    if set(actual)-set(ids):
        raise ValueError('Catalog contains items outside the declared inventory.')
    entries={i['id']:i for i in catalog['items']}
    slots=[];missing=[]
    from urllib.parse import urlsplit
    for ident in ids:
        options=entries.get(ident,{}).get('options',[])
        if not isinstance(options,list) or len(options)>(alternatives if count_policy=='required' else 100):
            raise ValueError('Catalog alternative count exceeds its exact requested coverage.')
        urls=[]
        for index,option in enumerate(options):
            url=option.get('product_url') if isinstance(option,dict) else None
            parsed=urlsplit(url) if isinstance(url,str) else None
            if not parsed or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Catalog options require public HTTPS product URLs.')
            # Fragment/query variations cannot pad coverage of the same product page.
            identity=(parsed.hostname.lower(),parsed.path.rstrip('/'))
            if identity in urls:
                raise ValueError('Repeated product pages cannot count as distinct alternatives.')
            urls.append(identity)
            slots.append(dict(item=ident,option=index+1,product_url=url))
        missing.extend(dict(item=ident,option=index+1) for index in range(len(options),alternatives))
    return dict(required_items=len(ids),options_per_item=alternatives,count_policy=count_policy,slots=slots,
                missing=missing if count_policy=='required' else [],shortfall=missing,
                unresolved_items=[ident for ident in ids if not entries.get(ident,{}).get('options')],
                semantic_evidence='Independent review required; slot presence does not verify facts or photographs.')


def coverage(state,pipeline):
    policy=json.loads(pipeline['spec']).get('completion',{}).get('coverage')
    if not policy:
        return None
    from .pipelines import artifact_source
    from pathlib import Path
    documents=[]
    for key in ('inventory','catalog'):
        ref=policy[key]
        step=state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',
                              (pipeline['id'],ref['stage'])).fetchone()
        if not step or step['status']!='completed':
            return dict(pending=key,missing=None)
        result=json.loads(step['result'] or '{}')
        source=result.get('deliverables',{}).get(ref['output'])
        if not source or source['bytes']>5000000 or artifact_source(state,source['artifact'])!=source:
            raise ValueError('Coverage input lacks an unchanged bounded artifact.')
        documents.append(json.loads(Path(source['path']).read_text()))
    return coverage_slots(*documents,policy['options_per_item'],policy.get('count_policy','required'))


def record_catalog_gap(state,pipeline,step,run,bindings):
    """A deterministic missing-slot result seeds recovery, never draft acceptance."""
    policy=json.loads(pipeline['spec']).get('completion',{}).get('coverage')
    if not policy or policy['catalog']['stage']!=step['id']:
        return False
    from .pipelines import artifact_source
    from .production_control import root
    from orchestrator.runtime import Runtime
    from pathlib import Path
    rt=Runtime(root(state),connection=state.db)
    inventory_step=state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',
                                    (pipeline['id'],policy['inventory']['stage'])).fetchone()
    if not inventory_step or inventory_step['status']!='completed':
        raise ValueError('Catalog completion requires its completed inventory.')
    inventory=json.loads(inventory_step['result'])['deliverables'][policy['inventory']['output']]
    catalog=bindings[policy['catalog']['output']]
    for source in (inventory,catalog):
        if source['bytes']>5000000 or artifact_source(state,source['artifact'])!=source:
            raise ValueError('Coverage recovery input is not an unchanged bounded artifact.')
    result=coverage_slots(json.loads(Path(inventory['path']).read_text()),
                          json.loads(Path(catalog['path']).read_text()),policy['options_per_item'],policy.get('count_policy','required'))
    if not result['missing']:
        return False
    detail=dict(pipeline=pipeline['id'],step=step['id'],inventory=inventory,catalog=catalog,
                options_per_item=policy['options_per_item'],missing=result['missing'])
    prior=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='delivery_coverage_gap' ORDER BY id DESC LIMIT 1",(run,)).fetchone()
    if not prior or json.loads(prior[0])!=detail:
        rt.event(run,None,None,'delivery_coverage_gap',detail)
    return True


def record_photo_gap(state,pipeline,step,run,bindings):
    """Preserve photo gaps; only explicitly required coverage seeds recovery."""
    action=json.loads(pipeline['spec'])
    stage=action['stages'][step['position']]
    policy=action['completion'].get('photos') if action.get('completion') else None
    if not action.get('completion') or not set(stage['capabilities'])&{'images.fetch','images.products'}:return False
    from .pipelines import artifact_source
    from .production_control import root
    from orchestrator.runtime import Runtime
    from orchestrator.image_sources import unpack
    from pathlib import Path
    missing=False
    for output,source in bindings.items():
        if stage['handoff']['outputs'][output]['media_type']!='application/zip':continue
        if artifact_source(state,source['artifact'])!=source:raise ValueError('Photo coverage source changed.')
        _,_,manifest=unpack(Path(source['path']).read_bytes())
        subjects=[{k:s[k] for k in ('id','label','query')} for s in manifest['subjects']]
        prior=state.db.execute("SELECT e.data FROM completion_recoveries r JOIN production_events e ON e.run=r.parent WHERE r.pipeline=? AND r.step=? AND e.kind='delivery_photo_gap' ORDER BY r.cycle,e.id LIMIT 1",(pipeline['id'],step['id'])).fetchone()
        if prior:
            expected=json.loads(prior[0])
            if expected['output']==output and expected['subjects']!=subjects:
                raise ValueError('Recovered photo bundle dropped or changed original subjects.')
        gaps=[s['id'] for s in manifest['subjects'] if s['status']=='missing']
        if not gaps:continue
        detail=dict(pipeline=pipeline['id'],step=step['id'],output=output,photo=source,subjects=subjects,missing=gaps)
        rt=Runtime(root(state),connection=state.db)
        prior=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='delivery_photo_gap' ORDER BY id DESC LIMIT 1",(run,)).fetchone()
        if not prior or json.loads(prior[0])!=detail:rt.event(run,None,None,'delivery_photo_gap',detail)
        missing=missing or not (policy and policy['stage']==step['id'] and policy['output']==output and policy['count_policy']=='target')
    return missing


def photo_recovery_gap(state,run,rt):
    row=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='delivery_photo_gap' ORDER BY id DESC LIMIT 1",(run,)).fetchone()
    if not row:return None
    detail=json.loads(row[0]);source=detail['photo']
    from .pipelines import artifact_source
    from orchestrator.image_sources import unpack
    from pathlib import Path
    if artifact_source(state,source['artifact'])!=source:return None
    p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(detail['pipeline'],)).fetchone()
    if not p or not json.loads(p['spec']).get('completion'):return None
    policy=json.loads(p['spec'])['completion'].get('photos')
    if policy and policy['stage']==detail['step'] and policy['output']==detail['output'] and policy['count_policy']=='target':return None
    artifact=rt.artifact(source['artifact'])
    plan=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    declared=plan.get('deliverables',{}).get(detail['output'],{})
    if (artifact['run']!=run or artifact['task']!=declared.get('task') or artifact['path']!=declared.get('output')
            or rt.task(run,artifact['task'])['latest']!=artifact['attempt']):return None
    _,_,manifest=unpack(Path(source['path']).read_bytes())
    subjects=[{k:s[k] for k in ('id','label','query')} for s in manifest['subjects']]
    gaps=[s['id'] for s in manifest['subjects'] if s['status']=='missing']
    if subjects!=detail['subjects'] or gaps!=detail['missing'] or not gaps:return None
    return dict(task=artifact['task'],kind='delivery_photos',missing=gaps,base_photo=source,
                instruction='Keep the exact base ZIP and all found bytes. Discover only missing subjects within the original grant; fetch observed sources, merge base first using images.merge, and independently review the complete merged ZIP. No intermediate approval or draft acceptance.')


def recovery_gap(state,run,rt):
    """Revalidate native gap evidence before admitting a read-only successor."""
    from .upstream_recovery import gap as consumer_gap
    upstream=consumer_gap(state,run,rt)
    if upstream:return upstream
    row=state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='delivery_coverage_gap' ORDER BY id DESC LIMIT 1",(run,)).fetchone()
    if not row:
        return photo_recovery_gap(state,run,rt)
    detail=json.loads(row[0])
    p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(detail['pipeline'],)).fetchone()
    if not p:
        return None
    policy=json.loads(p['spec']).get('completion',{}).get('coverage')
    if not policy or policy['catalog']['stage']!=detail['step'] or policy['options_per_item']!=detail['options_per_item']:
        return None
    inventory_step=state.db.execute('SELECT status,result FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],policy['inventory']['stage'])).fetchone()
    if (not inventory_step or inventory_step['status']!='completed'
            or json.loads(inventory_step['result'] or '{}').get('deliverables',{}).get(policy['inventory']['output'])!=detail['inventory']):
        return None
    plan=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    declared=plan.get('deliverables',{}).get(policy['catalog']['output'],{})
    artifact=rt.artifact(detail['catalog']['artifact'])
    if (artifact['run']!=run or artifact['task']!=declared.get('task') or artifact['path']!=declared.get('output')
            or rt.task(run,artifact['task'])['latest']!=artifact['attempt']):
        return None
    from .pipelines import artifact_source
    from pathlib import Path
    for source in (detail['inventory'],detail['catalog']):
        if source['bytes']>5000000 or artifact_source(state,source['artifact'])!=source:
            return None
    result=coverage_slots(json.loads(Path(detail['inventory']['path']).read_text()),
                          json.loads(Path(detail['catalog']['path']).read_text()),policy['options_per_item'],policy.get('count_policy','required'))
    if not result['missing'] or result['missing']!=detail['missing']:
        return None
    return dict(task=artifact['task'],kind='delivery_coverage',missing=result['missing'],
                instruction='Retain supported alternatives and fill only these missing slots using the original authorized sources and independent review. Do not accept the incomplete catalog or replay uncertain operations.')


def activate(state, pipeline):
    """Called only in the trusted initial dispatch/resume transaction."""
    if not state.db.in_transaction:
        raise ValueError('Delivery activation requires an atomic transaction.')
    action = json.loads(pipeline['spec'])
    if not action.get('completion') or pipeline['status'] != 'active':
        return
    validate(action)
    from .completion_recovery import authorize
    authorize(state, pipeline['id'], pipeline['request'])


def ledger(state, pipeline_id):
    pipeline = state.db.execute('SELECT * FROM relay_pipelines WHERE id=?', (pipeline_id,)).fetchone()
    if not pipeline:
        return None
    action = json.loads(pipeline['spec'])
    if not action.get('completion'):
        return None
    slots = []
    for step in state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position', (pipeline_id,)):
        declared = action['stages'][step['position']]
        try:
            result = json.loads(step['result'] or '{}')
        except (ValueError, TypeError):
            result = {}
        bindings = result.get('deliverables', {}) if isinstance(result, dict) else {}
        for output in declared['deliverables']:
            source = bindings.get(output)
            slots.append(dict(stage=step['id'], output=output, status=step['status'],
                              source=source, bound=bool(source), error=step['error']))
    from .workflow_usage import report as usage_report
    return dict(usage={k:v for k,v in usage_report(state,pipeline_id).items() if k!='records'},version=1, goal=pipeline['request'], final=action['completion'], slots=slots,
                coverage=coverage(state,pipeline),
                remaining=[dict(stage=s['stage'], output=s['output'], status=s['status'])
                           for s in slots if s['status'] != 'completed' or not s['bound']])


def check_final(state, pipeline):
    """No complete workflow without the exact final artifact and current review."""
    action = json.loads(pipeline['spec'])
    policy = action.get('completion')
    if not policy:
        return
    validate(action)
    item_coverage=coverage(state,pipeline)
    if item_coverage and (item_coverage.get('pending') or item_coverage['missing']):
        raise ValueError('Final delivery is missing required sourcing coverage.')
    from .pipelines import artifact_source
    from .production_control import root
    from orchestrator.runtime import Runtime
    from orchestrator.handoff_contracts import check_file
    from pathlib import Path
    step = state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',
                            (pipeline['id'], policy['stage'])).fetchone()
    if not step or step['status'] != 'completed':
        raise ValueError('Final artifact stage is not complete.')
    result = json.loads(step['result'] or '{}')
    source = result.get('deliverables', {}).get(policy['output'])
    if not source or artifact_source(state, source['artifact']) != source:
        raise ValueError('Final delivery has no unchanged bound artifact.')
    rt = Runtime(root(state), connection=state.db)
    artifact = rt.artifact(source['artifact'])
    run = result.get('run')
    if artifact['run'] != run or rt.status(run)['status'] != 'completed':
        raise ValueError('Final artifact production is not complete.')
    producer = rt.task(run, artifact['task'])
    if producer['latest'] != artifact['attempt']:
        raise ValueError('Final artifact is a stale producer version.')
    finished=state.db.execute('SELECT state,receipt FROM production_attempts WHERE id=?',(producer['latest'],)).fetchone()
    producer_receipt=json.loads(finished['receipt'] or '{}') if finished else {}
    if (not finished or finished['state']!='completed' or producer_receipt.get('status')!='finished'
            or producer_receipt.get('pending_requests') or producer_receipt.get('browser',{}).get('uncertain_actions')):
        raise ValueError('Final producer has no confirmed finished receipt.')
    valid_review = False
    for reviewer in state.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,)):
        if reviewer['status'] != 'completed' or rt.spec(reviewer).get('review_of') != artifact['task']:
            continue
        attempt = state.db.execute('SELECT * FROM production_attempts WHERE id=?', (reviewer['latest'],)).fetchone()
        frozen, receipt = json.loads(attempt['frozen']), json.loads(attempt['receipt'] or '{}')
        reports = state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC", (attempt['id'],)).fetchall()
        review = next((v['result'] for r in reports if (v := json.loads(r[0])).get('kind') == 'model_review'), None)
        if (attempt['state'] == 'completed' and receipt.get('status') == 'finished'
                and not receipt.get('pending_requests') and not receipt.get('browser', {}).get('uncertain_actions')
                and frozen.get('review_target') == producer['latest']
                and any(i.get('artifact') == source['artifact'] and i.get('sha256') == source['sha256'] for i in frozen['inputs'])
                and review and review.get('decision') == 'accept'):
            valid_review = True
    if not valid_review:
        raise ValueError('Final artifact lacks independent review of the exact current version.')
    check_file(Path(source['path']), action['stages'][-1]['handoff']['outputs'][policy['output']])
