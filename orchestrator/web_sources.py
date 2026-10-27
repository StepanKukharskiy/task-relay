"""Bounded public text-source collection for registered production steps."""

import json
import hashlib
import http.client
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from task_relay import gemini, orchestrator_web

MAX_QUERIES = 20
MAX_DOMAINS = 8
MAX_PAGES_PER_QUERY = 2


def page_identity(url):
    """Conservative URL identity; variant/SKU and unknown parameters survive."""
    from .page_identity import identity
    return identity(url)


def mechanical_index(pack):
    """Group recorded pages, never infer product identity or factual support."""
    pages={};captures={};texts={};observations=[]
    for entry_index,entry in enumerate(pack['entries']):
        for page_index,page in enumerate(entry['pages']):
            ref=f'entries[{entry_index}].pages[{page_index}]'
            url=page_identity(page['url'])
            text_hash=hashlib.sha256(page['text'].encode('utf-8')).hexdigest()
            group=pages.setdefault(url,dict(id='p'+str(len(pages)+1),url=url,observations=[],target_ids=[]))
            group['observations'].append(ref)
            group['target_ids']=list(dict.fromkeys(group['target_ids']+entry.get('target_ids',[])))
            key=(url,page['sha256'],text_hash)
            observations.append(dict(ref=ref,page_group=group['id'],sha256=page['sha256'],text_sha256=text_hash,
                                     duplicate_of=captures.get(key),reused_from=page.get('reused_from')))
            captures.setdefault(key,ref)
            texts.setdefault(text_hash,[]).append(ref)
    coverage=[]
    for target in pack.get('query_specification',{}).get('data',{}).get('targets',[]):
        groups=[g['id'] for g in pages.values() if target['id'] in g['target_ids']]
        coverage.append(dict(target_id=target['id'],option_goal=target['required_options'],page_groups=groups,fetched_page_count=len(groups)))
    return dict(version=1,observations=observations,page_groups=list(pages.values()),targets=coverage,
                repeated_text=[refs for refs in texts.values() if len(refs)>1],
                counts=dict(observations=len(observations),distinct_urls=len(pages),distinct_captures=len(captures),
                            exact_repeats=len(observations)-len(captures)),
                interpretation='Code-owned URL/capture grouping only. Fetched pages and identical text do not establish distinct products, correspondence, price, availability or accepted option coverage. Different variants and source versions remain recorded.')


