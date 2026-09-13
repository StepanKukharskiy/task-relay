"""POSIX, process-local credential pipes. No filesystem spool or retained payload."""
import json
import os
import select
import threading
from pathlib import Path
from .host import HOST

_pipes = {}
_lock = threading.Lock()


def register(data, job, stream):
    HOST.require_posix('Browser login input')
    os.set_blocking(stream.fileno(), False)
    with _lock:
        _pipes[(str(Path(data).resolve()), job)] = stream


def forget(data, job):
    with _lock:
        stream = _pipes.pop((str(Path(data).resolve()), job), None)
        if stream:
            stream.close()


def send(data, job, challenge, value):
    HOST.require_posix('Browser login input')
    raw = (json.dumps({'challenge': challenge, 'value': value}) + '\n').encode()
    if len(raw) > 4000:
        raise ValueError('Login input exceeds the supported size.')
    with _lock:
        stream = _pipes.get((str(Path(data).resolve()), job))
        if stream is None:
            raise ValueError('The login worker is unavailable; start a new sign-in session.')
        # One atomic, nonblocking pipe write. Failure never retries this payload.
        if os.write(stream.fileno(), raw) != len(raw):
            raise ValueError('Login input delivery was not confirmed; it will not be repeated.')


class Inbox:
    def __init__(self, stream):
        HOST.require_posix('Browser login input')
        self.fd = stream.fileno()
        self.buffer = bytearray()

    def poll(self):
        if not select.select([self.fd], [], [], .2)[0]:
            return None
        raw = os.read(self.fd, 4096)
        if not raw:
            raise ValueError('Login input channel closed.')
        self.buffer.extend(raw)
        if len(self.buffer) > 4000:
            raise ValueError('Login input exceeds the supported size.')
        if b'\n' not in self.buffer:
            return None
        raw = bytes(self.buffer)
        self.buffer.clear()
        value = json.loads(raw)
        if set(value) != {'challenge', 'value'} or not all(isinstance(x, str) for x in value.values()):
            raise ValueError('Invalid login input envelope.')
        return value
