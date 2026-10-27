"""Trusted read-only continuation adapters; Runtime owns every queue mutation."""
import copy
import json
from dataclasses import dataclass
from . import contracts as c
from .operation_session import outcome
from . import continuation_events as receipts, continuation_detection as detection


@dataclass(frozen=True)
class Adapter:
    gaps: frozenset
    prove: object
    build: object
    allocation_required: bool = True
    events: object = lambda prepared,attempt,receipt: []
    version: int = 1
    grouped: bool = False
    requires_ungated: bool = False
    authorize: object = lambda state,p,s,baseline,authority: authority
    project: object = lambda ctx:([],[])
    group_event: str = None
    detect: object = None
    priority: int = 100

    def manifest(self):
        return dict(version=self.version,gaps=sorted(self.gaps),allocation_required=self.allocation_required,
            detector=(self.detect.__module__+':'+self.detect.__qualname__) if self.detect else None,priority=self.priority,grouped=self.grouped,requires_ungated=self.requires_ungated,group_event=self.group_event,
            hooks=[h.__module__+':'+h.__qualname__ for h in (self.prove,self.build,self.events,self.authorize,self.project)])


def checkpoint(rt,task,attempt):
    from .record_recovery import continuation_proof
    proof=continuation_proof(rt,task,attempt,json.loads(attempt['receipt'] or '{}'))
    return (proof,outcome('produce','yielded','registered_checkpoint',effect='confirmed',checkpoint=proof)) if proof else None


def review(rt,task,attempt):
    from task_relay.local_review import proof
    value=proof(rt,task,attempt)
    return (value,value['outcome']) if value else None


def preflight(rt,task,attempt):
    from task_relay.completion_recovery import registered_preflight_gap
    value=registered_preflight_gap(rt,attempt,json.loads(attempt['receipt'] or '{}'))
    return (value,outcome('validate','yielded','confirmed_native_preflight',effect='none',checkpoint=value)) if value else None


def provider_schema(rt,task,attempt):
    from task_relay.completion_recovery import schema_repair_gap
    value=schema_repair_gap(rt,attempt,json.loads(attempt['receipt'] or '{}'))
    return (value,outcome('validate','yielded','confirmed_provider_schema_repair',effect='none',checkpoint=value)) if value else None


def budget(rt,task,attempt):
    from task_relay.review_budget_recovery import proof
    value=proof(rt,task,attempt)
    return (value,outcome('review','yielded','confirmed_saved_review_budget',effect='confirmed',checkpoint=value)) if value else None


def photos(rt,task,attempt):
    from task_relay.public_photo_recovery import confirmed
    frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
    if not confirmed(frozen,receipt) or task['attempts']!=1:return None
    value=dict(frozen_sha256=c.digest(frozen),receipt_sha256=c.digest(receipt))
    return value,outcome('observe','yielded','confirmed_browser_setup',effect='none',checkpoint=value)


def unchanged(rt,task,attempt,proof,gap,reference,kind):
    spec=copy.deepcopy(rt.spec(task));maximum=max(spec['max_attempts'],task['attempts']+1) if gap else spec['max_attempts']
    if gap:spec['revision']=dict(instruction=gap['instruction'],source='existing_completion_recovery_grant',previous_attempt=attempt['id'])
    return spec,maximum


def revised(rt,task,attempt,proof,gap,reference,kind):
    if reference is None:
        if task['attempts']>=rt.spec(task)['max_attempts']:
            raise ValueError('Continuation needs its committed allocation')
        spec,maximum=unchanged(rt,task,attempt,proof,None,None,kind)
        spec['revision']=dict(kind=kind,previous_attempt=attempt['id'],instruction=proof['instruction'],
            source='original_assignment_attempts',proof=proof)
        return spec,maximum
    if proof!=gap:raise ValueError('Continuation proof changed before queue')
    spec,maximum=unchanged(rt,task,attempt,proof,gap,reference,kind)
    spec['revision']=dict(kind=kind,previous_attempt=attempt['id'],instruction=proof['instruction'],
        source='completion_recovery:'+reference['pipeline']+':'+str(reference['cycle']),proof=proof,baseline_sha256=reference['baseline_sha256'])
    return spec,maximum


def budget_successor(rt,task,attempt,proof,gap,reference,kind):
    from task_relay.completion_recovery import DELIVERY_POLICY
    from task_relay.review_budget_recovery import continuation
    if proof!=gap:raise ValueError('Saved review proof changed before queue')
    return continuation(rt,task,attempt,DELIVERY_POLICY),task['attempts']+1


def photo_successor(rt,task,attempt,proof,gap,reference,kind):
    from task_relay.completion_recovery import DELIVERY_POLICY
    from task_relay.public_photo_recovery import continuation
    return continuation(rt.spec(task),attempt,DELIVERY_POLICY),task['attempts']+1


def checkpoint_events(prepared,attempt,receipt):
    return [('operation_resume_queued',dict(parent=attempt['id'],committed=prepared['proof']['committed'],
        receipt_sha256=c.digest(receipt),checkpoint=prepared['proof'],attempts_reset=False,acceptance=False))]


REGISTRY={
    'provider_schema':Adapter(frozenset(('provider_schema_repair',)),provider_schema,unchanged,allocation_required=False),
    'record_checkpoint':Adapter(frozenset(('typed_record_budget','typed_provider_rejected')),checkpoint,unchanged,False,checkpoint_events,authorize=receipts.authorize_records,project=receipts.records,detect=detection.records,priority=50),
    'local_review_session':Adapter(frozenset(('local_review_session',)),review,revised,allocation_required=False,project=receipts.review,detect=detection.review,priority=20),
    'registered_input_preflight':Adapter(frozenset(('registered_input_preflight',)),preflight,revised,requires_ungated=True,project=receipts.native,detect=detection.native,priority=10),
    'saved_review_budget':Adapter(frozenset(('saved_review_budget',)),budget,budget_successor,project=receipts.budget,detect=detection.budget,priority=30),
    'public_photo_setup':Adapter(frozenset(('public_photo_setup',)),photos,photo_successor,grouped=True,project=receipts.photos,group_event='completion_public_photos_continued',detect=detection.photo_setup,priority=40),
}


def definition(kind):
    if kind not in REGISTRY:raise ValueError('Unsupported continuation adapter')
    return REGISTRY[kind]


def detect_gap(rt,task,attempt,photos=False):
    for adapter in sorted(REGISTRY.values(),key=lambda a:a.priority):
        if not adapter.detect:continue
        gap=adapter.detect(rt,task,attempt,photos)
        if gap:
            if gap.get('kind') not in adapter.gaps or gap.get('task')!=task['id'] or gap.get('attempt')!=attempt['id']:
                raise ValueError('Continuation classifier returned a foreign gap')
            return gap
    return None


from .worker_startup_recovery import prove as startup_proof
REGISTRY['worker_startup']=Adapter(frozenset(('worker_startup',)),startup_proof,unchanged,allocation_required=False)
