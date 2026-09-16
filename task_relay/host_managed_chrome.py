"""Installed Chrome discovery and persistent Relay-owned browser lifecycle."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import signal
import subprocess
import time

from . import credentials
from .host import HOST
from .host_browser_accounts import local_endpoint, resolve_endpoint

START_URL = 'chrome://newtab/'


def chrome_path(host=HOST):
    # The desktop app currently ships for macOS. Do not imply Windows support
    # until its privacy, process and installer adapters are qualified.
    host.require_macos('Managed Chrome')
    for app in (Path('/Applications/Google Chrome.app'), Path.home()/'Applications/Google Chrome.app'):
        executable = app/'Contents/MacOS/Google Chrome'
        if executable.is_file() and os.access(executable, os.X_OK):
            return executable
    return None


@contextmanager
def setup_lock(data, host=HOST):
    host.require_macos('Managed Chrome setup')
    root = Path(data)/'browser-perplexity'
    if root.is_symlink():
        raise ValueError('The Relay browser folder must not be a link.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    fd = os.open(root/'chrome-setup.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError('The browser setup lock is not a private regular file.')
        try:
            host.lock(stream)
        except BlockingIOError:
            raise ValueError('Browser setup is already running. Wait a moment, then try again.') from None
        yield root


def descriptor(profile):
    path = profile/'DevToolsActivePort'
    if path.is_symlink():
        raise ValueError('The browser connection record must not be a link.')
    try:
        with path.open() as stream:
            raw = stream.read(1025)
    except FileNotFoundError:
        return None
    parts = raw.splitlines()
    if (len(raw) > 1024 or len(parts) != 2 or not parts[0].isascii()
            or not parts[0].isdecimal() or not 1 <= int(parts[0]) <= 65535):
        raise ValueError('Chrome has not published a valid connection record. Close the Relay browser and open it again.')
    return local_endpoint('ws://127.0.0.1:'+parts[0]+parts[1], True)


def live_socket(profile):
    """Reject a reused port belonging to another browser, including normal Chrome."""
    socket = descriptor(profile)
    if not socket:
        return None
    from urllib.parse import urlsplit
    try:
        current = resolve_endpoint('http://'+urlsplit(socket).netloc)
    except (OSError, ValueError, KeyError):
        return None
    return socket if current == socket else None


def ensure(root, *, open_window=False, host=HOST, timeout=30):
    """Called under setup_lock; launch no task and never copy a personal profile."""
    executable = chrome_path(host)
    if executable is None:
        raise ValueError('Google Chrome is required. Install Chrome, then turn Browser use on again.')
    profile = root/'chrome-profile'
    if profile.is_symlink():
        raise ValueError('The Relay Chrome profile must not be a link.')
    profile.mkdir(mode=0o700, exist_ok=True)
    os.chmod(profile, 0o700)
    socket = live_socket(profile)
    command = [str(executable), '--user-data-dir='+str(profile), '--remote-debugging-port=0',
               '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check', START_URL]
    if socket:
        if open_window:
            # Chrome routes this invocation to the same profile's process.
            host.spawn(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return socket
    record_path = root/'chrome-process.json'
    record = credentials.private_json(record_path) if record_path.exists() else {}
    if record.get('mode') == 'manual' and host.process_matches(record.get('pid'), '--user-data-dir='+str(profile)+' '):
        raise ValueError('Finish sign-in in Chrome, then choose Done signing in in Task Relay.')
    # A launch interrupted while Chrome is starting must not start a second one.
    running = host.process_matches(record.get('pid'), '--user-data-dir='+str(profile)+' --remote-debugging-port=0')
    process = None
    if not running:
        process = host.spawn(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        credentials.save(record_path, {'pid': process.pid, 'mode': 'worker'})
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        socket = live_socket(profile)
        if socket:
            return socket
        if process is not None and process.poll() not in (None, 0):
            break
        time.sleep(.15)
    raise ValueError('Chrome did not publish a verified connection within the startup limit. No website action was sent. Retry the blocked browser task after Chrome finishes opening; Relay will reuse the same browser and saved sign-ins.')


def stop_owned(root, host=HOST, timeout=6):
    """Caller holds both job/profile and setup locks; never terminate personal Chrome."""
    profile = root/'chrome-profile'
    record_path = root/'chrome-process.json'
    record = credentials.private_json(record_path) if record_path.exists() else {}
    pid = record.get('pid')
    token = '--user-data-dir='+str(profile)+' '
    if host.process_matches(pid, token):
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic()+timeout
        while host.process_matches(pid, token) and time.monotonic() < deadline:
            try:os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:pass
            time.sleep(.1)
        if host.process_matches(pid, token):
            raise ValueError('Close the Relay Chrome window to finish switching sign-in mode. No browser was forced to quit.')
    elif live_socket(profile):
        raise ValueError('Close the Relay Chrome window first; its process ownership could not be verified.')
    descriptor_path = profile/'DevToolsActivePort'
    if descriptor_path.is_symlink():
        raise ValueError('The browser connection record must not be a link.')
    descriptor_path.unlink(missing_ok=True)


def open_manual(root, host=HOST):
    """Open ordinary Chrome for human sign-in with no debugger or automation client."""
    executable = chrome_path(host)
    if executable is None:
        raise ValueError('Google Chrome is required. Install Chrome, then try again.')
    profile = root/'chrome-profile'
    if profile.is_symlink():
        raise ValueError('The Relay Chrome profile must not be a link.')
    profile.mkdir(mode=0o700, exist_ok=True)
    os.chmod(profile, 0o700)
    record_path = root/'chrome-process.json'
    record = credentials.private_json(record_path) if record_path.exists() else {}
    already_manual = record.get('mode') == 'manual' and host.process_matches(record.get('pid'), '--user-data-dir='+str(profile)+' ')
    if not already_manual:
        stop_owned(root, host)
    command = [str(executable), '--user-data-dir='+str(profile), '--no-first-run', '--no-default-browser-check', 'chrome://newtab/']
    process = host.spawn(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not already_manual:
        credentials.save(record_path, {'pid': process.pid, 'mode': 'manual'})
    # Startup is asynchronous. Do not interpret opening Chrome as a verified login.
