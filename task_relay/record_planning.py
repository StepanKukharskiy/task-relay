"""Compact registered record interfaces; ports, projections and reviews are code-owned."""
import copy
from pathlib import PurePosixPath
from orchestrator import operation_contracts as c


INSTRUCTIONS='''Use task.records for subject-neutral saved-source collection. Select
collection.subjects version 1 to extract subjects from a declared text, JSON or PNG source;
bind source_path and declare fields and max_records. Use an independent file reviewer
with the exact source and subject projections. For alternatives select
collection.options version 1, bind inventory_path and source_pack_path using exact
input references, and supply semantic parameters: field_definitions (field name to
text or price), identity_field, options_per_item, count_policy and max_records.
The same interface handles plants, products or other named subjects. Code owns
paths, JSON/Markdown, item identity, literal span extraction, batches and review
wiring. Declare one independent file reviewer and pass the same inventory/source
inputs plus the producer JSON. Unknown fields and 0/1/5 options are explicit data;
target counts do not invent slots or block delivery. Original source scope,
providers and total allowances remain binding. Models submit fragments only.
For visual selection, gather pixels before catalog approval: images.products with
catalog_path:null uses the exact source pack and inventory to project a bounded
discovery image pool. It retains captured listing entities and search-only leads,
not buying-fact verification. Pass that ZIP, the same source pack and reference
pixels to collection.options and its independent reviewer. source_find/source_read
expose stable lead-* observations; their exact titles may identify visual leads,
but all unsupported buying fields remain unknown. Select only after actual image
comparison; do not make definitive visual exclusions from text alone. Missing
images can use already granted source readers on observed URLs, never invented
links or replay of uncertain reads. max_records bounds SUBJECTS, not alternatives;
code computes workload separately and preserves this semantic ceiling on recovery.
For document content use document.layout version 1 with inputs:{}, parameters
{renderer:"pptx.create",title:string,style:"clean_minimal_v1",max_records:integer}.
Declare one application/json output and a files.text worker, with exact source and
image inputs. No intermediate model reviewer is required: code validates layout
fragments, and the finished rendered document still needs independent review.
Pass that JSON and image assets to the registered renderer; do not write rendering code.'''


def schema(interface_version=2):
    from .planning_contract import obj
    from .artifact_bindings import schema as binding
    variants=[]
    for (ident,version),family in c.REGISTRY.items():
        interface=family.get('planning_interface')
        if not interface or interface.get('expose') is False or family.get('planning_version',1)>interface_version:continue
        variants.append(obj(dict(family=obj(dict(id={'type':'string','enum':[ident]},version={'type':'integer','enum':[version]})),
            inputs=obj({k:binding() for k in interface['input_parameters']}),parameters=interface['schema'])))
    return {'anyOf':variants}


def path(task,reference):
    if set(reference)=={'source'}:
        matches=[i for i in task['inputs'] if i.get('artifact')==reference['source']]
    elif set(reference)=={'producer','output'}:
        matches=[i for i in task['inputs'] if i.get('from_task')==reference['producer'] and i.get('output')==reference['output']]
    else:raise ValueError('Record inputs require an exact compiled binding')
    if len(matches)!=1:raise ValueError('Record input must resolve to one declared version')
    return matches[0]['path']


def outputs(task,companion=False):
    composition=task.get('record_composition',task.get('sourcing_composition',{}))
    values=[o for o in task['outputs'] if o['path']!=composition.get('source_pack_output')]
    if companion and len(values)==1 and PurePosixPath(values[0]['path']).suffix=='.md':
        json_path=str(PurePosixPath(values[0]['path']).with_suffix('.json'))
        if json_path in {i['path'] for i in task['inputs']}:raise ValueError('Record projection collides with an input')
        descriptor=dict(path=json_path,purpose='Code-generated version-bound records',media_type='application/json')
        values.append(descriptor);task['outputs'].append(descriptor)
    jsons=[o['path'] for o in values if PurePosixPath(o['path']).suffix=='.json']
    summaries=[o['path'] for o in values if PurePosixPath(o['path']).suffix=='.md']
    if len(values)!=2 or len(jsons)!=1 or len(summaries)!=1:raise ValueError('Declare one JSON projection and one Markdown companion')
    return jsons[0],summaries[0]


