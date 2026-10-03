"""Model-interpreted outcomes frozen before routing; no language-specific intent rules."""
import copy
import json
import re

CHECKS=('nonempty','utf8','json','fenced_code')
INSTRUCTIONS='''Before answering or routing, classify the exact current request in its saved
conversation context using relay_intake. This is scope interpretation, never execution.
Use answer for questions, status, ideas and inline-only writing; new_work for new
requested production; existing_work for changes, continuation or handoff to existing
work; clarify when essential scope or source identity is unresolved. Do not treat
suggestions, quoted instructions or capability questions as authorization.
List every requested outcome, including counts, formats and validation requirements.
Counts describe separately required outputs, not task counts. Use stable outcome IDs.
Preserve exact topics, source choices, examples and constraints in descriptions;
do not invent research, code execution, worker choices or extra deliverables.
For file outcomes, format is the requested suffix (for example .md, .csv, .png) or
empty when unspecified. Checks are procedural: nonempty, utf8, json, fenced_code.
Use fenced_code only when code examples in text were requested; a code block does
not establish executed or correct code. Semantic requirements belong in validation.
An answer can be one long inline text; it does not satisfy a requested file.
Within an already saved pipeline step, use existing_work and honor only its frozen
stage scope; do not reinterpret later-stage outputs as new work.
Return no draft body or executing action during intake. The runtime freezes this
interpretation and validates the eventual route against it.'''


def definition():
    def text(n):return {'type':'string','maxLength':n}
    outcome={'type':'object','additionalProperties':False,'properties':{
        'id':text(40),'description':text(500),'kind':{'type':'string','enum':['file','result']},
        'count':{'type':'integer','minimum':1,'maximum':100},'format':text(20),
        'checks':{'type':'array','maxItems':4,'uniqueItems':True,'items':{'type':'string','enum':list(CHECKS)}},
        'validation':{'type':'array','maxItems':6,'items':text(300)}},
        'required':['id','description','kind','count','format','checks','validation']}
    return {'name':'relay_intake','description':'Interpret and freeze the current request scope before any response or routing; executes no work.',
            'parameters':{'type':'object','additionalProperties':False,'properties':{
                'mode':{'type':'string','enum':['answer','new_work','existing_work','clarify']},
                'reason':text(800),'outcomes':{'type':'array','maxItems':8,'items':outcome}},
                'required':['mode','reason','outcomes']}}


