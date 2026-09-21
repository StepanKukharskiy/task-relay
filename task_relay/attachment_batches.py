"""Durable Telegram upload groups and once-only caption handoff."""
import hashlib
import time
from pathlib import Path

QUIET_SECONDS = 3


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS relay_attachment_batches (
      id TEXT PRIMARY KEY, last_received REAL NOT NULL, notified_count INTEGER NOT NULL DEFAULT 0,
      request_id INTEGER);
    CREATE TABLE IF NOT EXISTS relay_attachment_members (
      upload_id INTEGER PRIMARY KEY, batch TEXT NOT NULL, album INTEGER NOT NULL);
    ''')


def receive(state, message, ident):
    # Only unassigned orchestrator attachments participate. Production guides
    # retain their separate approval/revision semantics.
    group = message.get('media_group_id')
    key = str(message['chat']['id']) + ':' + ('album:' + str(group) if group else 'file:' + str(ident))
    batch = hashlib.sha256(key.encode()).hexdigest()[:24]
    first = not state.db.execute('SELECT 1 FROM relay_attachment_batches WHERE id=?', (batch,)).fetchone()
    state.db.execute('''INSERT INTO relay_attachment_batches(id,last_received) VALUES (?,?)
        ON CONFLICT(id) DO UPDATE SET last_received=excluded.last_received''', (batch, time.time()))
    state.db.execute('INSERT INTO relay_attachment_members VALUES (?,?,?)', (ident, batch, bool(group)))
    from .codex_inputs import MAX_TOTAL
    others = budget_members(state,ident)
    current = state.db.execute('SELECT declared_size FROM production_uploads WHERE id=?',(ident,)).fetchone()[0]
    if len(others) >= 10 or sum(r[0] for r in others) + current > MAX_TOTAL:
        raise ValueError('Use at most 10 files and 50 MB per attachment group.')
    pending = state.db.execute("SELECT sum(declared_size) FROM production_uploads WHERE run='@orchestrator' AND status='pending'").fetchone()[0]
    if pending > MAX_TOTAL:
        raise ValueError('Pending downloads exceed 50 MB. Wait for current uploads to finish.')
    if first:
        from .orchestrator_chat import queue_notice
        queue_notice(state, 'attachments-receiving:' + batch,
                     'Receiving attachments. I’ll show their local folder when the downloads finish and handle any caption with the saved files.')
    return batch


def budget_members(state, ident):
    member = state.db.execute('SELECT batch FROM relay_attachment_members WHERE upload_id=?', (ident,)).fetchone()
    if not member:return None
    return state.db.execute("""SELECT COALESCE(u.bytes,u.declared_size) FROM production_uploads u
        JOIN relay_attachment_members m ON m.upload_id=u.id
        WHERE m.batch=? AND u.id!=? AND u.status IN ('pending','ready')""", (member[0], ident)).fetchall()


def relative_path(state, row):
    member = state.db.execute('SELECT * FROM relay_attachment_members WHERE upload_id=?', (row['id'],)).fetchone()
    if member and member['album']:
        return 'albums/' + member['batch'] + '/' + str(row['id']) + '-' + row['filename']
    return str(row['id']) + '/' + row['filename']


def selected(state, request_id):
    return state.get('orchestrator-attachments:' + str(request_id))


def finish(state, now=None):
    """Queue notices and one caption atomically; no provider or transport calls."""
    from . import production_control as pc, orchestrator_chat as chat
    now = time.time() if now is None else now
    with state.db:
        batches = state.db.execute('SELECT * FROM relay_attachment_batches WHERE last_received<=?',
                                  (now - QUIET_SECONDS,)).fetchall()
        for batch in batches:
            rows = state.db.execute('''SELECT u.* FROM production_uploads u
                JOIN relay_attachment_members m ON m.upload_id=u.id WHERE m.batch=? ORDER BY u.id''',
                (batch['id'],)).fetchall()
            if len(rows) <= batch['notified_count'] or any(r['status'] == 'pending' for r in rows):
                continue
            ready = [r for r in rows if r['status'] in ('ready', 'used')]
            failed = [r for r in rows if r not in ready]
            captions = list(dict.fromkeys(r['caption'] for r in rows if r['caption'].strip()))
            paths = [str(Path(r['path']).parent) for r in ready]
            folders = list(dict.fromkeys(paths))
            text = f"Saved {len(ready)} attachment(s) on the Relay computer."
            if folders:
                text += '\n\nFolder' + ('s' if len(folders) > 1 else '') + ':\n' + '\n'.join(folders)
                text += '\n\nFiles:\n' + '\n'.join(Path(r['path']).name for r in ready)
            if failed:
                text += '\n\nNot saved: ' + ', '.join(r['filename'] for r in failed) + '. Please resend these files. Your caption is retained; it has not started work.'
            elif batch['request_id'] is not None:
                text += '\n\nLate album attachments were saved. They were not added to the earlier request; send a new instruction to use them.'
            elif len(captions) > 1:
                text += '\n\nThis group has different captions. Send one instruction for the saved files.'
            elif captions:
                caption = captions[0]
                try:
                    if len(caption) > 16000:
                        raise ValueError('Caption exceeds the 16,000-character request limit.')
                    provider, model = chat.provider(state)
                    if state.db.execute("SELECT count(*) FROM orchestrator_chats WHERE status IN ('queued','sending')").fetchone()[0] >= 5:
                        raise ValueError('Five requests are already pending.')
                except ValueError as exc:
                    text += '\n\nCaption saved but not queued: ' + str(exc) + ' Send your instruction after resolving this.'
                else:
                    ident = rows[0]['id']
                    state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (?,?,NULL,?,?,?)',
                                     (ident, caption, provider, model, now))
                    state.put('orchestrator-attachments:' + str(ident), [r['id'] for r in ready])
                    state.db.execute('UPDATE relay_attachment_batches SET request_id=? WHERE id=?', (ident, batch['id']))
                    text += '\n\nYour caption is queued once with these exact attachments.'
            else:
                text += '\n\nSend an instruction if you want Relay to do more with these files.'
            pc.notice(state, '@orchestrator', 'attachments:' + batch['id'] + '-' + str(len(rows)), text)
            state.db.execute('UPDATE relay_attachment_batches SET notified_count=? WHERE id=?', (len(rows), batch['id']))
