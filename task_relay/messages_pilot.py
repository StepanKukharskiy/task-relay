#!/usr/bin/env python3
"""Paired iMessage interface to the shared orchestrator and direct agent providers."""
import argparse
import datetime as dt
from task_relay.host import HOST
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import signal
import sqlite3
import subprocess
import threading
import time

from task_relay.bridge import Desktop, BridgeError, local_tasks, recent_status, complete_offset, checkpoint_anchor, split_text

from task_relay.relay_paths import PATHS
ROOT = PATHS.install
HELP = ('Ordinary text goes to the orchestrator.\n'
        '/orchestrator YOUR INSTRUCTION — talk to the orchestrator\n/routing — where your messages go\n'
        '/choose CODE NUMBER — answer the choices on a card\n'
        '/browser TASK — plan a browser task; connect|status|cancel — Perplexity sign-in\n'
        '/ping — check Messages connection\n/status — check the task\n'
        '/gemini YOUR INSTRUCTION — talk to Gemini\n/codex YOUR INSTRUCTION — continue this Codex task\n'
        '/ask YOUR INSTRUCTION — continue the selected provider\n'
        '/new gemini — start a fresh Gemini conversation\n/stop gemini — cancel Gemini work\n'
        '/help — these commands\n\n'
        'Use /gemini or /codex without text to select a provider. Text conversations only. '
        'Codex approvals and questions stay on the Mac. Keep the Mac awake; keep Codex open for Codex tasks.')


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else 0
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 0


def write_health(folder, status, detail=''):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = folder / f'health.{os.getpid()}.tmp'
    temporary.write_text(json.dumps({'pid': os.getpid(), 'updated_at': time.time(),
                                     'status': status, 'detail': detail}) + '\n')
    temporary.replace(folder / 'health.json')


class Store:
    def __init__(self, path=None, *, state=None):
        from task_relay.messages_storage import initialize
        if state is None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.db = sqlite3.connect(path)
            os.chmod(path, 0o600)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA busy_timeout=5000')
        else:
            self.db = state.db
        initialize(self.db)
        self.db.commit()
        with self.db:
            self.db.execute("UPDATE messages_commands SET status='uncertain' WHERE status='submitting'")
            self.db.execute("UPDATE messages_delivery SET status='uncertain' WHERE status='sending'")

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM messages_settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO messages_settings VALUES (?,?)', (key, json.dumps(value)))


