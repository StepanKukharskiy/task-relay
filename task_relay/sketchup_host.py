"""macOS owned SketchUp launch. No session attachment, shell, or global quit."""
import json
from pathlib import Path
import subprocess
import time

STARTUP_SECONDS=60


def command(executable, script, platform):
    if platform!='darwin':raise ValueError('SketchUp host execution requires macOS')
    if not Path(executable).is_absolute() or not Path(script).is_absolute():raise ValueError('Absolute SketchUp paths required')
    return [str(executable), '-RubyStartup', str(script)]


def running_instances(executable):
    result=subprocess.run(['/bin/ps','-axo','pid=,comm='],capture_output=True,text=True,timeout=5,check=True)
    selected=Path(executable).resolve()
    return [int(parts[0]) for line in result.stdout.splitlines()
            if len(parts:=line.strip().split(None,1))==2 and parts[0].isdigit()
            and parts[1].startswith('/') and Path(parts[1]).resolve()==selected]


def reply(path, pid, request):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>200000:return None
    try:
        value=json.loads(path.read_text())
        if isinstance(value,dict) and value.get('pid')==pid and value.get('token')==request['token'] and value.get('mode')==request['mode']:
            return value
    except (ValueError,OSError):pass
    return None


def run(executable, script, request_path, timeout, platform):
    from .relay_paths import PATHS
    from .app_access import settings_lock
    # Serialize launch checks across attempts/processes, including different
    # projects. A second worker must never race the existing-instance check.
    root=PATHS.data/'sketchup-process-lock'
    with settings_lock(root):
        return _run(executable,script,request_path,timeout,platform)


def _run(executable, script, request_path, timeout, platform):
    from orchestrator.workers import atomic
    request_path=Path(request_path);request=json.loads(request_path.read_text())
    argv=command(executable,script,platform)
    existing=running_instances(executable)
    if existing:
        return dict(passed=False,launched=False,existing_pids=existing,error='SketchUp is already running. Save and quit that version before requesting recovery; no user session was touched.')
    start=time.monotonic();deadline=start+timeout;startup_deadline=min(deadline,start+STARTUP_SECONDS)
    result=dict(command=argv,passed=False,launched=False,timeout=False,worker=None)
    log=request_path.with_suffix('.log')
    with log.open('xb') as stream:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,cwd=request_path.parent)
        result.update(pid=process.pid,launched=True)
        try:
            atomic(request_path.with_suffix('.owner.json'),dict(pid=process.pid,token=request['token']))
            started=False
            while process.poll() is None:
                started=started or reply(request_path.with_suffix('.started.json'),process.pid,request) is not None
                remaining=(deadline if started else startup_deadline)-time.monotonic()
                if remaining<=0:
                    result.update(timeout=True,error='SketchUp '+('task' if started else 'startup')+' timed out; check desktop/license dialogs. Only the owned process was stopped; no replay.')
                    break
                try:process.wait(timeout=min(.25,remaining))
                except subprocess.TimeoutExpired:pass
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
        result['returncode']=process.returncode
    result['worker']=reply(request_path.with_suffix('.result.json'),process.pid,request)
    if result['worker'] is None:result.setdefault('error','SketchUp exited without a matching worker receipt; outcome is unverified, no replay.')
    result['passed']=not result['timeout'] and process.returncode==0 and bool(result['worker'] and result['worker'].get('passed') is True)
    if result['worker'] and not result['passed']:result.setdefault('error',result['worker'].get('error','SketchUp worker failed'))
    with log.open('rb') as stream:
        stream.seek(max(0,log.stat().st_size-64000));result['log_tail']=stream.read(64000).decode('utf-8','replace')
    result.update(log_bytes=log.stat().st_size,elapsed_seconds=time.monotonic()-start)
    return result
