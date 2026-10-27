"""A registered browser-read fallback over literal observed candidates only."""
import copy,hashlib,json,os
from pathlib import Path
from .web_sources import allowed,mechanical_index,page_identity


class ReadCancelled(ValueError):
    """Confirmed stop, with no unresolved read; never permission to replay."""


def check_cancel(root):
    stop=root/'fallback-stop.json'
    if not (root/'cancel.json').exists() and not stop.exists():return
    from .operation_inspection import rendered
    from .runtime_outcomes import UncertainOperation
    from .workers import atomic
    observation={};rendered(root,observation,{})
    if observation.get('status')=='uncertain':raise UncertainOperation(observation['reason'])
    if not stop.exists():atomic(stop,dict(reason='Source reading cancelled',replay=False))
    raise ReadCancelled('Source reading cancelled; saved receipts retained without replay')


POLICY=dict(version=1,url_attempts=3,reader_attempts=1,publisher_recovery_reads=4,publisher_reads_per_batch=2)


def reader_kind(policy):
    # A different helper hash or observation allowance is not a new reader.
    return 'native' if policy is not None else 'rendered'


def groups(entry):
    return ['target:'+str(t) for t in entry.get('target_ids',[])] or ['query:'+digest(entry.get('query',''))]


def observed_links(entry):
    """Follow only literal links retained by a permitted reader, with ancestry."""
    import re
    from urllib.parse import urlsplit
    result=[]
    for page in entry.get('pages',[]):
        products=[p.get('url') for p in page.get('products',[]) if isinstance(p,dict) and p.get('url')]
        for value in products+page.get('links',[]):
            url=value if isinstance(value,str) else value.get('url','')
            if not url or url==page['url']:continue
            if url not in products and not re.search(r'/(?:products?|p|pd|ip)/',urlsplit(url).path,re.I):continue
            result.append((url,'captured_product_link'))
    return result


def image_coverage(pack):
    """Acquisition progress only: URL counts never certify distinct designs."""
    from .discovery_evidence import observations
    counts={}
    for entry in pack['entries']:
        for group in groups(entry):counts.setdefault(group,set())
    for lead in observations(pack):
        value=lead['result']
        if value['images']:
            for group in groups(value):counts.setdefault(group,set()).add(page_identity(value['url']))
    return {key:len(urls) for key,urls in counts.items()}


