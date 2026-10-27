"""Versioned, data-only layouts compiled to the existing editable slide schema."""
import copy
from .handoff_contracts import PPTX_SLIDES


def text(slot, x, y, w, h, role='body'):
    return dict(type='text', slot=slot, x=x, y=y, w=w, h=h, role=role)


HEADER = text('title', .6, .4, 12.1, 1.0, 'heading')
CATALOG = {
    'title': [text('title', .8, 2, 11.7, 1.6, 'heading'), text('subtitle', .8, 3.9, 11.7, 1.5)],
    'section': [text('title', .8, 2.6, 11.7, 1.6, 'heading'), text('subtitle', .8, 4.3, 11.7, 1.2)],
    'text': [HEADER, text('body', .6, 1.5, 12.1, 5.1)],
    'two_columns': [HEADER, text('left', .6, 1.5, 5.85, 5.1), text('right', 6.85, 1.5, 5.85, 5.1)],
    'image_text': [HEADER, dict(type='image',slot='image',x=.6,y=1.5,w=6.1,h=4.6),
                   text('caption', .6, 6.15, 6.1, .85, 'caption'), text('body', 7, 1.5, 5.7, 5.1)],
    'table': [HEADER, dict(type='table',slot='rows',x=.6,y=1.5,w=12.1,h=4.8), text('caption',.6,6.4,12.1,.4,'caption')],
    'chart': [HEADER, dict(type='chart',slot='chart',x=.6,y=1.5,w=12.1,h=4.8), text('caption',.6,6.4,12.1,.4,'caption')],
}
# Named/versioned defaults stay stable for saved specifications.
STYLES = {'clean_minimal_v1': {'body_font':'Arial', 'heading_font':'Arial',
          'background':'FFFFFF', 'text':'272727', 'accent':'202020'}}
COLLECTION_LAYOUTS = {'image_grid': {'required':['title','items'],
    'optional':['per_page','fit'], 'per_page':[1,4,6], 'default_per_page':6,
    'item':{'required':['image','label'], 'optional':['caption','credit']}}}
COLLECTION_LAYOUTS['content_cards']={'required':['title','items'],'optional':['per_page'],
    'per_page':[1,3],'default_per_page':1,
    'item':{'required':['label','body'],'optional':['image','link','credit']}}


def card_pages(source,brand):
    """Paginated evidence cards: native links and images, fixed readable boxes."""
    from .pptx_document import _object, _text, _hyperlink
    content=source['content'];_object(content,('title','items'),('per_page',))
    _text(content['title'],70,False)
    if '\n' in content['title']:raise ValueError('Card title must be one line')
    count=content.get('per_page',1)
    if type(count) is not int or count not in (1,3):raise ValueError('Cards require 1 or 3 items per page')
    items=content['items']
    if not isinstance(items,list) or not 1<=len(items)<=120:raise ValueError('Cards require 1–120 items')
    for item in items:
        _object(item,('label','body'),('image','link','credit'))
        _text(item['label'],80,False);_text(item['body'],900 if count==1 else 300,False)
        _text(item.get('credit',''),2000)
        if item.get('image') is not None:_text(item['image'],500,False)
        if item.get('link') is not None:_hyperlink(item['link'])
    font=brand.get('body_font','Arial');color=brand.get('text','272727')
    total=(len(items)+count-1)//count
    for start in range(0,len(items),count):
        title=content['title']+(f' ({start//count+1}/{total})' if total>1 else '')
        elements=[dict(type='text',name='title',x=.6,y=.4,w=12.1,h=.7,text=title,
            font=brand.get('heading_font',font),font_size=30,bold=True,color=brand.get('accent','202020'))]
        notes=[source.get('notes','')]
        for n,item in enumerate(items[start:start+count]):
            x=.6+n*4.15;w=3.8 if count==3 else 5.1;name='item-'+str(start+n+1)
            image_box=dict(x=x,y=1.5,w=w,h=2.1 if count==3 else 4.8)
            if item.get('image'):
                elements.append(dict(type='image',name=name+'-image',path=item['image'],fit='contain',**image_box))
            else:
                elements.append(dict(type='text',name=name+'-image-gap',text='Image unavailable',font=font,font_size=16,color=color,**image_box))
            tx=x if count==3 else 6.1;ty=3.8 if count==3 else 1.5;tw=w if count==3 else 6.5
            label=dict(type='text',name=name+'-label',x=tx,y=ty,w=tw,h=.7,text=item['label'],
                font=font,font_size=18 if count==3 else 24,bold=True,color=color)
            if item.get('link'):label['hyperlink']=item['link']
            elements.extend([label,dict(type='text',name=name+'-body',x=tx,y=ty+.85,w=tw,
                h=1.85 if count==3 else 3.7,text=item['body'],font=font,font_size=14 if count==3 else 18,color=color)])
            if item.get('link'):elements.append(dict(type='text',name=name+'-link',x=tx,y=6.65,w=tw,h=.35,
                text='Open source',hyperlink=item['link'],font=font,font_size=12,color=color))
            if item.get('credit'):notes.append(item['label']+' — '+item['credit'])
        yield dict(background=brand.get('background','FFFFFF'),notes='\n\n'.join(notes),elements=elements)



