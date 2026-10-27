"""Compile explicit sourcing intent to service-owned record contracts."""
from pathlib import PurePosixPath

from orchestrator.sourcing_contract import SEMANTIC_CRITERION

INSTRUCTIONS='''For source-backed sourcing catalogs use task.sourcing with version:1,
inventory and source_pack as exact input-binding references ({source:artifact_id}
or {producer:task_id,output:declared_output_path}), options_per_item and count_policy
(required or target) preserving the user's policy, and max_records matching the
bounded inventory size. This requires a files.text API worker and one JSON catalog
plus one Markdown schedule. Declare an independent files.text API reviewer with
both outputs and the same inventory/source-pack inputs. Code constructs both
operation contracts and their exports; never supply operation_contract yourself.
Submit each item through operation_submit, including unresolved items with gaps.
Code captures source spans and constructs product values/identities. Independent
review checkpoints one exact item version at a time. Budget at least max_records+2
tools/provider_requests, plus saved-page reads for the producer. All original
semantic criteria remain; visual inspection requires a separate capable worker.
This text-only preparation is not new browsing, stock verification or acceptance.
If the selected/locked worker cannot submit typed records, report that limitation
without switching providers or enlarging a user budget.'''
INVENTORY_INSTRUCTIONS='''For visual inventory use task.sourcing {version:2,kind:"inventory",image:exact input binding,max_records:bounded count}. Declare that PNG input with visual_reference:true, a files.text/images.view API worker, one JSON and one Markdown output and an independent image-capable reviewer with the same image. Reserve max_records+3 requests/tools. Existing AVIF/JPEG uploads need their recorded decoded PNG artifact, never relabel original bytes. For final specifications use the registered sourcing.slides operation with exact inventory/catalog/source-pack/image paths and an optional reviewed photos ZIP; code constructs the editable image map and all alternative cards. Bind its JSON, exact room PNG and the same photo ZIP to pptx.create. Final visual/factual review remains required, without inventing a user gate. Photo subjects use exact catalog option_id and product_url. Missing photos and unknown fields are disclosed, not guessed.'''

def schema(include_inventory=False):
    from .planning_contract import obj
    from .artifact_bindings import schema as binding
    options=obj({'version':{'type':'integer','enum':[1]},'inventory':binding(),
                'source_pack':binding(),'options_per_item':{'type':'integer'},
                'count_policy':{'type':'string','enum':['required','target']},
                'max_records':{'type':'integer'}},
               ('version','inventory','source_pack','options_per_item','count_policy','max_records'))
    if not include_inventory:return options
    return {'anyOf':[options,obj({'version':{'type':'integer','enum':[2]},'kind':{'type':'string','enum':['inventory']},'image':binding(),'max_records':{'type':'integer'}})]}

def selected_path(task,ref):
    if set(ref)=={'source'}:
        matches=[i for i in task['inputs'] if i.get('artifact')==ref['source']]
    elif set(ref)=={'producer','output'}:
        matches=[i for i in task['inputs'] if i.get('from_task')==ref['producer'] and i.get('output')==ref['output']]
    else:raise ValueError('Sourcing selects only an exact source or producer/output binding')
    if len(matches)!=1:raise ValueError('Sourcing input reference must match one declared bound input')
    return matches[0]['path']

def pair(task):
    owned=task.get('sourcing_composition',{}).get('source_pack_output')
    outputs=[o for o in task['outputs'] if o['path']!=owned]
    jsons=[o['path'] for o in outputs if PurePosixPath(o['path']).suffix=='.json']
    markdown=[o['path'] for o in outputs if PurePosixPath(o['path']).suffix=='.md']
    if len(jsons)!=1 or len(markdown)!=1 or len(outputs)!=2:
        raise ValueError('Typed sourcing requires exactly one JSON and one code-generated Markdown output')
    return jsons[0],markdown[0]

def review_pair(task,version):
    # This JSON is a projection of typed judgments, not a second LLM-authored
    # report. New connector contracts own its companion to the selected summary.
    outputs=task['outputs']
    if version>=2 and len(outputs)==1 and PurePosixPath(outputs[0]['path']).suffix=='.md':
        path=str(PurePosixPath(outputs[0]['path']).with_suffix('.json'))
        if path in {i['path'] for i in task['inputs']}:raise ValueError('Sourcing review companion conflicts with a declared input')
        outputs.append(dict(path=path,purpose='Code-generated typed item-review records paired with the declared Markdown summary',media_type='application/json'))
    return pair(task)

