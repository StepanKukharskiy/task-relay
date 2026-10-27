"""Pure evidence batching and execution-cost estimates; no semantic judgments."""
import hashlib,math

BATCH_CHARACTERS=64000
FINAL_CALLS=2

def review_cost(characters,pages):
    batches=max(math.ceil(characters/BATCH_CHARACTERS),math.ceil(pages/8)) if pages else 0
    return dict(batches=batches,tool_calls=batches+FINAL_CALLS,seconds=60+30*batches)

def record_cost(items,inspection_calls=0,batch=1):
    commits=math.ceil(items/batch)
    return dict(items=items,submission_calls=commits,inspection_calls=inspection_calls,
                finalization_calls=1,correction_calls=2,tool_calls=commits+inspection_calls+3)

def review_batches(pack,ceiling):
    """Read every captured text version; exact repeats alias their first version."""
    if type(ceiling) is not int or ceiling<=FINAL_CALLS:raise ValueError('Review needs evidence and finalization capacity')
    pages=[];seen={};aliases=[]
    for ei,entry in enumerate(pack['entries']):
        for pi,page in enumerate(entry.get('pages',[])):
            ref=f'page-{ei}-{pi}';text=page['text'];key=(page['url'],page.get('sha256'),hashlib.sha256(text.encode()).hexdigest())
            if key in seen:aliases.append(dict(observation=ref,duplicate_of=seen[key]));continue
            seen[key]=ref;pages.append(dict(observation=ref,url=page['url'],text=text,target_ids=entry.get('target_ids',[])))
    characters=sum(len(p['text']) for p in pages)
    capacity=ceiling-FINAL_CALLS
    size=max(BATCH_CHARACTERS,math.ceil(characters/capacity))
    # A batch may combine independent short pages; long captures retain offsets.
    batches=[];current=[];used=0
    for page in pages:
        offset=0
        while offset<len(page['text']) or not page['text'] and offset==0:
            if used==size:batches.append(current);current=[];used=0
            end=min(len(page['text']),offset+size-used)
            current.append({**page,'text':page['text'][offset:end],'offset':offset,'end':end,'characters':len(page['text'])})
            used+=end-offset
            if end==len(page['text']):break
            offset=end
    if current:batches.append(current)
    return dict(version=1,pages=len(pages),aliases=aliases,characters=characters,batch_characters=size,
                batches=batches,required_tool_calls=len(batches)+FINAL_CALLS,
                authority='Exact saved text batches and offsets only; correspondence and purchasing facts require independent review.')


def item_evidence(ctx,item,maximum=12000):
    """Offer literal mapped excerpts without forcing whole-pack inspection."""
    from .sourcing_contract import source_read
    import re
    from .sourcing_contract import field_rules
    rules=field_rules(ctx.get('parameters',{}))
    patterns=[re.escape(field).replace('_','[ _]') for field in rules]
    if 'price' in rules.values():patterns.append(r'\$\s*\d|"price"')
    highlights=re.compile('|'.join(patterns),re.I)
    selected=[];remaining=maximum
    targets=ctx.get('observation_targets',{})
    candidates=[(ident,page) for ident,page in ctx['observations'].items()
                if item in targets.get(ident,[]) or not targets.get(ident)]
    candidates.sort(key=lambda pair: item not in targets.get(pair[0],[]))
    for ident,page in candidates:
        text=page['text'];windows=[(0,min(len(text),1600))]
        for m in highlights.finditer(text):
            start=max(0,m.start()-180);end=min(len(text),m.end()+500)
            if any(a<=start and end<=b for a,b in windows):continue
            windows.append((start,end))
            if len(windows)>=4:break
        excerpts=[]
        for start,end in windows:
            if remaining<=0:break
            end=min(end,start+remaining)
            if end<=start:continue
            excerpts.append(source_read(ctx,dict(observation=ident,offset=start,limit=end-start)));remaining-=end-start
        if excerpts:selected.append(dict(observation=ident,url=page['url'],excerpts=excerpts,characters=len(text),
            correspondence='mapped candidate, not verified' if item in targets.get(ident,[]) else 'unmapped candidate; independently assess relevance'))
        if remaining<=0:break
    return dict(item=item,pages=selected,excerpt_characters=maximum-remaining,
                mapped_pages=sum(item in ids for ids in targets.values()),
                unmapped_pages=sum(not targets.get(ident) for ident in ctx['observations']),
                limitation='Bounded literal excerpts; omitted text remains available through the registered source-read tool. Correspondence and availability are not inferred.')
