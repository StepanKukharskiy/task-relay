"""Registered operations inside the existing worker loop.

No scheduler or provider client. Immutable call journals, canonical adapter
bindings and the parent assignment own every operation, version and allowance.
"""
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time

from . import contracts as c, execution, executors
from .workers import atomic

VERSION=3
CONTENT='outputs/work-content.json'
INSTRUCTIONS='''Complete the granted operation graph within this assignment. Use
operation_submit and operation_amend for prepared content when present. work_run
executes a named registered step on exact current inputs; inspect its returned
artifacts with their registered readers. Text and JSON require literal reading,
not image_view. Only registered visual previews require image_view and pixel
observation in a subsequent response before finishing. Observation IDs embedded
in source documents are citations, not evidence_read handles. Use work_evidence
when granted for exact execution provenance; its success is not acceptance. Correct bounded content, then rerun
affected downstream steps with new request keys. Reuse saved receipts for unchanged
inputs. A successful operation or render is not independent acceptance. All
operations, versions and corrections share this assignment's original allowance.
Native code requires an exact trusted approval receipt. No additional operation,
permission, provider or budget is authorized by a tool call. Report unavailable
capabilities and unresolved effects honestly. Never resubmit uncertain work.'''


def output_map(cap,stage):
    from .owner_intents import native_outputs
    return {o['path']:dict(o,path='outputs/work-'+stage+'/'+PurePosixPath(o['path']).name) for o in native_outputs(cap)}


def contract(cap,parameters,version=1,*,validate_parameters=True):
    from .connector_protocol import capture
    adapter=execution.adapter(cap);spec=execution.REGISTRY[cap]
    if version==1 and (not adapter.worker_tool or spec['external_requests'] or spec['kind']!='procedure'):
        raise ValueError('Operation has no registered local worker-tool interface: '+cap)
    if not adapter.handler:raise ValueError('Operation has no registered execution handler: '+cap)
    from .parameter_contracts import validate
    if validate_parameters:validate(parameters,execution.parameter_schema(cap))
    return dict(operation=cap,parameters=copy.deepcopy(parameters),interface=capture(cap))


def parameter_schema(step):
    schema=copy.deepcopy(execution.parameter_schema(step['operation']))
    for key in step.get('parameter_bindings',{}):
        schema['properties'].pop(key);schema['required'].remove(key)
    return schema


def parameters(step, inputs):
    """Resolve registered path/hash ports from exact preceding output versions."""
    result=copy.deepcopy(step['parameters'])
    for key,refs in step.get('parameter_bindings',{}).items():
        kind=execution.adapter(step['operation']).references[key]
        values=[]
        for ref in refs:
            path='inputs/'+ref['step']+'/'+PurePosixPath(ref['path']).name
            found=next((i for i in inputs if i['path']==path and i['media_type']==ref['media_type']),None)
            if not found:raise ValueError('Bound operation input is unavailable: '+path)
            values.append(found['sha256'] if kind=='sha256' else path)
        result[key]=values if kind=='paths' else values[0]
    return result


def bind_step_parameters(step, preceding):
    """Models name ports; code owns the immutable binding and input alias."""
    from .owner_intents import native_outputs,ports
    bindings={}
    for key,kind in execution.adapter(step['operation']).references.items():
        value=step['parameters'].get(key)
        refs=value if kind=='paths' and isinstance(value,list) else [value]
        if not any(isinstance(r,dict) and 'step' in r for r in refs):continue
        if not all(isinstance(r,dict) and set(r)=={'step','output'} for r in refs):raise ValueError('Use preceding step ports consistently for a bound parameter')
        bound=[]
        for ref in refs:
            if ref['step'] not in preceding or ref['step'] not in step['from_steps']:raise ValueError('Bound parameter requires a declared preceding step')
            source=ports(dict(outputs=native_outputs(preceding[ref['step']]['operation']))).get(ref['output'])
            if not source:raise ValueError('Unknown preceding operation output port')
            if source['media_type'] not in execution.REGISTRY[step['operation']]['input_types']:raise ValueError('Incompatible preceding operation output')
            bound.append(dict(step=ref['step'],path=source['path'],media_type=source['media_type']))
        bindings[key]=bound;step['parameters'].pop(key)
    if bindings:step['parameter_bindings']=bindings


