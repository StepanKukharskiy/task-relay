"""Service-owned exact-code authorization receipts; never populated by a planner."""
import json
from pathlib import Path
from . import contracts as c

CAPABILITY='blender.run_python'
SOURCES=('host_code.py','blender_edit.py','blender_edit_worker.py','blender_snapshot.py','execution.py','step_runner.py')

def required(spec):return spec.get('execution',{}).get('capability') in (CAPABILITY,'rhino.run_python')

def profile(spec):
    from task_relay.host_apps import blender,rhino
    if spec['execution']['capability']=='rhino.run_python':
        from .rhino_contract import validate_checks
        sources=('host_code.py','rhino_contract.py','rhino_execution.py','rhino_worker.py','execution.py','step_runner.py',
                 '../task_relay/rhino_host.py','../task_relay/host_apps.py')
        return rhino(),validate_checks,'application/vnd.rhino',sources
    from .blender_edit import validate_checks
    return blender(),validate_checks,'application/x-blender',SOURCES

def source_hashes(sources):
    from .runtime import file_hash
    return {n:file_hash(Path(__file__).parent/n) for n in sources}

def binding(rt,spec):
    from .runtime import file_hash
    from task_relay.host_evidence import application_signature
    spec=c.assignment(spec)
    app,validate_checks,media,sources=profile(spec)
    if not app['available']:raise ValueError(app['blocker'])
    inputs=[]
    fields={media:'scene_sha256','text/x-python':'script_sha256','application/json':'checks_sha256'}
    for item in spec['inputs']:
        artifact=rt.artifact(item['artifact'])
        if file_hash(artifact['blob'])!=artifact['sha256']:raise ValueError('Host-code input changed')
        field=fields.get(item['media_type'])
        if field and artifact['sha256']!=spec['execution']['parameters'][field]:raise ValueError('Host-code input hash does not match the proposed script/scene/checks')
        if item['media_type']=='application/json':
            checks=validate_checks(json.loads(Path(artifact['blob']).read_text()))
            if media=='application/vnd.rhino' and (checks['mode']=='edit')!=(spec['execution']['parameters']['scene_sha256'] is not None):
                raise ValueError('Rhino checks mode does not match selected source')
        if item['media_type']=='text/x-python':
            if artifact['bytes']>100000:raise ValueError('Editing script exceeds 100 KB')
            # Rhino 7 syntax is compiled by its exact IronPython runtime during
            # the read-only baseline phase, before any modeling script executes.
            if media!='application/vnd.rhino' or app.get('major',8)!=7:
                compile(Path(artifact['blob']).read_text(),item['path'],'exec')
        inputs.append({'artifact':artifact['id'],'sha256':artifact['sha256'],'path':item['path']})
    extra={'rhino_runtime':{'major':app.get('major',8),'version':app.get('version')}} if media=='application/vnd.rhino' else {}
    return {**extra,'assignment_digest':c.digest(spec),'assignment':spec,'inputs':inputs,'application_signature':application_signature(app['executable']),
            'runtime_sources':source_hashes(sources),
            'permissions':'unrestricted_host','workspace_policy':'Fresh attempt workspace; source copies retained; no OS isolation.'}

def authorize(rt,run,tid,receipt):
    if not rt.db.in_transaction:raise ValueError('Host-code approval must commit with its user decision')
    task=rt.task(run,tid);spec=rt.spec(task)
    if not required(spec) or task['attempts'] or task['status']!='queued':raise ValueError('Host-code approval needs an unstarted exact assignment')
    if not isinstance(receipt,dict) or not receipt.get('source'):raise ValueError('Missing explicit user decision receipt')
    value={'binding':binding(rt,spec),'decision':receipt}
    rt.event(run,tid,None,'host_code_authorized',value)
    return value

def approved(rt,run,tid,spec):
    row=rt.db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND kind='host_code_authorized' ORDER BY id DESC LIMIT 1",(run,tid)).fetchone()
    if not row:raise ValueError('Exact-script host approval is required before host Python can launch')
    value=json.loads(row['data'])
    if value['binding']!=binding(rt,spec):raise ValueError('Script, inputs, assignment, application or implementation changed after host approval')
    return value

def verify_frozen(frozen):
    from .runtime import file_hash
    from task_relay.host_evidence import application_signature
    grant=frozen.get('host_code_authorization',{}).get('binding')
    if not grant or grant.get('permissions')!='unrestricted_host':raise ValueError('Missing exact-script host authorization')
    app,_,_,sources=profile(frozen)
    if not app['available']:raise ValueError(app['blocker'])
    if grant['application_signature']!=application_signature(app['executable']):raise ValueError('Application changed after approval')
    if frozen['execution']['capability']=='rhino.run_python' and grant.get('rhino_runtime')!={'major':app.get('major',8),'version':app.get('version')}:
        raise ValueError('Rhino runtime changed after approval')
    if grant['runtime_sources']!=source_hashes(sources):raise ValueError('Host-code implementation changed after approval')
    if grant['inputs']!=[{k:i[k] for k in ('artifact','sha256','path')} for i in frozen['inputs']]:raise ValueError('Host-code inputs changed after approval')
    if grant['assignment_digest']!=frozen.get('authorized_assignment_digest'):raise ValueError('Host-code assignment approval mismatch')
    actual={k:frozen.get(k) for k in grant['assignment']}
    actual['inputs']=[{k:v for k,v in i.items() if k!='sha256'} for i in frozen['inputs']]
    if c.digest(actual)!=grant['assignment_digest']:raise ValueError('Frozen assignment changed after approval')
