"""Optional signed macOS helper; private pipes, no browser/CDP connection."""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys

from .computer_contract import PROTOCOL
from .host import UnsupportedHost

SOURCE = Path(__file__).parent / 'assets/macos/ComputerObserver.swift'
IDENTIFIER = 'org.taskrelay.computer-observer'


def bundled_helper():
    """Resolve the shipped helper without compiling or inspecting any browser."""
    require_host()
    return Path(__file__).resolve().parents[2] / 'helpers/Relay Computer Observer.app'


@contextmanager
def lease():
    """One native session per OS user; importing this module remains portable."""
    require_host()
    from .host import HOST
    from .host_managed_chrome import setup_lock
    # One OS-user Safari lease across Relay jobs, databases and data bindings.
    # Reuse checked ownership/locking without launching or inspecting Chrome.
    root = HOST.user_data() / 'computer-use'
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Computer-use lease path must not traverse symlinks.')
    with setup_lock(root, host=HOST):
        yield


def require_host():
    if sys.platform != 'darwin':
        raise UnsupportedHost('Computer observation requires the macOS adapter; other hosts are unqualified.')
    if int(platform.mac_ver()[0].split('.')[0]) < 14:
        raise UnsupportedHost('Computer observation requires macOS 14 or newer.')


def build(destination):
    """Explicit development build, never invoked by status or an observation."""
    require_host()
    app = Path(destination).absolute()
    if app.suffix != '.app' or app.exists() or app.is_symlink():
        raise ValueError('Choose a new .app destination; existing helper builds are preserved.')
    if any(p.is_symlink() for p in app.parents):
        raise ValueError('Helper destination must not traverse symlinks.')
    binary = app / 'Contents/MacOS/ComputerObserver'
    binary.parent.mkdir(parents=True, mode=0o700)
    metadata = {'CFBundleIdentifier': IDENTIFIER, 'CFBundleName': 'Relay Computer Observer',
                'CFBundleExecutable': 'ComputerObserver', 'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '1', 'CFBundleShortVersionString': '0.1.0',
                'LSMinimumSystemVersion': '14.0', 'LSUIElement': True,
                'NSAppleEventsUsageDescription': 'Task Relay reads and navigates explicitly approved Safari research pages.',
                'NSScreenCaptureUsageDescription': 'Capture only the Safari window explicitly selected for a Relay observation.'}
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(metadata))
    cache = app.parent / 'swift-module-cache'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-O', '-target',
                    platform.machine() + '-apple-macosx14.0', '-module-cache-path', str(cache),
                    str(SOURCE), '-o', str(binary)], check=True, timeout=120)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier', IDENTIFIER,
                    str(app)], check=True, capture_output=True, timeout=30)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], check=True,
                   capture_output=True, timeout=15)
    receipt = {'protocol': PROTOCOL, 'identifier': IDENTIFIER, 'signing': 'ad-hoc-development',
               'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'installed': False, 'tcc_qualified': False}
    # Receipt stays outside the signed bundle.
    app.with_suffix('.build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return {'helper': str(app), **receipt}


class Observer:
    def __init__(self, app):
        require_host()
        self.app = Path(app).absolute()
        self.binary = self.app / 'Contents/MacOS/ComputerObserver'
        if any(p.is_symlink() for p in (self.binary, *self.binary.parents)):
            raise ValueError('Helper path must not traverse symlinks.')
        receipt = json.loads(self.app.with_suffix('.build.json').read_text())
        if receipt.get('protocol') != PROTOCOL or receipt.get('identifier') != IDENTIFIER:
            raise ValueError('Helper build identity mismatch.')
        if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != receipt.get('source_sha256'):
            raise ValueError('Helper source changed; explicitly build a new helper.')
        if hashlib.sha256(self.binary.read_bytes()).hexdigest() != receipt.get('binary_sha256'):
            raise ValueError('Helper executable differs from its build receipt.')
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(self.app)], check=True,
                       capture_output=True, timeout=15)
        self.identity = receipt

    def require_ready(self):
        value=self.call({'protocol':PROTOCOL,'operation':'status'})
        if value.get('ok') is not True or value.get('ready') is not True:
            missing=[name for name in ('accessibility','screen_recording','session_unlocked') if value.get(name) is not True]
            raise ValueError('Safari helper needs '+', '.join(missing or ['native permissions'])+'. Check macOS Privacy & Security for '+str(self.app)+'. No Safari window was opened.')

    def require_scripting_ready(self):
        value=self.call({'protocol':PROTOCOL,'operation':'scripting-status'})
        if value.get('ok') is not True or value.get('ready') is not True:
            raise ValueError('Safari scripting unavailable: '+str(value.get('error','Automation permission required'))+'. Allow the bundled Relay helper to control Safari in macOS Automation. No research window was opened.')

    def call(self, request):
        if request.get('protocol') != PROTOCOL or request.get('operation') not in ('status', 'scripting-status', 'windows', 'observe', 'request-permissions'):
            raise ValueError('Unsupported native observer request.')
        raw = json.dumps(request, ensure_ascii=False).encode()
        if len(raw) > 24000:
            raise ValueError('Native request exceeds its bound.')
        # No shell, listener, arbitrary output path, environment credentials or CDP.
        result = subprocess.run([str(self.binary)], input=raw, capture_output=True, timeout=25,
                                env={k: v for k, v in os.environ.items() if k in ('HOME', 'TMPDIR', 'PATH', 'LANG')})
        if result.returncode or len(result.stdout) > 14000000:
            raise ValueError('Native observer failed or exceeded its response bound.')
        value = json.loads(result.stdout)
        if value.get('protocol') != PROTOCOL:
            raise ValueError('Native helper protocol mismatch.')
        return value

    @contextmanager
    def session(self):
        """An owned private JSON-lines process; no reconnect or implicit resend."""
        child = subprocess.Popen([str(self.binary), '--session'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env={k: v for k, v in os.environ.items() if k in ('HOME', 'TMPDIR', 'PATH', 'LANG')})
        try:
            yield NativeSession(child)
        finally:
            # Closing or killing the child never authorizes resending a request.
            child.stdin.close()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()


class NativeSessionError(ValueError):
    """Retain only a bounded protocol code across the worker boundary."""
    def __init__(self, code):
        self.code = code if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,159}', code) else 'invalid_native_error'
        super().__init__('Native session blocked: ' + self.code)


