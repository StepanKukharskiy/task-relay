"""Keep external source checks within the capabilities frozen for a stage."""

import re
import json
from pathlib import Path,PurePosixPath


_ARTICLE = re.compile(r"\b(?:артикул\w*|part\s*(?:number|no\.?|#)|sku)\b", re.I)
_CONFIRM = re.compile(r"(?:подтвержд\w*|проверк\w*|верифицир\w*|verif\w*|confirm\w*)", re.I)
_SOURCE = re.compile(r"(?:источник\w*|каталог\w*|производител\w*|source\w*|catalog\w*|manufacturer|oem)", re.I)
_ONLINE = re.compile(r"(?:интернет\w*|онлайн|открыт\w* доступ\w*|public\s+(?:web|source)|online|on\s+the\s+web)", re.I)
_CATALOG = re.compile(r"(?:каталог\w*|catalog\w*|oem|service\s+manual|схем\w*)", re.I)
_RESEARCH = re.compile(r"\b(?:research|search|look\s*up)\b|(?:поиск\w*|исследован\w*)", re.I)
_PART_IDENTIFIERS = re.compile(r"\b(?:articles?|part[\s-]*(?:numbers?|no\.?|#)|sku)\b|артикул\w*", re.I)
_URL = re.compile(r"\burls?\b|источник\w*|ссылк\w*", re.I)


def required(request):
    """Recognize explicit source verification, not ordinary source-grounded writing."""
    if not isinstance(request, str):
        return False
    words = " ".join(request.split())
    return bool((_ARTICLE.search(words) and _CONFIRM.search(words) and _SOURCE.search(words))
                or (_ONLINE.search(words) and _CONFIRM.search(words) and _SOURCE.search(words))
                or (_CATALOG.search(words) and _CONFIRM.search(words))
                or (_RESEARCH.search(words) and _CATALOG.search(words)
                    and _PART_IDENTIFIERS.search(words) and _URL.search(words)))


def supplied(payload):
    """An explicitly selected catalog/research source can replace a live lookup."""
    options = payload.get('options', {})
    selected={(s['artifact'],s.get('sha256'),s.get('bytes')) for s in payload.get('sources',[]) if s.get('artifact')}
    if any(r.get('capability','web.sources') in ('web.sources','web.sources.prepared')
           and (r['artifact'],r['sha256'],r['bytes']) in selected
           for r in payload.get('recorded_external_sources',[])):
        return True
    if options.get('research_ids') or options.get('reference_pack_id'):
        return True
    for source in payload.get('sources', []):
        path = source.get('path', '')
        if source.get('request_context') or PurePosixPath(path).name == 'conversation.json':
            continue
        if _CATALOG.search(PurePosixPath(path).name):
            return True
    return False


