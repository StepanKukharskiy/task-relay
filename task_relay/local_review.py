"""One confirmed local-review continuation path over immutable operation sessions.

Historical journals are projected read-only. New outcomes are code-owned; model
wording never selects a transition. Original attempts and grants remain binding.
"""
import copy,hashlib,json
from pathlib import Path
from orchestrator import contracts as c,executors
from orchestrator.operation_session import identity,outcome,supported,transition,record_state


def file_digest(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('Linked review receipt is not immutable')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def journals(rt,attempt,frozen,receipt):
    folder=rt.root/'workers'/attempt['id'];hashes={};requests=sorted(folder.glob('api-*.request.json'))
    if not requests or receipt.get('api_requests')!=len(requests):raise ValueError('Unaccounted review requests')
    for path in requests:
        req=json.loads(path.read_text());res=path.with_name(path.name.replace('.request.json','.response.json'))
        if req.get('provider')!=executors.provider_for(frozen['backend']) or req.get('model')!=frozen['backend']['model']:
            raise ValueError('Review provider changed')
        # An existing actual response is required. Missing/unknown calls never
        # become retry permission, even when a checkpoint happens to exist.
        json.loads(res.read_text())
        for p in (path,res):hashes[p.name]=file_digest(p)
    tools=sorted(folder.glob('tool-*.json'))
    if len(tools)!=receipt.get('tool_calls'):raise ValueError('Unaccounted review tool calls')
    for path in tools:hashes[path.name]=file_digest(path)
    return folder,hashes,tools


def historical_checkpoint(folder,frozen,hashes,tools):
    """Observed intervals derive from actual supplied text/results, never claims."""
    checkpoint=dict(version=1,identity=identity(frozen),observed={},notes=[],checks={},accepted=False)
    inputs={i['path']:i for i in frozen['inputs']}
    def span(path,start,end,sha):
        if path not in inputs or inputs[path]['sha256']!=sha:raise ValueError('Historical input binding changed')
        if type(start)is not int or type(end)is not int or start<0 or end<start:raise ValueError('Invalid observed span')
        checkpoint['observed'].setdefault(path,[]).append([start,end])
    pack=folder/'source-pack.json'
    if pack.exists():
        hashes[pack.name]=file_digest(pack)
        for row in json.loads(pack.read_text()).get('files',[]):span(row['path'],0,len(row['text']),row['sha256'])
    for path in tools:
        row=json.loads(path.read_text());value=row.get('result',{});args=row.get('arguments',{})
        if value.get('error'):continue
        if row['name']=='evidence_next':
            for part in value.get('parts',[]):span(part['path'],part['offset'],part['end'],part['sha256'])
            if args.get('notes'):checkpoint['notes'].append(dict(notes=args['notes'],origin=path.name))
        elif row['name']=='file_read' and args.get('path') in inputs:
            if isinstance(value.get('text'),str):
                start=value.get('offset',args.get('offset',0))
                span(args['path'],start,start+len(value['text']),inputs[args['path']]['sha256'])
    checks=folder/'report-checks.json'
    if checks.exists():
        from orchestrator.report_fragments import Store
        store=Store(frozen,folder);checkpoint['checks']=store.checks;hashes[checks.name]=file_digest(checks)
    return checkpoint


def session_proof(rt,task,attempt):
    spec=rt.spec(task);frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if (task['status']!='blocked' or task['latest']!=attempt['id'] or task['assignment']!=attempt['assignment']
            or attempt['state']!='blocked'
            or not supported(frozen) or any(spec.get(k) for k in ('user_gate','browser','computer','execution'))
            or any(spec.get(k)!=frozen.get(k) for k in ('criteria','tools','limits','operation_contract'))
            or receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
            or receipt.get('pending_requests')!=[] or receipt.get('cleanup_error')
            or receipt.get('token')!=attempt['id']):return None
    target=rt.task(task['run'],spec['review_of'])
    parent=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    if target['status']!='awaiting_review' or target['latest']!=frozen.get('review_target') or not parent or parent['state']!='completed':return None
    done=json.loads(parent['receipt'] or '{}')
    if done.get('status')!='finished' or done.get('exit_code') or done.get('pending_requests') or done.get('cleanup_error'):return None
    # A completed semantic verdict requires correction, not another opinion.
    if rt.db.execute("SELECT 1 FROM production_events WHERE attempt=? AND kind='checks_recorded'",(attempt['id'],)).fetchone():return None
    try:
        folder,hashes,tools=journals(rt,attempt,frozen,receipt)
        current=folder/'execution-outcome.json'
        if current.exists():
            hashes[current.name]=file_digest(current);value=json.loads(current.read_text())
            cp=folder/'review-session.json'
            if value.get('checkpoint')!={'path':str(cp),'sha256':file_digest(cp)}:return None
            hashes[cp.name]=file_digest(cp);checkpoint=json.loads(cp.read_text())
        else:
            # Compatibility projection: a fully received local invocation ended
            # without a valid report. Require a code-recorded local tool error or
            # a confirmed discarded generation receipt, not an arbitrary exit.
            last=json.loads(tools[-1].read_text()) if tools else {}
            failures=list(folder.glob('api-*.recovery.json'))
            discarded=False
            for path in failures:
                row=json.loads(path.read_text());hashes[path.name]=file_digest(path)
                if row.get('continued') is False and row.get('executed_calls')==0 and row.get('kind') in {'generation_output_limit','malformed_function_call'}:discarded=True
            if not receipt.get('exit_code') or not (last.get('result',{}).get('error') or discarded):return None
            value=outcome('review','yielded','legacy_confirmed_local_invocation')
            checkpoint=historical_checkpoint(folder,frozen,hashes,tools)
        if transition(value,remaining_attempts=max(1,spec['max_attempts']-task['attempts']),confirmed=True,unchanged=True)!='continue_local':return None
        if checkpoint.get('identity')!=identity(frozen) or checkpoint.get('accepted') is not False:return None
        records=record_state(frozen,rt.db)
        if records:
            # Partial collections retain their existing record continuation.
            # A complete collection still owes a validated final review.
            if not records['complete']:return None
            if checkpoint.get('record_state',records)!=records:return None
            checkpoint['record_state']=records
            value={**value,'phase':'finalize'}
        for item in frozen['inputs']:
            artifact=rt.artifact(item['artifact'])
            if artifact['sha256']!=item['sha256'] or file_digest(artifact['blob'])!=item['sha256']:return None
            if item.get('from_task')==target['id'] and artifact['attempt']!=target['latest']:return None
    except (OSError,ValueError,KeyError,TypeError):return None
    for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
        if other['status'] in ('running','launching','cancelling','uncertain') or other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
    return dict(kind='local_review_session',task=task['id'],attempt=attempt['id'],candidate=target['latest'],
        outcome=value,checkpoint=checkpoint,journal_sha256=hashes,
        requires_cycle_attempt=task['attempts']>=spec['max_attempts'],
        instruction='Continue the same independent review from its exact-version provisional checkpoint. Amend judgments after any further inspection, then submit the final validated report. Preserve all criteria, input versions, provider and limits. Do not repeat source collection or infer acceptance.')


def zero_dispatch_proof(rt,task,attempt):
    """Read-only adapter for a historical projection-capacity preflight.

    Reproduce both old and registered current obligations from exact inputs;
    exception text never decides eligibility and no semantic verdict is reused.
    """
    import math
    from orchestrator.review_inputs import interface
    from orchestrator.record_lifecycle import definition
    spec=rt.spec(task);frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if (task['status']!='blocked' or task['latest']!=attempt['id'] or task['assignment']!=attempt['assignment']
            or attempt['state']!='blocked' or not frozen.get('review_of') or not frozen.get('operation_contract')
            or any(spec.get(k) or frozen.get(k) for k in ('user_gate','browser','computer','execution'))
            or frozen.get('backend',{}).get('type') not in executors.FILE_TYPES
            or any(spec.get(k)!=frozen.get(k) for k in ('operation_contract','criteria','tools','limits'))
            or receipt.get('status')!='finished' or not receipt.get('exit_code') or receipt.get('token')!=attempt['id']
            or receipt.get('external_outcome')!='no_pending_response' or receipt.get('pending_requests')!=[]
            or receipt.get('api_requests')!=0 or receipt.get('tool_calls')!=0 or receipt.get('cleanup_error')):return None
    hooks=definition(frozen['operation_contract'])
    if not hooks or not hooks.review_units:return None
    if rt.db.execute('SELECT 1 FROM operation_records WHERE attempt=?',(attempt['id'],)).fetchone():return None
    if rt.db.execute("SELECT 1 FROM production_events WHERE attempt=? AND kind='checks_recorded'",(attempt['id'],)).fetchone():return None
    target=rt.task(task['run'],spec['review_of']);parent=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    if target['status']!='awaiting_review' or target['latest']!=frozen.get('review_target') or not parent or parent['state']!='completed':return None
    done=json.loads(parent['receipt'] or '{}')
    if done.get('status')!='finished' or done.get('exit_code') or done.get('pending_requests') or done.get('cleanup_error'):return None
    folder=rt.root/'workers'/attempt['id']
    if list(folder.glob('api-*.request.json')) or list(folder.glob('tool-*.json')):return None
    try:
        inputs={i['path']:i for i in frozen['inputs']};data={}
        for path,item in inputs.items():
            artifact=rt.artifact(item['artifact'])
            if artifact['sha256']!=item['sha256'] or file_digest(artifact['blob'])!=item['sha256']:return None
            if item.get('from_task')==target['id'] and artifact['attempt']!=target['latest']:return None
            data[path]=Path(artifact['blob']).read_bytes()
        current=interface(frozen,lambda p:data[p]);available=min(spec['limits']['tool_calls'],executors.request_limit(spec))
        if not current or current['required_requests']>available:return None
        pack_path=folder/'source-pack.json'
        if not pack_path.exists():
            # A confirmed zero-effect launch may resume only after the worker
            # implementation actually changes. It cannot loop on the same build.
            import orchestrator.gemini_worker as worker
            prior=frozen.get('runtime_sources',{}).get('gemini_worker.py')
            current_worker=file_digest(worker.__file__)
            if not prior or prior==current_worker:return None
            workspace=Path(frozen['workspace'])
            if (workspace/'.relay/result.json').exists():return None
            # Registered workers may export deterministic empty projections
            # during initialization, before the first provider request.
            from orchestrator.operation_records import Store
            empty=Store(frozen,rt.db).projections([]);projection_hashes={}
            for output in frozen['outputs']:
                path=workspace/output['path']
                if path.exists():
                    if path.is_symlink() or output['path'] not in empty or path.read_bytes()!=empty[output['path']]:return None
                    projection_hashes['workspace/'+output['path']]=file_digest(path)
            for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
                if other['status'] in ('running','launching','cancelling','uncertain') or other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
            return dict(kind='local_review_session',task=task['id'],attempt=attempt['id'],candidate=target['latest'],
                outcome=outcome('observe','yielded','confirmed_zero_dispatch_runtime_change'),checkpoint=None,
                journal_sha256=projection_hashes,requires_cycle_attempt=task['attempts']>=spec['max_attempts'],
                implementation=dict(before=prior,after=current_worker),projection=dict(after=current),
                instruction='Resume the unchanged independent review after a confirmed zero-effect launch and verified worker implementation change. Preserve the exact candidate, criteria, provider, limits and all earlier receipts. No acceptance or source collection is replayed.')
        pack=json.loads(pack_path.read_text());old_paths={p for p,i in inputs.items() if i.get('from_task')==frozen['review_of']}
        if {i['path'] for i in pack['files']}!=old_paths:return None
        reads=0
        for item in pack['files']:
            raw=data[item['path']];text=raw.decode('utf-8');prefix=item['text']
            if item['sha256']!=inputs[item['path']]['sha256'] or item['bytes']!=len(raw) or not text.startswith(prefix):return None
            if item['next_offset']!=(len(prefix) if len(prefix)<len(text) else None):return None
            reads+=math.ceil((len(text)-len(prefix))/24000)
        old_required=reads+current['submission_requests']+1
        if old_required<=available or not set(current['indexed_evidence'])&old_paths:return None
    except (ValueError,OSError,KeyError,TypeError):return None
    for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
        if other['status'] in ('running','launching','cancelling','uncertain') or other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
    return dict(kind='local_review_session',task=task['id'],attempt=attempt['id'],candidate=target['latest'],
        outcome=outcome('observe','yielded','review_input_capacity'),checkpoint=None,
        journal_sha256={pack_path.name:file_digest(pack_path)},requires_cycle_attempt=task['attempts']>=spec['max_attempts'],
        projection=dict(before_requests=old_required,after=current),
        instruction='Continue independent review of the exact candidate projections and every registered item using its source-bound evidence. The composed evidence container retains its indexed source role. Inspect complete authored projections; retain original criteria, versions, provider and limits. No source collection or prior acceptance is replayed.')


def proof(rt,task,attempt):
    """Normalize legacy receipt formats; one owner queues all local reviews."""
    frozen=json.loads(attempt['frozen'])
    if supported(frozen):
        session=session_proof(rt,task,attempt)
        if session:return session
    # Historical typed/code workers cannot inherit text observation checkpoints.
    # Their strict read-only adapters prove a fresh local invocation is allowed.
    from .review_budget_recovery import generation_proof,input_proof
    preflight=zero_dispatch_proof(rt,task,attempt)
    if preflight:return preflight
    legacy=generation_proof(rt,task,attempt) or input_proof(rt,task,attempt)
    if not legacy:return None
    value=outcome('review','yielded','legacy_confirmed_local_invocation')
    if transition(value,remaining_attempts=rt.spec(task)['max_attempts']-task['attempts'],confirmed=True,unchanged=True)!='continue_local':return None
    return dict(kind='local_review_session',task=task['id'],attempt=attempt['id'],candidate=legacy['candidate'],
        outcome=value,checkpoint=None,legacy=legacy,journal_sha256=legacy['journal_sha256'],instruction=legacy['instruction'])


def validate_dispatch(rt,task,spec,backend,inputs):
    revision=spec['revision'];old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(revision['previous_attempt'],)).fetchone()
    if not old or old['run']!=task['run'] or old['task']!=task['id'] or task['latest']!=old['id']:raise ValueError('Review session parent changed')
    original=dict(task,status='blocked',assignment=old['assignment']);current=proof(rt,original,old)
    if not current or current!=revision['proof']:raise ValueError('Review session continuation proof changed')
    expected=copy.deepcopy(rt.spec(original));expected['revision']=revision
    if current.get('requires_cycle_attempt'):expected['max_attempts']=task['attempts']+1
    frozen=json.loads(old['frozen'])
    if {k:v for k,v in spec.items() if k!='evidence_context'}!={k:v for k,v in expected.items() if k!='evidence_context'} or backend!=frozen['backend']:raise ValueError('Review session scope changed')
    keys=lambda rows:sorted((i['path'],i['artifact'],i['sha256']) for i in rows)
    if keys(inputs)!=keys(frozen['inputs']):raise ValueError('Review session input versions changed')
    if revision.get('source')=='original_assignment_attempts':
        if current.get('requires_cycle_attempt') or task['attempts']>=spec['max_attempts']:
            raise ValueError('Original review attempts exhausted')
        row=rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='continuation_committed' ORDER BY id DESC LIMIT 1",(old['id'],)).fetchone()
        saved=json.loads(row[0]) if row else {}
        if (saved.get('allocation') is not None or saved.get('assignment')!=task['assignment']
                or saved.get('proof')!=current or saved.get('invocation_limits_before')!=spec['limits']
                or saved.get('task_attempt_limit_before')!=spec['max_attempts']):
            raise ValueError('Missing original-attempt continuation commitment')
        return dict(data=current['checkpoint'],sha256=c.digest(current['checkpoint'])) if current['checkpoint'] is not None else None
    digest=revision['baseline_sha256']
    rows=list(rt.db.execute('SELECT r.baseline,g.policy FROM completion_recoveries r JOIN completion_recovery_grants g ON g.pipeline=r.pipeline WHERE r.parent=?',(task['run'],)))
    rows+=list(rt.db.execute('SELECT r.baseline,g.policy FROM local_review_invocations r JOIN completion_recovery_grants g ON g.pipeline=r.pipeline WHERE r.parent=?',(task['run'],)))
    matches=[r for r in rows if hashlib.sha256(r['baseline'].encode()).hexdigest()==digest]
    if not matches or len({r['baseline'] for r in matches})!=1:raise ValueError('Missing committed review session baseline')
    allocation(rt,original,current,json.loads(matches[0]['policy']))
    baseline=json.loads(matches[0]['baseline'])
    for ident in (old['id'],frozen['review_target']):
        saved=next((a for a in baseline['attempts'] if a['id']==ident),None)
        actual=rt.db.execute('SELECT frozen,receipt FROM production_attempts WHERE id=?',(ident,)).fetchone()
        if not saved or not actual or any(saved[key+'_sha256']!=hashlib.sha256(actual[key].encode()).hexdigest() for key in ('frozen','receipt')):
            raise ValueError('Committed review session receipt changed')
    events=rt.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='local_review_session_queued' AND json_extract(detail,'$.parent')=?",(task['run'],)).fetchall()
    if not any((v:=json.loads(r[0])).get('baseline_sha256')==digest and v.get('proof')==current and v.get('assignment_sha256')==c.digest(rt.spec(task)) for r in events):raise ValueError('Missing committed review session transition')
    return dict(data=current['checkpoint'],sha256=c.digest(current['checkpoint'])) if current['checkpoint'] is not None else None


