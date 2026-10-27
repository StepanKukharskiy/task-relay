"""Owner policy 3 composes existing registry/compiler interfaces, never dispatches.

Required companions and partitions consume the original job slots and worker
ceilings. Saved evidence is inspected, never converted or accepted by discovery.
"""
import copy
import hashlib
import json
from . import execution, operation_contracts, executors


def request_ceiling(grant):
    return min(grant['task_limits']['tool_calls'],grant['task_limits']['provider_requests'],executors.MAX_EXPLICIT_ROUNDS)


def label(ident,kind):
    return (ident[:40]+'_'+kind+'_'+hashlib.sha256((ident+':'+kind).encode()).hexdigest()[:8])


def reviewer(producer,grant):
    from .deliverable_outputs import review_criteria
    ident=label(producer['id'],'review')
    from .handoff_closure import review_inputs
    inputs=review_inputs(producer)
    result=dict(id=ident,objective='Independently review '+producer['objective'],
        instruction='Inspect the exact candidate and its source evidence. Resolve recorded findings against this version; reject unsupported claims and unusable output.',
        role='reviewer',review_of=producer['id'],inputs=inputs,
        outputs=[dict(path='outputs/review.md',purpose='Independent candidate review',media_type='text/markdown')],
        dependencies=list(dict.fromkeys(producer['dependencies']+[producer['id']])),
        criteria=review_criteria(producer),worker=dict(requires=['files.text']),
        limits=copy.deepcopy(grant['task_limits']),max_attempts=grant['task_attempts'])
    from .owner_intents import worker_requirements
    result['worker']['requires']=worker_requirements(result)
    return result


def append(tasks,value):
    if value['id'] in {t['id'] for t in tasks}:raise ValueError('Compiler companion task ID conflicts with proposed work')
    tasks.append(value)


def final_companions(tasks,grant):
    """Attach final inspection to the terminal visual representation, not upstream.

    A review on the deck itself would block its render dependency. A registered
    render is therefore produced first; its reviewer receives exact ancestors
    through the existing handoff closure and can cover both final artifacts.
    """
    from .owner_intents import native_outputs
    from .job_owner import VISUAL_DOCUMENTS
    wanted=set(grant['deliverables'].values())
    for target in list(tasks):
        if target.get('review_of'):continue
        media={o.get('media_type') for o in target['outputs']}&wanted
        if not media:continue
        children=[t for t in tasks if not t.get('review_of') and any(i.get('from_task')==target['id'] for i in t['inputs'])
            and (execution.REGISTRY.get(t.get('execution',{}).get('capability'),{}).get('review_evidence') or media&{o.get('media_type') for o in t['outputs']})]
        if children:continue # terminal artifact/review will inherit this evidence
        if any(t.get('review_of')==target['id'] for t in tasks):continue
        from .job_owner import independent,user_choice
        if user_choice(grant,target):continue
        if not independent(grant) and not (target.get('execution') or target.get('work_tools') or target.get('operation_contract')):continue
        if media&VISUAL_DOCUMENTS and not target.get('work_tools',{}).get('steps',{}).get('inspect') and not execution.REGISTRY.get(target.get('execution',{}).get('capability'),{}).get('review_evidence'):
            choices=[cap for cap in grant['operations'] if execution.REGISTRY[cap].get('review_evidence') and media&set(execution.REGISTRY[cap]['input_types'])]
            if len(choices)!=1:raise ValueError('Final visual file requires one granted registered preview operation; choose its explicit render and review tasks')
            cap=choices[0]
            if execution.parameter_schema(cap).get('required'):raise ValueError('Preview operation needs semantic parameters; declare it explicitly')
            selected=[o for o in target['outputs'] if o.get('media_type') in execution.REGISTRY[cap]['input_types']]
            if len(selected)!=1:raise ValueError('Select the exact file to render before final review')
            o=selected[0];render=dict(id=label(target['id'],'preview'),objective='Render exact final candidate for independent inspection',
                instruction='Use the registered preview operation on the exact candidate.',
                execution=dict(capability=cap,version=execution.REGISTRY[cap]['version'],parameters={}),
                inputs=[dict(from_task=target['id'],output=o['path'],path='candidate/'+o['path'],purpose=o['purpose'],authority='Exact unreviewed candidate',media_type=o['media_type'])],
                outputs=native_outputs(cap),dependencies=[target['id']])
            append(tasks,render);target=render
        review=reviewer({**target,'criteria':target.get('criteria',['Fulfill the exact requested deliverable.'])},grant)
        review.pop('limits');review.pop('max_attempts');append(tasks,review)


