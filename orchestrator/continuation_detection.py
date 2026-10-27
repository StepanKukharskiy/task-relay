"""Read-only stopped-work classifiers registered with continuation adapters."""
import json


def native(rt,task,attempt,photos):
    from task_relay.completion_recovery import registered_preflight_gap
    return registered_preflight_gap(rt,attempt,json.loads(attempt['receipt']))


def review(rt,task,attempt,photos):
    from task_relay.local_review import proof
    return proof(rt,task,attempt)


def budget(rt,task,attempt,photos):
    from task_relay.review_budget_recovery import proof
    return proof(rt,task,attempt)


def photo_setup(rt,task,attempt,photos):
    if not photos:return None
    from task_relay.public_photo_recovery import confirmed
    if confirmed(json.loads(attempt['frozen']),json.loads(attempt['receipt'])):
        return dict(task=task['id'],kind='public_photo_setup',attempt=attempt['id'],instruction='Continue authorized public photo discovery in an isolated unsigned-in profile; preserve the confirmed pre-submission stop.')


def records(rt,task,attempt,photos):
    from .record_recovery import supports,checkpoint,rejected_checkpoint
    from .operation_records import Store
    frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'])
    if not supports(frozen,'resumable'):return None
    rejected=rejected_checkpoint(frozen,receipt,rt.db,authorized=False)
    if rejected:
        return dict(task=task['id'],kind='typed_provider_rejected',attempt=attempt['id'],committed=rejected['committed'],remaining=rejected['remaining'],proof=rejected,instruction='Resume exact inherited records after explicit authorization following the confirmed billing rejection; do not repeat source collection or reset attempts.')
    if checkpoint(frozen,receipt,rt.db):
        progress=Store(frozen,rt.db).progress()
        if progress.get('committed',0)>0 and progress.get('remaining',0)>0:
            return dict(task=task['id'],kind='typed_record_budget',attempt=attempt['id'],committed=progress['committed'],remaining=progress['remaining'],instruction='Continue exact committed typed records under the existing bounded recovery grant; do not repeat completed items or source collection.')
