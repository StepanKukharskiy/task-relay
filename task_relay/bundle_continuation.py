"""Bounded second revision from a selected native/companion bundle.

A frozen plan names exact native text edits and JSON patches against the selected
versions. The submitted set is reconstructed and checked before registration.
The selected parent, image bytes and unrelated PPTX package members are reused.
This module records candidates only; review and selection are separate.
"""

import hashlib
import json
from pathlib import Path
import time
import uuid

from orchestrator import pptx_edit
from orchestrator.storage import transaction
from . import native_links, revision_bundle


SCHEMA = 'task-relay.bundle-continuation'
VERSION = 1
ROLES = ('slides', 'photo_manifest')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_bundle_continuation_plans(
        id TEXT PRIMARY KEY,job TEXT NOT NULL,request_key TEXT NOT NULL,
        parent_bundle TEXT NOT NULL,exact_request TEXT NOT NULL,
        plan_digest TEXT NOT NULL,plan TEXT NOT NULL,actor TEXT NOT NULL,
        created REAL NOT NULL,UNIQUE(job,request_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_bundle_continuations(
        id TEXT PRIMARY KEY,job TEXT NOT NULL,submission_key TEXT NOT NULL,
        plan_id TEXT NOT NULL,pptx_artifact TEXT NOT NULL,pptx_sha256 TEXT NOT NULL,
        slides_artifact TEXT NOT NULL,slides_sha256 TEXT NOT NULL,
        photo_manifest_artifact TEXT NOT NULL,photo_manifest_sha256 TEXT NOT NULL,
        set_digest TEXT NOT NULL,checks TEXT NOT NULL,submitted_by TEXT NOT NULL,
        created REAL NOT NULL,UNIQUE(job,submission_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_bundle_continuation_reviews(
        id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL UNIQUE,job TEXT NOT NULL,
        set_digest TEXT NOT NULL,decision TEXT NOT NULL,reviewer TEXT NOT NULL,
        note TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_bundle_continuation_selections(
        candidate_id TEXT PRIMARY KEY,job TEXT NOT NULL,set_digest TEXT NOT NULL,
        selected_by TEXT NOT NULL,receipt TEXT NOT NULL,created REAL NOT NULL)''')


def _parent(db, bundle_id):
    bundle, _ = revision_bundle.verified(db, bundle_id)
    if revision_bundle.status(db, bundle_id) != 'selected':
        raise ValueError('Continuation needs an exact selected parent bundle.')
    members = {item['role']: dict(item) for item in db.execute('''
        SELECT * FROM relay_revision_bundle_files WHERE bundle_id=?''', (bundle_id,))}
    if set(members) != set(ROLES):
        raise ValueError('Selected parent has incomplete companion versions.')
    selection = db.execute('''SELECT * FROM relay_revision_bundle_selections
        WHERE bundle_id=?''', (bundle_id,)).fetchone()
    if selection['set_digest'] != bundle['set_digest']:
        raise ValueError('Parent selection version changed.')
    receipt_sha256 = hashlib.sha256(selection['receipt'].encode('utf-8')).hexdigest()
    return bundle, members, receipt_sha256, selection['receipt']


def _validated_plan(db, parent_bundle, intent, manifest, companions, cross_checks,
                    decision_projections):
    bundle, members, selection_sha, selection_receipt = _parent(db, parent_bundle)
    if not isinstance(intent, str) or not intent.strip() or len(intent) > 10_000:
        raise ValueError('Continuation needs a bounded change intent.')
    native = native_links._artifact(db, bundle['pptx_candidate'])
    pptx_edit.validate(manifest)
    if (manifest['source_sha256'] != native['sha256']
            or any(edit['kind'] not in ('replace_text', 'replace_notes_text')
                   for edit in manifest['edits'])):
        raise ValueError('Continuation permits exact native text and notes edits only.')
    if (not isinstance(companions, list) or not 1 <= len(companions) <= 2
            or len({item.get('role') for item in companions if isinstance(item, dict)}) != len(companions)):
        raise ValueError('Continuation needs distinct declared companion patches.')
    frozen = []
    documents = {}
    for item in sorted(companions, key=lambda value: value['role']):
        if not isinstance(item, dict) or set(item) != {'role', 'patches'} or item['role'] not in members:
            raise ValueError('Continuation companion has an unsupported role or field.')
        source = native_links._artifact(db, members[item['role']]['candidate_artifact'])
        revised = revision_bundle.apply_patches(Path(source['blob']).read_bytes(), item['patches'])
        frozen.append({'role': item['role'], 'baseline_artifact': source['id'],
                       'baseline_sha256': source['sha256'], 'patches': item['patches'],
                       'expected_digest': _digest(revised)})
        documents[item['role']] = revised
    parent_plan = db.execute('''SELECT plan FROM relay_revision_bundle_plans
        WHERE id=?''', (bundle['plan_id'],)).fetchone()
    if parent_plan is None:
        raise ValueError('Parent bundle plan is missing.')
    parent_spec = native_links._json(parent_plan['plan'])
    image = native_links._artifact(db, parent_spec['image_artifact'])
    if image['sha256'] != parent_spec['image_sha256']:
        raise ValueError('Pinned parent image version changed.')
    if (not isinstance(cross_checks, list) or not 1 <= len(cross_checks) <= 100
            or not {'picture', 'forbid_terms'}.issubset(
                {item.get('kind') for item in cross_checks if isinstance(item, dict)})):
        raise ValueError('Continuation needs picture and stale-term cross-checks.')
    if not isinstance(decision_projections, list) or len(decision_projections) > 20:
        raise ValueError('Continuation decision projections must be bounded.')
    if decision_projections:
        receipt = native_links._json(selection_receipt)
        if not isinstance(receipt, dict):
            raise ValueError('Selected parent has no structured decision receipt.')
        for item in decision_projections:
            if (not isinstance(item, dict)
                    or set(item) != {'receipt_key', 'role', 'pointer'}
                    or item['role'] not in documents
                    or item['receipt_key'] not in receipt
                    or revision_bundle._value(documents[item['role']], item['pointer'])
                       != receipt[item['receipt_key']]):
                raise ValueError('Companion decision claim differs from selected receipt.')
    plan = {'schema': SCHEMA + '.plan', 'version': VERSION, 'job': bundle['job'],
            'parent_bundle': parent_bundle, 'parent_set_digest': bundle['set_digest'],
            'parent_selection_sha256': selection_sha, 'intent': intent,
            'pptx_baseline_artifact': native['id'], 'pptx_baseline_sha256': native['sha256'],
            'manifest': manifest, 'companions': frozen,
            'reused': [{'role': role, 'artifact': members[role]['candidate_artifact'],
                        'sha256': members[role]['candidate_sha256']}
                       for role in ROLES if role not in {item['role'] for item in frozen}],
            'image_artifact': image['id'], 'image_sha256': image['sha256'],
            'cross_checks': cross_checks,
            'decision_projections': decision_projections}
    return bundle, plan


def record_plan(db, *, parent_bundle, request_key, exact_request, intent, actor,
                manifest, companions, cross_checks, decision_projections=None):
    if (not all(isinstance(value, str) and value.strip() for value in
                (request_key, exact_request, actor)) or len(request_key) > 200
            or len(exact_request) > 100_000):
        raise ValueError('Continuation needs an exact request, actor and bounded key.')
    with transaction(db):
        bundle, plan = _validated_plan(db, parent_bundle, intent, manifest,
                                       companions, cross_checks,
                                       decision_projections or [])
        digest = _digest(plan)
        old = db.execute('''SELECT * FROM relay_bundle_continuation_plans
            WHERE job=? AND request_key=?''', (bundle['job'], request_key)).fetchone()
        if old:
            if (old['parent_bundle'] != parent_bundle or old['exact_request'] != exact_request
                    or old['plan_digest'] != digest or old['plan'] != _json(plan)
                    or old['actor'] != actor):
                raise ValueError('Continuation request key belongs to another plan.')
            return old['id']
        ident = uuid.uuid4().hex
        db.execute('INSERT INTO relay_bundle_continuation_plans VALUES (?,?,?,?,?,?,?,?,?)',
                   (ident, bundle['job'], request_key, parent_bundle, exact_request,
                    digest, _json(plan), actor, time.time()))
        return ident


def inspect_plan(db, plan_id):
    row = db.execute('SELECT * FROM relay_bundle_continuation_plans WHERE id=?',
                     (plan_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown continuation plan.')
    row = dict(row)
    try:
        saved = native_links._json(row['plan'])
        if _digest(saved) != row['plan_digest']:
            raise ValueError('Saved continuation plan digest changed.')
        _, current = _validated_plan(db, row['parent_bundle'], saved['intent'],
            saved['manifest'], [{key: item[key] for key in ('role', 'patches')}
                                for item in saved['companions']], saved['cross_checks'],
            saved['decision_projections'])
        if current != saved or row['job'] != saved['job']:
            raise ValueError('Continuation baseline or selection changed.')
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return {**row, 'status': 'stale', 'reason': str(exc)}
    return {**row, 'plan': saved, 'status': 'current'}


def _member_diff(before, after):
    with pptx_edit._package(before) as old, pptx_edit._package(after) as new:
        names = set(old.namelist())
        if names != set(new.namelist()):
            raise ValueError('Continuation changed the native package member set.')
        changed = sorted(name for name in names if old.read(name) != new.read(name))
        if any(name.startswith('ppt/media/') or name.endswith('.rels') for name in changed):
            raise ValueError('Continuation changed native image bytes or relationships.')
        return {'total': len(names), 'changed': changed,
                'preserved': len(names)-len(changed)}


def _check(db, plan_id, pptx_raw, companion_raw):
    frozen = inspect_plan(db, plan_id)
    if frozen['status'] != 'current':
        raise ValueError('Continuation plan is stale: ' + frozen['reason'])
    plan = frozen['plan']
    baseline = native_links._artifact(db, plan['pptx_baseline_artifact'])
    before = Path(baseline['blob']).read_bytes()
    expected, _ = pptx_edit.edit(before, plan['manifest'], images={})
    from .agent_candidate import _files_equal
    compared = _files_equal(expected, pptx_raw)
    members = _member_diff(before, pptx_raw)
    documents, versions = {}, {}
    patch_by_role = {item['role']: item for item in plan['companions']}
    reused = {item['role']: item for item in plan['reused']}
    if set(companion_raw) != set(patch_by_role):
        raise ValueError('Continuation supplied undeclared companion files.')
    for role in ROLES:
        source_id = (patch_by_role[role]['baseline_artifact'] if role in patch_by_role
                     else reused[role]['artifact'])
        source = native_links._artifact(db, source_id)
        raw = Path(source['blob']).read_bytes()
        if role in patch_by_role:
            expected_json = revision_bundle.apply_patches(raw, patch_by_role[role]['patches'])
            candidate = revision_bundle._document(companion_raw[role])
            if candidate != expected_json or _digest(expected_json) != patch_by_role[role]['expected_digest']:
                raise ValueError('Continuation companion differs from exact patches: ' + role)
            raw_sha = hashlib.sha256(companion_raw[role]).hexdigest()
        else:
            candidate = revision_bundle._document(raw)
            raw_sha = source['sha256']
        documents[role] = candidate
        versions[role] = {'baseline_artifact': source_id, 'baseline_sha256': source['sha256'],
                          'candidate_sha256': raw_sha, 'reused': role in reused}
    temp_path = None
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as temporary:
            temporary.write(pptx_raw)
            temp_path = Path(temporary.name)
        couplings = revision_bundle._generic_couplings(db, {'blob': str(temp_path)},
                                                        documents, plan)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    set_digest = _digest({'plan_digest': frozen['plan_digest'],
                          'pptx_sha256': hashlib.sha256(pptx_raw).hexdigest(),
                          'companions': versions, 'image_sha256': plan['image_sha256']})
    checks = {'schema': SCHEMA + '.checks', 'version': VERSION,
              'plan_digest': frozen['plan_digest'], 'parent_set_digest': plan['parent_set_digest'],
              'set_digest': set_digest, 'pptx_sha256': hashlib.sha256(pptx_raw).hexdigest(),
              'native_members': members, 'complete_package_members_compared': compared,
              'companions': versions, 'couplings': couplings,
              'image_reused_sha256': plan['image_sha256'],
              'review': 'pending', 'selection': 'none'}
    return frozen, checks


def submit(rt, *, plan_id, submission_key, pptx_file, companion_files, submitted_by):
    if (not all(isinstance(value, str) and value.strip() for value in
                (submission_key, submitted_by)) or len(submission_key) > 200):
        raise ValueError('Continuation submission needs a bounded key and actor.')
    from orchestrator.runtime import safe_file
    paths = {'pptx': Path(pptx_file).absolute()}
    paths.update({role: Path(path).absolute() for role, path in companion_files.items()})
    for path in paths.values():
        safe_file(Path(path.anchor), str(path.relative_to(path.anchor)))
    raw = {role: path.read_bytes() for role, path in paths.items()}
    frozen, checks = _check(rt.db, plan_id, raw['pptx'],
                            {key: value for key, value in raw.items() if key != 'pptx'})
    with transaction(rt.db):
        second, current = _check(rt.db, plan_id, raw['pptx'],
                                  {key: value for key, value in raw.items() if key != 'pptx'})
        if second['plan_digest'] != frozen['plan_digest'] or current != checks:
            raise ValueError('Continuation changed before registration.')
        old = rt.db.execute('''SELECT * FROM relay_bundle_continuations
            WHERE job=? AND submission_key=?''', (frozen['job'], submission_key)).fetchone()
        if old:
            if (old['plan_id'] != plan_id or old['set_digest'] != checks['set_digest']
                    or old['checks'] != _json(checks) or old['submitted_by'] != submitted_by):
                raise ValueError('Continuation submission key belongs to another set.')
            verified(rt.db, old['id'])
            from .execution_capture import notify
            notify(rt.db, 'bundle_continuation', old['id'])
            return old['id']
        ids = {}
        for role, filename in (('pptx', 'presentation.pptx'),
                               ('slides', 'slides.json'),
                               ('photo_manifest', 'selected-photo-manifest.json')):
            if role in paths:
                ids[role] = rt.register(paths[role], 'Agent-submitted continuation',
                    task='bundle_continuation', path='delivery/' + filename)
                if rt.artifact(ids[role])['sha256'] != (
                        checks['pptx_sha256'] if role == 'pptx' else
                        checks['companions'][role]['candidate_sha256']):
                    raise ValueError('Continuation file changed during registration.')
            else:
                ids[role] = next(item['artifact'] for item in
                                   frozen['plan']['reused'] if item['role'] == role)
        ident = uuid.uuid4().hex
        rt.db.execute('INSERT INTO relay_bundle_continuations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (ident, frozen['job'], submission_key, plan_id,
             ids['pptx'], checks['pptx_sha256'],
             ids['slides'], checks['companions']['slides']['candidate_sha256'],
             ids['photo_manifest'], checks['companions']['photo_manifest']['candidate_sha256'],
             checks['set_digest'], _json(checks), submitted_by, time.time()))
        from .execution_capture import notify
        notify(rt.db, 'bundle_continuation', ident)
    return ident


def verified(db, ident):
    row = db.execute('SELECT * FROM relay_bundle_continuations WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Unknown continuation candidate.')
    row = dict(row)
    plan = inspect_plan(db, row['plan_id'])
    if plan['status'] != 'current':
        raise ValueError('Continuation plan is stale: ' + plan['reason'])
    changed = {item['role'] for item in plan['plan']['companions']}
    raw = {}
    for role, column in (('pptx', 'pptx_artifact'),
                         ('slides', 'slides_artifact'),
                         ('photo_manifest', 'photo_manifest_artifact')):
        artifact = native_links._artifact(db, row[column])
        expected_path = {'pptx': 'delivery/presentation.pptx',
                         'slides': 'delivery/slides.json',
                         'photo_manifest': 'delivery/selected-photo-manifest.json'}[role]
        if (role == 'pptx' or role in changed) and (
                artifact['task'] != 'bundle_continuation'
                or artifact['path'] != expected_path
                or artifact['run'] is not None or artifact['attempt'] is not None):
            raise ValueError('Continuation candidate artifact has unexpected ownership.')
        raw[role] = Path(artifact['blob']).read_bytes()
    for item in plan['plan']['reused']:
        if row[item['role'] + '_artifact'] != item['artifact']:
            raise ValueError('Reused continuation artifact identity changed.')
    _, checks = _check(db, row['plan_id'], raw['pptx'],
                        {role: raw[role] for role in changed})
    if (row['job'] != plan['job'] or row['set_digest'] != checks['set_digest']
            or row['checks'] != _json(checks)
            or any(row[column] != checks[key] for column, key in
                   (('pptx_sha256', 'pptx_sha256'),))
            or row['slides_sha256'] != checks['companions']['slides']['candidate_sha256']
            or row['photo_manifest_sha256'] != checks['companions']['photo_manifest']['candidate_sha256']):
        raise ValueError('Saved continuation version or checks changed.')
    return row, checks


def review(db, *, candidate_id, decision, reviewer, note, expected_set_digest):
    if (decision not in ('accept', 'revise')
            or not all(isinstance(value, str) and value.strip() for value in
                       (reviewer, note, expected_set_digest))):
        raise ValueError('Continuation review needs an exact decision and reason.')
    with transaction(db):
        candidate, _ = verified(db, candidate_id)
        if (candidate['set_digest'] != expected_set_digest
                or reviewer == candidate['submitted_by']):
            raise ValueError('Independent continuation review needs exact current versions.')
        if db.execute('SELECT 1 FROM relay_bundle_continuation_reviews WHERE candidate_id=?',
                      (candidate_id,)).fetchone():
            raise ValueError('Continuation candidate already reviewed.')
        ident = uuid.uuid4().hex
        db.execute('INSERT INTO relay_bundle_continuation_reviews VALUES (?,?,?,?,?,?,?,?)',
                   (ident, candidate_id, candidate['job'], expected_set_digest,
                    decision, reviewer, note, time.time()))
        return ident


def select(db, *, candidate_id, selected_by, receipt, expected_set_digest):
    if not all(isinstance(value, str) and value.strip() for value in
               (selected_by, receipt, expected_set_digest)):
        raise ValueError('Continuation selection needs exact actor and receipt.')
    with transaction(db):
        candidate, _ = verified(db, candidate_id)
        if candidate['set_digest'] != expected_set_digest:
            raise ValueError('Continuation set changed before selection.')
        approval = db.execute('''SELECT * FROM relay_bundle_continuation_reviews
            WHERE candidate_id=?''', (candidate_id,)).fetchone()
        if (approval is None or approval['decision'] != 'accept'
                or approval['set_digest'] != expected_set_digest):
            raise ValueError('Exact independent continuation acceptance is required.')
        if db.execute('SELECT 1 FROM relay_bundle_continuation_selections WHERE candidate_id=?',
                      (candidate_id,)).fetchone():
            raise ValueError('Continuation candidate already selected.')
        plan = db.execute('SELECT parent_bundle FROM relay_bundle_continuation_plans WHERE id=?',
                          (candidate['plan_id'],)).fetchone()
        if plan is None:
            raise ValueError('Continuation parent plan is missing.')
        other = db.execute('''SELECT 1 FROM relay_bundle_continuation_selections s
            JOIN relay_bundle_continuations c ON c.id=s.candidate_id
            JOIN relay_bundle_continuation_plans p ON p.id=c.plan_id
            WHERE p.parent_bundle=?''', (plan['parent_bundle'],)).fetchone()
        if other:
            raise ValueError('Another continuation of this parent is already selected.')
        db.execute('INSERT INTO relay_bundle_continuation_selections VALUES (?,?,?,?,?,?)',
                   (candidate_id, candidate['job'], expected_set_digest,
                    selected_by, receipt, time.time()))
    return candidate_id


def status(db, candidate_id):
    if db.execute('SELECT 1 FROM relay_bundle_continuation_selections WHERE candidate_id=?',
                  (candidate_id,)).fetchone():
        return 'selected'
    row = db.execute('SELECT decision FROM relay_bundle_continuation_reviews WHERE candidate_id=?',
                     (candidate_id,)).fetchone()
    return ({'accept': 'accepted', 'revise': 'revision_requested'}[row['decision']]
            if row else 'verified_pending_review')


def records(db, job):
    return {'plans': [dict(row) for row in db.execute(
                'SELECT * FROM relay_bundle_continuation_plans WHERE job=? ORDER BY created,id', (job,))],
            'candidates': [dict(row) for row in db.execute(
                'SELECT * FROM relay_bundle_continuations WHERE job=? ORDER BY created,id', (job,))],
            'reviews': [dict(row) for row in db.execute(
                'SELECT * FROM relay_bundle_continuation_reviews WHERE job=? ORDER BY created,id',
                (job,))],
            'selections': [dict(row) for row in db.execute(
                'SELECT * FROM relay_bundle_continuation_selections WHERE job=? ORDER BY created,candidate_id',
                (job,))]}
