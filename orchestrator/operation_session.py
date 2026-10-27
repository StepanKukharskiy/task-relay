"""Durable local review sessions and structured execution outcomes.

A physical invocation never owns acceptance. Checkpoints retain observations and
provisional judgments; the normal report validator owns final disposition.
"""
import copy
import hashlib
import json
from pathlib import Path
from . import contracts as c
from .workers import atomic

VERSION = 1
STATUSES = {'progress','completed','correction_needed','yielded','waiting_external','needs_user','failed'}
PHASES = {'compile','observe','produce','validate','review','finalize','materialize','deliver'}


def outcome(phase,status,code,*,path=None,effect='none',checkpoint=None,usage=None):
    if phase not in PHASES or status not in STATUSES or effect not in {'none','confirmed','uncertain'}:
        raise ValueError('Invalid operation outcome')
    if not isinstance(code,str) or not code:raise ValueError('Outcome needs a stable code')
    return dict(version=VERSION,phase=phase,status=status,code=code,path=path,effect=effect,
                checkpoint=checkpoint,usage=usage or {})


def transition(value,*,remaining_attempts,confirmed,unchanged):
    """One transition policy; error wording never selects a recovery branch."""
    if value.get('version')!=VERSION:return 'hold'
    if value.get('effect')=='uncertain' or not confirmed:return 'reconcile'
    if not unchanged:return 'hold'
    if value.get('status')=='completed':return 'advance'
    if value.get('status') in {'yielded','correction_needed'} and remaining_attempts>0:return 'continue_local'
    return 'hold'


def supported(frozen):
    from .executors import FILE_TYPES
    from .record_recovery import supports
    return (bool(frozen.get('review_of')) and frozen.get('backend',{}).get('type') in FILE_TYPES
            and not any(frozen.get(k) for k in ('browser','computer','execution','user_gate'))
            and (not frozen.get('operation_contract') or supports(frozen,'resumable'))
            and set(frozen.get('tools',[]))<={'files'})


def identity(frozen):
    value=dict(candidate=frozen.get('review_target'),backend=frozen['backend'],
        inputs=sorted([(i['path'],i['artifact'],i['sha256']) for i in frozen['inputs']]),
        criteria=frozen['criteria'],report_contract=frozen.get('report_contract'),tools=frozen.get('tools',[]))
    if frozen.get('operation_contract'):value['operation_contract']=frozen['operation_contract']
    return c.digest(value)


def record_state(frozen,db=None):
    """Bind typed judgments without turning record completion into acceptance."""
    if not frozen.get('operation_contract'):return None
    from .operation_records import Store
    store=Store(frozen,db)
    with store.connection(write=False) as connection:revision,records=store._state(connection)
    return dict(revision=revision,committed=len(records),records_sha256=c.digest(records),
                complete=bool(store.lifecycle.complete(store,records)))


class Session:
    def __init__(self,files,control,report_store):
        self.files=files;self.frozen=files.frozen;self.control=Path(control);self.report_store=report_store
        self.identity=identity(self.frozen);self.parent=None;self.sequence=0
        inherited=self.frozen.get('review_checkpoint')
        if inherited:
            value=inherited['data']
            if c.digest(value)!=inherited['sha256']:raise ValueError('Review checkpoint changed before invocation')
            self.restore(value);self.parent=dict(sha256=inherited['sha256'])
        self.supplied_observed=copy.deepcopy(self.files.observed)

    def received(self):
        """The confirmed response proves the preceding input was supplied."""
        self.supplied_observed=copy.deepcopy(self.files.observed)

    def restore(self,value):
        if value.get('version')!=VERSION or value.get('identity')!=self.identity:
            raise ValueError('Review session candidate, input or criteria changed')
        observed=value.get('observed',{})
        if set(observed)-set(self.files.inputs):raise ValueError('Checkpoint has undeclared inputs')
        for path,intervals in observed.items():
            from .evidence_context import literal_input
            raw=self.files.read_bytes(path)
            if not literal_input(self.files,path):
                if intervals:raise ValueError('Binary evidence cannot carry text observation intervals')
                continue
            length=len(raw.decode('utf-8'))
            for span in intervals:
                if (not isinstance(span,list) or len(span)!=2 or any(type(x)is not int for x in span)
                        or not 0<=span[0]<=span[1]<=length):raise ValueError('Invalid checkpoint observation')
                self.files.observe(path,*span,raw)
        notes=value.get('notes',[])
        if not isinstance(notes,list) or len(c.encoded(notes).encode())>200000:raise ValueError('Oversized checkpoint notes')
        self.files.evidence_notes=copy.deepcopy(notes)
        checks=value.get('checks',{})
        if checks and not self.report_store:raise ValueError('Checkpoint checks lack a review contract')
        for key,detail in checks.items():self.report_store.validate(key,detail)
        if self.report_store:self.report_store.checks=copy.deepcopy(checks)
        if value.get('record_state'):
            current=record_state(self.frozen)
            if any(current[k]!=value['record_state'][k] for k in ('committed','records_sha256','complete')):
                raise ValueError('Review checkpoint typed judgments changed')

    def save(self,*,requests=0,tools=0):
        self.sequence+=1
        value=dict(version=VERSION,identity=self.identity,attempt=self.frozen['assignment_id'],
            sequence=self.sequence,observed=copy.deepcopy(self.supplied_observed),
            notes=copy.deepcopy(getattr(self.files,'evidence_notes',[])),
            checks=copy.deepcopy(self.report_store.checks if self.report_store else {}),
            usage=dict(requests=requests,tool_calls=tools),parent=self.parent,accepted=False)
        records=record_state(self.frozen)
        if records:value['record_state']=records
        atomic(self.control/'review-session.json',value)
        return dict(path=str(self.control/'review-session.json'),sha256=hashlib.sha256((self.control/'review-session.json').read_bytes()).hexdigest())

    def record(self,status,code,*,phase='review',requests=0,tools=0,effect='none'):
        checkpoint=self.save(requests=requests,tools=tools)
        records=record_state(self.frozen)
        if phase=='review' and records and records['complete']:phase='finalize'
        value=outcome(phase,status,code,effect=effect,checkpoint=checkpoint,usage=dict(requests=requests,tool_calls=tools))
        atomic(self.control/'execution-outcome.json',value)
        return value

    def view(self):
        from .evidence_context import progress
        # Checkpoints record prior observation, not a claim that a new model saw
        # omitted text. The same logical review retains provisional conclusions.
        value=dict(session=self.identity,remaining=progress(self.files),
            provisional_checks=self.report_store.checks if self.report_store else {},
            provisional_notes=[n.get('notes','') for n in getattr(self.files,'evidence_notes',[])],
            authority='Exact-version continuation of the same independent review; provisional observations are amendable and are not acceptance.')
        if self.frozen.get('operation_contract'):
            from .operation_records import Store
            store=Store(self.frozen)
            with store.connection(write=False) as db:_,records=store._state(db)
            value['provisional_records']=records
            value['phase']='finalize' if store.lifecycle.complete(store,records) else 'review'
        return value
