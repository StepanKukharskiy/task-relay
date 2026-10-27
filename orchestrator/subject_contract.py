"""Generic subject fragments bound to one declared text, JSON or visual source."""
import copy
import hashlib
import math
import re
from . import parameter_contracts as wire

IDENTITY=dict(id='collection.subjects',version=1)
CRITERION='Independently check subject coverage, labels, attributes and uncertainty against the exact declared source; a completion seal is not acceptance.'
PARAMETERS=dict(type='object',properties=dict(
    source_path=dict(type='string',minLength=1),summary_path=dict(type='string',minLength=1),
    max_records=dict(type='integer',minimum=1,maximum=40),
    fields=dict(type='array',maxItems=12,uniqueItems=True,items=dict(type='string',pattern='^[a-z][a-z0-9_]{0,39}$'))),
    required=['source_path','summary_path','max_records','fields'],additionalProperties=False)


def obj(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def schema(p):
    return dict(anyOf=[obj(dict(kind=dict(type='string',enum=['item']),slot=dict(type='integer',minimum=1,maximum=p['max_records']),
        label=dict(type='string',minLength=1,maxLength=160),
        attributes=obj({k:dict(anyOf=[dict(type='string',minLength=1,maxLength=600),dict(type='null')]) for k in p['fields']}),
        quote=dict(type='string',maxLength=600),
        bbox=dict(anyOf=[dict(type='array',minItems=4,maxItems=4,items=dict(type='number',minimum=0,maximum=1)),dict(type='null')]),
        notes=dict(type='string',maxLength=600))),
        obj(dict(kind=dict(type='string',enum=['end']),count=dict(type='integer',minimum=0,maximum=p['max_records']),notes=dict(type='string',maxLength=600)))])


def parameters(p):
    from .contracts import relative
    wire.validate(p,PARAMETERS);relative(p['source_path']);relative(p['summary_path'])


def record(value,p,context=None):
    wire.validate(value,schema(p))
    if value['kind']=='end':return 'end'
    b=value['bbox']
    if b is not None and (not all(math.isfinite(x) for x in b) or b[0]>=b[2] or b[1]>=b[3]):raise ValueError('Invalid normalized subject box')
    if context is not None:
        visual=context['source']['media_type']=='image/png'
        if visual:
            if b is None or value['quote']:raise ValueError('Visual subjects need a box and no invented text quote')
        elif b is not None or not value['quote'].strip() or ('text' in context and value['quote'] not in context['text']):
            raise ValueError('Text subjects need a literal source quote and no visual box')
    return str(value['slot'])


def context(frozen,read):
    p=frozen['operation_contract']['parameters'];parameters(p)
    rows=[i for i in frozen['inputs'] if i['path']==p['source_path']]
    if len(rows)!=1:raise ValueError('Subject source must resolve to one declared input')
    source=rows[0];raw=read(p['source_path']);sha=hashlib.sha256(raw).hexdigest()
    if sha!=source['sha256']:raise ValueError('Subject source version changed')
    media=source.get('media_type')
    if media=='image/png':
        from .browser_contract import png_info
        if not source.get('visual_reference'):raise ValueError('Subject PNG must be declared visual')
        png_info(raw);text=''
    elif media in ('text/plain','text/markdown','application/json'):text=raw.decode('utf-8')
    else:raise ValueError('Unsupported subject source format')
    return dict(source=dict(path=source['path'],sha256=sha,media_type=media),text=text)


def document(records,p,ctx):
    items=[];end=None
    for r in records:
        record(r,p,ctx)
        if end is not None:raise ValueError('Subject records cannot follow completion')
        if r['kind']=='end':
            if r['count']!=len(items):raise ValueError('Subject seal differs from committed count')
            end=r;continue
        if r['slot']!=len(items)+1:raise ValueError('Submit consecutive subject slots')
        items.append(dict(id=f"SUB-{r['slot']:03d}",**{k:copy.deepcopy(r[k]) for k in ('label','attributes','quote','bbox','notes')}))
    return dict(contract=IDENTITY.copy(),parameters=copy.deepcopy(p),source=copy.deepcopy(ctx['source']),records=copy.deepcopy(records),
                items=items,complete=end is not None,notes=end['notes'] if end else '')


def validate_document(data):
    from .operation_contracts import fields
    fields(data,('contract','parameters','source','records','items','complete','notes'))
    if data['contract']!=IDENTITY:raise ValueError('Wrong subject contract')
    if type(data['complete']) is not bool:raise ValueError('Invalid subject completion state')
    parameters(data['parameters']);s=data['source'];fields(s,('path','sha256','media_type'))
    if s['path']!=data['parameters']['source_path'] or not isinstance(s['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',s['sha256']) or s['media_type'] not in ('text/plain','text/markdown','application/json','image/png'):raise ValueError('Invalid subject source identity')
    if not isinstance(data['records'],list) or len(data['records'])>data['parameters']['max_records']+1:raise ValueError('Invalid subject record count')
    if data!=document(data['records'],data['parameters'],dict(source=s)):raise ValueError('Subject projection differs from committed fragments')


def validate_input(data):
    """One inventory boundary for saved, deferred and executing consumers.

    Historical items projections remain readable. An arbitrary planning document
    is not a projection and must be prepared through the registered record writer.
    Never rename keys or infer subject identities from untyped prose here.
    """
    contract=data.get('contract') if isinstance(data,dict) else None
    if contract:
        from .operation_contracts import identity,validate_document as validate
        if identity(contract).get('record_role') not in ('inventory','subjects'):
            raise ValueError('Inventory input requires a registered subject contract')
        import json
        validate(json.dumps(data).encode(),contract)
        if data.get('complete') is not True:raise ValueError('Inventory input is not sealed')
    items=data.get('items') if isinstance(data,dict) else None
    if not isinstance(items,list) or len(items)>40:
        raise ValueError('Inventory handoff needs an items projection. Prepare collection.subjects from the exact source with registered content fragments; free-form planning JSON is context only.')
    seen=set()
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not 1<=len(item['id'])<=80 or not item['id'].strip():
            raise ValueError('Inventory input needs explicit bounded subject identities')
        if item['id'] in seen:raise ValueError('Duplicate inventory subject identity')
        seen.add(item['id'])
    return data


def summary(data):
    lines=['# Subjects','','Source SHA-256: '+data['source']['sha256'],'']
    for i in data['items']:
        lines.append(i['id']+': '+i['label']+'; '+str(i['attributes'])+'; '+i['notes'])
    return '\n'.join(lines+['',data['notes'],'',CRITERION])+'\n'


def validate_assignment(f):
    from .executors import API_TYPES,VISION_FILE_TYPES,request_limit,response_limit
    p=f['operation_contract']['parameters'];parameters(p)
    backend=f.get('backend',f.get('worker',{}).get('backend',{}))
    if f.get('tools')!=['files'] or backend.get('type') not in API_TYPES or f.get('execution') or f.get('browser') or f.get('computer') or f.get('review_of'):raise ValueError('Subjects require a declared-file API producer')
    rows=[i for i in f['inputs'] if i['path']==p['source_path']]
    if len(rows)!=1 or rows[0].get('media_type') not in ('text/plain','text/markdown','application/json','image/png'):raise ValueError('Declare a supported subject source')
    if rows[0].get('media_type')=='image/png' and (backend['type'] not in VISION_FILE_TYPES or not rows[0].get('visual_reference')):raise ValueError('Visual subjects require a vision worker and visual input')
    if not {p['summary_path'],f['operation_contract']['output']}<={o['path'] for o in f['outputs']} or p['summary_path']==f['operation_contract']['output']:raise ValueError('Subjects need separate JSON and summary outputs')
    if min(request_limit(f),f['limits']['tool_calls'])<p['max_records']+3 or response_limit(f)<4096:raise ValueError('Subjects exceed frozen fragment/finalization capacity')


def progress(store,records):
    doc=store.document(records)
    return dict(next_slot=len(doc['items'])+1,sealed=doc['complete'],source=doc['source'],remaining=0 if doc['complete'] else store.contract['parameters']['max_records']-len(doc['items'])+1)


def projection(store,records):return document(records,store.contract['parameters'],store.context())
def summaries(store,records):return {store.contract['parameters']['summary_path']:summary(store.document(records)).encode()}
