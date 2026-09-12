"""Exact-authorized host Python candidate editing and independent verification."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from .runtime import safe_file,file_hash
from .workers import atomic
from . import host_code

CHECKS_DESCRIPTION={
    'changed_objects':'1–100 existing object names allowed to change; object additions/removals and collection/frame changes are outside v1',
    'preserve_other_objects':'true','preserve_cameras':'true','preserve_materials':'true',
    'expected_dimensions':'Map of changed object name to expected [x,y,z] dimensions, at least one; tolerance max(0.0001, abs(expected)*0.0001)',
    'preview':{'camera':'Existing camera name, preserved','resolution':'[width,height], each 64–1024','samples':'1–16; CPU Cycles'},
    'scope':'Self-contained scenes only: packed/generated assets; no library imports, animation setup or UI. Checks are scoped, not full Blender semantic equivalence.'}

def validate_checks(value):
    if not isinstance(value,dict) or set(value)!={'changed_objects','preserve_other_objects','preserve_cameras','preserve_materials','expected_dimensions','preview'}:
        raise ValueError('Use the exact Blender edit checks schema')
    names=value['changed_objects']
    if not isinstance(names,list) or not 1<=len(names)<=100 or any(not isinstance(n,str) or not 1<=len(n)<=200 for n in names) or len(names)!=len(set(names)):
        raise ValueError('Specify unique existing objects allowed to change')
    if any(value[k] is not True for k in ('preserve_other_objects','preserve_cameras','preserve_materials')):
        raise ValueError('B02 v1 preserves other objects, cameras and materials')
    expected=value['expected_dimensions']
    if not isinstance(expected,dict) or not expected or set(expected)-set(names):raise ValueError('Specify expected dimensions for changed objects')
    for dims in expected.values():
        if not isinstance(dims,list) or len(dims)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=100000 for n in dims):
            raise ValueError('Invalid expected dimensions')
    p=value['preview']
    if not isinstance(p,dict) or set(p)!={'camera','resolution','samples'} or not isinstance(p['camera'],str) or not 1<=len(p['camera'])<=200:
        raise ValueError('Choose an exact preview camera')
    if not isinstance(p['resolution'],list) or len(p['resolution'])!=2 or any(type(n) is not int or not 64<=n<=1024 for n in p['resolution']):raise ValueError('Preview dimensions exceed bounds')
    if type(p['samples']) is not int or not 1<=p['samples']<=16:raise ValueError('Preview samples exceed bounds')
    return value

def execute(frozen,control,documents):
    from task_relay.host_apps import blender
    host_code.verify_frozen(frozen)
    workspace=Path(frozen['workspace']);control=Path(control);out=workspace/'delivery'
    if out.exists() or out.is_symlink():raise ValueError('Candidate outputs exist; no replacement or replay')
    paths={i['media_type']:safe_file(workspace,i['path']) for i in frozen['inputs'] if i['media_type'] in ('application/x-blender','text/x-python','application/json')}
    scene=paths['application/x-blender'];script=paths['text/x-python'];contract=paths['application/json']
    validate_checks(json.loads(contract.read_text()))
    receipt={'host_execution':True,'capability':'blender.run_python','authorization':frozen['host_code_authorization'],
             'assignment':frozen['assignment_id'],'run':frozen['run'],'backend':frozen['backend'],
             'input_versions':[{k:i[k] for k in ('artifact','sha256','path')} for i in frozen['inputs']],
             'outputs':frozen['outputs'],'limits':frozen['limits'],'runs':[],
             'scope':'Explicitly approved Python with normal host filesystem/network permissions. No OS isolation. Candidate creation is not user selection.'}
    with (control/'host-code-intent.json').open('x') as f:json.dump(receipt,f)
    out.mkdir();shutil.copyfile(script,out/'edit.py')
    deadline=time.monotonic()+max(1,frozen['limits']['seconds']-5)
    passed=True;baseline_hash=None
    for mode in ('before','edit','verify'):
        command=[blender()['executable'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
            '--python',str(Path(__file__).with_name('blender_edit_worker.py')),'--',mode,str(scene),str(script),str(contract),str(out)]
        start=time.monotonic()
        try:
            result=subprocess.run(command,cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,timeout=max(.1,deadline-start))
            r={'mode':mode,'command':command,'returncode':result.returncode,'timeout':False,
               'stdout':result.stdout.decode('utf-8','replace')[-64000:],'stderr':result.stderr.decode('utf-8','replace')[-64000:],
               'stdout_bytes':len(result.stdout),'stderr_bytes':len(result.stderr)}
        except subprocess.TimeoutExpired as exc:
            r={'mode':mode,'command':command,'returncode':None,'timeout':True,
               'stdout':(exc.stdout or b'').decode('utf-8','replace')[-64000:],'stderr':(exc.stderr or b'').decode('utf-8','replace')[-64000:]}
        except OSError as exc:
            r={'mode':mode,'command':command,'returncode':None,'timeout':False,'stdout':'','stderr':str(exc)}
        r['elapsed_seconds']=time.monotonic()-start
        r['streams_may_be_truncated']=r['timeout'] or any(r.get(k,0)>64000 for k in ('stdout_bytes','stderr_bytes'))
        receipt['runs'].append(r)
        try:
            passed=r['returncode']==0 and 'RELAY_EDIT_'+mode.upper()+'_OK' in r['stdout']
            if any(file_hash(safe_file(workspace,i['path']))!=i['sha256'] for i in frozen['inputs']):raise ValueError('Input copy changed')
            if file_hash(out/'edit.py')!=frozen['execution']['parameters']['script_sha256']:raise ValueError('Delivered script changed')
            if passed and mode=='before':baseline_hash=file_hash(safe_file(workspace,'delivery/checks.json'))
            if passed and mode=='edit' and baseline_hash!=file_hash(safe_file(workspace,'delivery/checks.json')):raise ValueError('Script changed baseline verification evidence')
            if sum(p.stat().st_size for p in out.iterdir() if p.is_file())>frozen['limits']['output_bytes']:raise ValueError('Output byte limit exceeded')
            if passed and mode=='verify':
                evidence=json.loads(safe_file(workspace,'delivery/checks.json').read_text())
                if evidence.get('passed') is not True:raise ValueError('Independent checks failed')
                for name in ('before.png','after.png'):
                    if safe_file(workspace,'delivery/'+name).read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid preview')
                if safe_file(workspace,'delivery/candidate.blend').stat().st_size==0:raise ValueError('Empty candidate')
        except (ValueError,OSError) as exc:
            passed=False;receipt['validation_error']=str(exc)
        receipt['recorded_at']=time.time();receipt['passed']=passed
        atomic(out/'execution.json',receipt)
        if not passed:break
    if passed:
        receipt['lineage']={'source_scene_sha256':frozen['execution']['parameters']['scene_sha256'],
            'script_sha256':file_hash(out/'edit.py'),'candidate_sha256':file_hash(out/'candidate.blend'),
            'attempt':frozen['assignment_id'],'selected':False}
        atomic(out/'execution.json',receipt)
    summary='Candidate saved, independently reopened/checked and previewed; awaiting review and selection.' if passed else 'Blender edit failed; see execution.json. Partial files are not accepted and will not be replayed.'
    details={'outcome':'completed' if passed else 'failed','execution':frozen['execution'],'summary':summary,'usage':{}}
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',{'assignment_id':frozen['assignment_id'],'summary':summary,
        'decision':'delivered' if passed else 'blocked','instruction':'',
        'checks':[{'criterion':1,'passed':passed,'evidence':'delivery/checks.json and delivery/execution.json'}]})
    return details
