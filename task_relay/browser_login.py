"""Chat-assisted login control. Journal metadata only; credentials stay in a pipe."""
import secrets
import time
from pathlib import Path
from orchestrator.storage import transaction
from . import host_login

PREFIX = 'browser-login:'


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS browser_login_inputs(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, kind TEXT NOT NULL,
        status TEXT NOT NULL, expires REAL NOT NULL, chat_id INTEGER,
        prompt_id INTEGER, created REAL NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS browser_login_message
        ON browser_login_inputs(chat_id,prompt_id) WHERE prompt_id IS NOT NULL;''')


def data(state):
    return Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent


def request_input(state, job, kind, now=None):
    if kind not in ('email', 'code', 'password'):
        raise ValueError('Unsupported login field.')
    now = time.time() if now is None else now
    ident = secrets.token_hex(16)
    with transaction(state.db):
        if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND operation='browser_chat_login' AND status='running'", (job,)).fetchone():
            raise ValueError('Login session is no longer running.')
        state.db.execute("UPDATE browser_login_inputs SET status='expired' WHERE job=? AND status='waiting'", (job,))
        state.db.execute('INSERT INTO browser_login_inputs VALUES (?,?,?,?,?,?,NULL,?)',
                         (ident, job, kind, 'waiting', now+180, state.get('chat_id'), now))
        label = {'email': 'email address', 'code': 'email verification code', 'password': 'password'}[kind]
        text = (f'Perplexity sign-in · https://www.perplexity.ai\nReply directly to THIS message with your {label}. '
                'Expires in 3 minutes. /browser cancel stops sign-in.\n'
                'Telegram receives your reply. Relay requests message deletion and sends the value only to this login window; '
                'it is not saved in task history or sent to a model. Deletion cannot guarantee removal from Telegram.')
        state.db.execute("INSERT INTO outbox(id,thread_id,text) VALUES (?,'',?)", (PREFIX+ident, text))
    return ident


def controls(state, event):
    if event.startswith(PREFIX) and state.db.execute('SELECT 1 FROM browser_login_inputs WHERE id=?', (event[len(PREFIX):],)).fetchone():
        return {'force_reply': True, 'selective': True, 'input_field_placeholder': 'Reply only to this login prompt'}


def remember(state, event, chat, message):
    if event.startswith(PREFIX):
        # Retain all historical prompt identities so stale replies never become tasks.
        state.db.execute('UPDATE browser_login_inputs SET prompt_id=? WHERE id=? AND chat_id=? AND prompt_id IS NULL',
                         (message, event[len(PREFIX):], chat))


def finish(state, job, status):
    state.db.execute("UPDATE browser_login_inputs SET status=CASE WHEN status IN ('claimed','submitting') THEN 'uncertain' ELSE ? END WHERE job=? AND status IN ('waiting','claimed','submitting')", (status, job))


def receive(bridge, message, update_id):
    state = bridge.state
    reply = message.get('reply_to_message', {}).get('message_id')
    row = state.db.execute('SELECT * FROM browser_login_inputs WHERE chat_id=? AND prompt_id=?',
                          (state.get('chat_id'), reply)).fetchone() if reply else None
    raw = message.get('text', '')
    active = state.db.execute("SELECT 1 FROM provider_jobs WHERE provider='perplexity' AND operation='browser_chat_login' AND status IN ('queued','running')").fetchone()
    reserved = raw.startswith('/login ') or raw == '/login'
    orphan_prompt = message.get('reply_to_message', {}).get('text', '').startswith('Perplexity sign-in · https://www.perplexity.ai')
    if not row and not reserved and not orphan_prompt and not (active and not raw.startswith('/')):
        return False
    # Authentication is also checked here so callers cannot accidentally bypass it.
    if (message.get('chat', {}).get('type') != 'private' or message.get('chat', {}).get('id') != state.get('chat_id')
            or message.get('from', {}).get('id') != state.get('user_id') or message.get('from', {}).get('is_bot')):
        return True
    claimed = False
    with transaction(state.db):
        if state.db.execute('SELECT 1 FROM incoming WHERE id=?', (update_id,)).fetchone():
            return True
        state.db.execute("INSERT INTO incoming VALUES (?,'handled',NULL)", (update_id,))
        state.db.execute('INSERT OR IGNORE INTO provider_deletions(chat_id,message_id) VALUES (?,?)',
                         (state.get('chat_id'), message['message_id']))
        if row and isinstance(raw, str) and 0 < len(raw.encode()) <= 1024:
            claimed = state.db.execute("UPDATE browser_login_inputs SET status='claimed' WHERE id=? AND status='waiting' AND expires>? AND job IN (SELECT id FROM provider_jobs WHERE status='running')",
                                       (row['id'], time.time())).rowcount == 1
    # Never put raw input or transport exception text in a receipt or reply.
    if claimed:
        try:
            host_login.send(data(state), row['job'], row['id'], raw)
        except Exception:
            with transaction(state.db):
                state.db.execute("UPDATE browser_login_inputs SET status='uncertain' WHERE id=? AND status='claimed'", (row['id'],))
            bridge.send('Login input could not be confirmed. It will not be replayed. Use /browser status, then /browser cancel before starting another session.')
    else:
        bridge.send('No current matching login prompt. This reply was not used or sent to a task. Use /browser chat to start, then reply directly to its latest prompt.')
    return True


def run(state, job, driver, inbox, timeout=600):
    from . import browser_setup
    deadline = time.monotonic()+timeout
    driver.begin_login()
    previous = None
    challenge = None
    while time.monotonic() < deadline:
        if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND status='running'", (job,)).fetchone():
            return
        stage = driver.login_stage()
        if stage == 'ready':
            browser_setup.finish(state, job, True, 'Perplexity browser connected. Its session is saved on the Relay computer. No search was submitted.')
            return
        if stage not in ('email', 'code', 'password'):
            if previous!='manual':
                with transaction(state.db):
                    finish(state,job,'expired')
                browser_setup.progress(state,job,'browser_interaction_required',
                    'Perplexity needs browser interaction or verification on the Relay computer. No credential is requested in this state. Complete that step there, or /browser cancel. Chat sign-in will continue only after a recognized login form appears.')
                previous='manual'
            driver.pause()
            continue
        if stage != previous:
            identity = driver.login_identity(stage)
            challenge = request_input(state, job, stage)
            previous = stage
        row = state.db.execute('SELECT * FROM browser_login_inputs WHERE id=?', (challenge,)).fetchone()
        if row['expires'] <= time.time() or row['status'] == 'uncertain':
            raise ValueError('Login prompt expired or delivery is uncertain.')
        envelope = inbox.poll()
        if envelope is None:
            continue
        if envelope['challenge'] != challenge:
            raise ValueError('Login input does not match the current prompt.')
        with transaction(state.db):
            claimed = state.db.execute("UPDATE browser_login_inputs SET status='submitting' WHERE id=? AND status='claimed' AND expires>? AND job IN (SELECT id FROM provider_jobs WHERE status='running')",
                                       (challenge, time.time())).rowcount
            if not claimed:
                raise ValueError('Login input is no longer eligible.')
        # Durable intent precedes DOM writes. The driver rechecks domain and stage.
        try:
            driver.login_submit(stage, envelope['value'], identity)
        finally:
            envelope.clear()
        with transaction(state.db):
            state.db.execute("UPDATE browser_login_inputs SET status='consumed' WHERE id=? AND status='submitting'", (challenge,))
        # Do not issue another prompt or retry while the submitted stage is unchanged.
        transition = time.monotonic()+20
        while driver.login_stage() == stage and time.monotonic() < transition:
            if not state.db.execute("SELECT 1 FROM provider_jobs WHERE id=? AND status='running'", (job,)).fetchone():
                return
            driver.pause()
        if driver.login_stage() == stage:
            raise ValueError('Sign-in did not advance. Check the browser before trying again.')
    raise ValueError('Chat-assisted sign-in timed out.')
