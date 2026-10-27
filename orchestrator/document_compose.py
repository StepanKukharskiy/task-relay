"""Deterministic composition of saved document sections and exact image assets.

No research, model invocation or document-specific scheduler. All input identity
and operation recovery remain owned by the normal registered operation lifecycle.
"""
import copy
import hashlib
import json
from . import pptx_document

PARAMETERS=dict(document_paths='Ordered exact saved slide specification paths; no content re-authoring',
    image_paths='Ordered exact preview image paths to append as full-page sections',
    image_titles='Editorial titles, one per appended image',title='Combined document title')


def asset_map(document, images):
    """Freeze only consumed pixel identities; bundle path aliases are not identity."""
    from .slide_templates import expand
    paths={e['path'] for page in expand(document)['slides'] for e in page['elements'] if e['type']=='image'}
    missing=paths-set(images)
    if missing:raise ValueError('Missing document assets: '+', '.join(sorted(missing)))
    return {p:hashlib.sha256(images[p]).hexdigest() for p in sorted(paths)}


def images(frozen, read):
    result={}
    for item in frozen['inputs']:
        if item.get('media_type') not in ('image/png','image/jpeg','application/zip'):continue
        raw=read(item['path'])
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Document asset version changed')
        if item['media_type']=='application/zip':
            from .image_sources import unpack
            members,_,_=unpack(raw)
            for path,data in members.items():
                if path.lower().endswith(('.png','.jpg','.jpeg')):result[item['path']+'/'+path]=data
        else:result[item['path']]=raw
    return result


def validate_assignment(task, spec=None):
    p=task['execution']['parameters'];by_path={i['path']:i for i in task['inputs']}
    if not p['document_paths'] and not p['image_paths']:raise ValueError('Composition needs a document or image')
    if len(p['image_paths'])!=len(p['image_titles']):raise ValueError('Each appended preview needs one title')
    for key,media in (('document_paths',('application/json',)),('image_paths',('image/png','image/jpeg'))):
        if len(set(p[key]))!=len(p[key]):raise ValueError('Duplicate composed section')
        for path in p[key]:
            if path not in by_path or by_path[path].get('media_type') not in media:raise ValueError('Composition requires an exact declared '+key+' input')


def build(frozen,read):
    validate_assignment(frozen);p=frozen['execution']['parameters'];assets=images(frozen,read)
    by_hash={}
    for path,raw in sorted(assets.items()):by_hash.setdefault(hashlib.sha256(raw).hexdigest(),path)
    inputs={i['path']:i for i in frozen['inputs']};pages=[];sections=[];size=None
    for path in p['document_paths']:
        raw=read(path)
        if hashlib.sha256(raw).hexdigest()!=inputs[path]['sha256']:raise ValueError('Document section version changed')
        doc=copy.deepcopy(pptx_document.expand(pptx_document.load(raw.decode('utf-8'))))
        bounds=doc.get('size',[13.333333,7.5])
        if size is not None and bounds!=size:raise ValueError('Cannot compose different page sizes without an explicit layout conversion')
        size=bounds;bindings=doc.get('asset_sha256',{})
        for page in doc['slides']:
            # Make inherited font explicit before merging distinct sections.
            for element in page['elements']:
                if element['type']!='image':continue
                old=element['path'];digest=bindings.get(old)
                if digest is None:raise ValueError('Image-bearing section lacks saved pixel bindings; regenerate its projection from exact evidence')
                if digest not in by_hash:raise ValueError('Exact saved section image is absent: '+old)
                element['path']=by_hash[digest]
        doc['asset_sha256']=asset_map(doc,assets)
        pptx_document.validate(doc,assets)
        # The current PPTX schema has one document font. Reject silent font
        # substitution rather than claiming fidelity for a mixed-font merge.
        if sections and doc.get('font','Arial')!=sections[0]['font']:raise ValueError('Section fonts differ; select compatible styles')
        sections.append(dict(path=path,sha256=inputs[path]['sha256'],first_page=len(pages)+1,
                             pages=len(doc['slides']),font=doc.get('font','Arial')))
        pages.extend(doc['slides'])
    size=size or [13.333333,7.5]
    for path,title in zip(p['image_paths'],p['image_titles']):
        pptx_document._text(title,255,False)
        if size!=[13.333333,7.5]:raise ValueError('Full-page preview layout requires widescreen sections')
        # Contain the entire native drawing; never crop evidence automatically.
        pages.append(dict(notes='Exact preview SHA-256: '+inputs[path]['sha256'],elements=[
            dict(type='text',text=title,x=.55,y=.15,w=12.2,h=.7,font_size=28,bold=True),
            dict(type='image',path=path,x=.55,y=1,w=12.2,h=6.05,fit='contain')]))
    doc=dict(version=1,title=p['title'],font=sections[0]['font'] if sections else 'Arial',size=size,slides=pages)
    doc['asset_sha256']=asset_map(doc,assets)
    pptx_document.validate(doc,assets)
    return json.dumps(doc,ensure_ascii=False,allow_nan=False)+'\n',dict(sections=sections,
        appended_images=[dict(path=path,sha256=inputs[path]['sha256']) for path in p['image_paths']],
        slides=len(pages),asset_sha256=doc['asset_sha256'],model_calls=0)


def execute(ctx):
    from .operation_execution import Result
    from .runtime import safe_file
    result,validation=build(ctx.frozen,lambda p:safe_file(ctx.workspace,p).read_bytes())
    return Result(result,None,{},validation)