def candidates(pack,domains,read_policy=None,*,adaptive=False):
    from collections import Counter
    from urllib.parse import urlsplit
    seen={};result=[];attempts=Counter();readers=Counter();hosts=Counter();spent=Counter();observed=set()
    reads=pack.get('rendered_fallback',{}).get('reads',[])
    pixels=image_coverage(pack)
    captured={page_identity(r['url']) for r in reads if r.get('outcome')=='captured' and not adaptive}
    memberships={}
    for entry in pack['entries']:
        group=groups(entry)
        if entry.get('pages'):observed.update(group)
        values=[(r['url'],'http_failed') for r in entry.get('retrievals',[]) if r.get('outcome')=='failed']
        values += [(p.get('requested_url') or p['url'],'rendered_observation_missing') for p in entry.get('pages',[])
                   if p.get('content_type','text/html') in ('text/html','application/xhtml+xml')]
        values += [(s['url'],'observed_candidate_unread') for s in entry.get('grounding',[])]
        values += observed_links(entry)
        for r in entry.get('retrievals',[]):
            key=page_identity(r['url']);attempts[key]+=1;readers[(key,'http')]+=1
        for url,_ in values:memberships.setdefault(page_identity(url),set()).update(group)
        for page in entry.get('pages',[]):
            key=page_identity(page.get('requested_url') or page['url'])
            method='rendered' if page.get('capture_method')=='isolated-rendered-dom' else 'http'
            # A completed direct capture is reusable even when an old pack has
            # no retrieval row. Do not fetch it again to discover its images.
            if adaptive:
                readers[(key,method)]=max(1,readers[(key,method)])
                if page.get('images'):captured.add(key)
            elif method=='rendered':captured.add(key)
    for r in reads:
        key=page_identity(r['url']);host=urlsplit(key).hostname
        attempts[key]+=1;readers[(key,r.get('reader') or reader_kind(r.get('read_policy')))]+=1;hosts[host]+=1
        spent.update(r.get('groups') or memberships.get(key,[]))
    for ei,entry in enumerate(pack['entries']):
        values=[(s['url'],'observed_candidate_unread') for s in entry.get('grounding',[])]
        values += [(r['url'],'http_failed') for r in entry.get('retrievals',[]) if r.get('outcome')=='failed']
        values += [(p.get('requested_url') or p['url'],'rendered_observation_missing') for p in entry.get('pages',[])
                   if p.get('content_type','text/html') in ('text/html','application/xhtml+xml')]
        values += observed_links(entry)
        for url,reason in values:
            try:permitted=allowed(url,domains) and allowed(url,pack.get('domains',[]))
            except ValueError:continue
            key=page_identity(url);host=urlsplit(key).hostname
            method=reader_kind(read_policy)
            if adaptive:method='http' if readers[(key,'http')]==0 else 'rendered'
            if (not permitted or key in captured or attempts[key]>=POLICY['url_attempts'] or
                    readers[(key,method)]>=POLICY['reader_attempts'] or
                    hosts[host]>=POLICY['publisher_recovery_reads']):continue
            if key in seen:
                seen[key]['target_ids']=list(dict.fromkeys(seen[key]['target_ids']+entry.get('target_ids',[])))
                continue
            candidate=dict(url=url,target_ids=list(entry.get('target_ids',[])),groups=sorted(memberships[key]),entry=ei,reason=reason)
            if adaptive:candidate['reader']=method
            seen[key]=candidate;result.append(candidate)
    # Durable round-robin, including untagged queries. Captured text is an
    # observation, never a claim that purchasing facts are complete or accepted.
    ordered=[];batch_hosts=Counter()
    while result:
        eligible=[c for c in result if batch_hosts[urlsplit(c['url']).hostname]<POLICY['publisher_reads_per_batch']
                  and hosts[urlsplit(c['url']).hostname]+batch_hosts[urlsplit(c['url']).hostname]<POLICY['publisher_recovery_reads']]
        if not eligible:break
        def rank(c):
            key=page_identity(c['url']);host=urlsplit(key).hostname
            return (min(pixels.get(g,0) for g in c['groups']),min(spent[g] for g in c['groups']),all(g in observed for g in c['groups']),
                    0 if adaptive and c['reader']=='rendered' else 1,attempts[key],hosts[host]+batch_hosts[host])
        candidate=min(eligible,key=rank);result.remove(candidate);ordered.append(candidate)
        spent.update(candidate['groups']);batch_hosts[urlsplit(candidate['url']).hostname]+=1
    return ordered


def extends(previous,current):
    """Registered append-only evidence relation; no semantic acceptance."""
    if previous.get('kind')!='public_source_candidates' or current.get('kind')!=previous.get('kind'):return False
    if current.get('source_recovery',{}).get('parent_sha256')!=digest(previous):return False
    if any(current.get(k)!=v for k,v in previous.items() if k not in ('entries','rendered_fallback','mechanical','source_recovery')):return False
    entries=previous.get('entries',[]);reads=previous.get('rendered_fallback',{}).get('reads',[])
    return (current.get('entries',[])[:len(entries)]==entries and
            current.get('rendered_fallback',{}).get('reads',[])[:len(reads)]==reads and
            len(current.get('entries',[]))>len(entries))


