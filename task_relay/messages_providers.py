"""Messages routing using Task Relay's existing Gemini tasks and worker.

Uses the main database and the main service's worker. Channel records keep
Messages replies separate from Telegram; this adapter never starts a worker.
"""
import hashlib
import shlex
import time

from task_relay import backends
from task_relay import gemini, relay_channels
from orchestrator.storage import transaction
from task_relay.bridge import State


class ProviderRouter:
    def __init__(self, path=None, *, state=None, require_ready=True):
        from task_relay.messages_storage import initialize
        self.owns_state = state is None
        self.state = State(path) if state is None else state
        self.require_ready = require_ready
        initialize(self.state.db)
        self.state.db.commit()

    def submit(self, guid, prompt, cwd):
        state = self.state
        with transaction(state.db):
            old = state.db.execute('SELECT r.job_id,j.prompt FROM messages_provider_requests r '
                                   'JOIN backend_jobs j ON j.id=r.job_id WHERE r.guid=?', (guid,)).fetchone()
            if old:
                if old['prompt'] != prompt:
                    raise ValueError('This message already has a different saved instruction.')
                return old['job_id']
            if not gemini.read_config():
                raise ValueError('Gemini is not connected or is disabled. Connect Gemini through /providers in Telegram.')
            if self.require_ready and time.time() - state.get('health:gemini', {}).get('last_success', 0) >= 60:
                raise ValueError('The shared Relay Gemini worker is offline. No job was queued; restart Task Relay.')
            # Negative IDs distinguish direct Messages input from Telegram updates.
            update_id = -int.from_bytes(hashlib.sha256(('messages:gemini:' + guid).encode()).digest()[:7], 'big') - 1
            state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)', (update_id, 'messages'))
            scoped = relay_channels.ScopedState(state, 'messages')
            tid = state.get('messages:gemini_task')
            if not tid:
                tid, _, _ = backends.create_task(
                    scoped, shlex.join(['gemini', str(cwd), 'Gemini — Messages']), update_id,
                    prompt=prompt, transaction=False)
                state.put('messages:gemini_task', tid)
            else:
                backends.enqueue(scoped, tid, prompt, update_id, transaction=False)
            job = state.db.execute('SELECT id FROM backend_jobs WHERE update_id=?', (update_id,)).fetchone()
            state.db.execute('INSERT INTO messages_provider_requests VALUES (?,?,?)', (guid, update_id, job['id']))
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

    def close(self):
        if self.owns_state:
            self.state.db.close()
