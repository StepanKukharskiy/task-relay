"""Build executable assignments from typed selections, never from model constants.

V1 owns one standalone rhino3dm execution/review stage. Pure construction only:
no provider, native application, artifact mutation, approval or dispatch.
"""
import copy
import json
from pathlib import PurePosixPath

from orchestrator import contracts as c
from orchestrator.execution import REGISTRY
from orchestrator.rhino3dm_script_contract import validate_checks

CAPABILITY='rhino3dm.run_python'
PORTS={'model':'delivery/candidate.3dm','script':'delivery/model.py',
       'checks':'delivery/checks.json','receipt':'delivery/execution.json'}
SPEC_FIELDS=('version','input_types','max_inputs','input_bytes','seconds','output_bytes',
             'outputs','criteria','parameters','requires_registered_inputs')
INSTRUCTIONS='''When operation_builder is present, this typed contract replaces the generic task,
operation and deliverable_map authoring instructions above. Preserve all request,
source-fidelity, scope and approval restrictions.
This is a typed standalone-library execution stage: exact script/checks already exist.
For ready, plan contains only operation="rhino3dm.run_python" and inputs with script
and checks artifact IDs from operation_builder.slots. For edit checks also select
scene; create checks must omit scene. Optional assets lists exact captured additional
input IDs, retaining their captured workspace aliases. Optional review_instruction
contains task-specific review concerns, not acceptance or permission. If requested
deliverables exist, plan.deliverables maps each requested ID to an output port:
model, script, checks or receipt. Relay constructs the tasks, paths, hashes, version,
fixed criteria, limits, reviewer and selection gate. Do not supply tasks, execution,
parameters, tools, worker, permissions, gates, deliverable_map or deferred_operations.
Keep required geometry_basis/input_basis declarations in the response envelope.
Missing or ambiguous inputs require needs_input or blocked, never substitute files.
This proposes exact-code execution; the delivered script/checks and Start remain required.
'''


class ContractError(ValueError):
    def __init__(self,code,field,expected):
        self.code=code;self.field=field;self.expected=expected
        super().__init__(field+': '+expected)

    def receipt(self):
        return dict(code=self.code,field=self.field,expected=self.expected,builder_version=1)


def freeze(payload):
    """Opt in only a single operation with captured, valid preparation inputs.

    No inference from filenames alone for checks; use the already frozen text and
    its domain validator. Preparation/mixed/legacy stages keep their contracts.
    """
    options=payload['options']
    if options.get('step_capabilities')!=[CAPABILITY]:return None
    spec=next((x for x in payload.get('graph_operations',[]) if x['id']==CAPABILITY),None)
    if not spec:return None
    texts={x['artifact']:x['text'] for x in payload.get('source_texts',[])}
    from .geometry_sources import is_source
    sources=[x for x in payload['sources'] if is_source(x)]
    scripts=[];checks={};scenes=[];assets=[]
    for source in sources:
        aid=source['artifact'];suffix=PurePosixPath(source['path']).suffix.lower()
        if suffix=='.py' and aid in texts and source['bytes']<=100000:scripts.append(aid)
        if suffix=='.3dm':scenes.append(aid)
        if suffix=='.json' and aid in texts:
            try:
                value=json.loads(texts[aid]);validate_checks(value)
            except (ValueError,TypeError,KeyError):pass
            else:checks[aid]=value['mode']
        assets.append(aid)
    if not scripts or not checks:return None
    return dict(version=1,capability=CAPABILITY,spec={k:copy.deepcopy(spec[k]) for k in SPEC_FIELDS},
                slots=dict(script=scripts,checks=list(checks),scene=scenes,assets=assets),
                checks_modes=checks)


def plan_schema(policy,options):
    from .planning_contract import obj,array
    slots=policy['slots']
    def ref(key):return {'type':'string','enum':slots[key]}
    inputs={'script':ref('script'),'checks':ref('checks')}
    if slots['scene']:inputs['scene']=ref('scene')
    if slots['assets']:inputs['assets']=array(ref('assets'))
    properties={'operation':{'type':'string','enum':[CAPABILITY]},
                'inputs':obj(inputs,('script','checks')),
                'review_instruction':{'type':'string'}}
    required=['operation','inputs']
    if options.get('deliverables'):
        properties['deliverables']=obj({k:{'type':'string','enum':list(PORTS)} for k in options['deliverables']},options['deliverables'])
        required.append('deliverables')
    return obj(properties,required)


