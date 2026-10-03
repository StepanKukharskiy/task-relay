"""Desktop inspection and stop controls for existing native sessions; no dispatch."""
from contextlib import contextmanager
import json
import sqlite3
import subprocess

from orchestrator.storage import transaction
from . import computer_sessions as sessions
from .computer_contract import digest, PROTOCOL
from .desktop_tasks import DesktopTaskError
from .relay_paths import PATHS


def setup(request_permissions=False):
    """Inspect native grants only; never read a page or create a session."""
    from .computer_target import runtime
    from .host_computer import Observer
    try:
        target = runtime(required=True)
        helper = Observer(target['helper'])
        operation = 'request-permissions' if request_permissions else 'status'
        value = helper.call({'protocol': PROTOCOL, 'operation': operation})
        if value.get('ok') is not True:
            raise ValueError('Native permission status is unavailable.')
        return {'available': True, 'helper': str(helper.app),
                'mode': target.get('mode', 'selected-window'),
                'permissions': {k: value.get(k) is True for k in
                                ('accessibility', 'screen_recording', 'session_unlocked')},
                'permission_prompted': value.get('permission_prompted') is True,
                'automation': 'checked-at-task-start'}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {'available': False, 'error': str(exc)[:1000]}


@contextmanager
def database(paths, writable=False):
    path = paths.state
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise DesktopTaskError('No available Relay session history at this data location.')
    db = sqlite3.connect(path.as_uri() + ('?mode=rw' if writable else '?mode=ro'),
                         uri=True, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def available(db):
    return all(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
               for name in sessions.TABLES)


def listing(offset=0, paths=PATHS):
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise DesktopTaskError('Choose a valid session page.')
    empty = {'items': [], 'total': 0, 'next_offset': None}
    if not paths.state.exists():
        return empty
    with database(paths) as db, transaction(db, write=False):
        if not available(db):
            return empty
        total = db.execute('SELECT count(*) FROM relay_computer_assignments').fetchone()[0]
        rows = db.execute('''SELECT id,job,state,substr(exact_request,1,180) AS request_excerpt,created
            FROM relay_computer_assignments ORDER BY created DESC,id DESC LIMIT 20 OFFSET ?''', (offset,)).fetchall()
        return {'items': [dict(r) for r in rows], 'total': total,
                'next_offset': offset + len(rows) if offset + len(rows) < total else None}


def _detail(db, ident):
    if not isinstance(ident, str) or not 1 <= len(ident) <= 100:
        raise DesktopTaskError('Choose an exact saved Safari session.')
    if not available(db):
        raise DesktopTaskError('No native sessions have been recorded here.')
    row = sessions.get(db, ident)
    actions = sessions.actions(db, ident)
    decisions = db.execute('''SELECT count(*),max(rowid) FROM relay_computer_decisions
        WHERE assignment=?''', (ident,)).fetchone()
    # The comparison includes completed/in-flight receipts, not only the visible state.
    fingerprint = digest({'assignment': row, 'actions': actions, 'decisions': tuple(decisions)})
    recent = [dict(r) for r in db.execute('''SELECT kind,actor,substr(note,1,512) AS note_excerpt,created
        FROM relay_computer_decisions WHERE assignment=? ORDER BY created DESC,rowid DESC LIMIT 20''', (ident,))]
    history = []
    for action in actions:
        request = json.loads(action['request'])
        receipt = json.loads(action['receipt']) if action['receipt'] else None
        history.append({'id': action['id'], 'ordinal': action['ordinal'], 'state': action['state'],
                        'operation': request['operation'], 'url': request.get('observation_request', {}).get('url'),
                        'resolved': bool(action['resolved']), 'error': action['error'],
                        'files': receipt['files'] if receipt else {}})
    return {'id': ident, 'job': row['job'], 'state': row['state'], 'exact_request': row['exact_request'],
            'spec': json.loads(row['spec']), 'helper': json.loads(row['helper']),
            'current_url': row['current_url'], 'deadline': row['deadline'],
            'actions': history, 'decision_count': decisions[0], 'recent_decisions': recent,
            'fingerprint': fingerprint, 'can_pause': row['state'] in ('approved', 'running'),
            'can_cancel': row['state'] not in ('completed', 'cancelled'),
            'unresolved': sum(a['state'] in ('claimed', 'uncertain') and not a['resolved'] for a in actions),
            'evidence_note': 'Saved receipt hashes only; files have not been reverified by this view. Evidence remains unreviewed.'}


def detail(ident, paths=PATHS):
    with database(paths) as db, transaction(db, write=False):
        return _detail(db, ident)


def control(ident, kind, fingerprint, note, paths=PATHS):
    if kind not in ('pause', 'cancel') or not isinstance(note, str) or not note.strip() or len(note) > 4000:
        raise DesktopTaskError('Choose Pause or Cancel and record a decision note.')
    with database(paths, writable=True) as db, transaction(db):
        current = _detail(db, ident)
        if not isinstance(fingerprint, str) or fingerprint != current['fingerprint']:
            raise DesktopTaskError('Session changed. Refresh and inspect the current receipt before deciding.')
        if not current['can_' + kind]:
            raise DesktopTaskError('This control is no longer available. Refresh the session.')
        sessions.control(db, ident, kind, actor='local desktop user', note=note)
        return _detail(db, ident)


def dispatch(action, value):
    if not isinstance(value, dict):
        raise DesktopTaskError('Expected a saved session query.')
    fields = {'computer-sessions': {'offset'}, 'computer-session-detail': {'id'},
              'computer-session-control': {'id', 'kind', 'fingerprint', 'note'},
              'computer-setup-status': set(), 'computer-request-permissions': set()}
    if action not in fields or set(value) - fields[action]:
        raise DesktopTaskError('Unsupported native session control.')
    try:
        if action in ('computer-setup-status', 'computer-request-permissions'):
            return setup(request_permissions=action == 'computer-request-permissions')
        if action == 'computer-sessions': return listing(value.get('offset', 0))
        if action == 'computer-session-detail': return detail(value.get('id'))
        return control(value.get('id'), value.get('kind'), value.get('fingerprint'), value.get('note'))
    except ValueError as exc:
        raise DesktopTaskError(str(exc)) from None
