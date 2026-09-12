"""Exact review receipts and text-only application to new isolated trial folders."""
import difflib
import json
import os
from pathlib import Path
import tempfile
import time
import gemini
from .store import digest, encoded, identifier


def atomic_text(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.observer-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def trial_target(details):
    target = Path(details['treatment'])
    root = Path(details['trial'])
    if root.resolve() != root or target.resolve() != target or not target.is_relative_to(root / 'treatment'):
        raise ValueError('Trial paths changed or contain symlinks')
    return target


def receipt(proposal):
    return digest(encoded(proposal['details']).encode())


def assert_current(store, proposal):
    details = proposal['details']
    source_ids = {store.get('events', r)['source_id'] for r in details['evidence']}
    source_ids.add(details['change']['source_id'])
    finding = store.get('findings', proposal['finding_id'])
    source_ids.update(store.get('analysis_runs', finding['run_id'])['details'].get('source_ids', []))
    for sid in source_ids:
        source = store.get('sources', sid)
        try:
            current = digest(Path(source['path']).read_bytes())
        except OSError:
            current = None
        if current != source['sha256']:
            with store.db:
                store.decision(proposal['id'], 'stale', {'source_id': sid, 'expected': source['sha256'], 'actual': current})
                store.db.execute("UPDATE proposals SET status='stale' WHERE id=?", (proposal['id'],))
            raise ValueError('Proposal is stale: a supporting source or target guide changed; analyze the revised inputs')


def card(store, pid):
    proposal = store.get('proposals', pid)
    d = proposal['details']
    change = d['change']
    original = store.get('sources', change['source_id'])['raw'].decode('utf-8')
    amended = original.replace(change['before'], change['after'], 1)
    diff = ''.join(difflib.unified_diff(original.splitlines(keepends=True), amended.splitlines(keepends=True),
                                      fromfile=d['target_path'], tofile='trial/' + Path(d['target_path']).name))
    lines = [f'# {pid}', '', f"Status: {proposal['status']}", f"Review hash: `{receipt(proposal)}`", '',
             f"Scope: {d['scope']['workflow']} / {d['scope']['mode']}", '',
             f"Observation: {d['observation']}", '', f"Hypothesis: {d['hypothesis']}", '',
             f"Existing guidance: {d['existing_guidance']}", '', f"Expected benefit (untested): {d['expected_benefit']}", '',
             f"Evaluation: {d['evaluation']}", '', f"Remaining question: {d['missing_evidence']}", '',
             f"Base SHA-256: `{d['target_hash']}`", f"Amended SHA-256: `{d['result_hash']}`", '',
             '## Exact amendment', '', '````diff', diff, '````', '', '## Supporting evidence', '']
    for ref in d['evidence']:
        event = store.get('events', ref)
        source = store.get('sources', event['source_id'])
        lines += [f"- [{event['details'].get('message_id', 'guide')} · {event['role']}](<{source['path']}:{event['line_start']}>) "
                  f"— `{ref}` (snapshot `{source['sha256']}`, lines {event['line_start']}–{event['line_end']})", '',
                  ]
        if event['role'] != 'guide':
            excerpt = event['text'][:900]
            lines += ['> ' + excerpt.replace('\n', '\n> '), '']
            if len(excerpt) < len(event['text']):
                lines += ['Excerpt shown; the complete message is retained under the evidence ID above.', '']
    lines += ['Evidence links open current files. Stored source bytes preserve the cited revision. '
              'Semantic support and applicability require review; acceptance authorizes only an isolated text trial.']
    return '\n'.join(lines)


def decide(store, pid, action, review_hash=None, note=''):
    proposal = store.get('proposals', pid)
    transitions = {'accept': ('proposed', 'accepted'), 'dismiss': ('proposed', 'dismissed'),
                   'keep': ('evaluated', 'kept'), 'revise': ('evaluated', 'revised')}
    if action not in transitions or proposal['status'] != transitions[action][0]:
        raise ValueError('Decision is not valid in the current proposal state')
    if action == 'accept':
        if review_hash != receipt(proposal):
            raise ValueError('Accept requires the exact review hash shown on the suggestion card')
        assert_current(store, proposal)
    with store.db:
        store.decision(pid, action, {'review_hash': receipt(proposal), 'note': note})
        store.db.execute('UPDATE proposals SET status=? WHERE id=?', (transitions[action][1], pid))
    return {'proposal_id': pid, 'status': transitions[action][1]}


def revise(store, pid, amendment, note):
    """Create a new review version; never carry acceptance over to changed text."""
    from .analyzer import validate_finding
    proposal = store.get('proposals', pid)
    if proposal['status'] not in {'proposed', 'accepted', 'evaluated', 'kept'}:
        raise ValueError('This proposal cannot be revised in its current state')
    if not isinstance(amendment, dict) or not note.strip():
        raise ValueError('Revision requires a JSON object and a reviewer note')
    allowed_fields = {'change', 'observation', 'evidence', 'hypothesis', 'scope', 'existing_guidance',
                      'missing_evidence', 'expected_benefit', 'evaluation'}
    if set(amendment) - allowed_fields:
        raise ValueError('Revision contains unsupported fields')
    assert_current(store, proposal)
    finding = store.get('findings', proposal['finding_id'])
    run = store.get('analysis_runs', finding['run_id'])
    sources = run['details']['source_ids']
    allowed = {r[0] for sid in sources for r in store.db.execute('SELECT id FROM events WHERE source_id=?', (sid,))}
    guides = {sid for sid in sources if store.get('sources', sid)['kind'] == 'guide'}
    details = validate_finding(store, {**proposal['details'], **amendment}, proposal['details']['scope']['workflow'], allowed, guides)
    details.update(derived_from=pid, authored_by='local_reviewer', revision_note=note)
    fingerprint = digest(encoded({k: details[k] for k in ('scope', 'target_hash', 'change')}).encode())
    if store.db.execute('SELECT 1 FROM proposals WHERE fingerprint=?', (fingerprint,)).fetchone():
        raise ValueError('An identical proposal already exists')
    fid, new_id = identifier('finding'), identifier('proposal')
    with store.db:
        store.db.execute('INSERT INTO findings VALUES (?,?,?)', (fid, finding['run_id'], encoded(details)))
        store.db.execute('INSERT INTO proposals VALUES (?,?,?,?,?)', (new_id, fid, 'proposed', fingerprint, encoded(details)))
        store.decision(pid, 'revise', {'replacement_proposal': new_id, 'note': note})
        store.db.execute("UPDATE proposals SET status='revised' WHERE id=?", (pid,))
    return {'proposal_id': new_id, 'status': 'proposed', 'derived_from': pid}


def apply(store, pid, trial, guide_path=None):
    proposal = store.get('proposals', pid)
    if proposal['status'] != 'accepted':
        raise ValueError('Only an accepted proposal may be applied')
    accepted = store.db.execute("SELECT details FROM decisions WHERE proposal_id=? AND action='accept' ORDER BY created_at DESC LIMIT 1", (pid,)).fetchone()
    if not accepted or json.loads(accepted[0])['review_hash'] != receipt(proposal):
        raise ValueError('Proposal differs from the accepted review')
    assert_current(store, proposal)
    d = proposal['details']
    relative = Path(guide_path or Path(d['target_path']).name)
    if relative.is_absolute() or '..' in relative.parts or not relative.name or relative.parts[0].startswith('.'):
        raise ValueError('Trial guide path must be a relative file path without traversal')
    trial = Path(trial).expanduser().absolute()
    # A fresh directory prevents overwriting existing work or following planted symlinks.
    trial.mkdir(parents=True, exist_ok=False)
    trial = trial.resolve()
    original = store.get('sources', d['change']['source_id'])['raw']
    amended = original.decode('utf-8').replace(d['change']['before'], d['change']['after'], 1).encode()
    if digest(original) != d['target_hash'] or digest(amended) != d['result_hash']:
        raise ValueError('Reviewed amendment hash mismatch')
    aid = identifier('application')
    baseline, treatment = trial / 'baseline' / relative, trial / 'treatment' / relative
    details = {'schema_version': 1, 'proposal_id': pid, 'review_hash': receipt(proposal),
               'trial': str(trial), 'baseline': str(baseline), 'treatment': str(treatment),
               'before_hash': digest(original), 'after_hash': digest(amended), 'state': 'prepared'}
    # Journal intent before filesystem changes; failure remains recoverable and never implies success.
    with store.db:
        store.db.execute('INSERT INTO applications VALUES (?,?,?,?)', (aid, pid, time.time(), encoded(details)))
    atomic_text(baseline, original)
    atomic_text(treatment, amended)
    if digest(treatment.read_bytes()) != d['result_hash']:
        raise ValueError('Trial verification failed')
    details['state'] = 'applied'
    atomic_text(trial / 'intervention.json', encoded({'application_id': aid, **details}).encode())
    with store.db:
        store.db.execute('UPDATE applications SET details=? WHERE id=?', (encoded(details), aid))
        store.db.execute("UPDATE proposals SET status='applied-to-trial' WHERE id=?", (pid,))
        store.decision(pid, 'apply', {'application_id': aid, 'review_hash': receipt(proposal)})
    return {'application_id': aid, **details}


def revert(store, aid, note=''):
    app = store.get('applications', aid)
    d = app['details']
    if d['state'] != 'applied':
        raise ValueError('Application is not active')
    target = trial_target(d)
    if target.is_symlink() or digest(target.read_bytes()) != d['after_hash']:
        raise ValueError('Treatment changed; refusing to overwrite subsequent work')
    proposal = store.get('proposals', app['proposal_id'])
    original = store.get('sources', proposal['details']['change']['source_id'])['raw']
    atomic_text(target, original)
    d['state'] = 'reverted'
    atomic_text(Path(d['trial']) / 'intervention.json', encoded({'application_id': aid, **d}).encode())
    with store.db:
        store.db.execute('UPDATE applications SET details=? WHERE id=?', (encoded(d), aid))
        store.db.execute("UPDATE proposals SET status='reverted' WHERE id=?", (app['proposal_id'],))
        store.decision(app['proposal_id'], 'revert', {'application_id': aid, 'note': note})
    return {'application_id': aid, 'status': 'reverted'}