class NativeSession:
    def __init__(self, child):
        self.child = child
        self.buffer = bytearray()

    def call(self, request):
        import selectors
        import time
        raw = json.dumps(request, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(raw) > 24000 or request.get('operation') not in ('launch', 'bind', 'observe', 'navigate', 'scroll'):
            raise ValueError('Invalid bounded native session request.')
        deadline = time.monotonic() + 25
        with selectors.DefaultSelector() as selector:
            # A stopped helper must not hang its parent while filling a pipe.
            os.set_blocking(self.child.stdin.fileno(), False)
            selector.register(self.child.stdin, selectors.EVENT_WRITE)
            offset = 0
            while offset < len(raw):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise NativeSessionError('native_request_delivery_timeout')
                try:
                    offset += os.write(self.child.stdin.fileno(), raw[offset:])
                except BlockingIOError:
                    continue
            selector.unregister(self.child.stdin)
            selector.register(self.child.stdout, selectors.EVENT_READ)
            while b'\n' not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise NativeSessionError('native_response_timeout')
                chunk = os.read(self.child.stdout.fileno(), 65536)
                if not chunk:
                    raise NativeSessionError('native_response_eof')
                self.buffer.extend(chunk)
                if len(self.buffer) > 14000000:
                    raise NativeSessionError('native_response_too_large')
        line, _, rest = self.buffer.partition(b'\n')
        self.buffer = bytearray(rest)
        try:value = json.loads(line)
        except (ValueError, UnicodeError):raise NativeSessionError('native_response_invalid_json') from None
        if not isinstance(value, dict) or value.get('protocol') != PROTOCOL:
            raise NativeSessionError('native_protocol_mismatch')
        if value.get('ok') is not True:
            raise NativeSessionError(value.get('error', 'native_response_rejected'))
        return value
