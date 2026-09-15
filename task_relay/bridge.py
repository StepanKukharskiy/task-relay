#!/usr/bin/env python3
"""Personal Telegram remote for the local Codex desktop app. Python stdlib only."""
import argparse
import contextlib
import datetime
from task_relay.host import HOST, UnsupportedHost
import getpass
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import plistlib
import re
import secrets
import signal
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import time
import threading
import tempfile
import urllib.error
import urllib.request
import uuid
import unicodedata
from task_relay.media import MAX_FILE, MIMES, queue_attachments, video_metadata
from task_relay import backends
from task_relay import gemini
from task_relay import providers
from task_relay import api_providers as api
from task_relay import telegram_text
from task_relay import codex_approvals
from task_relay import codex_inputs
from task_relay import approval_ui
from task_relay import workflows
from task_relay import orchestrator_chat
from task_relay import production_control
from task_relay import task_routing
from task_relay import task_creation
from task_relay import reference_packs
from task_relay import relay_channels
from task_relay import channel_policy
from task_relay import usage_tracker

from task_relay.relay_paths import PATHS
ROOT = PATHS.install
DATA = PATHS.data
WORKSPACES = PATHS.workspaces
CODEX_DIR = Path.home() / '.codex'
HELP = ('New messages go to the orchestrator. Reply to a task message to continue that exact task.\n'
        '/tasks — one replyable card per recent task\n/use TASK_ID — select a target for commands\n'
        'Long Codex instructions: reply with a UTF-8 .txt or .md file (up to 100 KB).\n'
        'Codex media: attach photos, documents, audio or video (20 MB each), then send an instruction.\n'
        '/emoji 🏠 — set emoji for the replied-to or selected task\n'
        '/status — connection and selected task\n/routing — where your messages go\n/help — this help\n'
        '/usage [DAYS] [provider|model|project|day] — recorded token usage\n'
        '/templates — workflow starters\n/procedures — saved reusable workflows\n'
        '/opportunities — find repeated work and failure patterns\n'
        '/new PROVIDER "/project/path" Title — create a task\n'
        '/gemini INSTRUCTION · /openai INSTRUCTION · /qwen INSTRUCTION\n'
        '/deepseek INSTRUCTION · /openrouter INSTRUCTION · /claude INSTRUCTION\n'
        '/model [text|speech|image|video] MODEL — set a task model\n'
        '/speak TEXT — read text aloud from any task (Gemini)\n'
        '/speak as a reply — read the replied-to message\n'
        '/image PROMPT · /video PROMPT — create or continue Gemini media tasks\n'
        '/references · /forget ID — pending Codex files or Gemini references\n'
        '/resume — retrieve a saved API result\n'
        '/allow ID or /deny ID — answer a Codex or Claude permission request\n'
        '/stop — stop the selected or replied-to managed task\n'
        '/providers — connect providers and choose default models\n'
        '/browser TASK — plan a browser task; connect|status|cancel — Perplexity sign-in\n'
        '/workflow — linked roadmap runs and step budgets\n'
        '/orchestrator — talk about and control linked workflows\n'
        '/workflow run NAME 1 · /workflow plan NAME · /workflow pause NAME\n'
        '/models — choose this task’s model with buttons\n'
        '/endpoint qwen HTTPS_URL — set a regional workspace endpoint\n'
        '/cancelsetup — cancel API-key entry\n'
        '/backends — provider settings\n'
        '/use does not change where new messages go. '
        'Codex and Claude permission requests appear here. Keep Codex open for desktop approvals.')

EMOJIS = ('🏠 🏢 🏗️ 🧱 🛠️ ⚙️ 🔧 🔬 🧪 🧬 🔭 🛰️ 🚀 🛸 🪐 🌍 🌙 ⭐ ☀️ '
          '🔥 💧 🌊 ❄️ 🌈 ⚡ ☁️ 🌲 🌳 🌴 🌵 🌿 🍀 🍁 🍄 🌻 🌹 🌷 🌸 '
          '🐶 🐱 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🦉 🦅 🦆 🐝 '
          '🦋 🐞 🐢 🐍 🦎 🐙 🦑 🦀 🐠 🐬 🐳 🦈 🐘 🦒 🦓 🦏 🦛 🦘 '
          '🦔 🐿️ 🦦 🦥 🦩 🦚 🦜 🦢 🕊️ 🐇 🐎 🦌 🐐 🐏 🐪 🦙 '
          '🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍒 🍑 🥭 🍍 🥝 🥑 🍅 🥥 🥕 '
          '🌽 🥦 🥨 🥐 🥯 🧀 🍕 🍔 🌮 🍣 🍜 🍩 🍪 🎂 🍫 🍬 🍿 ☕ 🫖 '
          '🎨 🎭 🎬 🎤 🎧 🎷 🎺 🎸 🎻 🥁 🎹 🎲 🧩 ♟️ 🎯 🎳 🎮 🕹️ '
          '⚽ 🏀 🏈 ⚾ 🎾 🏐 🏉 🥏 🎱 🏓 🏸 🥊 🛹 🛼 ⛸️ 🎿 🛷 '
          '🚲 🛵 🏍️ 🚗 🚕 🚌 🚎 🚚 🚜 🚂 🚆 ✈️ 🚁 ⛵ 🚤 🚢 🛶 '
          '💎 🧲 💡 🔦 🕯️ 🪔 📚 📕 📗 📘 📙 📓 📌 📎 ✂️ 📐 📏 '
          '🔑 🗝️ 🔒 🛎️ 🧭 ⏰ ⌛ ⏳ ⌚ 📡 📷 📹 💻 🖥️ 🖨️ ⌨️ '
          '🧵 🪡 🧶 🧸 🎁 🎈 🎀 🪁 🪀 🪄 🏆 🥇 🥈 🥉 🛡️ ⚔️').split()


def emoji_key(value):
    return unicodedata.normalize('NFC', value).replace('\ufe0f', '')


def valid_task_emoji(value):
    # Allow a short emoji sequence (including flags, skin tones and ZWJ families),
    # but never multiline labels, arbitrary text, or invisible-only identifiers.
    def base(char):
        n = ord(char)
        return 0x1F000 <= n <= 0x1FAFF or 0x2600 <= n <= 0x27BF or n in (
            0xA9, 0xAE, 0x203C, 0x2049, 0x2122, 0x2139, 0x2328, 0x23CF, 0x24C2,
            0x3030, 0x303D, 0x3297, 0x3299) or 0x2194 <= n <= 0x21FF or 0x231A <= n <= 0x231B or 0x23E9 <= n <= 0x23FA or 0x25AA <= n <= 0x25FE or 0x2B05 <= n <= 0x2B55
    return (0 < len(value) <= 24 and
            (any(base(c) for c in value) or '\u20e3' in value) and
            all(base(c) or c in '\ufe0f\u200d\u20e3' or
                (c in '0123456789#*' and '\u20e3' in value) or
                0xE0020 <= ord(c) <= 0xE007F for c in value))


class BridgeError(Exception):
    pass


class OwnerUnavailable(BridgeError):
    pass


class TelegramError(BridgeError):
    def __init__(self, method, status, retry_after=0):
        super().__init__(f'Telegram {method}: HTTP {status}')
        self.status, self.retry_after = status, retry_after


