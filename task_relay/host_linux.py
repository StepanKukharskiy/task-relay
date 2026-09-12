"""Optional systemd user service; foreground CLI works without a user manager."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .filesystem import FILES, Grant
from .host import UnsupportedHost

UNIT = 'task-relay-telegram.service'
MARKER = '# Task Relay service v1 '


def quote(value):
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise ValueError('Service paths must not contain control characters')
    return '"'+value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')+'"'


def definition(root, paths, python=None):
    python = str(python or sys.executable)
    binding = {'install': str(root), 'python': python, **paths.environment()}
    body = '\n'.join([
        '[Unit]', 'Description=Task Relay Telegram inbox',
        'StartLimitIntervalSec=60', 'StartLimitBurst=5', '', '[Service]',
        'Type=exec', 'WorkingDirectory='+quote(root),
        # A colon disables systemd's dollar expansion in the command arguments.
        'ExecStart=:'+quote(python)+' -m task_relay telegram run',
        *('Environment='+quote(k+'='+v) for k, v in paths.environment().items()),
        'UMask=0077', 'Restart=on-failure', 'RestartSec=5', 'TimeoutStopSec=45',
        # Detached supervisors retain their receipts and survive scheduler restart.
        'KillMode=process', '', '[Install]', 'WantedBy=default.target', '',
    ])
    binding['body_sha256'] = hashlib.sha256(body.encode()).hexdigest()
    return (MARKER+json.dumps(binding, sort_keys=True)+'\n'+body).encode()


def check_owner(raw, root, error, paths=None):
    try:
        header, body = raw.decode().split('\n', 1)
        if not header.startswith(MARKER):raise ValueError()
        binding = json.loads(header[len(MARKER):])
        if binding['install'] != str(root):raise ValueError()
        if binding['body_sha256'] != hashlib.sha256(body.encode()).hexdigest():raise ValueError()
        if paths and any(binding[k] != v for k, v in paths.environment().items()):raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise error('Existing user service has different bindings or local edits; it was preserved.') from None


def manager():
    executable = shutil.which('systemctl')
    if not executable:
        raise UnsupportedHost('No systemd user manager. Run task-relay telegram run under your chosen supervisor.')
    result = subprocess.run([executable, '--user', 'show-environment'], capture_output=True, timeout=10)
    if result.returncode:
        raise UnsupportedHost('systemd user manager is unavailable. Run task-relay telegram run in the foreground.')
    return executable


def command(executable, *arguments):
    return subprocess.run([executable, '--user', *arguments], capture_output=True, timeout=60)


def unit_path():
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))
    if not config.is_absolute():raise UnsupportedHost('XDG_CONFIG_HOME must be absolute')
    return config/'systemd/user'/UNIT


def read(path):
    try:return FILES.read(Grant(path.parent, 'inspect owned service', frozenset({path.name})), path.name, 100_000)
    except FileNotFoundError:return None


def write(path, raw):
    root = path.parent
    while not root.exists() and not root.is_symlink():root = root.parent
    name = path.relative_to(root).as_posix()
    FILES.write(Grant(root, 'explicit service installation', writes=frozenset({name})), name, raw)


def install(ROOT, DATA, PATHS, read_config, BridgeError):
    executable = manager()  # Detect availability before credentials or file mutation.
    read_config()
    path = unit_path(); prior = read(path)
    if prior is not None:check_owner(prior, ROOT, BridgeError, PATHS)
    # Refuse a system-wide/vendor unit with the same name, too.
    if prior is None:
        loaded = command(executable, 'show', UNIT, '--property=LoadState', '--value')
        if loaded.returncode == 0 and loaded.stdout.strip() not in (b'', b'not-found'):
            raise BridgeError('Another service with this name exists; it was preserved.')
    enabled = command(executable, 'is-enabled', UNIT).returncode == 0
    active = command(executable, 'is-active', UNIT).returncode == 0
    write(path, definition(ROOT, PATHS))
    try:
        for args in (('daemon-reload',), ('enable', UNIT), ('restart', UNIT), ('is-active', UNIT)):
            if command(executable, *args).returncode:
                raise BridgeError('Could not activate the systemd user service.')
    except (OSError, subprocess.SubprocessError, BridgeError) as exc:
        recovered = True
        try:
            if not active:recovered &= command(executable, 'stop', UNIT).returncode == 0
            if not enabled:recovered &= command(executable, 'disable', UNIT).returncode == 0
            if prior is None:path.unlink()
            else:write(path, prior)
            recovered &= command(executable, 'daemon-reload').returncode == 0
            if active:recovered &= command(executable, 'restart', UNIT).returncode == 0
        except (OSError, subprocess.SubprocessError):recovered = False
        raise BridgeError('Service activation failed; '+('prior state restored.' if recovered else
                          'recovery is incomplete; inspect systemctl --user status '+UNIT+'.')) from exc
    print('systemd user service is active. Provider and message delivery health require separate evidence.')


def uninstall(ROOT, BridgeError):
    executable = manager(); path = unit_path(); prior = read(path)
    if prior is None:
        print('No owned user service is installed.');return
    check_owner(prior, ROOT, BridgeError)
    for args in (('stop', UNIT), ('disable', UNIT)):
        if command(executable, *args).returncode:
            raise BridgeError('Could not stop/disable the service; its unit and application data were preserved.')
    path.unlink()
    if command(executable, 'daemon-reload').returncode:
        raise BridgeError('Unit removed, but the user manager could not reload; run systemctl --user daemon-reload.')
    print('User service removed. Configuration, pairing and execution records were kept.')
