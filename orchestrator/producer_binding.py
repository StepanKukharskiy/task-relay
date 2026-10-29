"""Backward contract binding over registered graph ports, before any dispatch.

This compiler only edits the explicitly new/future assignments handed to it.
It never converts saved evidence, creates extra tasks, or increases allowances.
"""
import copy
from . import prepared_schemas

CONTEXT=('text.bundle','gemini.text','blender.startup','images.crop','images.pptx','images.gallery','web.sources','pptx.render','images.collect',
    'images.merge','runway.image','runway.video','higgsfield.image','higgsfield.video','meshy.mesh','gemini.image',
    'openai.image','openrouter.image','blender.geometry','blender.inspect','rhino.startup','rhino.inspect','sketchup.startup','sketchup.inspect')


def port(selector,kind,**kw):return dict(selector=selector,kind=kind,**kw)


PORTS={cap:[] for cap in CONTEXT}
PORTS.update({cap:[port('json','preparation',target=cap)] for cap in prepared_schemas.REGISTRY})
from .native_apps import SCRIPT_OPERATIONS
for cap in SCRIPT_OPERATIONS:
    PORTS[cap][0]['reference_parameter']='checks_sha256'
PORTS['pptx.create']=[port('json','records',families=['document.layout'],native=['sourcing.slides','collection.slides','document.compose'])]
PORTS['document.compose']=[port('parameter:document_paths','records',families=['document.layout'],native=['sourcing.slides','collection.slides','document.compose'])]
PORTS['web.sources.rendered']=[port('json','evidence',native=['web.sources','web.sources.prepared','web.sources.coverage','web.sources.rendered'])]
PORTS['web.sources.native']=copy.deepcopy(PORTS['web.sources.rendered'])
PORTS['images.fetch']=[port('json','evidence',native=[])] # observed browser manifest, never inferred URLs
PORTS['hyperframes.render']=[port('json','evidence',native=['hyperframes.preview'])]
for cap in ('images.products','images.catalog','sourcing.slides','collection.slides','sourcing.merge','records.merge','web.sources.coverage'):
    PORTS[cap]=[port('parameter:source_pack_path','evidence',native=['web.sources','web.sources.prepared','web.sources.coverage','web.sources.rendered','sourcing.merge','records.merge'])]
    PORTS[cap].append(port('parameter:catalog_paths' if cap.endswith('.merge') else 'parameter:catalog_path','records',
                          families=['collection.options','sourcing.options']))
    if cap.endswith('.merge'):PORTS[cap].append(port('parameter:review_paths','records',families=['collection.review','sourcing.review']))
    if cap!='web.sources.coverage':PORTS[cap].append(port('parameter:inventory_path','records',families=['collection.subjects','sourcing.inventory'],legacy=True))


def manifest(capability):
    if capability not in PORTS:raise ValueError('Operation has no registered handoff policy: '+capability)
    return dict(version=1,default='declared-context-or-native-file',ports=copy.deepcopy(PORTS[capability]))


def requirements(capability):
    from .execution import adapter
    policy=adapter(capability).handoffs
    if policy is None or policy.get('version')!=1:raise ValueError('Operation has no registered producer binding policy')
    return policy['ports']


def selected(task,port):
    selector=port['selector']
    if selector=='json':
        items=[i for i in task['inputs'] if i.get('media_type')=='application/json']
        if len(items)!=1:raise ValueError('Registered preparation/evidence port requires exactly one JSON input')
        return items
    paths=task['execution']['parameters'][selector.split(':',1)[1]]
    if paths is None:return [] # Only explicitly nullable registered ports may omit a binding.
    paths=paths if isinstance(paths,list) else [paths]
    items=[]
    for path in paths:
        matches=[i for i in task['inputs'] if i['path']==path and i.get('media_type')=='application/json']
        if len(matches)!=1:raise ValueError('Registered handoff must select one exact JSON input: '+str(path))
        items.append(matches[0])
    return items


