"""Confirmed-stop checkpoint continuation within an existing attempt grant."""
import json
import hashlib
from pathlib import Path
from . import operation_contracts as c

SCHEMA='''CREATE TABLE IF NOT EXISTS operation_record_resumes (
 attempt TEXT PRIMARY KEY, parent TEXT NOT NULL, proof TEXT NOT NULL);'''

def initialize(db):db.execute(SCHEMA)

def supports(frozen,feature):
    from .record_lifecycle import definition
    contract=frozen.get('operation_contract')
    if not contract:return False
    hooks=definition(contract)
    return bool(hooks and getattr(hooks,feature,False))

def collected_checkpoint(rt,artifact):
    """Exact collected records may be a new correction's input, never acceptance.

    Unlike an in-place retry, this requires an explicitly selected sealed export
    and a new authorized assignment. No task/latest lookup or effect replay.
    """
    from .operation_records import Store
    from .runtime import safe_file
    try:
        row=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
        if not row or row['state'] not in ('blocked','completed'):return None
        frozen=json.loads(row['frozen']);receipt=json.loads(row['receipt'] or '{}')
        if (frozen.get('assignment_id')!=row['id'] or frozen.get('review_of')
                or not supports(frozen,'amendable') or frozen.get('tools')!=['files']
                or any(frozen.get(k) for k in ('execution','browser','computer','work_tools','user_gate'))
                or receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
                or receipt.get('pending_requests')!=[] or receipt.get('exit_code')!=0
                or receipt.get('reason') is not None or receipt.get('cleanup_error')
                or receipt.get('browser',{}).get('uncertain_actions')):return None
        store=Store(frozen,rt.db)
        if artifact['path']!=store.contract['output']:return None
        reports=[json.loads(r[0]) for r in rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id",(row['id'],))]
        procedural=[r for r in reports if r.get('kind')=='procedural']
        results=[r['result'] for r in reports if r.get('kind')=='worker_self_report' and r.get('result')]
        if len(procedural)!=1 or not procedural[0].get('passed') or len(results)!=1:return None
        result=results[0]
        if result.get('assignment_id')!=row['id'] or result.get('decision') not in ('blocked','delivered'):return None
        for item in frozen['inputs']:
            if hashlib.sha256(safe_file(frozen['workspace'],item['path']).read_bytes()).hexdigest()!=item['sha256']:return None
        with store.connection(write=False) as db:revision,records=store._state(db)
        if not store.lifecycle.complete(store,records):return None
        outputs={}
        for path,raw in store.projections(records).items():
            rows=rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=? AND path=?',(row['id'],path)).fetchall()
            if len(rows)!=1:return None
            saved=rows[0];blob=Path(saved['blob'])
            data=safe_file(blob.anchor,str(blob.relative_to(blob.anchor))).read_bytes()
            if data!=raw or len(data)!=saved['bytes'] or hashlib.sha256(data).hexdigest()!=saved['sha256']:return None
            if path==artifact['path'] and saved['id']!=artifact['id']:return None
            outputs[path]=dict(artifact=saved['id'],sha256=saved['sha256'],bytes=saved['bytes'])
        params=store.contract['parameters']
        source=outputs[params['source_pack_output']]['artifact'] if params.get('source_pack_output') else next(i['artifact'] for i in frozen['inputs'] if i['path']==params['source_pack_path'])
        parent=next((i['artifact'] for i in frozen['inputs'] if i['path']==params.get('base_catalog_path')),None)
        return dict(version=1,attempt=row['id'],baseline=artifact['id'],source=source,parent=parent,record_range=params.get('record_range'),
            frozen_sha256=c.digest(frozen),receipt_sha256=c.digest(receipt),
            result_sha256=c.digest(result),unresolved_findings=result.get('findings',[]),
            revision=revision,records_sha256=c.digest(records),outputs=outputs,acceptance=False)
    except (OSError,ValueError,KeyError,TypeError):return None


def incomplete_result(frozen,receipt,result,db):
    """Prove missing local records independently of an empty model diagnosis.

    This authorizes no retry itself. The workflow's remaining recovery grant,
    exact-version baseline and independent successor review still apply.
    """
    if (not supports(frozen,'resumable') or frozen.get('review_of')
            or frozen.get('tools')!=['files'] or any(frozen.get(k) for k in ('execution','browser','computer','user_gate'))
            or receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
            or receipt.get('pending_requests')!=[] or receipt.get('exit_code')!=0 or receipt.get('reason') is not None
            or receipt.get('cleanup_error') or not isinstance(result,dict)
            or result.get('assignment_id')!=frozen['assignment_id'] or result.get('decision')!='blocked'
            or result.get('findings')!=[]):return None
    from .operation_records import Store
    try:
        store=Store(frozen,db)
        with store.connection(write=False) as connection:revision,records=store._state(connection)
        if store.lifecycle.complete(store,records):return None
        progress=store.progress()
        if progress.get('remaining',0)<=0:return None
        projections=store.projections(records)
        for path,raw in projections.items():
            from .runtime import safe_file
            if safe_file(frozen['workspace'],path).read_bytes()!=raw:return None
    except (ValueError,OSError,KeyError,TypeError):return None
    return dict(version=1,frozen_sha256=c.digest(frozen),receipt_sha256=c.digest(receipt),
        result_sha256=c.digest(result),revision=revision,committed=len(records),remaining=progress['remaining'],
        projection_sha256={path:hashlib.sha256(raw).hexdigest() for path,raw in projections.items()},acceptance=False)

def confirmed(receipt):
    reason=str(receipt.get('reason','')).removeprefix('ValueError: ')
    return (receipt.get('status')=='finished' and receipt.get('external_outcome')=='no_pending_response'
            and receipt.get('pending_requests')==[] and not receipt.get('browser',{}).get('uncertain_actions')
            and (reason=='time_limit' or 'Provider request budget exhausted' in reason or reason=='Tool budget exhausted before execution.'))

def confirmed_budget(frozen,receipt):
    if confirmed(receipt):return True
    from .executors import FILE_TYPES,request_limit
    return (frozen.get('backend',{}).get('type') in FILE_TYPES
            and receipt.get('status')=='finished' and receipt.get('external_outcome')=='no_pending_response'
            and receipt.get('pending_requests')==[] and receipt.get('reason') is None
            and receipt.get('exit_code')==0
            and (receipt.get('tool_calls',0)>=frozen['limits']['tool_calls']
                 or ((receipt.get('decision_exchanges') if frozen.get('backend',{}).get('type') in ('codex-agent','codex-code') else receipt.get('api_requests')) or 0)>=request_limit(frozen)))

def rejected_checkpoint(frozen,receipt,db,*,authorized=True):
    """A confirmed billing rejection needs a new exact human recovery grant."""
    count=receipt.get('api_requests');tools=receipt.get('tool_calls')
    if (frozen.get('backend',{}).get('type')!='gemini-agent'
            or not supports(frozen,'rejection_resumable')
            or receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
            or receipt.get('pending_requests')!=[] or receipt.get('exit_code')!=1
            or type(count)is not int or count<1 or type(tools)is not int or tools<0
            or count==1 and tools!=0 or receipt.get('cleanup_error')
            or not str(receipt.get('reason','')).startswith('ProviderError: Gemini request failed (402):')
            or receipt.get('browser',{}).get('uncertain_actions')):return None
    row=db.execute('SELECT session FROM production_attempts WHERE id=?',(frozen['assignment_id'],)).fetchone()
    try:
        control=Path(json.loads(row[0])['control']);outcome=control/f'api-{count:02d}.outcome.json'
        if outcome.is_symlink() or outcome.stat().st_size>100000 or (control/f'api-{count:02d}.response.json').exists():return None
        raw=outcome.read_bytes();journal=json.loads(raw)
        if journal.get('outcome')!='rejected' or journal.get('http_status')!=402:return None
        hashes={}
        if count>1:
            # Every earlier call must have a saved response. A terminal rejection
            # never resolves an earlier unknown submission or unaccounted tool.
            expected={f'api-{n:02d}.request.json' for n in range(1,count+1)}
            replies={f'api-{n:02d}.response.json' for n in range(1,count)}
            if {p.name for p in control.glob('api-*.request.json')}!=expected or {p.name for p in control.glob('api-*.response.json')}!=replies:return None
            tool_paths=list(control.glob('tool-*.json'))
            if len(tool_paths)!=tools:return None
            for path in [*(control/n for n in sorted(expected|replies)),*tool_paths]:
                if path.is_symlink() or path.stat().st_size>2000000:return None
                data=path.read_bytes();value=json.loads(data)
                if not isinstance(value,dict):return None
                if path.name.endswith('.request.json') and (value.get('provider')!='gemini' or value.get('model')!=frozen['backend']['model']):return None
                hashes[path.name]=hashlib.sha256(data).hexdigest()
        elif list(control.glob('api-*.response.json')):return None
    except (OSError,ValueError,KeyError,TypeError):return None
    from .operation_records import Store
    progress=Store(frozen,db).progress()
    # A first provider request may be rejected before any typed record exists.
    # The exact rejection and explicit post-billing grant provide authority;
    # fabricated progress is neither required nor inferred.
    if progress.get('committed',0)<0 or progress.get('remaining',0)<1:return None
    if authorized:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'completion_recoveries','completion_recovery_extensions'}<=tables:return None
        granted=False
        for recovery in db.execute('SELECT pipeline,step,baseline FROM completion_recoveries WHERE parent=?',(frozen['run'],)):
            baseline=json.loads(recovery['baseline'])
            if not any(g.get('kind')=='typed_provider_rejected' and g.get('attempt')==frozen['assignment_id'] for g in baseline['gaps']):continue
            digest=hashlib.sha256(recovery['baseline'].encode()).hexdigest()
            if db.execute('SELECT 1 FROM completion_recovery_extensions WHERE pipeline=? AND step=? AND baseline_sha256=?',(recovery['pipeline'],recovery['step'],digest)).fetchone():
                granted=True;break
        if not granted:return None
    proof=dict(version=1,provider_rejected=True,frozen_sha256=c.digest(frozen),
                receipt_sha256=c.digest(receipt),outcome_sha256=hashlib.sha256(raw).hexdigest(),
                revision=progress['revision'],committed=progress['committed'],remaining=progress['remaining'],acceptance=False)
    if count>1:proof['journal_sha256']=hashes
    return proof

