"""Compile owner-facing task intents into the existing assignment boundary.

No dispatch, new controller or inferred authorization. Registry contracts own
ports; Runtime owns exact versions and hashes. Original intents are journaled by
the caller in the same transaction as the compiled assignments.
"""
import copy
import hashlib
import json
import mimetypes
from pathlib import PurePosixPath

from . import contracts as c, execution, parameter_contracts as schema

INSTRUCTIONS='''Complete the user's job and deliverables. Delegate substantial
work promptly using the supplied artifact references; workers can inspect the
full evidence. Read a passage yourself only when needed to decide the next task.
Use job_catalog for selected capabilities, then job_delegate with task objectives,
input references and named outputs. Connect a preparation worker to its intended
operation in the same batch: code supplies schemas, paths and exact file bindings.
For a staged script/checks producer use prepares:<registered operation> to receive
its full authoring contract without execution authority.
Use registered operations to create supported documents. Ask workers to select
content and layouts. Independent reviewers must assess the actual final files,
their evidence and rendered pages; correct their findings before job_complete.
Delegation yields automatically and returns worker outcomes to you. Continue
useful work after failures, disclose genuine gaps, and preserve prior versions.
For registered record corrections, option_id is a content-version hash and changes
with amended content. Preserve source provenance and unchanged records, not the old
ID of an amended option. Bind the corrected catalog to its exact exported source
pack and require independent review; retained source provenance is not acceptance.
Use job_wait only for running work. Stay within the given provider, permissions
and capacity. Never replay an uncertain external action or infer acceptance.'''


COMPILED_INSTRUCTIONS="""Finish the user's job. Delegate substantial work using the supplied references;
workers inspect the evidence. Read only a passage needed for a task decision.
Use job_catalog for the relevant operation or content contract. Delegate a
preparation worker and its consumer together. Choose content and suitable layouts;
code owns schemas, paths, hashes, dependencies, placement and file creation.
When catalog worker_work is available, use one work task for preparing, building,
inspecting and correcting a deliverable. For version 3 supply work:{operation,mode,
parameters,data,baseline,content_parameters} with references inside work;
code grants its registered local tools and output ports. It needs no separate preparation
or render task. Independent final review remains required.
For native operations supply operation and parameters (or data for a JSON input).
For registered content supply content; for a review supply review_of. Omit outputs
for all three: code supplies their output ports. Only an ordinary worker declares
named outputs.
For content correction, select content.baseline:{artifact:ID} (or task/output).
Omit content.parameters: code inherits every immutable semantic choice from that
exact eligible baseline. Explicit conflicts reject; new content requires choices.
An identical baseline beside content is supported. Code binds only that exact
sealed candidate; inherited older candidates remain evidence, not choices.
Owner state identifies verified correction_checkpoint candidates, their exact
source export and parent. Continue saved corrections through these exact versions;
a blocked semantic verdict does not erase a verified checkpoint. Its saved records
start at revision zero in the fresh worker; amend only remaining changes. This
does not accept the candidate or authorize replay of uncertain work.
An option_id is a content-version hash: amended options receive new IDs. Preserve
unchanged records and exact source-page/image provenance, not amended IDs. Use the
corrected catalog with its exact exported source pack; require independent review.
For a script/checks producer that must finish before exact hashes
can be bound, declare prepares:<registered operation>. Code supplies that
operation's full authoring contract to the worker; this grants no execution.
Code adds required reviewers and bounds work to the frozen grant.
If delegation is rejected, correct the saved proposal using the diagnostic and
resubmit. Nothing was queued unless there is a committed receipt. History reading
cannot repair a proposal. Never replay an uncertain action.
After workers return, resolve review findings and complete only exact reviewed
files. Preserve originals and disclose remaining gaps. Wait only for running work.
Stay within the given provider, permissions and capacity."""


