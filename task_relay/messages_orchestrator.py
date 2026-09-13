"""Authenticated text interface to the shared orchestrator; no Telegram calls."""
import json
import secrets
import time

from task_relay import orchestrator_chat
from task_relay import relay_channels
from task_relay.bridge import State


class OrchestratorRouter:
    def __init__(self, path=None, require_ready=True, *, state=None):
        self.owns_state = state is None
        self.state = State(path) if state is None else state
        self.require_ready = require_ready
        self.state.db.executescript('''
          CREATE TABLE IF NOT EXISTS messages_orchestrator_requests (
            guid TEXT PRIMARY KEY, request_id INTEGER UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS messages_orchestrator_exports (
            event_id TEXT PRIMARY KEY, delivery_key TEXT UNIQUE NOT NULL, text TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS messages_orchestrator_cards (
            code TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, options TEXT NOT NULL);
        ''')

    def ready(self):
        health = self.state.get('health:scan', {})
        worker = self.state.get('health:orchestrator-chat', {})
        # The version proves the shared service has channel routing loaded. Use
        # its independent local scan heartbeat: neither Telegram network failures
        # nor a long model request should prevent phone submissions.
        return worker.get('interface_version') == 1 and time.time() - health.get('last_success', 0) < 60

    def bind_task(self, task_id):
        with self.state.db:
            relay_channels.bind(self.state, 'task', task_id, 'messages')

    def submit(self, guid, prompt):
        if not prompt.strip():
            raise ValueError('Send an instruction after /orchestrator, or just write a message.')
        if len(prompt) > 16000:
            raise ValueError('Please keep orchestrator messages under 16,000 characters.')
        state = self.state
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            old = state.db.execute('SELECT request_id FROM messages_orchestrator_requests WHERE guid=?', (guid,)).fetchone()
            if old:
                return old[0]
            if self.require_ready and not self.ready():
                raise ValueError('The shared orchestrator service is offline. Your instruction was not queued; restart Task Relay on the Mac.')
            name, model = orchestrator_chat.provider(state)
            if state.db.execute("SELECT count(*) FROM orchestrator_chats c JOIN relay_request_channels r ON r.request_id=c.id "
                                "WHERE r.channel='messages' AND c.status IN ('queued','sending')").fetchone()[0] >= 5:
                raise ValueError('Five Messages requests are pending. Wait for a reply before sending more.')
            latest = state.db.execute('SELECT COALESCE(max(request_id),0) FROM messages_orchestrator_requests').fetchone()[0]
            ident = max(int(time.time() * 1_000_000), latest + 1)
            last = state.db.execute("SELECT c.focus FROM orchestrator_chats c JOIN relay_request_channels r ON r.request_id=c.id "
                                    "WHERE r.channel='messages' AND c.status='answered' ORDER BY c.id DESC LIMIT 1").fetchone()
            state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)', (ident, 'messages'))
            state.db.execute('INSERT INTO messages_orchestrator_requests VALUES (?,?)', (guid, ident))
            state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (?,?,?,?,?,?)',
                             (ident, prompt, last[0] if last else None, name, model, time.time()))
        return ident

    def status(self):
        row = self.state.db.execute("SELECT c.status FROM orchestrator_chats c JOIN relay_request_channels r ON r.request_id=c.id "
                                    "WHERE r.channel='messages' ORDER BY c.id DESC LIMIT 1").fetchone()
        return ('ready' if self.ready() else 'service offline') + (' · latest request: ' + row[0] if row else '')

    def browser_setup(self,guid,argument):
        from . import browser_setup
        if self.require_ready and not self.ready():
            raise ValueError('The shared Relay service is offline; browser setup was not queued.')
        return browser_setup.command(self.state,argument,'messages:'+guid,'messages')

    def acknowledge(self, pilot):
        for row in self.state.db.execute('SELECT e.* FROM messages_orchestrator_exports e JOIN outbox o ON o.id=e.event_id WHERE o.sent=0').fetchall():
            parts = pilot.store.db.execute('SELECT status FROM messages_delivery WHERE substr(id,1,?)=?',
                                           (len(row['delivery_key'])+1, row['delivery_key']+':')).fetchall()
            if parts and all(part[0] == 'sent' for part in parts):
                with self.state.db:
                    self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['event_id'],))
                    card = self.state.db.execute('SELECT rowid FROM messages_orchestrator_cards WHERE event_id=?', (row['event_id'],)).fetchone()
                    if card:
                        orchestrator_chat.remember(self.state, row['event_id'], -1, card[0])
                    # Text delivery reports file locations; it never claims binary delivery.
                    self.state.db.execute("UPDATE media_outbox SET status='skipped' WHERE event_id=? AND status='pending'", (row['event_id'],))

    def tick(self, pilot):
        self.acknowledge(pilot)
        for row in relay_channels.pending(self.state, 'messages'):
            with self.state.db:
                direct = self.state.db.execute('SELECT 1 FROM messages_provider_requests r '
                    'JOIN backend_jobs j ON j.id=r.job_id WHERE j.thread_id=?', (row['thread_id'],)).fetchone()
                saved = self.state.db.execute('SELECT * FROM messages_orchestrator_exports WHERE event_id=?', (row['id'],)).fetchone()
                if not saved:
                    text = row['text'].removeprefix('Orchestrator\n')
                    text = text.replace('tap the button to apply', 'choose an option below to apply')
                    text = text.replace('Reply to continue this task.', 'Use /gemini YOUR INSTRUCTION to continue.' if direct
                                        else 'Send a new instruction to the orchestrator to continue this task.')
                    markup = orchestrator_chat.controls(self.state, row['id']) or {}
                    options = [b for line in markup.get('inline_keyboard', []) for b in line if 'callback_data' in b]
                    if options:
                        code = secrets.token_hex(3)
                        self.state.db.execute('INSERT INTO messages_orchestrator_cards VALUES (?,?,?)',
                                              (code, row['id'], json.dumps(options)))
                        text += '\n\n' + '\n'.join(f'{i}. {b["text"]}' for i, b in enumerate(options, 1))
                        text += f'\n\nReply with /choose {code} NUMBER (for example, /choose {code} 1).'
                    files = self.state.db.execute('SELECT DISTINCT filename,path FROM media_outbox WHERE event_id=?', (row['id'],)).fetchall()
                    if files:
                        text += '\n\nFiles saved on the Mac (Messages currently sends text only):\n'
                        text += '\n'.join(f'{f["filename"]}: {f["path"]}' for f in files)
                    key = 'shared-orchestrator:' + row['id']
                    if direct:
                        key = row['id']  # Preserve the original Messages provider delivery identity.
                    parts = row['id'].split(':')
                    if row['thread_id'] == pilot.task_id and len(parts) == 3 and parts[2] in ('task_complete', 'turn_aborted'):
                        # The original pilot watches this task too. Both paths use
                        # one delivery key, including when the pilot wins the race.
                        key = ':'.join(parts[1:])
                    self.state.db.execute('INSERT INTO messages_orchestrator_exports VALUES (?,?,?)', (row['id'], key, text))
                    saved = {'delivery_key': key, 'text': text}
                # Production uses one connection: export, choices and outgoing
                # parts commit together. Sent acknowledgement follows transport.
                if pilot.store.db is self.state.db:
                    if not pilot.store.db.execute('SELECT 1 FROM messages_delivery WHERE id=?', (saved['delivery_key'] + ':1',)).fetchone():
                        pilot.notify(saved['delivery_key'], saved['text'], provider='Gemini' if direct else 'Orchestrator')
            if pilot.store.db is not self.state.db:
                with pilot.store.db:
                    if not pilot.store.db.execute('SELECT 1 FROM messages_delivery WHERE id=?', (saved['delivery_key'] + ':1',)).fetchone():
                        pilot.notify(saved['delivery_key'], saved['text'], provider='Gemini' if direct else 'Orchestrator')

    def choose(self, pilot, guid, argument):
        words = argument.split()
        if len(words) != 2 or not words[1].isdigit():
            raise ValueError('Use /choose CODE NUMBER from the message containing the choices.')
        self.acknowledge(pilot)
        card = self.state.db.execute('SELECT rowid,* FROM messages_orchestrator_cards WHERE code=?', (words[0].lower(),)).fetchone()
        if not card:
            raise ValueError('Unknown choice code. Use the code printed with the choices.')
        options = json.loads(card['options'])
        index = int(words[1]) - 1
        if not 0 <= index < len(options):
            raise ValueError('That option number is not on this card.')
        sent = self.state.db.execute('SELECT sent FROM outbox WHERE id=?', (card['event_id'],)).fetchone()
        if not sent or sent[0] != 1:
            raise ValueError('Wait for the complete choices message before choosing.')
        active = orchestrator_chat.controls(self.state, card['event_id']) or {}
        valid = {b.get('callback_data') for line in active.get('inline_keyboard', []) for b in line}
        choice = options[index]['callback_data']
        if choice not in valid:
            raise ValueError('That choice has expired or was already handled. Send a fresh request.')
        replies = []
        class CallbackSink:
            def call(self, method, **kwargs):
                if method != 'answerCallbackQuery':
                    raise ValueError('This control is not available through Messages.')
                replies.append(kwargs.get('text', ''))
                return True
        class Adapter:
            state = relay_channels.ScopedState(self.state, 'messages')
            telegram = CallbackSink()
            def send(self, text, thread_id=None):
                replies.append(text)
        handled = orchestrator_chat.callback(Adapter(), {'callback_query': {
            'id': guid, 'data': choice, 'from': {'id': -1, 'is_bot': False},
            'message': {'message_id': card['rowid'], 'chat': {'id': -1, 'type': 'private'}}}})
        if not handled:
            raise ValueError('This control is not available through Messages.')
        with pilot.store.db:
            pilot.notify(guid, '\n'.join(dict.fromkeys(t for t in replies if t)) or 'Choice received.', provider='Orchestrator')

    def close(self):
        if self.owns_state:
            self.state.db.close()