def build(result,payload,options):
    policy=payload['operation_builder'];request=result['plan']
    if policy.get('version')!=1 or policy.get('capability')!=CAPABILITY:
        raise ContractError('unsupported_builder','$.plan.operation','Use the frozen supported operation builder.')
    if options.get('step_capabilities')!=[CAPABILITY]:
        raise ContractError('scope_changed','$.plan.operation','The frozen scope must contain only '+CAPABILITY+'.')
    spec=policy['spec'];current={k:REGISTRY[CAPABILITY][k] for k in SPEC_FIELDS}
    if spec!=current:
        raise ContractError('operation_changed','$.plan.operation','Registered contract changed; prepare a new proposal, never rebind silently.')
    known={s['artifact']:s for s in payload['sources']}
    selected=request['inputs'];script=selected['script'];checks=selected['checks'];scene=selected.get('scene')
    mode=policy['checks_modes'][checks]
    if mode=='edit' and not scene:
        raise ContractError('missing_input','$.plan.inputs.scene','Select a captured .3dm source for these edit checks.')
    if mode=='create' and scene:
        raise ContractError('unexpected_input','$.plan.inputs.scene','Create checks have no primary scene; omit this slot.')
    ids=[script,checks]+([scene] if scene else [])+selected.get('assets',[])
    if len(ids)!=len(set(ids)):
        raise ContractError('duplicate_input','$.plan.inputs','Each artifact may fill only one input slot.')
    if len(ids)>spec['max_inputs'] or sum(known[x]['bytes'] for x in ids)>spec['input_bytes']:
        raise ContractError('input_limit','$.plan.inputs','Selected inputs exceed the frozen operation input bound.')
    instruction=request.get('review_instruction','')
    if not isinstance(instruction,str) or len(instruction)>3000:
        raise ContractError('invalid_detail','$.plan.review_instruction','Use at most 3000 characters of review concerns.')
    def source(aid,media):
        value=known[aid]
        return dict(artifact=aid,path=value['path'],purpose=value['purpose'],authority=value['authority'],media_type=media)
    inputs=[source(script,'text/x-python'),source(checks,'application/json')]
    if scene:inputs.append(source(scene,'application/vnd.rhino'))
    for aid in selected.get('assets',[]):
        # Extra files have no script/checks/primary-scene role, even if JSON/3DM.
        inputs.append(source(aid,'application/octet-stream'))
    outputs=[dict(path=p,media_type=m,purpose='Registered standalone-library '+next(k for k,v in PORTS.items() if v==p))
             for p,m in spec['outputs'].items()]
    host=dict(id='execute_model',role='procedure',objective='Execute the selected standalone rhino3dm script.',
              instruction='Run only the exact selected script and checks within the original request. Save and reopen the candidate with the standalone library.',
              inputs=inputs,outputs=outputs,dependencies=[],criteria=copy.deepcopy(spec['criteria']),
              limits=dict(seconds=min(spec['seconds'],options['limits']['seconds']),tool_calls=1,output_bytes=spec['output_bytes']),
              max_attempts=1,tools=[],user_gate='Select the exact reviewed model, script, checks and execution receipt.',
              selection_outputs=list(spec['outputs']),
              execution=dict(capability=CAPABILITY,version=spec['version'],parameters=dict(
                  script_sha256=known[script]['sha256'],checks_sha256=known[checks]['sha256'],
                  scene_sha256=known[scene]['sha256'] if scene else None,permissions='unrestricted_host')))
    reviewer=dict(id='review_model',role='reviewer',objective='Independently review the saved model and execution evidence.',
                  instruction='Inspect all exact candidate outputs and original script/checks against request/USER-REQUEST.txt. Reopen the library model for necessary measurements; do not execute the modeling script. Report findings and limitations; library verification is not native Rhino or user acceptance.'+('\nTask-specific review concerns: '+instruction if instruction else ''),
                  inputs=[dict(from_task=host['id'],output=o['path'],path='candidate/'+o['path'],
                               purpose='Independently review '+o['purpose'],authority='Unaccepted candidate output',media_type=o['media_type']) for o in outputs],
                  outputs=[dict(path='review/model.md',purpose='Independent model and evidence review',media_type='text/markdown')],
                  dependencies=[host['id']],review_of=host['id'],criteria=copy.deepcopy(spec['criteria']),
                  worker={'requires':['files.text','files.binary','code.execute']},
                  limits={k:min(options['limits'][k],v) for k,v in dict(seconds=600,tool_calls=60,output_bytes=2000000).items()},
                  max_attempts=options.get('max_attempts',1))
    compiled=copy.deepcopy(result)
    compiled['plan']=dict(brief='Execute and independently review the selected standalone rhino3dm model.',tasks=[host,reviewer])
    if options.get('deliverables'):
        compiled['deliverable_map']={k:dict(task=host['id'],output=PORTS[v]) for k,v in request['deliverables'].items()}
    receipt=dict(version=1,capability=CAPABILITY,request=copy.deepcopy(request),
                 registry_sha256=c.digest(spec),input_versions=[dict(artifact=aid,sha256=known[aid]['sha256']) for aid in ids])
    return compiled,receipt
