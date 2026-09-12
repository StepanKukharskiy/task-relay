"""macOS login service adapter; imported only after host capability selection."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from .host import HOST

def install(ROOT, DATA, PATHS, read_config, BridgeError):
    read_config()
    path = Path.home() / 'Library/LaunchAgents/com.personal.codex-telegram.plist'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        prior_bytes=path.read_bytes()
        spec = plistlib.loads(prior_bytes)
        if spec.get('WorkingDirectory') != str(ROOT):
            raise BridgeError('A LaunchAgent with this name already exists; it was preserved.')
        from task_relay.relay_paths import resolve
        prior=resolve(spec.get('EnvironmentVariables',{}),ROOT)
        if prior.data!=PATHS.data:
            raise BridgeError('The installed service uses another data root. An explicit migration is required; it was preserved.')
        spec['EnvironmentVariables']={**spec.get('EnvironmentVariables',{}),**PATHS.environment()}
        temporary=path.with_suffix('.plist.tmp')
        temporary.write_bytes(plistlib.dumps(spec));temporary.replace(path)
        # Reload the same installed service with explicit, stable path bindings.
        HOST.launchctl(['bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
        result = HOST.launchctl(['bootstrap', f'gui/{os.getuid()}', str(path)], capture_output=True)
        if result.returncode:
            temporary.write_bytes(prior_bytes);temporary.replace(path)
            restored=HOST.launchctl(['bootstrap',f'gui/{os.getuid()}',str(path)],capture_output=True)
            raise BridgeError('Service reload failed. Prior configuration restored; '+('previous service restarted.' if restored.returncode==0 else 'service restart also failed; use Run.command to troubleshoot.'))
        print('Existing background service restarted.')
        return
    specification = {
        'Label': 'com.personal.codex-telegram',
        'ProgramArguments': [sys.executable, str(ROOT / 'bridge.py'), 'run'],
        'WorkingDirectory': str(ROOT), 'RunAtLoad': True, 'KeepAlive': True,
        'EnvironmentVariables': PATHS.environment(),
        'ThrottleInterval': 15,
        'StandardOutPath': str(DATA / 'service.log'),
        'StandardErrorPath': str(DATA / 'service-error.log'),
    }
    with path.open('wb') as stream:
        plistlib.dump(specification, stream)
    result = HOST.launchctl(['bootstrap', f'gui/{os.getuid()}', str(path)],
                            capture_output=True)
    if result.returncode:
        path.unlink()
        raise BridgeError('Could not start the LaunchAgent. Run Run.command in a terminal instead.')
    print('Background service installed. It starts at login and restarts after errors.')


def uninstall(ROOT, BridgeError):
    path = Path.home() / 'Library/LaunchAgents/com.personal.codex-telegram.plist'
    if path.exists():
        spec = plistlib.loads(path.read_bytes())
        if spec.get('WorkingDirectory') != str(ROOT):
            raise BridgeError('The existing service belongs to a different folder; it was preserved.')
        HOST.launchctl(['bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
        path.unlink()
    print('Background service removed. Local configuration and message mappings were kept.')