def validate(queries, domains):
    if (not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES
            or any(not isinstance(q, str) or not 1 <= len(q.strip()) <= 250
                   or any(ord(c) < 32 for c in q) for q in queries)
            or len({q.casefold().strip() for q in queries}) != len(queries)):
        raise ValueError('Web source collection requires 1–20 distinct literal queries of at most 250 characters.')
    if (not isinstance(domains, list) or len(domains) > MAX_DOMAINS
            or any(not isinstance(d, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', d)
                   or '.' not in d or '..' in d for d in domains)
            or len(set(d.lower() for d in domains)) != len(domains)):
        raise ValueError('Use up to eight distinct public domain names without schemes, paths or wildcards.')
    return [q.strip() for q in queries], [d.lower() for d in domains]


def allowed(url, domains):
    host = urlsplit(orchestrator_web.public_url(url)).hostname
    return not domains or any(host == d or host.endswith('.' + d) for d in domains)


def collect(queries, domains, model, control, config, *, prepared_spec=None, session_factory=None):
    """Return fetched candidates; no result is promoted to a verified fact."""
    queries, domains = validate(queries, domains)
    if prepared_spec is not None:
        declared=validate_prepared(prepared_spec['data'])
        if queries!=declared:raise ValueError('Prepared queries differ from the frozen specification.')
    if not isinstance(model, str) or not model or config.get('models', {}).get('text') != model:
        raise ValueError('The selected Gemini text model changed; no search was sent.')
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    entries = [];page_cache={};stopped=None
    discoveries=[]
    if prepared_spec is not None:
        # Discover across the whole inventory before spending reads on the first
        # few results. Retain original sessions/journals; never repeat a search.
        unavailable=None
        for index,query in enumerate(queries,1):
            session=(session_factory or orchestrator_web.Session)(control/f'query-{index:02d}.json',config)
            if unavailable is not None:discoveries.append((session,unavailable));continue
            try:found=session.search(query)
            except gemini.ProviderError as exc:
                from .search_outcomes import unavailable as classify
                if classify(exc) is None:raise
                found=exc;unavailable=exc
            except (ValueError,OSError) as exc:
                from .runtime_outcomes import Hold
                if isinstance(exc,Hold):raise
                found=exc
            discoveries.append((session,found))
    remaining_reads=80-len(queries)
    for index, query in enumerate(queries, 1):
        session = discoveries[index-1][0] if discoveries else (session_factory or orchestrator_web.Session)(control / f'query-{index:02d}.json', config)
        entry = {'query': query, 'status': 'unresolved', 'search_queries': [],
                 'searched_at': None, 'grounding': [], 'pages': [], 'errors': [], 'retrievals': []}
        if stopped is not None:
            entry.update(status='not_submitted',search_outcome=dict(stopped,batch_stopped_at=stopped_at))
            entries.append(entry)
            continue
        try:
            search = discoveries[index-1][1] if discoveries else session.search(query)
            if isinstance(search,Exception):raise search
        except gemini.ProviderError as exc:
            from .search_outcomes import unavailable
            stopped=unavailable(exc)
            if stopped is not None:
                stopped_at=index
                entry.update(status='unavailable',search_outcome=stopped)
                entry['errors'].append('Search unavailable: '+str(exc))
                entries.append(entry)
                continue
            # Session.search retains the submitted/uncertain receipt. Stop here;
            # neither this operation nor recovery may resubmit an uncertain call.
            raise
        except (ValueError, OSError) as exc:
            # A runtime authority/capacity hold is terminal for the operation,
            # not evidence that this individual query had no matching source.
            from .runtime_outcomes import Hold
            if isinstance(exc,Hold):raise
            entry['errors'].append('Search: ' + str(exc))
            entries.append(entry)
            continue
        if search.get('observation_outcome') is not None:
            entry['observation_outcome']=search['observation_outcome']
        entry['search_queries'] = search['queries']
        entry['searched_at'] = search['retrieved_at']
        entry['grounding'] = [source for source in search['sources'] if allowed(source['url'], domains) or orchestrator_web.grounding_redirect(source['url'])]
        if not entry['grounding']:
            entry['errors'].append('No grounding source matched the selected domains.')
        # Domain-like publisher titles are scheduling hints, never evidence.
        # Every redirect destination still passes the downloader's domain guard.
        ordered=sorted(entry['grounding'],key=lambda s:(0 if allowed(s['url'],domains) else 1 if s.get('title','').strip().lower() in domains else 2,0 if re.search(r'/(?:products?|p|pd|ip)/',urlsplit(s['url']).path,re.I) else 1))
        candidates=[];seen=set()
        for source in ordered:
            identity=page_identity(source['url'])
            if identity in seen:continue
            seen.add(identity);candidates.append(source)
        # Fallback reads use an additional observed candidate, never a made-up URL
        # or another paid search. Keep the registered aggregate read allocation.
        allocation=80 if prepared_spec is not None else 60
        page_limit=min(orchestrator_web.MAX_FETCHES,remaining_reads//(len(queries)-index+1)) if prepared_spec is not None else min(3,allocation//len(queries)-1)
        entry['fallback_reads']=[]
        reads=0;position=0;host_reads={}
        while candidates and reads<page_limit and position<orchestrator_web.MAX_FETCHES:
            # Fairness across observed publishers, preserving domain restrictions.
            def publisher(source):
                host=urlsplit(source['url']).hostname or ''
                title=source.get('title','').strip().lower()
                return title if orchestrator_web.grounding_redirect(source['url']) and re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',title) else host
            candidates.sort(key=lambda source:host_reads.get(publisher(source),0))
            source=candidates.pop(0)
            host=publisher(source);host_reads[host]=host_reads.get(host,0)+1
            if len(entry['pages'])>=MAX_PAGES_PER_QUERY and prepared_spec is None:break
            if position>=MAX_PAGES_PER_QUERY and len(entry['pages'])<MAX_PAGES_PER_QUERY and entry['errors']:
                entry['fallback_reads'].append(dict(url=source['url'],reason='Earlier observed candidates failed; bounded same-grant fallback.'))
            try:
                cached=page_cache.get(page_identity(source['url']))
                if cached:
                    page,ref=cached
                    page=dict(page,reused_from=ref)
                else:
                    reads+=1
                    page = session.fetch(source['url'], 0, orchestrator_web.MAX_CHARS,
                                         allowed_hosts=domains or None)
                if not allowed(page['url'], domains):
                    entry['errors'].append('Redirect left the selected domains: ' + page['url'])
                    continue
                entry['retrievals'].append(dict(url=source['url'],publisher=host,outcome='fetched',resolved_url=page['url']))
                entry['pages'].append({key: page[key] for key in
                    ('url', 'requested_url', 'title', 'text', 'retrieved_at', 'sha256', 'content_type',
                     'total_characters', 'next_offset')})
                entry['pages'][-1].update({k:page[k] for k in ('raw_bytes','raw_byte_limit','links','images','products') if k in page})
                if source.get('observed_link_from'):entry['pages'][-1]['observed_link_from']=source['observed_link_from']
                if cached:entry['pages'][-1].update(reused_from=ref,grounded_url=source['url'])
                else:
                    ref=f'entries[{len(entries)}].pages[{len(entry["pages"])-1}]'
                    for identity in (page_identity(source['url']),page_identity(page['url'])):
                        page_cache.setdefault(identity,(dict(entry['pages'][-1]),ref))
                # Follow literal product links from fetched category pages.
                # URL shape is a scheduling hint, never accepted product evidence.
                if prepared_spec is not None:
                    follow=[]
                    product_links=[p.get('url') for p in page.get('products',[]) if isinstance(p,dict) and p.get('url')]
                    product_links.extend(o['url'] for p in page.get('products',[]) if isinstance(p,dict) for o in p.get('offers',[]) if isinstance(o,dict) and o.get('url'))
                    links=product_links+([] if page.get('products') else page.get('links',[]))
                    for link in links:
                        url=link if isinstance(link,str) else link.get('url','')
                        if not url or not allowed(url,domains):continue
                        key=page_identity(url)
                        if key in seen or key==page_identity(page['url']) or not (url in product_links or re.search(r'/(?:products?|p|pd|ip)/',urlsplit(url).path,re.I)):continue
                        seen.add(key)
                        follow.append(dict(url=url,observed_link_from=dict(url=page['url'],sha256=page['sha256'])))
                    candidates=follow[:page_limit-reads]+candidates
            except (ValueError, OSError, http.client.HTTPException) as exc:
                entry['retrievals'].append(dict(url=source['url'],publisher=host,outcome='failed',error=str(exc)))
                entry['errors'].append('Fetch ' + source['url'] + ': ' + str(exc))
            position+=1
        entry['read_allocation']=dict(limit=page_limit,submitted=reads,basis=str(allocation)+' aggregate searches and reads; cache reuse does not submit another read')
        if prepared_spec is not None:remaining_reads-=reads
        if entry['pages']:
            entry['status'] = 'source_fetched'
        elif entry['grounding']:
            entry['status'] = 'search_only'
        entries.append(entry)
    pack = {'version': 1, 'kind': 'public_source_candidates', 'provider': 'Gemini with Google Search',
            'model': model, 'domains': domains, 'created_at': time.time(), 'entries': entries,
            'interpretation': 'Search grounding and fetched pages are source candidates, not verified facts. Check the exact subject in each page.'}
    if prepared_spec is not None:
        pack['query_specification']={k:prepared_spec[k] for k in ('path','sha256','data')}
        for entry in entries:
            entry['target_ids']=[t['id'] for t in prepared_spec['data']['targets'] if entry['query'] in t['queries']]
        pack['candidate_pool']=[dict(target=t['id'],goal=t['required_options'],
            links=list(dict.fromkeys(s['url'] for e in entries if t['id'] in e['target_ids'] for s in e['grounding'])),
            interpretation='Discovery links, not selected designs. Inspect product images and deduplicate designs before counting; unknown buying facts remain unknown.') for t in prepared_spec['data']['targets']]
        pack['read_budget']=dict(maximum=80,search_slots=len(queries),submitted_reads=80-len(queries)-remaining_reads,
            policy='All mapped discovery before reads; unused read allocation rolls forward without increasing the aggregate bound.')
    pack['mechanical']=mechanical_index(pack)
    return json.dumps(pack, ensure_ascii=False, sort_keys=True), {
        'queries': len(entries), 'grounded': sum(bool(e['grounding']) for e in entries),
        'fetched': sum(bool(e['pages']) for e in entries),
        'unresolved': sum(not e['pages'] for e in entries)}


PREPARED_INSTRUCTIONS = """For searches whose subjects depend on an image, document,
extraction or other upstream observation, do not guess literal queries during
planning or run generic discovery in parallel and call it task-specific research.
Use an inspection/preparation agent to produce one query JSON with version=1 and
targets=[{id, queries, required_options}]. Targets map to the observed item IDs;
queries are literal, specific public searches preserving country and budget.
Use at most 20 targets and 20 distinct queries per operation; split larger batches.
Prefer a broad visual-description query per subject before narrower alternatives.
Gather a pool of distinct candidate designs before spending the allowance on
buying-detail verification. Retain search links as leads, never as approved products.
Unknown buying details do not disqualify an independently judged visual alternative.
Independently review that JSON against the exact observations and user request.
web.sources.prepared consumes only that reviewed JSON; depend on its author AND
reviewer. Its parameters are domains and model; the JSON cannot change either.
Its source-pack reviewer must consume the query JSON, check target coverage,
product-specific source correspondence under the compiled count policy. With a
required count, missing required coverage means revise/blocked. With a target
count, retain supported options and disclose unresolved targets without inventing
facts. The source pack's mechanical index groups URLs and captures in code;
reviewers judge correspondence and factual support, not URL duplicates or hashes.
Repeated text alone is not product identity. Source
collection retrieves candidates; it does not verify purchasability. Final authors
and reviewers must inspect product-specific price, variant, dimensions, availability
and visual comparisons. A homepage or overview is not substitute product evidence.
When exact queries are already established, legacy web.sources remains available.
"""


def validate_prepared(data):
    from .operation_contracts import fields
    fields(data,('version','targets'))
    if type(data['version']) is not int or data['version']!=1:
        raise ValueError('Unsupported prepared query version.')
    targets=data['targets']
    if not isinstance(targets,list) or not 1<=len(targets)<=20:
        raise ValueError('Use 1–20 target mappings per prepared research batch.')
    ids=set();queries=[]
    for target in targets:
        fields(target,('id','queries','required_options'))
        ident=target['id']
        if not isinstance(ident,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}',ident) or ident in ids:
            raise ValueError('Prepared research needs distinct bounded target IDs.')
        ids.add(ident)
        if type(target['required_options']) is not int or not 1<=target['required_options']<=10:
            raise ValueError('Use an explicit required option count of 1–10 per target.')
        literal,_=validate(target['queries'],[])
        if literal!=target['queries']:raise ValueError('Prepared queries must be exact trimmed strings.')
    from .collection_core import coverage_queries
    queries=coverage_queries(targets)
    validate(queries,[])
    return queries


def prepared_document(documents):
    if len(documents)!=1 or documents[0].get('text') is None:
        raise ValueError('Prepared research requires exactly one frozen JSON specification.')
    doc=documents[0]
    # Duplicate fields must not silently change the reviewed request.
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate prepared query field.')
            value[key]=item
        return value
    data=json.loads(doc['text'],object_pairs_hook=unique)
    queries=validate_prepared(data)
    return queries,{'path':doc['path'],'sha256':doc['sha256'],'data':data}


def prepared_validator_source():
    """Freeze the same pure query checker for authors and independent reviewers."""
    import inspect
    from .operation_contracts import fields
    checker=inspect.getsource(validate_prepared).replace('    from .operation_contracts import fields\n','')
    return ('import json, re, sys\nMAX_QUERIES = '+repr(MAX_QUERIES)+'\nMAX_DOMAINS = '+repr(MAX_DOMAINS)+'\n\n'+
            inspect.getsource(fields)+'\n'+inspect.getsource(validate)+'\n'+checker+'\n'+
            inspect.getsource(prepared_document)+'\n'+
            'if __name__ == "__main__":\n'
            '    with open(sys.argv[1], encoding="utf-8") as f: content=f.read()\n'
            '    queries,spec=prepared_document([{"path":sys.argv[1],"sha256":"standalone", "text":content}])\n'
            '    print("RELAY_PREPARED_RESEARCH_CONTRACT_VALID",len(queries))\n')