def checkpoint(frozen,receipt,db,result=None):
    """Prove local progress after a confirmed budget yield, not a new grant.

    An early finish is recoverable only for a typed budget finding. Missing
    inputs, semantic rejection, cancellation and unknown effects remain held.
    The proof is regenerated from the immutable assignment and record journal.
    """
    rejected=rejected_checkpoint(frozen,receipt,db)
    if rejected:return rejected
    if (receipt.get('status')!='finished' or receipt.get('external_outcome')!='no_pending_response'
            or receipt.get('pending_requests')!=[] or receipt.get('browser',{}).get('uncertain_actions')):return None
    if not supports(frozen,'resumable'):return None
    if not confirmed_budget(frozen,receipt):
        if receipt.get('reason') is not None or receipt.get('exit_code')!=0:return None
        if result is None:
            row=db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' ORDER BY id DESC LIMIT 1",(frozen['assignment_id'],)).fetchone()
            result=json.loads(row[0]).get('result') if row else None
        findings=(result or {}).get('findings',[])
        if ((result or {}).get('decision')!='blocked' or not findings
                or any(f.get('category')!='execution' or str(f.get('code','')).lower() not in
                       ('budget','budget_exhausted','checkpoint_yield','request_budget_insufficient') for f in findings)):return None
    from .operation_records import Store
    progress=Store(frozen,db).progress()
    inherited=db.execute('SELECT proof FROM operation_record_resumes WHERE attempt=?',(frozen['assignment_id'],)).fetchone()
    baseline=json.loads(inherited[0])['committed'] if inherited else 0
    if progress.get('committed',0)<=baseline or progress.get('remaining',0)<=0:return None
    return dict(version=1,frozen_sha256=c.digest(frozen),revision=progress['revision'],
                committed=progress['committed'],remaining=progress['remaining'],inherited=baseline,
                receipt_sha256=c.digest(receipt),result_sha256=c.digest(result) if result else None,
                acceptance=False)

