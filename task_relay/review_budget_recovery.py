"""Continue a terminated local review of immutable native read evidence."""
import copy
import hashlib
import json


def generation_proof(rt,task,attempt):
    """Known received generation failure of an unchanged local candidate.

    This consumes only the review's remaining original attempt. Transport
    uncertainty, cancellations, host actions and exhausted attempts do not qualify.
    """
    from orchestrator import executors,gemini_worker
    spec=rt.spec(task);frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if (task['status']!='blocked' or task['latest']!=attempt['id'] or task['assignment']!=attempt['assignment']
            or attempt['state']!='blocked' or not spec.get('review_of') or task['attempts']>=spec.get('max_attempts',0)
            or any(spec.get(k) or frozen.get(k) for k in ('user_gate','browser','computer','execution','operation_contract'))
            or frozen.get('backend',{}).get('type') not in (*executors.FILE_TYPES,*executors.CODE_TYPES)
            or receipt.get('status')!='finished' or not receipt.get('exit_code')
            or receipt.get('external_outcome')!='no_pending_response' or receipt.get('pending_requests')!=[]
            or receipt.get('cleanup_error') or receipt.get('token')!=attempt['id']
            or not isinstance(receipt.get('reason'),str)
            or 'incomplete response retained without executing its tools' not in receipt['reason']):return None
    count=receipt.get('api_requests')
    if type(count) is not int or count<1:return None
    control=rt.root/'workers'/attempt['id'];hashes={}
    try:
        requests=sorted(control.glob('api-*.request.json'))
        if len(requests)!=count:return None
        for path in requests:
            request=json.loads(path.read_text());response_path=path.with_name(path.name.replace('.request.json','.response.json'))
            response=json.loads(response_path.read_text())
            if request.get('provider')!=executors.provider_for(frozen['backend']) or request.get('model')!=frozen['backend']['model']:return None
            for p in (path,response_path):hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
        last=requests[-1];recovery_path=last.with_name(last.name.replace('.request.json','.recovery.json'))
        recovery=json.loads(recovery_path.read_text())
        failure=gemini_worker.generation_failure(request['provider'],response)
        if (failure not in ('generation_output_limit','malformed_function_call') or recovery.get('kind')!=failure
                or recovery.get('continued') is not False or recovery.get('executed_calls')!=0):return None
        hashes[recovery_path.name]=hashlib.sha256(recovery_path.read_bytes()).hexdigest()
    except (OSError,ValueError,KeyError,TypeError):return None
    target=rt.task(task['run'],spec['review_of'])
    old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    if (target['status']!='awaiting_review' or target['latest']!=frozen.get('review_target')
            or not old or old['state']!='completed'):return None
    done=json.loads(old['receipt'] or '{}')
    if done.get('status')!='finished' or done.get('exit_code') or done.get('pending_requests'):return None
    for item in frozen['inputs']:
        artifact=rt.artifact(item['artifact'])
        if artifact['sha256']!=item['sha256']:return None
        from orchestrator.runtime import file_hash
        from pathlib import Path
        blob=Path(artifact['blob'])
        if blob.is_symlink() or file_hash(blob)!=item['sha256']:return None
        if item.get('from_task')==target['id'] and artifact['attempt']!=target['latest']:return None
    for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
        if other['status'] in ('running','launching','cancelling','uncertain') or other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
    return dict(task=task['id'],kind='confirmed_review_generation',attempt=attempt['id'],candidate=target['latest'],journal_sha256=hashes,
        instruction='Continue only independent review of this exact saved candidate under the remaining original attempt allowance. Keep the report compact: a short summary and brief evidence per frozen check, plus actionable findings. Use report_check for bounded evidence fragments when available. Preserve all criteria and gaps; never infer acceptance or repeat completed production.')


