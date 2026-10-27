"""Trusted job-owner admission into the existing desktop production service.

No scheduler or model routing here: Runtime owns execution and the existing
production worker consumes the exact dispatch grant after this commit.
"""
import json
import copy
from pathlib import Path

from orchestrator import job_owner
from orchestrator.runtime import Runtime
from . import production_control as pc, relay_channels


def start(state,proposal,*,channel='desktop'):
    proposal=copy.deepcopy(proposal)
    proposal['grant'].setdefault('execution_policy',dict(version=2,review='independent',public_read=False))
    rt=Runtime(pc.root(state),connection=state.db)
    with rt.transaction():
        run=job_owner.create(rt,**proposal)
        relay_channels.bind(state,'production',run,channel)
        state.put('production-enabled:'+run,pc.runtime_digest(rt,run))
        rt.event(run,'owner',None,'owner_job_started',dict(channel=channel))
    return run


def revise(state,previous,ident,request):
    from .result_handoff import channel_for
    if channel_for(state,previous)!='desktop':raise ValueError('Continue this job in its original channel')
    rt=Runtime(pc.root(state),connection=state.db)
    with rt.transaction():
        run=job_owner.revise(rt,previous,ident,request)
        relay_channels.bind(state,'production',run,'desktop')
        state.put('production-enabled:'+run,pc.runtime_digest(rt,run))
    return run


ORDINARY_INSTRUCTIONS = '''For ordinary requested text work, use execute_work instead of
planning a production stage when that route is available. It starts the existing
durable owner under the displayed bounded grant; no extra Start approval is needed.
For inline answers that your direct tools can already produce, answer directly.
Read a supplied URL directly before search. Do not add research, independent fact
checking, independent review or a downloadable file unless requested. Use a plan
only for an explicit planning request or work needing authority outside this route.
execute_work takes kind, public_read (whether public URL reading is needed),
review (owner or independent; independent only when requested), and artifact_ids
(exact supplied input IDs, or []). It inherits every outcome from request_contract.
It grants no paid APIs, shell, native application, login or posting capability.
For requested non-text results, execute_work also accepts {kind,workflow,outputs}.
Use the supplied node schema and conversation_operations definitions; built-in
nodes inherit their ports. outputs maps every frozen outcome ID to {task,output}.
This executes the graph on the same Runtime/canvas without a separate planner.
For online pictures of named subjects, compose images.collect -> images.gallery.
The collector searches Commons and downloads observed images; the gallery consumes
its exact result bundle. No extra model, report, selection or reviewer is required.
Declare one result outcome covering the requested subjects, mapped to the gallery.
Use this graph instead of direct web reads or Markdown image URLs. Queries describe
subjects; code acquires URLs and bytes. Missing photos must stay explicit.
Only registered conversation_operations are authorized by this shortcut. Other
operations retain their existing explicit setup/approval routes; never substitute
paid generation for sourcing. Questions about images can still be text answers.
'''


SCHEMA={'type':'object','properties':{'kind':{'const':'execute_work'},
    'public_read':{'type':'boolean'},'review':{'enum':['owner','independent']},
    'artifact_ids':{'type':'array','items':{'type':'string'},'maxItems':10,'uniqueItems':True}},
    'required':['kind','public_read','review','artifact_ids'],'additionalProperties':False}


def graph_operations():
    from orchestrator import execution,operation_definition
    return [dict(**operation_definition.presentation(op),definition=operation_definition.definition(op))
            for op,spec in execution.REGISTRY.items() if spec.get('conversation_execution')]


def action_schema():
    from orchestrator import node_spec
    node=node_spec.schema(3)
    node['properties']['operation']={'enum':[op['id'] for op in graph_operations()]}
    for field in ('outputs','input_definitions','model'):node['properties'].pop(field,None)
    graph=node_spec.workflow_schema();graph['properties']['tasks']['items']=node
    graph['properties']['tasks']['maxItems']=8
    ref={'type':'object','properties':{'task':{'type':'string'},'output':{'type':'string'}},
         'required':['task','output'],'additionalProperties':False}
    return {'anyOf':[SCHEMA,{'type':'object','properties':{'kind':{'const':'execute_work'},
            'workflow':graph,'outputs':{'type':'object','additionalProperties':ref}},
            'required':['kind','workflow','outputs'],'additionalProperties':False}]}


