"""Exact pending permission cards and one-shot decisions in the local Tasks tab."""
import hashlib
import json
from pathlib import Path
import time

from . import codex_approvals, codex_requests
from .relay_paths import PATHS

MAX_DESKTOP_REVIEW = 300_000


def inbox(paths=PATHS):
    from contextlib import closing
    from .desktop_tasks import _database, _table
    if not paths.state.is_file():
        return {'items': []}
    with closing(_database(paths)) as db:
        counts = {}
        if _table(db, 'codex_approvals'):
            for row in db.execute("SELECT thread_id,count(*) n FROM codex_approvals WHERE status='pending' GROUP BY thread_id"):
                counts[row['thread_id']] = row['n']
        if _table(db, 'tool_requests') and _table(db, 'backend_jobs'):
            for row in db.execute("""SELECT r.thread_id,count(*) n FROM tool_requests r
                JOIN backend_jobs j ON j.id=r.job_id WHERE r.status='pending' AND r.expires_at>?
                AND j.status IN ('running','waiting') AND j.cancel=0 GROUP BY r.thread_id""", (time.time(),)):
                counts[row['thread_id']] = counts.get(row['thread_id'], 0) + row['n']
        items = []
        for task_id, count in counts.items():
            task = db.execute('SELECT title FROM watched WHERE id=?', (task_id,)).fetchone()
            if task:
                items.append(dict(task_id=task_id, title=task['title'] or task_id, count=count))
        return {'items': items}


def _tool_fingerprint(row):
    fields = [row[key] for key in ('id', 'job_id', 'thread_id', 'tool', 'input_json', 'expires_at')]
    return hashlib.sha256(json.dumps(fields, separators=(',', ':')).encode()).hexdigest()


def pending(db, task_id):
    cards = []
    review_budget = MAX_DESKTOP_REVIEW
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='codex_approvals'").fetchone():
        for row in db.execute("SELECT * FROM codex_approvals WHERE thread_id=? AND status='pending' ORDER BY rowid",
                              (task_id,)):
            request = json.loads(row['request_json'])
            event_id = 'codex-approval:' + row['id']
            event = db.execute('SELECT text FROM outbox WHERE id=?', (event_id,)).fetchone()
            review = event['text'] if event else ''
            complete = bool(review)
            report = db.execute('SELECT * FROM codex_approval_reports WHERE token=?', (row['id'],)).fetchone()
            if report:
                try:
                    path = Path(report['path'])
                    raw = path.read_bytes() if not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_DESKTOP_REVIEW else b''
                    if not raw or hashlib.sha256(raw).hexdigest() != report['sha256']:
                        raise ValueError('Review document unavailable')
                    review = raw.decode('utf-8')
                except (OSError, UnicodeError, ValueError):
                    complete = False
            size = len(review.encode('utf-8'))
            if size > review_budget:
                complete = False
            if complete:
                review_budget -= size
            if not complete:
                review = ((event['text'][:1200] if event else 'Complete approval details are unavailable here.') +
                          '\nOpen this task in Codex to review the complete request. Allow is disabled here.')
            method = request['method']
            cards.append({'token': row['id'], 'kind': 'codex', 'fingerprint': row['fingerprint'],
                          'title': {codex_approvals.COMMAND: 'Run command', codex_approvals.FILE: 'File changes',
                                    codex_approvals.PERMISSIONS: 'Permissions', codex_requests.MCP: 'Connector request',
                                    codex_requests.INPUT: 'Question'}.get(method, 'Codex request'),
                          'review': review, 'can_allow': complete and bool(row['can_allow']),
                          'can_deny': method in codex_approvals.METHODS,
                          'can_answer': complete and method == codex_requests.INPUT and codex_requests.supported(request)})
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='tool_requests'").fetchone():
        for row in db.execute('''SELECT r.* FROM tool_requests r JOIN backend_jobs j ON j.id=r.job_id
                                 WHERE r.thread_id=? AND r.status='pending' AND r.expires_at>?
                                   AND j.status IN ('running','waiting') AND j.cancel=0
                                 ORDER BY r.expires_at''', (task_id, time.time())):
            cards.append({'token': row['id'], 'kind': 'tool', 'fingerprint': _tool_fingerprint(row),
                          'title': 'Claude permission: ' + row['tool'],
                          'review': row['tool'] + '\n\n' + row['input_json'] + '\n\nExpires in 15 minutes. Approval applies once.',
                          'can_allow': True, 'can_deny': True, 'can_answer': False})
    return cards


def decide(task_id, token, fingerprint, allow, answer=None, paths=PATHS, desktop_factory=None):
    from .bridge import Desktop, State
    if not isinstance(task_id, str) or not task_id or len(task_id) > 180:
        raise ValueError('Choose an exact task.')
    if not isinstance(token, str) or len(token) > 80 or not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError('Refresh the approval card before deciding.')
    if type(allow) is not bool or (answer is not None and (not isinstance(answer, str) or len(answer) > 4000)):
        raise ValueError('Choose one valid decision or answer.')
    if not paths.state.is_file():
        raise ValueError('The saved task history is unavailable. Refresh the task.')
    state = State(paths.state)
    try:
        card = next((item for item in pending(state.db, task_id) if item['token'] == token), None)
        if not card or card['fingerprint'] != fingerprint:
            raise ValueError('The approval changed or is no longer pending. Refresh the task.')
        if allow and not card['can_allow']:
            raise ValueError('The complete request is not reviewable here. Open it in Codex.')
        if answer is not None and not card['can_answer']:
            raise ValueError('This request does not accept a desktop answer.')
        if card['kind'] == 'codex':
            _, message = codex_approvals.decide(state, token, allow, desktop_factory or Desktop,
                                                answer=answer, desktop_review_fingerprint=fingerprint)
            return {'message': message, 'status': 'submitted'}
        if answer is not None:
            raise ValueError('This permission needs Allow or Deny.')
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            row = state.db.execute('''SELECT r.* FROM tool_requests r JOIN backend_jobs j ON j.id=r.job_id
                WHERE r.id=? AND r.thread_id=? AND r.status='pending' AND r.expires_at>?
                  AND j.status IN ('running','waiting') AND j.cancel=0''',
                (token, task_id, time.time())).fetchone()
            if not row or _tool_fingerprint(row) != fingerprint:
                raise ValueError('The permission changed or expired. Refresh the task.')
            state.db.execute('UPDATE tool_requests SET status=? WHERE id=?',
                             ('allowed' if allow else 'denied', token))
        return {'message': 'Approved once.' if allow else 'Denied.', 'status': 'submitted'}
    finally:
        state.db.close()
