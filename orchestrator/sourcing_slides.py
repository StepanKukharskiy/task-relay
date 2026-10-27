"""Native typed inventory/catalog → editable slide specification, no model call."""
import hashlib
from . import operation_contracts as c, sourcing_contract as sourcing, pptx_document

PARAMETERS={'inventory_path':'Exact typed inventory JSON path','catalog_path':'Exact typed sourcing catalog JSON path',
            'source_pack_path':'Exact original native source-pack path','image_path':'Exact original PNG room image path',
            'photos_path':'Exact photo ZIP path, or null for disclosed text-only alternatives','title':'Deck title, 1–160 characters',
            'layout':'standard or readable; fixed code-owned layouts'}

def parameters(p):
    c.fields(p,PARAMETERS)
    from .contracts import relative
    for k in PARAMETERS:
        if k.endswith('_path') and not (k in ('image_path','photos_path') and p[k] is None):relative(p[k])
    c.text(p['title'],160)
    if p['layout'] not in ('standard','readable'):raise ValueError('Unknown sourcing layout preset')

def validate_assignment(task):
    p=task['execution']['parameters'];parameters(p)
    if task['execution']['capability']=='sourcing.slides' and p['image_path'] is None:
        raise ValueError('The historical room slide operation requires its exact image')
    by_path={i['path']:i for i in task['inputs']}
    for k in ('inventory_path','catalog_path','source_pack_path','image_path','photos_path'):
        if p[k] is None:continue
        if p[k] not in by_path:raise ValueError('Sourcing slides need exact declared input paths')
        expected='image/png' if k=='image_path' else 'application/zip' if k=='photos_path' else 'application/json'
        if by_path[p[k]].get('media_type')!=expected:raise ValueError('Sourcing slide input type mismatch')

def clipped(s,n):return s if len(s)<=n else s[:n-1]+'…'

def text(s,x,y,w,h,size=16,**kw):return dict(type='text',text=s,x=x,y=y,w=w,h=h,font_size=size,**kw)

