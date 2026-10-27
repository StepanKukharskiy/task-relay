"""Trusted operation child. One invocation, no tools, no automatic API retries."""
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from orchestrator import contracts as c, execution
from orchestrator.runtime import safe_file,file_hash
from orchestrator.workers import atomic


def execute(frozen,control,client_factory=None,config_reader=None,*,reconcile=False):
    from task_relay.host import verify_support
    verify_support(frozen)
    spec=execution.validate(frozen);control=Path(control);workspace=Path(frozen['workspace'])
    # Detect implementation drift between committed claim and child startup.
    for name in ('execution.py','step_runner.py', 'media_adapters.py',
                 'operation_adapters.py','operation_validators.py','parameter_contracts.py','operation_execution.py','operation_lifecycle.py'):
        if frozen.get('runtime_sources',{}).get(name)!=file_hash(Path(__file__).with_name(name)):
            raise ValueError('Registered operation implementation changed after dispatch was frozen.')
    for name in spec.get('runtime_modules',[]):
        if frozen.get('runtime_sources',{}).get(name)!=file_hash(Path(__file__).with_name(name)):
            raise ValueError('Registered collection implementation changed after dispatch')
    documents=[];total=0
    for item in frozen['inputs']:
        path=safe_file(workspace,item['path']);total+=path.stat().st_size
        if total>spec['input_bytes']:raise ValueError('Registered operation input byte limit exceeded.')
        if file_hash(path)!=item['sha256']:raise ValueError('Frozen input content changed.')
        media=item['media_type']
        text=path.read_bytes().decode('utf-8') if media.startswith('text/') or media in ('application/json','application/javascript','application/xml') or media.endswith(('+json','+xml')) else None
        documents.append({'artifact':item['artifact'],'path':item['path'],'sha256':item['sha256'],
                          'purpose':item['purpose'],'authority':item['authority'],'text':text})
    from orchestrator.operation_execution import Context, Result
    execution.adapter(frozen['execution']['capability']).verify_implementation(frozen,spec)
    execution.adapter(frozen['execution']['capability']).validate_content(
        frozen,lambda path:safe_file(workspace,path).read_bytes())
    if not execution.adapter(frozen['execution']['capability']).handler:raise ValueError('No execution handler registered; no fallback dispatched')
    if (control/'operation-dispatch.json').exists() and not reconcile:raise ValueError('Cannot replay a dispatched operation; explicit reconciliation required')
    from orchestrator.operation_lifecycle import invoke
    context=Context(frozen,control,workspace,spec,documents,client_factory,config_reader)
    value=invoke(context)
    if not isinstance(value,Result):raise ValueError('Adapter returned an invalid execution result')
    if value.receipt is not None:
        if value.receipt.get('outcome')=='completed':
            from orchestrator.operation_lifecycle import materialized
            materialized(context,value.receipt)
        return value.receipt
    result,upstream,usage,validation=value.data,value.upstream,value.usage or {},value.validation
    output=workspace/frozen['outputs'][0]['path']
    data=result if isinstance(result,bytes) else result.encode('utf-8')
    if len(data)>frozen['limits']['output_bytes']:raise ValueError('Registered output exceeds its byte limit.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream:stream.write(data)
    details={'outcome':'completed','execution':frozen['execution'],'upstream_id':upstream,'usage':usage,
             'input_bytes':total,'output_bytes':len(data),'output_sha256':hashlib.sha256(data).hexdigest(),
             'request_sha256':file_hash(control/'request.json') if spec['kind']=='api' else None,
             'response_sha256':file_hash(control/'response.json') if spec['kind']=='api' else None}
    if validation is not None:details['validation']=validation
    if value.failure:
        details.update(outcome='failed',reason=value.failure)
        atomic(control/'operation.json',details)
        raise ValueError(value.failure)
    atomic(control/'operation.json',details)
    report={'assignment_id':frozen['assignment_id'],'summary':'Registered '+frozen['execution']['capability']+' completed.',
            'decision':'delivered','instruction':'','checks':[{'criterion':1,'passed':True,
            'evidence':c.encoded({'input_hashes':[d['sha256'] for d in documents],'output_sha256':details['output_sha256']})}]}
    atomic(workspace/'.relay/result.json',report)
    from orchestrator.operation_lifecycle import materialized
    materialized(context,details)
    return details


def main():
    control=Path(sys.argv[1]);workspace=Path(sys.argv[2])
    frozen=json.loads((workspace/'.relay/ASSIGNMENT.json').read_text())
    try:execute(frozen,control,reconcile=len(sys.argv)>3 and sys.argv[3]=='--reconcile')
    except Exception as exc:
        prior=control/'operation.json'
        if not prior.exists():
            from orchestrator.operation_lifecycle import traits
            external=traits(frozen['execution']['capability'])['external_effects']
            dispatched=(control/'operation-dispatch.json').exists()
            atomic(prior,{'outcome':'uncertain' if external and dispatched else 'failed','effect':'uncertain' if external and dispatched else 'none','reason':str(exc),'usage':None})
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':main()
