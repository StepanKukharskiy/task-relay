"""Feasibility floors for bounded source/image tasks, after worker resolution."""
from orchestrator.executors import request_limit

INSTRUCTIONS = '''Source/photo batches must fit the resolved worker limits, including finishing.
For browser image discovery reserve four tool calls/provider turns per subject
(open/inspect, preview/read, export) plus four for setup and finish. At the 24-turn
API ceiling, use at most five subjects and usually fewer for difficult pages.
Declare the actual smaller batches before Start; never advertise 60 API turns.
A web.sources query reserves one search and two page reads within its legacy
60-request ceiling. web.sources.prepared uses its registered 80-request ceiling
and distributes page reads from the literal query count. Split more than 20
queries per native source operation. Retain item mappings. A frozen available
web.sources.rendered companion can render only already observed public URLs in
an isolated browser, preserving captures and failures for independent review.
On failed sources use other candidates within the same granted domains/origins;
keep the failures, preserve successful evidence, and do not assert search snippets
as product verification. Internal independent review is not a user approval gate.
'''


def image_manifest_only(task, capabilities):
    """The image connector exports observed URLs, not an authored factual report."""
    grants=task.get('browser',{}).get('image_sources',[])
    return ('images.fetch' in capabilities and len(grants)==1 and
            len(task.get('outputs',[]))==1 and
            task['outputs'][0]['path']==grants[0]['path'] and
            task['outputs'][0].get('media_type')=='application/json')


def requirements(task):
    groups=task.get('browser',{}).get('image_sources',[])
    if not groups:return None
    subjects=[s['id'] for g in groups for s in g['subjects']]
    count=len(subjects)
    return dict(subjects=count,tool_calls=4*count+4,provider_requests=4*count+4)


def validate(plan):
    for task in plan['tasks']:
        required=requirements(task)
        if required:
            limits=task['limits']
            if required['tool_calls']>limits['tool_calls'] or required['provider_requests']>request_limit(task):
                raise ValueError('Image discovery batch exceeds resolved tools/provider turns including finalization; split subjects into smaller independently reviewed batches.')
        execution=task.get('execution',{})
        if execution.get('capability')=='web.sources':
            if 3*len(execution['parameters']['queries'])>60:
                raise ValueError('Source query batch exceeds native external-request budget; split literal queries.')


