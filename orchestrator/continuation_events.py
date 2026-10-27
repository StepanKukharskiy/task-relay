"""Pure compatibility receipt projections for registered continuations."""
from . import contracts as c


def limits(ctx):
    return dict(parent=ctx['run'],cycle=ctx['cycle'],baseline_sha256=ctx['digest'],assignment_sha256=c.digest(ctx['spec']),proof=ctx['gap'],
        task_attempt_limit_before=ctx['committed']['task_attempt_limit_before'],task_attempt_limit_after=ctx['spec']['max_attempts'],attempts_reset=False,allowances_expanded=False)


def native(ctx):return [],[('native_preflight_continued',dict(**limits(ctx),provider_planning_calls=0))]
def review(ctx):return [],[('local_review_session_queued',dict(**limits(ctx),cycle_attempt_allocated=bool(ctx['gap'].get('requires_cycle_attempt')),accepted=False))]


def budget(ctx):
    detail=dict(previous_assignment=ctx['task']['assignment'],assignment=ctx['committed']['assignment'],cycle=ctx['cycle'],candidate=ctx['gap']['candidate'],attempts_reset=False,source_collection_repeated=False,accepted=False)
    return [('saved_review_budget_continued',detail)],[('completion_review_continued',dict(detail,parent=ctx['run'],task=ctx['gap']['task'],attempt=ctx['gap']['attempt'],baseline_sha256=ctx['digest']))]


def photos(ctx):
    detail=dict(previous_assignment=ctx['task']['assignment'],assignment=ctx['committed']['assignment'],cycle=ctx['cycle'],profile=ctx['spec']['browser']['profile'],attempts_reset=False,provider_repeated=False,settings_changed=False,accepted=False)
    return [('public_photo_setup_continued',detail)],[]


def records(ctx):
    gap=ctx['gap']
    return [],[('completion_records_continued',dict(parent=ctx['run'],cycle=ctx['cycle'],task=gap['task'],attempt=gap['attempt'],previous_assignment=ctx['task']['assignment'],assignment=ctx['committed']['assignment'],committed=gap['committed'],remaining=gap['remaining'],new_attempts=1,attempts_reset=False,authorization=ctx['authority'],baseline_sha256=ctx['digest'],provider_repeated=False))]


def authorize_records(state,p,s,baseline,authority):
    if any(g['kind']=='typed_provider_rejected' for g in baseline['gaps']):
        row=state.db.execute('SELECT request FROM completion_recovery_extensions WHERE pipeline=? AND step=? AND baseline_sha256=? ORDER BY rowid DESC LIMIT 1',(p['id'],s['id'],c.digest(baseline))).fetchone()
        if not row:return None
        return row['request']
    return authority