def input_proof(rt,task,attempt):
    """Recover a proven local observation/tool mismatch, never a semantic rejection."""
    from orchestrator import executors
    from orchestrator.record_lifecycle import definition
    from orchestrator.runtime import file_hash
    from pathlib import Path
    spec=rt.spec(task);frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if (task['status']!='blocked' or task['latest']!=attempt['id'] or task['assignment']!=attempt['assignment']
            or attempt['state']!='blocked' or not spec.get('review_of') or task['attempts']>=spec.get('max_attempts',0)
            or any(spec.get(k) or frozen.get(k) for k in ('user_gate','browser','computer','execution'))
            or frozen.get('backend',{}).get('type') not in executors.FILE_TYPES
            or receipt.get('status')!='finished' or receipt.get('exit_code')!=0 or receipt.get('reason') is not None
            or receipt.get('external_outcome')!='no_pending_response' or receipt.get('pending_requests')!=[]
            or receipt.get('cleanup_error') or receipt.get('token')!=attempt['id']):return None
    contract=frozen.get('operation_contract')
    if not contract or any(spec.get(k)!=frozen.get(k) for k in ('operation_contract','criteria','limits','tools')):return None
    try:
        hooks=definition(contract)
        if not hooks or not hooks.fragment_only:return None
    except (ValueError,KeyError,TypeError):return None
    target=rt.task(task['run'],spec['review_of'])
    candidate=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    if (target['status']!='awaiting_review' or target['latest']!=frozen.get('review_target')
            or not candidate or candidate['state']!='completed'):return None
    done=json.loads(candidate['receipt'] or '{}')
    if done.get('status')!='finished' or done.get('exit_code') or done.get('pending_requests'):return None
    row=rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC LIMIT 1",(attempt['id'],)).fetchone()
    result=json.loads(row[0]).get('result',{}) if row else {}
    if (result.get('decision')!='blocked' or not result.get('findings') or
            any(f.get('category')!='execution' for f in result['findings'])):return None
    bound={i['path'] for i in frozen['inputs'] if i.get('from_task')==spec['review_of']}
    if not bound:return None
    count=receipt.get('api_requests');control=rt.root/'workers'/attempt['id'];hashes={};mismatch=False
    try:
        requests=sorted(control.glob('api-*.request.json'))
        if type(count) is not int or count<1 or len(requests)!=count:return None
        for path in requests:
            response=path.with_name(path.name.replace('.request.json','.response.json'))
            request=json.loads(path.read_text());json.loads(response.read_text())
            if request.get('provider')!=executors.provider_for(frozen['backend']) or request.get('model')!=frozen['backend']['model']:return None
            for p in (path,response):
                if p.is_symlink():return None
                hashes[p.name]=file_hash(p)
            payload=request['payload']
            names={t['name'] for group in payload.get('tools',[]) for t in group.get('functionDeclarations',[])} if request['provider']=='gemini' else {
                t.get('name',t.get('function',{}).get('name')) for t in payload.get('tools',[])}
            for tool in control.glob(path.name.removesuffix('.request.json').replace('api-','tool-')+'-*.json'):
                if tool.is_symlink():return None
                journal=json.loads(tool.read_text());hashes[tool.name]=file_hash(tool)
                error=journal.get('result',{}).get('error','')
                if (journal.get('name')=='finish' and 'file_read' not in names and
                        error in {'Read the complete exact candidate before reporting a review decision: '+p for p in bound}):mismatch=True
        if not mismatch:return None
        for item in frozen['inputs']:
            artifact=rt.artifact(item['artifact']);blob=Path(artifact['blob'])
            if artifact['sha256']!=item['sha256'] or blob.is_symlink() or file_hash(blob)!=item['sha256']:return None
            if item['path'] in bound and artifact['attempt']!=target['latest']:return None
    except (OSError,ValueError,KeyError,TypeError):return None
    for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
        if other['status'] in ('running','launching','cancelling','uncertain') or other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
    return dict(task=task['id'],kind='confirmed_review_input',attempt=attempt['id'],candidate=target['latest'],journal_sha256=hashes,
        instruction='Independently re-review only the exact saved candidate using the corrected bounded candidate-input interface and remaining original attempt. Original item judgments are retained as historical unaccepted work. Inspect supplied candidate text and read any omitted suffixes before finalization. Preserve criteria, inputs, allowances and honest gaps; do not repeat source collection or infer acceptance.')