def continuation_proof(rt,task,attempt,receipt):
    proof=checkpoint(json.loads(attempt['frozen']),receipt,rt.db)
    if not proof:return False
    if not confirmed(receipt):
        from .operation_records import Store
        if Store(json.loads(attempt['frozen']),rt.db).progress().get('remaining',0)<=0:return False
    spec=rt.spec(task)
    if not supports(spec,'resumable'):return None
    count=rt.db.execute('SELECT count(*) FROM operation_records WHERE attempt=?',(attempt['id'],)).fetchone()[0]
    # Never keep spending on a worker that did not commit additional progress.
    inherited=rt.db.execute('SELECT proof FROM operation_record_resumes WHERE attempt=?',(attempt['id'],)).fetchone()
    baseline=json.loads(inherited[0])['committed'] if inherited else 0
    if count<=baseline and not proof.get('provider_rejected'):return False
    return proof

def queue(rt,attempt,receipt):
    """Compatibility entry point; the runtime owns the only queue mutation."""
    current=rt.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(attempt['id'],)).fetchone()
    if not current or json.loads(current[0] or '{}')!=receipt:return False
    return bool(rt.continue_attempt(attempt['run'],attempt['task'],attempt['id'],kind='record_checkpoint'))

def parent_for(rt,task):
    if not task['latest']:return None
    revision=rt.spec(task).get('revision',{})
    if revision.get('kind')=='local_review_session' and (revision.get('proof',{}).get('checkpoint') or {}).get('record_state'):
        return revision['previous_attempt']
    row=rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='operation_resume_queued' ORDER BY id DESC LIMIT 1",(task['latest'],)).fetchone()
    if not row:return None
    prior=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
    proof=json.loads(row[0])
    current=checkpoint(json.loads(prior['frozen']),json.loads(prior['receipt'] or '{}'),rt.db)
    if prior['state']!='blocked' or current!=proof['checkpoint'] or c.digest(json.loads(prior['receipt']))!=proof['receipt_sha256']:raise ValueError('Checkpoint continuation lacks an exact confirmed-stop receipt')
    return prior['id']

