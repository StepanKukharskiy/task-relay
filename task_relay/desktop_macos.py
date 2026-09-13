"""Own one packaged macOS Telegram service without replacing a source service."""
import json
from contextlib import closing
import os
from pathlib import Path
import plistlib
import sqlite3
import time
import uuid

from .host import HOST
from .relay_paths import PATHS

LABEL = 'com.personal.codex-telegram'
OWNER = 'task-relay-desktop-v1'


class DesktopServiceError(ValueError):
    pass


class DesktopService:
    def __init__(self, runtime=None, paths=PATHS, host=HOST, home=None, clock=time.time, sleep=time.sleep):
        self.runtime = Path(runtime or os.environ.get('TASK_RELAY_DESKTOP_RUNTIME_ROOT', '')).expanduser()
        self.paths, self.host, self.clock, self.sleep = paths, host, clock, sleep
        self.path = Path(home or Path.home()) / 'Library/LaunchAgents' / (LABEL + '.plist')
        self.app = self.runtime / 'app'
        self.python = self.runtime / 'python/bin/python3'
        self.logs = Path(home or Path.home()) / 'Library/Logs/Task Relay'

    def _command(self, args):
        return self.host.launchctl(args, capture_output=True, text=True, timeout=8)

    def _loaded(self):
        return self._command(['print', f'gui/{os.getuid()}/{LABEL}']).returncode == 0

    def _spec(self):
        return {
            'Label': LABEL,
            'TaskRelayDesktopOwner': OWNER,
            'ProgramArguments': [str(self.python), str(self.app / 'bridge.py'), 'run'],
            'WorkingDirectory': str(self.app),
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 15,
            'EnvironmentVariables': {**self.paths.environment(), 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
            'StandardOutPath': str(self.logs / 'service.log'),
            'StandardErrorPath': str(self.logs / 'service-error.log'),
        }

    def _owner(self):
        if not self.path.exists():
            return 'none', None
        try:
            raw = self.path.read_bytes()
            spec = plistlib.loads(raw)
        except (OSError, ValueError, TypeError):
            return 'other', None
        return ('desktop' if spec == self._spec() else 'other'), spec

    def _heartbeat(self):
        if not self.paths.state.is_file():
            return None
        try:
            with closing(sqlite3.connect(self.paths.state.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                row = db.execute("SELECT value FROM kv WHERE key='health:poll'").fetchone()
            value = json.loads(row[0]) if row else None
            return value.get('last_success') if isinstance(value, dict) else None
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return None

    def status(self):
        self.host.require_macos('Desktop Relay service')
        from .desktop_binding import FILE
        bound_source = FILE.is_file()
        owner, spec = self._owner()
        loaded = self._loaded()
        shared_data = bool(owner == 'desktop' or owner == 'other' and spec and
                           spec.get('EnvironmentVariables', {}).get('TASK_RELAY_DATA_DIR') == str(self.paths.data))
        heartbeat = self._heartbeat() if shared_data else None
        healthy = bool(loaded and isinstance(heartbeat, (int, float)) and 0 <= self.clock() - heartbeat < 20)
        connectable = False
        if owner == 'other' and not shared_data:
            from .desktop_binding import DesktopBindingError, source_service
            try:
                source_service()
                connectable = True
            except DesktopBindingError:
                pass
        detail = ('Desktop service is running.' if owner == 'desktop' and healthy else
                  'Desktop service is loaded but its Telegram poll is unverified.' if owner == 'desktop' and loaded else
                  'Desktop service is installed but stopped.' if owner == 'desktop' else
                  'Existing source service is running; the desktop app preserves it.' if owner == 'other' and shared_data and healthy else
                  'Connected to an existing source service; its health is unverified.' if owner == 'other' and shared_data else
                  'Another Relay login service owns this name; the desktop app will preserve it.' if owner == 'other' else
                  'No background Relay service is installed.')
        if owner == 'none' and loaded:
            owner, detail = 'other', 'A loaded Relay service has no matching desktop definition; it was preserved.'
        return {'owner': owner, 'loaded': loaded, 'healthy': healthy,
                'shared_data': shared_data, 'connectable': connectable, 'bound_source': bound_source,
                'last_poll': heartbeat, 'detail': detail}

    def _receipt(self, attempt, action, phase, detail):
        self.paths.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.paths.data / 'desktop-service-receipts.jsonl'
        record = {'id': attempt, 'at': self.clock(), 'action': action,
                  'phase': phase, 'detail': detail}
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps(record, separators=(',', ':')) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            raise

    def _ensure_runtime(self):
        if not self.python.is_file() or not os.access(self.python, os.X_OK) or not (self.app / 'bridge.py').is_file():
            raise DesktopServiceError('The packaged Relay runtime is incomplete. Reinstall the desktop app.')

    def _write_new(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('xb') as stream:
                stream.write(plistlib.dumps(self._spec()))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            os.link(temp, self.path)  # Atomic no-replace: preserve another installer.
        finally:
            temp.unlink(missing_ok=True)

    def start(self, timeout=25):
        self.host.require_macos('Desktop Relay service')
        from .desktop_binding import FILE
        if FILE.is_file() and self._owner()[0] != 'desktop':
            raise DesktopServiceError('Return to desktop data before starting an app-owned service. Existing service data was preserved.')
        self._ensure_runtime()
        from .bridge import read_config
        read_config()
        owner, _ = self._owner()
        if owner == 'other':
            raise DesktopServiceError('Another Relay login service is installed. It was preserved; manage it from its original installation.')
        if self._loaded():
            status = self.status()
            if status['healthy']:
                return {**status, 'message': 'Desktop service is already running.'}
            raise DesktopServiceError('A Relay service is loaded but has no fresh Telegram poll. Inspect its logs before retrying; it was not restarted.')
        created = owner == 'none'
        if created:
            try:
                self._write_new()
            except FileExistsError:
                raise DesktopServiceError('Another Relay service appeared during setup. It was preserved.') from None
        self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        started = self.clock()
        attempt = str(uuid.uuid4())
        self._receipt(attempt, 'start', 'intent', 'Bootstrapping the owned service.')
        result = self._command(['bootstrap', f'gui/{os.getuid()}', str(self.path)])
        if result.returncode:
            if created and self._owner()[0] == 'desktop':
                self.path.unlink()
            self._receipt(attempt, 'start', 'failed', 'launchd rejected the service; no successful start was observed.')
            raise DesktopServiceError('macOS could not start the Relay service. Configuration was kept; retry after checking service-error.log.')
        while self.clock() - started < timeout:
            current = self.status()
            if current['healthy'] and current['last_poll'] >= started:
                self._receipt(attempt, 'start', 'ready', 'A fresh Telegram poll was observed.')
                return {**current, 'message': 'Relay is running and Telegram polling is healthy. Provider tasks and delivery still need a real check.'}
            self.sleep(.25)
        self._command(['bootout', f'gui/{os.getuid()}', str(self.path)])
        if self._loaded():
            self._receipt(attempt, 'start', 'uncertain', 'No fresh Telegram poll; launchd still reports the service loaded.')
            raise DesktopServiceError('Relay did not confirm a fresh Telegram poll and macOS still reports it loaded. Inspect the service before retrying.')
        if created and self._owner()[0] == 'desktop' and not self._loaded():
            self.path.unlink()
        self._receipt(attempt, 'start', 'failed', 'No fresh Telegram poll; service was stopped.')
        raise DesktopServiceError('Relay did not confirm a fresh Telegram poll. The attempted service was stopped; check service-error.log.')

    def stop(self):
        self.host.require_macos('Desktop Relay service')
        if self._owner()[0] != 'desktop':
            raise DesktopServiceError('The desktop app does not own this service; nothing was stopped.')
        if not self._loaded():
            return {**self.status(), 'message': 'Desktop service is already stopped.'}
        attempt = str(uuid.uuid4())
        self._receipt(attempt, 'stop', 'intent', 'Stopping the owned service.')
        self._command(['bootout', f'gui/{os.getuid()}', str(self.path)])
        if self._loaded():
            self._receipt(attempt, 'stop', 'failed', 'launchd kept the service loaded.')
            raise DesktopServiceError('macOS could not stop the owned service. It remains loaded.')
        self._receipt(attempt, 'stop', 'stopped', 'Owned service unloaded; its definition remains for next login.')
        return {**self.status(), 'message': 'Desktop service stopped. It will start again at the next login unless removed.'}
