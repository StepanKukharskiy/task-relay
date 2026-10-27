"""Fetch images recorded on exact catalog pages, without another discovery model."""
import io
import hashlib
import json
import zipfile
import re
import unicodedata
from html import unescape
from . import sourcing_contract as sourcing, browser_images, image_sources

PARAMETERS={'inventory_path':'Exact typed inventory JSON', 'catalog_path':'Exact typed options JSON, or null to inspect a broad source-discovery image pool BEFORE catalog construction/approval; does not establish suitability',
            'source_pack_path':'Exact observed source-pack JSON', 'count_policy':'target or required'}


def product_aliases(page,literal):
    """Names on this capture may alias only with a shared explicit identity.

    No fuzzy title matching, URL guessing or cross-page SKU joins. Conflicting
    identifiers, variant attributes or product URLs make the alias ineligible.
    """
    def name(value):return tuple(re.findall(r'\w+',unicodedata.normalize('NFKC',unescape(str(value))).casefold()))
    wanted=name(literal);products=page.get('products',[])
    matches=[p for p in products if name(p.get('name',''))==wanted]
    aliases={wanted}
    if not wanted or not matches:return aliases
    from .page_identity import association
    def same(a,b):
        ids=('sku','productID')
        if not any(a.get(k) not in (None,'') and a.get(k)==b.get(k) for k in ids):return False
        for k in (*ids,'color','size','material'):
            if a.get(k) not in (None,'') and b.get(k) not in (None,'') and a[k]!=b[k]:return False
        urls=lambda p:[u for u in [p.get('url')]+[o.get('url') for o in p.get('offers',[])] if u]
        if any(not association(x,y) for x in urls(a) for y in urls(b)):return False
        return True
    for p in products:
        alias=name(p.get('name',''))
        owners=[q for q in products if name(q.get('name',''))==alias]
        if alias and all(same(a,b) for a in matches for b in owners):aliases.add(alias)
    return aliases


def candidate_images(page,literal):
    """Keep entity/image associations; a multi-entity page is not an identity.

    Older captures flattened JSON-LD images and discarded their product owner.
    Those ambiguous pages yield missing coverage, not the first unrelated image.
    Matching structured names narrows candidates only; visual review still owns
    correspondence and suitability. Never reconstruct association from a URL.
    """
    def name(value):return tuple(re.findall(r'\w+',unicodedata.normalize('NFKC',unescape(value)).casefold()))
    wanted=name(literal);aliases=product_aliases(page,literal)
    images=page.get('images',[])
    bound=[i for i in images if wanted and any(name(n) in aliases for n in i.get('product_names',[]) if isinstance(n,str))]
    if bound:images=bound
    elif len(page.get('products',[]))>1 or any(i.get('product_names') for i in images):return []
    return sorted(images,key=lambda i:0 if i.get('basis')=='observed-product-jsonld' else 1 if i.get('basis')=='observed-page-metadata' else 2)


def retained_photo(option, parameters, manifest, source_pack):
    """Rebind a changed record to one exact retained page/image observation.

    Record IDs include editorial findings. They are not durable image identities.
    URL similarity alone cannot recover an image: require the original page hash,
    an image still declared by that page's entity selection, and a unique receipt.
    This establishes provenance only, never variant suitability or acceptance.
    """
    from .page_identity import association
    identity=option['fields'][sourcing.identity_field(parameters)]
    pages={f'page-{i}-{j}':p for i,e in enumerate(source_pack['entries']) for j,p in enumerate(e.get('pages',[]))}
    page=pages.get(identity.get('observation_id'));observed_url=None
    if page is None and parameters.get('selection_policy')=='visual':
        from .discovery_evidence import observations
        lead=next((a['result'] for a in observations(source_pack) if a['id']==identity.get('observation_id')),None)
        if lead:
            page=dict(url=lead['url'],sha256=lead['discovery']['source_sha256'],images=lead['images'])
            observed_url=lead['discovery']['source_url']
    if not page or not page.get('sha256') or not association(page['url'],option['product_url']):return None,None
    allowed={i['url'] for i in candidate_images(page,identity['excerpt'])}
    matches=[s for s in manifest['subjects'] if s.get('status')=='found'
             and s.get('action_id')=='source-page:'+page['sha256']
             and s.get('download_url') in allowed
             and association(s.get('source_url'),page['url'])
             and association(s.get('observed_url'),observed_url or page['url'])]
    if len(matches)!=1:return None,None
    photo=matches[0]
    return photo,dict(basis='exact-retained-page-image',previous_subject=photo['id'],
        option_id=option['option_id'],source_page_sha256=page['sha256'],
        source_url=photo['source_url'],product_url=option['product_url'],
        download_url=photo['download_url'],image_sha256=photo['sha256'])


