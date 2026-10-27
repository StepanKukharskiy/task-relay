"""Shared, versioned content contracts. Job data never supplies executable validators."""
import hashlib

import json
import re
import copy

MAX_SUBMISSION_BYTES=16000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def fields(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Unexpected operation contract fields: expected '+', '.join(keys))


def text(value, limit=600):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError('Expected bounded nonempty contract text')


def references(value, sources=None, *, required=True):
    if not isinstance(value, list) or not (1 if required else 0) <= len(value) <= 3:
        raise ValueError('Use at most three literal source references')
    for item in value:
        fields(item, ('observation', 'quote')); text(item['observation'], 160); text(item['quote'], 500)
        if sources is not None and item['quote'] not in sources.get(item['observation'], ''):
            raise ValueError('Reference is absent from the exact frozen source')


def audit_record(value, parameters, context=None):
    fields(value, ('claim', 'verdict', 'reason', 'supports'))
    if type(value['claim']) is not int or value['claim'] < 1:
        raise ValueError('Expected a frozen claim ID')
    if value['verdict'] not in ('supported', 'unsupported', 'uncertain'):
        raise ValueError('Unknown audit verdict')
    text(value['reason'], 600)
    references(value['supports'], (context or {}).get('sources'), required=value['verdict']=='supported')
    if context is not None:
        unit=next((u for u in context['units'] if u['claim']==value['claim']), None)
        if unit is None:raise ValueError('Foreign claim ID')
        if unit['kind']!='limitation' and any(s['observation']=='coverage' for s in value['supports']):
            raise ValueError('Coverage cannot substantiate an observed fact or inference')
    return str(value['claim'])


def candidate_parameters(value):
    fields(value, ('entity_type', 'required_fields', 'max_records'))
    text(value['entity_type'], 80)
    names=value['required_fields']
    if (not isinstance(names, list) or not 1<=len(names)<=12 or
            any(not isinstance(n,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',n) for n in names)
            or len(set(names))!=len(names)):
        raise ValueError('Use 1–12 distinct required field names')
    if type(value['max_records']) is not int or not 1<=value['max_records']<=100:
        raise ValueError('Candidate record ceiling must be 1–100; use explicit bounded batches')


def candidate_record(value, parameters, context=None):
    fields(value, ('url', 'name', 'identity_support', 'facts'))
    text(value['url'], 500);text(value['name'], 160)
    if not re.fullmatch(r'https://[^\s]+',value['url']):raise ValueError('Candidate identity needs an exact HTTPS URL')
    sources=(context or {}).get('sources')
    references(value['identity_support'],sources)
    if sources is not None and not any(value['url'] in sources[s['observation']] for s in value['identity_support']):
        raise ValueError('Candidate URL is absent from its identity observations')
    facts=value['facts']
    if not isinstance(facts,list) or len(facts)!=len(parameters['required_fields']):
        raise ValueError('Record each required field explicitly, including unknowns')
    seen=set()
    for fact in facts:
        fields(fact, ('field','status','text','supports'))
        if fact['field'] not in parameters['required_fields'] or fact['field'] in seen:raise ValueError('Duplicate or foreign candidate field')
        seen.add(fact['field']);text(fact['text'],400)
        if fact['status'] not in ('observation','inference','unknown'):raise ValueError('Invalid candidate fact status')
        references(fact['supports'],sources,required=fact['status']!='unknown')
        if fact['status']=='unknown' and fact['supports']:raise ValueError('Unknown fields cannot assert observed support')
    return value['url']


AUDIT_SCHEMA={'type':'object','properties':{
    'claim':{'type':'integer'},'verdict':{'type':'string','enum':['supported','unsupported','uncertain']},
    'reason':{'type':'string','maxLength':600},'supports':{'type':'array','maxItems':3,'items':{
        'type':'object','properties':{'observation':{'type':'string'},'quote':{'type':'string','maxLength':500}},
        'required':['observation','quote'],'additionalProperties':False}}},
    'required':['claim','verdict','reason','supports'],'additionalProperties':False}
REF_SCHEMA=AUDIT_SCHEMA['properties']['supports']
CANDIDATE_SCHEMA={'type':'object','properties':{
    'url':{'type':'string'},'name':{'type':'string'},'identity_support':REF_SCHEMA,
    'facts':{'type':'array','maxItems':12,'items':{'type':'object','properties':{
        'field':{'type':'string'},'status':{'type':'string','enum':['observation','inference','unknown']},
        'text':{'type':'string','maxLength':400},'supports':REF_SCHEMA},
        'required':['field','status','text','supports'],'additionalProperties':False}}},
    'required':['url','name','identity_support','facts'],'additionalProperties':False}


def batch_parameters(value):
    fields(value, ('entity_type','required_fields','max_records','criteria'))
    candidate_parameters({k:value[k] for k in ('entity_type','required_fields','max_records')})
    criteria=value['criteria']
    if not isinstance(criteria,list) or len(criteria)>8:raise ValueError('Use at most eight qualification criteria')
    seen=set()
    for item in criteria:
        fields(item,('id','question'))
        text(item['question'],500)
        if not isinstance(item['id'],str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',item['id']) or item['id'] in seen:
            raise ValueError('Qualification criteria need distinct stable IDs')
        seen.add(item['id'])
    if value['max_records']*(1+len(value['required_fields'])+len(criteria))>30:
        raise ValueError('Research batch exceeds independent audit capacity')


def batch_record(value,parameters,context=None):
    fields(value,('url','name','identity_support','facts','assessment'))
    key=candidate_record({k:v for k,v in value.items() if k!='assessment'},parameters,context)
    decisions=value['assessment'];seen=set()
    if not isinstance(decisions,list) or len(decisions)!=len(parameters['criteria']):
        raise ValueError('Assess every frozen criterion, explicitly including unknowns')
    for item in decisions:
        fields(item,('criterion','verdict','reason','supports'))
        if item['criterion'] not in {c['id'] for c in parameters['criteria']} or item['criterion'] in seen:
            raise ValueError('Foreign or duplicate qualification criterion')
        seen.add(item['criterion']);text(item['reason'],400)
        if item['verdict'] not in ('met','unmet','unknown'):raise ValueError('Invalid criterion verdict')
        references(item['supports'],(context or {}).get('sources'),required=item['verdict']!='unknown')
        if item['verdict']=='unknown' and item['supports']:raise ValueError('Unknown criterion cannot assert support')
    return key


BATCH_SCHEMA=copy.deepcopy(CANDIDATE_SCHEMA)
BATCH_SCHEMA['properties']['assessment']={'type':'array','maxItems':8,'items':{
    'type':'object','properties':{'criterion':{'type':'string'},
    'verdict':{'type':'string','enum':['met','unmet','unknown']},
    'reason':{'type':'string','maxLength':400},'supports':REF_SCHEMA},
    'required':['criterion','verdict','reason','supports'],'additionalProperties':False}}
BATCH_SCHEMA['required'].append('assessment')

# Existing domain validators remain authoritative. Adapters do not grant tools.
REGISTRY={
    ('research.audit',1):dict(schema=AUDIT_SCHEMA,validate=audit_record,batch=3),
    ('research.candidates',1):dict(schema=CANDIDATE_SCHEMA,validate=candidate_record,batch=1),
    ('research.batch',1):dict(schema=BATCH_SCHEMA,validate=batch_record,batch=1),
    ('geometry.specification',1):dict(),
}
from .sourcing_contract import OPTIONS_SCHEMA, REVIEW_SCHEMA, options_record, review_record, options_schema
from .sourcing_inventory import SCHEMA as INVENTORY_SCHEMA, record as inventory_record, PLANNING_CRITERIA as INVENTORY_CRITERIA
REGISTRY.update({
    ('sourcing.inventory',1):dict(schema=INVENTORY_SCHEMA,validate=inventory_record,batch=1,planning_criteria=INVENTORY_CRITERIA),
    ('sourcing.options',1):dict(schema=OPTIONS_SCHEMA,validate=options_record,batch=1,
        deterministic_exports=dict(source_pack_output=4000000),
        file_context=dict(mode='indexed',input_bytes=4000000)),
    ('sourcing.review',1):dict(schema=REVIEW_SCHEMA,validate=review_record,batch=8,
        file_context=dict(mode='indexed',input_bytes=4000000)),
})

REGISTRY.update({
    ('collection.options',1):dict(schema=OPTIONS_SCHEMA,schema_for=options_schema,
        validate=options_record,batch=1,deterministic_exports=dict(source_pack_output=4000000),
        file_context=dict(mode='indexed',input_bytes=4000000),allow_empty_subjects=True,
        required_parameters=('field_definitions','identity_field')),
    ('collection.review',1):dict(schema=REVIEW_SCHEMA,validate=review_record,batch=8,
        file_context=dict(mode='indexed',input_bytes=4000000),allow_empty_subjects=True,
        required_parameters=('field_definitions','identity_field')),
})

from . import record_lifecycle as lifecycle
for _key, _hooks in {
    ('research.audit',1):lifecycle.AUDIT,
    ('research.candidates',1):lifecycle.LEDGER,
    ('research.batch',1):lifecycle.EMPTY_LEDGER,
    ('sourcing.inventory',1):lifecycle.INVENTORY,
    ('sourcing.options',1):lifecycle.OPTIONS,
    ('sourcing.review',1):lifecycle.REVIEW,
    ('collection.options',1):lifecycle.OPTIONS,
    ('collection.review',1):lifecycle.REVIEW,
}.items():
    REGISTRY[_key]['lifecycle']=_hooks
for _producer,_review in [('sourcing.options','sourcing.review'),('collection.options','collection.review')]:
    for _id,_role in [(_producer,'options'),(_review,'review')]:
        REGISTRY[_id,1].update(record_role=_role,producer_family=_producer,review_family=_review)
        REGISTRY[_id,1]['support_modules']=('orchestrator.visual_selection','orchestrator.record_transfers')

REGISTRY['collection.options',1]['display_terms']=dict(options='Collected alternatives',photo_missing='Source image unavailable',photo_unbound='Retained image needs a source/subject association review.',link='Open source page',coverage='Captured fields and links retain their source evidence. Subject suitability and image correspondence require independent review. Unknown fields, quantity shortfalls and missing images remain visible.')

from .collection_core import RECORD_CAPACITY
REGISTRY['collection.options',1]['planning_interface']=dict(
    review_scope=dict(source_parameter='inventory_path',range_parameter='record_range',maximum_parameter='max_records'),
    input_parameters=('inventory_path','source_pack_path'),
    review_parameters=('max_records','field_definitions','identity_field'),
    merge_operation='records.merge',capacity=RECORD_CAPACITY,workload=dict(input='inventory_path',collection='items'),
    merge_transfer=dict(version=1,parameters=dict(field_definitions='parameter',identity_field='parameter',options_per_item='parameter',count_policy='parameter',max_records='parameter',selection_policy='reviewed_artifact')),
    schema=dict(type='object',properties={
        'field_definitions':dict(type='object',minProperties=1,maxProperties=12,additionalProperties=dict(type='string',enum=['text','price']),
            description='Only facts selected from literal saved source-page text, each bound to an observed span or explicit unknown. Code already supplies item identity, source URL, capture provenance and evidence bindings. Put model judgments and source-to-subject comparisons in the comparison string, not extraction fields.'),
        'identity_field':dict(type='string',description='One declared literal source field that identifies the selected entity or product; it must have an observed span.'),'options_per_item':dict(type='integer',minimum=1,maximum=10),
        'count_policy':dict(type='string',enum=['target','required']),
        'selection_policy':dict(type='string',enum=['visual'],description='Separate provisional pool, distinct visually suitable designs, excluded and unavailable comparisons. Unknown buying fields do not disqualify visual suitability. Exact image observations and independent review required.'),
        'max_records':dict(type='integer',minimum=1,maximum=40)},
        required=['field_definitions','identity_field','options_per_item','count_policy','max_records'],additionalProperties=False))

REGISTRY['sourcing.inventory',1]['record_role']='inventory'

# Historical intent translates into the same partition compiler without gaining
# new operations or record-family identities in its frozen scope.
REGISTRY['sourcing.options',1]['planning_interface']={**REGISTRY['collection.options',1]['planning_interface'],
    'review_parameters':('max_records',),'merge_operation':'sourcing.merge','expose':False}


# New content families supply validation hooks as well as record lifecycle hooks.
# Historical families retain their exact serialized contracts.
from . import subject_contract as subjects
from .collection_core import Capacity
REGISTRY['collection.subjects',1]=dict(user_review=True,schema_for=subjects.schema,schema=subjects.schema(dict(max_records=40,fields=[])),
    validate=subjects.record,batch=1,record_role='subjects',review_criterion=subjects.CRITERION,planning_version=2,support_modules=('orchestrator.parameter_contracts',),
    validate_assignment=subjects.validate_assignment,validate_document=subjects.validate_document,
    lifecycle=lifecycle.Lifecycle(context=subjects.context,maximum=lambda s:s.contract['parameters']['max_records']+1,
        progress=subjects.progress,document=subjects.projection,complete=lambda s,r:s.document(r)['complete'],
        projections=subjects.summaries,require_active=True,export_empty=True,resumable=True,
        owned_parameters=('summary_path',),completion_error='Seal the exact subject count before completion',
        instructions='Submit consecutive subject slots from the exact source. Text sources need literal quotes; visual sources need normalized boxes. Use null for unknown attributes. Seal with kind:end and the actual count, including zero with coverage notes. The source and projections are unreviewed evidence; the admitted workflow governs assessment.'),
    planning_interface=dict(input_parameters=('source_path',),review_mode='file',merge_operation=None,
        capacity=Capacity(inspections_per_unit=0),
        schema={**subjects.PARAMETERS,'properties':{k:v for k,v in subjects.PARAMETERS['properties'].items() if k not in ('source_path','summary_path')},
                'required':['max_records','fields']}))


from . import layout_contract as layouts
REGISTRY['document.layout',1]=dict(schema_for=layouts.schema,
    local_record_tool=True,
    file_context=dict(mode='assets',input_bytes=100000000,media_types=['image/png','image/jpeg','application/zip']),
    schema=layouts.schema(dict(max_records=20)),validate=layouts.record,batch=3,
    validate_assignment=layouts.validate_assignment,validate_document=layouts.validate_document,
    planning_version=2,support_modules=('orchestrator.parameter_contracts','orchestrator.slide_templates',
        'orchestrator.pptx_document','orchestrator.image_sources','orchestrator.image_representation','orchestrator.table_layout','orchestrator.document_compose'),
    lifecycle=lifecycle.Lifecycle(context=layouts.context,maximum=lambda s:s.contract['parameters']['max_records']+1,
        progress=layouts.progress,document=layouts.projection,complete=layouts.complete,initial_records=layouts.initial_records,
        require_active=True,export_empty=True,resumable=True,amendable=True,
        completion_error='Seal the exact nonempty layout content count before finishing',
        instructions='Select registered layouts and submit up to three consecutive bounded page/content fragments per call, including the completion seal when ready. For work.mode revise, the exact baseline pages and seal already exist at revision zero as saved_page references. Read operation_progress and operation_read; use operation_amend with the current record hash to replace only affected pages with registered layouts. Do not resubmit saved pages or rewrite expanded JSON. Unchanged pages and exact image hashes survive automatically. Never generate Python, coordinates, fonts or arbitrary templates. Use only exact declared image paths, including validated bundle members. image_grid accepts one ordered list; code paginates it. Submit kind:end with the actual content-group count for new documents. Code owns JSON, placement and pagination. This is preparation, not final delivery or semantic acceptance.'),
    planning_interface=dict(input_parameters=(),review_mode='structural',merge_operation=None,
        capacity=Capacity(inspections_per_unit=0),schema=layouts.PARAMETERS,producer_defaults=layouts.producer_defaults))

from . import prepared_contract as preparations
preparations.register(REGISTRY,lifecycle)
from . import workflow_proposal
workflow_proposal.register(REGISTRY,lifecycle)

# Native producers are registered against an exact content family and output
# port. A model-supplied MIME or output annotation cannot establish this proof.
REGISTRY['sourcing.options',1]['native_producers']=[dict(capability='sourcing.merge',version=1,output='delivery/catalog.json')]
REGISTRY['collection.options',1]['native_producers']=[dict(capability='records.merge',version=1,output='delivery/catalog.json')]


# Presentation belongs to the existing registrations; it cannot change wire IDs.
REGISTRY['collection.subjects',1]['node_ui']=dict(title='Identify subjects',inputs={'source_path':'Source material','parameters':'Inventory settings'},outputs={'result':'Subject inventory','result_summary':'Inventory summary'})
REGISTRY['collection.options',1]['node_ui']=dict(title='Describe alternatives',inputs={'parameters':'Collection settings'},outputs={'result':'Alternatives catalog','result_summary':'Catalog summary'})
REGISTRY['document.layout',1]['node_ui']=dict(title='Arrange document sections',inputs={'parameters':'Layout settings'},outputs={'result':'Document layout'})


def baseline_supported(operation, grant=None):
    """One capability/authority rule for the public content correction field."""
    family=REGISTRY.get((operation,1),{})
    hooks=family.get('lifecycle')
    return bool(hooks and hooks.prepare_recovery and (grant is None or
        grant.get('coordination_version')==1 and grant.get('delegation_version')==4))


def output_contract(task, path):
    execution=task.get('execution')
    if execution:
        for (ident,version),family in REGISTRY.items():
            if any(execution.get('capability')==port['capability']
                   and execution.get('version')==port['version'] and path==port['output']
                   for port in family.get('native_producers',())):
                return dict(id=ident,version=version)
        return None
    bound=task.get('operation_contract',{})
    if bound.get('output')==path and (bound.get('id'),bound.get('version')) in REGISTRY:
        return {key:bound[key] for key in ('id','version')}
    return None


def identity(value):
    fields(value, ('id','version'))
    if not isinstance(value['id'],str) or type(value['version']) is not int or (value['id'],value['version']) not in REGISTRY:
        raise ValueError('Unknown operation contract/version')
    return REGISTRY[value['id'],value['version']]


def validate_assignment(frozen):
    contract=frozen.get('operation_contract')
    if not contract:return
    fields(contract, ('id','version','parameters','output'))
    family=identity({k:contract[k] for k in ('id','version')})
    if 'schema' not in family:raise ValueError('This content contract has no record submission adapter')
    if not set(family.get('required_parameters',()))<=set(contract['parameters']):raise ValueError('Missing registered semantic parameters')
    if family.get('validate_assignment'):
        family['validate_assignment'](frozen);return
    if family.get('record_role') or contract['id']=='sourcing.inventory':
        if contract['id']=='sourcing.inventory':
            from .sourcing_inventory import validate_assignment as validate_inventory
            validate_inventory(frozen);return
        from .sourcing_contract import validate_assignment as validate_sourcing
        validate_sourcing(frozen);return
    if frozen.get('tools') not in (['files'],['files','computer']) or frozen.get('execution'):
        raise ValueError('Record operations require a text or computer worker')
    if contract['output'] not in {o['path'] for o in frozen['outputs']}:raise ValueError('Contract output must be declared')
    if contract['id']=='research.audit':
        fields(contract['parameters'], ())
        if not frozen.get('review_of') or frozen.get('research_audit',{}).get('version')!=2:
            raise ValueError('Typed audit requires a separate research reviewer')
        units=frozen.get('computer_review',{}).get('research',{}).get('units')
        minimum=(len(units)+2)//3+2 if units is not None else 16
    else:
        (batch_parameters if contract['id']=='research.batch' else candidate_parameters)(contract['parameters'])
        if frozen.get('review_of') or not frozen.get('computer') or frozen.get('research_delivery',{}).get('version')!=2:
            raise ValueError('Candidate records require a source-bound research producer')
        parameters=contract['parameters']
        if parameters['max_records']*(len(parameters['required_fields'])+1)>30:
            raise ValueError('Discovery batch exceeds independent audit capacity')
        minimum=parameters['max_records']+2+2*len(frozen['computer'].get('spec',frozen['computer']).get('allowed_urls',[]))
    from .executors import request_limit,response_limit
    if request_limit(frozen)<minimum or frozen['limits']['tool_calls']<minimum:
        raise ValueError(f'Record contract needs at least {minimum} requests and tools; replan within user limits')
    if response_limit(frozen)<4096:raise ValueError('Record contracts need at least 4096 response tokens; replan within user limits')


def validate_document(raw, contract):
    """Handoff structure only: provenance and semantic review remain separate gates."""
    from .research_quality import load_json
    family=identity(contract);data=load_json(raw)
    if family.get('validate_document'):
        family['validate_document'](data);return
    if family.get('record_role') or contract['id']=='sourcing.inventory':
        if contract['id']=='sourcing.inventory':
            from .sourcing_inventory import validate_document as validate_inventory
            validate_inventory(data);return
        from .sourcing_contract import parameters
        expected=('contract','parameters','source_versions','records','items','complete') if family['record_role']=='options' else ('contract','parameters','catalog_sha256','records','complete')
        fields(data,expected)
        if data['contract']!=contract:raise ValueError('Content contract identity mismatch')
        parameters(data['parameters'],family['record_role']=='review')
        if not isinstance(data['records'],list) or len(data['records'])>data['parameters']['max_records'] or type(data['complete']) is not bool:
            raise ValueError('Invalid sourcing record collection')
        keys=[family['validate'](r,data['parameters']) for r in data['records']]
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate sourcing record identity')
        return
    if contract['id']=='geometry.specification':
        from .rhino3dm_contract import validate
        validate(data);return
    if contract['id']=='research.audit':
        fields(data, ('summary_sha256','evidence_sha256','raw_sha256','post_count','max_posts','claims'))
        for key in ('summary_sha256','evidence_sha256','raw_sha256'):
            if not isinstance(data[key],str) or not re.fullmatch('[0-9a-f]{64}',data[key]):raise ValueError('Invalid source digest')
        if type(data['post_count']) is not int or data['post_count']<0 or (data['max_posts'] is not None and (type(data['max_posts']) is not int or data['max_posts']<data['post_count'])):raise ValueError('Invalid evidence count')
        records=data['claims'];parameters={};maximum=40
    else:
        fields(data, ('contract','parameters','records'))
        if data['contract']!=contract:raise ValueError('Content contract identity mismatch')
        parameters=data['parameters']
        (batch_parameters if contract['id']=='research.batch' else candidate_parameters)(parameters)
        records=data['records'];maximum=parameters['max_records']
    minimum=0 if contract['id']=='research.batch' else 1
    if not isinstance(records,list) or not minimum<=len(records)<=maximum:raise ValueError('Invalid bounded record collection')
    keys=[family['validate'](r,parameters) for r in records]
    if len(set(keys))!=len(keys):raise ValueError('Duplicate record identity')


def tool(contract):
    family=identity({k:contract[k] for k in ('id','version')})
    return {'name':'operation_submit','description':f'Commit at most {family["batch"]} typed records and {MAX_SUBMISSION_BYTES} UTF-8 bytes including the request envelope per call. Use the current revision and a unique request_key. Identical retries return the saved receipt; conflicting records fail. Relay assembles the declared output. Records are evidence/judgments, never user acceptance.',
        'parameters':{'type':'object','properties':{
            'request_key':{'type':'string'},'revision':{'type':'integer'},
            'records':{'type':'array','minItems':1,'maxItems':family['batch'],'items':family.get('schema_for',lambda p:family['schema'])(contract['parameters'])}},
            'required':['request_key','revision','records'],'additionalProperties':False}}


def amendment_tool(contract):
    schema=tool(contract)['parameters']['properties']['records']['items']
    return dict(name='operation_amend',description=f'Within {MAX_SUBMISSION_BYTES} UTF-8 bytes including the request envelope, correct one committed fragment with a new request key, current revision and saved record hash. Original versions remain durable; this grants no acceptance.',
        parameters=dict(type='object',properties=dict(request_key=dict(type='string'),revision=dict(type='integer'),expected_record_sha256=dict(type='string'),record=schema),
            required=['request_key','revision','expected_record_sha256','record'],additionalProperties=False))


def interface_catalog():
    """Read-only registry metadata; never serialize or invoke executable hooks."""
    result=[]
    for (ident,version),family in REGISTRY.items():
        lifecycle=family.get('lifecycle');interface=family.get('planning_interface')
        row=dict(id=ident,version=version,record_role=family.get('record_role'),
            code_owned=['input versions','identities','validation','commits','projection structure','export versions'],
            model_owned=['semantic content','source references or spans','explicit unknowns','independent judgments'])
        if family.get('schema_for'):
            builder=family['schema_for'];row['fragment_schema']=dict(builder=builder.__module__+'.'+builder.__name__,parameters='Frozen semantic parameters determine field names and extraction rules')
        elif family.get('schema'):row['fragment_schema']=family['schema']
        if family.get('native_producers'):row['native_producers']=family['native_producers']
        if lifecycle:
            row['lifecycle']={k:getattr(lifecycle,k) for k in ('resumable','rejection_resumable','amendable','export_empty','indexed','fragment_only')}
            row['hooks']={k:(getattr(lifecycle,k).__module__+'.'+getattr(lifecycle,k).__name__) for k in ('context','progress','document','complete','normalize','verify_result') if callable(getattr(lifecycle,k))}
        if interface:
            row['planning_interface']=dict(inputs=list(interface['input_parameters']),semantic_parameters=interface['schema'],merge_operation=interface['merge_operation'],
                capacity=vars(interface['capacity']),advertised=interface.get('expose',True))
            if interface.get('merge_operation'):
                from .record_transfers import contract
                row['planning_interface']['merge_transfer']=contract(family)
        result.append(row)
    return result
