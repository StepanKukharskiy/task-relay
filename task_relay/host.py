"""Host mechanisms selected at use time; importing core code needs no native API."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


class UnsupportedHost(RuntimeError):
    pass


class Host:
    def __init__(self, platform=None):
        self.platform = sys.platform if platform is None else platform

    def require_posix(self, operation):
        if self.platform not in ('darwin', 'linux'):
            raise UnsupportedHost(operation+' requires a qualified native adapter on '+self.platform)

    def require_macos(self, operation):
        if self.platform != 'darwin':
            raise UnsupportedHost(operation+' is available only through the macOS adapter')

    def user_data(self):
        # O10's neutral default remains stable; installers may supply overrides.
        return Path.home()/'.task-relay'

    def environment_python(self, environment):
        return Path(environment)/('Scripts/python.exe' if self.platform=='win32' else 'bin/python')

    def browser_python(self, install, data):
        self.require_posix('Browser setup desktop session')
        import importlib.util
        configured=os.environ.get('TASK_RELAY_BROWSER_PYTHON')
        if configured:
            path=Path(configured).expanduser()
            if not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK):
                raise UnsupportedHost('Configured browser runtime is not an executable absolute file')
            return str(path)
        if importlib.util.find_spec('playwright') is not None:return sys.executable
        for folder in (Path(data)/'browser-venv',Path(install)/'.venv-browser'):
            path=self.environment_python(folder)
            if path.is_file() and os.access(path,os.X_OK):return str(path)
        raise UnsupportedHost('The optional browser component is unavailable on this host')

    def codex(self, explicit=None):
        configured = explicit or os.environ.get('TASK_RELAY_CODEX')
        if configured:
            path=Path(configured).expanduser()
            if not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK):
                raise UnsupportedHost('Configured Codex worker is not an executable absolute file')
            return str(path)
        found=shutil.which('codex')
        if found:return found
        if self.platform=='darwin':
            for app in ('ChatGPT','Codex'):
                path=Path('/Applications')/(app+'.app')/'Contents/Resources/codex'
                if path.is_file() and os.access(path,os.X_OK):return str(path)
        raise UnsupportedHost('Codex worker unavailable; configure TASK_RELAY_CODEX or install it on PATH')

    def codex_projects(self, codex_dir=None):
        """Read saved local project roots; never edit Codex's private UI state."""
        import json
        path = Path(codex_dir or Path.home()/'.codex')/'.codex-global-state.json'
        if not path.exists():
            return []
        if path.stat().st_size > 10_000_000:
            raise ValueError('Codex project metadata exceeds the read limit.')
        data = json.loads(path.read_text())
        result = []
        for project in data.get('local-projects', {}).values():
            for root in project.get('rootPaths', []):
                if isinstance(root, str):
                    result.append({'cwd': root, 'name': project.get('name') or Path(root).name})
        for root in data.get('electron-saved-workspace-roots', []):
            if isinstance(root, str):
                result.append({'cwd': root, 'name': Path(root).name})
        return result

    def lock(self, stream):
        self.require_posix('Exclusive service locking')
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def spawn(self, command, *, popen=None, **kwargs):
        self.require_posix('Worker process-tree ownership')
        return (popen or subprocess.Popen)(command, start_new_session=True, **kwargs)

    def signal_tree(self, process, force=False):
        self.require_posix('Worker process-tree cancellation')
        try:os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:pass

    def stop_tree(self, process, timeout=5):
        self.require_posix('Worker process-tree cancellation')
        self.signal_tree(process)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            process.poll()  # reap the group leader; descendants may still exist
            try:os.killpg(process.pid,0)
            except ProcessLookupError:break
            time.sleep(.02)
        self.signal_tree(process,force=True)
        process.wait(timeout=max(timeout,1))

    def process_matches(self, pid, token):
        self.require_posix('Worker recovery inspection')
        if type(pid) is not int or pid<2:return False
        result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
        return result.returncode==0 and token in result.stdout

    def launchctl(self, arguments, **kwargs):
        self.require_macos('Login service management')
        return subprocess.run(['launchctl',*arguments],**kwargs)

    def telegram_service(self, action, **kwargs):
        if self.platform=='linux':
            from . import host_linux
            return getattr(host_linux,action)(**kwargs)
        self.require_macos('Telegram login service management')
        from . import host_macos
        return getattr(host_macos,action)(**kwargs)

    def desktop_socket(self):
        self.require_posix('Codex desktop Unix IPC')
        import socket
        if not hasattr(socket,'AF_UNIX'):
            raise UnsupportedHost('Codex desktop Unix IPC is unavailable on this host')
        return socket.socket(socket.AF_UNIX)

    def open_codex(self, task_id, error):
        self.require_macos('Codex desktop task opening')
        app=next((p for p in (Path('/Applications/ChatGPT.app'),Path('/Applications/Codex.app')) if p.is_dir()),None)
        if app is None:raise error('Cannot locate the Codex desktop application')
        # An inactive window may show the task without acquiring its stream.
        # This fallback runs only when no desktop owner was found; activate the
        # app so readiness can be verified before submitting the user's turn.
        result=subprocess.run(['/usr/bin/open','-a',str(app),'codex://threads/'+task_id],capture_output=True,timeout=5)
        if result.returncode:raise error('macOS could not open the saved Codex task')

    def describe(self):
        return {'platform':self.platform,'services':('launchd' if self.platform=='darwin' else
                'systemd user manager when available; otherwise foreground CLI' if self.platform=='linux' else 'unavailable; native service adapter required'),
                'processes':'POSIX session/process group' if self.platform in ('darwin','linux') else 'unavailable; native process-tree adapter required',
                'filesystem':'descriptor-relative no-follow grants' if self.platform in ('darwin','linux') else 'unavailable; native junction/reparse-point enforcement required',
                'native_qualification':'macOS only; Linux/Windows qualification remains O12'}


def support_hashes():
    import hashlib
    return {name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('host.py','filesystem.py','credentials.py')}


def verify_support(frozen):
    if 'host_support' in frozen and frozen['host_support']!=support_hashes():
        raise ValueError('Host/access implementation changed after assignment was frozen')


HOST=Host()


def main():
    import json
    print(json.dumps(HOST.describe(),indent=2))


if __name__ == '__main__':
    main()
