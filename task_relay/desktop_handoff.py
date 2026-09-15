"""Reviewed macOS service-definition handoffs with durable recovery receipts.

Data stores are retained in place. No task or uncertain submission is replayed.
An interrupted handoff is inspected/restored explicitly, never applied twice.
"""
from contextlib import closing, contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import time
import uuid

from .desktop_macos import DesktopService, DesktopServiceError
from .desktop_messages import MessagesService
from .relay_paths import PATHS
from .host import HOST


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(record):
    return {key: record[key] for key in ('id', 'channel', 'created', 'prior', 'target',
        'prior_sha', 'target_sha', 'path', 'runtime_sha', 'paths', 'was_loaded', 'review')}


def _atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class Handoff:
    def __init__(self, runtime=None, paths=PATHS, host=HOST, home=None, clock=time.time, sleep=time.sleep):
        self.paths, self.host, self.clock, self.sleep = paths, host, clock, sleep
        self.services = {'relay': DesktopService(runtime, paths, host, home, clock, sleep),
                         'messages': MessagesService(runtime, paths, host, home, clock, sleep)}
        self.folder = paths.data / 'companion-handoffs'

    @contextmanager
    def _lock(self):
        self.host.require_macos('Companion service handoff')
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.folder / 'handoff.lock').open('a') as lock:
            try:
                self.host.lock(lock)
            except BlockingIOError:
                raise DesktopServiceError('Another handoff is in progress. Inspect its receipt before continuing.') from None
            yield

    def _file(self, ident):
        try:
            if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise DesktopServiceError('Choose a saved handoff receipt.') from None
        return self.folder / (ident + '.json')

    def _save(self, record, phase, detail):
        record.update(phase=phase, updated=self.clock(), detail=detail)
        record.setdefault('events', []).append({'at': self.clock(), 'phase': phase, 'detail': detail})
        _atomic(self._file(record['id']), json.dumps(record, sort_keys=True).encode())

    def _load(self, ident):
        try:
            record = json.loads(self._file(ident).read_text())
            if record['id'] != ident or record['channel'] not in self.services:
                raise ValueError
            if (_sha(json.dumps(_identity(record), sort_keys=True).encode()) != record['digest'] or
                    _sha(base64.b64decode(record['prior'], validate=True)) != record['prior_sha'] or
                    _sha(base64.b64decode(record['target'], validate=True)) != record['target_sha']):
                raise ValueError
            return record
        except (OSError, ValueError, KeyError):
            raise DesktopServiceError('The handoff receipt is unavailable; existing services were preserved.') from None

    def _idle(self):
        if not self.paths.state.is_file():
            raise DesktopServiceError('Existing task history is unavailable. Handoff requires the selected installation.')
        from .messages_storage import idle, tables
        try:
            with closing(sqlite3.connect(self.paths.state.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                idle(db)
                names = tables(db)
                for table, column, states in (
                    ('orchestrator_chats', 'status', ('running', 'processing')),
                    ('outbox_parts', 'status', ('sending',)),
                    ('messages_delivery', 'status', ('sending',)),
                    ('desktop_commands', 'status', ('submitting', 'sending', 'processing')),
                ):
                    if table in names:
                        columns = {row[1] for row in db.execute('PRAGMA table_info(' + table + ')')}
                        if column in columns and db.execute('SELECT 1 FROM ' + table + ' WHERE ' + column +
                            ' IN (' + ','.join('?' for _ in states) + ') LIMIT 1', states).fetchone():
                            raise ValueError('In-flight work exists.')
        except (sqlite3.Error, ValueError):
            raise DesktopServiceError('Wait for in-flight Relay work and deliveries to finish before handing off the service.') from None

    def _runtime_digest(self, service):
        service._ensure_runtime()
        result = hashlib.sha256()
        for path in sorted(p for p in service.app.rglob('*') if p.is_file() and '__pycache__' not in p.parts):
            if path.is_symlink():
                raise DesktopServiceError('The packaged source contains an unexpected symlink.')
            result.update(str(path.relative_to(service.app)).encode())
            result.update(hashlib.sha256(path.read_bytes()).digest())
        result.update(hashlib.sha256(service.python.read_bytes()).digest())
        if isinstance(service, MessagesService):
            result.update(hashlib.sha256(service.helper.read_bytes()).digest())
        return result.hexdigest()

    def _preview(self, record):
        return {key: record[key] for key in ('id', 'channel', 'digest', 'review', 'phase', 'detail')}

    def prepare(self, channel):
        if channel not in self.services:
            raise DesktopServiceError('Choose Relay or Messages for handoff.')
        with self._lock():
            if any(item['phase'] in ('stopping', 'switching', 'starting', 'restoring', 'uncertain') for item in self.inspect()['items']):
                raise DesktopServiceError('An unfinished handoff needs inspection before another can be prepared.')
            service = self.services[channel]
            service._ensure_runtime()
            try:
                prior = service.path.read_bytes()
                spec = plistlib.loads(prior)
            except (OSError, ValueError):
                raise DesktopServiceError('No readable existing service was found.') from None
            target = service._spec()
            if spec == target:
                raise DesktopServiceError('This connection already belongs to the companion.')
            args = spec.get('ProgramArguments', [])
            recognized = ((channel == 'relay' and (args[1:] == ['-m', 'task_relay.bridge', 'run'] or
                           len(args) == 3 and Path(args[1]).name == 'bridge.py' and args[2] == 'run')) or
                          (channel == 'messages' and len(args) == 1 and Path(args[0]).name == 'MessagesRelay'))
            if spec.get('Label') != target['Label'] or not recognized or not all(
                spec.get('EnvironmentVariables', {}).get(key) == value for key, value in self.paths.environment().items()):
                raise DesktopServiceError('The existing service does not match this installation. It was preserved.')
            if channel == 'messages':
                from .companion import messages_state
                state = messages_state(self.paths)
                if not state['paired'] or state['paused'] or state['error']:
                    raise DesktopServiceError('Messages must have an existing, readable, unpaused pairing before handoff.')
            candidate = plistlib.dumps(target)
            record = {'id': str(uuid.uuid4()), 'channel': channel, 'created': self.clock(),
                      'prior': base64.b64encode(prior).decode(), 'target': base64.b64encode(candidate).decode(),
                      'prior_sha': _sha(prior), 'target_sha': _sha(candidate), 'path': str(service.path),
                      'runtime_sha': self._runtime_digest(service), 'paths': self.paths.environment(),
                      'was_loaded': service._loaded()}
            record['review'] = ('Connection: ' + ('Relay' if channel == 'relay' else 'Apple Messages') +
                '\nCurrent executable: ' + args[0] + '\nCompanion executable: ' + target['ProgramArguments'][0] +
                '\nData retained at: ' + str(self.paths.data) + '\nWorkspaces retained at: ' + str(self.paths.workspaces) +
                '\nGenerated files retained at: ' + str(self.paths.generated) +
                '\nThe old service definition is saved for explicit rollback.' +
                ('\nMessages may require Full Disk Access and Automation permission for the bundled helper.' if channel == 'messages' else '') +
                '\nPreviously stopped services remain stopped after handoff.')
            record['digest'] = _sha(json.dumps(_identity(record), sort_keys=True).encode())
            self._save(record, 'prepared', 'Review prepared; no service was stopped or started.')
            return self._preview(record)

    def _validate(self, record):
        service = self.services[record['channel']]
        if record['paths'] != self.paths.environment() or record['path'] != str(service.path):
            raise DesktopServiceError('The installation binding changed. Prepare a new handoff.')
        if record['runtime_sha'] != self._runtime_digest(service) or record['target_sha'] != _sha(plistlib.dumps(service._spec())):
            raise DesktopServiceError('The packaged runtime changed. Prepare a new handoff.')
        return service

    def _unload(self, service):
        label = service._spec()['Label']
        if service._loaded():
            service._command(['bootout', f'gui/{os.getuid()}/{label}'])
            deadline = self.clock() + 8
            while service._loaded() and self.clock() < deadline:
                self.sleep(.1)
        if service._loaded():
            raise DesktopServiceError('macOS still reports the old service loaded. The definition was not replaced.')

    def apply(self, ident, digest):
        with self._lock():
            record = self._load(ident)
            if record['phase'] != 'prepared' or record['digest'] != digest:
                raise DesktopServiceError('This handoff changed or was already attempted. Inspect its saved receipt.')
            service = self._validate(record)
            if _sha(service.path.read_bytes()) != record['prior_sha'] or service._loaded() != record['was_loaded']:
                raise DesktopServiceError('The existing service changed after review. Prepare a new handoff.')
            self._idle()
            self._save(record, 'stopping', 'Stopping the reviewed old service before replacing its definition.')
            try:
                self._unload(service)
                self._idle()  # Work that raced with shutdown cannot be silently discarded.
                if _sha(service.path.read_bytes()) != record['prior_sha']:
                    raise DesktopServiceError('The old service definition changed during shutdown.')
                self._save(record, 'switching', 'Writing the reviewed definition; prior bytes are retained.')
                _atomic(service.path, base64.b64decode(record['target']))
                if record['was_loaded']:
                    self._save(record, 'starting', 'Starting the companion service and checking a fresh heartbeat.')
                    service.start(timeout=25)
                self._save(record, 'complete', 'Companion definition installed; ' + ('fresh startup observed.' if record['was_loaded'] else 'service remains stopped.'))
                return {**self._preview(record), 'message': record['detail']}
            except Exception:
                # Roll back this attempt only; preserve unrelated definitions and
                # never bootstrap the old service while the new one remains loaded.
                try:
                    self._restore(record, service)
                except Exception:
                    self._save(record, 'uncertain', 'Handoff or restoration is uncertain. Inspect and restore explicitly; do not apply again.')
                    raise DesktopServiceError(record['detail']) from None
                raise DesktopServiceError('The companion did not finish startup. The prior definition was restored; inspect its receipt and macOS permissions.') from None

    def _restore(self, record, service):
        current = service.path.read_bytes()
        if _sha(current) not in (record['prior_sha'], record['target_sha']):
            raise DesktopServiceError('Another installer changed the service. Automatic restoration was refused.')
        # Once the candidate has started new work, an automatic rollback must
        # leave it alone rather than interrupting that newly authorized work.
        if _sha(current) == record['target_sha'] and service._loaded():
            self._idle()
        self._save(record, 'restoring', 'Restoring the exact prior definition.')
        self._unload(service)
        _atomic(service.path, base64.b64decode(record['prior']))
        if record['was_loaded']:
            result = service._command(['bootstrap', f'gui/{os.getuid()}', str(service.path)])
            if result.returncode or not service._loaded():
                raise DesktopServiceError('The prior service definition was restored but startup is unverified.')
        self._save(record, 'restored', 'Prior definition restored; ' + ('launchd reports it loaded. Provider work and delivery were not tested.' if record['was_loaded'] else 'it remains stopped.'))

    def restore(self, ident):
        with self._lock():
            record = self._load(ident)
            if record['phase'] not in ('complete', 'stopping', 'switching', 'starting', 'restoring', 'uncertain'):
                raise DesktopServiceError('This receipt does not need restoration.')
            service = self.services[record['channel']]
            if record['paths'] != self.paths.environment() or record['path'] != str(service.path):
                raise DesktopServiceError('Return to the reviewed installation before restoring its service.')
            self._idle()
            try:
                self._restore(record, service)
            except Exception:
                self._save(record, 'uncertain', 'Restoration could not be confirmed. Inspect this receipt before another action.')
                raise DesktopServiceError(record['detail']) from None
            return {**self._preview(record), 'message': record['detail']}

    def inspect(self):
        items = []
        if self.folder.is_dir():
            for path in sorted(self.folder.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
                try:
                    items.append(self._preview(self._load(path.stem)))
                except DesktopServiceError:
                    items.append({'id': path.stem, 'phase': 'uncertain', 'detail': 'Unreadable handoff receipt; inspect local files.', 'channel': 'unknown'})
        return {'items': items}