COVERAGE_INSTRUCTIONS="""For visual sourcing use selection_policy:visual in collection.options.
Create inventory with content family collection.subjects from the original image
(normalized boxes, no text quotes), or prepare an existing planning document through
that same family with literal quotes. Code owns items, identities and completion.
Free-form inventory/planning JSON is context, never the images.products inventory
port. Bind the exact sealed inventory result to image acquisition and catalog work.
Discover a broad pool before selecting: seek 4–6 distinct plausible designs per item
within the existing research allowance, preserving additional grounded links as leads.
Use one broad visual-description query per subject before narrower alternatives;
do not use all query slots to verify buying details of the first few products.
Gather pools in bounded catalog/photo batches (images.products supports 40 candidates),
using catalog_path:null before catalog approval. Search links without image references
are acquisition gaps, not evidence that suitable alternatives do not exist. Within
the granted operations, run web.sources.rendered on the latest exact source pack,
then images.products on that richer pack. The reader follows captured product links
and prioritizes groups lacking image references within its existing max_pages and
per-publisher limits. Each direct HTTP or rendered attempt consumes one of those
same reads; confirmed direct failures can use the other method, while uncertain
reads stop. Completed captures and their images are reused. Inspect the returned pixels, then continue only eligible unread
leads if suitable coverage is still short and job capacity remains. A captured image
reference is not a downloaded photo or a suitable design. Do not repeat searches,
uncertain reads or completed downloads to simulate progress. Report blocked acquisition
separately from visual rejection; stop honestly at the existing limits.
using reviewed record_range partitions when needed; select within each partition,
then records.merge preserves the policy and images.merge retains exact photo assets.
inspect candidate images against the original, then amend selections before composition.
An unknown price, dimension, stock or delivery field does not disqualify an otherwise
visually suitable design. Keep those facts explicitly unknown. Count distinct designs,
not sellers or variants, using selection.status and design_id. Provisional, excluded
and unavailable records remain evidence but never reduce the suitable-option gap.
Use selection.reason as the current visual comparison with exact image_view source
hashes; independent reviewers must inspect those same pixels and assess the judgments.
Reserve capacity for the visual-selection amendment, review, correction and final files.
Do not substitute prose for typed selection state or proceed with a blocked catalog;
use a fresh scoped correction of an eligible baseline to address its reported defects.
For multi-item research, plan coverage across the full inventory before deepening
individual items. Use exact mapped queries for every subject, prioritize zero-option
and difficult gaps, and reserve the existing allowance for correction and final review.
Count only distinct, suitable, source-supported candidates; seller duplicates and size
variants are not additional designs. Keep provisional, unsuitable, unavailable and
missing-photo comparisons explicit. A target count never requires inventing options,
expanding limits or withholding honest partial files. Reuse saved evidence; uncertain
reads are not permission to replay. Coverage-first ordering does not prove suitability."""


WORK_INTENT_INSTRUCTIONS="""Declare work.mode: execute uses existing typed inputs,
create authorizes new content, and revise requires an exact baseline reference.
For a registered single JSON port, execute requires data or its registered parameter
reference. Evidence inputs do not authorize authoring. Never select create to render
saved content. Use the modes and required references shown by the catalog/brief."""
CORRECTION_SCOPE_INSTRUCTIONS="""Use repairs:[finding IDs] to assign only the defects
a helper can address. Its independent review inherits that scope. Other defects
remain job obligations. Use an unscoped final candidate review for complete final
assessment; helper acceptance cannot waive the final finding-coverage gate."""


def obj(properties, required=None):
    return dict(type='object',properties=properties,required=list(properties) if required is None else required,additionalProperties=False)


REF={'anyOf':[obj(dict(artifact=dict(type='string',minLength=1))),
              obj(dict(task=dict(type='string',minLength=1),output=dict(type='string',minLength=1)))]}
LABEL=dict(type='string',pattern='^[a-z][a-z0-9_-]{0,63}$')
TEXT=dict(type='string',minLength=1)
MIME_TYPES=mimetypes.MimeTypes(filenames=())


def delegation_schema(version=2):
    # The outer transport is structured, not a model-authored JSON envelope.
    # Operation/content options have registry-owned schemas from job_catalog.
    task=obj(dict(id=LABEL,objective=TEXT,instruction=TEXT,
        inputs=dict(type='array',items=REF,maxItems=100),
        outputs=dict(type='array',items=obj(dict(name=LABEL,media_type=TEXT,purpose=TEXT)),maxItems=32),
        operation=TEXT,parameters=dict(type='object'),prepares=TEXT,
        requires=dict(type='array',items=TEXT),dependencies=dict(type='array',items=LABEL),
        review_of=LABEL,repairs=dict(type='array',items=TEXT,maxItems=100,uniqueItems=True),content_parameters=dict(type='object'),
        content=obj(dict(family=TEXT,sources=dict(type='object',additionalProperties=REF),parameters=dict(type='object'))),
        authoring_fallback=obj(dict(reason=TEXT))),['id','objective'])
    if version in (3,4):
        fields=task['properties']
        native=obj({k:v for k,v in fields.items() if k in ('id','objective','instruction','inputs','dependencies','repairs','operation','parameters')},['id','objective','operation'])
        native['properties']['data']=copy.deepcopy(REF)
        agent=obj({k:v for k,v in fields.items() if k not in ('operation','parameters')},['id','objective'])
        task=dict(anyOf=[native,agent])
        if version==4:
            fields['content']['properties']['baseline']=copy.deepcopy(REF)
            # Recovery resolves exact saved parameters before validating choices.
            # New content still needs the complete registered schema at compile.
            fields['content']['required']=['family','sources']
            content=obj({k:v for k,v in fields.items() if k in ('id','objective','instruction','inputs','dependencies','requires','repairs','content')},['id','objective','content'])
            content['properties']['baseline']=copy.deepcopy(REF)
            review=obj({k:v for k,v in fields.items() if k in ('id','objective','instruction','inputs','dependencies','requires','repairs','review_of')},['id','objective','review_of'])
            worker=obj({k:v for k,v in fields.items() if k not in ('operation','parameters','content','review_of')},['id','objective','outputs'])
            work=obj({k:v for k,v in fields.items() if k in ('id','objective','instruction','inputs','dependencies','repairs')},['id','objective'])
            work['properties']['work']=obj(dict(operation=TEXT,mode=dict(type='string',enum=['execute','create','revise']),data=copy.deepcopy(REF),baseline=copy.deepcopy(REF),parameters=dict(type='object'),content_parameters=dict(type='object'),steps=dict(type='array',maxItems=12,items=obj(dict(id=LABEL,operation=TEXT,parameters=dict(type='object'),from_steps=dict(type='array',items=LABEL)),['id','operation']))),['operation'])
            work['required'].append('work')
            # The same exact reference can be supplied beside work, as for a
            # native operation. Construction owns placement, never selection.
            work['properties'].update(data=copy.deepcopy(REF),baseline=copy.deepcopy(REF))
            task=dict(anyOf=[native,content,review,worker,work])
    return obj(dict(request_id=TEXT,tasks=dict(type='array',items=task,minItems=1,maxItems=29)))