def proof(rt, task, attempt):
    spec=rt.spec(task);frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if (task['status']!='blocked' or task['latest']!=attempt['id'] or task['assignment']!=attempt['assignment'] or attempt['state']!='blocked'
            or not spec.get('review_of') or spec.get('user_gate')
            or any(frozen.get(k) or spec.get(k) for k in ('browser','computer','execution','operation_contract'))
            or frozen.get('backend',{}).get('type')!='codex-cli'
            or set(frozen.get('tools',[]))-{'files','shell'}
            or receipt.get('status')!='finished' or receipt.get('reason')!='tool_limit'
            or receipt.get('exit_code')!=-15 or receipt.get('token')!=attempt['id']
            or receipt.get('pending_requests') or receipt.get('cleanup_error')
            or receipt.get('browser',{}).get('uncertain_actions')
            or type(receipt.get('tool_calls')) is not int
            or receipt['tool_calls']<=frozen['limits']['tool_calls']):return None
    target=rt.task(task['run'],spec['review_of'])
    if target['status']!='awaiting_review' or target['latest']!=frozen.get('review_target'):return None
    old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    if not old or old['state']!='completed':return None
    source=json.loads(old['frozen']);done=json.loads(old['receipt'] or '{}')
    from orchestrator.execution import REGISTRY
    metadata=REGISTRY.get(source.get('execution',{}).get('capability'),{}).get('saved_evidence',{})
    digest=done.get('operation',{}).get('output_sha256')
    if (metadata.get('kind') not in ('pages','photos') or done.get('status')!='finished'
            or done.get('pending_requests') or done.get('exit_code') or not digest):return None
    bound=[i for i in frozen['inputs'] if i.get('from_task')==target['id']]
    if not bound or not any(i.get('sha256')==digest for i in bound):return None
    for i in frozen['inputs']:
        artifact=rt.artifact(i['artifact'])
        if artifact['sha256']!=i['sha256']:return None
        if i in bound and artifact['attempt']!=target['latest']:return None
    for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
        if other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
    return dict(task=task['id'],kind='saved_review_budget',attempt=attempt['id'],candidate=target['latest'],
                instruction='Finish independent review of these exact saved inputs. The retained draft is unaccepted supporting work; verify its findings against the original evidence and write the structured final report. Preserve disclosed gaps. Do not repeat source collection or conduct new research.')


def validate_generation_parent(rt,task,spec,backend,inputs):
    previous=spec['revision']['previous_attempt']
    old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(previous,)).fetchone()
    if not old or task['latest']!=old['id'] or old['run']!=task['run'] or old['task']!=task['id']:
        raise ValueError('Generation review continuation changed its parent')
    original=dict(task,status='blocked',assignment=old['assignment'])
    checker=input_proof if spec['revision'].get('kind')=='confirmed_review_input' else generation_proof
    gap=checker(rt,original,old)
    if not gap or spec['revision'].get('proof')!=gap:raise ValueError('Generation review continuation proof changed')
    expected=copy.deepcopy(rt.spec(original))
    expected['revision']=spec['revision']
    if spec!=expected or backend!=json.loads(old['frozen'])['backend']:
        raise ValueError('Generation review continuation changed frozen scope')
    frozen=json.loads(old['frozen'])
    identities=lambda rows:sorted((i['path'],i['artifact'],i['sha256']) for i in rows)
    if identities(inputs)!=identities(frozen['inputs']):raise ValueError('Generation review continuation changed input versions')
    rows=rt.db.execute('SELECT baseline FROM completion_recoveries WHERE parent=?',(task['run'],)).fetchall()
    if sum(gap in json.loads(row['baseline'])['gaps'] for row in rows)!=1:
        raise ValueError('Generation review continuation lacks its committed exact baseline')


def continuation(rt, task, attempt, policy):
    gap=proof(rt,task,attempt)
    if not gap:raise ValueError('Review continuation lacks exact confirmed budget-stop evidence')
    spec=copy.deepcopy(rt.spec(task))
    spec['inputs']=[i for i in spec['inputs'] if not (i.get('previous_delivery') and i['path'].startswith('recovery/draft/'))]
    spec['limits']['tool_calls']=policy['tool_calls']
    spec['limits']['provider_requests']=policy['tool_calls']
    spec['limits']['seconds']=policy['seconds']
    spec['max_attempts']=task['attempts']+1
    spec['revision']=dict(kind='saved_review_budget',source='existing_completion_recovery_grant',
                          previous_attempt=attempt['id'],instruction=gap['instruction'])
    paths={i['path'] for i in spec['inputs']}
    for artifact in rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY id',(attempt['id'],)):
        if artifact['path'] not in {o['path'] for o in spec['outputs']}:continue
        path='recovery/draft/'+artifact['path']
        if path in paths:raise ValueError('Review draft binding conflicts with an existing input')
        paths.add(path)
        spec['inputs'].append(dict(artifact=artifact['id'],path=path,purpose='Exact stopped review draft',
                                  authority='Unaccepted draft; check against original sources',previous_delivery=True))
    from orchestrator.contracts import assignment
    return assignment(spec)