def validate_assignment(task):
    from .operation_contracts import fields
    keys=set(PARAMETERS)
    if task['execution']['capability']=='images.catalog':keys|={'source_adapters','image_identity'}
    fields(task['execution']['parameters'],keys)
    p=task['execution']['parameters'];by_path={i['path']:i for i in task['inputs']}
    if p['count_policy'] not in ('target','required'):raise ValueError('Invalid product photo count policy')
    if task['execution']['capability']=='images.catalog':
        adapters=p['source_adapters']
        if not isinstance(adapters,list) or not adapters or len(set(adapters))!=len(adapters) or any(a not in ('observed-pages','commons') for a in adapters):raise ValueError('Select distinct registered image source adapters')
        if p['image_identity'] not in ('page','subject') or 'commons' in adapters and p['image_identity']!='subject':raise ValueError('Commons needs an explicit subject identity policy')
    for key in ('inventory_path','catalog_path','source_pack_path'):
        if key=='catalog_path' and p[key] is None:continue
        if p[key] not in by_path or by_path[p[key]].get('media_type')!='application/json':
            raise ValueError('Product photos need exact declared JSON inputs')


def prepare(frozen,read,*,legacy=False):
    validate_assignment(frozen);p=frozen['execution']['parameters']
    catalog,catalog_sha=sourcing.bound_json(frozen,p['catalog_path'],read)
    from .operation_contracts import identity
    if identity(catalog['contract']).get('record_role')!='options':raise ValueError('Photos require a registered options catalog')
    cp=catalog['parameters']
    rebound={**cp,'inventory_path':p['inventory_path'],'source_pack_path':p['source_pack_path']}
    for key in ('base_source_pack_path','base_catalog_path','source_pack_output'):rebound.pop(key,None)
    ctx=sourcing.context({**frozen,'operation_contract':dict(**catalog['contract'],parameters=rebound)},read)
    for fragment in catalog['records']:sourcing.options_record(fragment,cp,ctx)
    if not catalog['complete'] or catalog!=sourcing.options_document(catalog['records'],cp,ctx):
        raise ValueError('Product photos catalog differs from its bound sources')
    pack,_=sourcing.bound_json(frozen,p['source_pack_path'],read)
    pages={f'page-{i}-{j}':page for i,e in enumerate(pack['entries']) for j,page in enumerate(e.get('pages',[]))}
    subjects=[];candidates=[]
    for item in catalog['items']:
        for option in item['options']:
            maximum=image_sources.MAX_BUNDLE_SUBJECTS if frozen['execution']['capability']=='images.catalog' else image_sources.MAX_SUBJECTS
            if len(subjects)>=maximum:raise ValueError('Product photo subjects exceed the registered collection capacity')
            literal=option['fields'][sourcing.identity_field(cp)]['excerpt']
            project=(lambda text:text[:200]) if legacy else image_sources.display_text
            subjects.append(dict(id=option['option_id'],label=project(item['id']+': '+literal),query=project(literal)))
            observation=option['fields'][sourcing.identity_field(cp)]['observation_id']
            page=pages.get(observation)
            if page is None and cp.get('selection_policy')=='visual':
                lead=ctx['observations'][observation]
                if not lead.get('discovery'):raise ValueError('Missing captured image provenance')
                page=dict(url=lead['url'],images=lead['images'],sha256=lead['discovery']['source_sha256'],observed_url=lead['discovery']['source_url'])
            images=candidate_images(page,literal)
            seen=set()
            for image in images:
                url=image.get('url')
                if url in seen:continue
                seen.add(url)
                candidates.append(dict(subject=option['option_id'],download_url=url,source_url=page['url'],observed_url=page.get('observed_url',page['url']),
                                       observation=observation,action_id='source-page:'+page['sha256'],
                                       title=option['fields'][sourcing.identity_field(cp)]['excerpt'][:500]))
                if len(seen)==2:break
    if subjects and not legacy:
        image_sources.validate_subjects(subjects,maximum=maximum,literal_query=False)
    return catalog_sha,ctx,subjects,candidates


