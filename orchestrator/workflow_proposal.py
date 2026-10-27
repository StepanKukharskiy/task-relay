"""Workflow replies through the existing typed record commit/correction path."""
import copy
import hashlib
import json
from . import parameter_contracts


REPLY_CONTRACT_VERSION = 5
ROUTING_RULES = (
    'Classify the user request with kind: work, answer, or clarification. '
    'A request to create or edit a deliverable is work, even when phrased as a question '
    '(for example, "Can you help me write a post from this text?"). '
    'Work MUST include a workflow with at least one editable node; never put the finished deliverable only in message. '
    'Finding/showing online pictures is work even without a requested file format. Use registered acquisition and gallery nodes, '
    'not prose Markdown image URLs. images.collect searches public Commons and acquires literal source images; '
    'images.gallery displays its exact bundle and needs no advisory report unless requested. Do not add reviewers or generation. '
    'Use the smallest useful graph: a writing task needs one model node with the supplied source text as a named input, '
    'editable instructions, and a named text output. Preserve the supplied text exactly as data; do not add publication or sending nodes unless requested. '
    'Use answer only for explanations, advice, or discussion about Relay or existing results that do not request creating/changing a deliverable. '
    'Use clarification only when essential information is missing. Answer and clarification have workflow:null. '
    'The message explains the proposed work or asks the missing question. '
    'For contexts with reply_contract_version=2, kind is required. Never execute the proposed graph. '
)


def authoring_schema():
    from . import node_spec
    from .operation_definition import catalog
    model=node_spec.schema(3);model['properties']['operation']={'type':'string','enum':['model']}
    model['required']=list(dict.fromkeys(model['required']+['input_definitions','outputs']))
    registered=node_spec.schema(3)
    registered['properties']['operation']={'type':'string','enum':[r['id'] for r in catalog() if r['id']!='model']}
    for field in ('outputs','input_definitions'):registered['properties'].pop(field,None)
    registered['description']='Built-in operations inherit inputs and output ports from their definitions. Never declare outputs or input_definitions here.'
    schema=node_spec.workflow_schema();schema['properties']['tasks']['items']={'anyOf':[model,registered]}
    return schema


def schema(parameters=None):
    return dict(type='object',properties=dict(kind=dict(type='string',enum=['work','answer','clarification'],description='Request classification. Required by reply_contract_version 2; omission is retained only for historical contexts.'),message=dict(type='string',minLength=1,maxLength=4000),
        workflow=dict(anyOf=[dict(type='null'),authoring_schema()])),required=['message','workflow'],additionalProperties=False)


def context(frozen,read):
    path=frozen['operation_contract']['parameters']['context_path']
    item=next(i for i in frozen['inputs'] if i['path']==path);raw=read(path)
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Chat context changed')
    return json.loads(raw)


def record(value,parameters,context=None):
    from . import node_spec
    # Give an actionable node-specific diagnostic before general schema errors.
    if isinstance(value,dict) and isinstance(value.get('workflow'),dict):
        for node in value['workflow'].get('tasks',[]):
            if isinstance(node,dict) and node.get('operation')!='model' and set(node)&{'outputs','input_definitions'}:
                raise ValueError(str(node.get('id','Node'))+': '+str(node.get('operation'))+' already defines its ports. Remove outputs/input_definitions; connect using its registered output name.')
    parameter_contracts.validate(value,schema(),'chat reply')
    if (context or {}).get('reply_contract_version',1)>=2 and 'kind' not in value:
        raise ValueError('Classify this request with kind: work, answer, or clarification. Requests to create or edit a deliverable require kind:work and a nonempty workflow.')
    if value.get('kind')=='work' and value['workflow'] is None:
        raise ValueError('A work request needs a nonempty workflow. Put the writing or editing task in a model node with named inputs and output; message alone is not a canvas deliverable.')
    if value.get('kind') in ('answer','clarification') and value['workflow'] is not None:
        raise ValueError('A reply containing a graph must use kind:work. Answer and clarification use workflow:null.')

    if value['workflow'] is not None and context is not None:
        allowed=context.get('artifacts',{})
        def lookup(ident):
            if ident not in allowed:raise ValueError('Proposal references an unselected file: '+ident)
            return allowed[ident]
        view=node_spec.resolve_workflow(value['workflow'],artifact=lookup,draft=True)
        if context.get('reply_contract_version',1)>=3:
            from .producer_binding import validate_graph
            validate_graph(view,exact_baselines=context.get('reply_contract_version',1)>=5)
        if context.get('reply_contract_version',1)>=4:
            from .producer_binding import validate_model_workers
            validate_model_workers(view,context.get('model'))
    return 'reply'


def progress(store,records):
    from .operation_contracts import digest
    return dict(record_sha256=digest(records[0]) if records else None)


def document(store,records):
    if not records:return dict(message='',workflow=None)
    record(records[0],store.contract['parameters'],store.context())
    return copy.deepcopy(records[0])


def validate_assignment(task):
    p=task['operation_contract']['parameters']
    if set(p)!={'context_path','max_records'} or p['max_records']!=1:raise ValueError('Chat has one bounded reply')
    if not any(i['path']==p['context_path'] for i in task['inputs']):raise ValueError('Chat needs its exact context')
    if task.get('execution') or task.get('review_of') or len(task['outputs'])!=1:raise ValueError('Chat is one typed reply worker')


def register(registry,lifecycle):
    from .collection_core import Capacity
    registry['workflow.proposal',1]=dict(node_ui=dict(title='Plan a workflow',category='AI & text'),schema={},schema_for=schema,validate=record,batch=1,
        local_record_tool=True,validate_assignment=validate_assignment,
        validate_document=lambda value:parameter_contracts.validate(value,schema()),support_modules=('orchestrator.node_spec','orchestrator.operation_definition','orchestrator.producer_binding','orchestrator.worker_capabilities','task_relay.desktop_node_setup'),
        lifecycle=lifecycle.Lifecycle(context=context,document=document,progress=progress,require_active=True,amendable=True,
            instructions=ROUTING_RULES+'Propose graphs using the supplied authoring schema. Publish the first complete valid node/graph promptly with operation_submit so the user can see it on the canvas. As further nodes and connections become ready, update that same reply with operation_amend using the current revision and record_sha256 supplied in operation_progress. Each revision must be a valid graph with only complete nodes and resolved connections; never submit token fragments or dangling wires. Preserve existing nodes while extending the graph unless the user requested changes. Keep updates within the existing tool/provider limits; batch additions when necessary. The last committed reply is the final graph. Validation errors have no effect: fix the indicated fields and resubmit within the same remaining limits. Do not finish before a valid reply is committed. Built-in nodes inherit their output ports; only model nodes declare outputs/input_definitions. Never execute the proposed graph.'),
        planning_interface=dict(input_parameters=('context_path',),review_mode='structural',merge_operation=None,
            capacity=Capacity(inspections_per_unit=0),schema=dict(type='object',properties=dict(max_records=dict(type='integer',enum=[1])),required=['max_records'],additionalProperties=False)))
