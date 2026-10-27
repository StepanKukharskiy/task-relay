"""One public-reader definition and handler for tool and scheduled-node calls.

The existing reader owns transport receipts. Both entry points share the run's
six-method allowance; the host lock protects accounting across concurrent nodes.
"""
import copy
import json
from pathlib import Path
from . import parameter_contracts

MAX_CHARS = 24000
MAX_METHODS = 6

DESCRIPTION = 'Read a public HTTPS page. Return captured text and source evidence; disclose inaccessible content. No login or user-browser control.'
PARAMETERS = dict(type='object', properties=dict(
    url=dict(type='string', minLength=1),
    offset=dict(type='integer', minimum=0),
    limit=dict(type='integer', minimum=1, maximum=MAX_CHARS),
    method=dict(type='string', enum=['auto','rendered'])),
    required=['url','offset','limit','method'], additionalProperties=False)
DEFAULTS = dict(offset=0, limit=MAX_CHARS, method='auto')


def tool():
    schema=copy.deepcopy(PARAMETERS)
    schema['required']=['url','offset','limit']
    return dict(name='web_fetch',description=DESCRIPTION,parameters=schema)


def read(session, arguments):
    args={**DEFAULTS,**arguments}
    parameter_contracts.validate(args,PARAMETERS,'web.fetch inputs')
    if not session.durable:
        return session.fetch(**args)
    from task_relay.host import HOST
    session.root.mkdir(parents=True,exist_ok=True)
    with (session.root/'reader.lock').open('a+b') as lock:
        try:HOST.lock(lock)
        except OSError as exc:
            raise ValueError('Another public read owns this run; no read submitted') from exc
        return session.fetch(**args)


def execute(ctx):
    from task_relay.orchestrator_web import Session
    from .operation_execution import Result
    from .runtime_outcomes import UncertainOperation
    root=Path(ctx.frozen['workspace']).parent.parent
    session=Session(root/'owner-context'/ctx.frozen['run']/'public-reads.json',durable=True,rendered=True)
    result=session.execute(dict(name='web_fetch',arguments=json.dumps(ctx.frozen['execution']['parameters'])))
    if result.get('outcome')=='uncertain':raise UncertainOperation(result.get('error','Uncertain public read'))
    return Result(data=json.dumps(result,ensure_ascii=False),validation=dict(acceptance=False,source_access=result.get('outcome')))


def register(registry, adapters):
    from .operation_adapters import Adapter
    registry['web.fetch']=dict(version=1,kind='procedure',input_types=[],min_inputs=0,max_inputs=0,input_bytes=0,
        output_type='application/json',outputs={'outputs/page.json':'application/json'},output_bytes=200000,
        seconds=600,external_requests=MAX_METHODS,parameters={k:k for k in PARAMETERS['properties']},
        criteria=['Retain the exact public read outcome and source evidence; no semantic approval.'],
        permissions='Public HTTP and isolated rendering only; shared six-method run allowance; no paid provider.',
        cancellation='Retain incomplete receipts as uncertain; never replay uncertain reads.',
        support_modules=['orchestrator.public_read_operation','task_relay.orchestrator_web','task_relay.source_browser'],
        tool_name='web_fetch',description=DESCRIPTION,input_defaults=DEFAULTS)
    adapters['web.fetch']=Adapter(parameters=PARAMETERS,handler='orchestrator.public_read_operation:execute',handoffs=dict(version=1,ports=[]))
