"""macOS Messages helper owned by the same packaged companion as Relay."""
import os
from pathlib import Path
import plistlib
import shutil
import time
import uuid

from .desktop_macos import DesktopService, DesktopServiceError
from .host import HOST
from .relay_paths import PATHS

LABEL = 'com.personal.taskrelay.messages'
OWNER = 'task-relay-companion-messages-v1'


class MessagesService(DesktopService):
    def __init__(self, runtime=None, paths=PATHS, host=HOST, home=None, clock=time.time, sleep=time.sleep):
        super().__init__(runtime, paths, host, home, clock, sleep)
        self.path = Path(home or Path.home()) / 'Library/LaunchAgents' / (LABEL + '.plist')
        self.helper = self.runtime / 'helpers/Messages Relay.app/Contents/MacOS/MessagesRelay'
        # launchd opens these before the helper can request Documents access.
        self.logs = Path(home or Path.home()) / 'Library/Logs/Task Relay Messages'

    def _loaded(self):
        return self._command(['print', f'gui/{os.getuid()}/{LABEL}']).returncode == 0

    def _spec(self):
        return {'Label': LABEL, 'TaskRelayDesktopOwner': OWNER,
                'ProgramArguments': [str(self.helper)], 'WorkingDirectory': str(self.app),
                'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 20, 'ExitTimeOut': 12,
                'LimitLoadToSessionType': 'Aqua', 'Umask': 0o077,
                'EnvironmentVariables': {**self.paths.environment(), 'TASK_RELAY_COMPANION_RUNTIME': str(self.runtime),
                                         'TASK_RELAY_COMPANION': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                'StandardOutPath': str(self.logs / 'service.log'),
                'StandardErrorPath': str(self.logs / 'service-error.log')}

    def _ensure_runtime(self):
        super()._ensure_runtime()
        if not self.helper.is_file() or not os.access(self.helper, os.X_OK):
            raise DesktopServiceError('The packaged Messages helper is unavailable. Rebuild or reinstall Task Relay.')
        if not shutil.which('imsg') and not Path('/opt/homebrew/bin/imsg').is_file():
            raise DesktopServiceError('The optional Messages connection needs the imsg utility. Existing pairing was retained.')

    def status(self):
        from .companion import messages_state
        self.host.require_macos('Messages companion connection')
        state = messages_state(self.paths, self.clock)
        owner, spec = self._owner()
        loaded = self._loaded()
        shared = bool(spec and all(spec.get('EnvironmentVariables', {}).get(key) == value
                                  for key, value in self.paths.environment().items()))
        healthy = bool(shared and loaded and state['fresh'] and state['health'] == 'running' and not state['paused'])
        managed = owner == 'desktop'
        detail = ('Messages is connected through Task Relay.' if managed and healthy else
                  'The existing Messages helper is connected. Review a handoff to manage it here.' if healthy else
                  'Messages needs attention; inspect its permissions and recovery records.' if loaded and shared else
                  'Messages is stopped; your pairing is retained.' if managed else
                  'An existing Messages helper uses this installation.' if shared else
                  'Another Messages installation was found and is preserved.' if owner != 'none' else
                  'No Messages helper is installed. Telegram is ready for the complete setup flow.')
        return {**state, 'owner': owner, 'loaded': loaded, 'healthy': healthy, 'managed': managed,
                'shared_data': shared, 'detail': detail,
                'handoff_available': bool(shared and not managed and state['paired'] and not state['error'])}

    def start(self, timeout=25):
        self.host.require_macos('Messages companion connection')
        self._ensure_runtime()
        if self._owner()[0] != 'desktop':
            raise DesktopServiceError('Review a Messages connection handoff before starting it here.')
        if self._loaded():
            current = self.status()
            if current['healthy']:
                return {**current, 'message': 'Messages is already connected.'}
            raise DesktopServiceError('Messages is loaded but its connection is unverified. Inspect permissions and recovery first.')
        if (self.paths.messages / 'paused').exists():
            raise DesktopServiceError('The old helper is paused. Resume it deliberately before handing it off.')
        self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        attempt = str(uuid.uuid4())
        started = self.clock()
        self._receipt(attempt, 'messages-start', 'intent', 'Starting the app-owned Messages helper.')
        result = self._command(['bootstrap', f'gui/{os.getuid()}', str(self.path)])
        if not result.returncode:
            while self.clock() - started < timeout:
                current = self.status()
                if current['healthy']:
                    # A fresh post-start heartbeat is required, not a prior helper's.
                    import json
                    health = json.loads((self.paths.messages / 'health.json').read_text())
                    if health.get('updated_at', 0) >= started:
                        self._receipt(attempt, 'messages-start', 'ready', 'A fresh Messages watcher heartbeat was observed.')
                        return {**current, 'message': 'Messages watcher started. Actual phone delivery is not verified by its heartbeat.'}
                self.sleep(.25)
        self._command(['bootout', f'gui/{os.getuid()}/{LABEL}'])
        stopped = not self._loaded()
        self._receipt(attempt, 'messages-start', 'failed' if stopped else 'uncertain', 'No fresh watcher heartbeat.')
        raise DesktopServiceError('Messages did not confirm startup. Inspect permissions and service status; no send was repeated.')

    def stop(self):
        self.host.require_macos('Messages companion connection')
        if self._owner()[0] != 'desktop':
            raise DesktopServiceError('This Messages helper is not owned by the companion; it was preserved.')
        if not self._loaded():
            return {**self.status(), 'message': 'Messages is already stopped.'}
        attempt = str(uuid.uuid4())
        self._receipt(attempt, 'messages-stop', 'intent', 'Stopping the owned Messages transport, not its already dispatched work.')
        self._command(['bootout', f'gui/{os.getuid()}/{LABEL}'])
        if self._loaded():
            self._receipt(attempt, 'messages-stop', 'uncertain', 'macOS still reports the helper loaded.')
            raise DesktopServiceError('Messages is still loaded. Inspect the helper before retrying.')
        self._receipt(attempt, 'messages-stop', 'stopped', 'Messages helper unloaded; pairing retained.')
        return {**self.status(), 'message': 'Messages transport stopped. Existing work is not cancelled. It starts again at login.'}