def bind(plan,version=2,workers=None,evidence_binder=None,review_policy=None):
    """Registered semantic parameters + ports, never hand-authored path contracts."""
    from .planning_contract import validate
    from orchestrator.sourcing_contract import SEMANTIC_CRITERION
    def validate_bound(task):
        if evidence_binder:evidence_binder(task)
        if workers is not None:
            from orchestrator import worker_capabilities,executors
            task.pop('tools',None)
            from orchestrator.owner_intents import worker_requirements
            task['worker']=dict(requires=worker_requirements(task) if task.get('work_tools') or task.get('artifact_roles') else ['files.text'])
            eligible=[w for w in workers if w['backend']['type'] in (*executors.FILE_TYPES,'codex-cli')]
            worker_capabilities.resolve(task,eligible,plan['backend'])
        c.validate_assignment({**task,'backend':task.get('worker',{}).get('backend',plan['backend'])})
    for producer in plan['tasks']:
        intent=producer.pop('records',None)
        producer.pop('record_workload',None)
        if intent is None:continue
        validate(intent,schema(version));family=c.identity(intent['family']);interface=family['planning_interface']
        if producer.get('review_of') or producer.get('operation_contract'):raise ValueError('Record intent belongs to an unbound producer')
        reviews=[t for t in plan['tasks'] if t.get('review_of')==producer['id']]
        if interface.get('review_mode')=='structural':
            # Structural validation creates no model review obligation. Preserve
            # an explicitly declared semantic content review without adding one.
            if producer.get('work_tools'):
                from orchestrator.worker_tools import CONTENT
                if producer['outputs'][0]['path']!=CONTENT:raise ValueError('Work content projection changed')
            if (not producer.get('work_tools') and len(producer['outputs'])!=1 or producer['outputs'][0].get('media_type')!='application/json'
                    or PurePosixPath(producer['outputs'][0]['path']).suffix!='.json'):
                raise ValueError('Layout preparation declares one JSON projection')
            producer['outputs'][0]['content_contract']=intent['family'].copy()
            params=copy.deepcopy(intent['parameters'])
            params.update({k:path(producer,ref) for k,ref in intent['inputs'].items()})
            producer['operation_contract']=dict(**intent['family'],parameters=params,output=producer['outputs'][0]['path'])
            validate_bound(producer)
            continue
        if not reviews and review_policy=='user' and family.get('user_review') and interface.get('review_mode')=='file':
            output,summary=outputs(producer)
            params=copy.deepcopy(intent['parameters'])
            params.update({k:path(producer,ref) for k,ref in intent['inputs'].items()},summary_path=summary)
            producer['operation_contract']=dict(**intent['family'],parameters=params,output=output)
            for descriptor in producer['outputs']:
                if descriptor['path']==output:descriptor['content_contract']=intent['family'].copy()
            validate_bound(producer)
            continue
        if len(reviews)!=1:raise ValueError('A record producer needs one independent version-bound reviewer')
        review=reviews[0]
        if review.get('operation_contract'):raise ValueError('Record reviewer already has a contract')
        output,summary=outputs(producer)
        if interface.get('review_mode')=='file':
            params=copy.deepcopy(intent['parameters'])
            params.update({k:path(producer,ref) for k,ref in intent['inputs'].items()},summary_path=summary)
            # Require exact source and projection bindings; add only the code summary.
            for ref in intent['inputs'].values():path(review,ref)
            if not any(i.get('from_task')==producer['id'] and i.get('output')==output for i in review['inputs']):
                raise ValueError('Subject reviewer must bind the exact producer projection')
            if not any(i.get('from_task')==producer['id'] and i.get('output')==summary for i in review['inputs']):
                summary_path='records/'+producer['id']+'/summary.md'
                if summary_path in {i['path'] for i in review['inputs']}|{o['path'] for o in review['outputs']}:raise ValueError('Subject summary binding conflicts with a path')
                review['inputs'].append(dict(from_task=producer['id'],output=summary,path=summary_path,purpose='Exact subject summary',authority='Unaccepted candidate',media_type='text/markdown'))
            source=next(i for i in producer['inputs'] if i['path']==params['source_path'])
            if source.get('media_type')=='image/png':
                worker=review.setdefault('worker',{})
                worker['requires']=list(dict.fromkeys(worker.get('requires',[])+['images.view']))
            review['dependencies']=list(dict.fromkeys(review['dependencies']+[producer['id']]))
            producer['operation_contract']=dict(**intent['family'],parameters=params,output=output)
            from orchestrator.subject_contract import CRITERION
            review['criteria']=list(dict.fromkeys(review['criteria']+[CRITERION]))
            for descriptor in producer['outputs']:
                if descriptor['path']==output:descriptor['content_contract']=intent['family'].copy()
            validate_bound(producer)
            continue
        routput,rsummary=outputs(review,True)
        if not any(i.get('from_task')==producer['id'] and i.get('output')==summary for i in review['inputs']):
            summary_binding='records/'+producer['id']+'/summary.md'
            if summary_binding in {i['path'] for i in review['inputs']}|{o['path'] for o in review['outputs']}:raise ValueError('Record summary review binding conflicts with a declared path')
            review['inputs'].append(dict(from_task=producer['id'],output=summary,path=summary_binding,purpose='Code-generated summary of exact reviewed records',authority='Unaccepted candidate',media_type='text/markdown'))
        review['dependencies']=list(dict.fromkeys(review['dependencies']+[producer['id']]))
        params=copy.deepcopy(intent['parameters'])
        params.update({k:path(producer,ref) for k,ref in intent['inputs'].items()},summary_path=summary)
        composition=producer.pop('record_composition',producer.pop('sourcing_composition',None))
        if composition:
            producer['limits']['output_bytes']=composition['export_bytes']
            params.update({k:v for k,v in composition.items() if k!='export_bytes'})
        refs=[i['path'] for i in review['inputs'] if i.get('from_task')==producer['id'] and i.get('output')==output]
        if len(refs)!=1:raise ValueError('Reviewer must bind the exact producer projection')
        review_params={k:params[k] for k in interface['review_parameters']}
        review_params.update({k:path(review,ref) for k,ref in intent['inputs'].items()},summary_path=rsummary,catalog_path=refs[0])
        if composition:
            refs=[i['path'] for i in review['inputs'] if i.get('from_task')==producer['id'] and i.get('output')==composition['source_pack_output']]
            if len(refs)!=1:raise ValueError('Reviewer needs the exact composed source version')
            review_params['source_pack_path']=refs[0]
        if producer.get('records_range'):
            params['record_range']=producer.pop('records_range');review_params['record_range']=params['record_range']
            scope='\nCompiled record scope: this assignment covers only inventory indices '+str(params['record_range'])+' (end exclusive). operation_progress.scope lists exact assigned identities. Apply the original requirements to these identities; other partitions are evidence, not missing local work. The merge checks whole-inventory coverage. Saved records are not semantic acceptance.'
            producer['instruction']+=scope;review['instruction']+=scope
        producer['operation_contract']=dict(**intent['family'],parameters=params,output=output)
        review['operation_contract']=dict(id=family['review_family'],version=intent['family']['version'],parameters=review_params,output=routput)
        combined=list(dict.fromkeys(producer['criteria']+review['criteria']))
        producer['criteria']=[v for v in combined if v!=SEMANTIC_CRITERION]
        review['criteria']=producer['criteria']+[SEMANTIC_CRITERION]
        for task,selected in ((producer,output),(review,routput)):
            for descriptor in task['outputs']:
                if descriptor['path']==selected:descriptor['content_contract']={k:task['operation_contract'][k] for k in ('id','version')}
            validate_bound(task)


