"""Explicit desktop connection to the data paths of an existing macOS Relay service."""
import json
import os
from pathlib import Path
import plistlib
import tempfile

LABEL = 'com.personal.codex-telegram'
KEYS = ('TASK_RELAY_DATA_DIR', 'TASK_RELAY_WORKSPACE_DIR', 'TASK_RELAY_GENERATED_DIR')
FILE = Path.home() / 'Library/Application Support/Task Relay Desktop/binding.json'


class DesktopBindingError(ValueError):
    pass


def _paths(value):
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) for k in KEYS):
        raise DesktopBindingError('The existing service has no complete data-path binding.')
    selected = {key: Path(value[key]).expanduser() for key in KEYS}
    if any(not path.is_absolute() for path in selected.values()):
        raise DesktopBindingError('The existing service has invalid data paths.')
    selected = {key: str(path.resolve()) for key, path in selected.items()}
    if not (Path(selected[KEYS[0]]) / 'state.sqlite').is_file():
        raise DesktopBindingError('The existing service has no task history at its saved data path.')
    return selected


def apply_binding():
    if 'TASK_RELAY_DATA_DIR' in os.environ or not FILE.is_file():
        return
    try:
        saved = json.loads(FILE.read_text())
        selected = _paths(saved)
    except (OSError, ValueError, TypeError):
        return
    os.environ.update(selected)


def source_service():
    path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    try:
        spec = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, TypeError):
        raise DesktopBindingError('No readable existing Relay service was found.') from None
    if spec.get('Label') != LABEL or spec.get('TaskRelayDesktopOwner'):
        raise DesktopBindingError('There is no separate source-installed Relay service to connect.')
    selected = _paths(spec.get('EnvironmentVariables'))
    return selected


def connect():
    selected = source_service()
    FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.binding-', dir=FILE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(selected, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'message': 'Connected to the existing service task history. The desktop app did not restart or change that service.'}


def disconnect():
    FILE.unlink(missing_ok=True)
    return {'message': 'Desktop app returned to its own data location. The existing service and its history were not changed.'}
