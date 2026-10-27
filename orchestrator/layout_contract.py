"""Bounded layout/content fragments on the shared transactional record engine."""
import copy
import hashlib
from . import parameter_contracts as wire
from .contracts import digest
from . import slide_templates, pptx_document

IDENTITY=dict(id='document.layout',version=1)


def producer_defaults(task,maximum):
    return dict(renderer='pptx.create',title=task['objective'][:pptx_document.TITLE_MAX],style='clean_minimal_v1',max_records=min(maximum,40))


def obj(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


PARAMETERS=obj(dict(renderer=dict(type='string',enum=['pptx.create']),title=dict(type='string',minLength=1,maxLength=pptx_document.TITLE_MAX),
    style=dict(type='string',enum=list(slide_templates.STYLES)),max_records=dict(type='integer',minimum=1,maximum=40)))


def parameters(value):
    wire.validate(value,PARAMETERS)


def schema(p):
    string=dict(type='string',maxLength=4000)
    content_types={
        'text':string,'image':dict(type='string',minLength=1,maxLength=500),
        'table':dict(type='array',minItems=1,maxItems=20,items=dict(type='array',minItems=1,maxItems=10,items=dict(type='string',maxLength=300))),
        'chart':obj(dict(chart=dict(type='string',enum=['column','bar','line']),
            categories=dict(type='array',minItems=1,maxItems=50,items=string),
            series=dict(type='array',minItems=1,maxItems=8,items=obj(dict(name=string,values=dict(type='array',minItems=1,maxItems=50,items=dict(type='number'))))))) }
    layouts={name:obj({slot['slot']:content_types[slot['type']] for slot in slots}) for name,slots in slide_templates.CATALOG.items()}
    layouts['table']=obj(dict(title=dict(type='string',minLength=1,maxLength=90),rows=content_types['table'],caption=dict(type='string',maxLength=250)))
    layouts['image_grid']=obj(dict(title=dict(type='string',minLength=1,maxLength=70),
        items=dict(type='array',minItems=1,maxItems=120,items=obj(dict(image=content_types['image'],
            label=dict(type='string',maxLength=60),caption=dict(type='string',maxLength=80),credit=dict(type='string',maxLength=2000)))),
        per_page=dict(type='integer',enum=[1,4,6]),fit=dict(type='string',enum=['contain','cover'])))
    layouts['content_cards']=obj(dict(title=dict(type='string',minLength=1,maxLength=70),
        items=dict(type='array',minItems=1,maxItems=120,items=obj(dict(
            label=dict(type='string',minLength=1,maxLength=80),body=dict(type='string',minLength=1,maxLength=900),
            image=dict(anyOf=[content_types['image'],dict(type='null')]),
            link=dict(anyOf=[dict(type='string',minLength=1,maxLength=4096),dict(type='null')]),
            credit=dict(type='string',maxLength=2000)))),per_page=dict(type='integer',enum=[1,3])))
    # References retain immutable baseline pages; the model never supplies their
    # geometry. A replacement uses one of the existing registered layouts.
    layouts['saved_page']=obj(dict(page=dict(type='integer',minimum=1,maximum=40)))
    variants=[obj(dict(kind=dict(type='string',enum=['page']),slot=dict(type='integer',minimum=1,maximum=p['max_records']),
        layout=dict(type='string',enum=[name]),content=content,notes=dict(type='string',maxLength=4000))) for name,content in layouts.items()]
    variants.append(obj(dict(kind=dict(type='string',enum=['end']),count=dict(type='integer',minimum=1,maximum=p['max_records']))))
    return dict(anyOf=variants)


def document(records,p):
    slides=[];sealed=False
    for value in records:
        wire.validate(value,schema(p))
        if sealed:raise ValueError('Layout records cannot follow the completion seal')
        if value['kind']=='end':
            if value['count']!=len(slides):raise ValueError('Layout seal differs from the committed content count')
            sealed=True;continue
        if value['slot']!=len(slides)+1:raise ValueError('Submit consecutive layout content slots')
        slides.append({k:copy.deepcopy(value[k]) for k in ('layout','content','notes')})
    return dict(version=2,title=p['title'],style=p['style'],slides=slides)


def image_paths(doc):
    return [e['path'] for s in slide_templates.expand(doc)['slides'] for e in s['elements'] if e['type']=='image']


def record(value,p,context=None):
    wire.validate(value,schema(p))
    if value['kind']=='end':return 'end'
    if value['layout']=='saved_page':
        if context is not None and value['content']['page']>len(context.get('baseline',{}).get('slides',[])):
            raise ValueError('Saved page is outside the exact revision baseline')
        return str(value['slot'])
    doc=dict(version=2,title=p['title'],style=p['style'],slides=[{k:value[k] for k in ('layout','content','notes')}])
    expanded=slide_templates.expand(doc)
    # Geometry belongs to registered layouts. Inputs remain exact staged assets;
    # URLs, invented paths and caller-defined slot coordinates are never accepted.
    paths=context['images'] if context is not None else image_paths(doc)
    pptx_document.validate(expanded,paths)
    return str(value['slot'])


def context(frozen,read):
    images={};bundles={}
    from .artifact_roles import content_inputs
    for item in content_inputs(frozen):
        raw=read(item['path'])
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Layout source version changed')
        if item.get('media_type') in ('image/png','image/jpeg'):images[item['path']]=raw
        elif item.get('media_type')=='application/zip':bundles[item['path']]=raw
    if bundles:
        from .image_sources import unpack
        for path,raw in bundles.items():
            members,credits,manifest=unpack(raw)
            # The existing renderer independently verifies the bundle and each
            # association; expose only validated image members to the fragment.
            for name,data in members.items():
                if name.lower().endswith(('.png','.jpg','.jpeg')):images[path+'/'+name]=data
    result=dict(images=images)
    route=frozen.get('work_tools',{}).get('intent',{})
    if route.get('mode')=='revise':
        import json
        item=next(i for i in frozen['inputs'] if i['path']==route['baseline'])
        raw=read(item['path'])
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Layout baseline version changed')
        baseline=pptx_document.expand(json.loads(raw))
        if len(baseline['slides'])>frozen['operation_contract']['parameters']['max_records']:
            raise ValueError('Saved pages exceed the unchanged layout content ceiling')
        by_hash={hashlib.sha256(data).hexdigest():path for path,data in images.items()}
        bindings=baseline.get('asset_sha256',{})
        for page in baseline['slides']:
            for element in page['elements']:
                if element['type']!='image':continue
                sha=bindings.get(element['path'])
                if sha not in by_hash:raise ValueError('Exact baseline image is absent from revision assets')
                element['path']=by_hash[sha]
        from .document_compose import asset_map
        baseline['asset_sha256']=asset_map(baseline,images)
        pptx_document.validate(baseline,images)
        result.update(baseline=baseline,baseline_sha256=item['sha256'])
    return result


def initial_records(store):
    baseline=store.context().get('baseline')
    if baseline is None:return []
    records=[dict(kind='page',slot=n,layout='saved_page',content=dict(page=n),notes=p.get('notes',''))
             for n,p in enumerate(baseline['slides'],1)]
    return records+[dict(kind='end',count=len(records))]


def projection(store,records):
    doc=document(records,store.contract['parameters'])
    context=store.context()
    if any(s['layout']=='saved_page' for s in doc['slides']):
        baseline=context.get('baseline')
        if baseline is None:raise ValueError('Saved pages require an explicit exact revision baseline')
        pages=[]
        for slide in doc['slides']:
            if slide['layout']=='saved_page':
                n=slide['content']['page']
                if n>len(baseline['slides']):raise ValueError('Saved page is outside the exact revision baseline')
                page=copy.deepcopy(baseline['slides'][n-1]);page['notes']=slide['notes'];pages.append(page)
            else:
                if baseline.get('size',[13.333333,7.5])!=[13.333333,7.5] or baseline.get('font','Arial')!='Arial':
                    raise ValueError('Registered replacement layout is incompatible with baseline size or font')
                pages.extend(slide_templates.expand({**doc,'slides':[slide]})['slides'])
        doc={**copy.deepcopy(baseline),'title':doc['title'],'slides':pages}
    if doc['slides']:
        from .document_compose import asset_map
        doc['asset_sha256']=asset_map(doc,context['images'])
        pptx_document.validate(pptx_document.expand(doc),context['images'])
    return doc


def complete(store,records):
    projection(store,records)
    return bool(records) and records[-1]['kind']=='end'


def progress(store,records):
    doc=projection(store,records)
    return dict(next_slot=len(doc['slides'])+1,sealed=complete(store,records),
        image_paths=sorted(store.context()['images']),
        editable=[dict(slot=r.get('slot'),record_sha256=digest(r)) for r in records if r['kind']=='page'],
        rendered_pages=len(pptx_document.expand(doc)['slides']) if doc['slides'] else 0,
        baseline_sha256=store.context().get('baseline_sha256'))


def validate_document(value):
    if value.get('version')!=2:raise ValueError('Document content must use registered layouts')
    if set(value)-{'version','title','style','slides','asset_sha256'}:raise ValueError('Layout content cannot override registered geometry or brand')
    if value.get('style') not in slide_templates.STYLES:raise ValueError('Unknown registered layout style')
    pptx_document.validate(slide_templates.expand(value),image_paths(value))


def validate_assignment(frozen):
    from .executors import FILE_TYPES,request_limit
    p=frozen['operation_contract']['parameters'];parameters(p)
    backend=frozen.get('backend',frozen.get('worker',{}).get('backend',{}))
    if (not (backend.get('type') in FILE_TYPES and frozen.get('tools')==['files'] or backend.get('type')=='codex-cli' and frozen.get('tools')==['files','shell'])
            or frozen.get('execution') or frozen.get('review_of')):
        raise ValueError('Layout content uses a declared-file worker, without custom code')
    if frozen.get('work_tools'):
        from .worker_tools import validate_assignment
        validate_assignment(frozen)
    outputs=frozen['outputs'][:1] if frozen.get('work_tools') else frozen['outputs']
    if outputs!=[dict(path=frozen['operation_contract']['output'],purpose=frozen['outputs'][0]['purpose'],
                              media_type='application/json',content_contract=IDENTITY.copy())]:
        raise ValueError('Layout content requires exactly one code-owned JSON projection')
    reserved=9 if frozen.get('work_tools') else 2
    ceiling=min(request_limit(frozen),frozen['limits']['tool_calls'])
    from .operation_contracts import identity
    import math
    batch=identity(IDENTITY)['batch']
    submissions=math.ceil((p['max_records']+1)/batch)
    if ceiling<submissions+reserved:
        raise ValueError('Layout fragments exceed the existing request/tool allowance; use fewer content groups. '
            f"Requested {p['max_records']} groups and explicit seal need {submissions} batched submissions plus {reserved} reserved calls; allowance {ceiling}.")