def configure(task,intent,grant,*,bind_parameters=True):
    """Compile one work intent; all paths, preparations and companions are code owned."""
    version=grant.get('worker_tools_version')
    if version not in (1,2,3):raise ValueError('Worker operation tools are outside this grant')
    from .producer_binding import requirements
    cap=intent['operation']
    if cap not in grant['operations']:raise ValueError('Work operation is outside this job grant')
    if version==1 and execution.REGISTRY[cap].get('review_evidence'):raise ValueError('Preview operations are native tasks or worker inspection companions; choose a producing work operation')
    build=contract(cap,intent.get('parameters',{}),version,validate_parameters=bind_parameters);build['outputs']=output_map(cap,'build')
    ports=requirements(cap);preparation=None
    mode=intent.get('mode')
    if version==3:
        if mode not in ('execute','create','revise'):raise ValueError('Declare work.mode: execute existing inputs, create content, or revise an exact baseline')
        if mode=='execute' and intent.get('content_parameters'):raise ValueError('Execute cannot prepare new content; select create or revise explicitly')
        if mode!='revise' and intent.get('baseline'):raise ValueError('Baseline belongs to explicit revision')
        if mode!='execute' and intent.get('data'):raise ValueError('Data belongs to execute; use baseline for revision')
    elif any(k in intent for k in ('mode','data','baseline')):raise ValueError('Explicit work intent requires a prospective version 3 grant')
    prepare=version<3 or mode in ('create','revise')
    referenced=any(key in intent.get('parameters',{}) for key in execution.adapter(cap).references)
    if prepare and version>=2 and len(ports)==1 and ports[0]['kind']=='preparation' and ports[0]['selector']=='json' and not referenced:
        from .prepared_schemas import REGISTRY
        from .owner_compilation import request_ceiling
        registered=REGISTRY[ports[0]['target']]
        if registered['hash_inputs']:
            raise ValueError('This preparation needs exact baseline bindings; delegate a preparation producer and a native operation using its data port')
        if intent.get('content_parameters'):raise ValueError('Preparation fields are selected through registered fragment tools, not content_parameters')
        from .operation_contracts import REGISTRY as record_contracts
        batch=record_contracts['operation.preparation',1]['batch']
        params=dict(target=ports[0]['target'],max_records=min(100,max(1,request_ceiling(grant)-9)*batch),hash_bindings={})
        family=dict(id='operation.preparation',version=1)
        preparation=dict(family=family,parameters=params)
        task['operation_contract']=dict(**family,output=CONTENT,parameters=params)
        task['outputs']=[dict(path=CONTENT,purpose='Validated work content',media_type='application/json',content_contract=family)]
    elif prepare and ports and (version==1 or intent.get('content_parameters') or execution.adapter(cap).worker_tool):
        if len(ports)!=1 or ports[0]['selector']!='json' or ports[0]['kind']!='records' or len(ports[0]['families'])!=1:
            raise ValueError('Worker preparation needs a single registered fragment port')
        from .operation_contracts import identity
        family=ports[0]['families'][0];family=family if isinstance(family,dict) else dict(id=family,version=1)
        registered=identity(family);interface=registered['planning_interface']
        if interface.get('review_mode')!='structural' or interface['input_parameters']:
            raise ValueError('This preparation requires upstream semantic work and review')
        defaults=interface.get('producer_defaults')
        # Same registered defaults and schema used by producer-side binding.
        if defaults is None:raise ValueError('No registered worker preparation defaults')
        from .owner_compilation import request_ceiling
        params=defaults(task,max(1,min(40,(request_ceiling(grant)-9)*registered.get('batch',1)-1)))
        params.update(intent.get('content_parameters',{}))
        from .parameter_contracts import validate
        validate(params,interface['schema'])
        preparation=dict(family=family,parameters=params)
        task['records']=dict(family=copy.deepcopy(family),inputs={},parameters=params)
        task['outputs']=[dict(path=CONTENT,purpose='Validated work content',media_type='application/json')]
    elif intent.get('content_parameters'):raise ValueError('This operation has no content preparation interface')
    else:task['outputs']=[]
    steps={'build':build}
    companions=[name for name,kind in execution.REGISTRY[cap].get('companions',{}).items() if kind=='independent-review-evidence']
    if companions:
        choices=[name for name in companions if name in grant['operations']]
        if len(choices)!=1:raise ValueError('Work requires one granted inspection companion')
        inspect=contract(choices[0],{},version);inspect['outputs']=output_map(choices[0],'inspect');steps['inspect']=inspect
    if intent.get('steps'):
        if version<2:raise ValueError('Additional operations need a version 2 work grant')
        for item in intent['steps']:
            name=item['id'];c.label(name)
            if name in steps:raise ValueError('Duplicate work step')
            if item['operation'] not in grant['operations']:raise ValueError('Work step exceeds the grant')
            step=contract(item['operation'],item.get('parameters',{}),version,validate_parameters=False)
            sources=item.get('from_steps',[])
            if len(set(sources))!=len(sources) or not set(sources)<=set(steps):raise ValueError('Work inputs must name distinct preceding steps')
            step.update(outputs=output_map(item['operation'],name),from_steps=sources)
            bind_step_parameters(step,steps)
            steps[name]=step
    if version>=2:
        for name,step in steps.items():step.setdefault('from_steps',['build'] if name=='inspect' else [])
        from .owner_compilation import request_ceiling
        minimum=sum(execution.REGISTRY[step['operation']]['external_requests'] or 0 for step in steps.values())+len(steps)+1
        if minimum>request_ceiling(grant):
            raise ValueError('Operation graph cannot fit the worker request allowance; delegate registered operations as native tasks with prepared input producers instead of inline work')
    task['outputs'] += [o for step in steps.values() for o in step['outputs'].values()]
    if version==3 and mode in ('create','revise') and preparation is None:
        raise ValueError('No registered content preparation for this operation; use execute with its typed inputs')
    task['work_tools']=dict(version=version,steps=steps,preparation=preparation)
    if grant.get('execution_review_version')==1:task['work_tools']['evidence_version']=1
    if grant.get('work_diagnostics_version')==1:
        from .operation_diagnostics import OUTPUT
        task['work_tools']['diagnostics']=copy.deepcopy(OUTPUT)
        task['outputs'].append(copy.deepcopy(OUTPUT))
    if version==3:task['work_tools']['intent']=dict(mode=mode)

    task['instruction']+='\n'+INSTRUCTIONS
    if task['work_tools'].get('diagnostics'):
        task['instruction']+=' On a confirmed operation failure, read outputs/work-diagnostics.json for the exact receipt and bounded diagnostic evidence. It is not an accepted deliverable.'
    if bind_parameters:validate_assignment(task)


def ordered_steps(scope):
    pending=dict(scope['steps']);done=set();ordered=[]
    while pending:
        ready=[n for n,s in pending.items() if set(s.get('from_steps',[]))<=done]
        if not ready:raise ValueError('Work dependency graph has a cycle or unknown step')
        for name in sorted(ready):ordered.append(name);done.add(name);pending.pop(name)
    return ordered