def allocation(rt,task,gap,policy):
    from .completion_recovery import DELIVERY_POLICY
    if policy!=DELIVERY_POLICY:raise ValueError('Local session lacks a supported delivery recovery grant')
    spec=rt.spec(task)
    if (spec['limits']['seconds']>policy['seconds'] or spec['limits']['tool_calls']>policy['tool_calls']
            or executors.request_limit(spec)>policy['tool_calls']):raise ValueError('Local session exceeds its recovery allocation')
    if gap.get('requires_cycle_attempt') and task['attempts']!=spec['max_attempts']:
        raise ValueError('Local review attempt accounting changed')


def queue(state,rt,p,s,baseline,gap,cycle):
    from .continuation_owner import queue as continue_owned
    return continue_owned(state,rt,p,s,baseline,cycle,'local_review_session','existing completion allocation',proof_gaps=[gap])


def resume_zero_dispatch(state,rt,p,s,baseline):
    """Spend a remaining worker slot in the existing local review cycle.

    The immutable original cycle and launch receipts remain. This does not create
    another research cycle, reset an attempt, or add any provider allowance.
    """
    if not baseline or len(baseline['gaps'])!=1:return False
    gap=baseline['gaps'][0]
    if gap.get('kind')!='local_review_session' or gap.get('outcome',{}).get('code')!='confirmed_zero_dispatch_runtime_change':return False
    spec=rt.spec(rt.task(baseline['run'],gap['task']));revision=spec.get('revision',{})
    if revision.get('kind')!='local_review_session':return False
    receipt=state.db.execute('SELECT * FROM completion_recoveries WHERE pipeline=? AND step=? AND parent=? ORDER BY cycle DESC LIMIT 1',(p['id'],s['id'],baseline['run'])).fetchone()
    if not receipt or revision.get('source')!='completion_recovery:'+p['id']+':'+str(receipt['cycle']):return False
    first=json.loads(receipt['baseline'])
    if len(first['gaps'])!=1 or first['gaps'][0]['kind']!='local_review_session':return False
    events=[json.loads(r[0]) for r in state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND kind='local_review_session_queued'",(p['id'],))]
    used=[v for v in events if v.get('parent')==baseline['run'] and v.get('cycle')==receipt['cycle']]
    grant=state.db.execute('SELECT policy FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone()
    from .completion_recovery import DELIVERY_POLICY
    if not grant or json.loads(grant[0])!=DELIVERY_POLICY or not used or len(used)>=DELIVERY_POLICY['tasks_per_cycle']:return False
    if used[-1]['assignment_sha256']!=c.digest(spec):return False
    state.db.execute('INSERT INTO local_review_invocations VALUES (?,?,?,?,?,?)',(p['id'],s['id'],baseline['run'],receipt['cycle'],gap['attempt'],c.encoded(baseline)))
    queue(state,rt,p,s,baseline,gap,receipt['cycle'])
    return True