def option_text(option,cp,context,readable):
    fields=option['fields'];notes=[]
    rows=[];captured=set()
    from datetime import datetime,timezone
    for selection in fields.values():
        if selection['status']!='observed':continue
        stamp=context['observations'][selection['observation_id']].get('retrieved_at')
        if isinstance(stamp,(int,float)) and not isinstance(stamp,bool):
            try:captured.add(datetime.fromtimestamp(stamp,timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
            except (ValueError,OverflowError,OSError):pass
    for field,title in [(k,{'price':'Price','dimensions':'Dimensions','order_terms':'Ordering','us_context':'US context'}.get(k,k.replace('_',' ').capitalize())) for k in sourcing.field_rules(cp) if k!=sourcing.identity_field(cp)]:
        f=fields[field];value=f['reason'] if f['status']=='unknown' else f['excerpt']
        if f['status']=='observed':
            page=context['observations'][f['observation_id']]
            surrounding=page['text'][max(0,f['start']-160):min(len(page['text']),f['end']+240)]
            notes.append(title+' exact excerpt: '+f['excerpt']+'\nSaved source context: '+surrounding)
        # Preserve the selected amount without claiming it is a current
        # order price. Its source span may be a former/list/variant price.
        if sourcing.field_rules(cp)[field]=='price' and f['status']=='observed':
            prefix=page['text'][:f['start']].rstrip().rsplit('\n',1)[-1]
            label=prefix if len(prefix)<=35 and not any(ch.isdigit() for ch in prefix) else ''
            value=((f['currency']+' '+f['amount']+' observed offer; current variant unverified.') if f.get('currency') else f['excerpt']+' captured; current/variant/currency unverified.')+(' Source label: '+label if label else '')+' See notes.'
        rows.append(title+': '+(' '.join(value.split()) if readable else clipped(value,140)))
    return rows,notes,captured


def option_blocks(option,cp,rows,captured):
    name=option['fields'][sourcing.identity_field(cp)]['excerpt']
    from .visual_selection import description
    comparison=description(option) if cp.get('selection_policy')=='visual' else option['comparison']
    blocks=([name] if len(name)>180 else [])+rows+['Comparison: '+comparison]
    return blocks

def displayed_items(catalog):
    """Shortlist distinct suitable designs; retain the complete pool in catalog."""
    if catalog['parameters'].get('selection_policy')!='visual':return catalog['items']
    result=[];goal=catalog['parameters']['options_per_item']
    for item in catalog['items']:
        selected=[];seen=set()
        for o in item['options']:
            s=o['selection'];key=' '.join(s['design_id'].casefold().split())
            if s['status']=='visually_suitable' and key not in seen:
                seen.add(key)
                if len(selected)<goal:selected.append(o)
        v=item['coverage'];gap=f"Visually suitable distinct designs: {v['suitable']}; target: {goal}; gap: {v['shortfall']}. Provisional: {v['provisional']}; excluded: {v['excluded']}; unavailable: {v['unavailable']}. Buying details may remain unknown."
        result.append(dict(item,options=selected,gap=gap))
    return result


def review_workload(task,read,*,correction=False):
    """Measure the same literal text flow using saved JSON, without image reads."""
    import json,math
    from .product_evidence import source_pack_journal
    from .table_layout import flow_blocks
    p=task['execution']['parameters'];raw=[read(p[k]) for k in ('inventory_path','catalog_path','source_pack_path')]
    if any(value is None for value in raw):return None
    inventory,catalog,pack=map(json.loads,raw)
    context=dict(observations={a['id']:a['result'] for a in source_pack_journal(pack)['actions']})
    readable=correction or p['layout']=='readable';cp=catalog['parameters']
    pages=max(1,math.ceil(len(inventory['items'])/7)) if p['image_path'] is not None else 0
    if readable:
        for item in displayed_items(catalog):
            if not item['options']:
                pages+=len(list(flow_blocks(['No verified candidate recorded.',item['gap']],12.1,3.8,16)))
            for option in item['options']:
                rows,_,captured=option_text(option,cp,context,True)
                pages+=len(list(flow_blocks(option_blocks(option,cp,rows,captured),7.75,3.7,14)))
    else:pages+=math.ceil(sum(max(1,len(item['options'])) for item in displayed_items(catalog))/3)
    gaps=[item['id']+': '+item['gap'] for item in displayed_items(catalog) if item['gap']]
    pages+=max(1,len(list(flow_blocks(gaps,12,4,14))))
    return dict(slides=pages,tool_calls=pages+6,seconds=90+45*pages,
                basis='exact registered text-flow pagination; one image observation per page plus inspection and finalization')


def build(frozen,read):
    """Reproduce typed catalog from its original inputs, then lay it out in code."""
    validate_assignment(frozen);p=frozen['execution']['parameters']
    inventory,inv_sha=sourcing.bound_json(frozen,p['inventory_path'],read)
    from .sourcing_inventory import validate_document
    if p['image_path'] is not None:
        c.validate_document(c.encoded(inventory).encode(),inventory['contract'])
        if not inventory['complete']:raise ValueError('Sourcing slides require sealed inventory')
        raw=read(p['image_path'])
        if hashlib.sha256(raw).hexdigest()!=inventory.get('image',inventory.get('source',{}))['sha256']:raise ValueError('Room image differs from inventory pixel version')
    catalog,cat_sha=sourcing.bound_json(frozen,p['catalog_path'],read)
    family=c.identity(catalog['contract'])
    if family.get('record_role')!='options':raise ValueError('Slides need a registered typed options catalog')
    cp=catalog.get('parameters',{});sourcing.parameters(cp)
    terms=family.get('display_terms',{})
    if not isinstance(catalog.get('records'),list) or len(catalog['records'])>cp['max_records']:raise ValueError('Invalid catalog fragment collection')
    # Catalog paths are local to its producer. Rebind only the path names;
    # original byte hashes must still match and values must reproduce exactly.
    rebound={**cp,'inventory_path':p['inventory_path'],'source_pack_path':p['source_pack_path']}
    # The downstream input is already the exact composed version. Replaying
    # producer-local composition would require undeclared old aliases and would
    # append captures twice. Original document parameters remain unchanged.
    for key in ('base_source_pack_path','base_catalog_path','source_pack_output'):rebound.pop(key,None)
    context=sourcing.context({**frozen,'operation_contract':dict(**catalog['contract'],parameters=rebound)},read)
    for r in catalog.get('records',[]):sourcing.options_record(r,cp,context)
    if catalog!=sourcing.options_document(catalog.get('records',[]),cp,context) or not catalog['complete']:raise ValueError('Catalog differs from code-owned source projection')
    sourcing.validate_result(catalog,dict(decision='delivered'))
    slides=[]
    if p['image_path'] is not None:
        from .browser_contract import png_info
        info=png_info(raw);iw,ih=info['width'],info['height']
        if 'image' in inventory and (iw,ih)!=(inventory['image']['width'],inventory['image']['height']):raise ValueError('Inventory image dimensions differ from exact pixels')
        # Whole photograph plus editable numbered markers and a paginated legend.
        image_scale=min(8.2/iw,6.1/ih);w,h=iw*image_scale,ih*image_scale;x,y=.4+(8.2-w)/2,.95+(6.1-h)/2
        groups=[inventory['items'][n:n+7] for n in range(0,len(inventory['items']),7)] or [[]]
        for group in groups:
            elements=[text(p['title'],.4,.15,12.5,.6,26,bold=True),dict(type='image',path=p['image_path'],x=x,y=y,w=w,h=h)]
            for n,item in enumerate(group):
                left,top,right,bottom=item['bbox'];slot=int(item['id'].split('-')[-1])
                # Mark the complete observed region, including grouped objects. A
                # union bbox cannot supply separate guessed object coordinates.
                bx,by,bw,bh=x+w*left,y+h*top,w*(right-left),h*(bottom-top)
                for ex,ey,ew,eh in ((bx,by,bw,.01),(bx,by+bh-.01,bw,.01),(bx,by,.01,bh),(bx+bw-.01,by,.01,bh)):
                    elements.append(dict(type='shape',shape='rectangle',x=ex,y=ey,w=ew,h=eh,fill='1B4F72',name=item['id']+' region'))
                elements.append(dict(type='shape',shape='ellipse',x=max(x,min(x+w-.3,x+w*(left+right)/2-.15)),y=max(y,min(y+h-.3,y+h*(top+bottom)/2-.15)),w=.3,h=.3,text=str(slot),font_size=10,fill='FFFFFF',color='1B4F72',bold=True,align='center',name=item['id']))
                qualifier=' ('+item['confidence']+')' if 'confidence' in item else ''
                elements.append(text(f"{slot}. {clipped(item['label'],85)}{qualifier}",8.9,1+n*.46,4,.42,13))
            if not group:elements.append(text('No visible sourcing items identified. '+clipped(inventory['notes'],250),8.9,1,4,3,14))
            slides.append(dict(elements=elements,notes='Image SHA-256: '+inventory.get('image',inventory.get('source',{}))['sha256']+'\n'+inventory['notes']+'\nBoxes identify exact inventory regions; a grouped region does not imply individually observed object anchors.\n'+'\n'.join(i['id']+': '+i['notes'] for i in group)))
    photos={};photo_sha=None;missing=[];rebindings=[];manifest=None
    if p['photos_path'] is not None:
        from .image_sources import unpack
        photo_raw=read(p['photos_path']);photo_sha=hashlib.sha256(photo_raw).hexdigest()
        _,_,manifest=unpack(photo_raw)
        for s in manifest['subjects']:
            if s['status']=='found':photos[s['id']]=s
        source_pack,_=sourcing.bound_json(frozen,p['source_pack_path'],read)
    labels={i['id']:i['label'] for i in inventory['items']}
    regions={i['id']:i.get('bbox') for i in inventory['items']}
    cards=[]
    for item in displayed_items(catalog):
        if not item['options']:cards.append((item,None))
        else:cards.extend((item,o) for o in item['options'])
    columns=1 if p['layout']=='readable' else 3
    card_w=12.1 if columns==1 else 4.05
    for start in range(0,len(cards),columns):
        elements=[text(terms.get('options','Sourcing options'),.4,.15,12.4,.6,26,bold=True)];notes=[]
        for col,(item,option) in enumerate(cards[start:start+columns]):
            cx=.4+col*(card_w+.2);ident=item['id'];label=clipped(labels[ident],95)
            elements.append(text(ident+' · '+label,cx,.95,card_w,.7,16,bold=True))
            if option is None:
                if columns==1:
                    from .table_layout import flow_blocks
                    for chunk in flow_blocks(['No verified candidate recorded.',item['gap']],card_w,3.8,16):
                        slides.append(dict(elements=elements+[text('\n\n'.join(chunk),cx,2,card_w,3.8,16)],notes=ident+' '+item['gap']))
                else:elements.append(text('No verified candidate recorded.\n'+clipped(item['gap'],600),cx,2,card_w,3.8,16))
                continue
            fields=option['fields'];name=fields[sourcing.identity_field(cp)]['excerpt']
            elements.append(text(clipped(name,180),cx,1.7,card_w,.8,16,bold=True,hyperlink=option['product_url']))
            photo=photos.get(option['option_id'])
            from .page_identity import association
            page_binding=association(photo.get('source_url'),option['product_url']) if photo else None
            if photo is None and manifest is not None:
                from .product_photos import retained_photo
                photo,page_binding=retained_photo(option,cp,manifest,source_pack)
                if photo:rebindings.append(page_binding)
            if photo and not page_binding:
                binding=photo.get('catalog_subject_binding',{})
                if binding==dict(option_id=option['option_id'],catalog_sha256=cat_sha,identity_policy='subject',query=name[:200]):
                    page_binding=dict(basis='exact-catalog-subject-binding; visual identity requires independent review')
            if cp.get('selection_policy')=='visual':
                selection=option['selection']
                if not photo or not page_binding or selection['photo_sha256']!=photo['sha256']:
                    raise ValueError('Selected visual assessment does not bind the retained product photo')
                source=inventory.get('source',{})
                reference=inventory.get('image',source if source.get('media_type')=='image/png' else {}).get('sha256')
                if reference and selection['reference_sha256']!=reference:raise ValueError('Visual assessment targets a different subject reference')
            image_w=4 if columns==1 else card_w;photo_x=cx
            if columns==1 and p['image_path'] is not None and regions.get(ident):
                image_w=1.9;photo_x=cx+2.1
                elements.extend([text('Room reference',cx,2.55,1.9,.3,12),text('Candidate',photo_x,2.55,1.9,.3,12),
                    dict(type='image',path=p['image_path'],source_region=regions[ident],x=cx,y=2.95,w=1.9,h=2.5)])
                notes.append('Room crop uses exact inventory normalized bounds: '+c.encoded(regions[ident])+'. Original image bytes are retained.')
            if photo and page_binding:
                elements.append(dict(type='image',path=p['photos_path']+'/'+photo['path'],x=photo_x,y=2.95 if photo_x!=cx else 2.55,w=image_w,h=2.5 if columns==1 else 1.75))
                notes.append('Photo page association: '+c.encoded(page_binding)+'\nVisual variant/correspondence remains subject to independent review.')
            else:
                message=terms.get('photo_unbound','Photo retained in bundle; product-page URL binding differs. Variant/correspondence needs review.') if photo else terms.get('photo_missing','Product photo unavailable')
                elements.append(text(message,photo_x,3,image_w,1.4 if columns==1 else .8,14));missing.append(option['option_id'])
                if photo:notes.append('Retained photo source URL: '+photo['source_url']+'\nCatalog product URL: '+option['product_url'])
            rows,field_notes,captured=option_text(option,cp,context,columns==1);notes.extend(field_notes)
            if columns==1:
                from .table_layout import flow_blocks
                blocks=option_blocks(option,cp,rows,captured)
                chunks=list(flow_blocks(blocks,7.75,3.7,14))
                for index,chunk in enumerate(chunks):
                    body=text('\n\n'.join(chunk),cx+4.35,2.55,7.75,3.7,14)
                    capture_note='Historical source capture: '+(', '.join(sorted(captured)) if captured else 'time not recorded')+'. Verify current price, availability and destination.'
                    page_elements=elements+[body,text(capture_note,cx,6.45,card_w,.5,12),text(terms.get('link','Open retailer page')+(' · continued '+str(index+1)+'/'+str(len(chunks)) if len(chunks)>1 else ''),cx,7.03,card_w,.3,12,color='1B4F72',hyperlink=option['product_url'])]
                    slides.append(dict(elements=page_elements,notes='\n'.join(notes+[ident+' '+option['option_id']+' '+option['product_url'],item['gap'],'Full comparison: '+option['comparison']])))
                continue
            else:
                elements.append(text('\n'.join(rows),cx,4.45,card_w,1.65,13))
                from .visual_selection import description
                elements.append(text(clipped(description(option) if cp.get('selection_policy')=='visual' else option['comparison'],180),cx,6.1,card_w,.6,12))
            elements.append(text(terms.get('link','Open retailer page'),cx,6.85,card_w,.35,13,color='1B4F72',hyperlink=option['product_url']))
            notes.extend([ident+' '+option['option_id']+' '+option['product_url'],item['gap'],'Full comparison: '+option['comparison']])
        if columns!=1:slides.append(dict(elements=elements,notes='\n'.join(notes)))
    elements=[text('Coverage and checks',.4,.2,12.4,.6,26,bold=True),text(terms.get('coverage','Saved page evidence supports the captured fields. Product suitability and image correspondence require independent review. Current stock, shipping totals and user acceptance are not guaranteed. Unknown fields and missing alternatives remain visible.'),.6,1,12,1.5,19)]
    from .table_layout import flow_blocks
    gaps=[i['id']+': '+i['gap'] for i in displayed_items(catalog) if i['gap']]
    for chunk in flow_blocks(gaps,12,4,14):slides.append(dict(elements=elements+[text('\n\n'.join(chunk),.6,2.7,12,4,14)],notes='Exact catalog SHA-256: '+cat_sha))
    if not gaps:slides.append(dict(elements=elements,notes='Exact catalog SHA-256: '+cat_sha))
    document=dict(version=1,title=p['title'],slides=slides,font='Arial')
    images=([p['image_path']] if p['image_path'] is not None else [])+[e['path'] for s in slides for e in s['elements'] if e['type']=='image' and e['path']!=p['image_path']]
    pptx_document.validate(document,images)
    from .document_compose import asset_map, images as bound_images
    document['asset_sha256']=asset_map(document,bound_images(frozen,read))
    validation=dict(inventory_sha256=inv_sha,catalog_sha256=cat_sha,source_pack_sha256=context['source_versions']['source_pack_sha256'],
                    image_sha256=inventory.get('image',{}).get('sha256'),photos_sha256=photo_sha,missing_photos=missing,
                    photo_rebindings=rebindings,
                    items=len(inventory['items']),options=sum(len(i['options']) for i in catalog['items']),slides=len(slides))
    return c.encoded(document)+'\n',validation
