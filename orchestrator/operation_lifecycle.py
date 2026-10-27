"""Registered operation lifecycle shared by inline work and native tasks.

Transport-specific handlers produce evidence; these rules own effect certainty,
pending completion and resource identities. No application-specific controller.
"""
import json
import copy
import time
from . import execution, contracts as c
from .workers import atomic
from .runtime_outcomes import UncertainOperation


def traits(capability):
    spec=execution.REGISTRY[capability];adapter=execution.adapter(capability)
    resources=list(spec.get('resources', []))
    if spec['kind']=='host' and not resources:
        from .native_apps import profile
        try:resources=['host-'+profile(capability).name]
        except ValueError:resources=['host-'+capability.split('.')[0]]
    return dict(version=1, mode=spec['kind'], resources=sorted(set(resources)),
                external_effects=spec['kind']!='procedure' or spec['external_requests']!=0,
                executable=bool(adapter.handler), reconcile=adapter.reconcile)


def resources(task):
    result={task['resource']} if task.get('resource') else set()
    caps=[task['execution']['capability']] if task.get('execution') else []
    caps += [s['operation'] for s in task.get('work_tools', {}).get('steps', {}).values()]
    for cap in caps:result.update(traits(cap)['resources'])
    return result


def terminal(frozen, control, error=None):
    """A process exit/exception is not evidence of a failed external effect."""
    path=control/'operation.json'
    value=json.loads(path.read_text()) if path.exists() else {}
    state=value.get('outcome');external=traits(frozen['execution']['capability'])['external_effects']
    observation=dict(status='finished',execution=frozen['execution'])
    execution.adapter(frozen['execution']['capability']).inspect(control,observation,copy.deepcopy(value))
    if observation.get('status')=='uncertain' or observation.get('external_outcome')=='unknown':
        raise UncertainOperation(observation.get('reason','Registered receipt observer found unresolved work'))
    if state=='completed':return value
    if state=='failed' and (observation.get('operation_terminal_confirmed') or observation.get('external_outcome') in ('response_received','rejected','not_submitted')):
        return dict(value,effect='confirmed')
    if state=='rejected' or (state=='failed' and (not external or value.get('effect') in ('none','confirmed'))):
        return dict(value, effect=value.get('effect', 'none' if state=='rejected' else 'confirmed'))
    if not external and state is None:
        return dict(outcome='failed', effect='confirmed', reason=str(error or 'Local operation stopped'))
    raise UncertainOperation('Operation outcome requires reconciliation; no resubmission: '+str(value.get('reason') or error or state))


def identity(context):
    return c.digest(context.frozen)


def await_result(context, result):
    """Poll the registered status reader under the original durable deadline."""
    from .operation_execution import Result
    from .operation_adapters import resolve
    folder=context.control;adapter=execution.adapter(context.frozen['execution']['capability'])
    dispatch=json.loads((folder/'operation-dispatch.json').read_text())
    while result.receipt and result.receipt.get('outcome')=='pending':
        pending=result.receipt
        atomic(folder/'operation-pending.json', dict(binding=identity(context), receipt=pending))
        if not adapter.reconcile:raise UncertainOperation('Pending operation has no registered status reader')
        if (folder/'cancel.json').exists() or time.time()>=dispatch['deadline']:
            raise UncertainOperation('Pending operation stopped waiting; external outcome remains unresolved')
        time.sleep(min(.1, max(0, dispatch['deadline']-time.time())))
        result=resolve(adapter.reconcile)(context, pending)
        if not isinstance(result, Result):raise UncertainOperation('Invalid registered reconciliation result')
    if result.receipt is not None:
        # All adapters, including pending adapters, commit a terminal receipt.
        atomic(folder/'operation.json', result.receipt)
    return result


def materialized(context, receipt, *, verify=False):
    """Bind terminal operation receipt to the exact complete output version."""
    from .runtime import safe_file,file_hash
    proof=context.control/'operation-materialized.json'
    value=dict(binding=identity(context),receipt_sha256=c.digest(receipt),outputs={})
    for output in context.frozen.get('outputs',[]):
        path=safe_file(context.workspace,output['path'])
        value['outputs'][output['path']]=dict(sha256=file_hash(path),bytes=path.stat().st_size)
    adapter=execution.adapter(context.frozen['execution']['capability'])
    if adapter.review_evidence:
        from .operation_adapters import resolve
        value['adapter_evidence_sha256']=c.digest(resolve(adapter.review_evidence)(context.control,context.frozen))
    if verify:
        if not proof.exists() or json.loads(proof.read_text())!=value:
            raise UncertainOperation('Completed operation files lack an unchanged materialization receipt; reconcile without replay')
    else:atomic(proof,value)


def invoke(context):
    """One dispatch, or status-only reconciliation of a previously saved handle."""
    from .operation_execution import Result
    adapter=execution.adapter(context.frozen['execution']['capability'])
    pending=context.control/'operation-pending.json'
    intent=context.control/'operation-dispatch.json'
    binding=identity(context)
    if intent.exists():
        saved=json.loads(intent.read_text())
        if saved.get('binding')!=binding:raise UncertainOperation('Operation assignment or input identity changed')
        terminal_path=context.control/'operation.json'
        if terminal_path.exists() and json.loads(terminal_path.read_text()).get('outcome') in ('completed','failed','rejected'):
            receipt=terminal(context.frozen, context.control)
            if receipt['outcome']=='completed' and context.frozen.get('outputs'):
                materialized(context,receipt,verify=True)
            return Result(receipt=receipt)
        if not pending.exists():
            # A crash before a handle or receipt is never permission to submit again.
            return Result(receipt=terminal(context.frozen, context.control))
        saved=json.loads(pending.read_text())
        if saved.get('binding')!=binding:raise UncertainOperation('Pending operation identity changed')
        result=Result(receipt=saved['receipt'])
    else:
        atomic(intent, dict(binding=binding, deadline=time.time()+context.frozen['limits']['seconds']))
        result=adapter.execute(context)
    if not isinstance(result, Result):raise UncertainOperation('Invalid adapter result after dispatch')
    return await_result(context, result)