def construct_delegation(args,version):
    value=copy.deepcopy(args)
    if version==4 and isinstance(value,dict) and isinstance(value.get('tasks'),list):
        for index,task in enumerate(value['tasks']):
            if not isinstance(task,dict):continue
            container='work' if isinstance(task.get('work'),dict) else 'content' if isinstance(task.get('content'),dict) else None
            if container is None:continue
            for name in (('data','baseline') if container=='work' else ('baseline',)):
                if name not in task:continue
                ref=task.pop(name)
                schema.validate(ref,REF,'delegation.tasks['+str(index)+'].'+name)
                if name in task[container] and task[container][name]!=ref:
                    raise ValueError('delegation.tasks['+str(index)+']: conflicting '+name+' references beside and inside '+container+'; select one exact reference')
                task[container][name]=ref
    return value


def validate_delegation(args,version):
    args=construct_delegation(args,version)
    if version==4 and isinstance(args,dict) and isinstance(args.get('tasks'),list):
        conflicts=[]
        for index,task in enumerate(args['tasks']):
            if isinstance(task,dict) and 'outputs' in task and any(k in task for k in ('operation','content','review_of','work')):
                conflicts.append('tasks['+str(index)+'].outputs ('+str(task.get('id','unnamed'))+')')
        for index,task in enumerate(args['tasks']):
            if isinstance(task,dict) and 'outputs' in task and not any(k in task for k in ('operation','content','review_of','work')):
                try:schema.validate(task['outputs'],dict(type='array',items=obj(dict(name=LABEL,media_type=TEXT,purpose=TEXT)),maxItems=32),'delegation.tasks['+str(index)+'].outputs')
                except ValueError as exc:raise ValueError(str(exc)+'; ordinary worker outputs require [{name,media_type,purpose}]. For independent assessment use review_of and omit outputs.') from None
        if conflicts:
            raise ValueError('Code owns output ports for operation, content and review tasks. Remove '+', '.join(conflicts)+'. Keep task references and objectives; resubmit job_delegate. Catalog outputs are reference names, not fields to copy into these tasks.')
    schema.validate(args,delegation_schema(version),'delegation')


def suffix(media):
    from .document_authoring import REGISTRY
    return (REGISTRY[media]['extensions'][0] if media in REGISTRY else
            { 'text/plain':'.txt','text/markdown':'.md','application/json':'.json',
              'image/jpeg':'.jpg' }.get(media) or MIME_TYPES.guess_extension(media) or '.bin')


def ports(spec):
    """Public logical output names, derived from code-owned declarations."""
    result={}
    outputs=spec['outputs']
    for output in outputs:
        name=PurePosixPath(output['path']).stem.replace('.','_')
        if output.get('media_type')=='text/markdown' and any(PurePosixPath(o['path']).stem==PurePosixPath(output['path']).stem and o.get('media_type')=='application/json' for o in outputs):name+='_summary'
        if spec.get('work_tools') and sum(PurePosixPath(o['path']).stem==PurePosixPath(output['path']).stem for o in outputs)>1:
            step=next((n for n,v in spec['work_tools']['steps'].items() if output in v['outputs'].values()),None)
            if step:name=step+'_'+name
        elif sum(PurePosixPath(o['path']).stem==PurePosixPath(output['path']).stem for o in outputs)>1:
            peers=[o for o in outputs if PurePosixPath(o['path']).stem==PurePosixPath(output['path']).stem]
            if {o.get('media_type') for o in peers}!={'application/json','text/markdown'}:
                name+='_'+PurePosixPath(output['path']).suffix.lstrip('.').replace('.','_')
        if name in result:raise ValueError('Ambiguous registered output name: '+name)
        result[name]=output
    return result


def native_outputs(capability):
    spec=execution.REGISTRY[capability]
    if spec.get('outputs'):
        return [dict(path=p,media_type=m,purpose='Registered operation output') for p,m in spec['outputs'].items()]
    media=spec['output_type']
    return [dict(path='outputs/result'+suffix(media),media_type=media,purpose='Registered operation result')]


def content_outputs(family):
    from . import operation_contracts
    interface=operation_contracts.identity(dict(id=family,version=1))['planning_interface']
    result=[dict(path='outputs/result.json',purpose='Code-owned content projection',media_type='application/json')]
    if interface.get('review_mode')!='structural':
        result.append(dict(path='outputs/result.md',purpose='Code-owned content summary',media_type='text/markdown'))
    return result