class Messages:
    def __init__(self, binary):
        self.binary = binary

    def verify_chat(self, chat_id, guid):
        # Recent macOS versions use any;-; for actual iMessage conversations.
        # Resolve their service from chat metadata, never from the prefix alone.
        result = subprocess.run([self.binary, 'chats', '--limit', '1000', '--json'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise BridgeError('Could not verify the pairing conversation. Check Messages access.')
        for line in result.stdout.splitlines():
            chat = json.loads(line)
            if chat.get('id') == chat_id and chat.get('guid') == guid:
                return chat.get('service') == 'iMessage' and chat.get('is_group') is False
        return False

    def send(self, chat, text):
        from task_relay import channel_policy
        if hasattr(self, 'policy_path'):
            channel_policy.require_outgoing(self.policy_path, 'messages')
        # Explicit iMessage and exact paired GUID; never fall back to SMS.
        result = subprocess.run([self.binary, 'send', '--chat-guid', chat['guid'],
                                 '--service', 'imessage', '--no-sms-fallback', '--text', text],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise BridgeError('Messages send failed or has an uncertain outcome. '
                              'Check Automation permission and the conversation; it will not be retried.')


class Pilot:
    def __init__(self, store, transport, task_id, desktop_factory=Desktop, task_reader=local_tasks, providers=None, orchestrator=None):
        task_id = task_id or store.get('task_id')
        if not task_id:
            raise BridgeError('Choose a Codex task with --task TASK_UUID for the first setup.')
        self.store, self.transport = store, transport
        from task_relay import channel_policy
        transport.policy_path = channel_policy.database_path(store.db)
        self.task_id, self.desktop_factory, self.task_reader = task_id, desktop_factory, task_reader
        self.providers = providers
        self.orchestrator = orchestrator
        self.started = time.time()
        self.token = secrets.token_hex(5)
        self.expires = self.started + 3600
        previous = store.get('task_id')
        if previous and previous != task_id:
            raise BridgeError('Messages is paired to another task. Preserve or explicitly reset the existing pairing first.')
        with store.db:
            store.put('task_id', task_id)

    def task(self):
        match = next((t for t in self.task_reader() if t['id'] == self.task_id), None)
        if not match:
            raise BridgeError('The configured Codex task is unavailable or archived.')
        return match

    def baseline(self):
        path = Path(self.task()['rollout_path'])
        offset = complete_offset(path)
        self.store.put('checkpoint', [str(path), offset, checkpoint_anchor(path, offset)])
        self.store.put('paired_since', time.time())

    def notify(self, key, text, provider='Codex'):
        chunks = split_text(text, limit=2800)
        for i, part in enumerate(chunks, 1):
            header = '🤖 ' + provider + (f' ({i}/{len(chunks)})' if len(chunks) > 1 else '')
            self.store.db.execute('INSERT OR IGNORE INTO messages_delivery VALUES (?,?,?)',
                                  (f'{key}:{i}', header + '\n\n' + part, 'pending'))

    def receive(self, msg):
        from task_relay import channel_policy
        if not channel_policy.accepting(self.store.db, 'messages', timestamp(msg.get('created_at'))):
            return
        # Self-chat inputs sync as outbound. Never accept anyone else's incoming messages,
        # group traffic, reactions, absent routing metadata, or stale/offline commands.
        if (msg.get('is_from_me') is not True or msg.get('is_group') is not False
                or msg.get('is_reaction') or not isinstance(msg.get('guid'), str)
                or not msg['guid'] or not isinstance(msg.get('chat_id'), int)
                or msg['chat_id'] <= 0 or not isinstance(msg.get('chat_guid'), str)
                or not msg['chat_guid'].startswith(('iMessage;-;', 'any;-;'))):
            return
        created = timestamp(msg.get('created_at'))
        if created < max(self.started - 2, time.time() - 600) or created > time.time() + 60:
            return
        text = msg.get('text')
        if not isinstance(text, str):
            return
        raw_text = text
        text = text.strip()
        chat = self.store.get('chat')
        if not chat:
            if time.time() > self.expires or not secrets.compare_digest(text.encode(), ('/pair ' + self.token).encode()):
                return
            if not self.transport.verify_chat(msg['chat_id'], msg['chat_guid']):
                print('Pairing refused: the conversation could not be verified as a direct iMessage chat.', flush=True)
                return
            with self.store.db:
                self.baseline()
                self.store.put('chat', {'id': msg['chat_id'], 'guid': msg['chat_guid']})
                self.store.db.execute('INSERT OR IGNORE INTO messages_commands VALUES (?,?)', (msg['guid'], 'paired'))
                title = self.task()['title'] or self.task_id
                self.notify('paired', f'Paired to: {title}\n\n' + HELP)
            print('Paired. Waiting for an instruction from your phone.', flush=True)
            return
        if msg['chat_id'] != chat['id'] or msg['chat_guid'] != chat['guid']:
            return
        if not text or text.startswith('🤖'):
            return  # Reserved relay header on EVERY outgoing part prevents self-chat loops.
        guid = msg['guid']
        from . import browser_research
        if browser_research.request_text(raw_text) is not None:
            if self.store.db.execute('SELECT 1 FROM messages_commands WHERE guid=?', (guid,)).fetchone():
                return
            try:
                if not self.orchestrator:
                    raise ValueError('The shared Relay connection is unavailable.')
                from orchestrator.storage import transaction
                # Commit the exact request first. A legacy separate store can
                # replay this receipt safely if command acknowledgement is lost.
                with transaction(self.orchestrator.state.db):
                    browser_research.enqueue(self.orchestrator.state, 'messages:' + guid, raw_text, 'messages')
                    if self.store.db is self.orchestrator.state.db:
                        self.store.db.execute('INSERT INTO messages_commands VALUES (?,?)', (guid, 'received'))
                if self.store.db is not self.orchestrator.state.db:
                    with self.store.db:self.store.db.execute('INSERT OR IGNORE INTO messages_commands VALUES (?,?)', (guid, 'received'))
            except ValueError as exc:
                with self.store.db:self.notify(guid, str(exc), provider='Perplexity')
            return
        with self.store.db:
            inserted = self.store.db.execute('INSERT OR IGNORE INTO messages_commands VALUES (?,?)',
                                             (guid, 'received')).rowcount
        if not inserted:
            return
        if not text.startswith('/'):
            self.orchestrate(guid, raw_text)
            return
        words = text.split(maxsplit=1)
        command, argument = words[0].lower(), words[1].strip() if len(words) > 1 else ''
        if command == '/templates':
            from .workflow_library import describe
            try:result=describe(argument)
            except ValueError as exc:result=str(exc)
            with self.store.db:self.notify(guid,result,provider='Orchestrator')
            return
        if command == '/browser':
            from .browser_requests import is_request
            if is_request(raw_text):
                self.orchestrate(guid,raw_text)
                return
            try:
                if not self.orchestrator:raise ValueError('The shared Relay connection is unavailable.')
                result=self.orchestrator.browser_setup(guid,argument)
            except ValueError as exc:result=str(exc)
            with self.store.db:self.notify(guid,result,provider='Orchestrator')
            return
        if command == '/routing' or (command == '/orchestrator' and argument == 'off'):
            with self.store.db:
                self.notify(guid, 'New messages go to the orchestrator. /codex and /gemini address those agents directly. '
                            '/ask continues the provider selected explicitly; selecting a provider does not redirect ordinary text.', provider='Orchestrator')
            return
        if command == '/orchestrator':
            if argument:
                self.orchestrate(guid, argument)
            else:
                with self.store.db:
                    self.notify(guid, 'Ordinary messages already go to the orchestrator. Send your task or question.\n'
                                'Use /codex or /gemini for a direct instruction to that agent.', provider='Orchestrator')
            return
        if command == '/choose':
            try:
                if not self.orchestrator:
                    raise ValueError('The orchestrator connection is unavailable. Restart Messages Relay.')
                self.orchestrator.choose(self, guid, argument)
            except ValueError as exc:
                with self.store.db:
                    self.notify(guid, str(exc), provider='Orchestrator')
            return
        if command in ('/gemini', '/codex'):
            selected = command[1:]
            with self.store.db:
                self.store.put('selected_provider', selected)
                if not argument:
                    self.notify(guid, f'{selected.capitalize()} selected. Use /ask YOUR INSTRUCTION.', provider='Messages Relay')
            if argument:
                self.route(guid, argument, selected)
            return
        if command == '/ask' and argument:
            self.route(guid, argument, self.store.get('selected_provider', 'codex'))
            return
        if command in ('/new', '/stop') and argument.lower() == 'gemini':
            try:
                if not self.providers:
                    raise ValueError('The Gemini worker is unavailable. Restart Messages Relay.')
                if command == '/new':
                    self.providers.new_conversation()
                    reply = 'Fresh Gemini conversation selected. Use /gemini YOUR INSTRUCTION.'
                    with self.store.db:
                        self.store.put('selected_provider', 'gemini')
                else:
                    reply = ('Cancellation requested. Google may still finish a request already submitted.'
                             if self.providers.stop() else 'Gemini has no active work to cancel.')
            except ValueError as exc:
                reply = str(exc)
            with self.store.db:
                self.notify(guid, reply, provider='Gemini')
            return
        with self.store.db:
            if command == '/ping':
                self.notify(guid, 'Pong — your phone is connected to the Messages pilot.')
            elif command == '/status':
                task = self.task()
                pending = self.store.get('pending')
                self.notify(guid, f"Selected: {self.store.get('selected_provider', 'codex').capitalize()}\n"
                            + 'Ordinary messages: Orchestrator\n'
                            + ('Orchestrator: ' + self.orchestrator.status() + '\n' if self.orchestrator else '')
                            + f"Codex: {recent_status(task['rollout_path'])}\nTask: {task['title']}"
                            + ('\nAn instruction is awaiting completion or acceptance is uncertain.' if pending else '')
                            + ('\nGemini: ' + self.providers.status() if self.providers else '')
                            + '\nFor permission requests or questions, open Codex on the Mac.')
            else:
                self.notify(guid, HELP)

    def orchestrate(self, guid, prompt):
        try:
            if not self.orchestrator:
                raise ValueError('The orchestrator connection is unavailable. Restart Messages Relay.')
            self.orchestrator.submit(guid, prompt)
            with self.store.db:
                self.store.db.execute("UPDATE messages_commands SET status='queued' WHERE guid=?", (guid,))
        except ValueError as exc:
            with self.store.db:
                self.store.db.execute("UPDATE messages_commands SET status='failed' WHERE guid=?", (guid,))
                self.notify(guid, str(exc), provider='Orchestrator')

    def route(self, guid, prompt, provider):
        if provider == 'codex':
            self.submit(guid, prompt)
            return
        try:
            if not self.providers:
                raise ValueError('The Gemini worker is unavailable. Restart Messages Relay.')
            if len(prompt) > 20000:
                raise ValueError('Please limit an instruction to 20,000 characters.')
            self.providers.submit(guid, prompt, self.task()['cwd'])
            reply = 'Queued for Gemini. I’ll send the result here. Use /ask for follow-ups or /codex to switch.'
            status = 'queued'
        except (ValueError, BridgeError) as exc:
            reply, status = str(exc), 'failed'
        with self.store.db:
            self.store.db.execute('UPDATE messages_commands SET status=? WHERE guid=?', (status, guid))
            self.notify(guid, reply, provider='Gemini')

    def submit(self, guid, prompt):
        if len(prompt) > 20000:
            with self.store.db:
                self.notify(guid, 'Please limit this pilot instruction to 20,000 characters.')
            return
        phase = 'received'
        try:
            task = self.task()
            if self.store.get('pending') or recent_status(task['rollout_path']) != 'idle':
                with self.store.db:
                    self.notify(guid, 'The task is busy or its state is uncertain. This instruction was not sent. '
                                'Wait for completion or check Codex on the Mac.')
                return
            with self.desktop_factory() as desktop:
                owner = desktop.ready_owner(self.task_id)
                if recent_status(task['rollout_path']) != 'idle':
                    raise BridgeError('The task became busy. This instruction was not sent.')
                if self.orchestrator:
                    self.orchestrator.bind_task(self.task_id)
                # Persist before IPC. A timeout or process crash must never replay an instruction.
                with self.store.db:
                    self.store.db.execute("UPDATE messages_commands SET status='submitting' WHERE guid=?", (guid,))
                    self.store.put('pending', {'guid': guid, 'since': time.time()})
                phase = 'submitting'
                desktop.start(self.task_id, prompt, owner)
            with self.store.db:
                self.store.db.execute("UPDATE messages_commands SET status='submitted' WHERE guid=?", (guid,))
                self.notify(guid, 'Sent to Codex. The final reply will arrive here. '
                            'If it needs permission or asks a question, answer in Codex on the Mac.')
        except Exception:
            with self.store.db:
                uncertain = phase == 'submitting'
                self.store.db.execute('UPDATE messages_commands SET status=? WHERE guid=?',
                                      ('uncertain' if uncertain else 'failed', guid))
                self.notify(guid, 'Codex acceptance is uncertain. Check the Mac before resending.' if uncertain
                            else 'Could not connect to an idle Codex task. Your instruction was not sent.')

    def scan(self):
        if not self.store.get('chat'):
            return
        path = Path(self.task()['rollout_path'])
        checkpoint = self.store.get('checkpoint')
        if not checkpoint:
            with self.store.db:
                self.baseline()
            return
        old_path, offset, anchor = checkpoint
        if (str(path) != old_path or path.stat().st_size < offset
                or checkpoint_anchor(path, offset) != anchor):
            offset = 0  # Event timestamps and IDs guard against replay after rewrites.
        with self.store.db, path.open('rb') as stream:
            stream.seek(offset)
            for _ in range(2000):
                before = stream.tell()
                line = stream.readline()
                if not line or not line.endswith(b'\n'):
                    stream.seek(before)
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') != 'event_msg' or timestamp(event.get('timestamp')) < self.store.get('paired_since', 0):
                    continue
                payload = event.get('payload', {})
                kind, turn = payload.get('type'), payload.get('turn_id')
                if kind not in ('task_complete', 'turn_aborted') or not turn:
                    continue
                event_key = f'{turn}:{kind}'
                if self.store.db.execute('SELECT 1 FROM messages_delivery WHERE id=?', (event_key + ':1',)).fetchone():
                    continue
                pending = self.store.get('pending')
                if not pending or timestamp(event.get('timestamp')) >= pending['since']:
                    self.store.put('pending', None)
                self.notify(f'{turn}:{kind}', ('Finished' if kind == 'task_complete' else 'Stopped')
                            + '\n\n' + (payload.get('last_agent_message') or 'Open Codex for details.'))
            offset = stream.tell()
            self.store.put('checkpoint', [str(path), offset, checkpoint_anchor(path, offset)])

    def deliver(self):
        from task_relay import channel_policy
        if not channel_policy.outgoing(self.store.db, 'messages'):
            return
        chat = self.store.get('chat')
        if not chat:
            return
        # Hold the remaining parts of an ambiguous reply. Independent replies
        # must not be stranded behind it, and uncertainty is never acceptance.
        row = None
        candidates = self.store.db.execute("SELECT * FROM messages_delivery WHERE status!='sent' ORDER BY rowid").fetchall()
        held = {item['id'].rsplit(':', 1)[0] for item in candidates if item['status'] != 'pending'}
        for candidate in candidates:
            if candidate['id'].rsplit(':', 1)[0] in held:
                continue
            if (candidate['status'] == 'pending' and candidate['id'].startswith('shared-orchestrator:proactive:')
                    and channel_policy.read(self.store.db)['proactive'] == 'none'):
                continue
            row = candidate
            break
        if not row or row['status'] != 'pending':
            return
        with self.store.db:
            self.store.db.execute("UPDATE messages_delivery SET status='sending' WHERE id=?", (row['id'],))
        try:
            self.transport.send(chat, row['text'])
        except channel_policy.ChannelPaused:
            with self.store.db:
                self.store.db.execute("UPDATE messages_delivery SET status='pending' WHERE id=?", (row['id'],))
            return
        except Exception as exc:
            with self.store.db:
                self.store.db.execute("UPDATE messages_delivery SET status='uncertain' WHERE id=?", (row['id'],))
                self.store.put('delivery_failure:' + row['id'], {
                    'delivery_id': row['id'], 'status': 'uncertain', 'at': time.time(),
                    'error_type': type(exc).__name__, 'automatic_resend': False})
            raise BridgeError('Message delivery is uncertain. Check Messages and Automation permission. '
                              'No automatic resend. See docs/messages-pilot.md for recovery.') from None
        with self.store.db:
            self.store.db.execute("UPDATE messages_delivery SET status='sent' WHERE id=?", (row['id'],))

    def delivery_attention(self):
        count = self.store.db.execute("SELECT count(*) FROM messages_delivery WHERE status='uncertain'").fetchone()[0]
        if not count:
            return ''
        return (f'{count} earlier message part(s) have unconfirmed delivery and remain held for review. '
                'New messages can receive replies. No automatic resend.')


def run(args):
    from task_relay.messages_providers import ProviderRouter
    from task_relay.messages_orchestrator import OrchestratorRouter
    folder = Path(args.state).resolve()
    if folder != PATHS.messages.resolve():
        raise BridgeError('Messages uses one shared Relay database. Use TASK_RELAY_DATA_DIR for a separate installation; '
                          '--state cannot create a second pairing against the same database.')
    binary = shutil.which('imsg') or '/opt/homebrew/bin/imsg'
    result = subprocess.run([binary, 'chats', '--limit', '1', '--json'], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        if os.environ.get('TASK_RELAY_MESSAGES_OWNER')=='task-relay-app':
            raise BridgeError('Messages access is blocked. In Task Relay → Channels → Messages → Permissions, add Task Relay.app to Full Disk Access, then stop/start the Messages connection in Task Relay.')
        launcher = 'Messages Relay' if args.background else 'Terminal'
        raise BridgeError(f'Messages access is blocked. Enable {launcher} in System Settings → Privacy & Security → '
                          f'Full Disk Access, then restart {launcher}.')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / 'pilot.lock').open('w') as lock:
        try:
            HOST.lock(lock)
        except BlockingIOError:
            raise BridgeError('The Messages pilot is already running.') from None
        from task_relay.messages_storage import require_consolidated
        require_consolidated(PATHS.state, folder)
        from task_relay.bridge import State
        shared = State(PATHS.state)
        store = Store(state=shared)
        provider_router = None
        orchestrator_router = None
        try:
            provider_router = ProviderRouter(state=shared)
            orchestrator_router = OrchestratorRouter(state=shared)
            pilot = Pilot(store, Messages(binary), args.task, providers=provider_router, orchestrator=orchestrator_router)
            task = pilot.task()
            print('Messages pilot — ' + (task['title'] or pilot.task_id), flush=True)
            if args.ack_delivery:
                with store.db:
                    count = store.db.execute("UPDATE messages_delivery SET status='sent' WHERE id=? AND status='uncertain'",
                                             (args.ack_delivery,)).rowcount
                if not count:
                    raise BridgeError('No uncertain delivery matches that ID.')
            if args.clear_pending:
                if recent_status(task['rollout_path']) != 'idle':
                    raise BridgeError('Cannot clear the pending marker while the task is not idle.')
                with store.db:
                    store.put('pending', None)
            uncertain = store.db.execute("SELECT id FROM messages_delivery WHERE status='uncertain'").fetchall()
            if uncertain:
                print('Uncertain deliveries: ' + ', '.join(r['id'] for r in uncertain), flush=True)
                print(pilot.delivery_attention() + ' See docs/messages-pilot.md for recovery.', flush=True)
            command = [binary, 'watch', '--json', '--debounce', '500ms']
            chat = store.get('chat')
            if chat:
                command += ['--chat-id', str(chat['id'])]
            # No saved input cursor: restarts only accept fresh commands. Never replay an offline backlog.
            events = queue.Queue(maxsize=256)
            stopping = threading.Event()
            def stop(*_):
                stopping.set()
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=None, text=True, bufsize=1) as process:
                def read():
                    for line in process.stdout:
                        try:
                            events.put(json.loads(line))
                        except ValueError:
                            pass
                    events.put(None)
                reader = threading.Thread(target=read, daemon=True)
                reader.start()
                try:
                    time.sleep(.7)
                    if process.poll() is not None:
                        raise BridgeError('Messages watcher could not start. Check Terminal permissions.')
                    if chat:
                        print('Already paired. Send ordinary text to the orchestrator, or /help in the paired self-chat.', flush=True)
                        with store.db:
                            pilot.notify('messages-orchestrator-v1', 'Ordinary messages now go to the shared orchestrator.\n\n' + HELP,
                                         provider='Messages Relay')
                    else:
                        print('\nOn your iPhone, open Messages and send this to YOUR OWN iMessage address:\n\n'
                              + '/pair ' + pilot.token + '\n\nPairing code expires in one hour.', flush=True)
                    print('Messages Relay is running in the background. Use the scribble menu to pause or restart.'
                          if args.background else 'Allow Terminal to control Messages if macOS asks. Ctrl+C stops the pilot.', flush=True)
                    last_health = 0
                    while not stopping.is_set():
                        from task_relay import channel_policy
                        channel_policy.heartbeat(shared, 'messages', 'intake')
                        channel_policy.heartbeat(shared, 'messages', 'delivery')
                        try:
                            message = events.get(timeout=.5)
                            if message is None:
                                raise BridgeError('Messages watcher stopped. Relaunch the pilot, then send new commands.')
                            pilot.receive(message)
                        except queue.Empty:
                            pass
                        pilot.scan()
                        orchestrator_router.tick(pilot)
                        pilot.deliver()
                        if time.monotonic() - last_health > 5:
                            write_health(folder, 'running', pilot.delivery_attention() or
                                         ('Paired' if store.get('chat') else 'Awaiting pairing'))
                            last_health = time.monotonic()
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        finally:
            if provider_router:
                provider_router.close()
            if orchestrator_router:
                orchestrator_router.close()
            store.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', help='Codex task ID for first setup; later starts use the saved task')
    parser.add_argument('--state', default=str(PATHS.messages), help='Messages lock/health directory; records use the shared Relay database')
    parser.add_argument('--ack-delivery', help='After inspecting Messages, skip this uncertain delivery without resending')
    parser.add_argument('--clear-pending', action='store_true', help='After inspecting Codex, clear an uncertain instruction marker; never resubmit')
    parser.add_argument('--background', action='store_true', help='Run as the Messages Relay login service')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        run(args)
        write_health(Path(args.state), 'stopped')
    except KeyboardInterrupt:
        print('\nMessages pilot stopped.')
    except (BridgeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        write_health(Path(args.state), 'needs_attention', str(exc))
        print('\n' + str(exc), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
