"""Owned Telegram service replacement through native host adapters."""
import base64
import os
from pathlib import Path
import plistlib

from .host import HOST, UnsupportedHost
from . import host_linux

LABEL = 'com.personal.codex-telegram'


class Service:
    def __init__(self, paths, install):
        self.paths, self.install = paths, str(install)
        if HOST.platform == 'darwin':
            self.path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
            self.manager = None
        elif HOST.platform == 'linux':
            self.path = host_linux.unit_path()
            self.manager = host_linux.manager() if self.path.exists() else None
        else:
            raise UnsupportedHost('Release switching requires a macOS or Linux adapter.')

    def read(self):
        return host_linux.read(self.path)

    def capture(self):
        raw = self.read()
        if raw is None:
            return dict(raw=None, active=False, platform=HOST.platform)
        if HOST.platform == 'darwin':
            spec = plistlib.loads(raw)
            argv = spec.get('ProgramArguments', [])
            if (spec.get('Label') != LABEL or spec.get('WorkingDirectory') != self.install
                    or len(argv) != 3 or argv[1:] != [str(Path(self.install) / 'bridge.py'), 'run']
                    or not Path(argv[0]).is_absolute()
                    or any(spec.get('EnvironmentVariables', {}).get(k) != v for k, v in self.paths.environment().items())):
                raise ValueError('Existing service has different bindings or a custom launcher; it was preserved.')
            active = HOST.launchctl(['print', f'gui/{os.getuid()}/{LABEL}'], capture_output=True).returncode == 0
        else:
            host_linux.check_owner(raw, self.install, ValueError, self.paths)
            active = host_linux.command(self.manager, 'is-active', host_linux.UNIT).returncode == 0
        return dict(raw=base64.b64encode(raw).decode(), active=active, platform=HOST.platform)

    def candidate(self, previous, target):
        if previous['raw'] is None:
            return None
        if HOST.platform == 'darwin':
            spec = plistlib.loads(base64.b64decode(previous['raw']))
            spec.update(ProgramArguments=[target['python'], str(Path(target['install']) / 'bridge.py'), 'run'],
                        WorkingDirectory=target['install'])
            return plistlib.dumps(spec)
        return host_linux.definition(target['install'], self.paths, target['python'])

    def verify(self, previous, candidate):
        current = self.read()
        old = base64.b64decode(previous['raw']) if previous['raw'] else None
        if previous['platform'] != HOST.platform or current not in (old, candidate):
            raise ValueError('Service definition changed during the update; manual recovery is required.')

    def stop(self, previous):
        if not previous['raw'] or not previous['active']:
            return
        if HOST.platform == 'darwin':
            result = HOST.launchctl(['bootout', f'gui/{os.getuid()}', str(self.path)], capture_output=True)
            # Already unloaded is acceptable, but never ignore a still-loaded service.
            if result.returncode and HOST.launchctl(['print', f'gui/{os.getuid()}/{LABEL}'], capture_output=True).returncode == 0:
                raise ValueError('Could not stop the owned launchd service.')
        elif host_linux.command(self.manager, 'stop', host_linux.UNIT).returncode:
            raise ValueError('Could not stop the owned systemd service.')

    def write(self, raw):
        if raw is not None:
            host_linux.write(self.path, raw)
            if HOST.platform == 'linux' and host_linux.command(self.manager, 'daemon-reload').returncode:
                raise ValueError('systemd could not reload the service definition.')

    def start(self, previous):
        if not previous['raw'] or not previous['active']:
            return
        result = (HOST.launchctl(['bootstrap', f'gui/{os.getuid()}', str(self.path)], capture_output=True)
                  if HOST.platform == 'darwin' else host_linux.command(self.manager, 'start', host_linux.UNIT))
        if result.returncode:
            raise ValueError('The selected service could not start.')