def table_pages(source,brand):
    from .pptx_document import _object,_text
    from .table_layout import pages
    content=source['content'];_object(content,('title','rows','caption'))
    _text(content['title'],90,False);_text(content['caption'],250)
    data=list(pages(content['rows']))
    for index,page in enumerate(data,1):
        title=content['title']+(f" — record {page['record']}" if 'record' in page else '')
        if len(data)>1:title+=f' ({index}/{len(data)})'
        yield dict(background=brand.get('background','FFFFFF'),notes=source.get('notes',''),elements=[
            dict(type='text',name='title',x=.6,y=.3,w=12.1,h=1.0,text=title,font_size=24,
                 font=brand.get('heading_font','Arial'),bold=True,color=brand.get('accent','202020')),
            dict(type='table',name='rows',x=.6,y=1.5,w=12.1,h=sum(page['row_heights']),
                 rows=page['rows'],row_heights=page['row_heights'],font_size=page['font_size'],
                 font=brand.get('body_font','Arial'),color=brand.get('text','272727')),
            dict(type='text',name='caption',x=.6,y=6.4,w=12.1,h=.8,text=content['caption'],font_size=12,
                 font=brand.get('body_font','Arial'),color=brand.get('text','272727'))])


def grid_pages(source, brand):
    """Paginate exact ordered content; no omission, font shrinking or LLM geometry."""
    from .pptx_document import _object, _text
    content=source['content']
    _object(content,('title','items'),('per_page','fit'))
    _text(content['title'],70,False)
    if '\n' in content['title']:raise ValueError('Image grid title must be one line.')
    per_page=content.get('per_page',6)
    if type(per_page) is not int or per_page not in (1,4,6):raise ValueError('Image grid per_page must be 1, 4 or 6.')
    fit=content.get('fit','contain')
    if fit not in ('contain','cover'):raise ValueError('Image grid fit must be contain or cover.')
    items=content['items']
    if not isinstance(items,list) or not 1<=len(items)<=120:raise ValueError('Image grid expects 1–120 items.')
    for item in items:
        _object(item,('image','label'),('caption','credit'))
        _text(item['image'],500,False)
        for key,limit in [('label',60),('caption',80),('credit',2000)]:
            _text(item.get(key,''),limit,key!='label')
            if key!='credit' and '\n' in item.get(key,''):raise ValueError('Image grid labels/captions must be single lines; use a detail slide for longer text.')
    cols=1 if per_page==1 else 2 if per_page==4 else 3
    w=(12.1-.35*(cols-1))/cols
    font=brand.get('body_font','Arial');color=brand.get('text','272727')
    total=(len(items)+per_page-1)//per_page
    for start in range(0,len(items),per_page):
        page=start//per_page+1
        title=content['title']+(f' ({page}/{total})' if total>1 else '')
        elements=[dict(type='text',name='title',x=.6,y=.3,w=12.1,h=.6 if per_page==1 else .65,text=title,
            font=brand.get('heading_font',font),font_size=24 if per_page==1 else 32,bold=True,color=brand.get('accent','202020'))]
        notes=[source.get('notes','')]
        for index,item in enumerate(items[start:start+per_page]):
            x=.6+(index%cols)*(w+.35);y=.95 if per_page==1 else 1.5+(index//cols)*2.72
            name='item-'+str(start+index+1)
            elements.extend([
                dict(type='image',name=name+'-image',x=x,y=y,w=w,h=5.85 if per_page==1 else 1.5,path=item['image'],fit=fit),
                dict(type='text',name=name+'-label',x=x,y=6.85 if per_page==1 else y+1.6,w=w,h=.3 if per_page==1 else .58,text=item['label'],
                     font=font,font_size=12 if per_page==1 else 16,bold=True,color=color),
                dict(type='text',name=name+'-caption',x=x,y=7.18 if per_page==1 else y+2.19,w=w,h=.25 if per_page==1 else .42,text=item.get('caption',''),
                     font=font,font_size=9 if per_page==1 else 12,color=color)])
            if item.get('credit'):notes.append(item['label']+' — '+item['credit'])
        yield dict(background=brand.get('background','FFFFFF'),notes='\n\n'.join(notes),elements=elements)


DESCRIPTION = '''Reusable layout specification version 2 (preferred for new decks):
{version:2,title:string,slides:[{layout:string,content:object,notes?:string}],
 style?:"clean_minimal_v1", brand?:{body_font?:string,heading_font?:string,background?:RGB,text?:RGB,accent?:RGB,
 logo?:{path:exact declared PNG/JPEG path,x:number,y:number,w:number,h:number}},
 templates?:{custom_name:[slot definitions]}}.
Built-in 16:9 layouts and required content slots: title/section(title,subtitle),
text(title,body), two_columns(title,left,right), image_text(title,image,caption,body),
table(title,rows,caption), chart(title,chart), image_grid(title,items,per_page?,fit?).
content_cards(title,items,per_page?) takes ordered {label,body,image?,link?,credit?}
items and paginates 1 (default) or 3 per page. Links must be HTTPS; absent images
are explicitly labeled unavailable. Label max 80 characters; body max 900 at one
per page or 300 at three. Use one per page for detailed evidence and specifications.
Tables use readable 14–16pt type, estimated row heights and repeated-header pagination;
very dense rows become record detail tables. Code retains every cell.
The model supplies content only; native geometry and clickable links are code-owned.
For image_grid, items are ordered {image:exact input path,label:string,
caption?:string,credit?:string}; per_page is 1, 4 or 6 (default 6); use 1 for a readable full-page drawing or detailed visual. Supply one list:
Relay paginates it, numbers pages and retains every item in order. Labels max 60
characters, captions max 80, each a single line; titles max 70. Long descriptions
belong on detail slides. Credits go in notes. Use exact bundle paths as usual.
fit defaults to contain (whole image); cover explicitly allows center cropping.
Missing optional photos: omit unavailable image items only when authorized, retain
subject research elsewhere and record omissions. Never fabricate paths.
Use style:"clean_minimal_v1" for a stable white/charcoal Arial theme. Brand overrides
are explicit. For new photo catalogues prefer image_grid; the author supplies data
and chooses density, while Relay calculates geometry, typography and pagination.
Older specs without style retain their original defaults. Text slots are strings; image is an exact
input path; rows are table rows; chart is {chart,categories,series}. Choose another
layout when an optional image is unavailable; do not invent or silently omit data.
Custom templates define 1–40 slots: {slot,type,x,y,w,h,role?:heading|body|caption}.
Types: text,image,table,chart. Inches in a 13.333333x7.5 slide. All supplied content
slots must match exactly; no extra or missing slots. Brand font/color/logo positions
are explicit data. Default logo box suggestion: x=11.5,y=6.95,w=1.2,h=.35.
Brand logos must not overlap layout content. Fixed text boxes reject overflow before commit. Keep each claim, qualification and source together; use another explicit content group when needed. Inspect every rendered page. Fonts must exist on the viewing computer; no font installation or embedding.
Freeze the chosen templates and brand in slides.json; user changes produce a new
version. Attach brand JSON, logo and written rules as exact references. An example
PPTX/PDF can guide a proposed profile, but native PPTX masters/import fidelity are
not supported and must not be promised. Confirm inferred brand rules with the user.
'''


def expand(document):
    from .pptx_document import _object, _text, _color, _number, TITLE_MAX
    if not isinstance(document,dict) or document.get('version') != 2:
        return document
    _object(document, ('version','title','slides'), ('brand','templates','style','asset_sha256'))
    _text(document['title'],TITLE_MAX,False)
    if type(document['version']) is not int:raise ValueError('Invalid template version.')
    style=document.get('style')
    if style is not None and (not isinstance(style,str) or style not in STYLES):raise ValueError('Unknown slide style.')
    brand=document.get('brand',{})
    _object(brand, (), ('body_font','heading_font','background','text','accent','logo'))
    for key in ('body_font','heading_font'):
        if key in brand:_text(brand[key],100,False)
    for key in ('background','text','accent'):
        if key in brand:_color(brand[key])
    brand={**STYLES.get(style,{}),**brand}
    custom=document.get('templates',{})
    if not isinstance(custom,dict) or len(custom)>20:raise ValueError('Expected at most 20 custom templates.')
    catalog=copy.deepcopy(CATALOG)
    for name, slots in custom.items():
        _text(name,100,False)
        if name in catalog or name in COLLECTION_LAYOUTS:raise ValueError('Custom templates must have distinct names.')
        catalog[name]=slots
    for slots in catalog.values():
        if not isinstance(slots,list) or not 1<=len(slots)<=40:raise ValueError('Expected 1–40 template slots.')
        names=set()
        for item in slots:
            _object(item,('slot','type','x','y','w','h'),('role',))
            _text(item['slot'],100,False)
            if item['slot'] in names:raise ValueError('Duplicate template slot.')
            names.add(item['slot'])
            if item['type'] not in ('text','image','table','chart'):raise ValueError('Unsupported slot type.')
            if item.get('role','body') not in ('heading','body','caption'):raise ValueError('Unsupported slot role.')
            for k in ('x','y','w','h'):_number(item[k],0 if k in ('x','y') else .01,40)
    logo=brand.get('logo')
    if logo is not None:_object(logo,('path','x','y','w','h'))
    slides=document['slides']
    if not isinstance(slides,list) or not 1<=len(slides)<=PPTX_SLIDES:raise ValueError('Expected 1–50 slides.')
    result=dict(version=1,title=document['title'],font=brand.get('body_font','Arial'),slides=[])
    for source in slides:
        _object(source,('layout','content'),('notes',))
        _text(source.get('notes',''),10000)
        if source['layout']=='table':
            for page in table_pages(source,brand):
                if logo:page['elements'].append(dict(type='image',name='brand-logo',**logo))
                result['slides'].append(page)
            continue
        if source['layout']=='content_cards':
            for page in card_pages(source,brand):
                if logo:page['elements'].append(dict(type='image',name='brand-logo',**logo))
                result['slides'].append(page)
            continue
        if source['layout']=='image_grid':
            for page in grid_pages(source,brand):
                if logo:page['elements'].append(dict(type='image',name='brand-logo',**logo))
                result['slides'].append(page)
            continue
        if not isinstance(source['layout'],str) or source['layout'] not in catalog:raise ValueError('Unknown slide layout.')
        slots=catalog[source['layout']];content=source['content']
        if not isinstance(content,dict) or set(content)!={s['slot'] for s in slots}:raise ValueError('Slide content must match its template slots exactly.')
        elements=[]
        for s in slots:
            e={k:v for k,v in s.items() if k not in ('slot','role')};e['name']=s['slot']
            value=content[s['slot']];kind=s['type'];role=s.get('role','body')
            if kind=='chart':
                _object(value,('chart','categories','series'));e.update(value)
            elif kind=='image':e['path']=value
            else:
                e['text' if kind=='text' else 'rows']=value
                e['color']=brand.get('accent','172B4D') if role=='heading' else brand.get('text','172B4D')
                e['font']=brand.get('heading_font',brand.get('body_font','Arial')) if role=='heading' else brand.get('body_font','Arial')
                e['font_size']={'heading':26,'body':18,'caption':12}[role]
                if kind=='text':e['bold']=role=='heading'
            elements.append(e)
        if logo:
            for k in ('x','y','w','h'):_number(logo[k],0 if k in ('x','y') else .01,40)
            for e in elements:
                if (logo['x'] < e['x']+e['w'] and e['x'] < logo['x']+logo['w'] and
                    logo['y'] < e['y']+e['h'] and e['y'] < logo['y']+logo['h']):
                    raise ValueError('Brand logo overlaps a template content slot.')
            elements.append(dict(type='image',name='brand-logo',**logo))
        result['slides'].append(dict(background=brand.get('background','FFFFFF'),notes=source.get('notes',''),elements=elements))
    from .table_layout import paginate_text
    result['slides']=[page for source in result['slides'] for page in paginate_text(source)]
    if len(result['slides'])>PPTX_SLIDES:raise ValueError('Image grid pagination exceeds 50-slide deck limit; split the deck.')
    if logo:
        for k in ('x','y','w','h'):_number(logo[k],0 if k in ('x','y') else .01,40)
        for page in result['slides']:
            for e in page['elements'][:-1]:
                if (logo['x'] < e['x']+e['w'] and e['x'] < logo['x']+logo['w'] and
                    logo['y'] < e['y']+e['h'] and e['y'] < logo['y']+logo['h']):
                    raise ValueError('Brand logo overlaps a template content slot.')
    if 'asset_sha256' in document:result['asset_sha256']=copy.deepcopy(document['asset_sha256'])
    return result