def recorded_sources(rt, sources, *, attempts=None, allow_empty=False, _seen=frozenset()):
    """Match selected bytes to a finished native fetched-page receipt.

    Aliases retain provenance through content identity. This establishes saved
    source availability, never fresh stock or semantic product correspondence.
    """
    records=[]
    for source in sources:
        rows=rt.db.execute('''SELECT a.id AS origin_artifact,a.path AS origin_path,p.id AS attempt,p.frozen,p.receipt,p.state
            FROM production_artifacts a JOIN production_attempts p ON p.id=a.attempt
            WHERE a.sha256=? AND a.bytes=? AND p.state IN ('completed','blocked','failed') ORDER BY a.id''',
            (source['sha256'],source['bytes']))
        for row in rows:
            if row['attempt'] in _seen or len(_seen)>=40:continue
            if attempts is not None and row['attempt'] not in attempts:continue
            frozen=json.loads(row['frozen']);receipt=json.loads(row['receipt'] or '{}')
            if frozen.get('work_tools'):
                from orchestrator.evidence_recovery import committed
                artifact=rt.artifact(row['origin_artifact'])
                matches=list(committed(rt,artifact))
                if len(matches)!=1:continue
                _,sub,operation=matches[0]
                # Use only the verified registered output receipt, never the
                # enclosing worker's decision or a JSON assertion of capture.
                frozen=sub
                receipt=dict(status='finished',pending_requests=[],operation=operation)
            elif row['state']!='completed':
                # A collected code-owned evidence export may be structurally
                # proven even when the enclosing semantic work was rejected.
                # Only the reconstruction branch below may establish ancestry;
                # this does not approve its catalog or broaden native receipts.
                contract=frozen.get('operation_contract',{})
                from orchestrator.operation_contracts import identity
                try:role=identity({k:contract[k] for k in ('id','version')}).get('record_role')
                except (KeyError,ValueError):continue
                if role!='options' or contract.get('parameters',{}).get('source_pack_output')!=row['origin_path']:continue
            operation=receipt.get('operation',{})
            fetched=operation.get('validation',{}).get('fetched')
            capability=frozen.get('execution',{}).get('capability')
            from orchestrator.execution import REGISTRY
            reuse=REGISTRY.get(capability,{}).get('saved_evidence')
            if REGISTRY.get(capability,{}).get('native_adapter')=='reviewed-record-merge':
                # The native join copies its bound source pack byte-for-byte.
                # Follow that exact parent rather than treating catalog output
                # hashes or merge completion as new source verification.
                if (row['origin_path']!='delivery/source-pack.json' or receipt.get('status')!='finished'
                        or receipt.get('pending_requests') or operation.get('outcome')!='completed'):continue
                try:
                    path=frozen['execution']['parameters']['source_pack_path']
                    item=next(i for i in frozen['inputs'] if i['path']==path)
                    artifact=rt.artifact(item['artifact'])
                    if item['sha256']!=source['sha256'] or (artifact['sha256'],artifact['bytes'])!=(source['sha256'],source['bytes']):continue
                    parent=recorded_sources(rt,[{**item,'bytes':artifact['bytes']}],allow_empty=allow_empty,_seen=_seen|{row['attempt']})
                    if not parent:continue
                except (KeyError,StopIteration,ValueError):continue
                records.append(dict(artifact=source['artifact'],sha256=source['sha256'],bytes=source['bytes'],
                    origin_artifact=row['origin_artifact'],attempt=row['attempt'],composition=True,
                    native_parents=[item['artifact']],evidence='Exact native source-pack passthrough with recorded capture ancestry; no product acceptance.'))
                break
            from orchestrator.operation_contracts import identity as record_family
            contract=frozen.get('operation_contract')
            try:family=record_family({k:contract[k] for k in ('id','version')}) if contract else {}
            except (KeyError,ValueError):continue
            if not reuse and family.get('record_role')=='options':
                # A code-owned composed export is an exact append of proven
                # captures. Reconstruct it from its frozen inputs and committed
                # records; a JSON "composition" assertion is never sufficient.
                from orchestrator import operation_records,sourcing_contract
                params=frozen['operation_contract']['parameters']
                if params.get('source_pack_output')!=row['origin_path'] or receipt.get('status')!='finished' or receipt.get('pending_requests'):continue
                try:
                    inputs={i['path']:i for i in frozen['inputs']}
                    parents=[{**inputs[params[k]],'bytes':rt.artifact(inputs[params[k]]['artifact'])['bytes']} for k in ('source_pack_path','base_source_pack_path')]
                    if any(not recorded_sources(rt,[i],allow_empty=True,_seen=_seen|{row['attempt']}) for i in parents):continue
                    def read(path):
                        item=inputs[path];artifact=rt.artifact(item['artifact']);raw=Path(artifact['blob']).read_bytes()
                        import hashlib
                        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Composed evidence input changed')
                        return raw
                    ctx=sourcing_contract.context(frozen,read)
                    raw=ctx['composed_source_pack']
                    import hashlib
                    if hashlib.sha256(raw).hexdigest()!=source['sha256'] or len(raw)!=source['bytes']:
                        # Earlier exports used this exact canonical serializer
                        # even for unchanged captures. Reconstruct that known
                        # version, never arbitrary JSON/content equivalence.
                        from orchestrator.operation_contracts import encoded
                        legacy=(encoded(json.loads(raw))+'\n').encode()
                        if hashlib.sha256(legacy).hexdigest()!=source['sha256'] or len(legacy)!=source['bytes']:continue
                        ctx={**ctx,'source_versions':{**ctx['source_versions'],'source_pack_sha256':source['sha256']}}
                    store=operation_records.Store(frozen,rt.db);_,fragments=store._state(rt.db)
                    document=sourcing_contract.options_document(fragments,params,ctx)
                    sourcing_contract.validate_result(document,dict(decision='delivered'))
                except (ValueError,OSError,KeyError,TypeError):continue
                records.append(dict(artifact=source['artifact'],sha256=source['sha256'],bytes=source['bytes'],
                    origin_artifact=row['origin_artifact'],attempt=row['attempt'],composition=True,
                    native_parents=[i['artifact'] for i in parents],evidence='Exact code-owned appended native captures; not product acceptance or a new lookup.'))
                break
            if (not reuse
                    or receipt.get('status')!='finished' or receipt.get('pending_requests')
                    or operation.get('output_sha256')!=source['sha256']):
                continue
            if reuse['kind']=='photos':
                coverage=operation.get('validation',{}).get('coverage',{})
                partial=frozen.get('execution',{}).get('parameters',{}).get('count_policy')=='target'
                if operation.get('outcome')!='completed' or type(coverage.get('found')) is not int or coverage['found']<(0 if capability=='images.products' and partial else 1):continue
            elif type(fetched) is not int or fetched<(0 if allow_empty else 1):continue
            records.append(dict(artifact=source['artifact'],sha256=source['sha256'],bytes=source['bytes'],
                                origin_artifact=row['origin_artifact'],attempt=row['attempt'],
                                evidence='Exact saved native fetched-page output; not a new lookup, stock guarantee or accepted product claim.'))
            if reuse['kind']=='photos':records[-1].update(capability=reuse['capability'],evidence='Exact saved native photo ZIP; no replay, new discovery or semantic acceptance.')
            break
    return records