def validate_graph(view,*,exact_baselines=False):
    """Check authored wires against the same registered consumer ports, without I/O.

    Run admission still owns concrete files, hashes, capabilities and budgets.
    Missing setup fields remain editable; known incompatible wires fail here.
    """
    from . import execution
    nodes={n['id']:n for n in view['tasks']}
    for ident,node in nodes.items():
        capability=node['operation']
        if capability not in execution.REGISTRY:continue
        links=[c for c in view['connections'] if c['task']==ident]
        for link in links:
            policy=execution.adapter(capability).reference_media.get(link['input'])
            if policy and 'task' in link['source'] and link['media_type']!=policy['media_type']:
                ref=link['source']
                raise ValueError(f'{ident} ({capability}): future output {ref["task"]}/{ref["output"]} must declare {policy["media_type"]} for {link["input"]}; update its producer and connected model input declarations. Historical saved-file compatibility does not retype future outputs.')
        for demand in requirements(capability):
            selector=demand['selector']
            name=selector.split(':',1)[1] if selector.startswith('parameter:') else None
            relevant=[c for c in links if name is None or c['input']==name]
            # An Ask when run file/bundle cannot be counted until it is supplied.
            pending=[k for k,v in node['inputs'].items() if 'workflow' in v and
                     (k==name if name else k=='files' or k in execution.adapter(capability).references)]
            if pending:continue
            if not relevant:continue
            items=[dict(path=str(i),media_type=c['media_type'],link=c) for i,c in enumerate(relevant)]
            params={name:[i['path'] for i in items]} if name else {}
            try:chosen=selected(dict(inputs=items,execution=dict(parameters=params)),demand)
            except ValueError:
                actual=', '.join(str(c['source'])+' ('+str(c['media_type'])+')' for c in relevant)
                target=demand.get('target') or ', '.join(demand.get('families',[])) or 'registered evidence'
                raise ValueError(f'{ident} ({capability}): {name or "files"} requires exactly one application/json input for {target}; received {actual}. Connect a compatible structured output, not prose.') from None
            for item in chosen:
                ref=item['link']['source'];source=nodes.get(ref.get('task'))
                if not source:continue  # Exact saved artifacts checked at admission.
                native=source['operation'] if source['operation'] in execution.REGISTRY else None
                if native:
                    if not compatible_native(native,demand.get('native',[])):
                        raise ValueError(f'{ident} ({capability}): {source["id"]}/{ref["output"]} is not a compatible registered {demand["kind"]} producer')
                elif source['operation']=='model':
                    if demand['kind']=='evidence':
                        raise ValueError(f'{ident} ({capability}): evidence must come from its registered producer, not model-authored JSON')
                    if demand['kind']=='preparation' and len(source['outputs'])!=1:
                        raise ValueError(f'{source["id"]}: split structured preparation for {capability} from unrelated outputs; use exactly one JSON output')
                    if demand['kind']=='preparation' and exact_baselines:
                        for field,media in prepared_schemas.REGISTRY[demand['target']]['hash_inputs'].items():
                            baselines=[c for c in links if c['media_type']==media]
                            if len(baselines)!=1:
                                raise ValueError(f'{ident} ({capability}): preparation requires one exact {media} baseline for {field}')
                            baseline=baselines[0]['source']
                            shared=[c for c in view['connections'] if c['task']==source['id'] and c['source']==baseline]
                            if len(shared)!=1:
                                raise ValueError(f'{source["id"]}: preparation for {ident} ({capability}) must connect the same exact baseline {baseline} once, alongside any inspection report. Code binds its hash; this binary is identity evidence, not a request for model binary-reading tools.')
                elif source['operation'] not in demand.get('families',[]):
                    raise ValueError(f'{ident} ({capability}): {source["operation"]} does not supply the required {demand["kind"]} contract')


