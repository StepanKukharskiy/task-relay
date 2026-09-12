"""Durable Telegram attachments for the next instruction to a local Codex task."""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

MAX_FILE = 20_000_000
MAX_TOTAL = 50_000_000
MAX_COUNT = 10
KINDS = ('document', 'photo', 'video', 'audio', 'voice', 'animation', 'video_note', 'sticker')
IMAGES = ('.png', '.jpg', '.jpeg', '.webp')


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS codex_inputs (
        id TEXT PRIMARY KEY, update_id INTEGER UNIQUE NOT NULL, thread_id TEXT NOT NULL,
        file_id TEXT NOT NULL, filename TEXT NOT NULL, kind TEXT NOT NULL,
        caption TEXT NOT NULL, declared_size INTEGER NOT NULL,
        path TEXT, sha256 TEXT, size INTEGER, image INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS codex_input_uses (
        incoming_id INTEGER NOT NULL, input_id TEXT NOT NULL,
        PRIMARY KEY(incoming_id,input_id));
      CREATE TABLE IF NOT EXISTS codex_input_albums (
        chat_id INTEGER NOT NULL, album_id TEXT NOT NULL, thread_id TEXT NOT NULL,
        PRIMARY KEY(chat_id,album_id));
    ''')


def album_target(state, message, target):
    group = message.get('media_group_id')
    if not group:
        return target
    row = state.db.execute('SELECT thread_id FROM codex_input_albums WHERE chat_id=? AND album_id=?',
                           (message['chat']['id'], group)).fetchone()
    if row:
        if message.get('reply_to_message') and target != row['thread_id']:
            raise ValueError('This album has conflicting task replies. Send it again to one task.')
        return row['thread_id']
    return target


def upload(message):
    # Animation messages can also contain a legacy document field.
    kind = next((k for k in ('animation', *KINDS) if message.get(k)), None)
    if not kind:
        raise ValueError('No downloadable file in this message.')
    entry = message[kind]
    if kind == 'photo':
        entry = max(entry, key=lambda p: p.get('width', 0) * p.get('height', 0))
    fallback = {'photo': 'photo.jpg', 'video': 'video.mp4', 'video_note': 'video-note.mp4',
                'audio': 'audio.mp3', 'voice': 'voice.ogg', 'animation': 'animation.mp4',
                'sticker': 'sticker.webm' if entry.get('is_video') else
                           ('sticker.tgs' if entry.get('is_animated') else 'sticker.webp')}.get(kind, 'document.bin')
    # Preserve a readable name, but never let remote metadata select a local path.
    filename = str(entry.get('file_name') or fallback).replace('\\', '/').split('/')[-1]
    filename = re.sub(r'[^\w .()\-]', '_', filename).strip(' .')[:160] or fallback
    size = entry.get('file_size', 0)
    if not isinstance(size, int) or size < 0 or size > MAX_FILE:
        raise ValueError('Telegram attachments must be at most 20 MB each.')
    return kind, entry['file_id'], filename, size


def receive(state, message, tid, update_id):
    kind, file_id, name, size = upload(message)
    token = 'cf-' + uuid.uuid4().hex[:16]
    with state.db:
        # A write lock makes reservations and the count/size checks atomic.
        state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'attachment', tid))
        rows = state.db.execute("SELECT declared_size,size FROM codex_inputs WHERE thread_id=? AND status IN ('pending','ready')", (tid,)).fetchall()
        if len(rows) >= MAX_COUNT or sum(r['size'] if r['size'] is not None else r['declared_size'] for r in rows) + size > MAX_TOTAL:
            raise ValueError('Use at most 10 pending attachments and 50 MB total. Use /references and /forget ID to remove one.')
        state.db.execute('INSERT INTO codex_inputs(id,update_id,thread_id,file_id,filename,kind,caption,declared_size) '
                         'VALUES (?,?,?,?,?,?,?,?)',
                         (token, update_id, tid, file_id, name, kind, message.get('caption', ''), size))
        if message.get('media_group_id'):
            state.db.execute('INSERT OR IGNORE INTO codex_input_albums VALUES (?,?,?)',
                             (message['chat']['id'], message['media_group_id'], tid))
        # Let replies to a user's own upload select the same task too.
        if message.get('message_id') is not None:
            state.remember(message['chat']['id'], message['message_id'], tid)


class Worker:
    def __init__(self, state, telegram):
        self.state, self.telegram = state, telegram

    def tick(self):
        row = self.state.db.execute("SELECT * FROM codex_inputs WHERE status='pending' AND next_attempt<=? ORDER BY update_id LIMIT 1", (time.time(),)).fetchone()
        if not row:
            return
        path = self.state.media_dir.parent / 'codex-inputs' / row['id'] / row['filename']
        try:
            self.telegram.download_file(row['file_id'], path, MAX_FILE)
            data = path.read_bytes()
            if not data or len(data) > MAX_FILE:
                raise ValueError('File is empty or exceeds 20 MB.')
            suffix = path.suffix.lower()
            image = suffix in IMAGES
            if image:
                from task_relay.media import valid_image
                if not valid_image(data, suffix):
                    raise ValueError('Image bytes do not match the file type.')
            with self.state.db:
                changed = self.state.db.execute("UPDATE codex_inputs SET path=?,sha256=?,size=?,image=?,status='ready' WHERE id=? AND status='pending'",
                                                (str(path.resolve()), hashlib.sha256(data).hexdigest(), len(data), int(image), row['id'])).rowcount
                if changed:
                    total = self.state.db.execute("SELECT sum(COALESCE(size,declared_size)) FROM codex_inputs WHERE thread_id=? AND status IN ('pending','ready')", (row['thread_id'],)).fetchone()[0]
                    if total > MAX_TOTAL:
                        raise ValueError('Pending attachments exceed 50 MB total.')
                    self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                        ('codex-input:' + row['id'], row['thread_id'],
                         f"Attached: {row['filename']}\nSend your instruction after all files are attached. Captions are saved with the files.\n/references · /forget {row['id']}"))
            if not changed:
                path.unlink(missing_ok=True)
        except Exception as exc:
            attempts = row['attempts'] + 1
            failed = isinstance(exc, ValueError) or getattr(exc, 'status', 0) in (400, 403, 404) or attempts >= 3
            with self.state.db:
                changed = self.state.db.execute("UPDATE codex_inputs SET status=?,attempts=?,next_attempt=? WHERE id=? AND status='pending'",
                     ('failed' if failed else 'pending', attempts, time.time() + attempts * 15, row['id'])).rowcount
                if failed and changed:
                    self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                        ('codex-input:' + row['id'], row['thread_id'],
                         f"Could not attach {row['filename']}. Send it again (up to 20 MB), or /forget {row['id']} before continuing."))
            path.unlink(missing_ok=True)


def prepare(state, tid, text):
    rows = state.db.execute("SELECT * FROM codex_inputs WHERE thread_id=? AND status IN ('pending','ready','failed') ORDER BY update_id", (tid,)).fetchall()
    if any(r['status'] == 'pending' for r in rows):
        raise ValueError('A file is still downloading. Wait for “Attached”, then send your instruction again.')
    if any(r['status'] == 'failed' for r in rows):
        raise ValueError('A file could not be attached. Use /references and /forget its ID before sending your instruction.')
    if len(rows) > MAX_COUNT or sum(r['size'] for r in rows) > MAX_TOTAL:
        raise ValueError('Too many pending attachments. Use /references and /forget ID.')
    images, manifest = [], []
    root = (state.media_dir.parent / 'codex-inputs').resolve()
    for row in rows:
        path = Path(row['path'])
        if path.is_symlink() or path.resolve().parent != root / row['id'] or not path.is_file():
            raise ValueError('An attached file is missing or changed. Remove it with /forget and upload it again.')
        try:
            with path.open('rb') as source:
                data = source.read(MAX_FILE + 1)
        except OSError:
            raise ValueError('An attached file cannot be read. Remove it with /forget and upload it again.') from None
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('An attached file changed. Remove it with /forget and upload it again.')
        manifest.append({'name': row['filename'], 'path': str(path), 'caption': row['caption'],
                         'kind': row['kind'], 'bytes': row['size']})
        if row['image']:
            images.append(str(path))
    if manifest:
        text += ('\n\nFiles supplied by the user for this instruction (JSON metadata):\n' +
                 json.dumps(manifest, ensure_ascii=True, indent=2) +
                 '\nImages are also attached as visual input. Other files are available at the listed absolute paths. '
                 'Inspect them with available tools as needed. Audio/video files have not been transcribed or decoded by the relay.')
    return text, images, [r['id'] for r in rows]


def claim(state, update_id, tokens):
    """Called in the same transaction as marking the instruction submitting."""
    for token in tokens:
        changed = state.db.execute("UPDATE codex_inputs SET status='used' WHERE id=? AND status='ready'", (token,)).rowcount
        if not changed:
            raise ValueError('Attachments changed before submission. Check /references and try again.')
        state.db.execute('INSERT INTO codex_input_uses VALUES (?,?)', (update_id, token))


def references(state, tid):
    rows = state.db.execute("SELECT id,filename,status FROM codex_inputs WHERE thread_id=? AND status IN ('pending','ready','failed') ORDER BY update_id", (tid,)).fetchall()
    return '\n'.join(f"{r['filename']} · {r['status']} · /forget {r['id']}" for r in rows) or 'No files waiting for the next instruction. Previously sent files remain in the task history.'


def forget(state, tid, token):
    with state.db:
        changed = state.db.execute("UPDATE codex_inputs SET status='forgotten' WHERE id=? AND thread_id=? AND status IN ('pending','ready','failed')", (token, tid)).rowcount
    return 'Removed from the next instruction.' if changed else 'Pending attachment not found in this task. Use /references.'
