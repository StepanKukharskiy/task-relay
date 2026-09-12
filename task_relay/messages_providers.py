"""Messages routing using Task Relay's existing Gemini tasks and worker.

Credentials are shared with the configured relay. Queues/history/delivery state
are separate so the Telegram service cannot consume Messages jobs or results.
"""
import hashlib
import shlex
import time

from task_relay import backends
from task_relay import gemini
from task_relay.bridge import State


class ProviderRouter:
    def __init__(self, path, worker_factory=backends.BackendWorker):
        self.state = State(path)
        self.state.db.execute('''CREATE TABLE IF NOT EXISTS message_requests(
            guid TEXT PRIMARY KEY, update_id INTEGER UNIQUE NOT NULL, job_id TEXT NOT NULL)''')
        self.state.db.commit()
        self.worker = worker_factory(self.state, backend='gemini')

    def submit(self, guid, prompt, cwd):
        old = self.state.db.execute('SELECT job_id FROM message_requests WHERE guid=?', (guid,)).fetchone()
        if old:
            return old['job_id']
        if not gemini.read_config():
            raise ValueError('Gemini is not connected or is disabled. Open Setup Gemini.command on your Mac.')
        # Stable within this independent DB; duplicates cannot launch twice after a crash.
        update_id = int.from_bytes(hashlib.sha256(guid.encode()).digest()[:7], 'big')
        with self.state.db:
            tid = self.state.get('messages:gemini_task')
            if not tid:
                tid, _, _ = backends.create_task(
                    self.state, shlex.join(['gemini', str(cwd), 'Gemini — Messages']), update_id,
                    prompt=prompt)
                self.state.put('messages:gemini_task', tid)
            else:
                backends.enqueue(self.state, tid, prompt, update_id)
            job = self.state.db.execute('SELECT id FROM backend_jobs WHERE update_id=?', (update_id,)).fetchone()
            self.state.db.execute('INSERT INTO message_requests VALUES (?,?,?)', (guid, update_id, job['id']))
        return job['id']

    def status(self):
        if not gemini.read_config():
            return 'not connected / disabled'
        tid = self.state.get('messages:gemini_task')
        if not tid:
            return 'ready; no Messages conversation yet'
        row = self.state.db.execute('SELECT w.status,b.model FROM watched w JOIN backend_tasks b ON b.id=w.id WHERE w.id=?', (tid,)).fetchone()
        return f"{row['status']} · {row['model']}" if row else 'conversation unavailable'

    def new_conversation(self):
        tid = self.state.get('messages:gemini_task')
        if tid and self.state.db.execute("SELECT 1 FROM backend_jobs WHERE thread_id=? AND status IN ('queued','running','waiting')", (tid,)).fetchone():
            raise ValueError('Wait for Gemini to finish, or use /stop gemini before starting a new conversation.')
        with self.state.db:
            self.state.put('messages:gemini_task', None)

    def stop(self):
        tid = self.state.get('messages:gemini_task')
        with self.state.db:
            count = self.state.db.execute("UPDATE backend_jobs SET cancel=1 WHERE thread_id=? AND status IN ('queued','running','waiting')", (tid,)).rowcount
        return bool(count)

    def tick(self, pilot):
        self.worker.tick()
        # Commit the delivery first, then acknowledge the provider outbox. The
        # deterministic event key makes a restart between these commits harmless.
        for row in self.state.db.execute('SELECT id,text FROM outbox WHERE sent=0 ORDER BY rowid LIMIT 20').fetchall():
            text = row['text'].replace('Reply to continue this task.', 'Use /gemini YOUR INSTRUCTION to continue.')
            with pilot.store.db:
                pilot.notify(row['id'], text, provider='Gemini')
            with self.state.db:
                self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['id'],))
        with self.state.db:
            self.state.put('messages:worker_health', {'last_success': time.time()})

    def close(self):
        try:
            self.worker.close()
        finally:
            self.state.db.close()