def validate_model_workers(view,default_model=None):
    """Resolve ordinary model-node capabilities before committing a proposal.

    Structured authors are bound by their consumer at compilation; their binary
    inputs can be identity evidence. Ordinary model nodes require actual readers.
    """
    from . import execution,worker_capabilities,owner_intents
    from task_relay.desktop_node_setup import backend
    typed=set()
    for node in view['tasks']:
        if node['operation'] not in execution.REGISTRY:continue
        for demand in requirements(node['operation']):
            if demand['kind'] not in ('preparation','records'):continue
            for link in view['connections']:
                if link['task']!=node['id'] or link['media_type']!='application/json':continue
                if demand['selector'].startswith('parameter:') and link['input']!=demand['selector'].split(':',1)[1]:continue
                if 'task' in link['source']:typed.add(link['source']['task'])
    for node in view['tasks']:
        if node['operation']!='model' or node['id'] in typed:continue
        choice=node.get('model') or default_model
        if not choice:continue
        selected_backend=backend(choice)
        items=[dict(path='input'+str(i)+owner_intents.suffix(c['media_type']),media_type=c['media_type'])
               for i,c in enumerate(view['connections']) if c['task']==node['id']]
        outputs=[dict(path=o['name']+owner_intents.suffix(o['media_type']),media_type=o['media_type']) for o in node['outputs']]
        task=dict(inputs=items,outputs=outputs)
        task['worker']=dict(requires=owner_intents.worker_requirements(task))
        try:worker_capabilities.resolve(task,[worker_capabilities.entry(selected_backend)],selected_backend)
        except ValueError as exc:
            raise ValueError(f'{node["id"]} ({choice["provider"]}): {exc}. Connect supported text/image evidence from the producer rather than an unreadable binary; keep the binary as a workflow output. Do not change the provider or add execution authority.') from None


def reference(item):
    return dict(source=item['artifact']) if 'artifact' in item else dict(producer=item['from_task'],output=item['output'])


def same_source(a,b):return reference(a)==reference(b)


def bind_saved_assets(plan,rt):
    """Keep a sealed preparation's asset paths when its consumer runs separately.

    Only future assignment paths change. Saved documents, artifacts and producing
    assignments remain untouched; names come from the exact completed producer.
    """
    import json
    from .runtime import file_hash
    for task in plan['tasks']:
        capability=task.get('execution',{}).get('capability')
        if not prepared_schemas.REGISTRY.get(capability,{}).get('assets'):continue
        documents=[i for i in task['inputs'] if i.get('media_type')=='application/json']
        if len(documents)!=1 or 'artifact' not in documents[0]:continue
        artifact=rt.artifact(documents[0]['artifact'])
        if not artifact.get('attempt'):continue
        row=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
        if not row:raise ValueError('Saved preparation producer is missing')
        frozen=json.loads(row['frozen']);contract=frozen.get('operation_contract',{})
        if contract.get('id')!='operation.preparation':continue
        if (row['state']!='completed' or row['run']!=artifact['run'] or row['task']!=artifact['task']
            or contract.get('version')!=1 or contract.get('parameters',{}).get('target')!=capability
            or contract.get('output')!=artifact['path'] or file_hash(artifact['blob'])!=artifact['sha256']):
            raise ValueError('Saved preparation requires its exact completed producer')
        paths={}
        for item in task['inputs']:
            if item is documents[0] or 'artifact' not in item:continue
            original=[i for i in frozen['inputs'] if i.get('artifact')==item['artifact']]
            if len(original)!=1:raise ValueError('Saved preparation asset is missing or ambiguous')
            source=original[0];current=rt.artifact(item['artifact'])
            if (source.get('sha256')!=current['sha256'] or file_hash(current['blob'])!=current['sha256']
                or source.get('media_type')!=item.get('media_type')):
                raise ValueError('Saved preparation asset version or media type changed')
            paths[item['path']]=source['path']
        names=[paths.get(i['path'],i['path']) for i in task['inputs']]
        if len(set(names))!=len(names) or set(names)&{o['path'] for o in task['outputs']}:
            raise ValueError('Saved preparation asset paths conflict')
        for item,name in zip(task['inputs'],names):item['path']=name


def compatible_native(capability, choices):
    from .execution import REGISTRY
    # Provider variants explicitly register their source interface separately
    # from transport identity. Never infer compatibility from an ID suffix.
    return capability in choices or REGISTRY[capability].get('source_mode') in choices


