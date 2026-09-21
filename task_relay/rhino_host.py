"""macOS Rhino transport: owned process or explicitly targeted Rhino 8 script server."""
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
CONNECTION_SECONDS = 20


def script_connection(executable, existing, platform):
    """Resolve one exact running application; never choose an unrelated Rhino."""
    from .host import UnsupportedHost
    if platform != 'darwin':raise UnsupportedHost('Shared Rhino sessions currently require macOS')
    cli=Path(executable).resolve().parents[1]/'Resources/bin/rhinocode'
    if not cli.is_file():
        raise ValueError('This Rhino version has no script connection. Use Rhino 8.11 or newer, or save and quit this Rhino session before Start.')
    try:
        reply=subprocess.run([str(cli),'list','--json'],stdin=subprocess.DEVNULL,
            capture_output=True,text=True,timeout=CONNECTION_SECONDS,check=True)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'Rhino connection discovery did not finish within {CONNECTION_SECONDS} seconds. '
            'This does not establish that its script server is off. Check Rhino for a busy operation or dialog, '
            'then continue again. No script was submitted and no new execution attempt was spent.') from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f'Rhino connection discovery failed (exit {exc.returncode}). '
            'Check the Rhino command-line installation before continuing. No script was submitted.') from exc
    except OSError as exc:
        raise ValueError('Rhino connection discovery could not start ('+type(exc).__name__+'). '
            'Check the selected Rhino installation before continuing. No script was submitted.') from exc
    try:
        entries=json.loads(reply.stdout)
        if not isinstance(entries,list):raise ValueError('Expected a connection list')
    except (ValueError,TypeError) as exc:
        raise ValueError('Rhino connection discovery returned an unreadable connection list. '
            'No script was submitted; inspect the Rhino command-line installation.') from exc
    matches=[r for r in entries if isinstance(r,dict) and type(r.get('processId')) is int
             and r['processId'] in existing and str(r.get('processVersion','')).startswith('8.')
             and r.get('pipeId')=='rhinocode_remotepipe_'+str(r['processId'])]
    if len(existing)!=1 or len(matches)!=1:
        raise ValueError('Relay needs one connected Rhino 8 session. In the selected Rhino run StartScriptServer, then press Start again. No new execution attempt was spent.')
    return dict(cli=str(cli),pid=matches[0]['processId'],pipe=matches[0]['pipeId'])


def require_available(executable,next_action='press Start again'):
    """Preflight transport before Start commits a run; dispatch rechecks it."""
    import sys
    existing=running_instances(executable,sys.platform)
    if existing:
        try:script_connection(executable,existing,sys.platform)
        except ValueError as exc:raise ValueError(str(exc).replace('press Start again',next_action)) from exc


def require_recovery_ready(executable, prior):
    """Host-specific readiness proof for the shared pre-execution recovery policy."""
    import sys
    existing=running_instances(executable,sys.platform)
    if prior.get('launched'):
        if prior['pid'] in existing:
            raise ValueError('The previous Rhino process is still present; inspect its startup before recovery.')
        # A failed owned start must be resolved before proposing another attempt.
        script_connection(executable,existing,sys.platform)
    else:
        require_available(executable,'continue this production again')


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
    """Select the verified transport; an existing Rhino is never process-owned."""
    from orchestrator.workers import atomic
    request_path=Path(request_path)
    request=json.loads(request_path.read_text())
    argv=command(executable,script,platform,request.get('rhino_major',8))
    existing=running_instances(executable,platform)
    if existing:
        connection=script_connection(executable,existing,platform)
        return run_shared(connection,script,request_path,request,timeout)
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
                        result.update(error_code='rhino_startup_timeout',error='Rhino did not confirm worker startup within '+str(STARTUP_SECONDS)+' seconds. Open the selected Rhino and resolve any plug-in, startup or license dialog, then continue. Only the new Relay process was stopped; no automatic replay.')
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


def run_shared(connection,script,request_path,request,timeout):
    """A client timeout never kills the user's Rhino or allows an uncertain replay."""
    import fcntl
    import tempfile
    from orchestrator.workers import atomic
    folder=Path(tempfile.gettempdir())/('task-relay-rhino-'+str(os.getuid()))
    folder.mkdir(mode=0o700,exist_ok=True)
    pending=folder/(str(connection['pid'])+'.json')
    with (folder/(str(connection['pid'])+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another Relay operation is using this Rhino session. No script was submitted.')
        if pending.exists():
            previous=json.loads(pending.read_text())
            terminal=_reply(Path(previous['request']).with_suffix('.result.json'),connection['pid'],previous)
            if terminal is None:
                raise ValueError('An earlier Rhino script has no completion receipt. Inspect that attempt before continuing; no script was resubmitted and Rhino was left open.')
        atomic(pending,dict(request=str(request_path),token=request['token'],mode=request['mode']))
        atomic(request_path.with_suffix('.owner.json'),dict(pid=connection['pid'],token=request['token'],shared=True))
        argv=[connection['cli'],'--rhino',connection['pipe'],'script',str(script)]
        result=dict(command=argv,transport='shared_document',pid=connection['pid'],launched=False,
                    submitted=False,timeout=False,worker=None,returncode=None)
        start=time.monotonic()
        try:
            with request_path.with_suffix('.log').open('xb') as log:
                process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,cwd=request_path.parent)
                result['submitted']=True
                try:
                    # RhinoCode acknowledges submission before the script finishes.
                    # Only the worker's identity-bound receipt establishes completion.
                    deadline=start+timeout
                    while time.monotonic()<deadline:
                        if _reply(request_path.with_suffix('.result.json'),connection['pid'],request) is not None:break
                        if process.poll() not in (None,0):break
                        time.sleep(min(.1,max(0,deadline-time.monotonic())))
                    if _reply(request_path.with_suffix('.result.json'),connection['pid'],request) is None and time.monotonic()>=deadline:
                        result.update(timeout=True,error_code='rhino_shared_timeout',
                            error='The Rhino script did not confirm completion in time. Rhino was left open; execution may still be running. Inspect this attempt before continuing; no automatic replay.')
                    if process.poll() is None:
                        process.kill() # CLI client only; never Rhino.
                    process.wait(timeout=5)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
                result['returncode']=process.returncode
        except OSError:
            if not result['submitted']:pending.unlink()
            raise
        result['worker']=_reply(request_path.with_suffix('.result.json'),connection['pid'],request)
        if result['worker'] is not None:pending.unlink()
        elif not result.get('error'):
            result.update(error_code='rhino_shared_uncertain',error='Rhino returned without a matching completion receipt. Rhino was left open; inspect this attempt before continuing. No automatic replay.')
        result['startup_received']=_reply(request_path.with_suffix('.started.json'),connection['pid'],request) is not None
        result['elapsed_seconds']=time.monotonic()-start
        result['passed']=not result['timeout'] and result['returncode']==0 and bool(result['worker'] and result['worker'].get('passed') is True)
        return result