def validate_parent(rt,frozen,parent):
    from .operation_records import Store
    old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(parent,)).fetchone()
    if not old or old['state']!='blocked' or old['run']!=frozen['run'] or old['task']!=frozen['id']:raise ValueError('Foreign or uncertain checkpoint parent')
    if frozen.get('revision',{}).get('kind')=='local_review_session':
        from task_relay.local_review import session_proof
        task=dict(rt.task(old['run'],old['task']),status='blocked',assignment=old['assignment'],latest=old['id'])
        proof=session_proof(rt,task,old)
        if not proof or proof!=frozen['revision']['proof'] or not proof['checkpoint'].get('record_state'):
            raise ValueError('Foreign or uncertain review checkpoint parent')
    elif not checkpoint(json.loads(old['frozen']),json.loads(old['receipt'] or '{}'),rt.db):
        raise ValueError('Foreign or uncertain checkpoint parent')
    prior=json.loads(old['frozen'])
    for key in ('operation_contract','backend','criteria','limits','tools','review_target'):
        if prior.get(key)!=frozen.get(key):raise ValueError('Checkpoint continuation changed '+key)
    identity=lambda f:sorted((i['path'],i['artifact'],i['sha256']) for i in f['inputs'])
    if identity(prior)!=identity(frozen):raise ValueError('Checkpoint continuation changed input versions')
    return prior


def seed(rt,frozen,parent):
    from .operation_records import Store
    prior=validate_parent(rt,frozen,parent)
    old=rt.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(parent,)).fetchone()
    old_store=Store(prior,rt.db);new_store=Store(frozen,rt.db)
    revision,records=old_store._state(rt.db)
    context=new_store.context()
    for record in records:new_store.family['validate'](record,new_store.contract['parameters'],context)
    new_store.document(records)
    rt.db.execute('INSERT INTO operation_record_sets VALUES (?,?,?)',(frozen['assignment_id'],new_store.binding,revision+1))
    for n,r in enumerate(records):
        key=new_store.family['validate'](r,new_store.contract['parameters'])
        rt.db.execute('INSERT INTO operation_records VALUES (?,?,?,?)',(frozen['assignment_id'],key,n,c.encoded(r)))
    proof=dict(parent=parent,parent_frozen_sha256=c.digest(prior),parent_receipt_sha256=c.digest(json.loads(old['receipt'])),
               records_sha256=c.digest(records),committed=len(records),revision=revision+1,user_accepted=False)
    rt.db.execute('INSERT INTO operation_record_resumes VALUES (?,?,?)',(frozen['assignment_id'],parent,c.encoded(proof)))
    rt.event(frozen['run'],frozen['id'],frozen['assignment_id'],'operation_records_resumed',proof)