def parameter_schema(capability, *, semantic=True, grant=None):
    value=copy.deepcopy(execution.parameter_schema(capability))
    for key,kind in execution.adapter(capability).references.items():
        old=value['properties'][key]
        if old.get('type')=='null':continue
        ref=dict(type='array',items=REF,minItems=old.get('minItems',0),maxItems=old.get('maxItems',100)) if kind=='paths' else copy.deepcopy(REF)
        nullable=old.get('type')=='null' or any(b.get('type')=='null' for b in old.get('anyOf',[]))
        value['properties'][key]={'anyOf':[ref,dict(type='null')]} if nullable else ref
    if semantic:
        from .model_binding import owner_fields
        for key in owner_fields(grant or {},capability):
            value['properties'].pop(key,None)
            if key in value['required']:value['required'].remove(key)
    return value


def catalog(grant,selected,records=False):
    from . import operation_contracts
    from .owner_compilation import request_ceiling
    operations={}
    for cap in selected:
        spec=execution.REGISTRY[cap]
        operations[cap]=dict(inputs=spec['input_types'],parameters=parameter_schema(cap,grant=grant),
            input_contract=dict(min_files=spec.get('min_inputs',1),max_files=spec['max_inputs'],max_bytes=spec['input_bytes'],
                role='Consumed native data only; background evidence belongs on the author/reviewer, not the operation'),
            outputs={k:v['media_type'] for k,v in ports(dict(outputs=native_outputs(cap))).items()},
            preparation=copy.deepcopy(execution.adapter(cap).handoffs['ports']))
        operations[cap]['authoring_worker']=dict(prepares=cap,description='For a separate ordinary script/checks producer, declare prepares with this operation. Code supplies its full registered authoring contract without execution authority. Declare only the required input files as worker outputs; operation parameters and hashes are bound later by code.')
        from .producer_binding import requirements
        preparation_ports=requirements(cap)
        if len(preparation_ports)==1 and preparation_ports[0]['kind']=='preparation' and preparation_ports[0]['selector']=='json':
            operations[cap]['authoring_worker']['outputs']=dict(count=1,media_type='application/json',
                reason='This producer becomes a typed preparation. Declare exactly one JSON output; keep extra reports in a separate assignment.')
        if grant.get('worker_tools_version') in (1,2,3) and (execution.adapter(cap).worker_tool or grant.get('worker_tools_version',0)>=2) and (grant.get('worker_tools_version',0)>=2 or not spec.get('review_evidence')):
            from .worker_tools import configure
            probe=dict(id='catalog',objective='Inspect available work route',instruction='',inputs=[],dependencies=[])
            try:configure(probe,dict(operation=cap,**(dict(mode='execute') if grant.get('worker_tools_version')==3 else {})),grant,bind_parameters=False)
            except ValueError as exc:
                operations[cap]['worker_work_unavailable']=dict(reason=str(exc),alternative='Use a native operation with its required data/preparation producers. No allowance is expanded.')
            else:
                operations[cap]['worker_work']=dict(operation=cap,parameters=parameter_schema(cap,grant=grant),description='One worker runs the declared operation graph; explicit mode selects existing-input execution or authorized content preparation. Code supplies outputs and the granted inspection companion. Supply work on the task, not operation. Exact parameters, input compatibility and remaining capacity are checked at admission.')
    if grant.get('worker_tools_version')==3:
        from .worker_tools import configure
        for cap,value in operations.items():
            if 'worker_work' not in value:continue
            modes=['execute']
            probe=dict(id='catalog',objective='Prepare bounded content',instruction='',inputs=[],dependencies=[])
            try:configure(probe,dict(operation=cap,mode='create'),grant,bind_parameters=False)
            except ValueError:pass
            else:modes+=['create','revise']
            value['worker_work']['modes']=modes
            value['worker_work']['input_binding']='execute binds data to an exact registered port; revise requires an exact baseline; evidence inputs do not implicitly request authoring'
    families={}
    if records:
        for (name,version),family in operation_contracts.REGISTRY.items():
            interface=family.get('planning_interface')
            if not interface or interface.get('expose') is False:continue
            families[name]=dict(sources=list(interface['input_parameters']),parameters=interface['schema'],
                outputs={'result':'application/json',**({'result_summary':'text/markdown'} if interface.get('review_mode')!='structural' else {})},
                independent_review=interface.get('review_mode')!='structural' and not (grant.get('execution_policy',{}).get('review')=='user' and family.get('user_review')),
                capacity=dict(**vars(interface['capacity']),single_task_units=max(0,(request_ceiling(grant)-interface['capacity'].reserved_calls)//(interface['capacity'].submissions_per_unit+interface['capacity'].inspections_per_unit)),
                    partition_merge=interface.get('merge_operation') if interface.get('merge_operation') in grant['operations'] else None,automatic=grant.get('delegation_version') in (3,4)))
            hooks=family.get('lifecycle')
            if operation_contracts.baseline_supported(name,grant):
                families[name]['baseline']=dict(schema=copy.deepcopy(REF),placement='content.baseline',
                    parameter_inheritance='Omit parameters for a correction: code inherits every registered semantic parameter from the exact baseline before capacity planning. Matching supplied subsets are allowed; conflicting or unknown choices reject without effects. New content requires all registered choices.',
                    description='Exact collected sealed candidate to correct, including a blocked producer only when correction_checkpoint proves confirmed collection and saved records. Continue its exact source export and remaining findings; checkpoint retention is not acceptance. Other inherited candidates are evidence only. Without baseline, only one directly supplied compatible candidate may be selected; ambiguity rejects.')
    from .producer_binding import semantic_schema
    return dict(operations=operations,content=families,content_parameters=semantic_schema(),
        workers=[dict(capabilities=w['capabilities'],restrictions=w.get('restrictions','')) for w in grant['workers']],
        limits=copy.deepcopy(grant['task_limits']),task_attempts=grant['task_attempts'],
        note='Use artifact or task/output references. Code resolves paths, versions, hashes, producer schemas and authorized model settings. Content schemas describe choices, not file envelopes.')


def authoring_instruction(capability):
    """Registry-supplied context for staged producers, never execution authority."""
    from . import prepared_schemas
    contract=execution.catalog([capability])[0]
    from .producer_binding import requirements
    preparations=[dict(selector=p['selector'],target=p['target'],document_schema=prepared_schemas.document_schema(p['target']))
                  for p in requirements(capability) if p['kind']=='preparation']
    if preparations:
        contract['preparation_inputs']=preparations
        if len(preparations)==1:contract['preparation_document_schema']=preparations[0]['document_schema']
    return ('Registered authoring contract supplied by code. Produce only assigned '
            'input artifacts for this operation; do not invent adapter globals, '
            'parameter envelopes or output paths. The operation owns execution, '
            'save/reopen and receipts. No execution authority is conferred.\n'+
            c.encoded(contract))


def artifact_descriptor(session, ident):
    """Read an authorized artifact's declared type from its exact binding."""
    artifact,_=session.artifact(ident)
    matches=[i for i in session.frozen['inputs'] if i['artifact']==ident]
    if not matches:
        row=session.rt.db.execute('SELECT run,task,frozen FROM production_attempts WHERE id=?',(artifact.get('attempt'),)).fetchone()
        if row is None or row['run']!=artifact['run'] or row['task']!=artifact['task']:
            raise ValueError('Artifact has no exact producing assignment')
        frozen=json.loads(row['frozen'])
        matches=[o for o in frozen['outputs'] if o['path']==artifact['path']]
    if not matches or len({i.get('media_type','application/octet-stream') for i in matches})!=1:
        raise ValueError('Artifact type binding is missing or ambiguous')
    return copy.deepcopy(matches[0])


def compile(session,args):
    validate_delegation(args,session.grant.get('delegation_version',2))
    args=construct_delegation(args,session.grant.get('delegation_version',2))
    raw=copy.deepcopy(args['tasks']);by_id={};batch=[]
    from .review_followup import findings
    known={f['id'] for f in findings(session.rt,session.run)} if session.grant.get('correction_scope_version')==1 else set()
    for item in raw:
        ident=item['id']
        if ident in by_id:raise ValueError('Duplicate task name')
        native=item.get('operation')
        if native and native not in session.grant['operations']:raise ValueError('Operation is outside this job grant')
        if native and any(k in item for k in ('outputs','requires','review_of','content','content_parameters','authoring_fallback','prepares')):
            raise ValueError('Operation outputs and worker bindings are code owned')
        task=dict(id=ident,objective=item['objective'],instruction=item.get('instruction',item['objective']),
            inputs=[],outputs=[],dependencies=list(item.get('dependencies',[])))
        if item.get('repairs'):
            if session.grant.get('correction_scope_version')!=1:raise ValueError('Scoped repairs need a prospective grant')
            if not set(item['repairs'])<=known:raise ValueError('Repair targets must name existing job finding IDs')
            if item.get('review_of'):raise ValueError('Review scope comes from its candidate and final obligations, not a reviewer-selected subset')
            task['correction_scope']=dict(version=1,findings=list(item['repairs']))
        if 'prepares' in item:
            cap=item['prepares']
            if cap not in session.grant['operations']:raise ValueError('Authoring operation is outside this job grant')
            if any(k in item for k in ('work','content','review_of')):raise ValueError('prepares belongs to an ordinary file producer')
            task['instruction']+='\n\n'+authoring_instruction(cap)
        if native:
            task['execution']=dict(capability=native,version=execution.REGISTRY[native]['version'],parameters={})
            task['outputs']=native_outputs(native)
        else:
            if 'parameters' in item:raise ValueError('Parameters belong to an operation')
            if item.get('work'):
                from .worker_tools import configure
                from .model_binding import bind_owner, selected
                work=copy.deepcopy(item['work'])
                for part in [work,*work.get('steps',[])]:part['parameters']=bind_owner(session.grant,part['operation'],part.get('parameters',{}),session.frozen['backend'])
                configure(task,work,session.grant,bind_parameters=False)
                task['work_backends']={name:selected(session.grant,step['operation'],session.frozen['backend']) for name,step in task['work_tools']['steps'].items()}
            if item.get('content'):
                from . import operation_contracts
                family=operation_contracts.identity(dict(id=item['content']['family'],version=1))
                interface=family.get('planning_interface')
                if not interface or interface.get('expose') is False:raise ValueError('Content family has no registered owner intent')
                if 'outputs' in item or 'content_parameters' in item:raise ValueError('Content projections are code owned; supply only semantic content parameters')
                task['outputs']=content_outputs(item['content']['family'])
            names=[o['name'] for o in item.get('outputs',[])]
            if len(set(names))!=len(names):raise ValueError('Named outputs must be distinct')
            for output in item.get('outputs',[]):
                task['outputs'].append(dict(path='outputs/'+output['name']+suffix(output['media_type']),
                    purpose=output['purpose'],media_type=output['media_type']))
            if item.get('review_of'):
                task['review_of']=item['review_of']
                if 'outputs' in item or 'content' in item:raise ValueError('Review projections are code owned')
                task['outputs']=[dict(path='outputs/review.md',purpose='Independent review',media_type='text/markdown')]
            elif not task['outputs']:raise ValueError('Worker needs a named output')
            if 'authoring_fallback' in item:task['authoring_fallback']=copy.deepcopy(item['authoring_fallback'])
            if 'content_parameters' in item:task['content_parameters']=copy.deepcopy(item['content_parameters'])
        if len(ports(task))!=len(task['outputs']):raise ValueError('Duplicate output name')
        by_id[ident]=task;batch.append(task)

    def producer(ident):
        return by_id.get(ident) or session.rt.spec(session.rt.task(session.run,ident))

    def resolve(ref):
        schema.validate(ref,REF,'input reference')
        if 'artifact' in ref:
            ident=ref['artifact'];descriptor=artifact_descriptor(session,ident)
            matches=[i for i in session.frozen['inputs'] if i['artifact']==ident]
            binding=dict(artifact=ident);identity='artifact:'+ident
            authority=descriptor.get('authority','Exact candidate; review status is tracked separately')
        else:
            spec=producer(ref['task']);outputs=ports(spec)
            if ref['output'] not in outputs:raise ValueError('Unknown named output '+ref['task']+'/'+ref['output']+'; choose '+', '.join(outputs))
            descriptor=outputs[ref['output']];binding=dict(from_task=ref['task'],output=descriptor['path'])
            identity=ref['task']+':'+descriptor['path'];authority='Exact worker candidate; no acceptance inferred'
        tag=hashlib.sha256(identity.encode()).hexdigest()[:16]
        path='inputs/'+tag+'/'+PurePosixPath(descriptor['path']).name
        if 'artifact' in ref and matches and PurePosixPath(descriptor['path']).parts[0] not in ('delivery','outputs'):
            # Retain safe names already bound by intake, including references
            # inside saved manifests. New/future outputs get isolated aliases.
            path=descriptor['path']
        binding.update(path=path,
            purpose=descriptor['purpose'],authority=authority,media_type=descriptor.get('media_type','application/octet-stream'))
        if descriptor.get('visual_reference'):binding['visual_reference']=True
        return binding

    recovery_cache={};recovery_claims={}
    def add(task,ref,cap=None):
        if cap and resolve(ref).get('media_type')!='application/json':cap=None
        if cap:
            from .evidence_recovery import select
            key=(cap,c.encoded(ref))
            if key not in recovery_cache:recovery_cache[key]=select(session,cap,ref,producer)
            ref=recovery_cache[key]
            hook=execution.adapter(cap).evidence_extension
            if hook:
                claim=(hook,c.encoded(ref))
                if claim in recovery_claims and recovery_claims[claim]!=task['id']:
                    raise ValueError('Evidence recovery needs one continuation per source lineage; do not dispatch duplicate readers')
                recovery_claims[claim]=task['id']
        value=resolve(ref)
        existing=next((i for i in task['inputs'] if i['path']==value['path']),None)
        if existing and {k:existing.get(k) for k in ('artifact','from_task','output')}!={k:value.get(k) for k in ('artifact','from_task','output')}:
            raise ValueError('Conflicting exact input aliases')
        if not existing:task['inputs'].append(value)
        if 'from_task' in value and value['from_task'] not in task['dependencies']:task['dependencies'].append(value['from_task'])
        return existing or value

    def bind_parameters(task,cap,params,bindings=None):
        def completed_artifact(source,key):
            if 'artifact' not in source:
                completed=(source['from_task'] not in by_id and
                    session.rt.task(session.run,source['from_task'])['status']=='completed')
                if not completed:raise ValueError('This operation requires an existing artifact for '+key+'; delegate it after that output completes')
                artifact=session.rt.output(session.run,source['from_task'],source['output'])
                if not artifact:raise ValueError('Completed producer has no exact output for '+key)
                session.artifact(artifact['id'])
                source.pop('from_task');source.pop('output');source['artifact']=artifact['id']
            return session.artifact(source['artifact'])[0]
        choices=parameter_schema(cap,semantic=False)
        for key in bindings or {}:choices['properties'].pop(key);choices['required'].remove(key)
        schema.validate(params,choices,'operation choices')
        for key,kind in execution.adapter(cap).references.items():
            if key not in params:continue
            value=params[key]
            if value is None:continue
            refs=value if kind=='paths' else [value];bound=[add(task,r) for r in refs]
            if kind=='sha256':
                params[key]=completed_artifact(bound[0],key)['sha256']
            else:
                params[key]=[b['path'] for b in bound] if kind=='paths' else bound[0]['path']
            if kind in ('sha256','path'):
                # Saved artifacts may use historical text media; future output
                # declarations stay immutable and are checked at graph admission.
                source=bound[0]
                execution.adapter(cap).bind_reference_media(key,source if 'artifact' in source else copy.deepcopy(source))
                from .producer_binding import requirements
                for port in requirements(cap):
                    if port.get('reference_parameter')!=key:continue
                    selected=source
                    if selected.get('media_type')!='application/json':raise ValueError(key+' requires its registered JSON preparation')
                    def identity(value):
                        return tuple(value.get(k) for k in ('artifact','from_task','output'))
                    for other in task['inputs']:
                        if other is selected or other.get('media_type')!='application/json':continue
                        if identity(other)==identity(selected):continue
                        # Distinct saved aliases may have identical bytes. Future
                        # outputs cannot be treated as equal before collection.
                        try:equal=completed_artifact(other,key)['sha256']==completed_artifact(selected,key)['sha256']
                        except ValueError:equal=False
                        if not equal:
                            raise ValueError('JSON data conflicts with named preparation '+key+'; supply only its exact reference, keeping context on the author/reviewer')
                    task['inputs']=[i for i in task['inputs'] if i is selected or i.get('media_type')!='application/json']
        return params

    for item,task in zip(raw,batch):
        implicit_cap=(item.get('operation') if not item.get('data') else None) or (
            item.get('work',{}).get('operation') if item.get('work',{}).get('mode')=='execute' and not item['work'].get('data') else None)
        for ref in item.get('inputs',[]):add(task,ref,implicit_cap)
        if item.get('review_of'):
            target=producer(item['review_of'])
            for name in ports(target):add(task,dict(task=target['id'],output=name))
            if target['id'] not in by_id and session.grant.get('review_snapshot_version')==1:
                current=session.rt.task(session.run,target['id'])
                if current['status']!='completed':
                    raise ValueError('Existing producer is not completed. Wait for its existing review; do not add a second gate. For completed candidates use review_of plus exact evidence inputs, without outputs.')
                task['review_snapshot']=dict(version=1,attempts={target['id']:current['latest']})
        if item.get('data'):
            if session.grant.get('delegation_version') not in (3,4) or not item.get('operation'):
                raise ValueError('An explicit data reference requires a compiled native operation')
            from .producer_binding import requirements
            if not any(p['selector']=='json' for p in requirements(item['operation'])):
                raise ValueError('This operation uses named parameter references rather than a data port')
            selected=add(task,item['data'],item['operation'])
            if selected.get('media_type')!='application/json':raise ValueError('Data port needs JSON')
            # Unselected JSON remains evidence on its producing/reviewing worker.
            # Native adapters receive exactly their named data port and assets.
            task['inputs']=[i for i in task['inputs'] if i.get('media_type')!='application/json' or i is selected or i==selected]
            task['dependencies']=list(dict.fromkeys(item.get('dependencies',[])+[i['from_task'] for i in task['inputs'] if 'from_task' in i]))
        if item.get('work'):
            route=task['work_tools'].get('intent')
            if route is not None:
                for key in ('data','baseline'):
                    if key in item['work']:route[key]=add(task,item['work'][key],item['work']['operation'] if key=='data' else None)['path']
            for step in task['work_tools']['steps'].values():
                step['parameters']=bind_parameters(task,step['operation'],step['parameters'],step.get('parameter_bindings'))
            from .worker_tools import validate_assignment
            validate_assignment(task)
            from .worker_tools import validate_inputs
            validate_inputs(task)
        if item.get('operation'):
            cap=item['operation'];params=copy.deepcopy(item.get('parameters',{}))
            from .model_binding import bind_owner
            params=bind_owner(session.grant,cap,params,session.frozen['backend'])
            task['execution']['parameters']=bind_parameters(task,cap,params)
            # Producer binding may still add required native inputs. Explicit
            # excess or unsupported selections are already invalid here.
            execution.validate_inputs(task,complete=False)
        else:
            if item.get('content'):
                from . import operation_contracts
                intent=item['content'];family=operation_contracts.identity(dict(id=intent['family'],version=1))
                interface=family.get('planning_interface')
                if not interface or interface.get('expose') is False:raise ValueError('Content family has no registered owner intent')
                if set(intent['sources'])!=set(interface['input_parameters']):raise ValueError('Content sources differ from registered ports')
                hooks=family.get('lifecycle')
                recovery_enabled=session.grant.get('coordination_version')==1 and hooks and hooks.prepare_recovery
                if not recovery_enabled:
                    schema.validate(intent.get('parameters',{}),interface['schema'],'content choices')
                refs={}
                for key,ref in intent['sources'].items():
                    hooks=family.get('lifecycle')
                    if (session.grant.get('coordination_version')==1 and hooks and hooks.evidence_extension
                            and key==hooks.evidence_parameter):
                        from .evidence_recovery import select
                        ref=select(session,intent['family'],ref,producer,hook=hooks.evidence_extension,reader=False)
                    value=add(task,ref)
                    refs[key]=dict(source=value['artifact']) if 'artifact' in value else dict(producer=value['from_task'],output=value['output'])
                task['records']=dict(family=dict(id=intent['family'],version=1),inputs=refs,parameters=copy.deepcopy(intent.get('parameters',{})))
                hooks=family.get('lifecycle')
                recovery_enabled=session.grant.get('coordination_version')==1 and hooks and hooks.prepare_recovery
                if 'baseline' in intent and not recovery_enabled:
                    raise ValueError('Content baseline requires a granted registered recovery interface')
                if session.grant.get('delegation_version')==4 and recovery_enabled:
                    # Capture direct intent before handoff closure adds ancestors.
                    selection=dict(inputs=[copy.deepcopy(resolve(ref)) for ref in item.get('inputs',[])])
                    if 'baseline' in intent:
                        baseline=add(task,intent['baseline'])
                        if 'artifact' not in baseline:
                            row=session.rt.task(session.run,baseline['from_task']) if baseline['from_task'] not in by_id else None
                            if not row or not row['latest']:raise ValueError('Content baseline requires a completed collected candidate')
                            artifact=session.rt.output(session.run,baseline['from_task'],baseline['output'])
                            if not artifact:raise ValueError('Content baseline requires a completed collected candidate')
                            session.artifact(artifact['id'])
                            source_task=baseline['from_task']
                            baseline.pop('from_task');baseline.pop('output');baseline['artifact']=artifact['id']
                            if source_task not in item.get('dependencies',[]) and not any(i.get('from_task')==source_task for i in task['inputs']):
                                task['dependencies']=[d for d in task['dependencies'] if d!=source_task]
                        selection['baseline']=copy.deepcopy(baseline)
                    task['record_recovery_selection']=selection
                if interface.get('review_mode')!='structural' and len(task['outputs'])==1:
                    task['outputs'].append(dict(path=str(PurePosixPath(task['outputs'][0]['path']).with_suffix('.md')),purpose='Code-owned summary',media_type='text/markdown'))
            requires=item.get('requires')
            if requires is None:requires=worker_requirements(task)
            task['worker']=dict(requires=requires)
    return batch


def worker_requirements(task):
    from .worker_capabilities import has_binary
    if task.get('artifact_roles'):
        return ['files.text']+(['images.view'] if any(row['inspection']['tool']=='image_view' for row in task['artifact_roles']['inputs'].values()) or task.get('work_tools') and 'inspect' in task['work_tools']['steps'] else [])
    if task.get('work_tools'):
        return ['files.text']+(['images.view'] if 'inspect' in task['work_tools']['steps'] or any(i.get('visual_reference') or i.get('media_type','').startswith('image/') for i in task['inputs']+task['outputs']) else [])
    requires=['files.text']
    visual=any(i.get('visual_reference') or i.get('media_type','').startswith('image/') for i in task['inputs'])
    if visual or task.get('review_of') and has_binary(task):requires.append('images.view')
    only_visual=all(i.get('media_type')=='image/png' or not has_binary(dict(inputs=[i])) for i in task['inputs']) and not has_binary(dict(outputs=task['outputs']))
    if has_binary(task) and not only_visual:requires.append('files.binary')
    return requires


def brief(frozen):
    grant=frozen['owner_grant']
    result=dict(request=frozen['brief'],instruction=frozen['instruction'],
        **({'revision':copy.deepcopy(frozen['revision'])} if frozen.get('revision') else {}),
        inputs=[dict(artifact=i['artifact'],label=i['purpose'],format=i.get('media_type'),
            provenance=i['authority'],assessment='Evidence reference; acceptance is not implied') for i in frozen['inputs']],
        deliverables=grant['deliverables'],available_operations=list(grant['operations']),
        authorized_capacity=dict(owner_turns=grant['owner_turns'],task_slots=grant['max_tasks'],
            per_task_limits=copy.deepcopy(grant['task_limits']),task_attempts=grant['task_attempts']),
        authoring=dict(registered_formats=list(grant.get('authoring_policy',{}).get('formats',{})),
            custom_code_exceptions=grant.get('authoring_policy',{}).get('custom_code',{})))
    if any(op.startswith('web.sources') or op=='collection.slides' for op in grant['operations']):
        result['sourcing_policy']=COVERAGE_INSTRUCTIONS
        from .job_owner import user_choice
        if user_choice(grant):
            result['sourcing_policy']='User-choice sourcing: prepare typed collection.subjects inventory from the original reference. Use web.sources.rendered with existing HTTP/rendered allowances, then images.products with catalog_path:null for a broad provisional pool. Reuse completed outcomes; stop on uncertainty and never replay reads. Deliver the entire photo bundle, not an AI-selected subset. Recommendations and duplicate-design groups are advisory. Inspect pixels before visual claims, disclose unassessed images and unknown buying details, and report target shortfalls without blocking honest delivery. No automatic AI suitability approval is requested; the user decides fit. Explicit reviews and intrinsic reviewed-data contracts remain binding.'
    if grant.get('decision_brief_version')==1:
        result.pop('inputs');result.pop('available_operations')
        result['current_state']='Use decision_brief in the current durable state for exact input references, findings and available work routes.'
    return result
