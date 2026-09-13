"""Native extension registration and framing; platform details stay here."""
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import struct
import sys
import time
from contextlib import contextmanager

from .host import UnsupportedHost

HOST_NAME = 'ai.task_relay.perplexity'
EXTENSION_ID = 'perplexity@task-relay.local'
MAX_MESSAGE = 900000


def chrome_endpoint(platform=sys.platform,home=None):
    """Read only Chrome's published connection descriptor, never account data."""
    from .host_browser_accounts import local_endpoint
    home=Path(home or Path.home())
    if platform=='darwin':folder=home/'Library/Application Support/Google/Chrome'
    elif platform=='linux':folder=home/'.config/google-chrome'
    else:raise UnsupportedHost('Existing Chrome session discovery supports macOS and Linux only.')
    try:
        with (folder/'DevToolsActivePort').open('r') as source:raw=source.read(1025)
    except OSError:
        raise ValueError('In your signed-in Chrome, enable remote debugging at chrome://inspect/#remote-debugging, then allow the connection.') from None
    lines=raw.splitlines()
    if len(raw)>1024 or len(lines)!=2 or not lines[0].isascii() or not lines[0].isdecimal() or not 1<=int(lines[0])<=65535:
        raise ValueError('Chrome connection descriptor is invalid; no other profile was selected.')
    return local_endpoint('ws://127.0.0.1:'+lines[0]+lines[1],True)


@contextmanager
def attached_page(endpoint=None,*,chrome=False):
    """Attach to an explicitly selected local Chromium instance; retain its tabs."""
    from .host_browser_accounts import resolve_endpoint, attach
    from playwright.sync_api import sync_playwright
    if chrome and endpoint:raise ValueError('Select the existing Chrome session or an explicit endpoint, not both.')
    socket = chrome_endpoint() if chrome else resolve_endpoint(endpoint)
    with sync_playwright() as runtime:
        # Permission-based Chrome connections may wait for the user's Allow dialog.
        remote = attach(runtime, socket,timeout=60000 if chrome else 10000)
        try:
            # Never adopt an existing draft or tab by position. The new task tab
            # stays open for inspection, including after an uncertain submission.
            yield remote.contexts[0].new_page()
        finally:
            remote.close()  # Disconnect CDP; the external browser owns its lifetime.


class Port:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    def read(self, timeout=45):
        deadline = time.monotonic() + timeout
        def exact(size):
            result = b''
            while len(result) < size:
                try:
                    fd = self.reader.fileno()
                except (AttributeError, OSError):
                    chunk = self.reader.read(size - len(result))
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                        raise ValueError('Browser response timed out; the action was not retried.')
                    chunk = os.read(fd, size - len(result))
                if not chunk:
                    raise EOFError('Browser disconnected.')
                result += chunk
            return result
        size = struct.unpack('=I', exact(4))[0]
        if not 0 < size <= MAX_MESSAGE:
            raise ValueError('Browser message exceeds the limit.')
        value = json.loads(exact(size))
        if not isinstance(value, dict):
            raise ValueError('Expected a browser message object.')
        return value

    def write(self, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        if len(raw) > MAX_MESSAGE:
            raise ValueError('Browser message exceeds the limit.')
        self.writer.write(struct.pack('=I', len(raw)) + raw)
        self.writer.flush()


def registry_folder(platform=sys.platform, home=None):
    home = Path(home or Path.home())
    if platform == 'darwin':
        return home / 'Library/Application Support/Mozilla/NativeMessagingHosts'
    if platform == 'linux':
        return home / '.mozilla/native-messaging-hosts'
    raise UnsupportedHost('Perplexity native browser registration is implemented for macOS and Linux only.')


def prepare(folder, paths, python=None):
    """Produce a reviewable local installer, without registering or installing an add-on."""
    from .relay_paths import ASSETS, PACKAGE
    root = Path(folder).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    extension = root / 'extension'
    extension.mkdir(exist_ok=True)
    for source, name in [('perplexity-extension.json', 'manifest.json'),
                         ('perplexity-background.js', 'background.js'), ('perplexity-page.js', 'page.js')]:
        shutil.copy2(ASSETS / source, extension / name)
    launcher = root / 'native-host'
    env = ['PYTHONDONTWRITEBYTECODE=1', 'PYTHONNOUSERSITE=1',
           'TASK_RELAY_DATA_DIR=' + str(paths.data), 'TASK_RELAY_WORKSPACE_DIR=' + str(paths.workspaces),
           'TASK_RELAY_GENERATED_DIR=' + str(paths.generated)]
    launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(PACKAGE.parent)) + ' || exit 1\nexec env ' +
                        ' '.join(shlex.quote(v) for v in env) + ' ' + shlex.quote(python or sys.executable) +
                        ' -m task_relay.perplexity_native serve "$@"\n')
    launcher.chmod(0o700)
    manifest = root / (HOST_NAME + '.json')
    manifest.write_text(json.dumps({'name': HOST_NAME, 'description': 'Task Relay Perplexity Search worker',
                                   'path': str(launcher), 'type': 'stdio', 'allowed_extensions': [EXTENSION_ID]}, indent=2))
    manifest.chmod(0o600)
    return {'extension': str(extension / 'manifest.json'), 'host_manifest': str(manifest),
            'register_at': str(registry_folder() / manifest.name)}


def register(manifest):
    source = Path(manifest).resolve()
    value = json.loads(source.read_text())
    if (value.get('name') != HOST_NAME or value.get('allowed_extensions') != [EXTENSION_ID]
            or value.get('type') != 'stdio' or not Path(value.get('path', '')).is_file()):
        raise ValueError('Use the reviewed Task Relay native-host manifest.')
    folder = registry_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (HOST_NAME + '.json')
    if target.exists() and json.loads(target.read_text()) != value:
        raise ValueError('A different native host is registered; review it before replacement.')
    shutil.copy2(source, target)
    return str(target)