def collect(pack,domains,maximum,control,renderer=None,*,read_policy=None):
    if pack.get('version')!=1 or pack.get('kind')!='public_source_candidates':raise ValueError('Fallback requires an exact native source pack')
    if type(maximum) is not int or not 1<=maximum<=12:raise ValueError('Rendered fallback needs 1–12 bounded page reads')
    from .web_sources import validate
    validate(['domain validation'],domains)
    validate(['original domain validation'],pack.get('domains',[]))
    original=pack.get('domains',[])
    effective_domains=domain_intersection(domains,original)
    adaptive=renderer is None and read_policy is None
    if renderer is None:
        from task_relay.source_browser import render
        renderer=render
    from .workers import atomic
    from .runtime_outcomes import UncertainOperation
    root=Path(control);root.mkdir(parents=True,exist_ok=True)
    check_cancel(root)
    selected=candidates(pack,domains,read_policy,adaptive=adaptive)[:maximum]
    identity=dict(version=3,recovery_policy=POLICY,source_sha256=digest(pack),domains=domains,effective_domains=effective_domains,maximum=maximum,candidates=selected,
                  acquisition='recompute from committed observations after each read; no suitability inference')
    if read_policy is not None:identity['read_policy']=copy.deepcopy(read_policy)
    if adaptive:identity['readers']=['http','rendered']
    manifest=root/'fallback-intent.json'
    if manifest.exists():
        if manifest.is_symlink() or json.loads(manifest.read_text())!=identity:
            raise ValueError('Fallback source, selection or grant changed; no replay')
    else:exclusive(manifest,identity)
    output=copy.deepcopy(pack);receipts=[]
    from collections import Counter
    from urllib.parse import urlsplit
    batch_hosts=Counter()
    for index in range(maximum):
        eligible=[c for c in candidates(output,domains,read_policy,adaptive=adaptive)
                  if batch_hosts[urlsplit(c['url']).hostname]<POLICY['publisher_reads_per_batch']]
        if not eligible:break
        c=eligible[0];batch_hosts[urlsplit(c['url']).hostname]+=1
        check_cancel(root)
        read_root=root/('render-'+str(index+1));read_root.mkdir(exist_ok=True)
        intent=read_root/'fallback-read-intent.json';outcome=read_root/'fallback-read-outcome.json'
        entry=dict(query=output['entries'][c['entry']]['query'],target_ids=c['target_ids'],status='unresolved',pages=[],errors=[],
                   grounding=[],search_queries=[],searched_at=None,fallback=dict(kind='rendered-public-page',observed_url=c['url'],reason=c['reason']))
        if intent.exists():
            if intent.is_symlink() or json.loads(intent.read_text())!=c:raise ValueError('Fallback read identity changed')
            if not outcome.exists():raise UncertainOperation('Previous fallback read has no confirmed outcome; no replay')
            if outcome.is_symlink():raise ValueError('Fallback outcome cannot be a symlink')
            saved=json.loads(outcome.read_text())
            if saved.get('identity')!=c or saved.get('sha256')!=digest(saved.get('result')):
                raise ValueError('Fallback outcome identity or evidence changed')
            result=saved['result']
        else:
            exclusive(intent,c)
            try:
                if c.get('reader')=='http':
                    from task_relay.source_browser import read_http
                    page=read_http(c['url'],effective_domains,read_root)
                else:page=renderer(c['url'],effective_domains,read_root)
                if not allowed(page['url'],domains) or not allowed(page['url'],pack.get('domains',[])):
                    raise ValueError('Rendered fallback left selected domains')
                result=dict(page=page)
            except UncertainOperation:raise
            except ReadCancelled as exc:
                result=dict(error=str(exc),cancelled=True)
            except (ValueError,OSError) as exc:
                if any((read_root/(kind+'-intent.json')).exists() and not (read_root/(kind+'-outcome.json')).exists() for kind in ('render','http')):
                    raise UncertainOperation('Renderer has an unresolved read; no replay') from exc
                result=dict(error=str(exc))
            atomic(outcome,dict(identity=c,result=result,sha256=digest(result)))
        if result.get('cancelled'):
            atomic(root/'fallback-stop.json',dict(reason=result['error'],replay=False))
        check_cancel(root)
        page=result.get('page')
        if page and page.get('retrieval_status','captured')=='captured':
            entry['pages'].append(page);entry['status']='source_fetched'
            receipts.append(dict(url=c['url'],outcome='captured',sha256=page['sha256']))
        else:
            reason=result.get('error') or page.get('retrieval_reason','Rendered page unavailable')
            entry['errors'].append(reason)
            if page:entry['diagnostic_capture']=page
            receipts.append(dict(url=c['url'],outcome='unavailable',reason=reason))
        receipts[-1]['groups']=c['groups']
        if adaptive:receipts[-1]['reader']=c['reader']
        if read_policy is not None:receipts[-1]['read_policy']=copy.deepcopy(read_policy)
        output['entries'].append(entry)
        output['rendered_fallback']=dict(version=1,maximum=maximum,reads=copy.deepcopy(pack.get('rendered_fallback',{}).get('reads',[]))+copy.deepcopy(receipts),search_requests=0,created_at=manifest.stat().st_mtime)
    if read_policy is not None:
        for receipt in receipts:receipt['read_policy']=copy.deepcopy(read_policy)
    output['rendered_fallback']=dict(version=1,maximum=maximum,reads=copy.deepcopy(pack.get('rendered_fallback',{}).get('reads',[]))+receipts,search_requests=0,created_at=manifest.stat().st_mtime)
    output['source_recovery']=dict(policy=copy.deepcopy(POLICY),parent_sha256=digest(pack),reader=reader_kind(read_policy),acceptance=False)
    output['mechanical']=mechanical_index(output)
    return json.dumps(output,ensure_ascii=False,sort_keys=True),dict(rendered=sum(r['outcome']=='captured' for r in receipts),unavailable=sum(r['outcome']=='unavailable' for r in receipts),search_requests=0,
        fetched=sum(bool(e.get('pages')) for e in output['entries']),recovery_policy=copy.deepcopy(POLICY),
        eligible_remaining=len(candidates(output,domains,read_policy,adaptive=adaptive)),
        image_reference_coverage=image_coverage(output),
        selection_outcome='bounded_reads_completed' if selected else 'no_eligible_unread_candidates_under_scope_and_caps')


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def exclusive(path,value):
    """Durable admission before dispatch; concurrent/restarted calls never replay."""
    from .runtime_outcomes import UncertainOperation
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise UncertainOperation('Fallback admission already exists; inspect saved receipt without replay') from None
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True);stream.flush();os.fsync(stream.fileno())


