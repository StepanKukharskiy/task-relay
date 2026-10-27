"""Atomic stage allocation for the existing Runtime continuation controller."""
import hashlib,json
from orchestrator import contracts as c
from orchestrator.continuation_adapters import REGISTRY,definition


def select(baseline,stage,policy):
    gaps=baseline['gaps']
    if not gaps or len(gaps)>policy['tasks_per_cycle']:return None
    matches=[(kind,a) for kind,a in REGISTRY.items() if all(g['kind'] in a.gaps for g in gaps)
             and (len(gaps)==1 or a.grouped) and (not a.requires_ungated or stage.get('gate')=='none')]
    if len(matches)>1:raise ValueError('Ambiguous registered continuation policy')
    return matches[0][0] if matches else None


def resume_original(state,rt,p,s,baseline):
    """Use original capacity for compatible registered continuations, atomically.

    The registry declares whether an adapter needs a separate allocation. The
    controller owns attempt accounting; adapters still reprove exact effects and
    checkpoint identity at commit and dispatch. No tool/domain name selects it.
    """
    from . import pipelines,production_control as pc
    if not state.db.in_transaction:raise ValueError('Continuation allocation requires an owner transaction')
    if not baseline or not baseline['gaps']:return False
    eligible=[]
    for gap in baseline['gaps']:
        matches=[(kind,a) for kind,a in REGISTRY.items() if gap['kind'] in a.gaps]
        if len(matches)>1:raise ValueError('Ambiguous registered continuation policy')
        if not matches:return False
        kind,adapter=matches[0];task=rt.task(baseline['run'],gap['task'])
        if adapter.allocation_required or task['attempts']>=rt.spec(task)['max_attempts']:return False
        eligible.append((gap,kind,rt.spec(task)['max_attempts']))
    for gap,kind,limit in eligible:
        committed=rt.continue_attempt(baseline['run'],gap['task'],gap['attempt'],kind=kind)
        if not committed:raise ValueError('Original-capacity continuation no longer eligible')
        pipelines.event(state,p['id'],s['id'],'original_capacity_continued',dict(parent=baseline['run'],task=gap['task'],attempt=gap['attempt'],
            adapter=kind,original_attempt_limit=limit,recovery_cycles_added=0,acceptance=False))
    state.put('production-enabled:'+baseline['run'],pc.runtime_digest(rt,baseline['run']))
    state.db.execute("UPDATE relay_pipeline_steps SET status='running',error=NULL WHERE pipeline=? AND id=?",(p['id'],s['id']))
    return True