def translate_options(plan):
    """Compatibility at one boundary; no historical provider/scope migration."""
    converted=[]
    for producer in plan['tasks']:
        intent=producer.get('sourcing')
        if not intent or intent.get('kind')=='inventory':continue
        producer.pop('sourcing');converted.append(producer['id'])
        producer['records']=dict(family=dict(id='sourcing.options',version=1),
            inputs=dict(inventory_path=intent['inventory'],source_pack_path=intent['source_pack']),
            parameters={k:intent[k] for k in ('max_records','count_policy','options_per_item')})
        if producer.get('sourcing_range'):producer['records_range']=producer.pop('sourcing_range')
    return converted


def restore_options(plan):
    for producer in plan['tasks']:
        intent=producer.get('records')
        if not intent or intent['family']['id']!='sourcing.options':continue
        producer.pop('records')
        producer['sourcing']=dict(version=1,inventory=intent['inputs']['inventory_path'],source_pack=intent['inputs']['source_pack_path'],**intent['parameters'])
        if producer.get('records_range'):producer['sourcing_range']=producer.pop('records_range')


def partition(plan,scope,options,ceilings,coverage=None):
    from .record_planning import partition as shared_partition
    translate_options(plan)
    try:return shared_partition(plan,scope,options,ceilings,coverage or {},families={'sourcing.options'})
    finally:restore_options(plan)


def budgets(plan,version,approved_limits=None,approved_response_tokens=None):
    """Freeze typed file request bounds within already declared tool capacity."""
    if version<2:return []
    from orchestrator import executors,worker_capabilities
    from .record_planning import budgets as shared_budgets
    if approved_limits is not None:
        translate_options(plan)
        try:common=shared_budgets(plan,approved_limits,approved_response_tokens)
        finally:restore_options(plan)
    else:
        common=[]
        producers={t['id'] for t in plan['tasks'] if t.get('sourcing')}
        for task in plan['tasks']:
            if task['id'] in producers or task.get('review_of') in producers:
                ceiling=min(executors.MAX_EXPLICIT_ROUNDS,task['limits']['tool_calls'])
                task['limits']['provider_requests']=min(task['limits'].get('provider_requests',ceiling),ceiling)
    producers={t['id'] for t in plan['tasks'] if t.get('sourcing',{}).get('kind')=='inventory'}
    bindings=list(common)
    for task in plan['tasks']:
        if task['id'] not in producers and task.get('review_of') not in producers:continue
        if worker_capabilities.backend_for(task,plan['backend'])['type'] not in executors.FILE_TYPES:continue
        limits=task['limits']
        if approved_limits and task['id'] in approved_limits:
            ceiling=approved_limits[task['id']]
            from orchestrator.evidence_workload import record_cost
            intent=next(t['sourcing'] for t in plan['tasks'] if t['id']==(task.get('review_of') or task['id']))
            bounds=task.get('sourcing_range') or next(t for t in plan['tasks'] if t['id']==(task.get('review_of') or task['id'])).get('sourcing_range')
            count=bounds[1]-bounds[0] if bounds else intent['max_records']
            inventory=intent.get('kind')=='inventory'
            inspection=count if not task.get('review_of') and not inventory else 0
            required=record_cost(count+(1 if inventory and not task.get('review_of') else 0),inspection)
            if not inventory and count+1>ceiling:
                raise ValueError('Typed sourcing batch cannot submit its declared items and finish within the frozen provider ceiling; split the batch before dispatch')
            value=min(ceiling,required['tool_calls'])
            for key in ('tool_calls','provider_requests'):
                before=limits.get(key)
                if before!=value:
                    limits[key]=value
                    bindings.append(dict(path='$.plan.tasks.'+task['id']+'.limits.'+key,before=before,value=value,
                        source='computed typed-record workload within frozen stage and API profile ceilings',
                        reason='reserve submissions, bounded inspection, correction and finalization',workload=required))
            response=limits.get('response_tokens',executors.MAX_OUTPUT_TOKENS)
            if type(response) is int and response<4096 and approved_response_tokens is not None and approved_response_tokens>=4096:
                limits['response_tokens']=4096
                bindings.append(dict(path='$.plan.tasks.'+task['id']+'.limits.response_tokens',before=response,value=4096,
                    source='typed-record response minimum within frozen response allowance',
                    reason='reserve the registered structured response minimum'))
        ceiling=min(executors.MAX_EXPLICIT_ROUNDS,limits['tool_calls'])
        limits['provider_requests']=min(limits.get('provider_requests',ceiling),ceiling)
    return bindings