def domain_intersection(selected,original):
    """Pass the narrower navigation authority to the host, before any request."""
    if not selected:return list(original)
    if not original:return list(selected)
    result=[]
    for left in selected:
        for right in original:
            left=left.lower();right=right.lower()
            if left==right or left.endswith('.'+right):result.append(left)
            elif right.endswith('.'+left):result.append(right)
    # Disjoint lists have no eligible candidates; [] is never dispatched then.
    return list(dict.fromkeys(result))


def review_evidence(control,frozen):
    """Registered source-reader projection; verify original hashes, never reread."""
    from .runtime import safe_file,file_hash
    records=[]
    for folder in sorted(Path(control).glob('render-*')):
        if not folder.is_dir():continue
        names=['fallback-read-intent.json','fallback-read-outcome.json']
        if (folder/'http-outcome.json').exists():
            value=json.loads(safe_file(folder,'http-outcome.json').read_text())
            names+=['http-intent.json','http-outcome.json']
            if value.get('evidence_sha256'):
                if file_hash(safe_file(folder,'http/page-1.json'))!=value['evidence_sha256']:raise ValueError('HTTP review evidence changed')
                names.append('http/page-1.json')
        outcome=folder/'render-outcome.json'
        if outcome.exists():
            value=json.loads(safe_file(folder,'render-outcome.json').read_text())
            names+=['render-intent.json','render-outcome.json']
            for name,sha in value.get('evidence',{}).items():
                if file_hash(safe_file(folder,name))!=sha:raise ValueError('Source review evidence changed')
                names.append(name)
            if (folder/'native-receipts.json').exists():
                from task_relay import computer_sessions
                native=json.loads(safe_file(folder,'native-receipts.json').read_text())
                for action in native['actions']:
                    if action.get('receipt'):computer_sessions._verify_receipt(action['receipt'])
        for name in dict.fromkeys(names):
            p=safe_file(folder,name);raw=p.read_bytes()
            records.append(dict(path=folder.name+'/'+name,sha256=hashlib.sha256(raw).hexdigest(),text=raw.decode('utf-8')))
    return records
