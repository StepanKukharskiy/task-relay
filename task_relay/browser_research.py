"""One authorized Perplexity Search job, executed by the connected browser helper."""
import hashlib
import re
import time
from pathlib import Path

from orchestrator.storage import transaction
from .browser_jobs import Journal, conversation_url, execute


def initialize(db):
    Journal(db)
    db.execute('''CREATE TABLE IF NOT EXISTS browser_research_requests(
        id TEXT PRIMARY KEY, source TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
        channel TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS browser_research_connection(
        id INTEGER PRIMARY KEY CHECK(id=1), session TEXT NOT NULL, updated REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS browser_research_transport(
        id TEXT PRIMARY KEY, transport TEXT NOT NULL)''')


SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['kind', 'site', 'query'], 'properties': {
              'kind': {'const': 'browser_research'}, 'site': {'const': 'perplexity'},
              'query': {'type': 'string', 'minLength': 1, 'maxLength': 12000,
                        'description': 'Self-contained research question for the website, preserving the user’s scope without Relay/browser routing instructions.'}}}


def catalog(state):
    """Configuration evidence only; the worker checks the actual saved session."""
    from types import SimpleNamespace
    from .managed_browser import status
    data = Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent
    info = status(SimpleNamespace(data=data))
    blocker = (info['error'] or ('Enable Browser use in Task Relay Settings.' if not info['enabled'] else
               'Choose Done signing in in Task Relay Settings.' if info['manual_sign_in'] else None))
    initialize(state.db)
    recent = [dict(r) for r in state.db.execute(
        "SELECT r.id,r.request,j.prompt AS query,r.state,j.url,j.error FROM browser_research_requests r "
        "JOIN browser_jobs j ON j.id=r.id WHERE r.channel=? ORDER BY r.created DESC LIMIT 5",
        (getattr(state, 'channel', 'telegram'),))]
    return dict(id='browser_research', executor='relay.managed_chrome',
                input_schema=SCHEMA, available=not blocker, blocker=blocker,
                sites=['perplexity'], session='Checked by the worker before submission; configuration is not proof of sign-in.',
                permissions='Explicit research request; one ordinary Search using the saved Chrome profile.',
                limits='Original request retained separately from the frozen website research query; no model browser executor, extension or Codex required. Other websites need their own supported route.',
                recent_requests=recent)


def validate_action(action):
    if (not isinstance(action,dict) or set(action)!={'kind','site','query'}
            or action['kind']!='browser_research' or action['site']!='perplexity'
            or not isinstance(action['query'],str) or not action['query'].strip()
            or len(action['query'])>12000):
        raise ValueError('Browser research requires a supported site and a nonempty research query of at most 12000 characters.')


def dispatch(state, job, action):
    from .relay_channels import request_channel
    validate_action(action)
    # This action never falls back to the legacy extension or another profile.
    if not managed_enabled(state):
        raise ValueError('Enable Browser use in Task Relay Settings. No Search was queued.')
    receipt = enqueue(state, 'orchestrator:'+str(job['id']), job['prompt'],
                      request_channel(state, job['id']), exact_prompt=action['query'], queued_notice=False)
    preview=action['query'][:1200]+('\n[Query preview shortened; the complete query is saved.]' if len(action['query'])>1200 else '')
    return 'Browser research queued. Relay will return the website answer and conversation URL.\nResearch request: '+preview+'\nReceipt: '+receipt, receipt


def managed_enabled(state):
    from .managed_browser import preference
    data = Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent
    saved = preference(data)
    if saved is not None and not saved['enabled']:
        raise ValueError('Browser use is off. Enable it in Task Relay Settings. No Search was queued.')
    if saved and saved.get('manual_sign_in'):
        raise ValueError('Complete sign-in in Chrome, then choose Done signing in in Task Relay Settings. No Search was queued.')
    return bool(saved and saved['enabled'])


def request_text(text):
    """Literal commands bypass interpretation; natural language uses the orchestrator."""
    match = re.match(r'^/perplexity(?:@[A-Za-z0-9_]+)?(?:\s+|$)', text, re.I)
    if match:
        return text[match.end():]
    return None


def connection(db, session):
    with transaction(db):
        db.execute('INSERT OR REPLACE INTO browser_research_connection VALUES (1,?,?)',
                   (session, time.time()))


def connected(db):
    row = db.execute('SELECT updated FROM browser_research_connection WHERE id=1').fetchone()
    return bool(row and 0 <= time.time() - row[0] < 20)


def notice(state, receipt, suffix, text):
    row = state.db.execute('SELECT channel FROM browser_research_requests WHERE id=?', (receipt,)).fetchone()
    if row and row[0] != 'local':
        event = 'perplexity-research:' + receipt + ':' + suffix
        state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,NULL,?)', (event, text))
        state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)', (event, row[0]))