def validate_assignment(task):
    scope=task.get('work_tools')
    if not scope:return
    allowed_scope=({'version','steps','preparation','intent'} if scope.get('version')==3 else {'version','steps','preparation'})
    if 'evidence_version' in scope:
        allowed_scope.add('evidence_version')
        if type(scope['evidence_version']) is not int or scope['evidence_version']!=1:raise ValueError('Invalid execution evidence policy')
    if 'diagnostics' in scope:allowed_scope.add('diagnostics')
    if set(scope)!=allowed_scope or scope['version'] not in (1,2,3) or task.get('execution') or task.get('review_of'):
        raise ValueError('Invalid worker-tool scope')
    if 'build' not in scope['steps'] or (scope['version']==1 and set(scope['steps']) not in ({'build'},{'build','inspect'})):raise ValueError('Invalid work steps')
    expected=[]
    if 'diagnostics' in scope:
        from .operation_diagnostics import OUTPUT
        if scope['diagnostics']!=OUTPUT or OUTPUT not in task['outputs']:raise ValueError('Diagnostic output is code owned')
        expected.append(OUTPUT['path'])
    if scope['preparation']:
        expected.append(CONTENT)
        actual=task.get('records',{}).get('parameters',task.get('operation_contract',{}).get('parameters'))
        if actual!=scope['preparation']['parameters']:raise ValueError('Work content parameters changed')
        family=scope['preparation']['family']
        binding=task.get('records',{}).get('family') or {k:task.get('operation_contract',{}).get(k) for k in ('id','version')}
        if binding!=family:raise ValueError('Work preparation differs from its record binding')
    if scope['version']==3:
        route=scope['intent'];mode=route.get('mode')
        if mode not in ('execute','create','revise') or set(route)-{'mode','data','baseline'}:raise ValueError('Invalid compiled work intent')
        if 'data' in route and mode!='execute' or 'baseline' in route and mode!='revise':raise ValueError('Compiled work intent has contradictory bindings')
        if bool(scope['preparation'])!=(mode!='execute'):raise ValueError('Work intent changed its preparation authority')
    preceding=set()
    for name in ordered_steps(scope):
        step=scope['steps'][name]
        c.label(name)
        if scope['version']>=2 and (not isinstance(step['from_steps'],list) or not set(step['from_steps'])<=preceding):raise ValueError('Invalid work dependency order')
        preceding.add(name)
        allowed={'operation','parameters','interface','outputs'}|({'from_steps'} if scope['version']>=2 else set())
        if step.get('parameter_bindings') and scope['version']>=2:allowed.add('parameter_bindings')
        if set(step)!=allowed or contract(step['operation'],step['parameters'],scope['version'],validate_parameters=False)!={k:step[k] for k in ('operation','parameters','interface')}:
            raise ValueError('Worker operation grant or interface changed')
        from .parameter_contracts import validate
        validate(step['parameters'],parameter_schema(step))
        for key,refs in step.get('parameter_bindings',{}).items():
            kind=execution.adapter(step['operation']).references.get(key)
            if not kind or not refs or (kind!='paths' and len(refs)!=1):raise ValueError('Invalid registered parameter binding')
            for ref in refs:
                if ref['step']==name or ref['step'] not in step['from_steps']:raise ValueError('Parameter binding is outside preceding step grant')
                source=scope['steps'][ref['step']]
                if ref['path'] not in source['outputs'] or source['outputs'][ref['path']]['media_type']!=ref['media_type']:raise ValueError('Bound output port changed')
        if step['outputs']!=output_map(step['operation'],name):raise ValueError('Work output mapping is code owned')
        for output in step['outputs'].values():
            if output not in task['outputs']:raise ValueError('Work output descriptor changed')
        expected += [o['path'] for o in step['outputs'].values()]
    if len(set(expected))!=len(expected) or set(expected)!={o['path'] for o in task['outputs']}:raise ValueError('Work outputs differ from registered projections')
    if 'inspect' in scope['steps']:
        build=scope['steps']['build']['operation'];inspect=scope['steps']['inspect']['operation']
        if execution.REGISTRY[build].get('companions',{}).get(inspect)!='independent-review-evidence':raise ValueError('Unregistered work inspection')
    if task.get('backend') and task['backend']['type'] not in executors.FILE_TYPES:raise ValueError('Work tools require the shared declared-file API loop')
    from .artifact_roles import validate
    validate(task)


def validate_inputs(task):
    scope=task.get('work_tools',{})
    if scope.get('version')!=3:return
    from .producer_binding import requirements
    route=scope['intent'];step=scope['steps']['build'];mode=route['mode']
    inputs={i['path']:i for i in task['inputs']}
    for key in ('data','baseline'):
        if key in route and route[key] not in inputs:raise ValueError('Work '+key+' must bind an exact declared input')
    if mode=='revise' and 'baseline' not in route:raise ValueError('Revision has no bound baseline')
    if mode=='execute':
        if any(p['selector']=='json' and not step['parameters'].get(p.get('reference_parameter')) for p in requirements(step['operation'])) and 'data' not in route:
            raise ValueError('Execute requires an explicit data reference for its registered JSON port; no authoring is inferred')
        from .artifact_roles import operation_inputs
        from .handoff_closure import capture
        selected=operation_inputs(task,'build') if task.get('artifact_roles') else task['inputs']
        if route.get('data'):
            selected=[i for i in selected if i['path']==route['data'] or i.get('media_type') in capture([step['operation']]).get(step['operation'],[])]
        execution.validate_inputs(dict(execution=dict(capability=step['operation']),inputs=selected))