def resume_finalization(state,rt,p,s,baseline):
    """Use an unspent worker in the current cycle after confirmed review progress.

    This is the same local review adapter and queue, not a new recovery grant.
    No new records/checks means no additional invocation via this path.
    """
    from .completion_recovery import DELIVERY_POLICY
    if not baseline or len(baseline['gaps'])!=1:return False
    gap=baseline['gaps'][0]
    if gap.get('kind')!='local_review_session' or gap.get('outcome',{}).get('phase')!='finalize':return False
    task=rt.task(baseline['run'],gap['task']);spec=rt.spec(task)
    parent=spec.get('revision',{}).get('previous_attempt')
    if not parent:return False
    row=state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='continuation_committed' ORDER BY id DESC LIMIT 1",(parent,)).fetchone()
    if not row:return False
    committed=json.loads(row[0]);ref=committed.get('allocation') or {}
    if (committed['assignment']!=task['assignment'] or ref.get('pipeline')!=p['id'] or ref.get('step')!=s['id']
            or committed.get('kind') not in ('record_checkpoint','local_review_session')):return False
    latest=state.db.execute('SELECT cycle FROM completion_recoveries WHERE pipeline=? AND step=? ORDER BY cycle DESC LIMIT 1',(p['id'],s['id'])).fetchone()
    grant=state.db.execute('SELECT policy,request FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone()
    if not latest or latest['cycle']!=ref.get('cycle') or not grant or json.loads(grant['policy'])!=DELIVERY_POLICY:return False
    prior=committed['proof'];old_checkpoint=prior.get('checkpoint') or {}
    current=gap['checkpoint'];old_records=old_checkpoint.get('record_state') or {}
    advanced=(current['record_state']['committed']>old_records.get('committed',prior.get('committed',0))
              or any(old_checkpoint.get('checks',{}).get(k)!=v for k,v in current.get('checks',{}).items()))
    if not advanced:return False
    events=[json.loads(r[0]) for r in state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND step=? AND kind='completion_continuations_queued'",(p['id'],s['id']))]
    used=sum(len(v['tasks']) for v in events if v.get('parent')==baseline['run'] and v.get('cycle')==ref['cycle'])
    if not 0<used<DELIVERY_POLICY['tasks_per_cycle']:return False
    if state.db.execute('SELECT 1 FROM local_review_invocations WHERE previous_attempt=?',(gap['attempt'],)).fetchone():return False
    state.db.execute('INSERT INTO local_review_invocations VALUES(?,?,?,?,?,?)',(p['id'],s['id'],baseline['run'],ref['cycle'],gap['attempt'],c.encoded(baseline)))
    return queue(state,rt,p,s,baseline,ref['cycle'],'local_review_session',grant['request'])


def queue(state,rt,p,s,baseline,cycle,kind,authority,*,allocate=False,proof_gaps=None):
    from . import pipelines,production_control as pc
    if not state.db.in_transaction:raise ValueError('Continuation allocation requires an owner transaction')
    adapter=definition(kind);digest=c.digest(baseline);run=baseline['run']
    authority=adapter.authorize(state,p,s,baseline,authority)
    if authority is None:
        from .workflow_state import decision
        return decision(state,p,s,'continuation_authorization_missing','This continuation needs authorization bound to its exact stopped baseline.','review_authorization')
    if allocate:
        ident=-int(hashlib.sha256((p['id']+':'+s['id']+':recovery:'+str(cycle)).encode()).hexdigest()[:15],16)-1
        state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',(p['id'],s['id'],run,cycle,ident,c.encoded(baseline)))
    gaps=baseline['gaps'] if proof_gaps is None else proof_gaps
    if len(gaps)!=len(baseline['gaps']) or [g['task'] for g in gaps]!=[g['task'] for g in baseline['gaps']]:raise ValueError('Continuation proof changed baseline ownership')
    for gap in gaps:
        task=rt.task(run,gap['task'])
        committed=rt.continue_attempt(run,gap['task'],gap['attempt'],kind=kind,
            allocation=dict(pipeline=p['id'],step=s['id'],cycle=cycle,baseline_sha256=digest))
        if not committed:raise ValueError('Registered continuation no longer eligible')
        context=dict(run=run,cycle=cycle,digest=digest,authority=authority,task=task,gap=gap,committed=committed,spec=rt.spec(rt.task(run,gap['task'])))
        events,stage_events=adapter.project(context)
        for name,data in events:rt.event(run,gap['task'],gap['attempt'],name,data)
        for name,data in stage_events:pipelines.event(state,p['id'],s['id'],name,data)
    state.put('production-enabled:'+run,pc.runtime_digest(rt,run))
    state.db.execute("UPDATE relay_pipeline_steps SET status='running',error=NULL WHERE pipeline=? AND id=?",(p['id'],s['id']))
    pipelines.event(state,p['id'],s['id'],'completion_continuations_queued',dict(parent=run,cycle=cycle,adapter=kind,tasks=[g['task'] for g in baseline['gaps']],baseline_sha256=digest,attempts_reset=False,acceptance=False))
    if adapter.group_event:
        pipelines.event(state,p['id'],s['id'],adapter.group_event,dict(parent=run,cycle=cycle,tasks=[g['task'] for g in baseline['gaps']],baseline_sha256=digest,attempts_reset=False,provider_repeated=False,settings_changed=False))
    return True
