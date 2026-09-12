"""Explicit, request-scoped Telegram decisions for the local desktop owner.

Desktop IPC is internal and version checked in bridge.Desktop. The relay never
edits Codex state or policy, opens tasks while polling, or retries a decision.
"""
import hashlib
import json
import secrets
from task_relay import codex_requests

COMMAND = 'item/commandExecution/requestApproval'
FILE = 'item/fileChange/requestApproval'
PERMISSIONS = 'item/permissions/requestApproval'
METHODS = {
    COMMAND: 'thread-follower-command-approval-decision',
    FILE: 'thread-follower-file-approval-decision',
    PERMISSIONS: 'thread-follower-permissions-request-approval-response',
    codex_requests.MCP: 'thread-follower-submit-mcp-server-elicitation-response',
}
NOTIFY_ONLY = {codex_requests.INPUT}
MAX_DETAILS = 10000


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS codex_approvals (
        id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, owner TEXT NOT NULL,
        fingerprint TEXT UNIQUE NOT NULL, request_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', can_allow INTEGER NOT NULL,
        decision TEXT)''')


def serialized(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def details(request, snapshot):
    """Only the pending request and its matching file-change item leave the Mac."""
    result = {'request': request}
    if request['method'] == FILE:
        p = request['params']
        turns = list(snapshot.get('turns', []))
        # Current desktop keeps loaded and live turns in normalized history.
        history = snapshot.get('turnHistory', {}).get('history', {})
        turns.extend(history.get('entitiesByKey', {}).values())
        for turn in turns:
            if turn.get('turnId', turn.get('id')) == p.get('turnId'):
                for item in turn.get('items', []):
                    if item.get('id') == p.get('itemId') and item.get('type') == 'fileChange':
                        result['fileChange'] = item
    return result


def fingerprint(thread_id, owner, request, snapshot):
    # Version the reviewed presentation so pending legacy desktop-only cards
    # are replaced once, with fresh tokens and complete actionable details.
    return hashlib.sha256(serialized([2, thread_id, owner, details(request, snapshot)]).encode()).hexdigest()


def can_allow(request, detail):
    p, method = request['params'], request['method']
    if method == codex_requests.MCP:
        return codex_requests.supported(request)
    if len(json.dumps(detail, indent=2, ensure_ascii=True, sort_keys=True)) > MAX_DETAILS:
        return False
    if method == COMMAND:
        choices = p.get('availableDecisions')
        return bool(p.get('command') or p.get('networkApprovalContext')) and (
            choices is None or 'accept' in choices)
    if method == FILE:
        return bool(detail.get('fileChange', {}).get('changes'))
    if method == PERMISSIONS:
        return isinstance(p.get('permissions'), dict) and bool(p['permissions'])
    return False


def queue_card(state, token, thread_id, title, request, detail, allow):
    # Freeze literal parts so Markdown/HTML cannot change the reviewed operation.
    # Connector cards omit verified duplicate display fields, not action details.
    from task_relay.bridge import split_text
    from task_relay import approval_text
    from task_relay.telegram_text import split_rendered
    readable = codex_requests.render(title, request) if codex_requests.supported(request) else None
    too_large = len(json.dumps(detail, indent=2, ensure_ascii=True, sort_keys=True)) > MAX_DETAILS
    text, entities = readable or approval_text.render(title, request, detail, allow, too_large)
    event_id = 'codex-approval:' + token
    state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                     (event_id, thread_id, text))
    for i, (chunk, selected) in enumerate(split_rendered(text, entities, split_text)):
        state.db.execute('INSERT INTO outbox_parts(event_id,part,text,entities) VALUES (?,?,?,?)',
                         (event_id, i, chunk, json.dumps(selected)))


def sync(state, thread_id, owner, snapshot, title=''):
    current = set()
    with state.db:
        for request in snapshot['requests']:
            if not isinstance(request, dict) or request.get('method') not in (*METHODS, *NOTIFY_ONLY):
                continue
            p = request.get('params', {})
            if (p.get('threadId') != thread_id or (not p.get('turnId') and request['method'] != codex_requests.MCP) or
                    type(request.get('id')) not in (str, int)):
                continue
            digest = fingerprint(thread_id, owner, request, snapshot)
            current.add(digest)
            if state.db.execute('SELECT 1 FROM codex_approvals WHERE fingerprint=?', (digest,)).fetchone():
                continue
            detail = details(request, snapshot)
            allowed = can_allow(request, detail)
            token = 'cx-' + secrets.token_hex(8)
            state.db.execute('INSERT INTO codex_approvals(id,thread_id,owner,fingerprint,request_json,can_allow) '
                             'VALUES (?,?,?,?,?,?)',
                             (token, thread_id, owner, digest, serialized(request), int(allowed)))
            queue_card(state, token, thread_id, title, request, detail, allowed)
        for row in state.db.execute("SELECT id,fingerprint FROM codex_approvals WHERE thread_id=? AND status='pending'",
                                    (thread_id,)).fetchall():
            if row['fingerprint'] not in current:
                state.db.execute("UPDATE codex_approvals SET status='resolved' WHERE id=?", (row['id'],))
                # Suppress queued obsolete cards. Already delivered cards remain
                # bound to their spent token and cannot approve a later request.
                state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', ('codex-approval:' + row['id'],))


class Worker:
    def __init__(self, state, desktop_factory):
        self.state, self.desktop_factory = state, desktop_factory
        self.cursor = 0

    def tick(self):
        if self.state.get('chat_id') is None:
            return
        rows = self.state.db.execute("SELECT id,title FROM watched WHERE status='running' OR id IN "
                                     "(SELECT thread_id FROM codex_approvals WHERE status='pending') ORDER BY id").fetchall()
        if not rows:
            return
        row = rows[self.cursor % len(rows)]
        self.cursor += 1
        with self.desktop_factory() as desktop:
            owner = desktop.owner(row['id'])
            snapshot = desktop.approval_snapshot(row['id'], owner)
        sync(self.state, row['id'], owner, snapshot, row['title'] or '')


def decide(state, token, allow, desktop_factory, *, answer=None):
    row = state.db.execute('SELECT * FROM codex_approvals WHERE id=?', (token,)).fetchone()
    if row and row['status'] in ('submitting', 'uncertain'):
        raise ValueError('Your decision was recorded, but the relay did not save Codex’s confirmation. '
                         'Codex may already have acted on it. This can happen when an approved command restarts the relay. '
                         'This decision will not be sent again.')
    if row and row['status'] == 'submitted':
        raise ValueError('This request was already answered through Telegram. The decision will not be sent again.')
    if not row or row['status'] != 'pending':
        raise ValueError('This Codex request is no longer pending. Check the desktop task.')
    request = json.loads(row['request_json'])
    answering = answer is not None and request['method'] == codex_requests.INPUT
    answer_payload = codex_requests.parse_answers(request, answer) if answering else None
    if (not answering and request['method'] not in METHODS) or (allow and not row['can_allow']):
        raise ValueError('This request requires desktop review.')
    if (allow or answering) and not state.db.execute('SELECT 1 FROM outbox WHERE id=? AND sent=1',
                                     ('codex-approval:' + token,)).fetchone():
        raise ValueError('Wait until all approval details have been delivered before approving.')
    with desktop_factory() as desktop:
        owner = desktop.owner(row['thread_id'])
        snapshot = desktop.approval_snapshot(row['thread_id'], owner)
        match = next((r for r in snapshot['requests'] if r == request), None)
        if (owner != row['owner'] or match is None or
                fingerprint(row['thread_id'], owner, match, snapshot) != row['fingerprint']):
            with state.db:
                state.db.execute("UPDATE codex_approvals SET status='resolved' WHERE id=? AND status='pending'", (token,))
            raise ValueError('This approval changed or was already answered on desktop. Use the current request.')
        method = codex_requests.INPUT_METHOD if answering else METHODS[request['method']]
        params = {'conversationId': row['thread_id'], 'requestId': request['id']}
        if answering:
            params['response'] = answer_payload
        elif request['method'] == codex_requests.MCP:
            params['response'] = {'action': 'accept' if allow else 'decline', 'content': {} if allow else None}
        elif request['method'] == PERMISSIONS:
            params['response'] = {'permissions': request['params']['permissions'] if allow else {}, 'scope': 'turn'}
        else:
            choices = request['params'].get('availableDecisions')
            decision = 'accept' if allow else 'decline'
            if choices is not None and decision not in choices:
                raise ValueError('That decision is unavailable. Review this request on desktop.')
            params['decision'] = decision
        # Claim durably before sending: a crash/timeout can never replay a grant.
        with state.db:
            claimed = state.db.execute("UPDATE codex_approvals SET status='submitting',decision=? WHERE id=? AND status='pending'",
                                       (serialized(answer_payload) if answering else 'allow' if allow else 'deny', token)).rowcount
        if not claimed:
            raise ValueError('This request was already handled.')
        try:
            response = desktop.request(method, params, 1, target=owner)
            if response.get('method') != method or response.get('result') != {'ok': True}:
                raise ValueError('Unexpected desktop acknowledgement')
        except Exception:
            with state.db:
                state.db.execute("UPDATE codex_approvals SET status='uncertain' WHERE id=?", (token,))
            raise ValueError('Decision delivery is uncertain. Check Codex on desktop; the relay will not resend it.') from None
    with state.db:
        state.db.execute("UPDATE codex_approvals SET status='submitted' WHERE id=?", (token,))
    return row['thread_id'], 'Answer sent to Codex.' if answering else 'Approval sent to Codex.' if allow else 'Denial sent to Codex.'
