"""Service-owned exact-code authorization receipts; never populated by a planner."""
import json
from pathlib import Path
from . import contracts as c
from .host_script import validate_script_bytes
from .native_apps import SCRIPT_OPERATIONS, profile as app_profile

CAPABILITY='blender.run_python'
SOURCES=('host_code.py','host_script.py','blender_edit.py','blender_edit_worker.py','blender_snapshot.py','execution.py','step_runner.py')

def required(spec):return spec.get('execution',{}).get('capability') in SCRIPT_OPERATIONS

def profile(spec):
    adapter=app_profile(spec['execution']['capability'])
    return adapter.discover(),adapter.validate_checks,adapter.media,adapter.sources

def source_hashes(sources):
    from .runtime import file_hash
    return {n:file_hash(Path(__file__).parent/n) for n in sources}

def binding(rt,spec):
    from .runtime import file_hash
    from task_relay.host_evidence import application_signature
    spec=c.assignment(spec)
    app,validate_checks,media,sources=profile(spec)
    adapter=app_profile(spec['execution']['capability'])
    if not app['available']:raise ValueError(app['blocker'])
    inputs=[]
    fields={media:'scene_sha256',adapter.script_media:'script_sha256','application/json':'checks_sha256'}
    for item in spec['inputs']:
        artifact=rt.artifact(item['artifact'])
        if file_hash(artifact['blob'])!=artifact['sha256']:raise ValueError('Host-code input changed')
        field=fields.get(item['media_type'])
        if field and artifact['sha256']!=spec['execution']['parameters'][field]:raise ValueError('Host-code input hash does not match the proposed script/scene/checks')
        if item['media_type']=='application/json':
            checks=validate_checks(json.loads(Path(artifact['blob']).read_text()))
            if adapter.new_model and (checks['mode']=='edit')!=(spec['execution']['parameters']['scene_sha256'] is not None):
                raise ValueError(adapter.name+' checks mode does not match selected source')
        if item['media_type']==adapter.script_media:
            adapter.validate_script(Path(artifact['blob']).read_bytes(),app)
        inputs.append({'artifact':artifact['id'],'sha256':artifact['sha256'],'path':item['path']})
    extra={'rhino_runtime':{'major':app.get('major',8),'version':app.get('version')}} if adapter.name=='rhino' else {}
    if adapter.name=='rhino3dm':extra['library_runtime']=app['library_runtime']
    if adapter.name=='sketchup':extra['sketchup_runtime']={'version':app.get('version')}
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
    if not row:raise ValueError('Exact-script host approval is required before host code can launch')
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
    if frozen['execution']['capability']=='rhino3dm.run_python' and grant.get('library_runtime')!=app['library_runtime']:
        raise ValueError('Standalone library/Python runtime changed after approval')
    if frozen['execution']['capability']=='rhino.run_python' and grant.get('rhino_runtime')!={'major':app.get('major',8),'version':app.get('version')}:
        raise ValueError('Rhino runtime changed after approval')
    if frozen['execution']['capability']=='sketchup.run_ruby' and grant.get('sketchup_runtime')!={'version':app.get('version')}:
        raise ValueError('SketchUp runtime changed after approval')
    if grant['runtime_sources']!=source_hashes(sources):raise ValueError('Host-code implementation changed after approval')
    if grant['inputs']!=[{k:i[k] for k in ('artifact','sha256','path')} for i in frozen['inputs']]:raise ValueError('Host-code inputs changed after approval')
    if grant['assignment_digest']!=frozen.get('authorized_assignment_digest'):raise ValueError('Host-code assignment approval mismatch')
    actual={k:frozen.get(k) for k in grant['assignment']}
    actual['inputs']=[{k:v for k,v in i.items() if k!='sha256'} for i in frozen['inputs']]
    if c.digest(actual)!=grant['assignment_digest']:raise ValueError('Frozen assignment changed after approval')
