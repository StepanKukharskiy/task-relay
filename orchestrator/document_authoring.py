"""Registered authoring policy; the existing compiler and Runtime own execution.

This metadata is snapshotted only for new owner jobs. It does not alter historical
connector identities or grant new operations. New formats register the same
output-routing contract instead of adding a controller.
"""
import copy
import hashlib
import json
from pathlib import PurePosixPath

PPTX='application/vnd.openxmlformats-officedocument.presentationml.presentation'
REGISTRY={
    PPTX:dict(extensions=['.pptx'],operations=['pptx.create','pptx.edit','images.pptx'],
              preparation='document.layout',renderer='pptx.create'),
    'application/pdf':dict(extensions=['.pdf'],operations=['pptx.render'],
                          preparation=None,renderer='pptx.render'),
}


def capture(operations, custom_code=None):
    value=dict(version=1,formats=copy.deepcopy(REGISTRY),custom_code=copy.deepcopy(custom_code or {}))
    validate(value,operations)
    return value


def validate(policy,operations):
    if (not isinstance(policy,dict) or set(policy)!={'version','formats','custom_code'}
            or policy['version']!=1 or not isinstance(policy['formats'],dict)
            or not isinstance(policy['custom_code'],dict)):
        raise ValueError('Invalid frozen authoring policy')
    # Older captures keep their original routes; a newly registered renderer
    # does not silently add itself to an existing job's authorization.
    if any(media not in REGISTRY or not isinstance(spec,dict)
           or {k:v for k,v in spec.items() if k!='operations'}!={k:v for k,v in REGISTRY[media].items() if k!='operations'}
           or not isinstance(spec.get('operations'),list) or not set(spec['operations'])<=set(REGISTRY[media]['operations'])
           for media,spec in policy['formats'].items()):
        raise ValueError('Registered authoring routes differ from the frozen grant')
    for media,reason in policy['custom_code'].items():
        if media not in policy['formats'] or not isinstance(reason,str) or not 1<=len(reason.strip())<=1000:
            raise ValueError('Custom authoring requires an explicit format-scoped authorization reason')


def check(task,policy,operations):
    """Reject bypass before admission; no model prose can expand the grant."""
    if policy is None:
        if task.get('authoring_fallback'):raise ValueError('Historical job has no explicit authoring fallback policy')
        return
    validate(policy,operations)
    matched=set()
    for output in task.get('outputs',[]):
        suffix=PurePosixPath(output['path']).suffix.lower()
        for media,spec in policy['formats'].items():
            if output.get('media_type')!=media and suffix not in spec['extensions']:continue
            if output.get('media_type')!=media:raise ValueError('Registered document extension and media type disagree')
            matched.add(media)
            capability=task.get('execution',{}).get('capability')
            if task.get('work_tools'):
                from .worker_tools import validate_assignment
                validate_assignment(task)
                for step in task['work_tools']['steps'].values():
                    if output['path'] in {o['path'] for o in step['outputs'].values()}:capability=step['operation']
            if capability in spec['operations'] and capability in operations:continue
            fallback=task.get('authoring_fallback')
            if (not task.get('execution') and media in policy['custom_code'] and isinstance(fallback,dict)
                    and set(fallback)=={'reason'} and isinstance(fallback['reason'],str)
                    and 1<=len(fallback['reason'].strip())<=1000):continue
            available=sorted(set(spec['operations'])&set(operations))
            raise ValueError(('Use registered document operations '+', '.join(available) if available else
                'No registered document renderer is granted for '+media)+
                '; select content/layouts with document.layout. Custom code requires an explicit frozen fallback authorization.')
    if task.get('authoring_fallback') and (not matched or task.get('execution')
            or not matched<=set(policy['custom_code'])):
        raise ValueError('Authoring fallback must name an authorized custom document assignment')


