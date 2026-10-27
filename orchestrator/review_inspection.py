"""Compile registered read-only evidence before dispatching independent reviews.

No model/tool-specific branching, host dispatch, inferred acceptance or new grant.
The same exact input identity shares one inspection across reviewers.
"""
import copy,hashlib,json
from . import execution
from .handoff_closure import resolved_key,add_evidence


def collected_standalone(rt,run,target,operation):
    """Evidence completion is independent of the inspection task's review state."""
    if target[0]!='artifact':return None
    from .runtime_outcomes import Hold
    from .execution_evidence import capsule
    from pathlib import Path
    rows=[]
    for row in rt.db.execute('SELECT * FROM production_attempts WHERE run=?',(run,)):
        frozen=json.loads(row['frozen'])
        if frozen.get('execution',{}).get('capability')!=operation:continue
        if any(i.get('artifact')==target[1] for i in frozen['inputs']):rows.append((row,frozen))
    if not rows:return None
    if len(rows)!=1:raise Hold('review_inspection_failed','Multiple exact inspection attempts require explicit reconciliation; no replay')
    row,frozen=rows[0];receipt=json.loads(row['receipt'] or '{}')
    if row['state'] in ('running','launching','queued'):return None
    if row['state']!='completed' or receipt.get('status')!='finished' or receipt.get('pending_requests'):
        raise Hold('review_inspection_failed','Exact inspection lacks conclusive collection; no replay')
    try:
        proof=capsule(frozen,json.loads(row['session'])['control'])
        saved=proof['receipts']['operation-materialized.json']['value']['outputs'];outputs=[]
        for output in frozen['outputs']:
            candidates=rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? AND path=?',(row['id'],output['path'])).fetchall()
            if len(candidates)!=1:raise ValueError('Inspection output missing or ambiguous')
            a=candidates[0];raw=Path(a['blob']).read_bytes()
            if saved[output['path']]!={'sha256':a['sha256'],'bytes':a['bytes']} or len(raw)!=a['bytes'] or hashlib.sha256(raw).hexdigest()!=a['sha256']:raise ValueError('Inspection output changed')
            outputs.append(dict(output,artifact=a['id']))
        return dict(id=frozen['id'],attempt=row['id'],outputs=outputs)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise Hold('review_inspection_failed','Exact collected inspection evidence invalid; no replay: '+str(exc)) from exc


def collected_inline(rt,run,artifact,operation):
    """Resolve historical inspection by producing attempt, never task/latest.

    Collection and the registered receipt establish evidence identity. Semantic
    acceptance is deliberately not a prerequisite for reading rejected work.
    """
    from .runtime_outcomes import Hold
    from .worker_tools import inspection_evidence
    attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
    if not attempt:return None
    frozen=json.loads(attempt['frozen'])
    if frozen.get('work_tools',{}).get('steps',{}).get('inspect',{}).get('operation')!=operation:return None
    if attempt['run']!=run:
        raise Hold('review_inspection_failed','Inspection reuse requires an exact same-run producing attempt')
    receipt=json.loads(attempt['receipt'] or '{}')
    if attempt['state']!='completed' or receipt.get('status')!='finished' or receipt.get('pending_requests'):
        raise Hold('review_inspection_failed','Inspection producer has no collected conclusive completion; do not replay it')
    proof=inspection_evidence(rt,attempt,operation)
    if not proof or (proof['candidate_path'],proof['candidate_sha256'])!=(artifact['path'],artifact['sha256']):
        raise Hold('review_inspection_failed','Saved inspection does not bind this exact candidate')
    outputs=[]
    for output in frozen['work_tools']['steps']['inspect']['outputs'].values():
        rows=rt.db.execute('SELECT id FROM production_artifacts WHERE attempt=? AND path=?',(artifact['attempt'],output['path'])).fetchall()
        if len(rows)!=1:raise Hold('review_inspection_failed','Exact collected inspection output is missing or ambiguous')
        saved=rt.artifact(rows[0]['id']);detail=proof['outputs'].get(output['path'],{})
        if saved['sha256']!=detail.get('sha256') or saved['bytes']!=detail.get('bytes'):
            raise Hold('review_inspection_failed','Collected inspection differs from its committed receipt')
        outputs.append(dict(output,artifact=saved['id']))
    return dict(id=frozen['id'],attempt=artifact['attempt'],outputs=outputs)


