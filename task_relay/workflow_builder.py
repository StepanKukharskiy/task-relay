"""Compile semantic workflow outputs and uses into the existing stage contract."""
import copy
from orchestrator import contracts as c
from orchestrator.handoff_contracts import ContractError,compile_workflow,operation

FORMATS={'text':'text/plain','markdown':'text/markdown','json':'application/json',
         'csv':'text/csv','python':'text/x-python','png':'image/png','jpeg':'image/jpeg',
         'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','html':'text/html','svg':'image/svg+xml',
         'mp4':'video/mp4','mp3':'audio/mpeg','wav':'audio/wav',
         'zip':'application/zip','3dm':'application/vnd.rhino','blend':'application/x-blender',
         'skp':'application/vnd.sketchup.skp','pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
INSTRUCTIONS='''For new plan_pipeline actions use stage_details instead of stages or
contract_version. Keep kind, title and planning_only. Each detail has id,
instruction, route, gate, capabilities, optional visual_intent, outputs and uses.
outputs is keyed by semantic deliverable ID. Each value has description and either
format (FORMAT_NAMES),
or operation plus port (an exact output key from the captured operation catalog;
use port="result" only for an operation with a single output_type).
Optional max_bytes and slides retain exact requested bounds/quantities; never lower
or omit a requested quantity to fit a limit. Optional together is a group name for
outputs which must travel together. All members of that group become companions.
uses is a list of {stage: earlier stage ID, output: its output ID, consumer: context
or a selected capability}. Select every required companion explicitly; no omitted
input is added silently. Relay derives media types, handoff shapes and contract_version.
Do not include deliverables, handoff, MIME types or contract_version in this form.
Keep explicit human gates and stage scope. No conversions or provider substitutions
are inferred. capabilities lists registered graph operation IDs only; use [] for
ordinary writing, editing and review. files.text is implicit in agent workers,
not an operation. Other worker abilities are resolved during stage planning.
Format selection is a deliverable requirement, not proof of installed
format tooling. Legacy stages remain readable; use this builder for new proposals.'''
INSTRUCTIONS=INSTRUCTIONS.replace('FORMAT_NAMES',', '.join(FORMATS))


def schema(operation_ids=None):
    from .planning_contract import obj,array
    if operation_ids is None:
        from orchestrator.execution import REGISTRY
        operation_ids=list(REGISTRY)
    text={'type':'string'}
    capability={'type':'string','enum':list(operation_ids)}
    extra={'description':text,'max_bytes':{'anyOf':[{'type':'integer'},{'type':'null'}]},
           'slides':{'anyOf':[{'type':'integer'},{'type':'null'}]},'together':text}
    output={'anyOf':[obj({**extra,'format':{'type':'string','enum':list(FORMATS)}},('description','format')),
                     obj({**extra,'operation':capability,'port':text},('description','operation','port'))]}
    detail=obj({'id':text,'instruction':text,'route':{'type':'string','enum':['conversation','production','browser_research','image']},
        'gate':{'type':'string','enum':['none','choice','selection']},'capabilities':array(capability),
        'visual_intent':{'type':'string','enum':['reference','synthetic']},'outputs':obj({},additional=output),
        'uses':array(obj({'stage':text,'output':text,'consumer':text},('stage','output','consumer')))},
        ('id','instruction','route','gate','capabilities','outputs','uses'))
    return obj({'kind':{'type':'string','enum':['plan_pipeline']},'title':text,'planning_only':{'type':'boolean'},
                'stage_details':array(detail)},('kind','title','planning_only','stage_details'))


def build(action,snapshot):
    if not isinstance(action,dict) or action.get('kind')!='plan_pipeline' or 'stage_details' not in action:
        return action,None
    from .planning_contract import validate
    # Older saved proposals can redundantly declare the baseline text ability.
    # It grants no operation or extra tools; retain the declaration in the receipt.
    accepted=schema()
    accepted['properties']['stage_details']['items']['properties']['capabilities']['items']={
        'type':'string','enum':accepted['properties']['stage_details']['items']['properties']['capabilities']['items']['enum']+['files.text']}
    validate(action,accepted)
    catalog=snapshot.get('capabilities',{}).get('graph_operations',[]);saved={o['id']:o for o in catalog}
    stages=[];seen={};operations={};implicit=[]
    def selected_operation(cap):
        if cap not in saved:raise ContractError('missing_producer','Operation must be captured in the workflow request.')
        spec=operation(cap,saved[cap])
        if any(spec.get(k)!=saved[cap].get(k) for k in ('outputs','output_type')):
            raise ContractError('operation_changed','Output contract changed since the workflow request was captured.')
        operations[cap]=copy.deepcopy(spec)
        return spec
    for detail in action['stage_details']:
        stage={k:copy.deepcopy(v) for k,v in detail.items() if k not in ('outputs','uses')}
        if stage['id'] in seen:raise ContractError('duplicate_stage','Duplicate workflow stage ID.')
        if len(set(stage['capabilities']))!=len(stage['capabilities']):
            raise ContractError('duplicate_capability','Duplicate workflow stage capability.')
        if 'files.text' in stage['capabilities']:
            if stage['route']!='production':
                raise ContractError('invalid_worker_requirement','The implicit text worker ability applies only to production stages.')
            stage['capabilities'].remove('files.text')
            implicit.append({'stage':stage['id'],'capability':'files.text','reason':'baseline_agent_ability'})
        for cap in stage['capabilities']:selected_operation(cap)
        outputs={};groups={}
        for ident,item in detail['outputs'].items():
            if 'operation' in item:
                cap=item['operation']
                if cap not in stage['capabilities'] or cap not in saved:
                    raise ContractError('missing_producer','Output operation must be captured and selected in this stage.')
                spec=selected_operation(cap)
                ports=spec.get('outputs') or {'result':spec.get('output_type')}
                media=ports.get(item['port'])
                if not media:raise ContractError('missing_output','Choose an exact captured operation output port.')
            else:media=FORMATS[item['format']]
            outputs[ident]={'media_type':media,**{k:item[k] for k in ('max_bytes','slides') if k in item}}
            if 'together' in item:
                if not item['together'].strip():raise ContractError('invalid_companions','Companion group needs a name.')
                groups.setdefault(item['together'],[]).append(ident)
        for members in groups.values():
            for ident in members:outputs[ident]['companions']=[m for m in members if m!=ident]
        uses=[]
        for ref in detail['uses']:
            source=seen.get(ref['stage'],{}).get('handoff',{}).get('outputs',{}).get(ref['output'])
            if not source:raise ContractError('missing_source','Select an exact earlier-stage output; forward references are not allowed.')
            uses.append(dict(stage=ref['stage'],deliverable=ref['output'],consumer=ref['consumer'],media_type=source['media_type']))
        stage['deliverables']={k:v['description'] for k,v in detail['outputs'].items()}
        stage['handoff']=dict(outputs=outputs,inputs=uses)
        stages.append(stage);seen[stage['id']]=stage
    compile_workflow(stages,catalog,True)
    value={k:copy.deepcopy(v) for k,v in action.items() if k!='stage_details'}
    value.update(contract_version=1,stages=stages)
    receipt=dict(version=1,request=copy.deepcopy(action),compiled_sha256=c.digest(value),
                 operation_sha256={k:c.digest(v) for k,v in operations.items()})
    if implicit:receipt['implicit_worker_abilities']=implicit
    return value,receipt