def research_available(payload):
    options = payload.get('options', {})
    return (bool(set(options.get('step_capabilities', [])) & {'web.sources','web.sources.prepared'})
            or (bool(set(options.get('optional_research_capabilities', [])) & {'web.sources','web.sources.prepared'})
                and (payload.get('research_mode')=='sources' or payload.get('research_advice_version')==1))
            or any(set(item.get('capabilities', [])) & {'browser.use','computer.use'}
                   for item in options.get('worker_catalog', [])))


def needed(payload):
    # The frozen stage defines this assignment. Retaining the whole user request
    # as context must not pull later-stage lookups into an image/text preparation.
    stage=payload.get('pipeline_step')
    request=('\n'.join([stage['instruction'],*stage.get('deliverables',{}).values()])
             if stage else payload.get('original_request'))
    return required(request) and not supplied(payload)


def bind_review_closure(plan):
    """Carry the exact declared research review into its agent consumers."""
    from orchestrator.execution import REGISTRY
    reviews={task['review_of']:task for task in plan['tasks'] if task.get('review_of')}
    sources={task['id'] for task in plan['tasks']
             if REGISTRY.get(task.get('execution',{}).get('capability'),{}).get('saved_evidence',{}).get('kind')=='pages'}
    receipts=[]
    for task in plan['tasks']:
        if task.get('review_of') or task.get('execution'):continue
        upstream={item['from_task'] for item in task['inputs'] if 'from_task' in item}
        for source in sorted(upstream&sources):
            reviewer=reviews.get(source)
            if not reviewer or reviewer['id'] in upstream:continue
            outputs=[output for output in reviewer['outputs'] if output.get('media_type') in ('text/plain','text/markdown','application/json')]
            if not outputs:continue
            for output in outputs:
                from pathlib import PurePosixPath
                path='review-inputs/'+reviewer['id']+'/'+PurePosixPath(output['path']).name
                if any(item['path']==path for item in task['inputs']):raise ValueError('Research review input alias conflicts with a declared input.')
                task['inputs'].append(dict(from_task=reviewer['id'],output=output['path'],path=path,
                    purpose='Exact independent research review accompanying the selected source pack',
                    authority='Unaccepted research assessment; inspect alongside exact source evidence.',media_type=output['media_type']))
                receipts.append(dict(task=task['id'],research=source,reviewer=reviewer['id'],output=output['path'],path=path))
            task['dependencies']=list(dict.fromkeys(task['dependencies']+[reviewer['id']]))
    return receipts


def validate_plan(plan, payload):
    """A file/shell-only plan cannot promise article-specific external evidence."""
    if not needed(payload):
        return
    tasks = {task['id']: task for task in plan['tasks']}
    research = {task['id'] for task in plan['tasks']
                if not task.get('review_of') and task.get('browser')
                and 'browser.use' in task.get('worker', {}).get('requires', [])}
    research.update(task['id'] for task in plan['tasks'] if not task.get('review_of')
                    and task.get('computer') and 'computer.use' in task.get('worker',{}).get('requires',[]))
    research.update(task['id'] for task in plan['tasks']
                    if not task.get('review_of')
                    and task.get('execution', {}).get('capability') in ('web.sources','web.sources.prepared'))
    if not research:
        raise ValueError('External article/source verification requires a browser.use, computer.use or web.sources research step, or selected catalog evidence; file and shell workers cannot establish it.')

    def research_input(task_id, seen=None):
        if task_id in research:
            return True
        seen = set() if seen is None else seen
        if task_id in seen:
            return False
        seen.add(task_id)
        return any(research_input(item['from_task'], seen.copy())
                   for item in tasks[task_id]['inputs'] if 'from_task' in item)

    consumed_by_producer = {item['from_task']
                            for task in plan['tasks'] if not task.get('review_of')
                            for item in task['inputs'] if 'from_task' in item}
    reviewers = {task['review_of']: task for task in plan['tasks']
                 if task.get('review_of')}
    for task in plan['tasks']:
        if task.get('review_of') or task['id'] in research:
            continue
        if task['id'] in consumed_by_producer:
            continue  # Source preparation can precede the research lookup.
        if not research_input(task['id']):
            raise ValueError('The file producer must consume a declared output from the research step; a dependency or instruction alone is not evidence.')
        upstream = {item['from_task'] for item in task['inputs'] if 'from_task' in item}
        for source_id in upstream & research:
            reviewer = reviewers.get(source_id)
            if task.get('execution') and payload.get('external_evidence_policy_version')==2:
                # Fixed operations consume only their registered wire inputs.
                # Their review gate is a dependency, not an extra payload file.
                if reviewer and reviewer['id'] not in task.get('dependencies',[]):
                    raise ValueError('The registered operation must wait for independent review of its research input; keep only its registered inputs.')
            elif reviewer and reviewer['id'] not in upstream:
                raise ValueError('The file producer must consume the independent research review as a declared input alongside the source pack.')