def bind(tasks,grant,rt,run):
    if grant.get('review_inspection_version')!=1:return []
    from .owner_intents import native_outputs
    from .runtime_outcomes import Hold
    existing=[rt.spec(r) for r in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,))]
    def identity(item):
        return resolved_key(item,rt,run,{t['id'] for t in tasks})
    receipts=[]
    for review in list(tasks):
        if not review.get('review_of'):continue
        for item in list(review['inputs']):
            media=item.get('media_type')
            # Only representations registered as requiring a reader. Text and
            # raster pixels are already directly inspectable by review tools.
            readers=[cap for cap,spec in execution.REGISTRY.items() if spec.get('review_evidence') and media in spec['input_types'] and media not in execution.TEXT_TYPES]
            if not readers:continue
            structured=[cap for cap in readers if set(execution.REGISTRY[cap].get('outputs',{}).values())<={'application/json',*execution.TEXT_TYPES}]
            if structured:readers=structured
            choices=[cap for cap in readers if cap in grant['operations'] and not execution.parameter_schema(cap).get('required')]
            if len(choices)!=1:raise Hold('review_inspection_unavailable','Exact candidate review needs one authorized parameter-free registered inspection for '+str(media))
            cap=choices[0];target=identity(item)
            producer_id=item.get('from_task')
            candidate_path=item.get('output')
            collected=None
            if 'artifact' in item:
                artifact=rt.artifact(item['artifact']);producer_id=artifact['task'];candidate_path=artifact['path']
                if artifact['attempt']:collected=collected_inline(rt,run,artifact,cap)
            if not collected:collected=collected_standalone(rt,run,target,cap)
            producer=next((t for t in [*tasks,*existing] if t['id']==producer_id),None)
            if 'artifact' in item:
                row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
                producer=json.loads(row['frozen']) if row else None
            steps=producer.get('work_tools',{}).get('steps',{}) if producer else {}
            inline=steps.get('inspect',{})
            if collected:inspect=collected
            elif inline.get('operation')==cap and any(o['path']==candidate_path for o in steps.get('build',{}).get('outputs',{}).values()):
                inspect=dict(id=producer_id,outputs=list(inline['outputs'].values()))
            else:inspect=None
            matches=[t for t in [*existing,*tasks] if t.get('execution',{}).get('capability')==cap and any(identity(i)==target for i in t.get('inputs',[]))]
            if inspect:pass
            elif matches:
                inspect=matches[0]
                if inspect in existing:
                    state=rt.task(run,inspect['id'])['status']
                    if state not in ('queued','launching','running','completed'):raise Hold('review_inspection_failed','Existing exact inspection is not reusable; retain its outcome without duplicate dispatch')
            else:
                tag=hashlib.sha256(json.dumps([cap,target]).encode()).hexdigest()[:20]
                inspect=dict(id='inspection_'+tag,objective='Inspect exact candidate through its registered reader before independent review',
                    instruction='Read-only inspection. Preserve exact candidate identity; do not author or accept artifacts.',
                    execution=dict(capability=cap,version=execution.REGISTRY[cap]['version'],parameters={}),
                    inputs=[copy.deepcopy(item)],outputs=native_outputs(cap),dependencies=[item['from_task']] if 'from_task' in item else [])
                tasks.append(inspect)
            bindings=[]
            for output in inspect['outputs']:
                source=dict(artifact=output['artifact']) if collected else dict(from_task=inspect['id'],output=output['path'])
                ref=dict(**source,path='inspection/'+inspect['id']+'/'+output['path'].split('/')[-1],
                    media_type=output['media_type'],purpose='Exact registered inspection evidence',authority='Inspection evidence only, not semantic acceptance')
                selected=add_evidence(review,ref,identity)
                bindings.append(dict(output=output['path'],path=selected['path'],identity=list(identity(selected))))
            if not collected and inspect['id'] not in review['dependencies']:review['dependencies'].append(inspect['id'])
            review['instruction']+='\nRegistered inspection evidence is supplied for the exact candidate. Assess its readable representation and provenance; do not invent binary decoders. Missing inspection coverage is a specific evidence gap, not permission to rebuild the candidate.'
            receipts.append(dict(review=review['id'],inspection=inspect['id'],candidate=list(target),operation=cap,bindings=bindings,
                collected_attempt=collected['attempt'] if collected else None))
    return receipts
