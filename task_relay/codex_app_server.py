"""Bounded Codex app-server control calls. Never starts a model turn."""
import json
import os
import selectors
import subprocess
import time

from .host import HOST


class Rejected(ValueError):
    """A correlated server error, distinct from a lost response."""


class Client:
    def __init__(self, timeout=20, command=None):
        self.timeout, self.command = timeout, command
        self.process = None
        self.selector = None
        self.buffer = b''
        self.number = 0

    def __enter__(self):
        try:
            self.process = HOST.spawn(self.command or [HOST.codex(), 'app-server'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            self.request('initialize', {'clientInfo': {'name': 'task_relay', 'version': '1'}})
            self.write({'method': 'initialized'})
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.selector:
            self.selector.close()
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                HOST.stop_tree(self.process, timeout=1)
            finally:
                self.process.stdout.close()

    def __exit__(self, *args):
        self.close()

    def write(self, value):
        data = json.dumps(value, ensure_ascii=False).encode() + b'\n'
        # FileIO.write may be partial. These small control requests do not carry
        # conversation bodies or credentials.
        while data:
            count = self.process.stdin.write(data)
            if not count:
                raise ConnectionError('Codex app-server input closed.')
            data = data[count:]

    def request(self, method, params):
        self.number += 1
        ident = self.number
        self.write({'id': ident, 'method': method, 'params': params})
        deadline = time.monotonic() + self.timeout
        received = 0
        while time.monotonic() < deadline:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                value = json.loads(line)
                if value.get('id') == ident and ('result' in value or 'error' in value):
                    if 'error' in value:
                        raise Rejected('Codex rejected '+method+': '+str(value['error']))
                    return value['result']
                if 'method' in value and 'id' in value:
                    # Creation is not authority to approve tools, permissions,
                    # authentication refresh or other server requests.
                    self.write({'id': value['id'], 'error': {'code': -32601,
                        'message': 'Task Relay creation client does not handle this request.'}})
            if not self.selector.select(max(0, deadline-time.monotonic())):
                break
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise ConnectionError('Codex app-server closed before its response.')
            received += len(chunk)
            if received > 4_000_000:
                raise ValueError('Codex control response exceeded its limit.')
            self.buffer += chunk
        raise TimeoutError('Codex app-server response timed out; no retry was made.')