def build(frozen,read,*,fetch=None,record=None):
    p=frozen['execution']['parameters']
    if p['catalog_path'] is None:
        validate_assignment(frozen)
        inventory,inv_sha=sourcing.bound_json(frozen,p['inventory_path'],read)
        pack,pack_sha=sourcing.bound_json(frozen,p['source_pack_path'],read)
        from .subject_contract import validate_input
        validate_input(inventory)
        from .discovery_evidence import manifest as discovery_manifest
        manifest,leads,coverage=discovery_manifest(pack,image_sources.MAX_SUBJECTS)
        if manifest['subjects']:
            raw,result=browser_images.fetch_bundle(manifest,fetch=fetch,record=record,seconds=frozen['limits']['seconds'],max_bytes=frozen['limits']['output_bytes'])
        else:
            empty=io.BytesIO()
            with zipfile.ZipFile(empty,'w'):pass
            raw=empty.getvalue();result=dict(version=1,kind='task-relay-sourced-images',subjects=[],complete=True,coverage=dict(found=0,missing=0,total=0))
        result.update(source_pack_sha256=pack_sha,inventory_sha256=inv_sha,discovery_pool=dict(leads=leads,coverage=coverage),source_catalog_sha256=None)
        if p['count_policy']=='required' and result['coverage']['missing']:raise ValueError('Required discovery image coverage remains incomplete')
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as before,zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as after:
            for name in before.namelist():
                if name!='manifest.json':after.writestr(name,before.read(name))
            after.writestr('manifest.json',json.dumps(result,ensure_ascii=False,indent=2))
        if len(output.getvalue())>frozen['limits']['output_bytes']:raise ValueError('Discovery manifest exceeds output byte limit')
        return output.getvalue(),result
    catalog_sha,ctx,subjects,candidates=prepare(frozen,read)
    # A sealed zero-option catalog has no subjects; retain an explicit empty
    # bundle rather than inventing a product or forcing another worker.
    if not subjects:
        if p['count_policy']=='required':raise ValueError('Required product photographs have no catalog options')
        manifest=dict(version=1,kind='task-relay-sourced-images',provider='observed-product-pages',subjects=[],complete=True,
                      coverage=dict(found=0,missing=0,total=0),empty_catalog=True,source_catalog_sha256=catalog_sha,
                      source_pack_sha256=ctx['source_versions']['source_pack_sha256'],review='No catalog alternatives; no product photos claimed.')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('manifest.json',json.dumps(manifest))
        return output.getvalue(),manifest
    from .collection_core import collect as collect_subjects
    import time
    deadline=time.monotonic()+frozen['limits']['seconds'];parts=[];files={}
    def collect_one(subject,adapter):
        remaining=frozen['limits']['output_bytes']-sum(map(len,files.values()))
        if remaining<=1000000:return {**subject,'status':'missing','reason':'Total image output allowance exhausted'}
        if adapter=='observed-pages':
            manifest=dict(schema=browser_images.SCHEMA,job=frozen.get('assignment_id','registered-product-photos'),subjects=[subject],candidates=[c for c in candidates if c['subject']==subject['id']])
            raw,result=browser_images.fetch_bundle(manifest,fetch=fetch,record=record,
                seconds=max(0,deadline-time.monotonic()),max_bytes=remaining)
        else:
            literal={**subject,'query':image_sources.normalized(subject['query'])[:200]}
            raw,result=image_sources.collect([literal],fetch=fetch,record=record,
                seconds=max(0,deadline-time.monotonic()),max_bytes=remaining)
        entry=result['subjects'][0]
        entry['query']=subject['query']
        parts.append(dict(adapter=adapter,sha256=hashlib.sha256(raw).hexdigest(),subjects=[subject['id']]))
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for name in archive.namelist():
                if name=='manifest.json':continue
                if name in files:raise ValueError('Photo batch archive member collision')
                files[name]=archive.read(name)
        if adapter=='commons' and entry['status']=='found':entry['catalog_subject_binding']=dict(option_id=subject['id'],catalog_sha256=catalog_sha,identity_policy='subject',query=subject['query'])
        return entry
    order=p.get('source_adapters',['observed-pages'])
    adapters=[dict(id=name,version=1,collect=lambda subject,name=name:collect_one(subject,name)) for name in order]
    entries,_=collect_subjects(subjects,adapters,policy=dict(catalog_sha256=catalog_sha,image_identity=p.get('image_identity','page')),
        commit=(lambda state:record(dict(kind='collection-checkpoint',status='requested' if state['pending'] else 'checkpointed',state=state))) if record else None)
    found=sum(s['status']=='found' for s in entries)
    result=dict(version=1,kind='task-relay-sourced-images',subjects=entries,source_batches=parts,
        complete=found==len(entries),coverage=dict(found=found,missing=len(entries)-found,total=len(entries)))
    if p['count_policy']=='required' and result['coverage']['missing']:
        raise ValueError('Required product photo coverage remains incomplete')
    result.update(provider='observed-product-pages',source_catalog_sha256=catalog_sha,
                  source_pack_sha256=ctx['source_versions']['source_pack_sha256'])
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as after:
        after.writestr('manifest.json',json.dumps(result,ensure_ascii=False,indent=2).encode())
        for name,raw in files.items():after.writestr(name,raw)
    if len(output.getvalue())>frozen['limits']['output_bytes']:raise ValueError('Photo manifest exceeds output byte limit')
    return output.getvalue(),result


