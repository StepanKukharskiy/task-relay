"""Durable lifecycle projection of the canonical pipeline stage owner.

Only pipelines own bindings and authorization. This record makes that owner's
phase, evidence and next action explicit across every effect adapter. It never
creates a second dispatch queue or treats an unknown effect as retry permission.
"""
import json
import time


class Hold(ValueError):
    def __init__(self,code,reason,next_action='inspect_recovery',machine_message=None):
        super().__init__(machine_message or reason)
        self.code,self.reason,self.next_action=code,reason,next_action


def failure(state,p,s,exc):
    return decision(state,p,s,getattr(exc,'code','transition_failed'),
        getattr(exc,'reason',str(exc)),getattr(exc,'next_action','inspect_recovery'))


def denied(state,p,s,message):
    row=state.db.execute('SELECT * FROM relay_recovery_decisions WHERE pipeline=? AND step=?',(p['id'],s['id'])).fetchone()
    if row and row['binding']==encoded(binding(s)):
        return Hold(row['code'],row['reason'],row['next_action'],message)
    return Hold('proof_unavailable',message,'inspect_receipt')


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'))


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_stage_state(
        pipeline TEXT NOT NULL, step TEXT NOT NULL, revision INTEGER NOT NULL,
        data TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(pipeline,step))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_recovery_decisions(
        pipeline TEXT NOT NULL, step TEXT NOT NULL, binding TEXT NOT NULL,
        code TEXT NOT NULL, reason TEXT NOT NULL, next_action TEXT NOT NULL,
        PRIMARY KEY(pipeline,step))''')


def binding(step):return {k:step[k] for k in ('target_kind','target','request_id')}


def decision(state,p,s,code,reason,next_action):
    if not state.db.in_transaction:raise ValueError('Recovery decisions require an atomic owner transaction')
    state.db.execute('''INSERT INTO relay_recovery_decisions VALUES (?,?,?,?,?,?)
        ON CONFLICT(pipeline,step) DO UPDATE SET binding=excluded.binding,
        code=excluded.code,reason=excluded.reason,next_action=excluded.next_action''',
        (p['id'],s['id'],encoded(binding(s)),code,reason,next_action))
    return False


def snapshot(state,p,s):
    db=state.db
    result=dict(version=1,owner=dict(pipeline=p['id'],step=s['id']),binding=binding(s),
                phase=s['status'],reason=None,next_action='wait',certainty='not_dispatched',
                run=None,attempts=[],candidates=[],remaining_recovery_cycles=None)
    def outcome(phase,reason,action,certainty=None):
        result.update(phase=phase,reason=reason,next_action=action)
        if certainty:result['certainty']=certainty
        return result
    grant=db.execute('SELECT policy FROM completion_recovery_grants WHERE pipeline=?',(p['id'],)).fetchone()
    if grant:
        policy=json.loads(grant[0])
        if type(policy.get('cycles')) is not int or policy['cycles']<0:
            return outcome('held','The saved recovery grant has no valid cycle allowance.','review_authorization')
        params=(p['id'],s['id']) if policy.get('cycle_scope')=='stage' else (p['id'],)
        used=db.execute('SELECT count(*) FROM completion_recoveries WHERE pipeline=?'+(' AND step=?' if len(params)==2 else ''),params).fetchone()[0]
        extra=db.execute('SELECT coalesce(sum(cycles),0) FROM completion_recovery_extensions WHERE pipeline=? AND step=?',(p['id'],s['id'])).fetchone()[0]
        result['remaining_recovery_cycles']=max(0,policy['cycles']+extra-used)
    kind=s['target_kind'];target=s['target'];run=None;row=None
    if kind=='production_run':run=target
    elif kind=='plan_production':
        row=db.execute('SELECT status,run,error FROM production_plans WHERE id=?',(target,)).fetchone()
        if row:run=row['run']
    if run:
        if not db.execute('SELECT 1 FROM production_runs WHERE id=?',(run,)).fetchone():
            return outcome('owner_missing','The current stage points to a missing execution run.','inspect_owner')
        result['run']=run
        tasks=[dict(t) for t in db.execute('SELECT id,status,latest FROM production_tasks WHERE run=?',(run,))]
        latest={t['latest'] for t in tasks if t['latest']}
        attempts=[dict(a) for a in db.execute('SELECT id,task,state,error,receipt FROM production_attempts WHERE run=? ORDER BY rowid',(run,)) if a['id'] in latest or a['state'] in ('running','launching','cancelling','uncertain')]
        result['attempts']=[{k:a[k] for k in ('id','task','state')} for a in attempts]
        result['candidates']=[dict(a) for a in db.execute('SELECT id,attempt,sha256 FROM production_artifacts WHERE run=? ORDER BY id',(run,)) if a['attempt'] in latest]
        if any(a['state']=='uncertain' or json.loads(a['receipt'] or '{}').get('pending_requests') or json.loads(a['receipt'] or '{}').get('cleanup_error') for a in attempts):
            return outcome('pending_external','An execution outcome is uncertain. Its exact receipt must be reconciled before retry.','reconcile_receipt','unknown')
        live=[a for a in attempts if a['state'] in ('running','launching','cancelling')]
        if live:return outcome('executing','; '.join(a['task']+': '+a['state'] for a in live),'observe_receipt','pending')
        result['certainty']='confirmed' if attempts else 'not_dispatched'
    else:tasks=[]
    # A stopped parent can retain immutable completed stages and failed attempts.
    if s['status'] in ('completed','skipped','cancelled'):
        return outcome(s['status'],'Stage '+s['status']+'.','none')
    if p['status'] in ('paused','cancelled','planned'):
        return outcome(p['status'],'Workflow '+p['status']+'.','resume' if p['status'] in ('paused','planned') else 'none')
    saved=db.execute('SELECT * FROM relay_recovery_decisions WHERE pipeline=? AND step=?',(p['id'],s['id'])).fetchone()
    if saved and saved['binding']==encoded(binding(s)) and s['status']=='blocked':
        result['recovery_code']=saved['code']
        return outcome('held',saved['reason'],saved['next_action'])
    if s['status']=='awaiting_choice':return outcome('waiting_user','A candidate selection is required.','select_candidate')
    if s['status']=='pending':return outcome('waiting_dependencies','Waiting for earlier stages and admission.','advance_when_ready')
    if s['status']=='queued':
        job=db.execute('SELECT status FROM orchestrator_chats WHERE id=?',(s['request_id'],)).fetchone()
        if not job:return outcome('owner_missing','The queued stage has no saved planning request.','inspect_owner')
        return outcome('planning','Stage planning: '+job['status']+'.','observe_planning')
    if run:
        if not tasks:return outcome('owner_missing','The execution run has no saved assignments.','inspect_owner')
        if all(t['status']=='completed' for t in tasks):return outcome('ready','Execution and review finished; validating stage handoff.','advance')
        if any(t['status']=='awaiting_user' for t in tasks):return outcome('waiting_user','Execution requires a saved user decision.','review_decision')
        failed=[a for a in attempts if a['error']]
        if s['status']=='blocked' or any(t['status']=='blocked' for t in tasks):
            return outcome('held','; '.join(a['task']+': '+a['error'] for a in failed) or s['error'] or 'Execution stopped; no admissible recovery was recorded.','inspect_recovery')
        enabled=db.execute('SELECT value FROM kv WHERE key=?',('production-enabled:'+run,)).fetchone()
        enabled=bool(enabled and json.loads(enabled[0]))
        return outcome('queued' if enabled else 'waiting_user',
            'Waiting for the execution scheduler.' if enabled else 'Execution has no active dispatch grant.',
            'dispatch_when_ready' if enabled else 'review_start')
    if kind=='plan_production':
        if not row:return outcome('owner_missing','The stage plan is missing.','inspect_owner')
        return outcome('held' if row['status'] in ('blocked','uncertain','discarded') else 'planning',row['error'] or 'Stage plan: '+row['status']+'.',
                       'inspect_plan' if row['status'] in ('blocked','uncertain','discarded','needs_input') else 'admit_plan')
    if kind in ('browser_research','generate_image'):
        table='browser_jobs' if kind=='browser_research' else 'backend_jobs'
        effect=db.execute('SELECT status FROM '+table+' WHERE id=?',(target,)).fetchone()
        if not effect:return outcome('owner_missing','The stage effect has no saved request.','inspect_owner')
        status=effect['status']
        if status in ('uncertain','submitting'):return outcome('pending_external','The external result is not confirmed.','reconcile_receipt','unknown')
        if status in ('blocked','failed','cancelled'):return outcome('held',s['error'] or 'External operation '+status+'.','inspect_receipt','confirmed')
        return outcome('ready' if status=='completed' else 'executing','External operation '+status+'.','advance' if status=='completed' else 'observe_receipt','confirmed' if status=='completed' else 'pending')
    if s['status']=='blocked':return outcome('held',s['error'] or 'Stage stopped without an admissible continuation.','inspect_recovery')
    return outcome('owner_missing','The running stage has no supported saved execution owner.','inspect_owner')


def refresh(state,pid):
    if not state.db.in_transaction:raise ValueError('Stage state must commit with its owner')
    p=state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(pid,)).fetchone()
    if not p:return
    for s in state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(pid,)).fetchall():
        data=snapshot(state,p,s);raw=encoded(data)
        prior=state.db.execute('SELECT revision,data FROM relay_stage_state WHERE pipeline=? AND step=?',(pid,s['id'])).fetchone()
        if prior and prior['data']==raw:continue
        state.db.execute('''INSERT INTO relay_stage_state VALUES (?,?,?,?,?) ON CONFLICT(pipeline,step)
            DO UPDATE SET revision=excluded.revision,data=excluded.data,updated=excluded.updated''',
            (pid,s['id'],prior['revision']+1 if prior else 1,raw,time.time()))


def read(db,pid):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_stage_state'").fetchone():return []
    rows=[]
    for row in db.execute('SELECT * FROM relay_stage_state WHERE pipeline=? ORDER BY step',(pid,)):
        value=json.loads(row['data']);s=db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(pid,row['step'])).fetchone()
        if s and value['binding']==binding(s):rows.append({**value,'revision':row['revision'],'updated':row['updated']})
    return rows
