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


def run(executable, script, request_path, timeout, platform):
    """Stay in the supervisor process group so its cancellation owns Rhino too.

    A PID handshake in the fixed worker rejects startup forwarding. Durable intent
    is the caller's responsibility. Only this newly spawned process is terminated.
    """
    from orchestrator.workers import atomic
    request_path = Path(request_path)
    request = json.loads(request_path.read_text())
    argv = command(executable, script, platform, request.get('rhino_major',8))
    log = request_path.with_suffix('.log')
    start = time.monotonic()
    result = dict(command=argv, timeout=False, returncode=None, worker=None)
    with log.open('xb') as stream:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                   cwd=request_path.parent)
        result['pid'] = process.pid
        try:
            atomic(request_path.with_suffix('.owner.json'), {'pid': process.pid, 'token': request['token']})
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            result['timeout'] = True
            process.kill()
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill();process.wait(timeout=5)
        result['returncode'] = process.returncode
    reply = request_path.with_suffix('.result.json')
    if reply.is_file() and not reply.is_symlink() and reply.stat().st_size <= 200000:
        try:
            value = json.loads(reply.read_text())
            if value.get('pid') == process.pid and value.get('token') == request['token'] and value.get('mode') == request['mode']:
                result['worker'] = value
        except (ValueError, OSError):pass
    with log.open('rb') as stream:
        stream.seek(max(0, log.stat().st_size-64000))
        result['log_tail'] = stream.read(64000).decode('utf-8', 'replace')
    result.update(log_bytes=log.stat().st_size, elapsed_seconds=time.monotonic()-start)
    result['passed'] = not result['timeout'] and result['returncode'] == 0 and bool(result['worker'] and result['worker'].get('passed') is True)
    return result