def preflight_recovery(frozen,receipt,control,read):
    """Project a historical catalog-display failure with no dispatched request.

    Reproduce the precise initial collection intent and local validation before
    the transport. A download/search journal entry or output disqualifies replay.
    """
    from .operation_contracts import digest
    path=control/'image-requests.jsonl'
    if path.is_symlink():return None
    try:
        raw=path.read_bytes();rows=[json.loads(line) for line in raw.splitlines()]
        sha,_,subjects,_=prepare(frozen,read,legacy=True)
        order=frozen['execution']['parameters'].get('source_adapters',['observed-pages'])
        if not subjects or order[0]!='observed-pages':return None
        binding=digest(dict(subjects=subjects,adapters=[dict(id=name,version=1) for name in order],policy=dict(catalog_sha256=sha,image_identity=frozen['execution']['parameters'].get('image_identity','page'))))
        first=subjects[0]['id']
        expected=dict(kind='collection-checkpoint',status='requested',state=dict(version=1,binding=binding,pending=dict(subject=first,adapter=order[0],version=1),units={first:{}}))
        if rows!=[expected]:return None
        try:image_sources.validate_subjects([subjects[0]],literal_query=False)
        except ValueError:pass
        else:return None
        prepare(frozen,read) # every corrected subject must validate before intent
        return dict(version=1,execution='not_started',quiescent=True,journal_sha256=hashlib.sha256(raw).hexdigest(),catalog_sha256=sha,
            instruction='Continue the unchanged registered photo operation using the exact saved inventory, catalog and source pack. Source whitespace is projected to bounded display text by code; source excerpts and identity bindings remain unchanged. The previous local validator ran before any transport request. Do not repeat catalog or source collection.')
    except (OSError,ValueError,KeyError,TypeError):return None


def revision_preview(frozen,receipt,read):
    """Pure changed-selection evidence; never fetch or judge visual acceptance."""
    if frozen['execution']['parameters']['count_policy']!='target':return None
    sha,ctx,subjects,candidates=prepare(frozen,read)
    old=receipt.get('operation',{}).get('validation',{})
    if old.get('source_catalog_sha256')!=sha or old.get('source_pack_sha256')!=ctx['source_versions']['source_pack_sha256']:return None
    prior={s['id']:s for s in old.get('subjects',[])}
    if set(prior)!={s['id'] for s in subjects}:return None
    changes=[]
    for subject in subjects:
        previous=prior[subject['id']];urls=[i['download_url'] for i in candidates if i['subject']==subject['id']]
        if previous.get('status')=='found' and previous.get('download_url') not in urls:
            changes.append(dict(subject=subject['id'],previous_url=previous.get('download_url'),current_candidates=urls))
    if not changes:return None
    from .operation_contracts import digest
    return dict(version=1,selection_sha256=digest(candidates),changes=changes,
        instruction='Recompute the unchanged native read using the corrected registered source selection. Exact saved inputs are preserved. Prior selected images excluded by current entity bindings must not remain usable evidence. Target shortfalls stay explicit. Independently review the new bundle; no acceptance is inferred.')