def instructions(policy):
    if policy is None:return ''
    return ('\nSupported document outputs must use the registered operations in authoring_policy. '
        'For compatible saved collections, prefer collection.slides followed by document.compose when granted; '
        'document.compose combines saved sections and full-page previews without retyping evidence. '
        'After a presentation review, use work:{operation:pptx.create,mode:revise,baseline:<exact saved composition>} '
        'with the original image assets and review evidence. Registered document.layout starts with saved pages '
        'at revision zero; amend only affected pages, then build and inspect. Do not send expanded JSON through '
        'an ordinary worker: that loses its registered preparation contract. '
        'For new editorial content, delegate a declared-file worker with records family document.layout: '
        'one bounded layout/content fragment at a time, no Python or coordinates. Pass its JSON and exact '
        'image assets to pptx.create, then pptx.render and independent visual review. '
        'Use collection.slides for compatible typed collections only when granted. '
        'Do not ask a document worker to repeat research, invent missing facts or replace product photos with room crops. '
        'Custom code is permitted only for format-scoped exceptions already present in custom_code and requires '
        'authoring_fallback:{reason:string} on that assignment. No exception can be created by a model. '
        'If an operation is unavailable, retain data and explain the missing capability.')


def check_inputs(batch,session):
    """Bind renderer preparation to code-owned content or an exact saved spec."""
    from . import operation_contracts,execution
    policy=session.grant.get('authoring_policy')
    by_id={t['id']:t for t in batch}
    for task in batch:
        contract=task.get('operation_contract',{})
        if contract.get('id')=='document.layout' and contract['parameters']['renderer'] not in session.grant['operations']:
            raise ValueError('Layout renderer is outside this job grant')
        if policy is None:continue
        if task.get('work_tools',{}).get('intent',{}).get('mode')=='revise':
            from .worker_tools import native_assignment
            task=native_assignment(task)
        capability=task.get('execution',{}).get('capability')
        routes=[s for s in policy['formats'].values() if s['renderer']==capability and s['preparation']]
        if not routes:continue
        family=routes[0]['preparation'];inputs=[i for i in task['inputs'] if i.get('media_type')=='application/json']
        if len(inputs)!=1:raise ValueError('Registered renderer needs one prepared content JSON')
        item=inputs[0]
        if 'artifact' in item:
            artifact,raw=session.artifact(item['artifact'])
            # User-supplied or prior-version layout data is usable after the same
            # structural check. This does not upgrade unverified source facts.
            try:operation_contracts.validate_document(raw,dict(id=family,version=1));continue
            except ValueError:
                if artifact['run']!=session.run or not artifact['task']:raise
                attempt=session.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
                if not attempt or attempt['state'] not in ('completed','blocked'):
                    raise ValueError('Prepared content requires confirmed collected production, never active or uncertain work')
                producer=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
                if (receipt.get('status')!='finished' or receipt.get('pending_requests')!=[]
                        or receipt.get('external_outcome')!='no_pending_response' or receipt.get('exit_code')!=0
                        or receipt.get('reason') or receipt.get('cleanup_error')):
                    raise ValueError('Prepared content has unresolved production effects')
                from .adapters import unresolved_operations
                if unresolved_operations(json.loads(attempt['session'])['control']):
                    raise ValueError('Prepared content has unresolved operation intents')
                prepared=producer.get('operation_contract',{})
                if prepared.get('id')==family and prepared.get('output')==artifact['path']:
                    from .operation_records import Store
                    from .runtime import safe_file
                    store=Store(producer,session.rt.db)
                    for source in producer['inputs']:
                        if hashlib.sha256(safe_file(producer['workspace'],source['path']).read_bytes()).hexdigest()!=source['sha256']:
                            raise ValueError('Prepared content source changed')
                    with store.connection(write=False) as db:_,records=store._state(db)
                    if not store.lifecycle.complete(store,records) or store.projections(records).get(artifact['path'])!=raw:
                        raise ValueError('Prepared content differs from its exact committed records')
                    rows=session.rt.db.execute('SELECT id FROM production_artifacts WHERE attempt=? AND path=?',(artifact['attempt'],artifact['path'])).fetchall()
                    if len(rows)!=1 or rows[0]['id']!=artifact['id']:raise ValueError('Ambiguous prepared content export')
                    continue
        else:
            producer=by_id.get(item['from_task']) or session.rt.spec(session.rt.task(session.run,item['from_task']))
            prepared=producer.get('operation_contract',{})
            if prepared.get('id')==family and prepared.get('output')==item['output']:continue
        # Existing registered data projections also own their geometry. Merely
        # naming a JSON output on a Python worker is not a compatible contract.
        upstream=producer.get('execution',{}).get('capability')
        if (upstream not in session.grant['operations'] or
                execution.REGISTRY[capability].get('companions',{}).get(upstream)!='registered-record-projection'):
            raise ValueError('Prepare renderer input with '+family+' or its granted registered record projection; arbitrary worker JSON is not layout content')