def enqueue(state, source, text, channel='telegram', target=None, *, exact_prompt=None, queued_notice=True):
    if channel not in ('telegram', 'messages', 'local'):
        raise ValueError('Unsupported research reply channel.')
    if not isinstance(source, str) or not source or len(source) > 240:
        raise ValueError('Research needs a durable input identity.')
    prompt = request_text(text) if exact_prompt is None else exact_prompt
    if prompt is None:
        raise ValueError('Use /perplexity QUESTION for a literal query; send natural-language requests to the orchestrator.')
    follow = re.match(r'^(https://www\.perplexity\.ai/search/\S+)\s+([\s\S]+)$', prompt)
    if follow and exact_prompt is None:
        selected = conversation_url(follow[1])
        if target and target != selected:
            raise ValueError('Two different conversation URLs were supplied.')
        target, prompt = selected, follow[2]
    initialize(state.db)
    journal = Journal(state.db)
    receipt = 'pplx-' + hashlib.sha256((channel + ':' + source).encode()).hexdigest()[:32]
    with transaction(state.db):
        old = state.db.execute('SELECT * FROM browser_research_requests WHERE id=?', (receipt,)).fetchone()
        if old:
            if old['request'] != text or old['source'] != source or old['channel'] != channel:
                raise ValueError('This research input identity was already used for different text.')
            job = journal.get(receipt)
            if job['target'] != target or job['prompt'] != prompt:
                raise ValueError('The research conversation identity changed.')
            return receipt
        managed = managed_enabled(state)
        if not managed and not connected(state.db):
            raise ValueError('Connect the Task Relay Perplexity extension in your signed-in browser first. No Search was queued.')
        if state.db.execute("SELECT count(*) FROM browser_research_requests WHERE state IN ('queued','running','inspect')").fetchone()[0] >= 5:
            raise ValueError('Five research requests are pending. Wait for one to finish.')
        journal.prepare(receipt, prompt, target)
        state.db.execute('INSERT INTO browser_research_requests VALUES (?,?,?,?,?,?)',
                         (receipt, source, text, channel, 'queued', time.time()))
        if managed:
            state.db.execute('INSERT INTO browser_research_transport VALUES (?,?)', (receipt, 'chrome'))
            state.db.execute('INSERT INTO provider_jobs VALUES (?,?,?,?,?)',
                             (receipt, 'perplexity', 'browser_research', 'queued', time.time()))
        if queued_notice:notice(state, receipt, 'queued', 'Perplexity Search queued. I will return its answer and saved conversation link.\nReceipt: ' + receipt)
    return receipt


def finalize(state, job):
    """Completion and its channel-owned outbox entry commit together."""
    with transaction(state.db):
        state.db.execute('UPDATE browser_research_requests SET state=? WHERE id=?', (job['status'], job['id']))
        if job['status'] == 'completed':
            body = job['result'] or ''
            if len(body) > 24000:
                body = body[:24000] + '\n\n[Transcript shortened for chat; the complete result is in the saved conversation.]'
            text = 'Perplexity Search\n' + job['url'] + '\n\n' + body
        else:
            text = 'Perplexity Search ' + job['status'] + ': ' + (job['error'] or 'No completed answer was saved.')
            text += '\nReceipt: ' + job['id'] + '\nNo automatic resubmission.'
            if job['url']:
                text += '\n' + job['url']
        notice(state, job['id'], job['status'], text)


def recover(state):
    """Called only after acquiring the exclusive browser worker lock."""
    journal = Journal(state.db)
    for row in state.db.execute("SELECT id FROM browser_research_requests WHERE state='running' AND id NOT IN (SELECT id FROM browser_research_transport)").fetchall():
        job = journal.get(row['id'])
        if job['status'] not in ('completed', 'blocked', 'uncertain'):
            journal.update(job['id'], 'uncertain' if job['status'] == 'submitting' else 'blocked',
                           error='Browser connection ended during this job. Inspect before retrying.')
        finalize(state, journal.get(row['id']))


def requeue(state, receipt, *, inspect=False, url=None):
    journal = Journal(state.db)
    with transaction(state.db):
        managed = state.db.execute('SELECT 1 FROM browser_research_transport WHERE id=?', (receipt,)).fetchone()
        if managed and not managed_enabled(state):
            raise ValueError('Enable Browser use in Task Relay Settings first.')
        if not managed and not connected(state.db):
            raise ValueError('Connect the browser extension first.')
        job = journal.get(receipt)
        row = state.db.execute('SELECT state FROM browser_research_requests WHERE id=?', (receipt,)).fetchone()
        if not row or row[0] in ('queued', 'running', 'inspect'):
            raise ValueError('This research request cannot be queued again now.')
        if inspect:
            if job['status'] not in ('uncertain', 'submitting'):
                raise ValueError('Only uncertain submissions can be inspected.')
            target = job['url'] or job['target']
            if url:
                conversation_url(url)
                if target and target != url:
                    raise ValueError('The saved conversation URL cannot be replaced.')
                journal.update(receipt, 'uncertain', url=url)
            elif not target:
                raise ValueError('Supply the saved conversation URL; no new Search will be submitted.')
        elif job['status'] != 'blocked' or url:
            raise ValueError('Only a blocked request before submission can be retried.')
        state.db.execute('UPDATE browser_research_requests SET state=? WHERE id=?',
                         ('inspect' if inspect else 'queued', receipt))
        if managed:
            state.db.execute("UPDATE provider_jobs SET status='queued' WHERE id=?", (receipt,))


def run_next(state, driver):
    with transaction(state.db):
        row = state.db.execute("SELECT id,state FROM browser_research_requests WHERE state IN ('queued','inspect') AND id NOT IN (SELECT id FROM browser_research_transport) ORDER BY created LIMIT 1").fetchone()
        if not row:
            return None
        state.db.execute("UPDATE browser_research_requests SET state='running' WHERE id=?", (row['id'],))
    result = execute(Journal(state.db), row['id'], driver, reconcile=row['state'] == 'inspect')
    finalize(state, result)
    return result


def telegram(bridge, message, update_id):
    text = message.get('text', '')
    if request_text(text) is None:
        return False
    initialize(bridge.state.db)
    try:
        with transaction(bridge.state.db):
            enqueue(bridge.state, 'telegram:' + str(update_id), text)
            bridge.state.db.execute('INSERT INTO incoming VALUES (?,?,NULL)', (update_id, 'handled'))
    except ValueError as exc:
        bridge.send(str(exc))
    return True
