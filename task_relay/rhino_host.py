"""macOS Rhino process adapter; never sends commands to an existing application."""
import json
import os
from pathlib import Path
import subprocess
import time


def shutdown_script(major, platform):
    """Owned-worker exit without Mono/C++ finalizers or save dialogs.

    Artifacts and the result receipt must be closed before invoking this code.
    The bootstrap passes the function only after verifying process ownership.
    """
    from .host import UnsupportedHost
    if platform != 'darwin':raise UnsupportedHost('Rhino shutdown requires the macOS adapter')
    if major == 7:
        return ('def relay_exit(code):\n'
                '    import ctypes\n'
                '    native_exit = ctypes.CDLL("/usr/lib/libSystem.B.dylib")._exit\n'
                '    native_exit.argtypes = [ctypes.c_int]\n'
                '    native_exit.restype = None\n'
                '    native_exit(code)\n')
    if major != 8:raise ValueError('Unsupported Rhino runtime version')
    # Rhino 8's managed shutdown can abort with "Pure virtual function called"
    # after a successful receipt. CPython provides a native exit directly.
    return 'def relay_exit(code):\n    import os\n    os._exit(code)\n'


def command(executable, script, platform, major=8):
    from .host import UnsupportedHost
    if platform != 'darwin':raise UnsupportedHost('Direct Rhino execution currently requires the macOS adapter')
    path = str(Path(script).resolve())
    if any(c in path for c in ('"', '\n', '\r')):raise ValueError('Unsupported Rhino script path')
    if major not in (7,8):raise ValueError('Unsupported Rhino runtime version')
    macro = '_-RunPythonScript ' if major == 7 else '_-ScriptEditor _Run '
    return [executable, '-runscript', macro + '"' + path + '"']


STARTUP_SECONDS = 60


def running_instances(executable, platform):
    """Inspect only the selected native executable; never attach to or close it."""
    from .host import UnsupportedHost
    if platform != 'darwin':raise UnsupportedHost('Rhino process inspection requires macOS')
    try:
        result=subprocess.run(['/bin/ps','-axo','pid=,comm='],capture_output=True,text=True,timeout=5,check=True)
    except (OSError,subprocess.SubprocessError) as exc:
        raise RuntimeError('Cannot check whether the selected Rhino is already running; no worker was launched.') from exc
    selected=Path(executable).resolve()
    matches=[]
    for line in result.stdout.splitlines():
        fields=line.strip().split(None,1)
        if len(fields)==2 and fields[0].isdigit() and fields[1].startswith('/') and Path(fields[1]).resolve()==selected:
            matches.append(int(fields[0]))
    return matches


def _reply(path, pid, request):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>200000:return None
    try:
        value=json.loads(path.read_text())
        if isinstance(value,dict) and value.get('pid')==pid and value.get('token')==request['token'] and value.get('mode')==request['mode']:
            return value
    except (ValueError,OSError):pass
    return None


def run(executable, script, request_path, timeout, platform):
    """Launch one owned process with separate startup and task time bounds."""
    from orchestrator.workers import atomic
    request_path=Path(request_path)
    request=json.loads(request_path.read_text())
    argv=command(executable,script,platform,request.get('rhino_major',8))
    existing=running_instances(executable,platform)
    if existing:
        return dict(command=argv,passed=False,worker=None,returncode=None,timeout=False,
                    launched=False,existing_pids=existing,error_code='rhino_already_running',
                    error='The selected Rhino is already running. Save your work and quit that Rhino app, then request recovery. Relay did not launch another instance or run the script.')
    log=request_path.with_suffix('.log')
    start=time.monotonic();deadline=start+timeout;startup_deadline=min(deadline,start+STARTUP_SECONDS)
    result=dict(command=argv,timeout=False,returncode=None,worker=None,launched=True,startup_received=False)
    with log.open('xb') as stream:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,cwd=request_path.parent)
        result['pid']=process.pid
        try:
            atomic(request_path.with_suffix('.owner.json'),{'pid':process.pid,'token':request['token']})
            while True:
                if not result['startup_received']:
                    result['startup_received']=_reply(request_path.with_suffix('.started.json'),process.pid,request) is not None
                now=time.monotonic()
                wait_until=deadline if result['startup_received'] else startup_deadline
                if now>=wait_until:
                    result['timeout']=True
                    if not result['startup_received'] and startup_deadline<deadline:
                        result.update(error_code='rhino_startup_timeout',error='Rhino did not confirm worker startup within '+str(STARTUP_SECONDS)+' seconds. Check startup or license dialogs. Only the new Relay process was stopped; no automatic replay.')
                    else:result.update(error_code='rhino_task_timeout',error='Rhino exceeded the approved task time limit; only the new Relay process was stopped.')
                    process.kill();process.wait(timeout=5);break
                try:
                    process.wait(timeout=min(1,wait_until-now));break
                except subprocess.TimeoutExpired:continue
        finally:
            if process.poll() is None:
                process.kill();process.wait(timeout=5)
        result['returncode']=process.returncode
    result['worker']=_reply(request_path.with_suffix('.result.json'),process.pid,request)
    if result['worker'] is not None:result['startup_received']=True
    if result['worker'] is None and not result.get('error'):
        result.update(error_code='rhino_missing_response',error='Rhino exited without a matching worker response. Check startup or license dialogs before requesting recovery; no automatic replay.')
    with log.open('rb') as stream:
        stream.seek(max(0,log.stat().st_size-64000))
        result['log_tail']=stream.read(64000).decode('utf-8','replace')
    result.update(log_bytes=log.stat().st_size,elapsed_seconds=time.monotonic()-start)
    result['passed']=not result['timeout'] and result['returncode']==0 and bool(result['worker'] and result['worker'].get('passed') is True)
    return result