def validate_parent(rt,task,spec,backend,inputs):
    from .completion_recovery import DELIVERY_POLICY
    old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(spec['revision']['previous_attempt'],)).fetchone()
    if not old or old['run']!=task['run'] or old['task']!=task['id'] or task['latest']!=old['id']:
        raise ValueError('Review continuation changed its stopped parent')
    # Revalidate against the old assignment while the live task is queued.
    original=dict(task,status='blocked',assignment=old['assignment'])
    expected=continuation(rt,original,old,DELIVERY_POLICY)
    if expected!=spec or backend!=json.loads(old['frozen'])['backend']:
        raise ValueError('Review continuation changed its frozen scope')
    rows=rt.db.execute('SELECT r.baseline,g.policy FROM completion_recoveries r JOIN completion_recovery_grants g ON g.pipeline=r.pipeline WHERE r.parent=?',(task['run'],)).fetchall()
    matches=[r for r in rows if json.loads(r['policy'])==DELIVERY_POLICY and any(
        g.get('kind')=='saved_review_budget' and g.get('attempt')==old['id'] for g in json.loads(r['baseline'])['gaps'])]
    if len(matches)!=1:raise ValueError('Review continuation lacks its committed bounded grant')
    baseline=json.loads(matches[0]['baseline'])
    for ident in (old['id'],json.loads(old['frozen'])['review_target']):
        current=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(ident,)).fetchone()
        saved=next((a for a in baseline['attempts'] if a['id']==ident),None)
        if (not saved or saved['receipt_sha256']!=hashlib.sha256(current['receipt'].encode()).hexdigest()
                or saved['frozen_sha256']!=hashlib.sha256(current['frozen'].encode()).hexdigest()):
            raise ValueError('Review continuation changed its committed attempt proof')
    original_inputs=json.loads(old['frozen'])['inputs']
    identities=lambda values:sorted((i['path'],i['artifact'],i['sha256']) for i in values)
    if identities([i for i in inputs if not i.get('previous_delivery')])!=identities([i for i in original_inputs if not i.get('previous_delivery')]):
        raise ValueError('Review continuation changed input versions')


def budgets(plan,scope,options):
    """Reserve a local evidence review within the frozen stage ceiling."""
    if scope.get('connector_companions_version')!=1 or scope.get('planner_budget_binding_version')!=2:return []
    operations={s['id']:s for s in scope.get('graph_operations',[])}
    tasks={t['id']:t for t in plan['tasks']};bindings=[]
    from orchestrator.worker_capabilities import backend_for
    from orchestrator import executors
    for task in plan['tasks']:
        producer=tasks.get(task.get('review_of'),{})
        source=operations.get(producer.get('execution',{}).get('capability'),{})
        if (source.get('saved_evidence',{}).get('kind') not in ('pages','photos')
                or any(task.get(k) for k in ('browser','computer','execution','operation_contract','user_gate'))
                or backend_for(task,plan['backend'])['type'] not in ('codex-cli',*executors.FILE_TYPES)):continue
        api=backend_for(task,plan['backend'])['type'] in executors.FILE_TYPES
        from orchestrator.evidence_workload import review_cost
        allocation=source.get('external_requests',80)
        count=len(producer.get('execution',{}).get('parameters',{}).get('queries',[])) or 20
        pages=min(6*count,max(0,allocation-count))
        characters=min(source.get('output_bytes',2000000),pages*24000)
        if producer.get('execution',{}).get('capability')=='web.sources.rendered':
            parent_bytes=sum(operations.get(tasks.get(i.get('from_task'),{}).get('execution',{}).get('capability'),{}).get('output_bytes',2000000) for i in producer['inputs'])
            rendered=producer['execution']['parameters']['max_pages']
            characters=min(source['output_bytes'],parent_bytes+rendered*24000)
            pages=(parent_bytes+23999)//24000+rendered
        cost=review_cost(characters,pages)
        reserves=[('tool_calls',cost['tool_calls']),('seconds',cost['seconds'])]
        if api and 'provider_requests' not in task['limits']:
            reserves.append(('provider_requests',cost['tool_calls']))
        for key,reserve in reserves:
            ceiling=options['limits'].get(key,options['limits']['tool_calls'])
            if api and scope.get('delivery_completion_policy_version')==1:
                from .completion_recovery import DELIVERY_POLICY
                ceiling=min(ceiling,DELIVERY_POLICY['seconds' if key=='seconds' else 'tool_calls'])
            if api and key in ('tool_calls','provider_requests'):
                ceiling=min(ceiling,executors.MAX_EXPLICIT_ROUNDS,
                            task['limits'].get('provider_requests',executors.MAX_EXPLICIT_ROUNDS),
                            options['limits'].get('provider_requests',executors.MAX_EXPLICIT_ROUNDS))
            value=min(max(reserve,task['limits'].get(key,0)),ceiling)
            if value==task['limits'].get(key):continue
            bindings.append(dict(path='$.plan.tasks.'+task['id']+'.limits.'+key,before=task['limits'].get(key),value=value,
                source='saved read-evidence review reserve within frozen stage allowance',
                reason='reserve computed evidence batches and structured report finalization',
                workload=dict(query_ceiling=count,page_ceiling=pages,character_ceiling=characters,**cost)))
            task['limits'][key]=value
    return bindings
