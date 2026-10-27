"""Read-only recovery evidence and allocation checks for Runtime.continue_attempt.

Adapters prove progress. The existing runtime alone commits the transition;
this module creates no queue, assignment, grant, worker or acceptance.
"""
import copy
import hashlib
import json
from . import contracts as c, executors
from .operation_session import outcome

from .continuation_adapters import definition, REGISTRY
ADAPTER_GAPS={kind:adapter.gaps for kind,adapter in REGISTRY.items()}


def allocation(rt, task, attempt, reference, kind):
    from task_relay.completion_recovery import DELIVERY_POLICY
    if not isinstance(reference,dict) or set(reference)!={'pipeline','step','cycle','baseline_sha256'}:
        raise ValueError('Continuation needs an exact committed allocation reference')
    row=rt.db.execute('SELECT r.baseline,r.request_id,g.policy FROM completion_recoveries r JOIN completion_recovery_grants g ON g.pipeline=r.pipeline WHERE r.pipeline=? AND r.step=? AND r.cycle=? AND r.parent=?',
        (reference['pipeline'],reference['step'],reference['cycle'],task['run'])).fetchone()
    if not row:raise ValueError('Missing committed continuation allocation')
    policy=json.loads(row['policy']);raw=row['baseline']
    if policy!=DELIVERY_POLICY:
        raise ValueError('Unsupported continuation grant')
    if c.digest(json.loads(raw))!=reference['baseline_sha256']:
        # A verified zero-dispatch invocation can spend a remaining worker slot
        # in its already committed cycle. Its own baseline is immutable too.
        extra=rt.db.execute('SELECT baseline FROM local_review_invocations WHERE pipeline=? AND step=? AND cycle=? AND previous_attempt=?',
            (reference['pipeline'],reference['step'],reference['cycle'],attempt['id'])).fetchone()
        if kind!='local_review_session' or not extra or c.digest(json.loads(extra[0]))!=reference['baseline_sha256']:
            raise ValueError('Continuation allocation baseline changed')
        raw=extra[0]
    baseline=json.loads(raw)
    saved=next((a for a in baseline['attempts'] if a['id']==attempt['id']),None)
    if (baseline['run']!=task['run'] or not saved or
            any(saved[k+'_sha256']!=hashlib.sha256(attempt[k].encode()).hexdigest() for k in ('frozen','receipt'))):
        raise ValueError('Continuation allocation attempt changed')
    gaps=[g for g in baseline['gaps'] if g.get('task')==task['id'] and g.get('attempt',attempt['id'])==attempt['id']]
    if len(gaps)!=1:raise ValueError('Continuation allocation does not own this stopped task')
    gap=gaps[0]
    if kind=='local_review_session' and gap['kind'] in ('split_budget','confirmed_review_generation'):
        # Historical failed replans already have a spent cycle. Reclaim only
        # its unused workers, retaining every planner reply and unchanged task.
        plan=rt.db.execute('SELECT id,status,calls FROM production_plans WHERE request_id=?',(row['request_id'],)).fetchone()
        calls=list(rt.db.execute('SELECT error FROM production_plan_calls WHERE plan_id=?',(plan['id'],))) if plan else []
        current=[dict(task) if t['id']==task['id'] else dict(t) for t in rt.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY id',(task['run'],))]
        if not plan or plan['status']!='blocked' or not calls or len(calls)!=plan['calls'] or any(not r['error'] for r in calls) or current!=baseline['tasks']:
            raise ValueError('Historical continuation allocation is not reclaimable')
        from task_relay.local_review import proof
        gap=proof(rt,task,attempt)
        if not gap:raise ValueError('Historical continuation proof unavailable')
    permitted=definition(kind).gaps
    if gap['kind'] not in permitted:raise ValueError('Continuation allocation has a different recovery kind')
    return gap


def proposal(rt, task, attempt, kind, reference=None):
    """Return checked evidence and an unchanged-scope successor; no writes."""
    adapter=definition(kind)
    checked=adapter.prove(rt,task,attempt)
    if not checked:return None
    proof,value=checked
    if adapter.allocation_required and reference is None:raise ValueError('Continuation needs its committed allocation')
    gap=allocation(rt,task,attempt,reference,kind) if reference is not None else None
    successor,maximum=adapter.build(rt,task,attempt,proof,gap,reference,kind)
    # Model-authored plans retain their 1–3 limit. Only a saved allocation can
    # extend the monotonic lifetime counter; per-invocation limits stay exact.
    successor['max_attempts']=min(maximum,3)
    successor=c.assignment(successor);successor['max_attempts']=maximum
    if reference is not None:
        from task_relay.completion_recovery import DELIVERY_POLICY
        if (successor['limits']['seconds']>DELIVERY_POLICY['seconds']
                or successor['limits']['tool_calls']>DELIVERY_POLICY['tool_calls']
                or executors.request_limit(successor)>DELIVERY_POLICY['tool_calls']):
            raise ValueError('Continuation exceeds its committed allocation')
    return dict(spec=successor,proof=proof,outcome=value,allocation=copy.deepcopy(reference),adapter=adapter.manifest(),
        remaining_attempts=maximum-task['attempts'])


def validate_dispatch(rt, task):
    """Reprove committed intent immediately before creating a worker attempt."""
    if not task['latest']:return
    row=rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='continuation_committed' ORDER BY id DESC LIMIT 1",(task['latest'],)).fetchone()
    if not row:return  # Historical queues retain their adapter validation.
    saved=json.loads(row[0])
    if task['assignment']!=saved['assignment']:raise ValueError('Continuation assignment changed after commit')
    attempt=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(saved['parent'],)).fetchone()
    if not attempt or attempt['state']!='blocked' or c.digest(json.loads(attempt['receipt'] or '{}'))!=saved['receipt_sha256']:
        raise ValueError('Continuation parent receipt changed after commit')
    if saved.get('adapter') is not None and saved['adapter']!=definition(saved['kind']).manifest():
        raise ValueError('Continuation adapter changed after commit')
    original=dict(task,status='blocked',assignment=saved['previous_assignment'])
    prepared=proposal(rt,original,attempt,saved['kind'],saved['allocation'])
    if (not prepared or prepared['proof']!=saved['proof'] or prepared['outcome']!=saved['outcome']
            or prepared['spec']!=rt.spec(task) or prepared['remaining_attempts']<=0):
        raise ValueError('Continuation evidence or scope changed after commit')
