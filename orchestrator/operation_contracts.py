"""Shared, versioned content contracts. Job data never supplies executable validators."""
import hashlib
import json
import re
import copy


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
    return {'name':'operation_submit','description':'Commit a small typed record batch. Use the current revision and a unique request_key. Identical retries return the saved receipt; conflicting records fail. Relay assembles the declared output. Records are evidence/judgments, never user acceptance.',
        'parameters':{'type':'object','properties':{
            'request_key':{'type':'string'},'revision':{'type':'integer'},
            'records':{'type':'array','minItems':1,'maxItems':family['batch'],'items':family['schema']}},
            'required':['request_key','revision','records'],'additionalProperties':False}}
