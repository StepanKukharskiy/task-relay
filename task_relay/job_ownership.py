"""Exact links from a pipeline media stage to its separate agent task.

The pipeline owns its stage and backend job. The watched task is a separate
conversation, even when Relay created it for this stage. These links record the
relationship without by itself granting deletion of that conversation or shared
channel history. Deletion separately proves that the task has one owner and no
other work before removing its Relay-local records.
"""

import time
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from orchestrator.storage import transaction
from .relay_paths import PATHS


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_pipeline_task_links(
        pipeline TEXT NOT NULL, step TEXT NOT NULL, request_id INTEGER NOT NULL,
        backend_job_id TEXT NOT NULL, task_id TEXT NOT NULL,
        task_scope TEXT NOT NULL CHECK(task_scope='separate_conversation'),
        origin TEXT NOT NULL, recorded REAL NOT NULL,
        PRIMARY KEY(pipeline,step), UNIQUE(backend_job_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS relay_standalone_jobs(
        id TEXT PRIMARY KEY, root_plan TEXT NOT NULL UNIQUE,
        request_id INTEGER NOT NULL, request_sha256 TEXT NOT NULL,
        channel TEXT NOT NULL, last_run TEXT NOT NULL,
        created REAL NOT NULL, updated REAL NOT NULL)''')


def standalone_id(root_plan):
    return 'job-' + hashlib.sha256(root_plan.encode()).hexdigest()[:24]


def record_standalone(db, root_plan, run, channel):
    """Bind a run to its exact root plan inside the caller's commit.

    Registration establishes ownership only; it does not select or accept results.
    """
    if not db.in_transaction:
        raise ValueError('Standalone ownership requires an outer transaction.')
    initialize(db)
    root = db.execute('SELECT id,request_id,request,parent_id,channel FROM production_plans WHERE id=?',
                      (root_plan,)).fetchone()
    if not root or root['parent_id'] is not None or root['channel'] != channel:
        raise ValueError('Standalone root plan is missing or changed.')
    if not db.execute('SELECT 1 FROM production_runs WHERE id=?', (run,)).fetchone():
        raise ValueError('Standalone result run is missing.')
    from .result_handoff import ancestry
    actual_root, runs, plans = ancestry(SimpleNamespace(db=db, channel=channel), run)
    if actual_root != root_plan:
        raise ValueError('Standalone result has different plan ancestry.')
    if any(db.execute('SELECT 1 FROM relay_pipeline_steps WHERE target_kind=? AND target=?',
                      (kind, ident)).fetchone() for kind, values in
           (('plan_production', plans), ('production_run', runs)) for ident in values):
        raise ValueError('A saved pipeline owns this production plan.')
    ident = standalone_id(root_plan)
    if db.execute('SELECT 1 FROM relay_pipelines WHERE id=?', (ident,)).fetchone():
        raise ValueError('Standalone job identity collides with a saved pipeline.')
    request_hash = hashlib.sha256(root['request'].encode()).hexdigest()
    prior = db.execute('SELECT * FROM relay_standalone_jobs WHERE id=?', (ident,)).fetchone()
    identity = (root_plan, root['request_id'], request_hash, channel)
    if prior and tuple(prior[k] for k in ('root_plan','request_id','request_sha256','channel')) != identity:
        raise ValueError('Standalone job ownership changed; inspect the saved record.')
    now = time.time()
    if prior and prior['last_run'] != run:
        db.execute('UPDATE relay_standalone_jobs SET last_run=?,updated=? WHERE id=?',
                   (run, now, ident))
    elif not prior:
        db.execute('INSERT INTO relay_standalone_jobs VALUES (?,?,?,?,?,?,?,?)',
                   (ident, *identity, run, now, now))
    return ident


def standalone_candidate(db, run, paths=PATHS):
    """Read-only discovery of a selected historical result with exact ancestry."""
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_standalone_jobs'").fetchone()
    prior = (db.execute('SELECT id FROM relay_standalone_jobs WHERE last_run=?',
                        (run,)).fetchone() if present else None)
    if prior:
        return {'id': prior['id'], 'registration_needed': False}
    from .result_handoff import ancestry, channel_for
    channel = channel_for(SimpleNamespace(db=db), run)
    try:
        root, runs, plans = ancestry(SimpleNamespace(db=db, channel=channel), run)
    except (ValueError, KeyError, TypeError):
        return None
    if root not in plans or not db.execute('SELECT 1 FROM production_decisions WHERE run=?',
                                           (run,)).fetchone():
        return None
    if not db.execute('SELECT 1 FROM outbox WHERE id=? AND sent=1',
                      ('production:' + run + ':files-ready',)).fetchone():
        return None
    if any(db.execute('SELECT 1 FROM relay_pipeline_steps WHERE target_kind=? AND target=?',
                      (kind, ident)).fetchone() for kind, values in
           (('plan_production', plans), ('production_run', runs)) for ident in values):
        return None
    ident = standalone_id(root)
    folder = paths.generated / 'workflows' / ident
    marker, view = folder / '.relay-workflow.json', folder / '.relay' / 'job.sqlite'
    if (folder.parent.is_symlink() or folder.is_symlink() or
            (folder / '.relay').is_symlink() or marker.is_symlink() or view.is_symlink() or
            not marker.is_file() or (view.exists() and not view.is_file()) or
            marker.stat().st_size > 65536):
        return None
    try:
        if json.loads(marker.read_text()).get('workflow') != ident:
            return None
    except (ValueError, OSError, TypeError):
        return None
    return {'id': ident, 'registration_needed': True, 'root_plan': root,
            'channel': channel}


def backfill_standalone(run, paths=PATHS):
    """Explicitly register a historical selected result before Delete preview."""
    if not paths.state.is_file():
        raise ValueError('No Relay job history exists.')
    db = sqlite3.connect(str(paths.state), timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with transaction(db):
            initialize(db)
            candidate = standalone_candidate(db, run, paths)
            if not candidate:
                raise ValueError('No exact selected standalone result is available for ownership review.')
            if candidate['registration_needed']:
                record_standalone(db, candidate['root_plan'], run, candidate['channel'])
            return candidate['id']
    finally:
        db.close()


def record_media_link(db, request_id, backend_job_id, task_id, *, origin='dispatch'):
    """Record only an exact, committed-stage/request/job/task chain.

    Called inside the media enqueue transaction. Legacy repair must pass
    ``verified_legacy`` and is deliberately an explicit operation.
    """
    if not db.in_transaction:
        raise ValueError('Media ownership link requires an outer transaction.')
    if origin not in ('dispatch', 'verified_legacy'):
        raise ValueError('Unsupported media ownership evidence.')
    stage = db.execute('''SELECT s.pipeline,s.id,s.request_id,s.target_kind,s.target
        FROM relay_pipeline_requests r JOIN relay_pipeline_steps s
        ON s.pipeline=r.pipeline AND s.id=r.step AND s.request_id=r.request_id
        WHERE r.request_id=?''', (request_id,)).fetchone()
    if stage is None:
        return None  # An independent media request is not a pipeline stage.
    image = db.execute('''SELECT task_id,backend_job_id FROM orchestrator_image_requests
        WHERE job_id=?''', (request_id,)).fetchone()
    job = db.execute('SELECT thread_id FROM backend_jobs WHERE id=?', (backend_job_id,)).fetchone()
    if (image is None or job is None or image['task_id'] != task_id or
            image['backend_job_id'] != backend_job_id or job['thread_id'] != task_id or
            stage['target_kind'] not in (None, 'generate_image') or
            (stage['target'] and (stage['target_kind'] != 'generate_image' or stage['target'] != backend_job_id))):
        raise ValueError('Media stage, request, backend job and task disagree.')
    existing = db.execute('SELECT * FROM relay_pipeline_task_links WHERE pipeline=? AND step=?',
                          (stage['pipeline'], stage['id'])).fetchone()
    values = (stage['pipeline'], stage['id'], request_id, backend_job_id, task_id)
    if existing:
        if tuple(existing[key] for key in ('pipeline','step','request_id','backend_job_id','task_id')) != values:
            raise ValueError('Media stage ownership changed; inspect the existing link.')
        return dict(existing)
    db.execute('''INSERT INTO relay_pipeline_task_links VALUES (?,?,?,?,?,?,?,?)''',
               (*values, 'separate_conversation', origin, time.time()))
    return dict(db.execute('SELECT * FROM relay_pipeline_task_links WHERE pipeline=? AND step=?',
                           (stage['pipeline'], stage['id'])).fetchone())


def backfill_verified_media_links(db, pipeline):
    """Record exact legacy chains; leave incomplete or ambiguous stages untouched."""
    if not db.in_transaction:
        raise ValueError('Legacy ownership backfill requires an outer transaction.')
    result = []
    for stage in db.execute('''SELECT request_id,target FROM relay_pipeline_steps
        WHERE pipeline=? AND target_kind='generate_image' ORDER BY position''', (pipeline,)):
        if stage['request_id'] is None or not stage['target']:
            continue
        job = db.execute('SELECT thread_id FROM backend_jobs WHERE id=?', (stage['target'],)).fetchone()
        if job:
            result.append(record_media_link(db, stage['request_id'], stage['target'],
                                            job['thread_id'], origin='verified_legacy'))
    return [row for row in result if row is not None]
