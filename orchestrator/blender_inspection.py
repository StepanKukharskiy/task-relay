"""Host adapter for version-bound, read-only Blender inventory."""
import json
from pathlib import Path
import subprocess
import time

from .runtime import safe_file,file_hash
from .workers import atomic


def execute(frozen,control,documents):
    from task_relay.host_apps import blender
    from task_relay.host_evidence import application_signature
    app=blender()
    if not app['available']:raise ValueError(app['blocker'])
    control=Path(control);workspace=Path(frozen['workspace'])
    for name in ('blender_inspection.py','blender_inspect.py'):
        if frozen.get('runtime_sources',{}).get(name)!=file_hash(Path(__file__).with_name(name)):
            raise ValueError('Blender inspection implementation changed after dispatch')
    inputs=[i for i in frozen['inputs'] if i['media_type']=='application/x-blender']
    if len(inputs)!=1:raise ValueError('Select exactly one Blender scene version for inspection')
    item=inputs[0];source=safe_file(workspace,item['path'])
    if file_hash(source)!=item['sha256']:raise ValueError('Selected scene copy changed')
    output=workspace/'delivery'
    if output.exists() or output.is_symlink():raise ValueError('Inspection outputs already exist; no replacement or replay')
    request={'assignment':frozen['assignment_id'],'source_artifact':item['artifact'],'source_sha256':item['sha256'],
        'executable':app['executable'],'application_signature':application_signature(app['executable']),
        'scope':'Host read-only inspection; embedded auto-execution disabled; linked libraries may resolve on the host.',
        'created':time.time()}
    with (control/'inspection-intent.json').open('x') as stream:json.dump(request,stream)
    output.mkdir()
    command=[app['executable'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
             '--python',str(Path(__file__).with_name('blender_inspect.py')),'--',str(source),str(output/'inspection.json')]
    start=time.time()
    try:
        r=subprocess.run(command,cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,
                         timeout=max(1,frozen['limits']['seconds']-5))
        receipt={**request,'command':command,'returncode':r.returncode,'timeout':False,
            'stdout':r.stdout.decode('utf-8','replace')[-64000:],'stderr':r.stderr.decode('utf-8','replace')[-64000:],
            'stdout_bytes':len(r.stdout),'stderr_bytes':len(r.stderr)}
    except subprocess.TimeoutExpired as exc:
        receipt={**request,'command':command,'returncode':None,'timeout':True,
            'stdout':(exc.stdout or b'').decode('utf-8','replace')[-64000:],
            'stderr':(exc.stderr or b'').decode('utf-8','replace')[-64000:]}
    receipt['elapsed_seconds']=time.time()-start
    receipt['source_unchanged']=file_hash(source)==item['sha256']
    passed=(receipt['returncode']==0 and 'RELAY_INSPECTION_WRITTEN' in receipt['stdout'] and receipt['source_unchanged'])
    if passed:
        try:
            path=safe_file(workspace,'delivery/inspection.json')
            if path.stat().st_size>1800000:raise ValueError('Inspection output exceeds the limit')
            inventory=json.loads(path.read_text())
            passed=isinstance(inventory,dict) and inventory.get('auto_scripts_enabled') is False and isinstance(inventory.get('objects'),list)
            receipt['inventory_sha256']=file_hash(path)
        except (ValueError,OSError) as exc:
            passed=False
            receipt['validation_error']=str(exc)
    receipt['streams_may_be_truncated']=receipt['timeout'] or any(receipt.get(k,0)>64000 for k in ('stdout_bytes','stderr_bytes'))
    atomic(output/'execution.json',receipt)
    summary='Selected Blender scene inspected without changing its input copy.' if passed else 'Blender inspection failed; see execution.json. No automatic retry.'
    details={'outcome':'completed' if passed else 'failed','execution':frozen['execution'],'summary':summary,'usage':{},
        'source_sha256':item['sha256'],'source_artifact':item['artifact']}
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',{'assignment_id':frozen['assignment_id'],'summary':summary,
        'decision':'delivered' if passed else 'blocked','instruction':'',
        'checks':[{'criterion':1,'passed':passed,'evidence':'delivery/inspection.json and delivery/execution.json'}]})
    return details
