"""Read execution evidence by environment; never promote an agent report to host health."""
import hashlib
import json
from pathlib import Path
import time

MAX_AGE=86400


def application_signature(executable):
    path=Path(executable);stat=path.stat()
    return {'path':str(path.resolve()),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,
            'inode':stat.st_ino,'device':stat.st_dev}


def observation(data,source,digest):
    if (not isinstance(data,dict) or data.get('host_execution') is not True
            or data.get('capability') not in ('blender.startup','blender.scene','blender.mesh_scene')):
        raise ValueError('Not a registered Blender host receipt')
    runs=data.get('runs')
    if not isinstance(runs,list) or not 1<=len(runs)<=2:raise ValueError('Missing bounded process receipts')
    def passed(r,marker):
        return isinstance(r,dict) and r.get('returncode')==0 and r.get('timeout') is False and marker in r.get('stdout','')
    first_marker='BLENDER_STARTUP_OK' if data['capability']=='blender.startup' else 'RELAY_SCENE_SAVED'
    startup=passed(runs[0],first_marker)
    completed=startup if data['capability']=='blender.startup' else startup and len(runs)==2 and passed(runs[1],'RELAY_SCENE_VERIFIED_RENDERED')
    return {'environment':'registered_host','capability':data['capability'],
            'startup_status':'passed' if startup else 'failed','operation_status':'passed' if completed else 'failed',
            'recorded_at':data.get('recorded_at',0),'application_signature':data.get('application_signature'),
            'runtime_sources':data.get('runtime_sources',{}),'source':str(source),'sha256':digest}


def read_observation(path,expected=None):
    from orchestrator.runtime import safe_file
    path=Path(path)
    path=safe_file(Path(path.anchor),str(path.relative_to(path.anchor)))
    if path.stat().st_size>200000:raise ValueError('Host receipt is too large')
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if expected and digest!=expected:raise ValueError('Host receipt changed')
    return observation(json.loads(raw),path,digest)


def record_check(state,path):
    """Maintenance-only import of an actual controlled host receipt. No worker launch."""
    item=read_observation(Path(path).resolve())
    item['evidence_kind']='Controlled host check; not a deployed conversation or user acceptance'
    prior=state.get('host-checks:blender',[])
    if not any(i['sha256']==item['sha256'] for i in prior):
        state.put('host-checks:blender',(prior+[item])[-10:])
    return item


def environments(state,app):
    from orchestrator.runtime import failure_detail,file_hash
    shell=[];host=[]
    for row in state.db.execute("SELECT id,run,state,error,frozen,receipt FROM production_attempts ORDER BY rowid DESC LIMIT 50"):
        frozen=json.loads(row['frozen']);execution=frozen.get('execution',{})
        if execution.get('capability','').startswith('blender.'):
            a=state.db.execute("SELECT blob,sha256 FROM production_artifacts WHERE attempt=? AND path='delivery/execution.json'",(row['id'],)).fetchone()
            if a:
                try:item=read_observation(a['blob'],a['sha256'])
                except (OSError,ValueError,TypeError):continue
                item.update(run=row['run'],attempt=row['id'],evidence_kind='Registered production execution receipt')
                host.append(item)
        elif row['state']=='blocked':
            detail=failure_detail(state.db,row) or ''
            if 'blender' in detail.lower() and len(shell)<3:
                shell.append({'environment':'agent_shell','run':row['run'],'attempt':row['id'],
                    'backend':frozen.get('backend'),'worker_report':detail[:1600],
                    'evidence_kind':'Historical agent report; does not establish registered host status'})
    # Runtime-only fixtures need not have Relay's kv table.
    for saved in getattr(state,'get',lambda *_:[])('host-checks:blender',[]):
        try:item=read_observation(saved['source'],saved['sha256'])
        except (OSError,ValueError,TypeError):continue
        item['evidence_kind']=saved['evidence_kind'];host.append(item)
    try:signature=application_signature(app['executable']) if app['available'] else None
    except OSError:signature=None
    runtime={name:file_hash(Path(__file__).resolve().parents[1]/'orchestrator'/name) for name in ('blender_host.py','blender_scene.py')}
    host.sort(key=lambda i:i['recorded_at'],reverse=True)
    for item in host:
        item['current_environment_match']=bool(signature and item['application_signature']==signature
            and item['runtime_sources']==runtime and 0<=time.time()-item['recorded_at']<=MAX_AGE)
    current=next((h for h in host if h['current_environment_match']),None)
    return {'agent_shell':{'historical_failures':shell,'applies_to':'Agent shell only; never evidence of registered host failure'},
            'registered_host':{'startup_status':current['startup_status'] if current else 'unverified',
                'latest_check':current,'recent_checks':host[:5],
                'meaning':'A host check is environment-specific evidence, not a guarantee for future jobs or Telegram delivery.'}}