def partition(plan,scope,options,ceilings,deliverables,*,families=None):
    """Common capacity/ports compiler for any registered partitionable interface."""
    frozen={s['id']:s for s in scope.get('graph_operations',[])};receipts=[]
    for producer in list(plan['tasks']):
        intent=producer.get('records')
        if not intent or producer['id'] not in ceilings or producer.get('records_range') or families is not None and intent['family']['id'] not in families:continue
        family=c.identity(intent['family']);interface=family['planning_interface']
        if not interface.get('merge_operation'):continue
        reviews=[t for t in plan['tasks'] if t.get('review_of')==producer['id']]
        if len(reviews)!=1:raise ValueError('Partitioned record work needs one reviewer')
        review=reviews[0];ranges=interface['capacity'].ranges(producer.get('record_workload',intent['parameters']['max_records']),min(ceilings[producer['id']],ceilings.get(review['id'],ceilings[producer['id']])))
        if len(ranges)<=1:
            if producer.get('record_workload',intent['parameters']['max_records'])!=intent['parameters']['max_records']:
                producer['records_range']=ranges[0]
            continue
        native=frozen.get(interface['merge_operation'],{})
        if scope.get('connector_companions_version')!=1 or not native.get('available'):continue
        if producer.get('user_gate') or review.get('user_gate'):raise ValueError('Partitioning cannot remove an explicit human gate')
        # The prospective policy may eliminate one structural reviewer. Check
        # the final graph below; do not spend a task slot on an omitted gate.
        possible_removal=int(scope.get('structural_review_policy_version')==1)
        if len(plan['tasks'])+2*len(ranges)>options['max_tasks']+possible_removal:raise ValueError('Record partitions exceed the frozen graph size')
        output,summary=outputs(producer);catalogs=[];judgments=[];pairs=[];names={t['id'] for t in plan['tasks']}
        for index,bounds in enumerate(ranges,1):
            ident=producer['id']+'_batch_'+str(index);rid=ident+'_review'
            if len(rid)>80 or {ident,rid}&names:raise ValueError('Record partition ID conflict')
            names.update((ident,rid));chunk=copy.deepcopy(producer);judge=copy.deepcopy(review)
            chunk.update(id=ident,records_range=bounds);judge.update(id=rid,review_of=ident)
            judge['dependencies']=[ident if d==producer['id'] else d for d in judge['dependencies']]
            for item in judge['inputs']:
                if item.get('from_task')==producer['id']:item['from_task']=ident
            rjson,_=outputs(judge,True)
            for target,tid,file in ((catalogs,ident,output),(judgments,rid,rjson)):
                target.append(dict(from_task=tid,output=file,path=f'partitions/{index}/'+('catalog.json' if target is catalogs else 'review.json'),purpose='Exact reviewed partition version',authority='Candidate and independent review',media_type='application/json'))
            pairs.extend((chunk,judge));ceilings[ident]=ceilings[rid]=min(ceilings[producer['id']],ceilings.get(review['id'],ceilings[producer['id']]))
        paths={k:path(producer,ref) for k,ref in intent['inputs'].items()}
        from orchestrator.record_transfers import project
        params=project(family,intent['parameters'],paths,[i['path'] for i in catalogs],[i['path'] for i in judgments])
        inputs=[copy.deepcopy(i) for i in producer['inputs'] if i['path'] in paths.values()]+catalogs+judgments
        for item in inputs:item['media_type']='application/json'
        composition=producer.get('record_composition',producer.get('sourcing_composition'))
        if composition:
            inputs=[i for i in inputs if i['path']!=paths['source_pack_path']]
            inputs.append(dict(from_task=pairs[0]['id'],output=composition['source_pack_output'],path=paths['source_pack_path'],
                purpose='Exact composed source version shared by partitions',authority='Captured evidence',media_type='application/json'))
        for key in ('records','record_workload','worker','tools','operation_contract','record_composition','sourcing_composition'):producer.pop(key,None)
        producer.update(execution=dict(capability=interface['merge_operation'],version=native['version'],parameters=params),
            inputs=inputs,dependencies=list(dict.fromkeys(producer['dependencies']+[i['from_task'] for i in inputs if 'from_task' in i]+[t['id'] for t in pairs])),criteria=copy.deepcopy(native['criteria']),
            outputs=[dict(path=p,purpose='Code-composed reviewed records',media_type=m) for p,m in native['outputs'].items()],
            limits=dict(seconds=min(native['seconds'],options['limits']['seconds']),tool_calls=1,output_bytes=min(native['output_bytes'],options['limits']['output_bytes'])),max_attempts=1)
        review.pop('records',None);review['criteria']=copy.deepcopy(native['criteria'])
        mapping={output:'delivery/catalog.json',summary:'delivery/catalog.md'}
        if composition:mapping[composition['source_pack_output']]='delivery/source-pack.json'
        for task in plan['tasks']:
            for item in task['inputs']:
                if item.get('from_task')==producer['id'] and item.get('output') in mapping:item['output']=mapping[item['output']]
        for binding in deliverables.values():
            if binding.get('task')==producer['id'] and binding.get('output') in mapping:binding['output']=mapping[binding['output']]
        if not any(i.get('from_task')==producer['id'] and i.get('output')=='delivery/source-pack.json' for i in review['inputs']):
            review['inputs'].append(dict(from_task=producer['id'],output='delivery/source-pack.json',path='merged/source-pack.json',purpose='Exact merged source version',authority='Captured evidence',media_type='application/json'))
        plan['tasks'].extend(pairs)
        receipts.append(dict(producer=producer['id'],ranges=ranges,source='registered capacity and merge ports',acceptance=False))
        from .structural_review import elide
        verification=elide(plan,producer,review,native,scope,deliverables)
        if verification:receipts.append(verification)
        if len(plan['tasks'])>options['max_tasks']:raise ValueError('Record partitions exceed the frozen graph size')
    return receipts


