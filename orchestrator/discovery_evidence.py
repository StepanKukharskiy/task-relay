"""Pure discovery projections over saved observations, never a new collector.

Search titles and listing entities identify leads, not verified buying facts.
Pixels keep their original captured-page associations. No URL is synthesized,
no network request is made, and no visual suitability is inferred here.
"""
import copy,hashlib,json
from .page_identity import identity
from task_relay.orchestrator_web import public_url

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def observations(pack):
    from .product_photos import candidate_images
    result=[]
    def add(ident,title,url,images,entry,provenance):
        if not isinstance(title,str) or not title.strip() or len(title)>4000:return
        try:url=public_url(url)
        except (ValueError,TypeError):return
        result.append(dict(id=ident,result=dict(observation=ident,text=title,url=url,
            images=copy.deepcopy(images),products=[],discovery=provenance,
            target_ids=list(entry.get('target_ids',[])),query=entry.get('query',''))))
    for ei,e in enumerate(pack['entries']):
        for pi,p in enumerate(e.get('pages',[])):
            products=[v for v in p.get('products',[]) if isinstance(v,dict) and isinstance(v.get('name'),str)]
            for n,v in enumerate(products):
                # Multi-entity listing pages need an explicit per-entity URL.
                url=v.get('url') or (p['url'] if len(products)==1 else None)
                if not url:continue
                add(f'lead-{ei}-{pi}-{n}',v['name'],url,candidate_images(p,v['name']),e,
                    dict(basis='captured-entity',source_url=p['url'],source_sha256=p.get('sha256') or digest(p),entity_sha256=digest(v)))
            if not products:
                title=p.get('title') or p.get('text','').split('\n')[0]
                add(f'lead-{ei}-{pi}-page',title,p['url'],candidate_images(p,title),e,
                    dict(basis='captured-page-title',source_url=p['url'],source_sha256=p.get('sha256') or digest(p)))
        for n,v in enumerate(e.get('grounding',[])):
            add(f'lead-{ei}-search-{n}',v.get('title'),v.get('url'),[],e,
                dict(basis='search-title',source_url=v.get('url'),source_sha256=digest(v)))
    return result

def pool(pack,maximum):
    """Fair bounded download pool; the complete discovery ledger stays in pack."""
    remaining=[a['result'] for a in observations(pack)];selected=[];seen=set();spent={}
    while remaining and len(selected)<maximum:
        def group(v):return tuple(v['target_ids']) or (v['query'],)
        chosen=min(remaining,key=lambda v:(spent.get(group(v),0),not bool(v['images'])))
        remaining.remove(chosen);key=identity(chosen['url'])
        if key in seen:continue
        seen.add(key);selected.append(chosen);g=group(chosen);spent[g]=spent.get(g,0)+1
    return selected,dict(total_observations=len(observations(pack)),selected=len(selected),
        remaining_distinct_urls=len({identity(v['url']) for v in remaining}-seen),
        interpretation='Bounded discovery leads, not selected designs. Missing pixels and buying facts remain unknown; inspect candidate and reference images before suitability judgments.')

def manifest(pack,maximum=40):
    from .browser_images import SCHEMA
    from .image_sources import display_text
    leads,coverage=pool(pack,maximum);subjects=[];candidates=[]
    for v in leads:
        ident=v['observation'];subjects.append(dict(id=ident,label=display_text(v['text']),query=display_text(v['text'])))
        for image in v['images'][:2]:
            candidates.append(dict(subject=ident,download_url=image['url'],source_url=v['url'],
                observed_url=v['discovery']['source_url'],observation=ident,
                action_id='source-page:'+v['discovery']['source_sha256'],title=v['text'][:500]))
    return dict(schema=SCHEMA,job='source-discovery:'+digest(pack),subjects=subjects,candidates=candidates),leads,coverage