def bind(plan,version=1):
    for task in plan['tasks']:
        intent=task.pop('sourcing',None)
        if intent is None:continue
        from .planning_contract import validate
        validate(intent,schema(version>=2))
        if task.get('review_of') or task.get('operation_contract'):raise ValueError('Sourcing intent belongs only to a new catalog producer')
        output,summary=pair(task)
        if intent.get('kind')=='inventory':
            from orchestrator.sourcing_inventory import validate_assignment,CRITERION
            image_path=selected_path(task,intent['image'])
            p=dict(image_path=image_path,max_records=intent['max_records'],summary_path=summary)
            task['operation_contract']=dict(id='sourcing.inventory',version=1,parameters=p,output=output)
            for o in task['outputs']:
                if o['path']==output:o['content_contract']=dict(id='sourcing.inventory',version=1)
            reviews=[r for r in plan['tasks'] if r.get('review_of')==task['id']]
            if len(reviews)!=1:raise ValueError('Inventory needs one independent visual reviewer')
            reviewer=reviews[0];rp=selected_path(reviewer,intent['image'])
            image=next(i for i in reviewer['inputs'] if i['path']==rp)
            from orchestrator.worker_capabilities import abilities
            if not image.get('visual_reference') or 'images.view' not in abilities(reviewer.get('worker',{}).get('backend',plan['backend'])):raise ValueError('Inventory reviewer must inspect original image pixels')
            task['criteria']=list(dict.fromkeys(c for c in task['criteria']+reviewer['criteria'] if c!=CRITERION))
            reviewer['criteria']=task['criteria']+[CRITERION]
            validate_assignment({**task,'backend':task.get('worker',{}).get('backend',plan['backend'])})
            continue
        p=dict(inventory_path=selected_path(task,intent['inventory']),
               source_pack_path=selected_path(task,intent['source_pack']),
               options_per_item=intent['options_per_item'],count_policy=intent['count_policy'],
               max_records=intent['max_records'],summary_path=summary)
        bounds=task.pop('sourcing_range',None)
        if bounds:p['record_range']=bounds
        composition=task.pop('sourcing_composition',None)
        if composition:
            task['limits']['output_bytes']=composition.pop('export_bytes')
            p.update(composition)
        task['operation_contract']=dict(id='sourcing.options',version=1,parameters=p,output=output)
        for o in task['outputs']:
            if o['path']==output:o['content_contract']=dict(id='sourcing.options',version=1)
        reviews=[r for r in plan['tasks'] if r.get('review_of')==task['id']]
        if len(reviews)!=1:raise ValueError('Typed sourcing needs one independent item-review worker')
        reviewer=reviews[0]
        review_json,review_md=review_pair(reviewer,version)
        catalog_refs=[i['path'] for i in reviewer['inputs'] if i.get('from_task')==task['id'] and i.get('output')==output]
        if len(catalog_refs)!=1:raise ValueError('Sourcing reviewer must receive the exact producer catalog')
        # Resolve the same original source references separately in each worker.
        rp=dict(inventory_path=selected_path(reviewer,intent['inventory']),
                source_pack_path=selected_path(reviewer,intent['source_pack']),
                max_records=p['max_records'],summary_path=review_md,catalog_path=catalog_refs[0])
        if bounds:rp['record_range']=bounds
        if composition:
            rp['source_pack_path']=next(i['path'] for i in reviewer['inputs'] if i.get('from_task')==task['id'] and i.get('output')==composition['source_pack_output'])
        if reviewer.get('operation_contract'):raise ValueError('Sourcing reviewer contract already bound')
        reviewer['operation_contract']=dict(id='sourcing.review',version=1,parameters=rp,output=review_json)
        combined=task['criteria']+reviewer['criteria']
        task['criteria']=list(dict.fromkeys(c for c in combined if version<2 or c!=SEMANTIC_CRITERION))
        reviewer['criteria']=list(task['criteria'])
        if SEMANTIC_CRITERION not in reviewer['criteria']:reviewer['criteria'].append(SEMANTIC_CRITERION)
        for o in reviewer['outputs']:
            if o['path']==review_json:o['content_contract']=dict(id='sourcing.review',version=1)
        from orchestrator.sourcing_contract import validate_assignment
        validate_assignment(task);validate_assignment(reviewer)