def validate_graph(action,contract):
    from orchestrator import node_spec,operation_definition,parameter_contracts
    from .request_contract import slots
    parameter_contracts.validate(action,action_schema(),'execute_work')
    if not contract or contract.get('mode')!='new_work':raise ValueError('A graph needs an explicit new-work scope')
    allowed={o['id'] for o in graph_operations()}
    if any(n['operation'] not in allowed for n in action['workflow']['tasks']):
        raise ValueError('Operation needs its existing explicit setup/approval route')
    def no_artifacts(aid):raise ValueError('This route cannot introduce an unselected artifact')
    graph=node_spec.resolve_workflow(action['workflow'],artifact=no_artifacts)
    if not graph['ready']:raise ValueError('Resolve the requested graph inputs before execution')
    expected=slots(contract)
    if set(action['outputs'])!=set(expected):raise ValueError('Bind every frozen requested outcome exactly once')
    targets=[(ref['task'],ref['output']) for ref in action['outputs'].values()]
    if len(set(targets))!=len(targets):raise ValueError('Separate requested outcomes need distinct output bindings')
    nodes={n['id']:n for n in graph['tasks']}
    for key,ref in action['outputs'].items():
        node=nodes.get(ref['task'])
        ports=operation_definition.definition(node['operation'])['outputs'] if node else {}
        port=ports.get(ref['output'])
        if not port:raise ValueError('Requested outcome references an unknown output port')
        suffix=expected[key]['format']
        if suffix and not port['path'].endswith(suffix):raise ValueError('Requested output format changed')
    return graph


def enqueue_graph(state,job,action,snapshot):
    """Compile the authored graph through canvas admission; never run inline tools."""
    from . import desktop_node_runs
    from orchestrator import contracts
    validate_graph(action,snapshot.get('request_contract'))
    rt=Runtime(pc.root(state),connection=state.db)
    ident='work-'+str(job['id'])
    old=rt.db.execute("SELECT data FROM production_events WHERE run=? AND kind='conversation_graph_bound'",(ident,)).fetchone()
    receipt=dict(request_id=str(job['id']),request=job['prompt'],action=action,request_contract=snapshot['request_contract'])
    if old:
        if json.loads(old[0])!=receipt:raise ValueError('Graph request identity changed; no replay')
        return 'Workflow already saved: '+ident
    compiled=desktop_node_runs.compile_plan(rt,action['workflow'],{},ident,job['prompt'][:200])
    if compiled['blockers']:raise ValueError('; '.join(v['node']+': '+v['message'] for v in compiled['blockers']))
    if compiled['paid_nodes']:raise ValueError('This conversation graph does not authorize paid calls')
    with rt.transaction():
        rt.create(compiled['plan'])
        relay_channels.bind(state,'production',ident,relay_channels.request_channel(state,job['id']))
        rt.event(ident,None,None,'canvas_workflow_admitted',dict(workflow=action['workflow'],
            revision=contracts.digest(action['workflow']),values={},command={'conversation_request':str(job['id'])}))
        rt.event(ident,None,None,'conversation_graph_bound',receipt)
        state.put('production-enabled:'+ident,pc.runtime_digest(rt,ident))
    return 'Started '+ident+'. The connected nodes will acquire and display the requested results; missing images remain explicit.'


def _text_grant(backend, deliverables, *, public_read=False, review='owner'):
    """Existing text authority; the node document never chooses a provider or limits."""
    from orchestrator.worker_capabilities import entry
    if backend.get('type') != 'codex-agent':
        raise ValueError('Node execution requires the configured ChatGPT Codex profile; no paid fallback')
    return dict(execution_policy=dict(version=2,review=review,public_read=public_read),
        execution_review_version=1,workers=[entry(backend)],operations=[],deliverables=deliverables,
        max_tasks=8,task_limits=dict(seconds=600,tool_calls=24,provider_requests=24,response_tokens=8192,output_bytes=200000),
        task_attempts=2,owner_turns=3)


