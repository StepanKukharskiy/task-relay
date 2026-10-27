"""Exact native-code approval bridge for registered in-assignment operations.

Only a trusted caller may authorize a saved proposal after obtaining the user's
decision. This module is not an agent tool and cannot broaden an operation grant.
"""
import copy
import json
from pathlib import Path
from . import contracts as c
from .workers import atomic
from .runtime_outcomes import Hold


def attach(parent, sub, step, inputs):
    folder=Path(sub['workspace']).parent
    # Store the exact candidate before asking the existing approval boundary.
    proposal=dict(parent=parent['assignment_id'], step=step, assignment=copy.deepcopy(sub))
    proposal_path=folder/'host-proposal.json'
    if proposal_path.exists():
        if json.loads(proposal_path.read_text())!=proposal:raise Hold('host_code_authorization_changed','Saved exact operation proposal changed; original retained')
    else:atomic(proposal_path, proposal)
    path=folder/'host-authorization.json'
    if not path.exists():
        raise Hold('host_code_authorization_required', 'Exact-script host approval is required for the saved operation proposal; no native code dispatched')
    value=json.loads(path.read_text())
    if value['proposal_sha256']!=c.digest(proposal):
        raise Hold('host_code_authorization_changed', 'Native operation differs from the exact approved proposal')
    from .runtime import Runtime
    rt=Runtime(Path(parent['workspace']).parent.parent)
    try:
        rows=rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='work_code_authorized'",(parent['assignment_id'],))
        if not any(json.loads(row[0])==value for row in rows):
            raise Hold('host_code_authorization_uncommitted','Native approval has no committed decision receipt')
    finally:rt.close()
    for key, field in value['authorization']['binding']['assignment'].items():
        sub.setdefault(key,copy.deepcopy(field))
    sub.update(host_code_authorization=value['authorization'],
               authorized_assignment_digest=value['authorization']['binding']['assignment_digest'])


def authorize(rt, parent_attempt, proposal_path, decision):
    """Trusted service entry, following the same explicit receipt as host_code.authorize."""
    from . import host_code
    from .runtime import file_hash
    if not rt.db.in_transaction:raise ValueError('Approval must commit with the explicit user decision')
    if not isinstance(decision,dict) or not decision.get('source'):raise ValueError('Missing explicit user decision receipt')
    row=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(parent_attempt,)).fetchone()
    if not row:raise ValueError('Unknown work assignment')
    task=rt.task(row['run'],row['task'])
    if task['latest']!=parent_attempt or task['status'] in ('cancelled','completed','superseded'):raise ValueError('Work assignment no longer owns this operation')
    parent=json.loads(row['frozen']);control=Path(json.loads(row['session'])['control']).resolve()
    path=Path(proposal_path).resolve()
    if not path.is_relative_to(control/'work-operations') or path.name!='host-proposal.json':raise ValueError('Proposal is outside this assignment')
    proposal=json.loads(path.read_text());sub=proposal['assignment'];step=proposal['step']
    if (path.parent/'intent.json').exists():raise ValueError('Dispatched work cannot acquire a replacement approval')
    if Path(sub['workspace']).resolve()!=path.parent/'workspace' or any(sub.get(k)!=parent[k] for k in ('id','run','assignment_id')):raise ValueError('Operation proposal identity changed')
    if sub['limits']['seconds']>parent['limits']['seconds'] or sub['limits']['output_bytes']>parent['limits']['output_bytes']:raise ValueError('Operation proposal exceeds its parent allowance')
    granted=parent['work_tools']['steps'][step]
    from .execution import REGISTRY
    from .worker_tools import parameters
    if proposal['parent']!=parent_attempt or sub['execution']!=dict(capability=granted['operation'],version=REGISTRY[granted['operation']]['version'],parameters=parameters(granted,sub['inputs'])):
        raise ValueError('Proposal differs from granted operation')
    if not host_code.required(sub):raise ValueError('Operation does not require native-code approval')
    spec={k:copy.deepcopy(v) for k,v in sub.items() if k not in ('workspace','assignment_id','run','runtime_sources','host_support','backend')}
    spec.setdefault('objective','Execute approved work operation');spec.setdefault('instruction',spec['objective']);spec.setdefault('dependencies',[])
    for item in spec['inputs']:
        if file_hash(Path(sub['workspace'])/item['path'])!=item['sha256']:raise ValueError('Proposed input changed')
        # Existing input artifacts must still have exactly these bytes.
        artifact=rt.artifact(item['artifact'])
        if artifact['sha256']!=item['sha256']:raise ValueError('Proposed input identity changed')
        item.pop('sha256',None)
    binding=host_code.binding(rt,spec)
    authorization=dict(binding=binding,decision=copy.deepcopy(decision))
    value=dict(proposal_sha256=c.digest(proposal),authorization=authorization)
    rt.event(parent['run'],parent['id'],parent_attempt,'work_code_authorized',value)
    # The operation checks the committed event as well as this local projection.
    atomic(path.with_name('host-authorization.json'),value)
    return value


def bind_inputs(parent, sub, folder):
    """Register exact intermediate versions and invoke ordinary adapter preflight.

The event is provenance for an unaccepted candidate, never delivery/acceptance.
All database writes commit before the child can dispatch an external operation.
"""
    from . import execution
    from .runtime import Runtime, file_hash
    from .runtime_outcomes import Hold
    rt=Runtime(Path(parent['workspace']).parent.parent)
    try:
        row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(parent['assignment_id'],)).fetchone()
        if not row or json.loads(row['frozen'])!=parent:raise Hold('work_parent_changed','Parent assignment no longer matches its committed grant')
        with rt.transaction():
            for item in sub['inputs']:
                source=Path(sub['workspace'])/item['path']
                if file_hash(source)!=item['sha256']:raise ValueError('Intermediate input changed')
                existing=rt.db.execute('SELECT * FROM production_artifacts WHERE id=?',(item['artifact'],)).fetchone()
                if existing:
                    if existing['sha256']!=item['sha256']:raise ValueError('Registered input identity changed')
                else:
                    saved=rt.db.execute('SELECT id FROM production_artifacts WHERE source=? AND sha256=?',
                        (str(source.absolute()),item['sha256'])).fetchone()
                    item['artifact']=saved['id'] if saved else rt.register(source,'Unaccepted intermediate operation input',path=item['path'])
                    if not saved:rt.event(parent['run'],parent['id'],parent['assignment_id'],'work_input_registered',dict(artifact=item['artifact'],sha256=item['sha256'],path=item['path'],accepted=False))
            execution.adapter(sub['execution']['capability']).bind_inputs(rt,sub)
    finally:rt.close()
