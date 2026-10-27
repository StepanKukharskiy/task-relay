"""Typed visual observations; code owns IDs, source identity and inventory files."""
import hashlib
import math
import re
from .sourcing_contract import obj, bounded_text

ITEM_SCHEMA=obj({'kind':{'type':'string','enum':['item']},'slot':{'type':'integer'},
    'label':{'type':'string','maxLength':160},'category':{'type':'string','enum':['furniture','lighting','rug','accessory','built_in']},
    'bbox':{'type':'array','description':'[left, top, right, bottom], each normalized to 0–1; left < right and top < bottom.',
            'minItems':4,'maxItems':4,'items':{'type':'number','minimum':0,'maximum':1}},
    'confidence':{'type':'string','enum':['high','medium','low']},'notes':{'type':'string','maxLength':600}})
END_SCHEMA=obj({'kind':{'type':'string','enum':['end']},'count':{'type':'integer'},'notes':{'type':'string','maxLength':600}})
SCHEMA={'anyOf':[ITEM_SCHEMA,END_SCHEMA]}
CRITERION='Independently inspect the exact room-image pixels and check inventory labels, bounding boxes, omissions and uncertainty; metadata alone is insufficient.'
PLANNING_CRITERIA=[
    'Fulfil the exact user-requested inventory scope from the supplied image, including requested furniture, lighting and textiles; disclose omissions and uncertainty without inventing unseen objects.',
    'Use actual observed subject labels and descriptions, never placeholders or schema-probing records as deliverables.',
    'Follow sourcing.inventory v1: bbox is [left, top, right, bottom], normalized to 0–1. Code validates serialization, identities and completion; proposed or historical alternative coordinate conventions are not requirements.',
    'Check that each included label and bounding box corresponds to the exact image pixels, and that the numbered notes accurately describe the committed records.'
]

def parameters(p):
    from .operation_contracts import fields
    from .contracts import relative
    fields(p,('image_path','max_records','summary_path'))
    relative(p['image_path']);relative(p['summary_path'])
    if type(p['max_records']) is not int or not 1<=p['max_records']<=40:raise ValueError('Inventory capacity must be 1–40')

def record(r,p,context=None):
    from .operation_contracts import fields
    if not isinstance(r,dict):raise ValueError('Inventory record must be an object')
    if r.get('kind')=='end':
        fields(r,('kind','count','notes'));bounded_text(r['notes'],600)
        if type(r['count']) is not int or not 0<=r['count']<=p['max_records']:raise ValueError('Invalid inventory completion count')
        return 'end'
    fields(r,('kind','slot','label','category','bbox','confidence','notes'))
    if r['kind']!='item' or type(r['slot']) is not int or not 1<=r['slot']<=p['max_records']:raise ValueError('Invalid inventory slot')
    bounded_text(r['label'],160);bounded_text(r['notes'],600,empty=True)
    if r['category'] not in ITEM_SCHEMA['properties']['category']['enum'] or r['confidence'] not in ('high','medium','low'):raise ValueError('Invalid visual observation category/confidence')
    b=r['bbox']
    if not isinstance(b,list) or len(b)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in b) or b[0]>=b[2] or b[1]>=b[3]:raise ValueError('Inventory bbox must be normalized left,top,right,bottom')
    return str(r['slot'])

def context(frozen,read):
    p=frozen['operation_contract']['parameters'];parameters(p)
    matches=[i for i in frozen['inputs'] if i['path']==p['image_path']]
    if len(matches)!=1 or not matches[0].get('visual_reference') or matches[0].get('media_type')!='image/png':raise ValueError('Inventory requires exact declared visual PNG input')
    raw=read(p['image_path'])
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=matches[0]['sha256']:raise ValueError('Inventory image version changed')
    from .browser_contract import png_info
    return dict(image=dict(path=p['image_path'],sha256=sha,**png_info(raw)))

def document(records,p,ctx):
    items=[];end=None
    for r in records:
        record(r,p)
        if end is not None:raise ValueError('Inventory records cannot follow completion')
        if r['kind']=='end':
            if r['count']!=len(items):raise ValueError('Inventory completion count differs from committed items')
            end=r;continue
        if r['slot']!=len(items)+1:raise ValueError('Inventory must submit next consecutive slot')
        items.append(dict(id=f"VIS-{r['slot']:03d}",**{k:r[k] for k in ('label','category','bbox','confidence','notes')}))
    return dict(contract=dict(id='sourcing.inventory',version=1),parameters=p,image=ctx['image'],
                records=records,items=items,complete=end is not None,notes=end['notes'] if end else '')

def validate_document(data):
    from .operation_contracts import fields
    fields(data,('contract','parameters','image','records','items','complete','notes'))
    if data['contract']!=dict(id='sourcing.inventory',version=1):raise ValueError('Wrong inventory contract')
    parameters(data['parameters'])
    image=data['image'];fields(image,('path','sha256','width','height','media_type','visual_content_inspected'))
    if (image['path']!=data['parameters']['image_path'] or not isinstance(image['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',image['sha256'])
            or image['media_type']!='image/png' or image['visual_content_inspected'] is not False
            or any(type(image[k]) is not int or not 1<=image[k]<=4096 for k in ('width','height'))
            or image['width']*image['height']>8000000):raise ValueError('Invalid inventory image identity')
    if not isinstance(data['records'],list) or len(data['records'])>data['parameters']['max_records']+1:raise ValueError('Invalid inventory records')
    if data!=document(data['records'],data['parameters'],dict(image=data['image'])):raise ValueError('Inventory differs from committed visual fragments')

def summary(data):
    lines=['# Visual inventory','', 'Image SHA-256: '+data['image']['sha256'],'']
    for i in data['items']:lines.append(f"{i['id']}: {i['label']} ({i['category']}, {i['confidence']}); bbox={i['bbox']}; {i['notes']}")
    return '\n'.join(lines+['',data['notes'],'','Labels and boxes are visual judgments requiring independent review.'])+'\n'

def validate_assignment(frozen):
    from .executors import VISION_FILE_TYPES,request_limit,response_limit
    p=frozen['operation_contract']['parameters'];parameters(p)
    backend=frozen.get('backend',frozen.get('worker',{}).get('backend',{}))
    if frozen.get('tools')!=['files'] or backend and backend.get('type') not in VISION_FILE_TYPES or frozen.get('execution') or frozen.get('browser') or frozen.get('computer') or frozen.get('review_of'):raise ValueError('Inventory requires a declared-file vision API producer')
    if p['image_path'] not in {i['path'] for i in frozen['inputs'] if i.get('visual_reference') and i.get('media_type')=='image/png'}:raise ValueError('Inventory image must be a declared visual PNG')
    if not {p['summary_path'],frozen['operation_contract']['output']}<={o['path'] for o in frozen['outputs']} or p['summary_path']==frozen['operation_contract']['output']:raise ValueError('Inventory requires separate code-owned JSON and Markdown')
    if min(request_limit(frozen),frozen['limits']['tool_calls'])<p['max_records']+3 or response_limit(frozen)<4096:raise ValueError('Inventory capacity exceeds frozen request/tool allowance; reserve seal and finish')