def native_assignment(task):
    """The same native preflight, without starting a worker or granting effects."""
    scope=task.get('work_tools',{})
    if scope.get('version')!=3 or scope['intent']['mode']=='create':return None
    validate_inputs(task)
    from .artifact_roles import operation_inputs
    step=scope['steps']['build'];route=scope['intent']
    if route['mode']=='revise':
        from .handoff_closure import capture
        media=capture([step['operation']]).get(step['operation'],[])
        consumed={i['path'] for i in operation_inputs(task,'build')}
        inputs=[i for i in task['inputs'] if i['path']==route['baseline'] or
                i['path'] in consumed and i.get('media_type') in media]
    else:inputs=operation_inputs(task,'build')
    bound={k:v for k,v in task.items() if k not in ('work_tools','operation_contract','records','artifact_roles')}
    bound.update(inputs=inputs,outputs=list(step['outputs'].values()),execution=dict(capability=step['operation'],version=execution.REGISTRY[step['operation']]['version'],parameters=step['parameters']))
    return bound


def owned(task):
    scope=task.get('work_tools',{})
    return {o['path'] for s in scope.get('steps',{}).values() for o in s['outputs'].values()} | ({scope['diagnostics']['path']} if 'diagnostics' in scope else set())


def freeze(frozen,rt=None):
    validate_assignment(frozen)
    validate_inputs(frozen)
    if rt is not None:
        from .artifact_roles import verify
        verify(rt,frozen)
    bindings={}
    for name,step in frozen['work_tools']['steps'].items():
        sub=copy.deepcopy(frozen)
        sub['backend']=copy.deepcopy(frozen.get('work_backends',{}).get(name,frozen['backend']))
        sub['execution']=dict(capability=step['operation'],version=execution.REGISTRY[step['operation']]['version'],parameters=step['parameters'])
        before=set(sub)
        execution.adapter(step['operation']).freeze(sub,execution.REGISTRY[step['operation']])
        bindings[name]={k:copy.deepcopy(v) for k,v in sub.items() if k not in before}
        frozen['runtime_sources'].update(sub['runtime_sources'])
    frozen['work_bindings']=bindings


def definitions(frozen):
    return ([dict(name='work_evidence',description='Read the current exact operation evidence envelope. Large values reference hash-bound documents: pass their exact page path as document and use offset for bounded reads. Preserve page order to reconstruct original JSON. References are not observations or acceptance; no execution.',parameters=dict(type='object',properties=dict(step=dict(type='string',enum=list(frozen['work_tools']['steps'])),offset=dict(type='integer',minimum=0),document=dict(type='string')),required=['step'],additionalProperties=False))] if frozen['work_tools'].get('evidence_version')==1 else [])+[dict(name='work_run',description='Execute a granted operation step on exact current inputs. Reuse a completed request key without execution; use a new key for changed inputs. Code owns effects, pending completion and recovery.',parameters=dict(type='object',properties=dict(step=dict(type='string',enum=list(frozen['work_tools']['steps'])),request_key=dict(type='string',minLength=1,maxLength=120)),required=['step','request_key'],additionalProperties=False)),
            dict(name='artifact_inspect',description='Read exact artifact identity and byte count. This does not inspect visual appearance or infer semantic acceptance.',parameters=dict(type='object',properties=dict(path=dict(type='string')),required=['path'],additionalProperties=False))]


def files(frozen,control):
    from .artifact_files import files as evidence_files
    return evidence_files(frozen,control)

def execute_local(frozen,control,parent_control,remaining,reconcile=False):
    """Existing fixed child command; process-tree ownership stays in the host adapter."""
    from task_relay.host import HOST
    from task_relay import runtime_process
    command=runtime_process.command(sys.executable,Path(__file__).with_name('step_runner.py'),control,frozen['workspace'])
    if reconcile:command.append('--reconcile')
    with (control/('reconciliation.log' if reconcile else 'runtime.log')).open('ab') as log:
        process=HOST.spawn(command,env=runtime_process.environment(),stdout=log,stderr=subprocess.STDOUT,cwd=frozen['workspace'])
        try:
            deadline=time.monotonic()+remaining
            while process.poll() is None:
                if (parent_control/'cancel.json').exists() or time.monotonic()>=deadline:
                    HOST.stop_tree(process);raise ValueError('Work operation cancelled or reached the assignment deadline')
                time.sleep(.02)
        finally:
            if process.poll() is None:HOST.stop_tree(process)
        if process.returncode:
            record=control/'operation.json'
            detail=json.loads(record.read_text()).get('reason') if record.exists() else (control/'runtime.log').read_text(errors='replace')[-2000:]
            raise ValueError('Registered work operation failed: '+str(detail))
    return json.loads((control/'operation.json').read_text())


