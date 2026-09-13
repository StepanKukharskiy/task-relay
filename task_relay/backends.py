"""Persistent tasks and supervised jobs for backends independent of Codex desktop."""
import json
from contextlib import nullcontext
import os
from pathlib import Path
import shlex
import signal
import subprocess
from .host import HOST, UnsupportedHost
from .credentials import private_json
import time
import uuid
import sys
from task_relay import gemini
from task_relay import api_providers as api

from task_relay.relay_paths import PATHS
ROOT = PATHS.install
DATA = PATHS.data
WORKSPACES = PATHS.workspaces
CLAUDE_PYTHON = DATA / 'claude-venv/bin/python'
ACTIVE = ('queued', 'running', 'waiting')


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS backend_tasks (
        id TEXT PRIMARY KEY, backend TEXT NOT NULL, session_id TEXT NOT NULL,
        cwd TEXT NOT NULL, model TEXT NOT NULL, initialized INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS backend_jobs (
        id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, update_id INTEGER UNIQUE NOT NULL,
        prompt TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
        started_at REAL, finished_at REAL, cancel INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL, result_path TEXT);
      CREATE UNIQUE INDEX IF NOT EXISTS one_active_backend_job ON backend_jobs(thread_id)
        WHERE status IN ('queued','running','waiting');
      CREATE TABLE IF NOT EXISTS tool_requests (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL, thread_id TEXT NOT NULL,
        tool TEXT NOT NULL, input_json TEXT NOT NULL, status TEXT NOT NULL,
        expires_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS speech_tasks (
        source_id TEXT PRIMARY KEY, thread_id TEXT UNIQUE NOT NULL);
    ''')

    gemini.initialize(db)
    api.initialize(db)
    # Internal analytical jobs are consumed locally and never enter Telegram delivery.
    from task_relay.internal_jobs import initialize as initialize_internal
    initialize_internal(db)


def claude_config():
    try:
        config = private_json(DATA/'claude.json')
    except (OSError, ValueError):
        return None
    return config if config.get('auth') == 'account' and config.get('enabled', True) else None


def claude_status():
    if not CLAUDE_PYTHON.is_file():
        return 'runtime missing; open Setup Claude.command'
    if not claude_config():
        return 'setup required; open Setup Claude.command'
    return 'configured (account login; verified when a task runs)'


def task(state, thread_id):
    return state.db.execute('SELECT * FROM backend_tasks WHERE id=?', (thread_id,)).fetchone()


def create_task(state, arg, update_id, prompt=None, capability="text", *, record_incoming=True, transaction=True, select=True):
    parts = shlex.split(arg)
    if len(parts) < 2 or parts[0].lower() not in ('claude', 'gemini', *api.SPECS):
        raise ValueError('Use /new PROVIDER "/absolute/project/path" Optional title. Providers: gemini, claude, openai, qwen, deepseek, openrouter.')
    cwd = Path(parts[1]).expanduser()
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError('Choose an existing absolute project folder. Quote paths containing spaces.')
    cwd = cwd.resolve()
    backend = parts[0].lower()
    title = ' '.join(parts[2:])[:150] or f'{backend.capitalize()}: {cwd.name}'
    config = api.read_config(backend) if backend in api.SPECS else (gemini.read_config() if backend == 'gemini' else claude_config())
    if not config or (backend == 'claude' and not CLAUDE_PYTHON.is_file()):
        raise ValueError(f'Connect {backend.capitalize()} first through /providers.')
    model = (config.get('models', {}).get('text', gemini.DEFAULT_MODELS['text']) if backend == 'gemini' else config.get('model', api.SPECS[backend]['model'] if backend in api.SPECS else 'sonnet'))
    session = str(uuid.uuid4())
    thread_id = backend + ':' + session
    if not transaction and not state.db.in_transaction:
        raise ValueError('Task creation requires an outer transaction.')
    with state.db if transaction else nullcontext():
        state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                         (thread_id, '', 0, title, 'idle', int(time.time())))
        state.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,0)',
                         (thread_id, backend, session, str(cwd), model))
        if prompt is None and record_incoming:
            state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'handled', thread_id))
        state.emoji(thread_id)
        if select:
            state.put('selected', thread_id)
        if prompt is not None:
            enqueue(state, thread_id, prompt, update_id, capability, transaction=transaction)
    return thread_id, title, str(cwd)


def reply_capability(state, thread_id):
    """Image conversations retain their modality until an explicit text request."""
    info = task(state, thread_id)
    if not info or info['backend'] != 'gemini':
        return 'text'
    mode = state.get('gemini-reply-capability:' + thread_id)
    if mode in ('image', 'text'):
        return mode
    # Compatibility for image tasks created before reply mode was recorded,
    # including tasks whose replies were accidentally dispatched as text.
    if state.db.execute('SELECT 1 FROM orchestrator_image_requests WHERE task_id=?', (thread_id,)).fetchone():
        return 'image'
    last = state.db.execute("SELECT r.capability FROM gemini_runs r JOIN backend_jobs j ON j.id=r.job_id WHERE j.thread_id=? AND r.capability IN ('image','text') ORDER BY j.created_at DESC,j.rowid DESC LIMIT 1", (thread_id,)).fetchone()
    return 'image' if last and last[0] == 'image' else 'text'


def enqueue(state, thread_id, prompt, update_id, capability="text", *, transaction=True):
    # Main polling thread is the sole producer. The unique indexes also protect
    # against duplicate Telegram deliveries and concurrent turns for one task.
    row = state.db.execute('SELECT status FROM watched WHERE id=?', (thread_id,)).fetchone()
    if not row or row['status'] != 'idle':
        raise ValueError('This task is busy or needs recovery. Use /status; wait for completion before sending more work.')
    info = task(state, thread_id)
    if state.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_routes'").fetchone() and state.db.execute(
            "SELECT 1 FROM task_routes WHERE task_id=? AND status IN ('queued','opening','submitting','uncertain')", (thread_id,)).fetchone():
        raise ValueError('A routed Codex request owns this task. Check its delivery status before starting another job.')
    if info['backend'] in api.SPECS and capability != 'text':
        raise ValueError('This API adapter supports text conversations. Use /speak for Gemini speech.')
    if info['backend'] == 'claude' and (not claude_config() or not CLAUDE_PYTHON.is_file()):
        raise ValueError('Claude needs local setup. Open Setup Claude.command.')
    job_id = str(uuid.uuid4())
    run = gemini.prepare_run(state, job_id, thread_id, capability) if info['backend'] == 'gemini' else None
    api_run = api.prepare_run(state, job_id, info, prompt) if info['backend'] in api.SPECS else None
    if not transaction and not state.db.in_transaction:
        raise ValueError('Job enqueue requires an outer transaction.')
    with state.db if transaction else nullcontext():
        state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'queued', thread_id))
        state.db.execute('INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES (?,?,?,?,?,?)',
                         (job_id, thread_id, update_id, prompt, 'queued', time.time()))
        from task_relay import relay_channels
        relay_channels.bind(state, 'task', thread_id, relay_channels.request_channel(state, update_id))
        if run:
            state.db.execute('INSERT INTO gemini_runs(job_id,capability,model,response_path,options_json) VALUES (?,?,?,?,?)', run)
            if capability in ('image', 'text'):
                state.put('gemini-reply-capability:' + thread_id, capability)
        if api_run:
            state.db.execute('INSERT INTO api_runs(job_id,model,base_url,response_path,request_json) VALUES (?,?,?,?,?)', api_run)
            state.db.execute('UPDATE api_runs SET workspace=? WHERE job_id=?', (info['cwd'], job_id))
        state.db.execute('UPDATE watched SET status=?,updated_at=? WHERE id=?',
                         ('queued', int(time.time()), thread_id))
    return job_id


def enqueue_speech(state, source_id, prompt, update_id):
    """Run speech independently of a Codex/Claude task, preserving reply routing."""
    config = gemini.read_config()
    if not config:
        raise ValueError('Connect Gemini for speech: /providers → Gemini → Connect / update API key.')
    info = task(state, source_id)
    if info and info['backend'] == 'gemini':
        enqueue(state, source_id, prompt, update_id, 'speech')
        return source_id
    source = state.db.execute('SELECT title FROM watched WHERE id=?', (source_id,)).fetchone()
    source_id = source_id if source else ''
    # The task and job are committed together; retries use the same speech task.
    with state.db:
        existing = state.db.execute('SELECT thread_id FROM speech_tasks WHERE source_id=?', (source_id,)).fetchone()
        if existing:
            tid = existing[0]
            status = state.db.execute('SELECT status FROM watched WHERE id=?', (tid,)).fetchone()[0]
            if status != 'idle':
                raise ValueError(f'Speech is busy or needs recovery. Reply to its queue message with /status, or select it with /use {tid}.')
        else:
            session = str(uuid.uuid4())
            tid = 'gemini:' + session
            title = ('Speech: ' + source['title'])[:150] if source else 'Speech'
            state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                             (tid, '', 0, title, 'idle', int(time.time())))
            state.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,0)',
                             (tid, 'gemini', session, str(ROOT), config.get('models', {}).get('text', gemini.DEFAULT_MODELS['text'])))
            state.db.execute('INSERT INTO speech_tasks VALUES (?,?)', (source_id, tid))
            state.emoji(tid)
        enqueue(state, tid, prompt, update_id, 'speech')
    return tid


def finish(state, job_id, status, summary, cost=None):
    from task_relay.media import queue_attachments
    job = state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (job_id,)).fetchone()
    if not job or job['status'] not in ACTIVE:
        return
    info = task(state, job['thread_id'])
    title = state.db.execute('SELECT title FROM watched WHERE id=?', (job['thread_id'],)).fetchone()[0]
    folder = state.media_dir.parent / 'results'
    folder.mkdir(mode=0o700, exist_ok=True)
    result_path = folder / (job_id + '.md')
    result_path.write_text(summary)
    os.chmod(result_path, 0o600)
    label = {'completed': 'Finished', 'failed': 'Failed', 'stopped': 'Stopped', 'uncertain': 'Needs checking'}[status]
    run = state.db.execute('SELECT model,capability FROM gemini_runs WHERE job_id=?', (job_id,)).fetchone()
    route = state.db.execute('SELECT source_id FROM speech_tasks WHERE thread_id=?', (job['thread_id'],)).fetchone()
    delivery_tid = route[0] if route and route[0] and run and run['capability'] == 'speech' else job['thread_id']
    if delivery_tid != job['thread_id']:
        source = state.db.execute('SELECT title FROM watched WHERE id=?', (delivery_tid,)).fetchone()
        title = 'Speech: ' + source['title']
    api_run = state.db.execute('SELECT model FROM api_runs WHERE job_id=?', (job_id,)).fetchone()
    model = run['model'] if run else (api_run[0] if api_run else info['model'])
    provider = api.SPECS[info['backend']]['name'] if info['backend'] in api.SPECS else info['backend'].capitalize()
    text = f'{label}: {title}\n{provider} · {model}\nTask: {delivery_tid}\n\n{summary}'
    if cost is not None:
        text += f'\n\nEstimated usage value: ${cost:.4f} (not a subscription charge).'
    if status == 'uncertain':
        text += f'\n\nCheck the project and session. Then /recover {job["thread_id"]} to allow a new instruction. This does not replay the old one.'
    else:
        text += '\n\nReply to continue this task.'
    event_id = f'backend:{job_id}:result'
    with state.db:
        state.db.execute('UPDATE backend_jobs SET status=?,finished_at=?,cost_usd=?,result_path=? WHERE id=?',
                         (status, time.time(), cost, str(result_path), job_id))
        state.db.execute('UPDATE watched SET status=?,updated_at=? WHERE id=?',
                         ('uncertain' if status == 'uncertain' else 'idle', int(time.time()), job['thread_id']))
        state.db.execute('UPDATE incoming SET status=? WHERE id=?', (status, job['update_id']))
        state.db.execute("UPDATE tool_requests SET status='expired' WHERE job_id=? AND status='pending'", (job_id,))
        state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                         (event_id, delivery_tid, text))
        attachment_summary = summary
        if info['backend'] in ('gemini', *api.SPECS):
            # A remote model's arbitrary local links never grant filesystem access.
            files = state.db.execute("SELECT path,filename FROM artifacts WHERE job_id=? AND role='output'", (job_id,)).fetchall()
            attachment_summary = '\n'.join(f"[{f['filename']}](<{f['path']}>)" for f in files)
        queue_attachments(state, event_id, delivery_tid, title, attachment_summary, info['cwd'])
        if len(summary) > 2500:
            # Retain the downloadable response alongside the full inline text.
            queue_attachments(state, event_id + ':full', delivery_tid, title,
                              f'[Full response](<{result_path}>)', str(folder))
            state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                             (event_id + ':full', delivery_tid, f'Full {provider} response attached below.'))


def decide(state, request_id, allow):
    with state.db:
        row = state.db.execute('SELECT r.* FROM tool_requests r JOIN backend_jobs j ON j.id=r.job_id '
                               "WHERE r.id=? AND r.status='pending' AND r.expires_at>? "
                               "AND j.status IN ('running','waiting') AND j.cancel=0", (request_id, time.time())).fetchone()
        if not row:
            raise ValueError('That permission request is expired, already answered, or no longer active.')
        state.db.execute('UPDATE tool_requests SET status=? WHERE id=?', ('allowed' if allow else 'denied', request_id))
    return row['thread_id']


class BackendWorker:
    """One managed job per provider; polling and media use other workers."""
    def __init__(self, state, popen=subprocess.Popen, backend="claude"):
        self.state, self.popen, self.backend = state, popen, backend
        self.active = None
        # Never restart an in-flight model turn after service restart.
        for row in state.db.execute("SELECT j.id FROM backend_jobs j JOIN backend_tasks t ON t.id=j.thread_id WHERE j.status IN ('running','waiting') AND t.backend=?", (backend,)).fetchall():
            if backend in api.SPECS and api.resume_job(state, row['id']):
                continue
            if backend == "gemini" and gemini.resume_job(state, row["id"]):
                continue
            finish(state, row['id'], 'uncertain', f'The bridge restarted while {backend.capitalize()} was working. The previous instruction was not replayed.')

    def tick(self):
        if self.active:
            job_id, process, started, stopping = self.active
            row = self.state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (job_id,)).fetchone()
            if process.poll() is not None:
                if row['status'] in ACTIVE:
                    finish(self.state, job_id, 'uncertain', f'{self.backend.capitalize()} exited without a confirmed result. Check the task before continuing.')
                self.active = None
            elif row['cancel'] or time.monotonic() - started > 3600:
                if not stopping:
                    # SIGTERM is handled by our runner, which disconnects the SDK.
                    process.terminate()
                    self.active = (job_id, process, started, time.monotonic())
                elif time.monotonic() - stopping > 10:
                    self.kill_group(process)
            return
        row = self.state.db.execute("SELECT j.* FROM backend_jobs j JOIN backend_tasks t ON t.id=j.thread_id WHERE j.status='queued' AND t.backend=? ORDER BY j.created_at LIMIT 1", (self.backend,)).fetchone()
        if not row:
            return
        if row['cancel']:
            finish(self.state, row['id'], 'stopped', 'Cancelled before the runner started. A previously submitted video operation may still run at Google.' if self.backend == 'gemini' else 'Cancelled before the runner started. No new request was sent.')
            return
        with self.state.db:
            claimed = self.state.db.execute("UPDATE backend_jobs SET status='running',started_at=? WHERE id=? AND status='queued'",
                                            (time.time(), row['id'])).rowcount
            if not claimed:
                return
            self.state.db.execute("UPDATE watched SET status='running' WHERE id=?", (row['thread_id'],))
            self.state.db.execute("UPDATE incoming SET status='submitting' WHERE id=?", (row['update_id'],))
        try:
            db_path = self.state.db.execute('PRAGMA database_list').fetchone()[2]
            runner = 'api_runner.py' if self.backend in api.SPECS else self.backend + '_runner.py'
            process = HOST.spawn([str(CLAUDE_PYTHON) if self.backend == 'claude' else sys.executable, str(ROOT / runner), db_path, row['id'], str(os.getpid())],
                                 cwd=ROOT, popen=self.popen, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except (OSError, UnsupportedHost):
            finish(self.state, row['id'], 'failed', f'The {self.backend.capitalize()} runtime could not start. Your instruction was not sent by this runner.')
            return
        self.active = (row['id'], process, time.monotonic(), 0)

    @staticmethod
    def kill_group(process):
        try:
            HOST.signal_tree(process, force=True)
        except ProcessLookupError:
            pass

    def close(self):
        if not self.active:
            return
        job_id, process, _, _ = self.active
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.kill_group(process)
                process.wait(timeout=3)
        resumed = (api.resume_job(self.state, job_id) if self.backend in api.SPECS else
                   (gemini.resume_job(self.state, job_id) if self.backend == 'gemini' else False))
        if not resumed:
            finish(self.state, job_id, 'uncertain', 'The bridge stopped during a task. The instruction will not be replayed automatically.')
        self.active = None
