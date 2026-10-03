"""Bounded external-agent PPTX candidates against a frozen Relay handoff.

The agent supplies a native file and an exact edit manifest. Relay reconstructs
the permitted edit from the registered baseline and compares every package
member. Submission, independent review and user selection are separate records.
"""

import hashlib
import json
from pathlib import Path
import time
import uuid

from orchestrator import pptx_edit
from orchestrator.storage import transaction
from . import impact_handoff, native_links


SCHEMA = 'task-relay.agent-candidate'
VERSION = 1


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_agent_candidates(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, submission_key TEXT NOT NULL,
        handoff_id TEXT NOT NULL, candidate_artifact TEXT NOT NULL UNIQUE,
        candidate_sha256 TEXT NOT NULL, manifest TEXT NOT NULL,
        submitted_by TEXT NOT NULL, checks TEXT NOT NULL, created REAL NOT NULL,
        UNIQUE(job,submission_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_agent_candidate_inputs(
        candidate_artifact TEXT NOT NULL, job TEXT NOT NULL, path TEXT NOT NULL,
        artifact TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(candidate_artifact,path))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_agent_candidate_reviews(
        id TEXT PRIMARY KEY, candidate_artifact TEXT NOT NULL UNIQUE,
        candidate_sha256 TEXT NOT NULL, plan_digest TEXT NOT NULL,
        decision TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL,
        checks TEXT NOT NULL, created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_agent_candidate_feedback(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, feedback_key TEXT NOT NULL,
        candidate_artifact TEXT NOT NULL, candidate_sha256 TEXT NOT NULL,
        plan_digest TEXT NOT NULL, scope TEXT NOT NULL, assessment TEXT NOT NULL,
        actor TEXT NOT NULL, exact_feedback TEXT NOT NULL, created REAL NOT NULL,
        UNIQUE(job,feedback_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_agent_candidate_selections(
        candidate_artifact TEXT PRIMARY KEY, candidate_sha256 TEXT NOT NULL,
        plan_digest TEXT NOT NULL, selected_by TEXT NOT NULL,
        receipt TEXT NOT NULL, created REAL NOT NULL)''')


def _files_equal(expected, submitted):
    """Ignore ZIP metadata; require the complete OOXML member set and bytes."""
    with pptx_edit._package(expected) as old, pptx_edit._package(submitted) as new:
        names = set(old.namelist())
        if names != set(new.namelist()):
            raise ValueError('Candidate PPTX package members differ from the declared edit.')
        changed = sorted(name for name in names if old.read(name) != new.read(name))
        if changed:
            raise ValueError('Candidate PPTX differs from the declared edit: ' + changed[0])
        return len(names)


def _location(edit):
    if edit['kind'] in ('replace_notes_text', 'remove_notes_run'):
        return ('pptx_notes_run', edit['slide'], edit['index'], edit['old'])
    if edit['kind'] in ('remove_table_row', 'remove_shape'):
        raise ValueError('Structural edits need expanded baseline locations.')
    if edit['kind'] == 'replace_image':
        return ('pptx_picture', edit['slide'], edit['shape_id'], edit['old_sha256'])
    if 'row' in edit:
        return ('pptx_table_cell', edit['slide'], edit['shape_id'],
                edit['row'], edit['column'], edit['old'])
    return ('pptx_text_run', edit['slide'], edit['shape_id'], edit['old'])


def _planned(location):
    if location['type'] == 'pptx_notes_run':
        return ('pptx_notes_run', location['slide'], location['index'], location['text'])
    if location['type'] == 'pptx_picture':
        return ('pptx_picture', location['slide'], location['shape_id'], location['sha256'])
    if location['type'] == 'pptx_table_cell':
        return ('pptx_table_cell', location['slide'], location['shape_id'],
                location['row'], location['column'], location['text'])
    if location['type'] == 'pptx_text_run':
        return ('pptx_text_run', location['slide'], location['shape_id'], location['text'])
    raise ValueError('Affected native location needs a supported edit adapter.')


def _covered_edit(edit, listing):
    if edit['kind'] not in ('remove_table_row', 'remove_shape'):
        return [_location(edit)]
    if edit['slide'] > len(listing['slides']):
        raise ValueError('Structural edit targets a slide outside the baseline.')
    slide = listing['slides'][edit['slide']-1]
    shapes = [shape for shape in slide['shapes']
              if shape['shape_id'] == edit['shape_id']]
    if len(shapes) != 1:
        raise ValueError('Structural edit targets a missing or ambiguous shape.')
    shape = shapes[0]
    if edit['kind'] == 'remove_table_row':
        cells = [cell for cell in shape.get('table_cells', [])
                 if cell['row'] == edit['row']]
        runs = [value for cell in cells for value in cell['text_runs']]
        if not cells or runs != edit['old_runs']:
            raise ValueError('Structural row edit does not match exact baseline runs.')
        return [('pptx_table_cell', edit['slide'], edit['shape_id'],
                 edit['row'], cell['column'], value)
                for cell in cells for value in cell['text_runs']]
    if shape['xml_sha256'] != edit['old_xml_sha256']:
        raise ValueError('Structural shape edit does not match exact baseline XML.')
    covered = [('pptx_text_run', edit['slide'], edit['shape_id'], value)
               for value in shape['text_runs'] if value]
    if shape.get('image_sha256'):
        covered.append(('pptx_picture', edit['slide'], edit['shape_id'],
                        shape['image_sha256']))
    if not covered:
        raise ValueError('Structural shape has no reviewed native content to remove.')
    return covered


def _validate(db, handoff_id, raw, manifest, images):
    handoff = impact_handoff.inspect(db, handoff_id)
    if handoff['status'] != 'current' or handoff['kind'] not in (
            impact_handoff.NATIVE_WITHDRAWAL, impact_handoff.NATIVE_REPLACEMENT):
        raise ValueError('Frozen handoff is not current and supported: ' + handoff['reason'])
    plan = handoff['plan']
    baseline = native_links._artifact(db, handoff['baseline_artifact'])
    pptx_edit.validate(manifest)
    if manifest['source_sha256'] != baseline['sha256']:
        raise ValueError('Edit manifest names a different baseline version.')
    edits = manifest['edits']
    if handoff['kind'] == impact_handoff.NATIVE_REPLACEMENT:
        picture_edits = [item for item in edits if item['kind'] == 'replace_image']
        replacement = native_links._artifact(db, handoff['inputs']['replacement_artifact'])
        if (len(picture_edits) != 1 or len(images) != 1
                or picture_edits[0]['new_sha256'] != replacement['sha256']
                or hashlib.sha256(images[picture_edits[0]['path']]).hexdigest()
                   != replacement['sha256']):
            raise ValueError('Replacement candidate needs the exact pinned picture input.')
    wanted = [_planned(item['location']) for item in plan['affected']]
    listing = pptx_edit.inspect(Path(baseline['blob']).read_bytes())
    supplied = [location for item in edits for location in _covered_edit(item, listing)]
    if len(wanted) != len(set(wanted)) or len(supplied) != len(set(supplied)) or set(supplied) != set(wanted):
        raise ValueError('Candidate edits must cover exactly the handoff affected locations.')
    expected, native = pptx_edit.edit(Path(baseline['blob']).read_bytes(), manifest, images=images)
    parts = _files_equal(expected, raw)
    if hashlib.sha256(raw).hexdigest() == baseline['sha256']:
        raise ValueError('Candidate is identical to baseline.')
    return handoff, {'schema': SCHEMA + '.checks', 'version': 1,
        'baseline_sha256': baseline['sha256'],
        'candidate_sha256': hashlib.sha256(raw).hexdigest(),
        'plan_digest': handoff['plan_digest'], 'edit_count': len(edits),
        'affected_locations_matched': len(wanted),
        'complete_package_members_compared': parts,
        'unchanged_package_parts_preserved': native['untouched_parts_preserved'],
        'changed_slides': native['changed_slides'],
        'visual_review': 'not_performed',
        'semantic_review': 'pending',
        'scope': 'Exact manifest edits only; no whole-deck semantic acceptance.'}


def _input_files(manifest, image_files):
    paths = {edit['path'] for edit in manifest['edits'] if edit['kind'] == 'replace_image'}
    if set(image_files) != paths:
        raise ValueError('Image inputs must match the exact manifest paths.')
    images = {}
    for name, file in image_files.items():
        path = Path(file).absolute()
        from orchestrator.runtime import safe_file
        safe_file(Path(path.anchor), str(path.relative_to(path.anchor)))
        images[name] = path.read_bytes()
    return images


def submit(rt, *, handoff_id, submission_key, candidate_path, manifest,
           image_files, submitted_by):
    """Register a checked file, never accept or select it implicitly."""
    if not all(isinstance(value, str) and value.strip() for value in
               (handoff_id, submission_key, submitted_by)) or len(submission_key) > 200:
        raise ValueError('Submission needs an exact handoff, key and agent identity.')
    candidate_path = Path(candidate_path).absolute()
    from orchestrator.runtime import safe_file
    safe_file(Path(candidate_path.anchor), str(candidate_path.relative_to(candidate_path.anchor)))
    raw = candidate_path.read_bytes()
    if len(raw) > 50_000_000:
        raise ValueError('Candidate exceeds the bounded PPTX input limit.')
    pptx_edit.validate(manifest)
    images = _input_files(manifest, image_files)
    image_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in images.items()}
    source = rt.db.execute('SELECT job FROM relay_impact_handoffs WHERE id=?', (handoff_id,)).fetchone()
    if source is None:
        raise ValueError('Unknown frozen handoff.')
    job = source['job']
    previous = rt.db.execute('''SELECT * FROM relay_agent_candidates
        WHERE job=? AND submission_key=?''', (job, submission_key)).fetchone()
    if previous:
        previous = dict(previous)
        saved_images = {row['path']: row['sha256'] for row in rt.db.execute(
            'SELECT path,sha256 FROM relay_agent_candidate_inputs WHERE candidate_artifact=?',
            (previous['candidate_artifact'],))}
        if (previous['handoff_id'] != handoff_id or previous['submitted_by'] != submitted_by
                or previous['candidate_sha256'] != hashlib.sha256(raw).hexdigest()
                or previous['manifest'] != _json(manifest)
                or saved_images != image_hashes):
            raise ValueError('Submission key already belongs to different candidate content.')
        verified(rt.db, previous['candidate_artifact'])
        from .execution_capture import notify
        notify(rt.db, 'native_candidate', previous['id'])
        return previous['candidate_artifact']
    handoff, checks = _validate(rt.db, handoff_id, raw, manifest, images)
    with transaction(rt.db):
        locked, locked_checks = _validate(rt.db, handoff_id, raw, manifest, images)
        if locked['plan_digest'] != handoff['plan_digest'] or locked_checks != checks:
            raise ValueError('Handoff or candidate checks changed before registration.')
        image_inputs = {}
        for name, path in image_files.items():
            ident = (handoff['inputs']['replacement_artifact']
                     if handoff['kind'] == impact_handoff.NATIVE_REPLACEMENT else
                     rt.register(path, 'Agent candidate declared picture input',
                         task='agent_candidate', path='inputs/' + name))
            if rt.artifact(ident)['sha256'] != image_hashes[name]:
                raise ValueError('Picture input changed during registration.')
            image_inputs[name] = {'artifact': ident, 'sha256': image_hashes[name]}
        aid = rt.register(candidate_path, 'Agent-submitted native PPTX candidate',
            task='agent_candidate', path='delivery/agent_candidate.pptx')
        if rt.artifact(aid)['sha256'] != checks['candidate_sha256']:
            raise ValueError('Candidate changed during registration.')
        rt.db.execute('''INSERT INTO relay_agent_candidates VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (uuid.uuid4().hex, job, submission_key, handoff_id, aid,
             checks['candidate_sha256'], _json(manifest), submitted_by,
             _json(checks), time.time()))
        for name, item in image_inputs.items():
            rt.db.execute('''INSERT INTO relay_agent_candidate_inputs VALUES (?,?,?,?,?)''',
                (aid, job, name, item['artifact'], item['sha256']))
        from .execution_capture import notify
        notify(rt.db, 'native_candidate', rt.db.execute('SELECT id FROM relay_agent_candidates WHERE candidate_artifact=?', (aid,)).fetchone()[0])
    return aid


def verified(db, candidate_artifact):
    row = db.execute('SELECT * FROM relay_agent_candidates WHERE candidate_artifact=?',
                     (candidate_artifact,)).fetchone()
    if row is None:
        raise ValueError('Unknown agent candidate.')
    row = dict(row)
    candidate = native_links._artifact(db, candidate_artifact)
    if candidate['sha256'] != row['candidate_sha256']:
        raise ValueError('Registered candidate version changed.')
    image_inputs = {item['path']: dict(item) for item in db.execute(
        'SELECT * FROM relay_agent_candidate_inputs WHERE candidate_artifact=?',
        (candidate_artifact,))}
    images = {}
    for name, item in image_inputs.items():
        source = native_links._artifact(db, item['artifact'])
        if source['sha256'] != item['sha256']:
            raise ValueError('Registered image input version changed.')
        images[name] = Path(source['blob']).read_bytes()
    handoff, checks = _validate(db, row['handoff_id'], Path(candidate['blob']).read_bytes(),
                                json.loads(row['manifest']), images)
    if checks != json.loads(row['checks']) or checks['candidate_sha256'] != candidate['sha256']:
        raise ValueError('Saved candidate checks changed.')
    return row, candidate, handoff, checks


def review(db, *, candidate_artifact, decision, reviewer, note,
           expected_sha256, expected_plan_digest):
    if decision not in ('accept', 'revise') or not all(isinstance(value, str) and value.strip()
            for value in (reviewer, note, expected_sha256, expected_plan_digest)):
        raise ValueError('Independent review needs an actor, decision and reason.')
    with transaction(db):
        row, candidate, handoff, checks = verified(db, candidate_artifact)
        if (reviewer == row['submitted_by'] or expected_sha256 != candidate['sha256']
                or expected_plan_digest != handoff['plan_digest']):
            raise ValueError('Independent reviewer and exact current versions are required.')
        if db.execute('SELECT 1 FROM relay_agent_candidate_reviews WHERE candidate_artifact=?',
                      (candidate_artifact,)).fetchone():
            raise ValueError('Candidate already reviewed.')
        ident = uuid.uuid4().hex
        db.execute('''INSERT INTO relay_agent_candidate_reviews VALUES (?,?,?,?,?,?,?,?,?)''',
            (ident, candidate_artifact, candidate['sha256'], handoff['plan_digest'],
             decision, reviewer, note, _json(checks), time.time()))
        return ident


def record_feedback(db, *, candidate_artifact, feedback_key, actor,
                    exact_feedback, expected_sha256, expected_plan_digest,
                    scope='visual_layout', assessment='looks_good'):
    """Pin scoped user feedback without making a review or selection decision."""
    if (scope != 'visual_layout' or assessment not in ('looks_good', 'needs_changes')
            or not all(isinstance(value, str) and value.strip() for value in
                       (feedback_key, actor, exact_feedback, expected_sha256,
                        expected_plan_digest))
            or len(feedback_key) > 200 or len(exact_feedback) > 100_000):
        raise ValueError('Scoped feedback needs an exact visual assessment and text.')
    with transaction(db):
        row, candidate, handoff, _ = verified(db, candidate_artifact)
        if (candidate['sha256'] != expected_sha256
                or handoff['plan_digest'] != expected_plan_digest):
            raise ValueError('Feedback candidate or handoff version changed.')
        fields = (row['job'], feedback_key, candidate_artifact, expected_sha256,
                  expected_plan_digest, scope, assessment, actor, exact_feedback)
        prior = db.execute('''SELECT * FROM relay_agent_candidate_feedback
            WHERE job=? AND feedback_key=?''', fields[:2]).fetchone()
        if prior:
            if tuple(prior[key] for key in ('job', 'feedback_key', 'candidate_artifact',
                    'candidate_sha256', 'plan_digest', 'scope', 'assessment',
                    'actor', 'exact_feedback')) != fields:
                raise ValueError('Feedback key already records different exact feedback.')
            return prior['id']
        ident = uuid.uuid4().hex
        db.execute('''INSERT INTO relay_agent_candidate_feedback
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (ident, *fields, time.time()))
        return ident


def select(db, *, candidate_artifact, selected_by, receipt,
           expected_sha256, expected_plan_digest):
    if not all(isinstance(value, str) and value.strip() for value in
               (selected_by, receipt, expected_sha256, expected_plan_digest)):
        raise ValueError('Selection needs an explicit actor, receipt and exact versions.')
    with transaction(db):
        _, candidate, handoff, _ = verified(db, candidate_artifact)
        if expected_sha256 != candidate['sha256'] or expected_plan_digest != handoff['plan_digest']:
            raise ValueError('Candidate or handoff version changed before selection.')
        approval = db.execute('''SELECT * FROM relay_agent_candidate_reviews
            WHERE candidate_artifact=?''', (candidate_artifact,)).fetchone()
        if (approval is None or approval['decision'] != 'accept'
                or approval['candidate_sha256'] != candidate['sha256']
                or approval['plan_digest'] != handoff['plan_digest']):
            raise ValueError('An independent acceptance of these exact versions is required.')
        if db.execute('SELECT 1 FROM relay_agent_candidate_selections WHERE candidate_artifact=?',
                      (candidate_artifact,)).fetchone():
            raise ValueError('Candidate already selected.')
        db.execute('''INSERT INTO relay_agent_candidate_selections VALUES (?,?,?,?,?,?)''',
            (candidate_artifact, candidate['sha256'], handoff['plan_digest'],
             selected_by, receipt, time.time()))
    return candidate_artifact


def records(db, job):
    candidates = [dict(row) for row in db.execute('''SELECT * FROM relay_agent_candidates
        WHERE job=? ORDER BY created,id''', (job,))]
    ids = [row['candidate_artifact'] for row in candidates]
    inputs = [dict(row) for row in db.execute('''SELECT * FROM relay_agent_candidate_inputs
        WHERE job=? ORDER BY candidate_artifact,path''', (job,))]
    reviews = [dict(row) for row in db.execute('SELECT * FROM relay_agent_candidate_reviews')
               if row['candidate_artifact'] in ids]
    feedback = [dict(row) for row in db.execute('''SELECT * FROM relay_agent_candidate_feedback
        WHERE job=? ORDER BY created,id''', (job,))]
    selections = [dict(row) for row in db.execute('SELECT * FROM relay_agent_candidate_selections')
                  if row['candidate_artifact'] in ids]
    return {'candidates': candidates, 'inputs': inputs, 'feedback': feedback,
            'reviews': reviews, 'selections': selections}


def _status(db, candidate_artifact):
    if db.execute('SELECT 1 FROM relay_agent_candidate_selections WHERE candidate_artifact=?',
                  (candidate_artifact,)).fetchone():
        return 'selected'
    review = db.execute('''SELECT decision FROM relay_agent_candidate_reviews
        WHERE candidate_artifact=?''', (candidate_artifact,)).fetchone()
    return ({'accept': 'accepted', 'revise': 'revision_requested'}[review['decision']]
            if review else 'verified_pending_review')


def main(argv=None):
    """Desktop-independent candidate submission and explicit decision commands."""
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    send = sub.add_parser('submit-native')
    send.add_argument('--database', required=True)
    send.add_argument('--handoff-id', required=True)
    send.add_argument('--submission-key', required=True)
    send.add_argument('--candidate', required=True)
    send.add_argument('--manifest', required=True)
    send.add_argument('--images-root')
    send.add_argument('--actor', required=True)
    check = sub.add_parser('verify')
    check.add_argument('--database', required=True)
    check.add_argument('--artifact', required=True)
    assess = sub.add_parser('review')
    assess.add_argument('--database', required=True)
    assess.add_argument('--artifact', required=True)
    assess.add_argument('--decision', choices=('accept', 'revise'), required=True)
    assess.add_argument('--reviewer', required=True)
    assess.add_argument('--note-file', required=True)
    assess.add_argument('--expected-sha256', required=True)
    assess.add_argument('--expected-plan-digest', required=True)
    observe = sub.add_parser('feedback')
    observe.add_argument('--database', required=True)
    observe.add_argument('--artifact', required=True)
    observe.add_argument('--feedback-key', required=True)
    observe.add_argument('--feedback-file', required=True)
    observe.add_argument('--actor', required=True)
    observe.add_argument('--assessment', choices=('looks_good', 'needs_changes'), required=True)
    observe.add_argument('--expected-sha256', required=True)
    observe.add_argument('--expected-plan-digest', required=True)
    choose = sub.add_parser('select')
    choose.add_argument('--database', required=True)
    choose.add_argument('--artifact', required=True)
    choose.add_argument('--selected-by', required=True)
    choose.add_argument('--receipt-file', required=True)
    choose.add_argument('--expected-sha256', required=True)
    choose.add_argument('--expected-plan-digest', required=True)
    args = parser.parse_args(argv)
    supplied = Path(args.database).expanduser()
    if not supplied.is_file() or supplied.is_symlink():
        parser.error('An existing non-symlink authoritative Relay database is required.')
    path = supplied.resolve()

    if args.action == 'verify':
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            row, candidate, handoff, checks = verified(db, args.artifact)
            result = {'schema': SCHEMA, 'version': VERSION, 'candidate_artifact': args.artifact,
                      'job': row['job'], 'handoff_id': handoff['id'],
                      'status': _status(db, args.artifact), 'checks': checks}
    else:
        from .bridge import State
        from . import production_control as pc, workflow_files
        from orchestrator.runtime import Runtime, safe_file
        state = State(path)
        try:
            if args.action == 'submit-native':
                manifest_file = Path(args.manifest).expanduser().absolute()
                safe_file(Path(manifest_file.anchor), str(manifest_file.relative_to(manifest_file.anchor)))
                manifest = pptx_edit.load(manifest_file.read_text(encoding='utf-8'))
                pptx_edit.validate(manifest)
                names = {edit['path'] for edit in manifest['edits']
                         if edit['kind'] == 'replace_image'}
                if names and not args.images_root:
                    parser.error('--images-root is required for declared picture inputs.')
                root = Path(args.images_root).expanduser().absolute() if args.images_root else None
                files = {name: root / name for name in names} if root else {}
                aid = submit(Runtime(pc.root(state), connection=state.db),
                    handoff_id=args.handoff_id, submission_key=args.submission_key,
                    candidate_path=args.candidate, manifest=manifest,
                    image_files=files, submitted_by=args.actor)
                row, candidate, handoff, checks = verified(state.db, aid)
                job = row['job']
                result = {'schema': SCHEMA, 'version': VERSION, 'candidate_artifact': aid,
                          'candidate_sha256': candidate['sha256'],
                          'plan_digest': handoff['plan_digest'],
                          'status': _status(state.db, aid), 'checks': checks}
            else:
                row = state.db.execute('SELECT job FROM relay_agent_candidates WHERE candidate_artifact=?',
                                       (args.artifact,)).fetchone()
                if row is None:
                    raise ValueError('Unknown agent candidate.')
                job = row['job']
                if args.action == 'feedback':
                    feedback_file = Path(args.feedback_file).expanduser().absolute()
                    safe_file(Path(feedback_file.anchor),
                              str(feedback_file.relative_to(feedback_file.anchor)))
                    ident = record_feedback(state.db, candidate_artifact=args.artifact,
                        feedback_key=args.feedback_key, actor=args.actor,
                        exact_feedback=feedback_file.read_text(encoding='utf-8'),
                        expected_sha256=args.expected_sha256,
                        expected_plan_digest=args.expected_plan_digest,
                        assessment=args.assessment)
                    result = {'schema': SCHEMA, 'version': VERSION,
                              'feedback_id': ident, 'candidate_artifact': args.artifact,
                              'scope': 'visual_layout', 'assessment': args.assessment,
                              'authorization': 'Feedback only; no acceptance or selection.'}
                elif args.action == 'review':
                    note_file = Path(args.note_file).expanduser().absolute()
                    safe_file(Path(note_file.anchor), str(note_file.relative_to(note_file.anchor)))
                    ident = review(state.db, candidate_artifact=args.artifact,
                        decision=args.decision, reviewer=args.reviewer,
                        note=note_file.read_text(encoding='utf-8'),
                        expected_sha256=args.expected_sha256,
                        expected_plan_digest=args.expected_plan_digest)
                    result = {'schema': SCHEMA, 'version': VERSION, 'review_id': ident,
                              'candidate_artifact': args.artifact, 'decision': args.decision}
                else:
                    receipt_file = Path(args.receipt_file).expanduser().absolute()
                    safe_file(Path(receipt_file.anchor), str(receipt_file.relative_to(receipt_file.anchor)))
                    select(state.db, candidate_artifact=args.artifact,
                        selected_by=args.selected_by,
                        receipt=receipt_file.read_text(encoding='utf-8'),
                        expected_sha256=args.expected_sha256,
                        expected_plan_digest=args.expected_plan_digest)
                    result = {'schema': SCHEMA, 'version': VERSION,
                              'candidate_artifact': args.artifact, 'selected': True}
            owner = state.db.execute('SELECT channel FROM relay_pipelines WHERE id=?',
                                     (job,)).fetchone()
            if owner is None:
                raise ValueError('Candidate job is missing.')
            state.channel = owner['channel']
            view = workflow_files.sync(state, job)
            result['job_view'] = str(view / '.relay/job.sqlite')
        finally:
            state.db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