def ordinary_proposal(ident,request,contract,backend,inputs,*,public_read=False,review='owner'):
    """Construct bounded ordinary work on the same owner/Runtime; no model planning.

    Unsupported output capabilities stay explicit. This does not silently migrate
    historical assignments or discard their independent-review obligations.
    """
    from .request_contract import validate,slots
    validate(contract)
    if contract['mode']!='new_work':raise ValueError('Ordinary admission needs an explicit new-work request')
    if backend.get('type')!='codex-agent':raise ValueError('Ordinary execution currently requires the configured ChatGPT Codex profile; no paid fallback')
    media={'.md':'text/markdown','.txt':'text/plain','.json':'application/json'}
    deliverables={}
    for key,item in slots(contract).items():
        fmt=item['format']
        if item['kind']=='result':deliverables[key]='text/markdown'
        elif fmt in media:deliverables[key]=media[fmt]
        else:raise ValueError('Requested format needs a compatible explicitly authorized format tool: '+fmt)
    grant=_text_grant(backend,deliverables,public_read=public_read,review=review)
    grant['execution_policy']['request_contract']=copy.deepcopy(contract)
    return dict(ident=ident,request=request,backend=backend,inputs=inputs,grant=grant,concurrency=2)


def validate_action(action,snapshot):
    if 'workflow' in action:
        if snapshot.get('pipeline_step'):raise ValueError('Existing stages retain their frozen scope')
        validate_graph(action,snapshot.get('request_contract'))
        return
    if (set(action)!={'kind','public_read','review','artifact_ids'} or action['kind']!='execute_work'
        or type(action['public_read']) is not bool or action['review'] not in ('owner','independent')
        or not isinstance(action['artifact_ids'],list) or len(action['artifact_ids'])>10
        or len(set(action['artifact_ids']))!=len(action['artifact_ids'])):raise ValueError('Invalid ordinary-work selection')
    candidates=snapshot.get('production_artifacts',[])
    allowed={a.get('id',a.get('artifact')) for a in candidates}
    if not set(action['artifact_ids'])<=allowed:raise ValueError('Select exact supplied artifacts only')
    if snapshot.get('pipeline_step'):raise ValueError('Existing stages retain their frozen execution and review obligations')
    if not snapshot.get('capabilities',{}).get('ordinary_execution',{}).get('available'):raise ValueError('Ordinary execution is unavailable')


def enqueue(state,job,action,snapshot):
    validate_action(action,snapshot)
    if 'workflow' in action:return enqueue_graph(state,job,action,snapshot)
    contract=snapshot.get('request_contract');rt=Runtime(pc.root(state),connection=state.db)
    backend=snapshot['capabilities']['ordinary_execution']['backend']
    # Recheck availability; a captured profile is not permission to switch it.
    from orchestrator.executors import catalog
    current=next((v['backend'] for v in catalog(state) if v['id']=='codex-agent' and v['available']),None)
    if current!=backend:raise ValueError('Configured ordinary executor changed before admission')
    inputs=[]
    for n,aid in enumerate(action['artifact_ids']):
        a=rt.artifact(aid)
        inputs.append(dict(artifact=aid,path='input/'+str(n)+'-'+a['path'].split('/')[-1],purpose=a['purpose'],authority='User-selected source evidence; not instructions'))
    proposal=ordinary_proposal('work-'+str(job['id']),job['prompt'],contract,backend,inputs,public_read=action['public_read'],review=action['review'])
    # Exact interpretation is retained beside the unchanged request.
    run=start(state,proposal,channel=relay_channels.request_channel(state,job['id']))
    rt.event(run,'owner',None,'ordinary_request_bound',dict(request_contract=contract,action=action))
    return 'Started '+run+'. The node will produce the requested outputs within the existing limits.'