def bind_fallback(proposal,scope,options):
    """Connect optional rendered reads only within a freshly frozen companion grant."""
    import copy
    if scope.get('connector_companions_version')!=1 or scope.get('delivery_completion_policy_version')!=1:return []
    operations={s['id']:s for s in scope.get('graph_operations',[])}
    fallback=operations.get('web.sources.rendered',{})
    if not fallback.get('available'):return []
    tasks=proposal.get('plan',{}).get('tasks',[]);receipts=[]
    for source in list(tasks):
        cap=source.get('execution',{}).get('capability')
        if operations.get(cap,{}).get('companions',{}).get('web.sources.rendered')!='observed-public-page-rendering-fallback':continue
        if any(t.get('execution',{}).get('capability')=='web.sources.rendered' and any(i.get('from_task')==source['id'] for i in t.get('inputs',[])) for t in tasks):continue
        reviews=[t for t in tasks if t.get('review_of')==source['id']]
        consumers=[t for t in tasks if not t.get('review_of') and not t.get('execution') and any(i.get('from_task')==source['id'] for i in t.get('inputs',[]))]
        if len(reviews)!=1 or not consumers or source.get('user_gate') or reviews[0].get('user_gate'):continue
        if len(tasks)+2>options['max_tasks']:continue
        output=next((o for o in source['outputs'] if o['path']=='delivery/source-pack.json'),None)
        if not output:continue
        ident=source['id']+'_rendered';rid=ident+'_review'
        if max(len(ident),len(rid))>80 or {ident,rid}&{t['id'] for t in tasks}:raise ValueError('Rendered fallback task identity conflict')
        seconds=min(options['limits']['seconds'],fallback['seconds']);maximum=min(12,(seconds-30)//65)
        if maximum<1:continue
        task=dict(id=ident,role='procedure',objective='Read observed public candidates in an isolated rendered browser',
            instruction='Preserve original source entries and failures; inspect only observed candidate URLs. No new searches, accounts, forms or invented URLs. Captures remain candidates for independent review.',
            execution=dict(capability='web.sources.rendered',version=1,parameters=dict(domains=copy.deepcopy(source['execution']['parameters']['domains']),max_pages=maximum)),
            inputs=[dict(from_task=source['id'],output=output['path'],path='fallback/source-pack.json',purpose='Exact native candidate evidence',authority='Unaccepted saved candidates',media_type='application/json')],
            outputs=[dict(path='delivery/source-pack.json',purpose='Original and rendered candidate evidence',media_type='application/json')],
            dependencies=[source['id'],reviews[0]['id']],criteria=copy.deepcopy(fallback['criteria']),
            limits=dict(seconds=seconds,tool_calls=1,output_bytes=min(3000000,options['limits']['output_bytes'])),max_attempts=1)
        review=copy.deepcopy(reviews[0]);review.update(id=rid,review_of=ident,objective='Independently review original and rendered public candidates',dependencies=[ident])
        for item in review['inputs']:
            if item.get('from_task')==source['id']:item['from_task']=ident
        review['outputs']=[dict(path='rendered-source-review.md',purpose='Independent rendered-source review',media_type='text/markdown')]
        for consumer in consumers:
            for item in consumer['inputs']:
                if item.get('from_task')==source['id']:item['from_task']=ident
            from .record_planning import collection_policy,replace_source
            ref=collection_policy(consumer).get('source_pack',{})
            if ref.get('producer')==source['id']:replace_source(consumer,{**ref,'producer':ident})
            consumer['dependencies']=list(dict.fromkeys(consumer['dependencies']+[ident,rid]))
        for other in tasks:
            if (other.get('review_of') in {t['id'] for t in consumers}
                    or any(i.get('from_task') in {t['id'] for t in consumers} for i in other.get('inputs',[]))):
                for item in other['inputs']:
                    if item.get('from_task')==source['id']:item['from_task']=ident
                other['dependencies']=list(dict.fromkeys(other['dependencies']+[ident,rid]))
        for binding in proposal.get('deliverable_map',{}).values():
            if binding==dict(task=source['id'],output=output['path']):binding['task']=ident
        tasks.extend([task,review]);receipts.append(dict(producer=source['id'],fallback=ident,reviewer=rid,maximum=maximum,
            source='frozen available read companion and original domains',new_searches=False,user_gate_added=False))
    return receipts


def bind_coverage(proposal,scope,options):
    """Compile one bounded product-coverage round, before ordinary consumers.

    A new search allowance must already be present in this request's connector
    metadata. Legacy scopes and explicit user gates never gain this graph.
    """
    import copy
    if scope.get('connector_companions_version')!=1 or scope.get('delivery_completion_policy_version')!=1:return []
    specs={s['id']:s for s in scope.get('graph_operations',[])}
    operation=specs.get('web.sources.coverage',{})
    if not operation.get('available'):return []
    tasks=proposal.get('plan',{}).get('tasks',[]);receipts=[]
    if any(t.get('execution',{}).get('capability')=='web.sources.coverage' for t in tasks):return []
    for producer in list(tasks):
        from .record_planning import collection_policy,replace_source
        intent=collection_policy(producer)
        if intent.get('version')!=1 or intent.get('count_policy')!='target' or producer.get('record_composition',producer.get('sourcing_composition')) or producer.get('user_gate'):continue
        ref=intent['source_pack'];source=next((t for t in tasks if t['id']==ref.get('producer')),None)
        if not source:continue
        origin=source
        if origin.get('execution',{}).get('capability')=='web.sources.rendered':
            origin=next((t for t in tasks if any(i.get('from_task')==t['id'] for i in source['inputs']) and t.get('execution',{}).get('capability') in ('web.sources','web.sources.prepared')),None)
        if not origin or origin.get('execution',{}).get('capability') not in ('web.sources','web.sources.prepared'):continue
        if 'web.sources.coverage' not in specs.get(origin['execution']['capability'],{}).get('companions',{}):continue
        reviews=[r for r in tasks if r.get('review_of')==producer['id']]
        source_reviews=[r for r in tasks if r.get('review_of')==source['id']]
        if len(reviews)!=1 or len(source_reviews)!=1 or reviews[0].get('user_gate'):continue
        if len(tasks)+4>options['max_tasks']:raise ValueError('Coverage recovery exceeds the frozen graph capacity')
        from .sourcing_planning import pair
        output,summary=pair(producer);review=reviews[0];ident=producer['id'];rid=review['id']
        seed=ident+'_seed';seed_review=rid+'_seed';search=ident+'_coverage';search_review=search+'_review'
        names={t['id'] for t in tasks}
        if any(len(n)>80 or n in names for n in (seed,seed_review,search,search_review)):raise ValueError('Coverage connector identity conflict')
        fresh=copy.deepcopy(producer);judge=copy.deepcopy(review)
        producer['id']=seed;review['id']=seed_review;review['review_of']=seed
        review['dependencies']=[seed if d==ident else d for d in review['dependencies']]
        for i in review['inputs']:
            if i.get('from_task')==ident:i['from_task']=seed
        src=next(i for i in fresh['inputs'] if i.get('from_task')==ref['producer'] and i.get('output')==ref['output'])
        original=copy.deepcopy(src);original['path']='base/source-pack.json'
        catalog=dict(from_task=seed,output=output,path='base/catalog.json',purpose='Exact reviewed base catalog',authority='Independent semantic review; no user acceptance',media_type='application/json')
        params=origin['execution']['parameters']
        collect=dict(id=search,role='procedure',objective='Search only reviewed product-coverage shortfalls',
            instruction='Use one bounded code-selected round of mapped subject queries. Preserve errors and original evidence; never count snippets or generic pages as verified alternatives.',
            execution=dict(capability='web.sources.coverage',version=1,parameters=dict(catalog_path=catalog['path'],source_pack_path=original['path'],domains=copy.deepcopy(params['domains']),model=params['model'])),
            inputs=[catalog,copy.deepcopy(original)],outputs=[dict(path='delivery/source-pack.json',purpose='Targeted additional source candidates',media_type='application/json')],
            dependencies=[seed,seed_review],criteria=copy.deepcopy(operation['criteria']),
            limits=dict(seconds=min(operation['seconds'],options['limits']['seconds']),tool_calls=1,output_bytes=min(operation['output_bytes'],options['limits']['output_bytes'])),max_attempts=1)
        sr=copy.deepcopy(source_reviews[0]);sr.update(id=search_review,review_of=search,objective='Review exact targeted additional source candidates',dependencies=[search],criteria=copy.deepcopy(operation['criteria']))
        sr['inputs']=[dict(from_task=search,output='delivery/source-pack.json',path='candidate/source-pack.json',purpose='Exact additional source candidates',authority='Unaccepted',media_type='application/json'),copy.deepcopy(catalog),copy.deepcopy(original)]
        sr['outputs']=[dict(path='coverage-review.md',purpose='Independent targeted source review',media_type='text/markdown')]
        src.update(from_task=search,output='delivery/source-pack.json')
        replace_source(fresh,dict(producer=search,output='delivery/source-pack.json'))
        fresh['inputs'].extend([copy.deepcopy(original),copy.deepcopy(catalog)])
        fresh['outputs'].append(dict(path='delivery/source-pack.json',purpose='Code-composed original and additional source captures',media_type='application/json'))
        fresh['record_composition' if fresh.get('records') else 'sourcing_composition']=dict(base_source_pack_path=original['path'],base_catalog_path=catalog['path'],source_pack_output='delivery/source-pack.json',allow_baseline_amend=True,export_bytes=min(4000000,options['limits']['output_bytes']))
        fresh['dependencies']=list(dict.fromkeys(fresh['dependencies']+[seed_review,search_review]))
        fresh['instruction']+='\nPreserve all supported base options and their exact source spans. Add only alternatives supported by the new mapped source pages. Submit every item, including explicit remaining gaps; a target shortfall alone is not a blocker after this bounded round. If a base candidate is demonstrably wrong or unsupported, use guarded operation_amend after submitting its item; preserve every other supported candidate and explain the correction/gap. Old artifacts and record versions remain immutable; the amended version requires independent semantic review.'
        for i in judge['inputs']:
            if i.get('from_task')==ref['producer'] and i.get('output')==ref['output']:
                i.update(from_task=ident,output='delivery/source-pack.json')
        additional=copy.deepcopy(src);additional['path']='coverage/additional-source-pack.json'
        judge['inputs'].append(additional)
        judge['inputs'].append(dict(from_task=ident,output='delivery/source-pack.json',path='candidate/composed-source-pack.json',purpose='Exact composed source version',authority='Recorded candidates',media_type='application/json')) if not any(i.get('from_task')==ident and i.get('output')=='delivery/source-pack.json' for i in judge['inputs']) else None
        judge['dependencies']=list(dict.fromkeys(judge['dependencies']+[search_review]))
        # Existing consumers keep the logical catalog ID, but matching source
        # context must move to the composed version rather than the seed pack.
        for consumer in tasks:
            if consumer in (producer,review,source,source_reviews[0]) or not any(i.get('from_task')==ident for i in consumer.get('inputs',[])):continue
            for i in consumer['inputs']:
                if i.get('from_task') in (ref['producer'],origin['id']) and i.get('output')==ref['output']:i.update(from_task=ident,output='delivery/source-pack.json')
        tasks.extend((collect,sr,fresh,judge))
        for binding in proposal.get('deliverable_map',{}).values():
            if binding.get('task')==ref['producer'] and binding.get('output')==ref['output']:
                binding.update(task=ident,output='delivery/source-pack.json')
        for task in tasks:
            task['dependencies']=list(dict.fromkeys(task['dependencies']+[i['from_task'] for i in task.get('inputs',[]) if 'from_task' in i]))
        receipts.append(dict(producer=ident,base=seed,source_task=search,reviewer=search_review,maximum_rounds=1,
            source='frozen optional coverage connector and exact reviewed catalog',acceptance=False))
    return receipts
