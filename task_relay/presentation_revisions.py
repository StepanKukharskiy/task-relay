"""Bounded reviewed XLSX-fact to PPTX-text revision pilot.

Only explicitly linked text runs are assessed. The registered PPTX is never
overwritten, and planning never starts an edit or records a decision.
"""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import uuid

from orchestrator import pptx_edit
from orchestrator.storage import transaction
from . import fact_revisions as facts


KIND = 'presentation_text'


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_presentation_links(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, entity_key TEXT NOT NULL,
        predicate TEXT NOT NULL, value TEXT NOT NULL, source_artifact TEXT NOT NULL,
        source_sha256 TEXT NOT NULL, source_sheet TEXT NOT NULL,
        source_key_column TEXT NOT NULL, source_cell TEXT NOT NULL,
        evidence TEXT NOT NULL, review_state TEXT NOT NULL, reviewer TEXT NOT NULL,
        output_artifact TEXT NOT NULL, output_sha256 TEXT NOT NULL,
        slide INTEGER NOT NULL, shape_id INTEGER NOT NULL, created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_presentation_coverage(
        job TEXT NOT NULL, output_artifact TEXT NOT NULL, slide INTEGER NOT NULL,
        shape_id INTEGER NOT NULL, state TEXT NOT NULL, note TEXT NOT NULL,
        PRIMARY KEY(job,output_artifact,slide,shape_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_presentation_revisions(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, baseline_artifact TEXT NOT NULL,
        candidate_artifact TEXT NOT NULL UNIQUE, old_source TEXT NOT NULL,
        replacement_source TEXT NOT NULL, plan_digest TEXT NOT NULL,
        edits TEXT NOT NULL, reviewer TEXT NOT NULL, created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_presentation_reviews(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, candidate_artifact TEXT NOT NULL UNIQUE,
        candidate_sha256 TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL,
        note TEXT NOT NULL, checks TEXT NOT NULL, created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_presentation_selections(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, candidate_artifact TEXT NOT NULL UNIQUE,
        candidate_sha256 TEXT NOT NULL, baseline_artifact TEXT NOT NULL,
        selected_by TEXT NOT NULL, receipt TEXT NOT NULL, created REAL NOT NULL)''')


def _deck(db, ident):
    row = db.execute('SELECT * FROM production_artifacts WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Unknown registered PPTX artifact.')
    row = dict(row)
    path = Path(row['blob'])
    if (not row['path'].lower().endswith('.pptx') or not path.is_file()
            or path.is_symlink() or path.stat().st_size != row['bytes']
            or row['bytes'] > 50_000_000
            or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']):
        raise ValueError('Registered PPTX is missing, changed or unsupported.')
    return row


def location(slide, shape_id):
    if type(slide) is not int or type(shape_id) is not int or not 1 <= slide <= 500 or not 1 <= shape_id <= 1000000:
        raise ValueError('Exact slide and shape ID are required.')
    return f'Slide {slide} / shape {shape_id}'


def _shape(listing, slide, shape_id):
    try:
        matches = [s for s in listing['slides'][slide-1]['shapes'] if s['shape_id'] == shape_id]
    except IndexError:
        matches = []
    if len(matches) != 1:
        raise ValueError('PPTX shape is missing or ambiguous.')
    return matches[0]


def record_link(db, *, job, entity_key, predicate, value, source_artifact,
                source_sheet, source_key_column, source_cell, evidence,
                output_artifact, slide, shape_id, reviewer, review_state='reviewed'):
    facts._location(source_sheet, source_cell)
    location(slide, shape_id)
    if (not all(isinstance(v, str) and v.strip() for v in
                (job, entity_key, predicate, value, evidence, reviewer))
            or review_state not in ('reviewed', 'pending')
            or not facts.COLUMN.fullmatch(source_key_column)):
        raise ValueError('Explicit fact, evidence and review state are required.')
    if db.execute('SELECT 1 FROM relay_pipelines WHERE id=?', (job,)).fetchone() is None:
        raise ValueError('Unknown job.')
    source, output = facts._artifact(db, source_artifact), _deck(db, output_artifact)
    with closing(facts._plain_xlsx(source['blob'])) as book:
        rows = facts._matching_rows(book, source_sheet, source_key_column, entity_key)
        if rows != [book[source_sheet][source_cell].row] or facts._value(book, source_sheet, source_cell) != value:
            raise ValueError('Source key or exact fact does not match the reviewed link.')
    shape = _shape(pptx_edit.inspect(Path(output['blob']).read_bytes()), slide, shape_id)
    if shape['text_runs'].count(value) != 1:
        raise ValueError('Exact PPTX text run is missing or ambiguous.')
    ident = uuid.uuid4().hex
    with transaction(db):
        db.execute('''INSERT INTO relay_presentation_links VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ident, job, entity_key, predicate, json.dumps(value), source_artifact,
             source['sha256'], source_sheet, source_key_column, source_cell,
             evidence, review_state, reviewer, output_artifact, output['sha256'],
             slide, shape_id, time.time()))
    return ident


def record_coverage(db, *, job, output_artifact, slide, shape_id, state, note):
    location(slide, shape_id)
    _deck(db, output_artifact)
    if state not in ('complete', 'incomplete') or not isinstance(note, str) or not note.strip():
        raise ValueError('Coverage needs a state and reason.')
    links = [dict(r) for r in db.execute('''SELECT * FROM relay_presentation_links
        WHERE job=? AND output_artifact=? AND slide=? AND shape_id=?''',
        (job, output_artifact, slide, shape_id))]
    if state == 'complete' and (len(links) != 1 or links[0]['review_state'] != 'reviewed'):
        raise ValueError('Complete slide coverage requires one reviewed link.')
    with transaction(db):
        db.execute('''INSERT INTO relay_presentation_coverage VALUES (?,?,?,?,?,?)
            ON CONFLICT(job,output_artifact,slide,shape_id)
            DO UPDATE SET state=excluded.state,note=excluded.note''',
            (job, output_artifact, slide, shape_id, state, note))


def records(db, job):
    return {
        'links': [dict(r) for r in db.execute('SELECT * FROM relay_presentation_links WHERE job=? ORDER BY created,id', (job,))],
        'coverage': [dict(r) for r in db.execute('SELECT * FROM relay_presentation_coverage WHERE job=? ORDER BY output_artifact,slide,shape_id', (job,))],
        'revisions': [dict(r) for r in db.execute('SELECT * FROM relay_presentation_revisions WHERE job=? ORDER BY created,id', (job,))],
        'reviews': [dict(r) for r in db.execute('SELECT * FROM relay_presentation_reviews WHERE job=? ORDER BY created,id', (job,))],
        'selections': [dict(r) for r in db.execute('SELECT * FROM relay_presentation_selections WHERE job=? ORDER BY rowid', (job,))],
    }


def plan_impact(db, *, job, old_source, replacement_source, baseline_artifact):
    if old_source == replacement_source:
        raise ValueError('Replacement needs a distinct artifact version.')
    old, replacement = facts._artifact(db, old_source), facts._artifact(db, replacement_source)
    baseline = _deck(db, baseline_artifact)
    rows = records(db, job)
    covered = [c for c in rows['coverage'] if c['output_artifact'] == baseline_artifact]
    if not covered:
        raise ValueError('No declared PPTX output coverage.')
    if not any(b['output_artifact'] == baseline_artifact and
               b['source_artifact'] == old_source for b in rows['links']):
        raise ValueError('Original source has no reviewed link to this deck.')
    listing = pptx_edit.inspect(Path(baseline['blob']).read_bytes())
    affected, unaffected, unknown = [], [], []
    with closing(facts._plain_xlsx(old['blob'])) as before, closing(facts._plain_xlsx(replacement['blob'])) as after:
        for c in covered:
            loc = location(c['slide'], c['shape_id'])
            item = {'location': loc, 'output_artifact': baseline_artifact}
            links = [b for b in rows['links'] if b['output_artifact'] == baseline_artifact
                     and b['slide'] == c['slide'] and b['shape_id'] == c['shape_id']]
            if c['state'] != 'complete' or len(links) != 1 or links[0]['review_state'] != 'reviewed':
                unknown.append({**item, 'reason': 'Incomplete reviewed coverage: ' + c['note']})
                continue
            b = links[0]
            try:
                source = facts._artifact(db, b['source_artifact'])
                if source['sha256'] != b['source_sha256'] or baseline['sha256'] != b['output_sha256']:
                    raise ValueError('Recorded artifact hash changed.')
                value = json.loads(b['value'])
                if _shape(listing, c['slide'], c['shape_id'])['text_runs'].count(value) != 1:
                    raise ValueError('Baseline text run no longer matches reviewed fact.')
                if b['source_artifact'] == old_source:
                    column = re.match(r'[A-Z]+', b['source_cell']).group()
                    if (facts._value(before, b['source_sheet'], column + '1') !=
                            facts._value(after, b['source_sheet'], column + '1') or
                            facts._value(before, b['source_sheet'], b['source_key_column'] + '1') !=
                            facts._value(after, b['source_sheet'], b['source_key_column'] + '1')):
                        raise ValueError('Replacement source columns changed.')
                    matches = facts._matching_rows(after, b['source_sheet'], b['source_key_column'], b['entity_key'])
                    if len(matches) != 1:
                        raise ValueError('Replacement entity key is missing or ambiguous.')
                    new = facts._value(after, b['source_sheet'], column + str(matches[0]))
                    if not isinstance(new, str) or not new.strip():
                        raise ValueError('Replacement fact is missing or unsupported.')
                    if new != value:
                        affected.append({**item, 'before': value, 'after': new,
                                         'reason': 'Reviewed source fact changed.'})
                    else:
                        unaffected.append({**item, 'reason': 'Complete reviewed link remains valid.'})
                else:
                    with closing(facts._plain_xlsx(source['blob'])) as independent:
                        if facts._value(independent, b['source_sheet'], b['source_cell']) != value:
                            raise ValueError('Independent source no longer matches reviewed fact.')
                    unaffected.append({**item, 'reason': 'Independent reviewed source remains valid.'})
            except (ValueError, OSError, KeyError, IndexError) as exc:
                unknown.append({**item, 'reason': str(exc)})
    plan = {'schema': 'task-relay.presentation-impact', 'version': 1, 'job': job,
        'old_source': old_source, 'replacement_source': replacement_source,
        'baseline_artifact': baseline_artifact, 'source_sha256': old['sha256'],
        'replacement_sha256': replacement['sha256'], 'baseline_sha256': baseline['sha256'],
        'affected': affected, 'unaffected': unaffected, 'unknown': unknown,
        'coverage_scope': 'Declared PPTX text runs only; other deck content is unassessed.',
        'authorization': 'Planning only; no edit, selection or dispatch.'}
    plan['digest'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    from . import reviewed_links
    plan['reviewed_impact'] = reviewed_links.impact_record(reviewed_links.records(db, job),
        kind=KIND, plan=plan, source_sha256=old['sha256'],
        replacement_sha256=replacement['sha256'])
    return plan


def _edits(plan):
    edits = []
    for item in plan['affected']:
        match = re.fullmatch(r'Slide ([1-9][0-9]*) / shape ([1-9][0-9]*)', item['location'])
        if match is None:
            raise ValueError('Invalid affected PPTX location.')
        edits.append({'kind': 'replace_text', 'slide': int(match[1]),
                      'shape_id': int(match[2]), 'old': item['before'], 'new': item['after']})
    if not edits:
        raise ValueError('No reviewed affected PPTX text runs to revise.')
    return edits


def revise_pptx(rt, *, plan, reviewer):
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError('An explicit candidate author is required.')
    fresh = plan_impact(rt.db, job=plan['job'], old_source=plan['old_source'],
        replacement_source=plan['replacement_source'], baseline_artifact=plan['baseline_artifact'])
    if fresh != plan:
        raise ValueError('Impact plan is stale.')
    baseline = _deck(rt.db, plan['baseline_artifact'])
    edits = _edits(plan)
    raw, checks = pptx_edit.edit(Path(baseline['blob']).read_bytes(),
        {'version': 1, 'source_sha256': baseline['sha256'], 'edits': edits})
    with tempfile.TemporaryDirectory(dir=rt.root) as folder:
        path = Path(folder) / 'candidate.pptx'
        path.write_bytes(raw)
        with transaction(rt.db):
            locked = plan_impact(rt.db, job=plan['job'], old_source=plan['old_source'],
                replacement_source=plan['replacement_source'], baseline_artifact=plan['baseline_artifact'])
            if locked != plan:
                raise ValueError('Impact plan changed before candidate registration.')
            aid = rt.register(path, 'O14 reviewed PPTX text revision candidate',
                task='presentation_revision', path='delivery/revised_deck.pptx')
            rt.db.execute('''INSERT INTO relay_presentation_revisions VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (uuid.uuid4().hex, plan['job'], plan['baseline_artifact'], aid,
                 plan['old_source'], plan['replacement_source'], plan['digest'],
                 json.dumps(edits, sort_keys=True), reviewer, time.time()))
            from . import reviewed_links
            reviewed_links.save_impact(rt.db, candidate_artifact=aid, plan=plan)
    return aid


def verified_candidate(db, candidate_artifact):
    row = db.execute('SELECT * FROM relay_presentation_revisions WHERE candidate_artifact=?',
                     (candidate_artifact,)).fetchone()
    if row is None:
        raise ValueError('Unknown PPTX revision candidate.')
    revision = dict(row)
    candidate, baseline = _deck(db, candidate_artifact), _deck(db, revision['baseline_artifact'])
    plan = plan_impact(db, job=revision['job'], old_source=revision['old_source'],
        replacement_source=revision['replacement_source'], baseline_artifact=revision['baseline_artifact'])
    if plan['digest'] != revision['plan_digest'] or json.loads(revision['edits']) != _edits(plan):
        raise ValueError('PPTX candidate plan is stale or edits changed.')
    from . import reviewed_links
    reviewed_links.verify_saved_impact(db, candidate_artifact=candidate_artifact, plan=plan)
    expected, native = pptx_edit.edit(Path(baseline['blob']).read_bytes(),
        {'version': 1, 'source_sha256': baseline['sha256'], 'edits': _edits(plan)})
    if expected != Path(candidate['blob']).read_bytes():
        raise ValueError('PPTX candidate differs from exact validated edit.')
    checks = {'baseline_sha256': baseline['sha256'], 'candidate_sha256': candidate['sha256'],
        'plan_digest': plan['digest'], 'changed_locations': [a['location'] for a in plan['affected']],
        'untouched_package_parts_verified': native['untouched_parts_preserved'],
        'changed_slides': native['changed_slides'], 'visual_review': native['visual_review']}
    return revision, candidate, plan, checks


def review_candidate(db, *, candidate_artifact, decision, reviewer, note):
    if decision not in ('accept', 'revise') or not all(isinstance(v, str) and v.strip() for v in (reviewer, note)):
        raise ValueError('Independent reviewer, decision and note are required.')
    revision, candidate, _, checks = verified_candidate(db, candidate_artifact)
    if reviewer == revision['reviewer']:
        raise ValueError('Candidate review must be independent.')
    ident = uuid.uuid4().hex
    with transaction(db):
        if db.execute('SELECT 1 FROM relay_presentation_reviews WHERE candidate_artifact=?',
                      (candidate_artifact,)).fetchone():
            raise ValueError('Candidate already reviewed.')
        db.execute('INSERT INTO relay_presentation_reviews VALUES (?,?,?,?,?,?,?,?,?)',
            (ident, revision['job'], candidate_artifact, candidate['sha256'],
             decision, reviewer, note, json.dumps(checks, sort_keys=True), time.time()))
    return ident


def select_candidate(db, *, candidate_artifact, selected_by, receipt):
    if not all(isinstance(v, str) and v.strip() for v in (selected_by, receipt)):
        raise ValueError('Explicit actor and selection receipt are required.')
    revision, candidate, _, _ = verified_candidate(db, candidate_artifact)
    review = db.execute('SELECT * FROM relay_presentation_reviews WHERE candidate_artifact=?',
                        (candidate_artifact,)).fetchone()
    if review is None or review['decision'] != 'accept' or review['candidate_sha256'] != candidate['sha256']:
        raise ValueError('Select only the exact independently accepted candidate.')
    ident = uuid.uuid4().hex
    with transaction(db):
        if db.execute('SELECT 1 FROM relay_presentation_selections WHERE candidate_artifact=?',
                      (candidate_artifact,)).fetchone():
            raise ValueError('Candidate already selected.')
        db.execute('INSERT INTO relay_presentation_selections VALUES (?,?,?,?,?,?,?,?)',
            (ident, revision['job'], candidate_artifact, candidate['sha256'],
             revision['baseline_artifact'], selected_by, receipt, time.time()))
    return ident