class Session:
    def __init__(self,files,control):
        self.files=files;self.frozen=files.frozen;self.control=Path(control)
        validate_assignment(self.frozen)
        from .runtime import file_hash
        names=['worker_tools.py','work_authorization.py','operation_lifecycle.py','runtime_outcomes.py']
        if self.frozen['work_tools'].get('diagnostics'):names.append('operation_diagnostics.py')
        for name in names:
            if file_hash(Path(__file__).with_name(name))!=self.frozen['runtime_sources'].get(name):raise ValueError('Worker tool implementation changed after freezing')
        self.binding=c.digest(self.frozen);self.folder=self.control/'work-operations';self.folder.mkdir(exist_ok=True)
        self.current={};self.receipts=[];self.unresolved=[]
        for folder in sorted(self.folder.iterdir()):
            if not folder.is_dir():continue
            if not (folder/'intent.json').exists():continue # preflight only, never dispatched
            intent=json.loads((folder/'intent.json').read_text())
            if intent['binding']!=self.binding:raise RuntimeError('Work journal belongs to another assignment')
            if not (folder/'outcome.json').exists():
                self.unresolved.append((folder,intent));continue
            receipt=json.loads((folder/'outcome.json').read_text())
            if receipt.get('status') not in ('completed','failed'):raise RuntimeError('Work operation is uncertain; reconcile without replay')
            self.receipts.append((folder,intent,receipt))
            if receipt['status']=='completed':self.current[intent['step']]=(folder,intent,receipt)
        clock=self.control/'work-clock.json'
        if not clock.exists():atomic(clock,dict(binding=self.binding,started=time.time()))
        original=json.loads(clock.read_text())
        if original['binding']!=self.binding:raise RuntimeError('Worker clock belongs to another assignment')
        self.started=original['started']
        checkpoint=self.control/'work-session.json';self.saved=json.loads(checkpoint.read_text()) if checkpoint.exists() else None
        if self.saved:
            if self.saved['binding']!=self.binding:raise RuntimeError('Worker checkpoint differs from its assignment')
            self.started=self.saved['started']
        for value in self.current.values():self.publish(*value)
        self.publish_diagnostics()
        # Reconcile before another model exchange. The shared lifecycle forbids
        # redispatch and verifies the exact frozen assignment and pending handle.
        for folder,intent in self.unresolved:
            sub=json.loads((folder/'workspace/.relay/ASSIGNMENT.json').read_text())
            if not (folder/'operation-dispatch.json').exists():
                from .runtime_outcomes import UncertainOperation
                raise UncertainOperation('Work operation is uncertain: intent has no dispatch receipt; reconcile without replay')
            self.complete(folder,intent,sub,self.frozen['limits']['output_bytes']-self.bytes_used(),resume=True)

    def restore(self,contents,history):
        requests=list(self.control.glob('api-*.request.json'))
        if not self.saved:
            if requests:raise RuntimeError('Provider requests without a worker checkpoint need reconciliation')
            return contents,history,0,0
        next_request=self.control/f"api-{self.saved['requests']+1:02d}.request.json"
        expected=self.saved['requests']+bool(self.saved.get('pending') and next_request.exists())
        if len(requests)!=expected:raise RuntimeError('Provider journal differs from the saved checkpoint; reconcile')
        if self.saved.get('pending') and next_request.exists() and not (self.control/f"api-{expected:02d}.response.json").exists():
            raise RuntimeError('Provider request outcome is unresolved; reconcile without replay')
        if (self.control/'agent-result.json').exists():raise RuntimeError('Worker is terminal; collect its saved result')
        return copy.deepcopy(self.saved['contents']),copy.deepcopy(self.saved['history']),self.saved['requests'],self.saved['tools']

    def save(self,contents,history,requests,tools,*,pending=False):
        self.saved=dict(version=1,binding=self.binding,started=self.started,contents=contents,history=history,requests=requests,tools=tools,pending=pending)
        atomic(self.control/'work-session.json',self.saved)

    def begin(self,contents,history,number,tools):
        prefix=self.control/f'api-{number:02d}'
        if prefix.with_suffix('.request.json').exists():
            if not self.saved or not self.saved.get('pending') or self.saved['requests']+1!=number:
                raise RuntimeError('Provider request already exists outside the pending turn')
            return json.loads(prefix.with_suffix('.request.json').read_text())['payload'],json.loads(prefix.with_suffix('.response.json').read_text())
        self.save(contents,history,number-1,tools,pending=True)
        return None

    def remaining(self):
        return self.frozen['limits']['seconds']-(time.time()-self.started)

    def reserved_requests(self):
        # Unknown script internals are retained as unknown in their approval and
        # receipts; they must never be reported as measured zero provider usage.
        return sum(execution.REGISTRY[self.frozen['work_tools']['steps'][i['step']]['operation']]['external_requests'] or 0 for _,i,_ in self.receipts)

    def check_capacity(self,next_request):
        from .runtime_outcomes import Hold
        if self.remaining()<=0:raise Hold('work_capacity_exhausted','Original worker deadline exhausted',phase='produce')
        if next_request+self.reserved_requests()>self.frozen['limits'].get('provider_requests',self.frozen['limits']['tool_calls']):
            raise Hold('work_capacity_exhausted','Model and registered operation requests exhaust the original allowance',phase='produce')

    def bytes_used(self):
        return sum(r.get('produced_bytes',sum(d['bytes'] for d in r.get('outputs',{}).values())) for _,_,r in self.receipts)

    def diagnostic_limit(self):
        return min(512000,self.frozen['limits']['output_bytes']//8) if self.frozen['work_tools'].get('diagnostics') else 0

    def publish_diagnostics(self):
        if not self.frozen['work_tools'].get('diagnostics'):return
        from .operation_diagnostics import encoded
        from task_relay.filesystem import FILES
        raw=encoded(self.frozen,self.receipts)
        if len(raw)>self.diagnostic_limit():raise ValueError('Diagnostic evidence allowance exhausted; original journals retained')
        path=self.frozen['work_tools']['diagnostics']['path']
        FILES.write(self.files.grant(),path,raw);self.files.written[path]=len(raw)

    def inputs(self,name):
        scope=self.frozen['work_tools'];step=scope['steps'][name];spec=execution.REGISTRY[step['operation']]
        if scope['version']>=2:
            from .artifact_roles import operation_inputs
            values=[]
            for source_step in step['from_steps']:
                self.verify_current(source_step)
                for output in scope['steps'][source_step]['outputs'].values():
                    if output['media_type'] in spec['input_types']:
                        values.append(dict(source=output['path'],path='inputs/'+source_step+'/'+PurePosixPath(output['path']).name,purpose='Exact preceding result',authority='Unaccepted candidate',media_type=output['media_type']))
            values += [dict({k:i[k] for k in ('path','purpose','authority','media_type')},source=i['path']) for i in operation_inputs(self.frozen,name)]
            if name=='build' and scope['preparation']:
                from .operation_records import Store
                store=Store(self.frozen);store.export(self.files,complete=True);store.verify_export(self.files.read_bytes)
                values=[v for v in values if v['media_type']!='application/json']
                values.insert(0,dict(source=CONTENT,path='prepared/content.json',purpose='Validated content',authority='Structural validity only',media_type='application/json'))
            return values
        if name=='inspect':
            if 'build' not in self.current:raise ValueError('Build a candidate before inspection')
            self.verify_current('build')
            values=[o for o in scope['steps']['build']['outputs'].values() if o['media_type'] in spec['input_types']]
            if len(values)!=1:raise ValueError('Inspection needs one exact candidate')
            source=values[0];return [dict(source=source['path'],path='inputs/candidate'+PurePosixPath(source['path']).suffix,purpose='Current work candidate',authority='Unaccepted candidate',media_type=source['media_type'])]
        values=[]
        if scope['preparation']:
            from .operation_records import Store
            store=Store(self.frozen);store.export(self.files,complete=True);store.verify_export(self.files.read_bytes)
            values.append(dict(source=CONTENT,path='prepared/content.json',purpose='Validated content',authority='Structural validity only',media_type='application/json'))
        from .artifact_roles import operation_inputs
        for item in operation_inputs(self.frozen,name):
            if item['media_type'] not in spec['input_types']:continue
            if scope['preparation'] and item['media_type']=='application/json':continue
            values.append({k:v for k,v in item.items() if k in ('path','purpose','authority','media_type')}|dict(source=item['path']))
        return values

    def descriptors(self,name):
        return [dict(i,sha256=hashlib.sha256(self.files.read_bytes(i['source'])).hexdigest()) for i in self.inputs(name)]

    def publish(self,folder,intent,receipt):
        from task_relay.filesystem import FILES
        for path,detail in receipt['outputs'].items():
            from .runtime import safe_file
            raw=safe_file(folder/'workspace',path).read_bytes()
            if len(raw)!=detail['bytes'] or hashlib.sha256(raw).hexdigest()!=detail['sha256']:raise RuntimeError('Committed work output changed')
            target=self.frozen['work_tools']['steps'][intent['step']]['outputs'][path]['path']
            FILES.write(self.files.grant(),target,raw);self.files.written[target]=len(raw)

    def verify_current(self,name):
        if name not in self.current:raise ValueError('Missing '+name+' result')
        folder,intent,receipt=self.current[name]
        if intent['inputs']!=self.descriptors(name):raise ValueError('Saved '+name+' result is stale; run it with the corrected current inputs')
        for path,detail in receipt['outputs'].items():
            target=self.frozen['work_tools']['steps'][name]['outputs'][path]['path']
            if hashlib.sha256(self.files.read_bytes(target)).hexdigest()!=detail['sha256']:raise ValueError('Published work result changed')

    def run(self,args):
        from .parameter_contracts import validate
        validate(args,next(t['parameters'] for t in definitions(self.frozen) if t['name']=='work_run'))
        name=args['step'];step=self.frozen['work_tools']['steps'][name];inputs=self.descriptors(name)
        intent=dict(binding=self.binding,step=name,request_key=args['request_key'],inputs=inputs)
        prior=next((v for v in self.receipts if v[1]['request_key']==args['request_key']),None)
        if prior:
            if prior[1]!=intent:raise ValueError('Work request key already belongs to different inputs')
            if prior[2]['status']!='completed':raise ValueError('This request already failed; correct the cause and use a new key within the allowance')
            # Reuse never changes which version is current.
            return self.result(*prior,reused=True)
        if execution.adapter(step['operation']).evidence_extension and name in self.current:
            current=self.current[name]
            if current[1]['inputs']==inputs:
                # Append-only readers must advance from the retained result.
                # A fresh request key cannot reread the same immutable source.
                self.verify_current(name)
                return self.result(*current,reused=True)
        remaining=self.remaining()
        if (self.control/'cancel.json').exists():raise ValueError('Work assignment is cancelled')
        if remaining<=0:
            from .runtime_outcomes import Hold
            raise Hold('work_capacity_exhausted','Assignment deadline exhausted',phase='produce')
        spec=execution.REGISTRY[step['operation']]
        reserved=spec['external_requests'] or 0
        used=(self.saved or {}).get('requests',0)+bool((self.saved or {}).get('pending'))
        self.check_capacity(used+reserved+1) # retain a final model decision
        ceiling=self.frozen['limits']['output_bytes']-self.bytes_used()-self.diagnostic_limit()-sum(n for p,n in self.files.written.items() if p not in owned(self.frozen))
        if ceiling<1:
            from .runtime_outcomes import Hold
            raise Hold('work_capacity_exhausted','Cumulative work output allowance exhausted',phase='produce')
        prepared=next((p.parent for p in self.folder.glob('*/preparation.json') if json.loads(p.read_text())==intent),None)
        folder=prepared or self.folder/f'{max([int(p.name) for p in self.folder.iterdir() if p.is_dir()]+[0])+1:04d}'
        folder.mkdir(exist_ok=True);workspace=folder/'workspace';workspace.mkdir(exist_ok=True);(workspace/'.relay').mkdir(exist_ok=True)
        atomic(folder/'preparation.json',intent)
        from .owner_intents import native_outputs
        sub=dict(id=self.frozen['id'],role='registered_operation',objective='Execute the granted operation',instruction='Execute the granted operation on exact current inputs',dependencies=[],assignment_id=self.frozen['assignment_id'],run=self.frozen['run'],workspace=str(workspace),
            execution=dict(capability=step['operation'],version=spec['version'],parameters=parameters(step,inputs)),
            criteria=spec['criteria'],tools=[],max_attempts=1,inputs=[],outputs=native_outputs(step['operation']),
            limits=dict(seconds=max(1,min(spec['seconds'],int(remaining))),tool_calls=1,output_bytes=min(spec['output_bytes'],ceiling)),
            backend=copy.deepcopy(self.frozen.get('work_backends',{}).get(name,self.frozen['backend'])),
            runtime_sources=copy.deepcopy(self.frozen['runtime_sources']),host_support=copy.deepcopy(self.frozen['host_support']))
        if self.frozen.get('provider_cooldown'):sub['provider_cooldown']=copy.deepcopy(self.frozen['provider_cooldown'])
        sub.update(copy.deepcopy(self.frozen.get('work_bindings',{}).get(name,{})))
        for item in inputs:
            data=self.files.read_bytes(item['source']);target=workspace/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if target.read_bytes()!=data:raise ValueError('Prepared operation input changed')
            else:target.write_bytes(data);target.chmod(0o400)
            sub['inputs'].append({k:v for k,v in item.items() if k!='source'}|dict(artifact=self.files.inputs.get(item['source'],{}).get('artifact') or c.digest([self.frozen['assignment_id'],item['source'],item['sha256']])))
        from .work_authorization import bind_inputs
        adapter=execution.adapter(step['operation'])
        for parameter in adapter.reference_media:
            matches=[i for i in sub['inputs'] if i['sha256']==sub['execution']['parameters'].get(parameter)]
            if len(matches)!=1:raise ValueError('Named operation input must select exactly one artifact: '+parameter)
            adapter.bind_reference_media(parameter,matches[0])
        bind_inputs(self.frozen,sub,folder)
        if prepared and (folder/'host-proposal.json').exists():
            old=json.loads((folder/'host-proposal.json').read_text())['assignment']
            # Approval pins the original allowance; elapsed parent time still gates dispatch.
            sub['limits']=old['limits']
        from .connector_protocol import bind
        sub.update(bind(sub,step['interface']))
        execution.validate(sub);execution.adapter(step['operation']).check_available(sub,spec)
        sub['producer_binding_version']=1
        execution.adapter(step['operation']).validate_content(sub,lambda p:(workspace/p).read_bytes())
        from .host_code import required as code_required, verify_frozen
        if code_required(sub):
            from .work_authorization import attach
            attach(self.frozen,sub,name,inputs)
            verify_frozen(sub)
        atomic(workspace/'.relay/ASSIGNMENT.json',sub);atomic(folder/'intent.json',intent)
        # Everything above is local preparation; the durable intent precedes dispatch.
        return self.complete(folder,intent,sub,ceiling)

    def complete(self,folder,intent,sub,ceiling,*,resume=False):
        from .runtime_outcomes import UncertainOperation
        workspace=folder/'workspace';name=intent['step'];remaining=self.remaining()
        spec=execution.REGISTRY[sub['execution']['capability']]
        try:
            operation=execute_local(sub,folder,self.control,max(.1,min(remaining,spec['seconds'])),True) if resume else execute_local(sub,folder,self.control,max(.1,min(remaining,spec['seconds'])))
            from .operation_lifecycle import terminal
            operation=terminal(sub,folder)
            if operation.get('outcome')!='completed':raise ValueError(str(operation.get('summary') or operation.get('reason') or 'Operation did not complete'))
            outputs={}
            for output in sub['outputs']:
                from .runtime import safe_file
                raw=safe_file(workspace,output['path']).read_bytes();outputs[output['path']]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            if sum(v['bytes'] for v in outputs.values())>ceiling:raise ValueError('Cumulative work output allowance exceeded')
            outcome=dict(status='completed',operation=operation,outputs=outputs,external_request_reservation=spec['external_requests'])
        except UncertainOperation:
            raise
        except (ValueError,OSError) as exc:
            from .operation_lifecycle import terminal
            operation=terminal(sub,folder,exc)
            outcome=dict(status='failed',error=str(exc),outputs={},produced_bytes=sum((workspace/o['path']).stat().st_size for o in sub['outputs'] if (workspace/o['path']).is_file()))
            if self.frozen['work_tools'].get('diagnostics'):
                from .operation_diagnostics import capture
                outcome['diagnostics']=capture(folder,sub,operation,exc,self.diagnostic_limit())
            atomic(folder/'outcome.json',outcome);self.receipts.append((folder,intent,outcome))
            self.publish_diagnostics()
            return dict(error=str(exc)[:4000],status='failed',effect='confirmed',version=folder.name,produced_bytes=outcome['produced_bytes'],
                        **({'diagnostics':self.frozen['work_tools']['diagnostics']['path']} if 'diagnostics' in outcome else {}))
        atomic(folder/'outcome.json',outcome);self.receipts.append((folder,intent,outcome));self.current[name]=(folder,intent,outcome)
        self.publish(folder,intent,outcome)
        return self.result(folder,intent,outcome)

    def result(self,folder,intent,receipt,reused=False):
        return dict(step=intent['step'],reused=reused,version=folder.name,
            outputs=[dict(path=self.frozen['work_tools']['steps'][intent['step']]['outputs'][p]['path'],**v) for p,v in receipt['outputs'].items()],
            structurally_completed=True,independently_accepted=False)

    def validate_delivery(self,observe=True):
        for name in self.frozen['work_tools']['steps']:self.verify_current(name)
        if observe and self.frozen['work_tools']['version']>=2:
            from .visual_files import confirmed_pixels,rendered_pixels
            pixels=set()
            for name in self.current:
                for o in self.frozen['work_tools']['steps'][name]['outputs'].values():
                    if o['media_type']=='image/png':pixels|=rendered_pixels(self.files.read_bytes(o['path']),'image/png')
            if not pixels<=confirmed_pixels(self.control):raise ValueError('Inspect every current native preview before finish')
        if observe and 'inspect' in self.current:
            from .visual_files import confirmed_pixels,rendered_pixels
            pixels=set();_,_,receipt=self.current['inspect']
            for path,o in self.frozen['work_tools']['steps']['inspect']['outputs'].items():
                if o['media_type'] in ('application/zip','image/png'):pixels|=rendered_pixels(self.files.read_bytes(o['path']),o['media_type'])
            if not pixels or not pixels<=confirmed_pixels(self.control):raise ValueError('Inspect every current rendered page in a subsequent model response before finish')
        return dict(steps={name:dict(version=folder.name,inputs=intent['inputs'],outputs=receipt['outputs']) for name,(folder,intent,receipt) in self.current.items()},acceptance=False)


def verify_delivery(frozen,control,db=None,*,candidate=False):
    """Read-only collection/review check; never republishes or executes anything."""
    from .runtime import safe_file
    control=Path(control);workspace=Path(frozen['workspace']);scope=frozen['work_tools']
    from .operation_diagnostics import verify_projection
    verify_projection(frozen,control)
    proof=None if candidate else json.loads((control/'work-delivery.json').read_text())
    if proof is not None and (proof.get('acceptance') is not False or set(proof.get('steps',{}))!=set(scope['steps'])):raise ValueError('Incomplete work delivery receipt')
    binding=c.digest(frozen);latest={}
    for folder in sorted((control/'work-operations').iterdir()):
        if not folder.is_dir() or not (folder/'intent.json').exists():continue
        intent=json.loads((folder/'intent.json').read_text())
        if intent['binding']!=binding:raise ValueError('Work receipt identity changed')
        if not (folder/'outcome.json').exists():raise ValueError('Work delivery has an uncertain operation')
        outcome=json.loads((folder/'outcome.json').read_text())
        if outcome['status']=='completed':latest[intent['step']]=(folder,intent,outcome)
    if not candidate and set(latest)!=set(scope['steps']):raise ValueError('Missing committed work steps')
    if candidate:
        proof=dict(steps={name:dict(version=folder.name,inputs=intent['inputs'],outputs=outcome['outputs'])
                         for name,(folder,intent,outcome) in latest.items()},acceptance=False,candidate_only=True)
    if scope['preparation']:
        from .operation_records import Store
        Store(frozen,db).verify_export(lambda path:safe_file(workspace,path).read_bytes())
    for name,(folder,intent,outcome) in latest.items():
        expected=dict(version=folder.name,inputs=intent['inputs'],outputs=outcome['outputs'])
        if proof['steps'][name]!=expected:raise ValueError('Work delivery points at an older or altered version')
        for item in intent['inputs']:
            if hashlib.sha256(safe_file(workspace,item['source']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Work result is stale against its current inputs')
        if set(outcome['outputs'])!=set(scope['steps'][name]['outputs']):raise ValueError('Missing registered work output')
        for path,detail in outcome['outputs'].items():
            alias=scope['steps'][name]['outputs'][path]['path']
            for root,source in ((folder/'workspace',path),(workspace,alias)):
                raw=safe_file(root,source).read_bytes()
                if len(raw)!=detail['bytes'] or hashlib.sha256(raw).hexdigest()!=detail['sha256']:raise ValueError('Work output differs from its committed version')
    if not candidate and 'inspect' in latest:
        from .visual_files import rendered_pixels,confirmed_pixels
        required=set()
        for output in scope['steps']['inspect']['outputs'].values():
            required|=rendered_pixels(safe_file(workspace,output['path']).read_bytes(),output['media_type'])
        if not required or not required<=confirmed_pixels(control):raise ValueError('Current work previews were not inspected')
    return proof


def inspection_evidence(rt,attempt,operation):
    """Expose committed registered inspection receipts, without new execution."""
    frozen=json.loads(attempt['frozen']);scope=frozen.get('work_tools',{})
    step=scope.get('steps',{}).get('inspect',{})
    if step.get('operation')!=operation:return None
    control=Path(json.loads(attempt['session'])['control']);proof=verify_delivery(frozen,control,rt.db,candidate=True)
    if 'inspect' not in proof['steps']:return None
    inspection=proof['steps']['inspect']
    if len(inspection['inputs'])!=1:raise ValueError('Inspection receipt requires one exact candidate')
    source=inspection['inputs'][0]
    return dict(candidate_path=source['source'],candidate_sha256=source['sha256'],
        outputs={step['outputs'][path]['path']:detail for path,detail in inspection['outputs'].items()})


def reviewed_pixels(rt,artifact,candidate):
    """Resolve the same exact local render receipt for independent review."""
    if candidate['attempt']!=artifact['attempt']:return set()
    attempt=rt.db.execute('SELECT frozen,session FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
    frozen=json.loads(attempt['frozen']);scope=frozen.get('work_tools',{})
    if 'inspect' not in scope.get('steps',{}):return set()
    control=Path(json.loads(attempt['session'])['control']);proof=verify_delivery(frozen,control,rt.db,candidate=True)
    if 'inspect' not in proof['steps']:return set()
    candidates={}
    for name,step in scope['steps'].items():
        if name not in proof['steps']:continue
        for path,output in step['outputs'].items():candidates[output['path']]=proof['steps'][name]['outputs'][path]['sha256']
    if candidates.get(candidate['path'])!=candidate['sha256'] or candidates.get(artifact['path'])!=artifact['sha256']:return set()
    inspection=scope['steps']['inspect']['outputs']
    output=next((o for o in inspection.values() if o['path']==artifact['path']),None)
    if not output:return set()
    from .visual_files import rendered_pixels
    raw=Path(artifact['blob']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=artifact['sha256']:raise ValueError('Work inspection artifact changed')
    return rendered_pixels(raw,output['media_type'])