def prepare_records(plan,session,used):
    """Reuse normal planning's companions, capacity and partition implementation."""
    from task_relay import record_planning
    from .connector_protocol import bind
    grant=session.grant;tasks=plan['tasks'];ceiling=request_ceiling(grant);decisions=[]
    for task in list(tasks):
        intent=task.get('records')
        if not intent:continue
        family=operation_contracts.identity(intent['family']);interface=family['planning_interface']
        hooks=family.get('lifecycle');receipt=None
        if session.grant.get('coordination_version')==1 and hooks and hooks.prepare_recovery:
            receipt=hooks.prepare_recovery(task,session)
        # Baseline resolution owns immutable choices before workload, partitions
        # or reviewers consume them. Missing new-content choices still reject.
        from . import parameter_contracts
        parameter_contracts.validate(intent['parameters'],interface['schema'],'content choices')
        workload=interface.get('workload')
        if workload:
            ref=intent['inputs'][workload['input']]
            if 'source' in ref:
                artifact,raw=session.artifact(ref['source'])
                from .research_quality import load_json
                data=load_json(raw)
                units=data.get(workload['collection'])
                if not isinstance(units,list):raise ValueError('Registered workload source has no subject collection')
                maximum=intent['parameters']['max_records']
                if len(units)>maximum:raise ValueError('Subject count exceeds the proposed content bound; preserve all subjects and increase the declared bound within frozen capacity')
                # max_records is a ceiling, not an instruction to invent subjects.
                # Keep semantic policy immutable across deferred/resolved inputs
                # and corrections. Only compiler capacity uses observed workload.
                task['record_workload']=max(1,len(units))
                decisions.append(dict(kind='registered_workload',producer=task['id'],source=ref['source'],sha256=artifact['sha256'],declared_bound=maximum,actual_units=len(units),compiled_bound=task['record_workload']))
        from .job_owner import user_choice
        if interface.get('review_mode')!='structural' and not user_choice(grant,task) and not any(t.get('review_of')==task['id'] for t in tasks):
            review=reviewer(task,grant);append(tasks,review)
            decisions.append(dict(kind='required_review',producer=task['id'],reviewer=review['id'],slot_consumed=True))
        if receipt:
            reviews=[t for t in tasks if t.get('review_of')==task['id']]
            if len(reviews)!=1:raise ValueError('Evidence composition requires one exact candidate reviewer')
            output=task['record_composition']['source_pack_output']
            if not any(i.get('from_task')==task['id'] and i.get('output')==output for i in reviews[0]['inputs']):
                reviews[0]['inputs'].append(dict(from_task=task['id'],output=output,path='composed/'+task['id']+'/sources.json',
                    purpose='Exact code-composed evidence',authority='Evidence only; no acceptance',media_type='application/json'))
            decisions.append(receipt)
    ceilings={t['id']:min(ceiling,t['limits']['tool_calls'],t['limits'].get('provider_requests',ceiling)) for t in tasks if not t.get('execution')}
    scope=dict(connector_companions_version=1,structural_review_policy_version=1,
        graph_operations=[dict(id=cap,available=True,**execution.REGISTRY[cap]) for cap in grant['operations']])
    # Whole-final-file review is an obligation, even when an intermediate merge
    # can otherwise replace its structural reviewer with registered code checks.
    final_reviews={t['id']:dict(task=t['id'],output=t['outputs'][0]['path']) for t in tasks if t.get('review_of')
        and any(o.get('media_type') in grant['deliverables'].values() for producer in tasks if producer['id']==t['review_of'] for o in producer['outputs'])}
    receipts=record_planning.partition(plan,scope,dict(max_tasks=grant['max_tasks']-used,limits=grant['task_limits']),ceilings,final_reviews)
    # partition() can replace the task list when eliding a structural reviewer.
    for task in plan['tasks']:
        if task.get('execution'):
            cap=task['execution']['capability']
            if cap not in grant['operations']:raise ValueError('Partition merge is outside the frozen operation grant')
            task.update(bind(task,grant['operations'][cap]))
    decisions.extend(record_planning.budgets(plan,ceilings,grant['task_limits']['response_tokens']))
    if len(plan['tasks'])+used>grant['max_tasks']:raise ValueError('Required workers, reviewers and merge operations exceed remaining job slots')
    return decisions+receipts


def artifact_type(raw):
    """Code validation describes compatibility only, never semantic acceptance."""
    from .research_quality import load_json
    try:
        value=load_json(raw);identity=value.get('contract') if isinstance(value,dict) else None
        if identity:
            family=operation_contracts.identity(identity)
            operation_contracts.validate_document(raw,identity)
            return dict(contract=identity,role=family.get('record_role'),sealed=value.get('complete') is True)
        from .layout_contract import validate_document
        validate_document(value)
        return dict(contract=dict(id='document.layout',version=1),role='layout',sealed=True)
    except (ValueError,KeyError,TypeError):return dict(contract=None,role=None,sealed=False)


def discovery(session,selected):
    refs=list(dict.fromkeys(session.grant['inputs']+[a['id'] for a in session.rt.status(session.run)['artifacts']]))
    artifacts=[]
    for ident in refs:
        a,raw=session.artifact(ident)
        item=dict(artifact=ident,assessment='Unaccepted evidence; type compatibility is not review')
        item.update(artifact_type(raw))
        from task_relay.external_evidence import recorded_sources
        item['recorded_source']=bool(recorded_sources(session.rt,[dict(artifact=ident,sha256=a['sha256'],bytes=a['bytes'])],allow_empty=True))
        artifacts.append(item)
    ports={}
    for cap in selected:
        demands=execution.adapter(cap).handoffs['ports']
        named=[p['reference_parameter'] for p in demands if p.get('reference_parameter')]
        ports[cap]=dict(data_selection=('The JSON preparation is selected by '+', '.join(named)+'; do not add a separate data alias' if named else
            'Use data for the single JSON port; inputs are context/assets' if any(p['selector']=='json' for p in demands) else 'Use exact references in named parameters'),
            content_roles=[dict(parameter=p,roles=list(roles),compatible_artifacts=[a['artifact'] for a in artifacts if a['sealed'] and a['role'] in roles]) for p,roles in execution.adapter(cap).content_ports])
    return dict(effective_request_ceiling=request_ceiling(session.grant),artifacts=artifacts,input_roles=ports,remaining_task_slots=session.snapshot()['remaining_task_slots'],
        compiler='Required record reviewers and supported partitions/merge tasks are automatic and consume these slots. Untyped evidence requires a registered content worker; never relabel it as sealed data.')