def compile(plan,*,editable=None,lookup=None,workers=None,prepare_records=None,evidence_binder=None,review_policy=None):
    """Configure producers from consumer demands; caller commits the whole batch."""
    from . import operation_contracts as contracts,executors,worker_capabilities
    tasks=plan['tasks'];by_id={t['id']:t for t in tasks};editable=set(by_id) if editable is None else set(editable)
    receipts=[];demands={};asset_names={}
    def producer(ident):
        if ident in by_id:return by_id[ident]
        if lookup:return lookup(ident)
        raise ValueError('Missing handoff producer: '+ident)
    # Resolve every demand before editing. Multiple consumers must agree.
    for consumer in tasks:
        capability=consumer.get('execution',{}).get('capability')
        if not capability:continue
        if consumer['id'] in editable:consumer['producer_binding_version']=1
        for demand in requirements(capability):
            for item in selected(consumer,demand):
                if 'from_task' not in item:continue # exact saved bytes are validated by the adapter
                source=producer(item['from_task']);native=source.get('execution',{}).get('capability')
                if demand['kind']=='evidence':
                    if native and not compatible_native(native,demand['native']):raise ValueError('Evidence port requires its registered producer')
                    expected='delivery/verification.json' if capability=='hyperframes.render' else 'delivery/source-pack.json'
                    if native and item['output']!=expected:raise ValueError('Evidence must use the exact registered output port')
                    browser_port=(capability=='images.fetch' and any(p.get('path')==item['output'] for p in source.get('browser',{}).get('image_sources',[])))
                    if not native and not browser_port:
                        bound=source.get('operation_contract',{})
                        family=contracts.REGISTRY.get((bound.get('id'),bound.get('version')),{});hooks=family.get('lifecycle')
                        parameter=hooks.evidence_output_parameter if hooks else ''
                        if not parameter or bound.get('parameters',{}).get(parameter)!=item['output']:
                            raise ValueError('Evidence must come from an exact registered source or browser observation; no model-authored substitute')
                    continue
                actual=contracts.output_contract(source,item['output'])
                if native:
                    if compatible_native(native,demand.get('native',[])):continue
                    if actual and actual['id'] in demand.get('families',[]):continue
                    raise ValueError('Native output has no compatible registered content contract')
                if actual:
                    if demand['kind']=='preparation':
                        bound=source['operation_contract']
                        if actual['id']!='operation.preparation' or bound['parameters']['target']!=demand['target']:raise ValueError('Conflicting prepared output contracts')
                    elif actual['id'] not in demand['families']:raise ValueError('Conflicting record output contracts')
                    continue
                intent=source.get('records')
                family=intent['family']['id'] if intent else None
                if family and family not in demand.get('families',[]):raise ValueError('Producer intent conflicts with its consumer contract')
                if source['id'] not in editable:raise ValueError('Saved producer is untyped; prepare a new version instead of rewriting its assignment')
                if source.get('review_of') and demand.get('families')==['collection.review','sourcing.review']:
                    # The same collection binder configures its independent review.
                    continue
                key=(source['id'],item['output'])
                choice=('operation.preparation',demand['target']) if demand['kind']=='preparation' else (family or demand['families'][0],1)
                if key in demands and demands[key][0]!=choice:raise ValueError('Consumers require incompatible producer schemas')
                aliases=asset_names.setdefault(key,{})
                for source_input in source['inputs']:
                    if source_input.get('media_type') in ('application/json','text/plain','text/markdown'):continue
                    matches=[i for i in consumer['inputs'] if same_source(i,source_input)]
                    if len(matches)>1:raise ValueError('Ambiguous consumer asset binding')
                    if not matches:continue
                    old=source_input['path'];new=matches[0]['path']
                    if old in aliases and aliases[old]!=new:raise ValueError('Consumers require incompatible asset paths')
                    aliases[old]=new
                demands[key]=(choice,source,consumer,item)
    for (ident,output),(choice,source,consumer,item) in demands.items():
        if source.get('records'):continue
        if source.get('operation_contract'):raise ValueError('One producer cannot own multiple structured projections')
        maximum=min(source['limits']['tool_calls'],executors.request_limit(source))-2
        if maximum<1:raise ValueError('Producer has no capacity for fragments and completion')
        params=copy.deepcopy(source.pop('content_parameters',{}))
        aliases=asset_names.get((ident,output),{})
        paths=[aliases.get(i['path'],i['path']) for i in source['inputs']]
        if len(set(paths))!=len(paths) or set(paths)&{o['path'] for o in source['outputs']}:raise ValueError('Consumer asset paths conflict with the producer workspace')
        for source_input,path in zip(source['inputs'],paths):source_input['path']=path
        family,target=choice
        if family=='operation.preparation':
            if params:raise ValueError('Operation preparation parameters are code owned; submit content through fragment tools')
            spec=prepared_schemas.REGISTRY[target];bindings={}
            for field,media in spec['hash_inputs'].items():
                matches=[i for i in consumer['inputs'] if i.get('media_type')==media]
                if len(matches)!=1:raise ValueError('Preparation requires one exact baseline: '+field)
                existing=[i for i in source['inputs'] if same_source(i,matches[0])]
                if len(existing)!=1:raise ValueError('Preparation worker must declare the same exact baseline as its consumer')
                bindings[field]=existing[0]['path']
            source['operation_contract']=dict(id=family,version=1,output=output,
                parameters=dict(target=target,max_records=min(maximum*contracts.REGISTRY['operation.preparation',1]['batch'],100),hash_bindings=bindings))
            if len(source['outputs'])!=1:raise ValueError('Split a structured preparation from unrelated output work')
            source['outputs'][0]['content_contract']=dict(id=family,version=1)
        else:
            registered=contracts.REGISTRY[family,1];interface=registered.get('planning_interface')
            if not interface:raise ValueError('This content family requires its registered producer intent')
            refs={}
            for field in interface['input_parameters']:
                path=consumer.get('execution',{}).get('parameters',{}).get(field)
                candidates=[i for i in consumer['inputs'] if i['path']==path] if path else []
                matches=[i for i in source['inputs'] if any(same_source(i,c) for c in candidates)]
                if field=='source_path' and not candidates:
                    matches=[i for i in source['inputs'] if i.get('media_type') in ('text/plain','text/markdown','application/json','image/png')
                             and not i['path'].startswith('operation-support/')]
                if len(matches)!=1:raise ValueError('Declare the exact '+field+' evidence input on the producer and consumer')
                refs[field]=reference(matches[0])
            if interface.get('producer_defaults'):
                params={**interface['producer_defaults'](source,maximum),**params}
            else:
                inherited=consumer.get('execution',{}).get('parameters',{})
                params={**{k:inherited[k] for k in interface['schema']['properties'] if k in inherited},**params}
                missing=set(interface['schema']['required'])-set(params)
                if missing:raise ValueError('Producer needs semantic content_parameters (not JSON structure): '+', '.join(sorted(missing)))
            source['records']=dict(family=dict(id=family,version=1),inputs=refs,parameters=params)
            if interface.get('review_mode')!='structural' and len(source['outputs'])==1:
                from pathlib import PurePosixPath
                summary=str(PurePosixPath(output).with_suffix('.md'))
                if summary==output or summary in {i['path'] for i in source['inputs']}:raise ValueError('Code-owned summary path conflicts with the assignment')
                source['outputs'].append(dict(path=summary,purpose='Code-generated content summary',media_type='text/markdown'))
        # The registered file writer owns the bytes. Never grant Python simply
        # because a model selected a code worker for serialization.
        if workers:
            # These compiler-supplied checker files served the former Python
            # preparation path. Validators now run inside the registered writer.
            source['inputs']=[i for i in source['inputs'] if not i['path'].startswith('operation-support/')]
            if evidence_binder:evidence_binder(source)
            from .owner_intents import worker_requirements
            source.pop('tools',None);source['worker']=dict(requires=worker_requirements(source) if source.get('artifact_roles') else ['files.text'])
            eligible=[w for w in workers if w['backend']['type'] in (*executors.FILE_TYPES,'codex-cli')]
            worker_capabilities.resolve(source,eligible,plan['backend'])
        elif not (source.get('tools')==['files'] or plan['backend']['type']=='codex-cli' and source.get('tools')==['files','shell']):
            raise ValueError('Structured preparation requires a compatible declared-file worker')
        elif not source.get('worker'):
            source['worker']=dict(requires=['files.text'])
            worker_capabilities.resolve(source,[worker_capabilities.entry(plan['backend'])],plan['backend'])
        receipts.append(dict(producer=ident,output=output,consumer=consumer['id'],contract=family,
            target=target,source='registered consumer input',allowance_increased=False,
            asset_paths={k:v for k,v in aliases.items() if k!=v}))
    if any('content_parameters' in t and t['id'] in editable for t in tasks):raise ValueError('Content parameters require a registered consuming port')
    if prepare_records:
        receipts.extend(prepare_records(plan) or [])
        tasks=plan['tasks'];by_id={t['id']:t for t in tasks}
    from task_relay.record_planning import bind
    bind(dict(tasks=tasks,backend=plan['backend']),version=2,workers=workers,evidence_binder=evidence_binder,review_policy=review_policy)
    for task in tasks:
        if task['id'] in editable and task.get('operation_contract'):
            if workers and not task.get('tools'):
                eligible=[w for w in workers if w['backend']['type'] in (*executors.FILE_TYPES,'codex-cli')]
                worker_capabilities.resolve(task,eligible,plan['backend'])
            backend=task.get('worker',{}).get('backend',plan['backend'])
            if backend['type'] in executors.API_TYPES:
                for key,ceiling in executors.limits_for(backend,task).items():
                    if key in task['limits']:task['limits'][key]=min(task['limits'][key],ceiling)
            contracts.validate_assignment({**task,'backend':task.get('worker',{}).get('backend',plan['backend'])})
    for consumer in tasks:
        capability=consumer.get('execution',{}).get('capability')
        if not capability:continue
        for demand in requirements(capability):
            if demand['kind']!='records':continue
            for item in selected(consumer,demand):
                if 'from_task' not in item:continue
                source=producer(item['from_task'])
                if source.get('execution',{}).get('capability') in demand.get('native',[]):continue
                actual=contracts.output_contract(source,item['output'])
                if not actual or actual['id'] not in demand['families']:raise ValueError('Producer did not bind the required record output')
    from .host_script import bind_preparers
    bind_preparers(plan, editable=editable)
    return receipts


