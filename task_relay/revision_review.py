"""One desktop review contract over typed, explicitly linked revision adapters.

Adapters own impact semantics and file checks. This surface never infers a link,
accepts a candidate, or selects a result from a read-only preview.
"""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from orchestrator.storage import transaction
from . import fact_revisions as facts, translation_revisions as translations
from . import presentation_revisions as presentations
from .desktop_tasks import _database
from .relay_paths import PATHS


ADAPTERS = {
    'material_cell': (facts, 'relay_fact_revisions', 'relay_fact_candidate_reviews',
                      'relay_fact_selections'),
    'parts_translation': (translations, 'relay_translation_revisions',
                          'relay_translation_reviews', 'relay_translation_selections'),
    'presentation_text': (presentations, 'relay_presentation_revisions',
                          'relay_presentation_reviews', 'relay_presentation_selections'),
}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_revision_action_receipts(
        request_id TEXT PRIMARY KEY, candidate_artifact TEXT NOT NULL,
        verb TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
        expected_sha256 TEXT NOT NULL, expected_plan_digest TEXT NOT NULL,
        result_id TEXT NOT NULL, created REAL NOT NULL)''')


def _table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (name,)).fetchone() is not None


def _owner(db, candidate_artifact):
    if not isinstance(candidate_artifact, str) or len(candidate_artifact) > 100:
        raise ValueError('Choose an exact revision candidate.')
    for kind, (adapter, table, reviews, selections) in ADAPTERS.items():
        if _table(db, table):
            row = db.execute('SELECT * FROM ' + table + ' WHERE candidate_artifact=?',
                             (candidate_artifact,)).fetchone()
            if row is not None:
                return kind, adapter, dict(row), reviews, selections
    raise ValueError('Unknown revision candidate.')


def _copy_path(paths, job, candidate_artifact, sha256):
    if not isinstance(job, str) or len(job) > 80:
        return None
    folder = paths.generated / 'workflows' / job
    manifest = folder / 'manifest.json'
    try:
        saved = json.loads(manifest.read_text())
        artifact = next(a for a in saved['artifacts'] if a['id'] == candidate_artifact)
        relative = Path(artifact['copy_path'])
        if (relative.is_absolute() or '..' in relative.parts
                or artifact['sha256'] != sha256
                or artifact['copy_status'] not in ('copied', 'present')):
            return None
        path = folder / relative
        if (not path.is_file() or folder.is_symlink() or path.is_symlink()
                or not path.resolve().is_relative_to(folder.resolve())
                or any(folder.joinpath(*relative.parts[:index]).is_symlink()
                       for index in range(1, len(relative.parts)))
                or hashlib.sha256(path.read_bytes()).hexdigest() != sha256):
            return None
        return str(path)
    except (OSError, ValueError, KeyError, StopIteration, TypeError):
        return None


def _evidence_links(db, kind, job, baseline_artifact):
    """Render the shared committed link contract for either typed adapter."""
    from . import reviewed_links
    links = [link for link in reviewed_links.records(db, job)['links']
             if link['kind'] == kind and link['output']['artifact'] == baseline_artifact]
    if len(links) > 200:
        raise ValueError('Revision review exceeds 200 evidence links; narrow the candidate.')
    output = []
    for link in links:
        source = link['source']['locator']
        source_location = (('Yamaha TXT row ' + str(source['row']) + ' · name field')
                           if source['type'] == 'txt_field' else reviewed_links.location(source))
        output.append({'kind': kind, 'source_artifact': link['source']['artifact'],
            'source_sha256': link['source']['sha256'],
            'source_location': source_location,
            'output_artifact': link['output']['artifact'],
            'output_sha256': link['output']['sha256'],
            'output_location': reviewed_links.location(link['output']['locator']),
            'fact': ('Russian part name' if kind == 'parts_translation' else link['predicate']),
            'evidence': link['evidence'].get('reference'),
            'evidence_url': link['evidence'].get('url'),
            'evidence_locator': link['evidence'].get('locator'),
            'review_state': link['review']['state']})
    return output


def _detail(db, candidate_artifact, paths):
    kind, adapter, revision, reviews_table, selections_table = _owner(db, candidate_artifact)
    candidate = db.execute('SELECT sha256,path FROM production_artifacts WHERE id=?',
                           (candidate_artifact,)).fetchone()
    if candidate is None:
        raise ValueError('Candidate artifact is missing.')
    decisions_ready = all(_table(db, name) for name in
                          (reviews_table, selections_table, 'relay_revision_action_receipts'))
    review = (db.execute('SELECT * FROM ' + reviews_table + ' WHERE candidate_artifact=?',
                         (candidate_artifact,)).fetchone() if decisions_ready else None)
    selection = (db.execute('SELECT * FROM ' + selections_table + ' WHERE candidate_artifact=?',
                            (candidate_artifact,)).fetchone() if decisions_ready else None)
    try:
        if kind == 'material_cell':
            _, checked_candidate, checks = adapter._verified_candidate(db, candidate_artifact)
            plan = adapter.plan_impact(db, job=revision['job'],
                old_source=revision['old_source'],
                replacement_source=revision['replacement_source'],
                baseline_artifact=revision['baseline_artifact'])
        else:
            _, checked_candidate, plan, checks = adapter.verified_candidate(db, candidate_artifact)
        verified = True
        error = None
        links = _evidence_links(db, kind, revision['job'], revision['baseline_artifact'])
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        verified = False
        error = str(exc)
        checked_candidate = None
        checks = None
        plan = None
        links = []
    title_row = db.execute('SELECT title FROM relay_pipelines WHERE id=?',
                           (revision['job'],)).fetchone()
    return {
        'kind': kind, 'candidate_artifact': candidate_artifact,
        'job': revision['job'], 'title': title_row['title'] if title_row else revision['job'],
        'candidate_sha256': candidate['sha256'],
        'candidate_path': _copy_path(paths, revision['job'], candidate_artifact,
                                     candidate['sha256']) if verified else None,
        'baseline_artifact': revision['baseline_artifact'],
        'old_source': revision['old_source'],
        'replacement_source': revision['replacement_source'],
        'verified': verified, 'error': error, 'plan': plan, 'checks': checks,
        'evidence_links': links,
        'review': dict(review) if review else None,
        'selection': dict(selection) if selection else None,
        'decision_blocker': None if decisions_ready else 'Restart Relay to enable revision decisions.',
        'can_review': verified and decisions_ready and review is None,
        'can_select': verified and decisions_ready and selection is None and review is not None
                      and review['decision'] == 'accept'
                      and review['candidate_sha256'] == candidate['sha256'],
    }


def candidates(paths=PATHS):
    if not paths.state.is_file():
        return {'items': []}
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        rows = []
        for kind, (_, table, reviews, selections) in ADAPTERS.items():
            if not _table(db, table):
                continue
            decisions_ready = all(_table(db, name) for name in
                                  (reviews, selections, 'relay_revision_action_receipts'))
            for row in db.execute('SELECT job,candidate_artifact,created FROM '
                                  + table + ' ORDER BY created DESC LIMIT 40'):
                review = (db.execute('SELECT decision FROM ' + reviews
                                     + ' WHERE candidate_artifact=?',
                                     (row['candidate_artifact'],)).fetchone()
                          if decisions_ready else None)
                selection = (db.execute('SELECT 1 FROM ' + selections
                                        + ' WHERE candidate_artifact=?',
                                        (row['candidate_artifact'],)).fetchone()
                             if decisions_ready else None)
                rows.append({'kind': kind, 'job': row['job'],
                             'candidate_artifact': row['candidate_artifact'],
                             'created': row['created'],
                             'status': 'requires_restart' if not decisions_ready else
                                       'selected' if selection else
                                       review['decision'] if review else 'awaiting_review'})
        rows.sort(key=lambda row: row['created'], reverse=True)
        return {'items': rows[:40]}


def detail(candidate_artifact, paths=PATHS):
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        return _detail(db, candidate_artifact, paths)


def decide(*, candidate_artifact, verb, actor, note, expected_sha256,
           expected_plan_digest, request_id, paths=PATHS):
    if verb not in ('accept', 'revise', 'select'):
        raise ValueError('Choose accept, revise or select.')
    if not all(isinstance(value, str) and value.strip() for value in
               (actor, expected_sha256, expected_plan_digest, request_id)):
        raise ValueError('Actor, exact version and request identity are required.')
    if not isinstance(note, str) or (verb != 'select' and not note.strip()):
        raise ValueError('Give a review reason.')
    if len(actor) > 120 or len(note) > 2000:
        raise ValueError('Review actor or note exceeds the bounded field.')
    try:
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Use a valid decision request identity.') from None
    with closing(_database(paths, writable=True)) as db:
        with transaction(db):
            if not _table(db, 'relay_revision_action_receipts'):
                raise ValueError('Restart Relay to enable revision decisions.')
            prior = db.execute('SELECT * FROM relay_revision_action_receipts WHERE request_id=?',
                               (request_id,)).fetchone()
            values = (candidate_artifact, verb, actor.strip(), note.strip(),
                      expected_sha256, expected_plan_digest)
            if prior:
                if tuple(prior[key] for key in ('candidate_artifact', 'verb', 'actor', 'note',
                    'expected_sha256', 'expected_plan_digest')) != values:
                    raise ValueError('That decision identity belongs to different content.')
                result_id = prior['result_id']
            else:
                view = _detail(db, candidate_artifact, paths)
                if (not view['verified'] or view['candidate_sha256'] != expected_sha256
                        or view['plan']['digest'] != expected_plan_digest):
                    raise ValueError('Candidate or impact plan changed; refresh before deciding.')
                _, adapter, _, _, _ = _owner(db, candidate_artifact)
                if verb in ('accept', 'revise'):
                    if not view['can_review']:
                        raise ValueError('This candidate already has a review.')
                    result_id = adapter.review_candidate(db, candidate_artifact=candidate_artifact,
                        decision=verb, reviewer=actor.strip(), note=note.strip())
                else:
                    if not view['can_select']:
                        raise ValueError('Only an accepted exact candidate can be selected.')
                    receipt = ('Desktop exact-version selection ' + request_id +
                               '; candidate SHA-256 ' + expected_sha256)
                    result_id = adapter.select_candidate(db, candidate_artifact=candidate_artifact,
                        selected_by=actor.strip(), receipt=receipt)
                db.execute('''INSERT INTO relay_revision_action_receipts VALUES (?,?,?,?,?,?,?,?,?)''',
                           (request_id, candidate_artifact, verb, actor.strip(), note.strip(),
                            expected_sha256, expected_plan_digest, result_id, time.time()))
            job = _owner(db, candidate_artifact)[2]['job']
    warning = None
    try:
        from .bridge import State
        from . import workflow_files
        state = State(paths.state)
        try:
            workflow_files.sync(state, job)
        finally:
            state.db.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        warning = 'Decision recorded, but workflow files could not be refreshed: ' + str(exc)
    return {'request_id': request_id, 'result_id': result_id,
            'detail': detail(candidate_artifact, paths), 'warning': warning}
