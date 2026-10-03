"""O15.2 finite Safari sessions in Relay's authoritative shared database.

No scheduler/provider dispatch. CLI approval freezes the complete manual plan.
Each external call follows its own committed intent. A lost result is never retried.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid

from orchestrator.storage import transaction
from . import computer_contract as contract
from .computer_use import write_new

TABLES = ('relay_computer_assignments', 'relay_computer_actions', 'relay_computer_decisions')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_computer_assignments(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, request_key TEXT NOT NULL,
        exact_request TEXT NOT NULL, spec TEXT NOT NULL, helper TEXT NOT NULL,
        output_root TEXT NOT NULL, state TEXT NOT NULL, cursor INTEGER NOT NULL,
        current_url TEXT NOT NULL, deadline REAL NOT NULL, created REAL NOT NULL,
        UNIQUE(job,request_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_computer_actions(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, assignment TEXT NOT NULL,
        ordinal INTEGER NOT NULL, plan_index INTEGER, request TEXT NOT NULL,
        state TEXT NOT NULL, receipt TEXT, error TEXT, resolved INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL, UNIQUE(assignment,ordinal))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_computer_decisions(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, assignment TEXT NOT NULL,
        kind TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
        data TEXT NOT NULL, created REAL NOT NULL)''')


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def get(db, ident):
    row = db.execute('SELECT * FROM relay_computer_assignments WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Unknown computer assignment.')
    return dict(row)


def actions(db, ident):
    return [dict(r) for r in db.execute('SELECT * FROM relay_computer_actions WHERE assignment=? ORDER BY ordinal', (ident,))]


def decision(db, row, kind, actor, note, data):
    if not all(isinstance(s, str) and s.strip() for s in (actor, note)) or len(note) > 16000:
        raise ValueError('Record an explicit actor and bounded decision note.')
    db.execute('INSERT INTO relay_computer_decisions VALUES (?,?,?,?,?,?,?,?)',
        (uuid.uuid4().hex, row['job'], row['id'], kind, actor, note, encoded(data), time.time()))


def approve(db, *, job, request_key, exact_request, spec, helper, output_root, actor):
    spec = contract.session_spec(spec)
    contract.request(spec['target'], spec['url'], exact_request, spec['capture'], spec['local_fixture'],
                     launch=contract.managed_target(spec['target']))
    if len(encoded(spec).encode()) + len(exact_request.encode()) > 20000:
        raise ValueError('Frozen session exceeds its transport bound.')
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
        raise ValueError('A bounded request key is required.')
    root = Path(output_root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Session output must not traverse symlinks.')
    with transaction(db):
        owner = db.execute('SELECT id FROM relay_pipelines WHERE id=?', (job,)).fetchone()
        if owner is None and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_standalone_jobs'").fetchone():
            owner = db.execute('SELECT id FROM relay_standalone_jobs WHERE id=?', (job,)).fetchone()
        if owner is None:
            raise ValueError('Select an existing saved Relay pipeline or standalone job.')
        prior = db.execute('SELECT * FROM relay_computer_assignments WHERE job=? AND request_key=?', (job, request_key)).fetchone()
        frozen = (exact_request, encoded(spec), encoded(helper), str(root))
        if prior:
            if tuple(prior[k] for k in ('exact_request', 'spec', 'helper', 'output_root')) != frozen:
                raise ValueError('Request key already freezes a different assignment.')
            return prior['id']
        # An unresolved old action cannot be bypassed with a fresh request key.
        if db.execute('''SELECT 1 FROM relay_computer_assignments WHERE job=?
            AND (state NOT IN ('completed','cancelled') OR id IN
              (SELECT assignment FROM relay_computer_actions WHERE state IN ('claimed','uncertain') AND resolved=0))''', (job,)).fetchone():
            raise ValueError('Resolve or cancel the existing computer assignment first.')
        ident, now = uuid.uuid4().hex, time.time()
        db.execute('INSERT INTO relay_computer_assignments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (ident, job, request_key, *frozen, 'approved', 0, spec['url'], 0, now))
        decision(db, get(db, ident), 'approve', actor, exact_request, {'spec_sha256': contract.digest(spec)})
        return ident


def control(db, ident, kind, *, actor, note):
    if kind not in ('pause', 'cancel'):
        raise ValueError('Unsupported session control.')
    with transaction(db):
        row = get(db, ident)
        if row['state'] in ('completed', 'cancelled'):
            raise ValueError('Assignment is already terminal.')
        decision(db, row, kind, actor, note, {'prior_state': row['state']})
        db.execute('UPDATE relay_computer_assignments SET state=? WHERE id=?',
                   ('paused' if kind == 'pause' else 'cancelled', ident))


def resume(db, ident, *, current_url, actor, note, abandon=False):
    """Caller holds the native host lease: no live session can be reconciled.

    Explicitly skip every claimed/uncertain action, retaining its original outcome.
    A new binding observation never proves the earlier action did not happen.
    """
    with transaction(db):
        row = get(db, ident)
        if row['state'] not in ('running', 'paused', 'blocked', 'cancelled'):
            raise ValueError('Assignment does not require recovery.')
        spec = json.loads(row['spec'])
        if contract.managed_target(spec['target']) and not abandon:
            raise ValueError('Reconcile and stop this managed window attempt; a new approved attempt creates a new window.')
        if current_url not in spec['allowed_urls']:
            raise ValueError('Recovery URL must remain inside the frozen exact URL list.')
        if not abandon and row['deadline'] and time.time() >= row['deadline']:
            raise ValueError('Original time budget expired; only stop/reconcile is available.')
        unresolved = [a['id'] for a in actions(db, ident) if a['state'] in ('claimed', 'uncertain') and not a['resolved']]
        decision(db, row, 'reconcile_stop' if abandon else 'resume_without_replay', actor, note,
                 {'unresolved_actions': unresolved, 'current_url': current_url, 'prior_state': row['state'],
                  'outcome': 'Earlier outcomes remain unknown; consumed plan positions are never repeated.'})
        db.execute("UPDATE relay_computer_actions SET resolved=1 WHERE assignment=? AND state IN ('claimed','uncertain')", (ident,))
        db.execute('UPDATE relay_computer_assignments SET state=?,current_url=? WHERE id=?',
                   ('cancelled' if abandon else 'approved', current_url, ident))


def _claim(db, ident, request, index):
    with transaction(db):
        row = get(db, ident)
        if row['state'] != 'running':
            raise ValueError('Session paused or cancelled before dispatch.')
        if time.time() >= row['deadline']:
            raise ValueError('Session time budget expired.')
        history = actions(db, ident)
        if any(a['state'] in ('claimed', 'uncertain') and not a['resolved'] for a in history):
            raise ValueError('Uncertain action needs explicit reconciliation.')
        if len(history) >= 20:
            raise ValueError('Session action budget exhausted, including recovery observations.')
        if json.loads(row['spec'])['capture'] and len(history) >= 5:
            raise ValueError('Session capture budget exhausted, including recovery observations.')
        if index is not None and index != row['cursor']:
            raise ValueError('Stale plan cursor.')
        action_id = uuid.uuid4().hex
        db.execute('INSERT INTO relay_computer_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (action_id, row['job'], ident, len(history), index, encoded(request), 'claimed', None, None, 0, time.time()))
        if index is not None:
            db.execute('UPDATE relay_computer_assignments SET cursor=cursor+1 WHERE id=?', (ident,))
        return action_id


def _verify_receipt(receipt):
    info = json.loads(receipt)
    folder = Path(info['folder'])
    for name, item in info['files'].items():
        p = folder / name
        if any(x.is_symlink() for x in (p, *p.parents)) or not p.is_file():
            raise ValueError('Saved evidence is unavailable; no recapture is permitted.')
        raw = p.read_bytes()
        if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Saved evidence changed; no recapture is permitted.')
    return info


def _save(row, action_id, request, response, *, refresh_url=None):
    # Native session replies embed the same bounded observation as O15.1.
    expected = request['observation_request']
    if request['operation'] == 'launch':
        scripting = expected['target'] == contract.SCRIPTING_WINDOW
        if (response.get('window_created') is not True or
                (scripting and (response.get('transport') != 'safari-scripting' or response.get('foreground_acquired') is not False)) or
                (not scripting and response.get('foreground_acquired') is not True)):
            raise ValueError('Missing new-window ownership receipt.')
        expected = {**expected, 'target': contract.target(response.get('observation', {}).get('target'))}
    if refresh_url is not None:expected={**expected,'expected_url':refresh_url}
    data, png = contract.validate_response(response.get('observation'), expected)
    token = response.get('token')
    if (response.get('ok') is not True or not isinstance(token, str) or
            not 1 <= len(token) <= 100 or token == request.get('token')):
        raise ValueError('Native session did not return a fresh observation token.')
    folder = Path(row['output_root']) / row['id'] / action_id
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise ValueError('Evidence path changed to a symbolic link.')
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_new(folder / 'request.json', request)
    text = data.pop('text').encode()
    files = {'page.txt': text}
    if png is not None:
        files['viewport.png'] = png
    for name, raw in files.items():
        write_new(folder / name, raw)
    evidence = {'schema': 'relay.computer-session-evidence.v1', **data, 'assignment': row['id'],
                'action': action_id, 'request_sha256': contract.digest(request), 'token': token,
                'helper': json.loads(row['helper']), 'review_status': 'unreviewed',
                'refreshed':response.get('refreshed',False),'action_executed':response.get('action_executed'),
                'transport':response.get('transport','accessibility'),
                'scroll_available':response.get('scroll_available',True),
                'window_created':response.get('window_created',False),'foreground_acquired':response.get('foreground_acquired',False),
                'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items()}}
    write_new(folder / 'evidence.json', evidence)
    names = ['request.json', 'evidence.json', *files]
    return {'folder': str(folder), 'token': token, 'url': data['url'], 'target': data['target'],
            'files': {name: {'bytes': (folder/name).stat().st_size,
                            'sha256': hashlib.sha256((folder/name).read_bytes()).hexdigest()} for name in names}}


def run(db, ident, helper):
    """Caller holds one host-wide native lease. helper.session is injected in tests."""
    if db.in_transaction:
        raise ValueError('Native dispatch requires committed authority, not an outer transaction.')
    row = get(db, ident)
    history = actions(db, ident)
    for action in history:
        if action['state'] == 'completed':
            _verify_receipt(action['receipt'])
    if row['state'] == 'completed':
        return inspect(db, ident)  # saved duplicate, without opening a helper
    if encoded(helper.identity) != row['helper']:
        raise ValueError('Helper differs from the frozen approved build.')
    spec = contract.session_spec(json.loads(row['spec']))
    if contract.managed_target(spec['target']):
        raise ValueError('Managed Safari windows run only through the approved worker, not the manual session runner.')
    with transaction(db):
        row = get(db, ident)
        if row['state'] != 'approved':
            raise ValueError('Explicit resume/reconciliation is required before running.')
        if any(a['state'] in ('claimed', 'uncertain') and not a['resolved'] for a in actions(db, ident)):
            raise ValueError('Resolve uncertain work first.')
        deadline = row['deadline'] or time.time() + spec['max_seconds']
        if deadline <= time.time():
            raise ValueError('Session time budget expired.')
        db.execute("UPDATE relay_computer_assignments SET state='running',deadline=? WHERE id=?", (deadline, ident))
    pending = None
    try:
        with helper.session() as native:
            token, current_url = None, row['current_url']
            # Binding on every new process is itself a journaled, budgeted observation.
            steps = [(None, {'operation': 'bind'})] + list(enumerate(spec['actions']))[row['cursor']:]
            for index, action in steps:
                row = get(db, ident)
                if row['state'] != 'running':
                    break
                next_url = action.get('url', current_url)
                frozen = contract.request(spec['target'], next_url, row['exact_request'], spec['capture'], spec['local_fixture'])
                request = {'protocol': contract.PROTOCOL, **action, 'token': token, 'observation_request': frozen}
                if index is None:
                    request['allowed_urls'] = spec['allowed_urls']
                    request['max_seconds'] = max(1, min(300, int(row['deadline'] - time.time())))
                pending = _claim(db, ident, request, index)  # commits BEFORE native effects
                response = native.call(request)
                receipt = _save(row, pending, request, response)
                with transaction(db):
                    # Evidence totals include this result before accepting completion.
                    totals = {'page.txt': receipt['files']['page.txt']['bytes'],
                              'viewport.png': receipt['files'].get('viewport.png', {}).get('bytes', 0)}
                    for prior in actions(db, ident):
                        if prior['receipt']:
                            for name in totals:
                                totals[name] += json.loads(prior['receipt'])['files'].get(name, {}).get('bytes', 0)
                    if totals['page.txt'] > 200000 or totals['viewport.png'] > 10000000:
                        raise ValueError('Session evidence budget exceeded; no further dispatch.')
                    db.execute("UPDATE relay_computer_actions SET state='completed',receipt=? WHERE id=? AND state='claimed'", (encoded(receipt), pending))
                    db.execute('UPDATE relay_computer_assignments SET current_url=? WHERE id=?', (receipt['url'], ident))
                pending = None
                token, current_url = receipt['token'], receipt['url']
            with transaction(db):
                latest = get(db, ident)
                if latest['state'] == 'running' and latest['cursor'] == len(spec['actions']):
                    db.execute("UPDATE relay_computer_assignments SET state='completed' WHERE id=?", (ident,))
    except BaseException:
        with transaction(db):
            if pending:
                db.execute("UPDATE relay_computer_actions SET state='uncertain',error=? WHERE id=? AND state='claimed'",
                           ('Dispatch or evidence persistence did not complete; explicit reconciliation required.', pending))
            db.execute("UPDATE relay_computer_assignments SET state='blocked' WHERE id=? AND state='running'", (ident,))
        raise
    return inspect(db, ident)


def inspect(db, ident):
    row = get(db, ident)
    return {'assignment': row, 'actions': actions(db, ident),
            'decisions': [dict(r) for r in db.execute('SELECT * FROM relay_computer_decisions WHERE assignment=? ORDER BY created,id', (ident,))]}
