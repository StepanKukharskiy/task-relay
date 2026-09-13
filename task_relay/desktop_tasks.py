"""Local task view and durable desktop instructions processed by the Relay service."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sqlite3
import stat
import time
import uuid

from .relay_paths import PATHS


class DesktopTaskError(ValueError):
    pass


def _database(paths=PATHS, writable=False):
    if not paths.state.is_file():
        raise DesktopTaskError('No Relay task history exists at this data location yet.')
    target = str(paths.state) if writable else paths.state.as_uri() + '?mode=ro'
    db = sqlite3.connect(target, uri=not writable, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    return db


def _table(db, name):
    return db.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?', (name,)).fetchone() is not None


def list_tasks(paths=PATHS):
    if not paths.state.is_file():
        return {'tasks': [], 'creations': [], 'can_create': False, 'data': str(paths.data)}
    with closing(_database(paths)) as db:
        if not _table(db, 'watched'):
            return {'tasks': [], 'creations': [], 'can_create': False, 'data': str(paths.data)}
        rows = db.execute('''SELECT w.id,w.title,w.status,w.updated_at,
                            COALESCE(b.backend,'codex') AS backend,b.cwd
                            FROM watched w LEFT JOIN backend_tasks b ON b.id=w.id
                            ORDER BY w.updated_at DESC,w.rowid DESC LIMIT 50''').fetchall()
        creations = [dict(r) for r in db.execute('''SELECT request_id,title,status,task_id,result
                        FROM desktop_creations ORDER BY created DESC LIMIT 6''')] if _table(db, 'desktop_creations') else []
        heartbeat = db.execute("SELECT value FROM kv WHERE key='health:desktop'").fetchone()
        try:
            value = json.loads(heartbeat[0]) if heartbeat else {}
            can_create = _table(db, 'desktop_creations') and value.get('interface_version') == 1 and 0 <= time.time() - value.get('last_success', 0) < 20
        except (ValueError, TypeError):
            can_create = False
        return {'tasks': [{'id': r['id'], 'title': r['title'][:180], 'status': r['status'],
                           'backend': r['backend'], 'project': Path(r['cwd']).name if r['cwd'] else None,
                           'updated_at': r['updated_at']} for r in rows],
                'creations': creations, 'can_create': can_create, 'data': str(paths.data)}


def task_detail(task_id, paths=PATHS):
    if not isinstance(task_id, str) or not task_id or len(task_id) > 180:
        raise DesktopTaskError('Choose an exact task from the list.')
    with closing(_database(paths)) as db:
        row = db.execute('''SELECT w.id,w.title,w.status,w.updated_at,w.path,
                            COALESCE(b.backend,'codex') AS backend,b.cwd,b.model
                            FROM watched w LEFT JOIN backend_tasks b ON b.id=w.id WHERE w.id=?''',
                         (task_id,)).fetchone()
        if row is None:
            raise DesktopTaskError('That task is no longer in this Relay history. Refresh the list.')
        jobs = [dict(r) for r in db.execute('''SELECT id,status,created_at,started_at,finished_at,cancel,cost_usd
                            FROM backend_jobs WHERE thread_id=? ORDER BY created_at DESC LIMIT 5''', (task_id,))] if _table(db, 'backend_jobs') else []
        commands = [dict(r) for r in db.execute('''SELECT request_id,status,created,result FROM desktop_commands
                            WHERE task_id=? ORDER BY created DESC LIMIT 12''', (task_id,))] if _table(db, 'desktop_commands') else []
        from .desktop_conversation import bounded_messages, messages as conversation_messages
        from . import relay_channels
        from .desktop_approvals import pending as pending_approvals
        events = []
        for event in db.execute('SELECT rowid,* FROM outbox WHERE thread_id=? ORDER BY rowid DESC LIMIT 20', (task_id,)):
            events.append({'id': event['id'], 'text': event['text'][:4000],
                           'channel': relay_channels.event_channel(type('ReadState', (), {'db': db})(),
                                                                   event['id'], task_id, event['rowid'])})
        heartbeat = db.execute("SELECT value FROM kv WHERE key='health:desktop'").fetchone()
        ready = False
        if heartbeat:
            try:
                value = json.loads(heartbeat[0])
                ready = value.get('interface_version') == 1 and time.time() - value.get('last_success', 0) < 20
            except (ValueError, TypeError):
                pass
        return {'task': {'id': row['id'], 'title': row['title'], 'status': row['status'],
                         'backend': row['backend'], 'project': row['cwd'], 'model': row['model'],
                         'updated_at': row['updated_at']},
                'jobs': jobs, 'commands': commands, 'events': list(reversed(events)),
                'messages': bounded_messages(conversation_messages(db, row, list(reversed(events)))),
                'history_note': 'Recent saved messages. Large messages may be excerpted; full history remains in the original provider and Relay records.',
                'approvals': pending_approvals(db, task_id),
                'can_send': ready and row['status'] == 'idle',
                'can_stop': row['backend'] != 'codex' and any(
                    job['status'] in ('queued', 'running', 'waiting') and not job['cancel'] for job in jobs)}


def _request_id(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise DesktopTaskError('The desktop request needs a valid identity.') from None
    if str(parsed) != value:
        raise DesktopTaskError('The desktop request identity is invalid.')
    return value


def enqueue(task_id, prompt, request_id, paths=PATHS, clock=time.time):
    _request_id(request_id)
    if not isinstance(task_id, str) or not task_id or len(task_id) > 180:
        raise DesktopTaskError('Choose an exact task from the list.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode('utf-8')) > 12000:
        raise DesktopTaskError('Enter a nonempty instruction of at most 12 KB.')
    if any(ord(char) < 32 and char not in '\n\r\t' for char in prompt):
        raise DesktopTaskError('The instruction contains unsupported control characters.')
    with closing(_database(paths, writable=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not _table(db, 'desktop_commands'):
                raise DesktopTaskError('This Relay service does not yet support desktop task commands. Update and restart it first.')
            existing = db.execute('SELECT * FROM desktop_commands WHERE request_id=?', (request_id,)).fetchone()
            if existing:
                if existing['task_id'] != task_id or existing['prompt'] != prompt:
                    raise DesktopTaskError('That desktop request identity belongs to different content.')
                return {'request_id': request_id, 'status': existing['status'],
                        'message': existing['result'] or 'Request already recorded; it was not sent again.'}
            heartbeat = db.execute("SELECT value FROM kv WHERE key='health:desktop'").fetchone()
            try:
                value = json.loads(heartbeat[0]) if heartbeat else {}
                ready = value.get('interface_version') == 1 and 0 <= clock() - value.get('last_success', 0) < 20
            except (ValueError, TypeError):
                ready = False
            if not ready:
                raise DesktopTaskError('The Relay service is not ready to receive desktop instructions. Refresh service status.')
            row = db.execute('SELECT status FROM watched WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise DesktopTaskError('That task is no longer in this Relay history. Refresh the list.')
            incoming_id = -secrets.randbelow(2**62) - 1
            while db.execute('SELECT 1 FROM incoming WHERE id=?', (incoming_id,)).fetchone():
                incoming_id = -secrets.randbelow(2**62) - 1
            db.execute('''INSERT INTO desktop_commands(request_id,task_id,prompt,incoming_id,status,created)
                          VALUES (?,?,?,?,?,?)''', (request_id, task_id, prompt, incoming_id, 'queued', clock()))
        return {'request_id': request_id, 'status': 'queued',
                'message': 'Instruction recorded for the Relay service. Refresh the task for its submission receipt.'}


def enqueue_file(task_id, path, caption, request_id, paths=PATHS):
    _request_id(request_id)
    if not isinstance(task_id, str) or not task_id or len(task_id) > 180:
        raise DesktopTaskError('Choose an exact task from the list.')
    with closing(_database(paths)) as db:
        if _table(db, 'desktop_commands'):
            prior = db.execute('SELECT task_id,status,result FROM desktop_commands WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior['task_id'] != task_id:
                    raise DesktopTaskError('That desktop request identity belongs to a different task.')
                return {'request_id': request_id, 'status': prior['status'],
                        'message': prior['result'] or 'File instruction already recorded; it was not sent again.'}
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise DesktopTaskError('Choose a local UTF-8 .txt or .md file.')
    selected = Path(path).expanduser()
    if not selected.is_absolute() or selected.suffix.lower() not in ('.txt', '.md'):
        raise DesktopTaskError('Choose a local UTF-8 .txt or .md file.')
    filename = selected.name
    if len(filename) > 128 or any(ord(c) < 32 for c in filename):
        raise DesktopTaskError('The selected file name is too long or contains unsupported characters.')
    if not isinstance(caption, str) or len(caption.encode('utf-8')) > 1500:
        raise DesktopTaskError('Keep the accompanying instruction under 1.5 KB.')
    try:
        fd = os.open(selected, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 9000:
                raise DesktopTaskError('Choose a regular text file of at most 9 KB.')
            frozen = stream.read(9001)
    except OSError:
        raise DesktopTaskError('The selected file could not be read. Choose it again.') from None
    if len(frozen) > 9000:
        raise DesktopTaskError('Choose a regular text file of at most 9 KB.')
    try:
        content = frozen.decode('utf-8')
    except UnicodeError:
        raise DesktopTaskError('Save the selected file as UTF-8 text.') from None
    if not content.strip():
        raise DesktopTaskError('The selected text file is empty.')
    digest = hashlib.sha256(frozen).hexdigest()
    prompt = (caption.strip() + '\n\n' if caption.strip() else '') + (
        f'Attached text file: {filename}\nSHA-256: {digest}\n\n{content}')
    result = enqueue(task_id, prompt, request_id, paths)
    return {**result, 'filename': filename, 'sha256': digest}


def enqueue_create(backend, cwd, title, request_id, paths=PATHS, clock=time.time):
    _request_id(request_id)
    if backend not in ('gemini', 'claude', 'openai', 'qwen', 'deepseek', 'openrouter'):
        raise DesktopTaskError('Choose a supported provider for the new task.')
    if not isinstance(cwd, str) or len(cwd) > 4096:
        raise DesktopTaskError('Choose an existing absolute working folder or leave it empty.')
    isolated = not cwd.strip()
    project_path = paths.workspaces / 'desktop-tasks' / request_id if isolated else Path(cwd).expanduser()
    if not isolated and (not project_path.is_absolute() or not project_path.is_dir()):
        raise DesktopTaskError('Choose an existing absolute working folder or leave it empty.')
    project = str(project_path.resolve())
    if isolated and not Path(project).is_relative_to(paths.workspaces.resolve()):
        raise DesktopTaskError('The Relay workspace location is outside its configured folder.')
    if not isinstance(title, str) or len(title) > 150 or any(ord(c) < 32 for c in title):
        raise DesktopTaskError('Use a task title of at most 150 characters without control characters.')
    title = title.strip() or (({'openai': 'OpenAI', 'openrouter': 'OpenRouter', 'deepseek': 'DeepSeek'}
                               .get(backend, backend.capitalize()) + ' task') if isolated else '')
    with closing(_database(paths, writable=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not _table(db, 'desktop_creations'):
                raise DesktopTaskError('This Relay service does not yet support desktop task creation. Update and restart it first.')
            existing = db.execute('SELECT * FROM desktop_creations WHERE request_id=?', (request_id,)).fetchone()
            if existing:
                if (existing['backend'], existing['cwd'], existing['title']) != (backend, project, title):
                    raise DesktopTaskError('That desktop request identity belongs to different task details.')
                return {'request_id': request_id, 'status': existing['status'],
                        'task_id': existing['task_id'], 'message': existing['result'] or 'Creation already recorded; it was not submitted again.'}
            heartbeat = db.execute("SELECT value FROM kv WHERE key='health:desktop'").fetchone()
            try:
                value = json.loads(heartbeat[0]) if heartbeat else {}
                ready = value.get('interface_version') == 1 and 0 <= clock() - value.get('last_success', 0) < 20
            except (ValueError, TypeError):
                ready = False
            if not ready:
                raise DesktopTaskError('The Relay service is not ready to create desktop tasks. Refresh service status.')
            if isolated:
                try:
                    project_path.mkdir(parents=True, exist_ok=True)
                    if project_path.is_symlink() or not project_path.is_dir():
                        raise OSError('Invalid isolated workspace')
                except OSError:
                    raise DesktopTaskError('Could not create a Relay workspace for this task.') from None
            db.execute('''INSERT INTO desktop_creations(request_id,backend,cwd,title,status,created)
                          VALUES (?,?,?,?,?,?)''', (request_id, backend, project, title, 'queued', clock()))
        return {'request_id': request_id, 'status': 'queued', 'task_id': None,
                'message': 'Task creation recorded. Refresh Tasks for its result; no provider work was started.'}


def stop(task_id, paths=PATHS):
    if not isinstance(task_id, str) or not task_id or len(task_id) > 180:
        raise DesktopTaskError('Choose an exact task from the list.')
    with closing(_database(paths, writable=True)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT backend FROM backend_tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise DesktopTaskError('Stop is available here for managed provider tasks. Open a Codex task to stop its turn.')
            changed = db.execute("UPDATE backend_jobs SET cancel=1 WHERE thread_id=? AND status IN ('queued','running','waiting') AND cancel=0", (task_id,)).rowcount
        return {'message': 'Stop requested. An already submitted provider request may still finish.' if changed else
                           'This task has no active run to stop.', 'changed': bool(changed)}


class _LocalBridge:
    """Use the existing task-submission rules with local receipts, never Telegram send."""
    def __init__(self, source, task_id, request_id):
        from .bridge import Bridge
        class Local(Bridge):
            channel = 'desktop'

            def target_task(self, message, chat_id):
                return task_id

            def send(self, text, thread_id=None):
                self.last_message = text
                self.message_count += 1
                event_id = f'desktop:{request_id}:{self.message_count}'
                with self.state.db:
                    self.state.db.execute('INSERT INTO outbox(id,thread_id,text,sent) VALUES (?,?,?,1)',
                                          (event_id, thread_id or task_id, text))
                    self.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)',
                                          (event_id, 'desktop'))
        self.bridge = Local(source.state, None, source.config, desktop_factory=source.desktop_factory)
        self.bridge.message_count = 0
        self.bridge.last_message = None


def process_commands(source, limit=1, clock=time.time):
    state = source.state
    for _ in range(limit):
        with state.db:
            command = state.db.execute("SELECT * FROM desktop_commands WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not command:
                break
            changed = state.db.execute("UPDATE desktop_commands SET status='submitting' WHERE request_id=? AND status='queued'",
                                       (command['request_id'],)).rowcount
            if not changed:
                continue
            state.db.execute('INSERT OR REPLACE INTO relay_request_channels VALUES (?,?)',
                             (command['incoming_id'], 'desktop'))
        local = _LocalBridge(source, command['task_id'], command['request_id']).bridge
        try:
            local.submit_text({}, command['prompt'], command['incoming_id'], 0)
            row = state.db.execute('SELECT status FROM incoming WHERE id=?', (command['incoming_id'],)).fetchone()
            incoming = row['status'] if row else None
            status = ('accepted' if incoming in ('queued', 'submitted') else
                      'uncertain' if incoming in ('submitting', 'uncertain') else 'rejected')
            message = local.last_message or ('Instruction was queued.' if status == 'accepted' else
                                             'The service did not confirm submission. Inspect the task before retrying.')
        except Exception:
            state.db.rollback()
            status, message = 'uncertain', 'The service stopped during desktop submission. Inspect the task before sending another instruction.'
        with state.db:
            state.db.execute("UPDATE desktop_commands SET status=?,result=? WHERE request_id=? AND status='submitting'",
                             (status, message, command['request_id']))
    process_creations(source)
    with state.db:
        state.put('health:desktop', {'interface_version': 1, 'last_success': clock()})


def process_creations(source, limit=1):
    from . import backends
    state = source.state
    for _ in range(limit):
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            row = state.db.execute("SELECT * FROM desktop_creations WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return
            try:
                task_id, title, _ = backends.create_task(
                    state, shlex.join([row['backend'], row['cwd'], row['title']]), 0,
                    record_incoming=False, transaction=False, select=False)
                state.db.execute("UPDATE desktop_creations SET status='accepted',task_id=?,result=? WHERE request_id=?",
                                 (task_id, 'Task created. No provider work was started.', row['request_id']))
            except ValueError as exc:
                state.db.execute("UPDATE desktop_creations SET status='rejected',result=? WHERE request_id=?",
                                 (str(exc), row['request_id']))


def recover_commands(state):
    """A prior submitting claim may have reached its target; never replay it."""
    with state.db:
        return state.db.execute("""UPDATE desktop_commands SET status='uncertain',
            result='The service restarted during submission. Inspect the task before sending another instruction.'
            WHERE status='submitting'""").rowcount