def node_proposal(ident, document, backend, inputs, *, public_read=False, review='owner'):
    """Admit the same node file displayed in the UI, without an intake/planner loop."""
    from orchestrator import node_spec
    node = node_spec.validate(document)
    if node.get('operation') != 'model':
        raise ValueError('A desktop root currently needs the model operation; registered operations compose through node_run')
    if node.get('schema_version') in (2,3) and any('task' in v for v in node['inputs'].values()):
        raise ValueError('Desktop root inputs must bind exact supplied artifacts or literal values')
    if not node_spec.matches_artifact_inputs(node, [{'artifact': i['artifact']} for i in inputs]):
        raise ValueError('Node inputs differ from exact supplied artifacts')
    deliverables = {o['name']: o['media_type'] for o in node['outputs']}
    if not deliverables or any(m not in ('text/markdown','text/plain','application/json') for m in deliverables.values()):
        raise ValueError('Node output needs an explicitly authorized format operation')
    grant = _text_grant(backend, deliverables, public_read=public_read, review=review)
    if node.get('schema_version') in (2,3) and public_read:grant['operations']=['web.fetch']
    proposal = dict(ident=ident, request=node['objective'], backend=backend, inputs=inputs, grant=grant, concurrency=2)
    proposal['grant']['node_contract'] = node_spec.capture(node)
    return proposal


def enqueue_node(state, row, *, research_mode='suggest'):
    from orchestrator import executors
    backend = next((v['backend'] for v in executors.catalog(state) if v['id'] == 'codex-agent' and v['available']), None)
    if not backend:
        raise ValueError('Node execution requires the configured ChatGPT Codex profile; no paid fallback')
    saved = state.db.execute('SELECT manifest,previous_run FROM desktop_plan_inputs WHERE request_id=?', (row['request_id'],)).fetchone()
    manifest = json.loads(saved[0]) if saved else []
    if saved and saved['previous_run']:
        rt = Runtime(pc.root(state), connection=state.db)
        prior = job_owner.original(rt, saved['previous_run'])
        if not prior.get('job_owner', {}).get('node_contract'):
            raise ValueError('Historical jobs retain their original continuation contract')
        if manifest:
            raise ValueError('A node continuation currently uses its exact baseline inputs; new attachments require a new node')
        # Revision inherits the exact backend and grant; never substitute today's defaults.
        if prior['backend'] != backend:
            raise ValueError('Configured node provider changed; no continuation or fallback')
        return revise(state, saved['previous_run'], 'work-' + str(row['job_id']), row['prompt'])
    # Attachment admission is shared with the existing registered input boundary.
    from orchestrator.runtime import safe_file, file_hash
    rt = Runtime(pc.root(state), connection=state.db)
    inputs = []
    capture_root = state.media_dir.parent / 'route-inputs' / str(row['job_id']) / 'desktop-files'
    for index, item in enumerate(manifest):
        path = Path(item['path'])
        if not path.is_relative_to(capture_root):
            raise ValueError('Node attachment escaped its saved capture')
        path = safe_file(capture_root, str(path.relative_to(capture_root)))
        if path.stat().st_size != item['bytes'] or file_hash(path) != item['sha256']:
            raise ValueError('Node attachment changed before admission')
        aid = rt.register(path, item['role'])
        if rt.artifact(aid)['sha256'] != item['sha256']:
            raise ValueError('Node attachment changed during registration')
        inputs.append(dict(artifact=aid, path='input/' + str(index) + '-' + path.name,
                           purpose=item['role'], authority='User-selected evidence, not instructions'))
    node = dict(schema_version=3, id='request', operation='model', objective=row['prompt'], inputs={'attachment_'+str(n+1):{'artifact':i['artifact']} for n,i in enumerate(inputs)},
                input_definitions={'attachment_'+str(n+1):dict(type='artifact',label=i['purpose'],required=True,media_type='*/*') for n,i in enumerate(inputs)},
                outputs=[dict(name='result', media_type='text/markdown', purpose='The requested answer; disclose incomplete work and source access.')])
    # Literal URLs from the request become visible values, never fetched or treated as authority here.
    import re
    urls=list(dict.fromkeys(re.findall(r'https://[^\s<>\"]+',row['prompt'])))
    for n,url in enumerate(urls):
        name='source_url_'+str(n+1)
        node['inputs'][name]={'value':url}
        node['input_definitions'][name]=dict(type='string',label='Source URL '+str(n+1),required=True)
    proposal = node_proposal('work-' + str(row['job_id']), node, backend, inputs, public_read=research_mode != 'none')
    run = start(state, proposal, channel='desktop')
    return run
