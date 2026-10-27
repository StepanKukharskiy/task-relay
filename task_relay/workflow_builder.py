"""Compile semantic workflow outputs and uses into the existing stage contract."""
import copy
from orchestrator import contracts as c
from orchestrator.handoff_contracts import ContractError,compile_workflow,operation

FORMATS={'text':'text/plain','markdown':'text/markdown','json':'application/json',
         'csv':'text/csv','python':'text/x-python','png':'image/png','jpeg':'image/jpeg',
         'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','html':'text/html','svg':'image/svg+xml',
         'mp4':'video/mp4','mp3':'audio/mpeg','wav':'audio/wav',
         'zip':'application/zip','gh':'application/vnd.grasshopper','ghx':'application/vnd.grasshopper','3dm':'application/vnd.rhino','blend':'application/x-blender',
         'skp':'application/vnd.sketchup.skp','pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
INSTRUCTIONS='''For new plan_pipeline actions use stage_details instead of stages or
contract_version. Keep kind, title and planning_only. Each detail has id,
instruction, route, gate, capabilities, optional visual_intent, outputs and uses.
Optional design_intent:true enables a cited design brief for a production stage.
For unresolved design form, keep a representative geometric prototype and its
visual selection before full development; pass the actual model and preview onward.
outputs is keyed by semantic deliverable ID. Each value has description and either
format (FORMAT_NAMES),
or operation plus port (an exact output key from the captured operation catalog;
use port="result" only for an operation with a single output_type).
Optional content_contract {id,version} names a registered JSON content type: research.candidates, research.batch, research.audit or geometry.specification, version 1. A uses entry can require content_contract explicitly; incompatible sources fail before dispatch. Do not label posts-only evidence as a candidate ledger.
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
format tooling. For verbatim delivery of a reviewed production text output, the final ungated conversation stage may declare report_source:{stage:earlier_stage_id,output:output_id}, with one matching text output and an explicit context use of that source. Relay reads the reviewed artifact without a model summary; keep the file within 10000 characters and 40000 bytes. Legacy stages remain readable; use this builder for new proposals.'''
INSTRUCTIONS=INSTRUCTIONS.replace('FORMAT_NAMES',', '.join(FORMATS))
from .delivery_completion import INSTRUCTIONS as DELIVERY_INSTRUCTIONS
INSTRUCTIONS+='\n'+DELIVERY_INSTRUCTIONS
from .research_campaign import INSTRUCTIONS as CAMPAIGN_INSTRUCTIONS
INSTRUCTIONS+='\n'+CAMPAIGN_INSTRUCTIONS
INSTRUCTIONS+='\nFor new source-backed sourcing catalogs, declare content_contract:{id:"sourcing.options",version:1} on the JSON catalog output. This binds typed item checkpoints and an independent sourcing.review worker; it is not an arbitrary JSON writing task. Preserve separate pixel-level visual inspection where requested. Source-derived fields and the catalog/schedule are assembled by code.'
INSTRUCTIONS+='\nFor subject-neutral saved-source collection use collection.options version 1 and task.records with configurable field definitions and exact subject/source ports. collection.review provides independent version-bound judgments, records.merge composes reviewed partitions, images.catalog fetches observed page images, and collection.slides projects exact records into presentation data. These operations share their engine and adapters with historical sourcing contracts; plants, products and other entity schemas are data configurations. Original count/source/provider policies remain binding.'
INSTRUCTIONS+='\nFor new visual room inventory, declare content_contract:{id:"sourcing.inventory",version:1}; workers submit visual fragments and code assigns IDs, normalized boxes and file structure. For PPTX delivery, sourcing.slides is a local companion to pptx.create: it assembles a typed inventory/catalog with exact saved sources, original PNG and optional photo ZIP into slide JSON. Bind the same image/photo versions to pptx.create and retain specification/final visual reviews. Automatic workflows use no invented selection gate. Historical untyped stages retain their original contracts.'
INSTRUCTIONS+='\nPrefer registered code connectors for already observed data. images.products extracts literal photo references from the exact typed catalog and product-page source pack; use browser image discovery only when recorded references are missing. Its inputs are inventory/catalog/source-pack JSON, and its count_policy target allows honest partial or empty photo coverage. For PPTX review the compiler adds pptx.render under the registered companion contract; choose a code-capable final reviewer and reserve space for that helper. Registered parameter_schema and output ports are authoritative; the model chooses compatible stages and supplies semantic fragments, not schema serialization or mechanical URL/hash checks.'


def schema(operation_ids=None):
    from .planning_contract import obj,array
    if operation_ids is None:
        from orchestrator.execution import REGISTRY
        operation_ids=list(REGISTRY)
    text={'type':'string'}
    capability={'type':'string','enum':list(operation_ids)}
    from orchestrator.operation_contracts import REGISTRY as CONTENT_CONTRACTS
    content={'anyOf':[obj({'id':{'type':'string','enum':[ident]},'version':{'type':'integer','enum':[version]}},('id','version'))
                      for ident,version in CONTENT_CONTRACTS]}
    extra={'content_contract':content,'description':text,'max_bytes':{'anyOf':[{'type':'integer'},{'type':'null'}]},
           'slides':{'anyOf':[{'type':'integer'},{'type':'null'}]},'together':text}
    output={'anyOf':[obj({**extra,'format':{'type':'string','enum':list(FORMATS)}},('description','format')),
                     obj({**extra,'operation':capability,'port':text},('description','operation','port'))]}
    detail=obj({'id':text,'instruction':text,'route':{'type':'string','enum':['conversation','production','browser_research','image']},
        'gate':{'type':'string','enum':['none','choice','selection']},'capabilities':array(capability),
        'visual_intent':{'type':'string','enum':['reference','synthetic']},'outputs':obj({},additional=output),
        'design_intent':{'type':'boolean'},
        'report_source':obj({'stage':text,'output':text},('stage','output')),
        'research_mode':{'type':'string','enum':['suggest','none','sources']},
        'uses':array(obj({'stage':text,'output':text,'consumer':text,'content_contract':content},('stage','output','consumer')))},
        ('id','instruction','route','gate','capabilities','outputs','uses'))
    from .research_campaign import schema as campaign_schema
    from .delivery_completion import schema as completion_schema
    return obj({'kind':{'type':'string','enum':['plan_pipeline']},'title':text,'planning_only':{'type':'boolean'},'research_campaign':campaign_schema(),'completion':completion_schema(),
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
    from .research_campaign import slots
    stages=slots(action['research_campaign']) if 'research_campaign' in action else []
    seen={s['id']:s for s in stages};operations={};implicit=[]
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
        for cap in stage['capabilities']:
            selected=selected_operation(cap)
            for companion in selected.get('companions',{}):
                if companion not in saved:continue  # Legacy captured catalogs keep their original readiness scope.
                ready=selected_operation(companion)
                if not saved[companion].get('available'):
                    raise ContractError('unavailable_companion','Required review companion is unavailable before dispatch: '+companion)
        outputs={};groups={}
        for ident,item in detail['outputs'].items():
            if 'operation' in item:
                cap=item['operation']
                if cap not in stage['capabilities'] and cap in saved:
                    selected_operation(cap);stage['capabilities'].append(cap)
                    implicit.append(dict(stage=stage['id'],capability=cap,reason='explicit_output_operation'))
                if cap not in stage['capabilities'] or cap not in saved:
                    raise ContractError('missing_producer','Output operation must be captured and selected in this stage.')
                spec=selected_operation(cap)
                ports=spec.get('outputs') or {'result':spec.get('output_type')}
                media=ports.get(item['port'])
                if not media:raise ContractError('missing_output','Choose an exact captured operation output port.')
            else:media=FORMATS[item['format']]
            outputs[ident]={'media_type':media,**{k:item[k] for k in ('max_bytes','slides','content_contract') if k in item}}
            if 'together' in item:
                if not item['together'].strip():raise ContractError('invalid_companions','Companion group needs a name.')
                groups.setdefault(item['together'],[]).append(ident)
        for members in groups.values():
            for ident in members:outputs[ident]['companions']=[m for m in members if m!=ident]
        uses=[]
        for ref in detail['uses']:
            source=seen.get(ref['stage'],{}).get('handoff',{}).get('outputs',{}).get(ref['output'])
            if not source:raise ContractError('missing_source','Select an exact earlier-stage output; forward references are not allowed.')
            edge=dict(stage=ref['stage'],deliverable=ref['output'],consumer=ref['consumer'],media_type=source['media_type'])
            if 'content_contract' in ref:edge['content_contract']=copy.deepcopy(ref['content_contract'])
            uses.append(edge)
        stage['deliverables']={k:v['description'] for k,v in detail['outputs'].items()}
        stage['handoff']=dict(outputs=outputs,inputs=uses)
        stages.append(stage);seen[stage['id']]=stage
    compile_workflow(stages,catalog,True)
    value={k:copy.deepcopy(v) for k,v in action.items() if k!='stage_details'}
    value.update(contract_version=1,stages=stages)
    derived_completion=False
    if 'completion' not in value and stages[-1]['route']=='production' and all(s['gate']=='none' for s in stages):
        pptx=[ident for ident,output in stages[-1]['handoff']['outputs'].items() if output['media_type']==FORMATS['pptx']]
        if len(pptx)==1:
            value['completion']=dict(version=1,stage=stages[-1]['id'],output=pptx[0])
            derived_completion=True
    receipt=dict(version=1,request=copy.deepcopy(action),compiled_sha256=c.digest(value),
                 operation_sha256={k:c.digest(v) for k,v in operations.items()})
    if derived_completion:receipt['derived_completion']=copy.deepcopy(value['completion'])
    if implicit:receipt['implicit_worker_abilities']=implicit
    return value,receipt