def semantic_schema():
    from .operation_contracts import REGISTRY
    from .layout_contract import PARAMETERS
    return dict(anyOf=[{**PARAMETERS,'required':[]},REGISTRY['collection.options',1]['planning_interface']['schema'],
                       REGISTRY['collection.subjects',1]['planning_interface']['schema']])


INSTRUCTIONS='''For structured tool handoffs declare the producer and consumer together with exact input/output references. Code binds the producer to the consumer's registered schema automatically. Do not write JSON envelopes or ask a worker to discover schemas or run supplied checker scripts. Optional content_parameters specify only semantic field definitions, counts or layout title/style; family, paths, versions and baseline hashes are code-owned. Collection content still needs its independent reviewer and exact source evidence. Native source packs, image observations and verification receipts must come from their actual tool/browser producers, never fabricated JSON. Saved untyped results need a new preparation assignment; historical assignments are immutable. Preparing host checks does not grant permission to execute scripts.'''


def validate_content(task,read):
    """Identical registered preparation validation at admission and dispatch."""
    from .research_quality import load_json
    from . import layout_contract
    for demand in requirements(task['execution']['capability']):
        for item in selected(task,demand):
            if demand['kind'] not in ('preparation','records'):continue
            raw=read(item['path'])
            if raw is None:continue
            doc=load_json(raw)
            if demand.get('families')==['collection.subjects','sourcing.inventory']:
                from .subject_contract import validate_input
                validate_input(doc)
            elif demand['kind']=='preparation':
                target=demand['target'];prepared_schemas.validate(target,doc,{i['path']:i.get('media_type') for i in task['inputs']})
                for field,media in prepared_schemas.REGISTRY[target]['hash_inputs'].items():
                    matches=[i for i in task['inputs'] if i.get('media_type')==media]
                    if len(matches)!=1:raise ValueError('Missing exact native baseline')
                    baseline=read(matches[0]['path'])
                    if baseline is not None:
                        import hashlib
                        if doc[field]!=hashlib.sha256(baseline).hexdigest():raise ValueError('Prepared baseline hash differs from the exact consumer input')
            elif demand['families']==['document.layout']:
                # Historical native collection projections use renderer v1.
                from .pptx_document import validate,expand
                if doc.get('version')==2:layout_contract.validate_document(doc)
                else:
                    expanded=expand(doc)
                    validate(expanded,[e['path'] for s in expanded['slides'] for e in s['elements'] if e.get('type')=='image'])
