"""Explicit native bridge registration; platform locations stay in this adapter."""
import json
from pathlib import Path
import re
import shlex
import sys
from .host import UnsupportedHost
from .browser_native import HOST_NAME
from .filesystem import FILES, Grant


def registry_folder(platform=sys.platform, home=None):
    home = Path(home or Path.home())
    if platform == 'darwin': return home / 'Library/Application Support/Google/Chrome/NativeMessagingHosts'
    if platform == 'linux': return home / '.config/google-chrome/NativeMessagingHosts'
    raise UnsupportedHost('Chrome capture bridge installation currently supports macOS and Linux')


def install(extension_id, data_dir, runtime_root, python, *, registration=None):
    if not re.fullmatch('[a-p]{32}', extension_id): raise ValueError('Copy the 32-letter ID from chrome://extensions')
    folder, root, executable = map(lambda p: Path(p).absolute(), (data_dir, runtime_root, python))
    if not root.joinpath('task_relay/browser_native.py').is_file() or not executable.is_file():
        raise ValueError('A runtime containing the capture bridge and a Python executable are required')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = Path(registration or registry_folder()).absolute()
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    launch = folder / 'chrome-capture-host'
    # Only the caller origin is shell-expanded. All selected paths are quoted.
    command = 'exec ' + shlex.quote(str(executable)) + ' -m task_relay.browser_native "$1" ' + shlex.join([
        '--extension-id', extension_id, '--data-dir', str(folder)])
    content = '#!/bin/sh\ncd ' + shlex.quote(str(root)) + ' || exit 1\n' + command + '\n'
    FILES.write(Grant(folder, 'User-authorized Chrome bridge installation', writes=frozenset({launch.name})), launch.name, content.encode())
    launch.chmod(0o700)
    name = HOST_NAME + '.json'
    manifest = {'name': HOST_NAME, 'description': 'Task Relay explicit browser capture', 'path': str(launch),
                'type': 'stdio', 'allowed_origins': ['chrome-extension://' + extension_id + '/']}
    FILES.write(Grant(destination, 'User-authorized Chrome native host registration', writes=frozenset({name})), name, json.dumps(manifest, indent=2).encode())
    return {'manifest': str(destination / name), 'data_dir': str(folder), 'extension_id': extension_id}