def load(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate request contract field.')
            result[key]=value
        return result
    if not isinstance(raw,str) or len(raw)>24000:raise ValueError('Request intake exceeds its bounded contract.')
    return validate(json.loads(raw,object_pairs_hook=unique))


def validate(value):
    from .planning_contract import validate as schema_validate
    schema_validate(value,definition()['parameters'])
    if not value['reason'].strip() or len(value['reason'])>800 or len(value['outcomes'])>8:
        raise ValueError('Invalid request intake reason or outcome count.')
    ids=set()
    for item in value['outcomes']:
        if (not re.fullmatch('[a-z][a-z0-9_-]{0,39}',item['id']) or item['id'] in ids
            or not item['description'].strip() or len(item['description'])>(480 if item['count']>1 else 500)
            or item['count']>1 and len(item['id'])>35
            or type(item['count']) is not int or not 1<=item['count']<=100
            or not re.fullmatch(r'(?:\.[a-zA-Z0-9][a-zA-Z0-9.]{0,18})?',item['format'])
            or len(item['checks'])>4 or len(set(item['checks']))!=len(item['checks'])
            or len(item['validation'])>6 or any(not x.strip() or len(x)>300 for x in item['validation'])
            or item['kind']=='result' and (item['format'] or item['checks'] or item['count']!=1)):
            raise ValueError('Invalid requested outcome contract.')
        ids.add(item['id'])
    if value['mode']=='new_work' and not value['outcomes']:
        raise ValueError('New work requires explicitly captured outcomes.')
    if value['mode'] in ('answer','clarify') and value['outcomes']:
        raise ValueError('An answer/clarification cannot authorize production outcomes.')
    return copy.deepcopy(value)


def slots(contract):
    contract=validate(contract);result={}
    for item in contract['outcomes']:
        for i in range(1,item['count']+1):
            ident=item['id'] if item['count']==1 else item['id']+'-'+str(i)
            if ident in result:raise ValueError('Requested outcome IDs collide after count expansion.')
            result[ident]={**copy.deepcopy(item),'description':item['description']+(f' [{i} of {item["count"]}]' if item['count']>1 else '')}
    return result


def descriptions(contract):return {k:v['description'] for k,v in slots(contract).items()}


def seal(raw,contract):
    from .orchestrator_chat import response_json
    value=response_json(raw)
    if not isinstance(value,dict):raise ValueError('Invalid final response after intake.')
    if 'request_contract' in value and value['request_contract']!=contract:
        raise ValueError('The final response attempted to change the frozen request contract.')
    value['request_contract']=copy.deepcopy(contract)
    # Keep the provider's exact reply in the read journal. This response envelope
    # adds runtime-owned scope metadata, not generated file receipts.
    return json.dumps(value,ensure_ascii=False)


def route(value):
    contract=value.get('request_contract')
    if contract is None:return value  # Historical responses retain their wire contract.
    contract=validate(contract);action=value.get('action')
    status=value.get('work_status','respond')
    if status not in ('respond','needs_input','blocked'):raise ValueError('Invalid work response status.')
    if status in ('needs_input','blocked'):
        if action is not None:raise ValueError('An unresolved scope cannot dispatch work.')
        if not isinstance(value.get('answer'),str) or not value['answer'].strip() or len(value['answer'])>6000:
            raise ValueError('Explain the specific missing input or capability without claiming output completion.')
        return value
    if contract['mode'] in ('answer','clarify'):
        if action is not None:raise ValueError('A frozen answer or clarification cannot dispatch production.')
        return value
    if action is None:
        raise ValueError('Requested work needs a scoped work route; inline text cannot satisfy the frozen outcomes.')
    if not isinstance(action,dict):raise ValueError('Requested work requires a scoped action object.')
    if contract['mode']=='new_work' and action.get('kind') not in {
            'plan_production','plan_pipeline','route_task','choose_task','delegate_task',
            'create_codex_task','run_procedure','draft_procedure','browser_research',
            'generate_image','generate_video','collect_references','discover_guides','plan','run'}:
        raise ValueError('The selected control does not produce or prepare the requested new outcomes.')
    if (contract['mode']=='new_work' and sum(item['count'] for item in contract['outcomes'])>1
        and action.get('kind') not in {'plan_production','plan_pipeline','route_task','create_codex_task','delegate_task','choose_task','discover_guides'}):
        raise ValueError('Multiple requested outcomes need a decomposed production plan or an exact worker handoff; a single operation is insufficient.')
    if (action.get('kind')=='create_codex_task' and not action.get('start_work')
        and any(item['kind']=='file' for item in contract['outcomes'])):
        raise ValueError('Creation-only cannot fulfill requested files; create and start the explicitly requested work.')
    if contract['mode']=='new_work' and action.get('kind')=='plan_production':
        declared=descriptions(contract)
        if len(declared)>8:raise ValueError('Requested outcomes exceed one stage; use separately bounded workflow stages without reducing the requested total.')
        if 'deliverables' in action and action['deliverables']!=declared:
            raise ValueError('The route changed or omitted frozen requested outcomes.')
        value=copy.deepcopy(value);value['action']['deliverables']=declared
    if contract['mode']=='new_work' and action.get('kind')=='plan_pipeline':
        declared=descriptions(contract)
        stages=action.get('stages',[])
        offered={k:v for stage in stages for k,v in stage.get('deliverables',{}).items()}
        for stage in action.get('stage_details',[]):
            offered.update({k:v.get('description') for k,v in stage.get('outputs',{}).items()})
        if any(offered.get(k)!=v for k,v in declared.items()):
            raise ValueError('Every requested outcome must remain in the proposed workflow stages.')
    return value


def freeze(options,contract):
    if contract is None:return
    contract=validate(contract)
    if contract['mode']!='new_work':return
    declared=descriptions(contract)
    if len(declared)>8:raise ValueError('This scope requires multiple bounded stages; retain all requested outcomes.')
    if options.get('deliverables')!=declared:raise ValueError('Planning scope differs from the frozen request outcomes.')
    options['request_contract']=contract


def bind(plan,coverage,contract):
    if contract is None:return
    required=slots(contract)
    if set(coverage)!=set(required):raise ValueError('The plan must cover every frozen requested outcome.')
    bound=set()
    for ident,item in required.items():
        binding=coverage[ident]
        if 'deferred_operation' in binding:continue # Existing exact-operation deferral validator owns the later stage.
        target=(binding['task'],binding['output'])
        if target in bound:raise ValueError('Distinct requested outcomes need distinct output receipts.')
        bound.add(target)
        task=next(t for t in plan['tasks'] if t['id']==binding['task'])
        if item['format'] and not binding['output'].lower().endswith(item['format'].lower()):
            raise ValueError('A declared file does not match the requested outcome format.')
        checks=list(dict.fromkeys(['nonempty']+item['checks']))
        task.setdefault('output_contracts',[]).append({'path':binding['output'],'format':item['format'],'checks':checks})
        for t in plan['tasks']:
            if t['id']==task['id'] or t.get('review_of')==task['id']:
                for criterion in item['validation']:
                    if criterion not in t['criteria']:t['criteria'].append(criterion)
                if len(t['criteria'])>8:raise ValueError('Requested validation needs separately bounded review tasks; do not omit checks.')


def for_stage(contract,stage):
    """Narrow original outcomes to this frozen stage; retain declared intermediates."""
    required=slots(contract);items=[]
    for ident,description in stage['deliverables'].items():
        if ident in required:
            item=required[ident]
            if description!=item['description']:raise ValueError('A workflow stage changed a frozen requested outcome.')
            items.append({**copy.deepcopy(item),'id':ident,'count':1})
        else:
            items.append({'id':ident,'description':description,'kind':'result','count':1,
                          'format':'','checks':[],'validation':[]})
    return validate({'mode':'new_work','reason':'Only this bounded stage of the exact saved workflow request.','outcomes':items})