def budgets(plan,ceilings=None,response_ceiling=None):
    """Check minimum workload while retaining authorized room for corrections."""
    from orchestrator import executors
    receipts=[]
    for producer in plan['tasks']:
        intent=producer.get('records')
        if not intent or producer.get('work_tools'):continue
        family=c.identity(intent['family']);capacity=family['planning_interface']['capacity']
        bounds=producer.get('records_range');count=bounds[1]-bounds[0] if bounds else producer.get('record_workload',intent['parameters']['max_records'])
        for task in [producer]+([t for t in plan['tasks'] if t.get('review_of')==producer['id']] if family['planning_interface'].get('review_mode')!='file' else []):
            limits=task['limits'];ceiling=(ceilings or {}).get(task['id'],min(limits['tool_calls'],limits.get('provider_requests',limits['tool_calls']),executors.MAX_EXPLICIT_ROUNDS))
            needed=capacity.reserved_calls+count*(capacity.submissions_per_unit+(0 if task.get('review_of') else capacity.inspections_per_unit))
            if count+2>ceiling:raise ValueError('Record batch cannot submit and finalize within its frozen allowance')
            for key in ('tool_calls','provider_requests'):
                before=limits.get(key);limits[key]=ceiling
                if limits[key]!=before:receipts.append(dict(path='$.plan.tasks.'+task['id']+'.limits.'+key,before=before,value=limits[key],source='retain frozen record allowance for inspection, validation corrections and finalization',estimated_required_calls=needed))
            if limits.get('response_tokens',4096)<4096 and response_ceiling is not None and response_ceiling>=4096:
                before=limits.get('response_tokens');limits['response_tokens']=4096
                receipts.append(dict(path='$.plan.tasks.'+task['id']+'.limits.response_tokens',before=before,value=4096,source='registered fragment response minimum within frozen allowance'))
    return receipts


def collection_policy(task):
    """Normalize historical intent once; source controllers consume ports/policy."""
    intent=task.get('records')
    if intent:
        family=c.identity(intent['family'])
        if family.get('record_role')!='options':return {}
        return dict(version=1,**intent['parameters'],inventory=intent['inputs']['inventory_path'],source_pack=intent['inputs']['source_pack_path'])
    return task.get('sourcing',{})


def replace_source(task,reference):
    if task.get('records'):task['records']['inputs']['source_pack_path']=reference
    elif task.get('sourcing'):task['sourcing']['source_pack']=reference