def split_text(text, limit=3800):
    """Lossless chunks with room for task emoji and part numbering.

    Count UTF-16 units conservatively, retaining complete Unicode code points.
    Prefer paragraph, line, then word boundaries in the latter half of a chunk.
    """
    chunks, start = [], 0
    while start < len(text):
        end, units = start, 0
        while end < len(text):
            width = 2 if ord(text[end]) > 0xffff else 1
            if units + width > limit:
                break
            units += width
            end += 1
        if end == start:
            raise ValueError('Chunk limit cannot hold a character')
        if end < len(text):
            # Keep a short ending/footer with some body text instead of sending
            # an almost-empty final notification.
            if len(text) - end < 300 and end - start > 1:
                end = start + (end - start) // 2
            for separator in ('\n\n', '\n', ' '):
                boundary = text.rfind(separator, start + (end - start) // 2, end)
                if boundary >= 0:
                    end = boundary + len(separator)
                    break
        chunks.append(text[start:end])
        start = end
    return chunks


def message_parts(text):
    chunks = split_text(text)
    if len(chunks) <= 1:
        return chunks
    return [f'Part {index}/{len(chunks)}\n\n{chunk}' for index, chunk in enumerate(chunks, 1)]


class SendPacer:
    """Space outgoing messages without holding a lock during HTTP uploads."""
    def __init__(self):
        self.lock = threading.Lock()
        self.next_send = 0.0

    def wait(self):
        while True:
            with self.lock:
                delay = self.next_send - time.monotonic()
                if delay <= 0:
                    self.next_send = time.monotonic() + 1.1
                    return
            time.sleep(min(delay, 1.1))

    def cooldown(self, seconds):
        with self.lock:
            self.next_send = max(self.next_send, time.monotonic() + max(seconds, 1))


class Telegram:
    def __init__(self, token, pacer=None):
        self.token = token
        self.pacer = pacer or SendPacer()
        self.ssl_context = ssl.create_default_context()
        # python.org macOS builds may have no configured CA file. Add the OS
        # certificate bundle while retaining hostname and certificate verification.
        system_ca = Path('/etc/ssl/cert.pem')
        if sys.platform == 'darwin' and system_ca.is_file():
            self.ssl_context.load_verify_locations(cafile=str(system_ca))

    def call(self, method, **params):
        return self.request(method, json.dumps(params).encode(), 'application/json')

    def request(self, method, data, content_type, timeout=15):
        if hasattr(self, 'policy_path') and method.startswith(('send', 'edit', 'delete', 'answer')):
            channel_policy.require_outgoing(self.policy_path, 'telegram')
        if method.startswith('send'):
            self.pacer.wait()
            if hasattr(self, 'policy_path'):
                channel_policy.require_outgoing(self.policy_path, 'telegram')
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/{method}',
            data=data, headers={'Content-Type': content_type})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as res:
                result = json.load(res)
        except urllib.error.HTTPError as exc:
            # Never print an exception containing the credential-bearing URL.
            try:
                retry_after = json.load(exc).get('parameters', {}).get('retry_after', 0)
            except (ValueError, OSError):
                retry_after = 0
            if exc.code == 429:
                self.pacer.cooldown(retry_after or 30)
            raise TelegramError(method, exc.code, retry_after) from None
        except (OSError, ValueError):
            raise BridgeError(f'Telegram {method}: connection failed') from None
        if not result.get('ok'):
            if result.get('error_code') == 429:
                self.pacer.cooldown(result.get('parameters', {}).get('retry_after', 30))
            raise TelegramError(method, result.get('error_code', 500),
                                result.get('parameters', {}).get('retry_after', 0))
        return result['result']

    def download_file(self, file_id, destination, max_size):
        result = self.call('getFile', file_id=file_id)
        path = result.get('file_path', '')
        if (not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or '..' in path or
                path.startswith('/') or result.get('file_size', 0) > max_size):
            raise ValueError('Unsupported reference download')
        url = f'https://api.telegram.org/file/bot{self.token}/{path}'
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.ssl_context), gemini.NoRedirect())
        try:
            with opener.open(url, timeout=30) as response:
                data = response.read(max_size + 1)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise TelegramError('download', code) from None
        except OSError:
            raise BridgeError('Telegram reference download failed') from None
        if not data or len(data) > max_size:
            raise ValueError('Reference too large or empty')
        gemini.atomic_bytes(destination, data)

    def send_media(self, chat_id, path, filename, kind, caption):
        metadata = video_metadata(path) if kind == 'video' else {}
        if kind == 'video' and not metadata:
            # Avoid guessing Telegram's video display geometry. Original file
            # delivery retains the actual container metadata and all bytes.
            kind = 'original'
            caption = caption.replace(' — video\n', ' — original file\n')
        field, method = {'preview': ('photo', 'sendPhoto'), 'video': ('video', 'sendVideo'),
                         'audio': ('audio', 'sendAudio'), 'original': ('document', 'sendDocument')}[kind]
        boundary = 'codex-' + secrets.token_hex(24)
        parts = []
        fields = {'chat_id': str(chat_id), 'caption': caption, 'disable_notification': 'true'}
        if kind == 'video':
            fields.update({key: str(value) for key, value in metadata.items()})
        if kind == 'audio':
            fields.update(title=caption.splitlines()[0][:120], performer='Task Relay')
        if kind == 'original':
            fields['disable_content_type_detection'] = 'true'
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        safe_name = filename.replace('"', '_').replace('\r', '_').replace('\n', '_').replace('\\', '_')
        mime = ('video/mp4' if kind == 'video' else
                MIMES.get(Path(filename).suffix.lower()) or mimetypes.guess_type(filename)[0] or 'application/octet-stream')
        with open(path, 'rb') as stream:
            data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise TelegramError(method, 413)
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{safe_name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
        parts.extend([data, f'\r\n--{boundary}--\r\n'.encode()])
        return self.request(method, b''.join(parts), f'multipart/form-data; boundary={boundary}', timeout=120)

    def send(self, chat_id, text, entities=None, reply_markup=None):
        # Splitting and receipt tracking belong to Bridge, never silently truncate.
        if not text or len(text.encode('utf-16-le')) > 8192:
            raise BridgeError('Telegram message must be split before sending')
        try:
            return self.call('sendMessage', chat_id=chat_id, text=text,
                             link_preview_options={'is_disabled': True}, **({'entities': entities} if entities else {}),
                             **({'reply_markup': reply_markup} if reply_markup else {}))
        except TelegramError as exc:
            if exc.status != 400 or not entities:
                raise
            # A confirmed formatting rejection can safely fall back to readable
            # text; a timeout or rate limit must retain normal retry semantics.
            return self.call('sendMessage', chat_id=chat_id, text=text,
                             link_preview_options={'is_disabled': True},
                             **({'reply_markup': reply_markup} if reply_markup else {}))


class Desktop:
    """Small isolated adapter for the desktop IPC protocol, verified September 2026.

    This is an internal protocol. Do not fall back to modifying Codex databases or
    running another agent if an app update makes the protocol incompatible.
    """
    def __init__(self, path=None):
        self.path = str(path or CODEX_DIR / 'ipc/ipc.sock')
        self.sock = None
        self.client_id = None

    def __enter__(self):
        self.sock = HOST.desktop_socket()
        self.sock.settimeout(15)
        try:
            self.sock.connect(self.path)
            response = self.request('initialize', {'clientType': 'telegram-bridge'}, 0)
            self.client_id = response['result']['clientId']
            return self
        except Exception as exc:
            self.sock.close()
            raise BridgeError(f'Cannot connect to Codex desktop ({type(exc).__name__}, '
                              f'errno={getattr(exc, "errno", None)}). Keep the app open.') from None

    def __exit__(self, *args):
        self.sock.close()

    def send(self, message):
        raw = json.dumps(message).encode()
        self.sock.sendall(struct.pack('<I', len(raw)) + raw)

    def exact(self, n):
        parts = bytearray()
        while len(parts) < n:
            chunk = self.sock.recv(n - len(parts))
            if not chunk:
                raise BridgeError('Codex connection closed')
            parts.extend(chunk)
        return parts

    def receive(self):
        n = struct.unpack('<I', self.exact(4))[0]
        if not 0 < n <= 268435456:
            raise BridgeError('Unexpected Codex IPC frame')
        return json.loads(self.exact(n))

    def request(self, method, params, version, target=None):
        request_id = str(uuid.uuid4())
        self.send({'type': 'request', 'requestId': request_id,
                   'sourceClientId': self.client_id, 'method': method,
                   'params': params, 'version': version, 'timeoutMs': 12000,
                   **({'targetClientId': target} if target else {})})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.sock.settimeout(max(.1, deadline - time.monotonic()))
            message = self.receive()
            if message.get('type') == 'client-discovery-request':
                self.send({'type': 'client-discovery-response',
                           'requestId': message['requestId'], 'response': {'canHandle': False}})
            if message.get('type') == 'response' and message.get('requestId') == request_id:
                if message.get('resultType') != 'success':
                    if method == 'thread-owner-discovery' and message.get('error') == 'no-client-found':
                        raise OwnerUnavailable('No window owns this task')
                    raise BridgeError('Codex desktop could not handle this request. '
                                      'Open the target task in the app and try again.')
                return message
        raise BridgeError('Codex response timed out')

    def owner(self, thread_id):
        return self.request('thread-owner-discovery',
                            {'hostId': 'local', 'conversationId': thread_id}, 1)['handledByClientId']

    def approval_snapshot(self, thread_id, owner):
        # A fresh connection/subscription yields an authoritative snapshot. Never
        # infer pending approvals from transcript text or reconstruct partial patches.
        def following(value):
            self.send({'type': 'broadcast', 'method': 'thread-stream-following-changed',
                       'sourceClientId': self.client_id, 'targetClientIds': [owner],
                       'version': 1, 'params': {'conversationId': thread_id,
                                               'hostId': 'local', 'following': value}})
        following(True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.sock.settimeout(max(.1, deadline - time.monotonic()))
                message = self.receive()
                if message.get('type') == 'client-discovery-request':
                    self.send({'type': 'client-discovery-response',
                               'requestId': message['requestId'], 'response': {'canHandle': False}})
                    continue
                params = message.get('params', {})
                if (message.get('type') != 'broadcast' or
                        message.get('method') != 'thread-stream-state-changed' or
                        message.get('sourceClientId') != owner or
                        params.get('conversationId') != thread_id or params.get('hostId') != 'local'):
                    continue
                if message.get('version') != 11:
                    raise BridgeError('Codex approval protocol changed. Review on desktop.')
                change = params.get('change', {})
                if change.get('type') != 'snapshot':
                    continue
                state = change.get('conversationState', {})
                if (state.get('id') != thread_id or state.get('hostId') != 'local' or
                        not isinstance(state.get('requests'), list)):
                    raise BridgeError('Unexpected Codex approval snapshot. Review on desktop.')
                return state
            raise BridgeError('Codex approval snapshot timed out. Review on desktop.')
        finally:
            with contextlib.suppress(OSError, BridgeError):
                following(False)

    def open_task(self, thread_id):
        # Open only an exact saved-task UUID; never put user prompts in a URL.
        try:
            task_id = str(uuid.UUID(thread_id))
        except (ValueError, TypeError, AttributeError):
            raise BridgeError('Invalid task ID for desktop navigation') from None
        HOST.open_codex(task_id, BridgeError)

    def ready_owner(self, thread_id, on_open=None):
        try:
            return self.owner(thread_id)
        except OwnerUnavailable:
            pass
        if on_open:
            on_open()
        self.open_task(thread_id)
        # Retry discovery only, never start-turn. Each IPC request has its own
        # deadline; an app that cannot load the task must not stall indefinitely.
        for attempt in range(2):
            time.sleep(1)
            try:
                return self.owner(thread_id)
            except OwnerUnavailable:
                if attempt == 1:
                    raise

    def start(self, thread_id, text, owner, images=None):
        from .app_access import require
        require('codex')
        response = self.request('thread-follower-start-turn', {
            'conversationId': thread_id,
            'turnStart': {'request': {'threadId': thread_id,
                                     'input': [{'type': 'text', 'text': text, 'text_elements': []},
                                               *[{'type': 'localImage', 'path': p} for p in images or []]]},
                          'context': {'inheritThreadSettings': True}}}, 2, target=owner)
        body = response.get('result')
        # The main-process IPC handler unwraps the renderer's {method,result}.
        # The method belongs to the OUTER response; body is {result: turnResult}.
        if response.get('method') != 'thread-follower-start-turn' or not isinstance(body, dict):
            raise BridgeError('Unexpected Codex start response; check the desktop task')
        return body


class State:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.media_dir = path.parent / 'media'
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.row_factory = sqlite3.Row
        from orchestrator import storage
        try:
            storage.initialize(self.db, path.parent / 'orchestrator/runtime.sqlite')
        except BaseException:
            self.db.close()
            raise
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS watched (
            id TEXT PRIMARY KEY, path TEXT, offset INTEGER, title TEXT, status TEXT,
            updated_at INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS watch_checkpoints (
            thread_id TEXT PRIMARY KEY, anchor TEXT NOT NULL, replaying INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY, thread_id TEXT, text TEXT, sent INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS outbox_parts (
            event_id TEXT NOT NULL, part INTEGER NOT NULL, text TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(event_id,part));
          CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER, message_id INTEGER, thread_id TEXT,
            PRIMARY KEY(chat_id, message_id));
          CREATE TABLE IF NOT EXISTS incoming (
            id INTEGER PRIMARY KEY, status TEXT, thread_id TEXT);
          CREATE TABLE IF NOT EXISTS desktop_commands (
            request_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, prompt TEXT NOT NULL,
            incoming_id INTEGER NOT NULL UNIQUE, status TEXT NOT NULL,
            created REAL NOT NULL, result TEXT);
          CREATE TABLE IF NOT EXISTS desktop_creations (
            request_id TEXT PRIMARY KEY, backend TEXT NOT NULL, cwd TEXT NOT NULL,
            title TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
            task_id TEXT, result TEXT);
          CREATE TABLE IF NOT EXISTS task_emojis (
            thread_id TEXT PRIMARY KEY, emoji TEXT NOT NULL, emoji_key TEXT UNIQUE NOT NULL,
            custom INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS media_outbox (
            id TEXT PRIMARY KEY, event_id TEXT, thread_id TEXT, path TEXT,
            filename TEXT, kind TEXT, caption TEXT, status TEXT DEFAULT 'pending',
            attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0);
        ''')
        backends.initialize(self.db)
        providers.initialize(self.db)
        codex_approvals.initialize(self.db)
        codex_inputs.initialize(self.db)
        approval_ui.initialize(self.db)
        workflows.initialize(self.db)
        orchestrator_chat.initialize(self.db)
        relay_channels.initialize(self.db)
        from . import desktop_plans
        desktop_plans.initialize(self.db)
        usage_tracker.initialize(self.db)
        from task_relay.messages_storage import initialize as initialize_messages
        initialize_messages(self.db)
        if 'entities' not in {r[1] for r in self.db.execute('PRAGMA table_info(outbox_parts)')}:
            self.db.execute('ALTER TABLE outbox_parts ADD COLUMN entities TEXT')
        os.chmod(path, 0o600)

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value)))

    def remember(self, chat_id, message_id, thread_id):
        self.db.execute('INSERT OR REPLACE INTO messages VALUES (?,?,?)',
                        (chat_id, message_id, thread_id))

    def emoji(self, thread_id):
        row = self.db.execute('SELECT emoji FROM task_emojis WHERE thread_id=?', (thread_id,)).fetchone()
        if row:
            return row[0]
        used = {r[0] for r in self.db.execute('SELECT emoji_key FROM task_emojis')}
        start = int(hashlib.sha256(thread_id.encode()).hexdigest()[:8], 16) % len(EMOJIS)
        for i in range(len(EMOJIS)):
            candidate = EMOJIS[(start + i) % len(EMOJIS)]
            if emoji_key(candidate) not in used:
                break
        else:
            # Keep defaults visually distinct even after the single-emoji pool fills.
            candidate = next(a + b for a in EMOJIS for b in EMOJIS if emoji_key(a + b) not in used)
        self.db.execute('INSERT INTO task_emojis(thread_id,emoji,emoji_key) VALUES (?,?,?)', (thread_id, candidate, emoji_key(candidate)))
        return candidate

    def set_emoji(self, thread_id, value):
        if not valid_task_emoji(value):
            raise BridgeError('Use an emoji or short emoji sequence, for example /emoji 🏠.')
        existing = self.db.execute('SELECT thread_id,custom FROM task_emojis WHERE emoji_key=?', (emoji_key(value),)).fetchone()
        displaced = None
        if existing and existing[0] != thread_id:
            if existing[1]:
                raise BridgeError('That emoji is already customized for another task. Choose a different emoji or a pair such as 🏠🔧.')
            displaced = existing[0]
            self.db.execute('DELETE FROM task_emojis WHERE thread_id=?', (displaced,))
        self.db.execute('INSERT INTO task_emojis(thread_id,emoji,emoji_key,custom) VALUES (?,?,?,1) ON CONFLICT(thread_id) DO UPDATE SET emoji=excluded.emoji,emoji_key=excluded.emoji_key,custom=1',
                        (thread_id, value, emoji_key(value)))
        if displaced:
            self.emoji(displaced)


def local_tasks(codex_dir=CODEX_DIR):
    path = codex_dir / 'state_5.sqlite'
    if not path.exists():
        raise BridgeError('Codex task database was not found. Open Codex desktop first.')
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT id,rollout_path,title,name,source,agent_role,updated_at,cwd '
                            'FROM threads WHERE archived=0 ORDER BY updated_at DESC').fetchall()
    return [dict(row) for row in rows if not row['agent_role']
            and 'subagent' not in row['source'].lower() and row['source'] != 'exec']


def recent_status(path):
    # Inspect only event metadata; never transmit raw histories or tool outputs.
    try:
        with open(path, 'rb') as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 2_000_000))
            if stream.tell():
                stream.readline()
            lines = stream.readlines()
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            payload = event.get('payload', {})
            if event.get('type') != 'event_msg':
                continue
            kind = payload.get('type')
            if kind == 'task_started':
                return 'running'
            if kind in ('task_complete', 'turn_aborted'):
                return 'idle'
    except OSError:
        pass
    return 'unknown'


def complete_offset(path):
    """Baseline through complete lines only, even while Codex is appending."""
    with open(path, 'rb') as stream:
        end = stream.seek(0, 2)
        pos = end
        while pos:
            size = min(pos, 65536)
            pos -= size
            stream.seek(pos)
            block = stream.read(size)
            index = block.rfind(b'\n')
            if index >= 0:
                return pos + index + 1
        return 0


def checkpoint_anchor(path, offset):
    """Verify the bytes preceding a cursor, not just the file's path and size."""
    with open(path, 'rb') as stream:
        stream.seek(max(0, offset - 256))
        return hashlib.sha256(stream.read(min(offset, 256))).hexdigest()


class Watcher:
    def __init__(self, state, codex_dir=CODEX_DIR):
        self.state, self.codex_dir = state, codex_dir

    def scan(self):
        tasks = local_tasks(self.codex_dir)
        first = not self.state.get('baselined', False)
        with self.state.db:
            if self.state.get('notification_since') is None:
                # Upgrade from byte-only checkpoints using the last successful
                # scan, preserving completions that arrived while offline.
                previous = self.state.get('health:scan', {}).get('last_success')
                self.state.put('notification_since', max(0, (previous or time.time()) - 5))
            for task in tasks:
                self.state.emoji(task['id'])
                path = Path(task['rollout_path'])
                if not path.is_file():
                    continue
                title = task['name'] or task['title'] or task['id']
                old = self.state.db.execute('SELECT * FROM watched WHERE id=?', (task['id'],)).fetchone()
                checkpoint = self.state.db.execute('SELECT * FROM watch_checkpoints WHERE thread_id=?', (task['id'],)).fetchone()
                replaying = bool(checkpoint and checkpoint['replaying'])
                if old is None:
                    offset = complete_offset(path) if first else 0
                    replaying = not first
                    status = recent_status(path)
                    self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                                          (task['id'], str(path), offset, title, status, task['updated_at']))
                elif old['path'] != str(path) or old['offset'] > path.stat().st_size:
                    offset, replaying = 0, True
                elif checkpoint and checkpoint['anchor'] != checkpoint_anchor(path, old['offset']):
                    # Codex may rewrite a history into a larger file at the same
                    # path. Re-read with timestamp filtering and event deduplication.
                    offset, replaying = 0, True
                else:
                    offset = old['offset']
                    if offset and not checkpoint:
                        with path.open('rb') as stream:
                            stream.seek(offset - 1)
                            if stream.read(1) != b'\n':
                                offset, replaying = 0, True
                with path.open('rb') as stream:
                    stream.seek(offset)
                    # Bound each scan; checkpoints allow large backlogs to drain later.
                    for _ in range(20000):
                        start = stream.tell()
                        line = stream.readline()
                        if not line or not line.endswith(b'\n'):
                            stream.seek(start)
                            break
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        self.event(task['id'], title, event, task['cwd'], require_timestamp=replaying)
                    offset = stream.tell()
                replaying = replaying and offset < complete_offset(path)
                self.state.db.execute('INSERT OR REPLACE INTO watch_checkpoints VALUES (?,?,?)',
                                      (task['id'], checkpoint_anchor(path, offset), int(replaying)))
                self.state.db.execute('UPDATE watched SET path=?,offset=?,title=?,updated_at=? WHERE id=?',
                                      (str(path), offset, title, task['updated_at'], task['id']))
            self.state.put('baselined', True)

    def event(self, thread_id, title, event, cwd=None, require_timestamp=False):
        if event.get('type') != 'event_msg':
            return
        timestamp = event.get('timestamp')
        if timestamp:
            try:
                occurred = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError, AttributeError, OverflowError):
                return
            if occurred < self.state.get('notification_since', 0):
                return
        elif require_timestamp:
            # Reconstructed history without event time cannot establish freshness.
            return
        payload = event.get('payload', {})
        kind, turn_id = payload.get('type'), payload.get('turn_id')
        if kind == 'task_started':
            self.state.db.execute('UPDATE watched SET status=? WHERE id=?', ('running', thread_id))
        elif kind in ('task_complete', 'turn_aborted'):
            self.state.db.execute('UPDATE watched SET status=? WHERE id=?', ('idle', thread_id))
            if not turn_id:
                turn_id = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
            if workflows.owns_turn(self.state, thread_id, turn_id):
                return
            summary = payload.get('last_agent_message') or 'Open Codex for details.'
            label = 'Finished' if kind == 'task_complete' else 'Stopped'
            title = title[:150]
            text = f'{label}: {title}\nTask: {thread_id}\n\n{summary}\n\nReply to continue this task.'
            event_id = f'{thread_id}:{turn_id}:{kind}'
            inserted = self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                             (event_id, thread_id, text)).rowcount
            if inserted:
                queue_attachments(self.state, event_id, thread_id, title, summary, cwd)


class Bridge:
    def __init__(self, state, telegram, config, desktop_factory=Desktop):
        self.state, self.telegram, self.config = state, telegram, config
        self.desktop_factory = desktop_factory
        telegram.policy_path = channel_policy.database_path(state.db)

    def send(self, text, thread_id=None):
        parts = list(telegram_text.parts(text, split_text))
        for index, (part, entities) in enumerate(parts):
            try:
                if not channel_policy.outgoing(self.state.db, 'telegram'):
                    raise channel_policy.ChannelPaused()
                response = self.send_part(part, thread_id, entities)
            except channel_policy.ChannelPaused:
                ident = 'held-reply:' + secrets.token_hex(16)
                with self.state.db:
                    self.state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                        (ident, thread_id, text if index == 0 else ''.join(p[0] for p in parts[index:])))
                    self.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)', (ident, 'telegram'))
                return
            if thread_id:
                with self.state.db:
                    self.state.remember(self.state.get('chat_id'), response['message_id'], thread_id)

    def send_part(self, text, thread_id=None, entities=None, reply_markup=None):
        chat_id = self.state.get('chat_id')
        if thread_id:
            decorated = self.decorate(text, thread_id)
            shift = telegram_text.units(decorated) - telegram_text.units(text)
            entities = [{**e, 'offset': e['offset'] + shift} for e in entities or []]
            text = decorated
        return self.telegram.send(chat_id, text, **({'entities': entities} if entities else {}),
                                  **({'reply_markup': reply_markup} if reply_markup else {}))

    def decorate(self, text, thread_id):
        with self.state.db:
            marker = self.state.emoji(thread_id)
        return f'{marker} {text}'

    def target_task(self, message, chat_id):
        reply_id = message.get('reply_to_message', {}).get('message_id')
        if reply_id is not None:
            row = self.state.db.execute('SELECT thread_id FROM messages WHERE chat_id=? AND message_id=?',
                                        (chat_id, reply_id)).fetchone()
            return row[0] if row else None
        return self.state.get('selected')

    def flush(self, include_media=True):
        channel_policy.heartbeat(self.state, 'telegram', 'delivery')
        with self.state.db:
            self.state.put('health:messages-routing', {'version': 1, 'last_success': time.time()})
            for row in relay_channels.pending(self.state, 'desktop', limit=50):
                self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['id'],))
        if self.state.get('chat_id') is None:
            return
        if not channel_policy.outgoing(self.state.db, 'telegram'):
            return
        for row in relay_channels.pending(self.state, 'telegram'):
            # Freeze boundaries once. A later failed part or service restart
            # resumes after confirmed sends, including if task emoji changes.
            with self.state.db:
                if not self.state.db.execute('SELECT 1 FROM outbox_parts WHERE event_id=?', (row['id'],)).fetchone():
                    self.state.db.executemany('INSERT INTO outbox_parts(event_id,part,text,entities) VALUES (?,?,?,?)',
                                              [(row['id'], i, part, json.dumps(entities)) for i, (part, entities) in enumerate(telegram_text.parts(row['text'], split_text))])
            controls = approval_ui.controls(self.state, row['id'])
            orchestration_controls = orchestrator_chat.controls(self.state, row['id'])
            from . import browser_login
            login_controls = browser_login.controls(self.state, row['id'])
            last_part = self.state.db.execute('SELECT max(part) FROM outbox_parts WHERE event_id=?', (row['id'],)).fetchone()[0]
            for part in self.state.db.execute('SELECT * FROM outbox_parts WHERE event_id=? AND sent=0 ORDER BY part', (row['id'],)).fetchall():
                markup = (login_controls or (controls[1] if controls else orchestration_controls)) if part['part'] == last_part else None
                try:
                    if not channel_policy.outgoing(self.state.db, 'telegram'):
                        return
                    if row['id'].startswith('proactive:') and channel_policy.read(self.state.db)['proactive'] == 'none':
                        break
                    response = self.send_part(part['text'], row['thread_id'], json.loads(part['entities'] or '[]'), markup)
                except channel_policy.ChannelPaused:
                    return
                with self.state.db:
                    if row['thread_id']:
                        self.state.remember(self.state.get('chat_id'), response['message_id'], row['thread_id'])
                    if controls:
                        approval_ui.remember(self.state, self.state.get('chat_id'), response['message_id'], controls[0])
                    orchestrator_chat.remember(self.state, row['id'], self.state.get('chat_id'), response['message_id'])
                    browser_login.remember(self.state, row['id'], self.state.get('chat_id'), response['message_id'])
                    self.state.db.execute('UPDATE outbox_parts SET sent=1 WHERE event_id=? AND part=?', (row['id'], part['part']))
            with self.state.db:
                self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=? AND NOT EXISTS '
                    '(SELECT 1 FROM outbox_parts WHERE event_id=? AND sent=0)', (row['id'], row['id']))
        if include_media:
            self.flush_media()

    def flush_media(self):
        if not channel_policy.outgoing(self.state.db, 'telegram'):
            return
        if self.state.get('chat_id') is None:
            return
        rows = self.state.db.execute(
            "SELECT m.* FROM media_outbox m JOIN outbox o ON o.id=m.event_id "
            "WHERE m.status='pending' AND m.next_attempt<=? AND o.sent=1 ORDER BY m.rowid",
            (time.time(),)).fetchall()
        rows = [r for r in rows if relay_channels.event_channel(self.state, r['event_id']) == 'telegram'][:6]
        for row in rows:
            try:
                if not channel_policy.outgoing(self.state.db, 'telegram'):
                    return
                response = self.telegram.send_media(self.state.get('chat_id'), row['path'],
                                                     row['filename'], row['kind'],
                                                     self.decorate(row['caption'], row['thread_id']) if row['thread_id'] else row['caption'])
            except channel_policy.ChannelPaused:
                return
            except (BridgeError, OSError) as exc:
                if row['kind'] in ('video', 'audio') and isinstance(exc, TelegramError) and exc.status == 400:
                    # Codec/container rejected for inline playback: retain the
                    # same snapshot and deliver the exact file as a document.
                    with self.state.db:
                        self.state.db.execute("UPDATE media_outbox SET kind='original',caption=?,attempts=0,next_attempt=0 WHERE id=?",
                                              (row['caption'].replace(' — video\n', ' — original file\n'), row['id']))
                    continue
                permanent = isinstance(exc, FileNotFoundError) or (
                    isinstance(exc, TelegramError) and exc.status in (400, 413))
                attempts = row['attempts'] + 1
                skipped = permanent or attempts >= 5
                with self.state.db:
                    self.state.db.execute('UPDATE media_outbox SET status=?,attempts=?,next_attempt=? WHERE id=?',
                                          ('skipped' if skipped else 'pending', attempts,
                                           time.time() + max(getattr(exc, 'retry_after', 0), min(30 * 2**attempts, 900)), row['id']))
                    if skipped:
                        explanation = ('Preview unavailable; the original file is sent separately.'
                                       if row['kind'] == 'preview' else 'Original file could not be delivered. Check the task’s local output files.')
                        self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                              (row['id'] + ':failed', row['thread_id'],
                                               f"{row['filename'][:180]}: {explanation}"))
                if isinstance(exc, TelegramError) and exc.status == 429:
                    # Respect Telegram's cooldown for all remaining uploads.
                    with self.state.db:
                        self.state.db.execute("UPDATE media_outbox SET next_attempt=max(next_attempt,?) WHERE status='pending'",
                                              (time.time() + max(exc.retry_after, 60),))
                    break
            else:
                with self.state.db:
                    if row['thread_id']:
                        self.state.remember(self.state.get('chat_id'), response['message_id'], row['thread_id'])
                    orchestrator_chat.remember(self.state, row['event_id'], self.state.get('chat_id'), response['message_id'])
                    approval = approval_ui.controls(self.state, row['event_id'])
                    if approval:
                        approval_ui.remember(self.state, self.state.get('chat_id'), response['message_id'], approval[0])
                    if isinstance(response.get('video'), dict):
                        self.state.put('video-receipt:' + row['id'], {key: response['video'].get(key) for key in ('width', 'height', 'duration')})
                    self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE id=?", (row['id'],))
            if not self.state.db.execute("SELECT 1 FROM media_outbox WHERE path=? AND status='pending'", (row['path'],)).fetchone():
                # Delete only snapshots owned by this bridge, after both deliveries.
                path = Path(row['path'])
                if path.parent.resolve() == self.state.media_dir.resolve():
                    path.unlink(missing_ok=True)

    def process(self, update, received_at=None):
        created = update.get('message', {}).get('date', received_at)
        if not channel_policy.accepting(self.state.db, 'telegram', created):
            return
        if 'callback_query' in update:
            if orchestrator_chat.callback(self, update):
                return
            if approval_ui.callback(self, update):
                return
            providers.Menu(self).callback(update)
            return
        update_id = update['update_id']
        message = update.get('message', {})
        chat, sender = message.get('chat', {}), message.get('from', {})
        text = message.get('text', '').strip()
        if chat.get('type') != 'private' or sender.get('is_bot'):
            return
        if self.state.get('user_id') is None:
            code = self.config.get('pair_code')
            supplied = text.partition(' ')[2]
            if (code and text.startswith('/start ') and
                    time.time() < self.config.get('pair_expires', 0) and
                    secrets.compare_digest(code, supplied)):
                with self.state.db:
                    self.state.put('user_id', sender['id'])
                    self.state.put('chat_id', chat['id'])
                self.send('Connected to Codex on your Mac.\n\n' + HELP)
            return
        if sender.get('id') != self.state.get('user_id') or chat.get('id') != self.state.get('chat_id'):
            return
        if self.state.db.execute('SELECT 1 FROM incoming WHERE id=?', (update_id,)).fetchone():
            return
        from . import browser_login
        if browser_login.receive(self, message, update_id):
            return
        if approval_ui.reply_input(self, message, update_id):
            return
        if providers.Menu(self).credential_message(update):
            return
        from . import browser_research
        if browser_research.telegram(self, message, update_id):
            return
        if orchestrator_chat.handle(self, message, text, update_id):
            return
        if any(message.get(k) for k in codex_inputs.KINDS):
            tid = self.target_task(message, chat['id'])
            try:
                tid = codex_inputs.album_target(self.state, message, tid)
            except ValueError as exc:
                self.send(str(exc))
                return
            info = backends.task(self.state, tid)
            if tid and not info and self.state.db.execute('SELECT 1 FROM watched WHERE id=?', (tid,)).fetchone():
                document = message.get('document', {})
                if Path(document.get('file_name', '')).suffix.lower() in ('.txt', '.md') and not message.get('media_group_id'):
                    self.codex_text_file(message, tid, update_id, chat['id'])
                    return
                try:
                    codex_inputs.receive(self.state, message, tid, update_id)
                except ValueError as exc:
                    self.send(str(exc), tid)
                    return
                self.send('Downloading attachment. Wait for “Attached” for each file, then send your instruction. Captions are saved; uploading does not start Codex.', tid)
                return
            if not info or info['backend'] != 'gemini':
                self.send('Reply to a Codex or Gemini task card from /tasks before attaching files. Other providers do not support Telegram attachments yet.')
                return
            try:
                if not gemini.receive_file(self.state, message, tid, update_id):
                    raise ValueError('Gemini references support photos, PDFs, and text documents. Audio and video uploads are supported for Codex tasks.')
                self.send('Downloading reference. Wait for “Reference attached”, then send your instruction. Captions do not start generation.', tid)
            except ValueError as exc:
                self.send(str(exc), tid)
            return
        if not text:
            self.send('Send text, or reply to a task card with an attachment. Codex accepts files, photos, audio, and video; transcription is not automatic.')
            return
        parts = text.split(None, 1)
        command, arg = parts[0], parts[1] if len(parts) > 1 else ''
        command = command.split('@')[0]
        if command == '/usage':
            try:self.send(usage_tracker.command(self.state,arg))
            except ValueError as exc:self.send(str(exc))
            return
        if command == '/browser':
            from . import browser_setup
            from orchestrator.storage import transaction
            try:
                with transaction(self.state.db):
                    result=browser_setup.command(self.state,arg,'telegram:'+str(update_id))
                    self.state.db.execute('INSERT INTO incoming VALUES (?,?,NULL)',(update_id,'handled'))
                self.send(result)
            except ValueError as exc:self.send(str(exc))
            return
        if command in ('/workflow', '/workflows'):
            try:
                orchestrator_chat.workflow_command(self, arg, update_id, source_request=message.get('text',''))
            except ValueError as exc:
                self.send(str(exc))
            return
        if command in ('/image', '/video', *tuple('/' + p for p in ('gemini', 'claude', *api.SPECS))):
            capability = command[1:] if command in ('/image', '/video') else 'text'
            provider = 'gemini' if capability != 'text' else command[1:]
            if not arg:
                example = 'a sunlit courtyard' if capability != 'text' else 'read README.md and summarise it'
                self.send(f'Use {command} followed by a prompt, for example: {command} {example}. A task is created automatically when needed.')
                return
            source = self.target_task(message, chat['id'])
            if message.get('reply_to_message') and not source:
                self.send('That reply is not linked to a task. Reply to a /tasks card so I can use the correct project folder.')
                return
            info = backends.task(self.state, source)
            try:
                if info and info['backend'] == provider:
                    backends.enqueue(self.state, source, arg, update_id, capability)
                    tid, folder = source, info['cwd']
                    action = 'Queued in this task'
                else:
                    if info:
                        folder = info['cwd']
                    elif source:
                        desktop_task = next((t for t in local_tasks() if t['id'] == source), None)
                        if not desktop_task:
                            raise ValueError('The source project folder is unavailable. Use /new PROVIDER "/absolute/project/path" Title.')
                        folder = desktop_task['cwd']
                    else:
                        folder = WORKSPACES
                        folder.mkdir(parents=True,exist_ok=True)
                    import shlex
                    title = ' '.join(arg.split())[:100]
                    tid, _, folder = backends.create_task(self.state, shlex.join([provider, str(folder), title]), update_id, prompt=arg, capability=capability)
                    action = 'Created and queued a new task'
                note = ('Reply here to continue this task. Requested project file contents are sent to this provider.' if capability == 'text' else
                        f'{capability.capitalize()} generation queued; media will arrive here. Reply here with /{capability} and another prompt to continue. /status checks progress; /stop requests cancellation.')
                if capability == 'image':
                    note = 'Image generation queued; media will arrive here. Reply normally with changes to edit it. /gemini switches to text discussion; /status checks progress.'
                self.send(f'{action} with {providers.REGISTRY[provider]["name"]}.\nFolder: {folder}\nTask: {tid}\n\n{note}', tid)
            except (ValueError, BridgeError) as exc:
                self.send(str(exc))
            return
        if command in ('/help', '/start'):
            self.send(HELP)
            return
        if command in ('/providers', '/backends'):
            providers.Menu(self).home()
            return
        if command == '/endpoint':
            parts = arg.split(None, 1)
            try:
                if len(parts) != 2:
                    raise ValueError('Use /endpoint qwen HTTPS_BASE_URL, or choose Region / endpoint in /providers → Qwen.')
                providers.Menu(self).set_endpoint(parts[0], parts[1])
            except ValueError as exc:
                self.send(str(exc))
            return
        if command == '/models':
            tid = self.target_task(message, chat['id'])
            info = backends.task(self.state, tid)
            if info:
                providers.Menu(self).caps(info['backend'], tid)
            else:
                self.send('Select a managed task first, or use /providers to choose default models.')
            return
        if command == '/new':
            if arg.split(None,1)[:1]==['codex']:
                try:
                    import shlex
                    parts=shlex.split(arg)
                    if len(parts)<3:raise ValueError('Use /new codex "PROJECT_PATH" Task title. This creates a task without starting work.')
                    action=dict(kind='create_codex_task',project=parts[1],title=' '.join(parts[2:]),
                                start_work=False,research_ids=[],artifact_ids=[])
                    snap={'codex_projects':task_creation.projects(self.state)}
                    with self.state.db:
                        self.state.db.execute('BEGIN IMMEDIATE')
                        if self.state.db.execute('SELECT 1 FROM incoming WHERE id=?',(update_id,)).fetchone():return
                        reply=task_creation.enqueue(self.state,{'id':update_id,'prompt':message.get('text',text)},action,snap)
                        self.state.db.execute('INSERT INTO incoming VALUES (?,?,NULL)',(update_id,'handled'))
                        self.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(update_id,'telegram'))
                        self.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)',('orchestrator:'+str(update_id)+':creation',reply))
                except (OSError,ValueError) as exc:self.send(str(exc))
                return
            try:
                thread_id, title, cwd = backends.create_task(self.state, arg, update_id)
            except ValueError as exc:
                self.send(str(exc))
                return
            backend = backends.task(self.state, thread_id)['backend']
            note = ('Send text, or /speak, /image, /video followed by a prompt. Gemini can inspect project text files and supplied references. Requested file contents are sent to Google. API usage may be billed.' if backend == 'gemini' else ('Send your first instruction. Read-only file tools can list, read, and search this project. Requested file contents are sent to this provider. Hidden/private paths and symlinks are excluded. API usage may be billed.' if backend in api.SPECS else 'Send your first instruction. Tool actions needing permission will ask here.'))
            self.send(f'Created: {title}\n{backend.capitalize()} · {cwd}\nTask: {thread_id}\n\n{note}', thread_id)
            return
        if command in ('/allow', '/deny'):
            try:
                token = approval_ui.command_token(self.state, message, arg)
                thread_id, result = approval_ui.decide(self, token, command == '/allow')
            except (ValueError, BridgeError) as exc:
                self.send(str(exc))
                return
            self.send(result, thread_id)
            return
        if command in ('/model', '/stop', '/recover'):
            thread_id = (arg.strip() if command in ('/stop', '/recover') and arg.strip()
                         else self.target_task(message, chat['id']))
            info = backends.task(self.state, thread_id)
            if not info:
                self.send('This command is for managed provider tasks. Reply to a task card from /tasks.')
                return
            status = self.state.db.execute('SELECT status FROM watched WHERE id=?', (thread_id,)).fetchone()[0]
            if command == '/stop':
                with self.state.db:
                    changed = self.state.db.execute("UPDATE backend_jobs SET cancel=1 WHERE thread_id=? AND status IN ('queued','running','waiting')", (thread_id,)).rowcount
                self.send(('Stop requested. The provider may continue a request already submitted.' if info['backend'] != 'claude' else 'Stop requested. I’ll confirm when Claude exits.') if changed else 'This task has no active run.', thread_id)
            elif command == '/recover':
                if status != 'uncertain':
                    self.send('This task does not need recovery.', thread_id)
                    return
                with self.state.db:
                    self.state.db.execute("UPDATE watched SET status='idle' WHERE id=?", (thread_id,))
                self.send('Ready for a new instruction. The previous instruction was not replayed. Check any partial work before continuing.', thread_id)
            else:
                model = arg.strip()
                if status != 'idle':
                    self.send('Wait until this task is idle before changing its model.', thread_id)
                    return
                if info['backend'] == 'gemini':
                    parts = model.split()
                    capability = parts[0] if len(parts) == 2 else 'text'
                    try:
                        model = gemini.model_name(parts[-1] if parts else '')
                        if capability not in gemini.DEFAULT_MODELS or len(parts) > 2:
                            raise ValueError('Use /model [text|speech|image|video] MODEL_ID.')
                    except ValueError as exc:
                        self.send(str(exc), thread_id)
                        return
                    with self.state.db:
                        self.state.db.execute('INSERT OR REPLACE INTO gemini_models VALUES (?,?,?)', (thread_id, capability, model))
                        if capability == 'text':
                            self.state.db.execute('UPDATE backend_tasks SET model=? WHERE id=?', (model, thread_id))
                    self.send(f'Gemini {capability} model set to {model}. Availability is checked when used.', thread_id)
                    return
                if info['backend'] in api.SPECS:
                    try:
                        model = api.model_name(model.removeprefix('text '))
                    except ValueError as exc:
                        self.send(str(exc), thread_id)
                        return
                elif not model or len(model) > 120 or any(c.isspace() for c in model):
                    self.send('Use /model sonnet, /model opus, or an exact Claude model ID available to your account.', thread_id)
                    return
                with self.state.db:
                    self.state.db.execute('UPDATE backend_tasks SET model=? WHERE id=?', (model, thread_id))
                self.send(f'{providers.REGISTRY[info["backend"]]["name"]} model set to {model}. It will be used on the next turn.', thread_id)
            return
        if command == '/tasks':
            rows = self.state.db.execute("SELECT w.*,COALESCE(b.backend,'codex') AS backend FROM watched w LEFT JOIN backend_tasks b ON b.id=w.id ORDER BY w.updated_at DESC LIMIT 12").fetchall()
            if not rows:
                self.send('No local tasks found yet.')
                return
            with self.state.db:
                for row in rows:
                    title = ' '.join(row['title'].split())[:100]
                    card = f"{title}\n{providers.REGISTRY[row['backend']]['name']} · {row['status']}\n\nReply to this message to continue this task.\nTask: {row['id']}"
                    self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                          (f'tasks:{update_id}:{row["id"]}', row['id'], card))
                self.state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'handled', ''))
            return
        if command == '/status':
            selected = self.target_task(message, chat['id'])
            info = backends.task(self.state, selected)
            if info:
                row = self.state.db.execute('SELECT * FROM watched WHERE id=?', (selected,)).fetchone()
                requests = self.state.db.execute("SELECT id,tool FROM tool_requests WHERE thread_id=? AND status='pending' AND expires_at>?", (selected, time.time())).fetchall()
                pending = ''.join(f"\nPermission: {r['tool']} · /allow {r['id']} or /deny {r['id']}" for r in requests)
                if info['backend'] == 'gemini':
                    run = self.state.db.execute('SELECT r.* FROM gemini_runs r JOIN backend_jobs j ON j.id=r.job_id WHERE j.thread_id=? ORDER BY j.created_at DESC LIMIT 1', (selected,)).fetchone()
                    if run:
                        pending += f"\nLast run: {run['capability']} · {run['model']} · {run['stage']}"
                        if run['capability'] == 'text' and json.loads(run['options_json']).get('workspace'):
                            count = self.state.db.execute('SELECT count(*) FROM api_tool_calls WHERE job_id=?', (run['job_id'],)).fetchone()[0]
                            pending += f'\nTools: list, read, and search project text files · {count} calls'
                        if run['operation_name']:
                            pending += '\nVideo operation saved; /resume can retry retrieval after interruption.'
                elif info['backend'] in api.SPECS:
                    run = self.state.db.execute('SELECT r.* FROM api_runs r JOIN backend_jobs j ON j.id=r.job_id WHERE j.thread_id=? ORDER BY j.created_at DESC LIMIT 1', (selected,)).fetchone()
                    pending += '\nTools: list, read, and search project text files'
                    if run:
                        count = self.state.db.execute('SELECT count(*) FROM api_tool_calls WHERE job_id=?', (run['job_id'],)).fetchone()[0]
                        pending += f"\nLast run: {run['stage']} · {count} file tool calls"
                self.send(f"New messages → Orchestrator. Reply here to continue this task.\n\n{providers.REGISTRY[info['backend']]['name']}: {row['status']}\n{row['title']}\nModel: {info['model']}\nFolder: {info['cwd']}\nTask: {selected}{pending}", selected)
                return
            try:
                with self.desktop_factory():
                    connected = 'connected'
            except Exception:
                connected = 'unavailable; open the app'
            self.send(f"New messages → Orchestrator. Reply to a task message to continue it.\n\nCodex desktop: {connected}\nCommand target: {selected or 'none'}", selected)
            return
        if command == '/speak':
            reply = message.get('reply_to_message', {})
            prompt = gemini.speech_text(arg or reply.get('text', '') or reply.get('caption', ''))
            if not prompt:
                self.send('Use /speak followed by text, or reply to a text message with /speak.')
                return
            try:
                tid = backends.enqueue_speech(self.state, self.target_task(message, chat['id']), prompt, update_id)
                self.send('Queued speech with Gemini. Reply here with /status or /stop to manage it. Audio will arrive here; replies to the audio continue the original task.', tid)
            except ValueError as exc:
                self.send(str(exc))
            return
        if command in ('/references', '/forget', '/resume'):
            tid = self.target_task(message, chat['id'])
            info = backends.task(self.state, tid)
            if command in ('/references', '/forget') and tid and not info and self.state.db.execute('SELECT 1 FROM watched WHERE id=?', (tid,)).fetchone():
                self.send(codex_inputs.references(self.state, tid) if command == '/references' else
                          codex_inputs.forget(self.state, tid, arg.strip()), tid)
                return
            if command == '/resume' and info and info['backend'] in api.SPECS:
                job = self.state.db.execute('SELECT id FROM backend_jobs WHERE thread_id=? ORDER BY created_at DESC LIMIT 1', (tid,)).fetchone()
                resumed = job and api.resume_job(self.state, job['id'], manual=True)
                self.send('Queued continuation from the saved API step. File inspection may require another model response; uncertain submissions are never replayed.' if resumed else 'No interrupted saved response is available. Check /status.', tid)
                return
            if not info or info['backend'] != 'gemini':
                self.send('Reply to a Gemini task message or select one with /use first.')
                return
            if command == '/references':
                rows = self.state.db.execute("SELECT id,filename FROM artifacts WHERE thread_id=? AND role='input' AND active=1", (tid,)).fetchall()
                self.send('\n'.join(f"{r['filename']} · /forget {r['id']}" for r in rows) or 'No active references. Attach a PDF, image, or text file (up to 10 MB).', tid)
            elif command == '/forget':
                with self.state.db:
                    changed = self.state.db.execute("UPDATE artifacts SET active=0 WHERE id=? AND thread_id=? AND role='input' AND active=1", (arg.strip(), tid)).rowcount
                self.send('Removed from new reference attachments. Earlier conversation turns and already queued jobs retain their snapshots; create a new task for a clean context.' if changed else 'Reference ID not found. Use /references.', tid)
            elif command == '/resume':
                row = self.state.db.execute('SELECT * FROM backend_jobs WHERE thread_id=? ORDER BY created_at DESC LIMIT 1', (tid,)).fetchone()
                if row and gemini.resume_job(self.state, row['id'], manual=True):
                    tool_run = self.state.db.execute('SELECT 1 FROM gemini_tool_runs WHERE job_id=?', (row['id'],)).fetchone()
                    self.send('Queued continuation from the saved Gemini step. File inspection may require another model response; uncertain submissions are never replayed.' if tool_run else 'Queued retrieval of the saved Gemini result. No new generation will be submitted.', tid)
                else:
                    self.send('No interrupted saved result is available to retrieve. /status shows the task state.', tid)
            return
        if command == '/emoji':
            # Accept /emoji SYMBOL while replying or after /use, plus an exact ID
            # form for managing tasks without changing the selected conversation.
            parts = arg.split()
            if len(parts) == 2:
                thread_id, value = parts
            else:
                thread_id = self.target_task(message, chat['id'])
                value = arg.strip()
            if not thread_id or not self.state.db.execute('SELECT 1 FROM watched WHERE id=?', (thread_id,)).fetchone():
                self.send('Reply to a task message with /emoji 🏠, or use /emoji TASK_ID 🏠.')
                return
            if not value:
                self.send('Set this task’s emoji with /emoji 🏠.', thread_id)
                return
            try:
                with self.state.db:
                    self.state.set_emoji(thread_id, value)
            except BridgeError as exc:
                self.send(str(exc), thread_id)
                return
            title = self.state.db.execute('SELECT title FROM watched WHERE id=?', (thread_id,)).fetchone()[0]
            self.send(f'Emoji set for {title[:180]}. Future messages will use this emoji.', thread_id)
            return
        if command == '/use':
            row = self.state.db.execute('SELECT * FROM watched WHERE id=?', (arg.strip(),)).fetchone()
            if not row:
                self.send('Task ID not found. Use /tasks and copy an exact ID.')
                return
            with self.state.db:
                self.state.put('selected', row['id'])
            self.send(f"Selected for commands: {row['title'][:180]}\nReply to this message to continue this task. New messages go to the orchestrator.", row['id'])
            return
        if text.startswith('/'):
            self.send(HELP)
            return
        self.submit_text(message, text, update_id, chat['id'])

    def codex_text_file(self, message, thread_id, update_id, chat_id):
        document = message['document']
        name = document.get('file_name', '')
        if Path(name).suffix.lower() not in ('.txt', '.md'):
            self.send('For long Codex instructions, attach a UTF-8 .txt or .md file (up to 100 KB).', thread_id)
            return
        row = self.state.db.execute('SELECT * FROM watched WHERE id=?', (thread_id,)).fetchone()
        if not row or row['status'] == 'running' or task_creation.task_status(self.state,thread_id,row['path']) != 'idle':
            self.send('This task is still running or unavailable. Send the text file after it finishes.', thread_id)
            return
        try:
            if document.get('file_size', 0) > 100_000:
                raise ValueError('Text file exceeds the 100 KB input limit.')
            # Use a generated private path; a Telegram filename is never a local path.
            with tempfile.TemporaryDirectory(prefix='codex-text-') as directory:
                path = Path(directory) / 'input.txt'
                self.telegram.download_file(document['file_id'], path, 100_000)
                raw = path.read_bytes()
                if len(raw) > 100_000:
                    raise ValueError('Text file exceeds the 100 KB input limit.')
                text = raw.decode('utf-8-sig')
                if not text.strip() or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
                    raise ValueError('Attach a nonempty UTF-8 text file, without binary content.')
        except UnicodeDecodeError:
            self.send('Save the file as UTF-8 .txt or .md and send it again.', thread_id)
            return
        except (ValueError, OSError, BridgeError) as exc:
            self.send(str(exc) if isinstance(exc, (ValueError, BridgeError)) else
                      'Could not read the text attachment. Please send it again.', thread_id)
            return
        caption = message.get('caption', '').strip()
        prompt = caption + '\n\n' + text if caption else text
        # File contents and captions are prompt data, never relay slash commands.
        # Standard submission rechecks idle state and records uncertain IPC sends.
        self.submit_text(message, prompt, update_id, chat_id)

    def submit_text(self, message, text, update_id, chat_id):
        thread_id = self.target_task(message, chat_id)
        if not thread_id:
            self.send('Reply to a task notification, or select one with /tasks and /use TASK_ID.')
            return
        if self.state.db.execute("SELECT 1 FROM task_creations WHERE task_id=? AND status IN ('created_pending','naming','opening','submitting','uncertain','needs_inspection')",(thread_id,)).fetchone():
            self.send('New-task creation or its first turn needs inspection before another instruction can be sent.',thread_id)
            return
        if self.state.db.execute("SELECT 1 FROM task_routes WHERE task_id=? AND status='guides_pending' AND expires>?", (thread_id,time.time())).fetchone():
            self.send('A guide choice is waiting. Use its Use guides, Continue without guides, or Cancel request button before sending more work.',thread_id)
            return
        if self.state.db.execute("SELECT 1 FROM task_routes WHERE task_id=? AND status IN ('queued','opening','submitting','uncertain')", (thread_id,)).fetchone():
            self.send('A routed request already owns this task. Check its delivery status before sending more work.', thread_id)
            return
        if workflows.user_intervention(self.state, thread_id):
            self.send('A workflow handoff to this project is in progress. Further handoffs are paused; check /workflow before resending your instruction.', thread_id)
            return
        if backends.task(self.state, thread_id):
            try:
                capability = backends.reply_capability(self.state, thread_id)
                backends.enqueue(self.state, thread_id, text, update_id, capability)
            except ValueError as exc:
                self.send(str(exc), thread_id)
                return
            name = providers.REGISTRY[backends.task(self.state, thread_id)['backend']]['name']
            label = f'{name} image editing' if capability == 'image' else name
            self.send(f'Queued for {label}. I’ll send the result here; /status checks progress and /stop requests cancellation.', thread_id)
            return
        row = self.state.db.execute('SELECT * FROM watched WHERE id=?', (thread_id,)).fetchone()
        if not row or row['status'] == 'running' or task_creation.task_status(self.state,thread_id,row['path']) != 'idle':
            self.send('This task is still running, or its state is unknown. Send your instruction after it finishes.', thread_id)
            return
        try:
            prompt, images, input_ids = codex_inputs.prepare(self.state, thread_id, text)
        except ValueError as exc:
            self.send(str(exc), thread_id)
            return
        # Discover first; a failed discovery has not submitted user work.
        with self.state.db:
            self.state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'received', thread_id))
        try:
            with self.desktop_factory() as desktop:
                owner = desktop.ready_owner(thread_id, on_open=lambda: self.send(
                    'Opening this task in Codex and reconnecting…', thread_id))
                # Loading can take seconds. A desktop user may have started work
                # during that interval, so refresh the rollout before dispatch.
                if task_creation.task_status(self.state,thread_id,row['path']) != 'idle':
                    with self.state.db:
                        self.state.db.execute('UPDATE incoming SET status=? WHERE id=?',
                                              ('failed', update_id))
                    self.send('This task started running while I was connecting. Your instruction was not sent.', thread_id)
                    return
                # Commit BEFORE a side effect. After an uncertain response we never
                # automatically submit the instruction a second time.
                if (prompt, images, input_ids) != codex_inputs.prepare(self.state, thread_id, text):
                    raise ValueError('Attachments changed while connecting. Your instruction was not sent; check /references and send it again.')
                with self.state.db:
                    codex_inputs.claim(self.state, update_id, input_ids)
                    self.state.db.execute('UPDATE incoming SET status=?,thread_id=? WHERE id=?',
                                          ('submitting', thread_id, update_id))
                    relay_channels.bind(self.state, 'task', thread_id, getattr(self, 'channel', 'telegram'))
                desktop.start(thread_id, prompt, owner, **({'images': images} if images else {}))
        except Exception as exc:
            status = self.state.db.execute('SELECT status FROM incoming WHERE id=?', (update_id,)).fetchone()[0]
            with self.state.db:
                self.state.db.execute('UPDATE incoming SET status=? WHERE id=?',
                                      ('uncertain' if status == 'submitting' else 'failed', update_id))
            if status != 'submitting' and isinstance(exc, ValueError):
                self.send(str(exc), thread_id)
                return
            self.send(('I could not confirm whether Codex accepted that instruction. Check the task before resending.'
                       if status == 'submitting' else
                       'I could not connect to this task in Codex. Your instruction was not sent. '
                       'Keep Codex open; if the task did not load automatically, open it manually and send again.'), thread_id)
            return
        with self.state.db:
            self.state.db.execute('UPDATE incoming SET status=? WHERE id=?', ('submitted', update_id))
            self.state.db.execute('UPDATE watched SET status=? WHERE id=?', ('running', thread_id))
        self.send('Sent to Codex. I’ll message you when this turn finishes.', thread_id)


def read_config():
    from .credentials import configuration, CredentialError
    try:
        value=configuration(DATA/'config.json',secret='token',enabled=False)
        if value is None:raise CredentialError('Telegram token is unavailable')
        return value
    except CredentialError as exc:
        raise BridgeError(str(exc)) from None


def configure():
    DATA.mkdir(mode=0o700, exist_ok=True)
    os.chmod(DATA, 0o700)
    print('Create a bot: open https://t.me/BotFather, send /newbot, follow its instructions.')
    existing = read_config() if (DATA / 'config.json').exists() else None
    token = existing['token'] if existing else getpass.getpass('Paste the bot token (hidden): ').strip()
    telegram = Telegram(token)
    bot = telegram.call('getMe')
    if telegram.call('getWebhookInfo').get('url'):
        raise BridgeError('This bot already has a webhook. Use a new dedicated bot.')
    config = {'token': token, 'username': bot['username'],
              'pair_code': secrets.token_urlsafe(24), 'pair_expires': time.time() + 3600}
    path = DATA / 'config.json'
    from .credentials import save
    save(path,config)
    state = State(DATA / 'state.sqlite')
    paired = state.get('user_id') is not None
    state.db.close()
    if paired:
        print('Your existing Telegram account pairing was preserved.')
    else:
        print(f"\nOpen this link in Telegram and tap Start (valid for one hour):\n"
              f"https://t.me/{bot['username']}?start={config['pair_code']}\n")
    print('Token saved locally with owner-only permissions.')


def install():
    return HOST.telegram_service('install',ROOT=ROOT,DATA=DATA,PATHS=PATHS,read_config=read_config,BridgeError=BridgeError)


def uninstall():
    return HOST.telegram_service('uninstall',ROOT=ROOT,BridgeError=BridgeError)


def doctor():
    tasks = local_tasks()
    print(f'Local tasks readable: {len(tasks)}')
    with Desktop() as desktop:
        print('Desktop IPC: connected')
        for task in tasks[:5]:
            try:
                desktop.owner(task['id'])
                print('Task-owner discovery: passed')
                break
            except BridgeError:
                continue
        else:
            raise BridgeError('No recent task has an available owner; open a task in Codex.')
    print('Telegram: configured' if (DATA / 'config.json').exists() else 'Telegram: awaiting bot token')


def log_operation_error(operation, exc):
    status = f' HTTP={exc.status}' if isinstance(exc, TelegramError) else ''
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    print(f'{stamp} {operation}: {type(exc).__name__}{status}', flush=True)


class BackgroundWorkers:
    """Each worker owns its SQLite connection; HTTP never holds a DB transaction."""
    def __init__(self, state_path, config, pacer, telegram_factory=Telegram, watcher_factory=Watcher):
        self.state_path, self.config, self.pacer = state_path, config, pacer
        self.telegram_factory, self.watcher_factory = telegram_factory, watcher_factory
        self.stop = threading.Event()
        self.threads = []

    def start(self):
        for name, interval in [('updates', 60), ('usage',30), ('scan', 2), ('approvals', 2), ('workflows', 5), ('orchestrator-chat', .5), ('production-planning', .5), ('reference-packs', 1), ('task-routing', .5), ('task-creation', .5), ('production', 2), ('notifications', .5), ('uploads', 1), ('backends', .5), ('gemini', .5), ('inputs', 1), ('codex-inputs', .5), ('providers', .5), *[(p, .5) for p in api.SPECS]]:
            thread = threading.Thread(target=self.work, args=(name, interval),
                                      name=f'bridge-{name}', daemon=True)
            self.threads.append(thread)
            thread.start()

    def work(self, name, interval):
        state = State(self.state_path)
        bridge = Bridge(state, self.telegram_factory(self.config['token'], self.pacer), self.config)
        watcher = self.watcher_factory(state)
        backend_worker = backends.BackendWorker(state, backend='claude' if name == 'backends' else name) if name in ('backends', 'gemini', *api.SPECS) else None
        provider_worker = providers.Worker(state, telegram=bridge.telegram) if name == 'providers' else None
        production_worker = production_control.Worker(state, telegram=bridge.telegram) if name == 'production' else None
        from . import releases
        job = {'updates': lambda: releases.tick(state, bridge.telegram),
               'scan': watcher.scan,
               'reference-packs': reference_packs.Worker(state).tick,
               'task-routing': task_routing.Worker(state, Desktop).tick,
               'task-creation': task_creation.Worker(state, Desktop).tick,
               'production': production_worker.tick if production_worker else None,
               'orchestrator-chat': orchestrator_chat.Worker(state).tick,
               'production-planning': orchestrator_chat.production_planning.Worker(state).tick,
               'usage': usage_tracker.Worker(state).tick,
               'workflows': workflows.Worker(state, Desktop).tick,
               'approvals': codex_approvals.Worker(state, Desktop).tick,
               **{p: backend_worker.tick if backend_worker else None for p in api.SPECS},
               'notifications': lambda: bridge.flush(include_media=False),
               'uploads': bridge.flush_media,
               'backends': backend_worker.tick if backend_worker else None,
               'gemini': backend_worker.tick if backend_worker else None,
               'inputs': gemini.InputWorker(state, bridge.telegram).tick,
               'codex-inputs': codex_inputs.Worker(state, bridge.telegram).tick,
               'providers': provider_worker.tick if provider_worker else None}[name]
        backoff = 2
        runtime_evidence = {}
        if name == 'orchestrator-chat':
            from orchestrator.execution import REGISTRY
            runtime_evidence = {'interface_version': 1, 'process_id': os.getpid(),
                                'registered_graph_operations': sorted(REGISTRY)}
        try:
            while not self.stop.is_set():
                start = time.monotonic()
                try:
                    job()
                    with state.db:
                        state.put(f'health:{name}', {'last_success': time.time(),
                                                   'seconds': round(time.monotonic() - start, 3),
                                                   **runtime_evidence})
                    backoff = 2
                    self.stop.wait(interval)
                except Exception as exc:
                    state.db.rollback()
                    log_operation_error(name, exc)
                    self.stop.wait(max(backoff, getattr(exc, 'retry_after', 0)))
                    backoff = min(backoff * 2, 30)
        finally:
            if backend_worker:
                backend_worker.close()
            if provider_worker:
                provider_worker.close()
            if production_worker:
                production_worker.close()
            state.db.close()

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=7 if thread.name in ('bridge-backends', 'bridge-gemini', 'bridge-providers', *('bridge-' + p for p in api.SPECS)) else .2)


def receive_updates(bridge):
    """Commands are polled independently of scans, notifications and uploads."""
    state = bridge.state
    channel_policy.heartbeat(state, 'telegram', 'intake')
    polled_at = time.time()
    updates = bridge.telegram.call('getUpdates', offset=state.get('offset', 0),
                                   timeout=5, limit=100, allowed_updates=['message', 'callback_query'])
    accept_after = channel_policy.read(state.db)['accept_after']['telegram']
    # Telegram callbacks have no click timestamp. Drain the first batch after
    # re-enabling before admitting callbacks, including after an offline pause.
    drain_callbacks = state.get('channel:telegram:accept_after', 0) < accept_after
    for update in updates:
        started = time.monotonic()
        received = time.time()
        try:
            if not (drain_callbacks and 'callback_query' in update):
                bridge.process(update, received_at=polled_at)
        except channel_policy.ChannelPaused:
            # A reply/ack was stopped before transport. Never replay its command.
            pass
        with state.db:
            state.put('offset', update['update_id'] + 1)
            state.put('health:commands', {
                'last_success': time.time(), 'seconds': round(time.monotonic() - started, 3),
                'delivery_lag_seconds': max(0, round(received - update.get('message', {}).get('date', received), 3))})
    with state.db:
        if polled_at >= accept_after and len(updates) < 100:
            state.put('channel:telegram:accept_after', accept_after)
        state.put('health:poll', {'last_success': time.time()})
    from .desktop_tasks import process_commands
    process_commands(bridge)
    from .desktop_plans import process_requests
    process_requests(state)


def run():
    config = read_config()
    DATA.mkdir(mode=0o700, exist_ok=True)
    lock = (DATA / 'bridge.lock').open('w')
    try:
        HOST.lock(lock)
    except BlockingIOError:
        raise BridgeError('The bridge is already running.') from None
    from .update_gate import startup
    startup()
    from task_relay.messages_storage import require_consolidated
    require_consolidated(DATA / 'state.sqlite', PATHS.messages)
    state = State(DATA / 'state.sqlite')
    pacer = SendPacer()
    bridge = Bridge(state, Telegram(config['token'], pacer), config)
    # A restart after a lost acknowledgement cannot safely replay a command.
    with state.db:
        uncertain = state.db.execute("SELECT id,thread_id,status FROM incoming WHERE status IN ('submitting','received') AND NOT EXISTS (SELECT 1 FROM backend_tasks b WHERE b.id=incoming.thread_id)").fetchall()
        for row in uncertain:
            state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                             (f"uncertain:{row['id']}", row['thread_id'],
                              ('The bridge restarted during instruction delivery. Check this task before resending.'
                               if row['status'] == 'submitting' else
                               'The bridge restarted before delivering your instruction. Please send it again.')))
        state.db.execute("UPDATE incoming SET status='uncertain' WHERE status='submitting' AND NOT EXISTS (SELECT 1 FROM backend_tasks b WHERE b.id=incoming.thread_id)")
        state.db.execute("UPDATE incoming SET status='failed' WHERE status='received' AND NOT EXISTS (SELECT 1 FROM backend_tasks b WHERE b.id=incoming.thread_id)")
    from .desktop_tasks import recover_commands
    recover_commands(state)
    workers = BackgroundWorkers(DATA / 'state.sqlite', config, pacer)
    workers.start()
    shutdown_requested = threading.Event()
    def terminate_service(*_):
        # A remotely approved command can restart this very process. Finish the
        # current approval acknowledgement and Telegram offset before exiting.
        shutdown_requested.set()
    signal.signal(signal.SIGTERM, terminate_service)
    print('Bridge running with independent command, scan, notification and upload workers.', flush=True)
    backoff = 2
    try:
        while not shutdown_requested.is_set():
            try:
                receive_updates(bridge)
                backoff = 2
            except (BridgeError, OSError, ValueError, sqlite3.Error) as exc:
                state.db.rollback()
                log_operation_error('commands', exc)
                shutdown_requested.wait(max(backoff, getattr(exc, 'retry_after', 0)))
                backoff = min(backoff * 2, 15)
    finally:
        workers.close()
        state.db.close()
        lock.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['configure', 'doctor', 'run', 'install', 'uninstall'])
    args = parser.parse_args()
    try:
        {'configure': configure, 'doctor': doctor, 'run': run,
         'install': install, 'uninstall': uninstall}[args.command]()
    except KeyboardInterrupt:
        print('\nStopped.')
    except (BridgeError, UnsupportedHost) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
