"""Permanent deletion of one proven Relay job ownership graph.

The database is authoritative. A small tombstone survives solely to retry private
view and provider-trace cleanup after a crash; native artifacts and external
project files are kept.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time

from orchestrator.storage import transaction
from .relay_paths import PATHS


class JobDeleteError(ValueError):
    pass


def _database(paths=PATHS, writable=False):
    if not paths.state.is_file(): raise JobDeleteError('No Relay job history exists.')
    target = str(paths.state) if writable else paths.state.as_uri() + '?mode=ro'
    db = sqlite3.connect(target, uri=not writable, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    return db


def _table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _ids(db, table, column, values):
    if not values or not _table(db, table):
        return []
    marks = ','.join('?' for _ in values)
    table_name = '"' + table.replace('"', '""') + '"'
    column_name = '"' + column.replace('"', '""') + '"'
    return list(db.execute(f'SELECT rowid AS _delete_rowid,* FROM {table_name} WHERE {column_name} IN ({marks}) ORDER BY rowid', tuple(sorted(values))))


def _prepare(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_delete_receipts(
        id TEXT PRIMARY KEY, digest TEXT NOT NULL, status TEXT NOT NULL,
        created REAL NOT NULL, error TEXT, files TEXT NOT NULL DEFAULT '[]',
        shared_history TEXT)''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(relay_delete_receipts)')}
    if 'files' not in columns:
        db.execute("ALTER TABLE relay_delete_receipts ADD COLUMN files TEXT NOT NULL DEFAULT '[]'")
    if 'shared_history' not in columns:
        db.execute('ALTER TABLE relay_delete_receipts ADD COLUMN shared_history TEXT')


def _private_media_files(paths, rows, jobs):
    """Freeze only provider traces at exact Relay-owned paths, with file hashes."""
    blockers = []
    locations = set()
    expected = {}
    for job in jobs:
        if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', job):
            blockers.append('A media job ID is not safe for private file cleanup.')
            continue
        expected[(job, 'result')] = paths.data / 'results' / (job + '.md')
        expected[(job, 'input')] = paths.data / 'gemini-runs' / (job + '.input.json')
        expected[(job, 'response')] = paths.data / 'gemini-runs' / (job + '.json')
    for row in rows.get('backend_jobs', ()):
        if row['id'] in jobs and row['result_path']:
            if (row['id'], 'result') not in expected:
                continue
            if row['result_path'] != str(expected[(row['id'], 'result')]):
                blockers.append('A media result file has unclassified ownership.')
            else: locations.add(expected[(row['id'], 'result')])
    for row in rows.get('gemini_history', ()):
        if row['job_id'] not in jobs: continue
        if (row['job_id'], 'input') not in expected: continue
        for column, kind in (('input_path', 'input'), ('response_path', 'response')):
            if row[column] != str(expected[(row['job_id'], kind)]):
                blockers.append('A provider history file has unclassified ownership.')
            else: locations.add(expected[(row['job_id'], kind)])
    for row in rows.get('gemini_runs', ()):
        if row['job_id'] not in jobs: continue
        if (row['job_id'], 'response') not in expected: continue
        if row['response_path'] != str(expected[(row['job_id'], 'response')]):
            blockers.append('A provider response file has unclassified ownership.')
        else: locations.add(expected[(row['job_id'], 'response')])
    files = []
    for path in sorted(locations):
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
            blockers.append('A private media file path is a symbolic link.')
            continue
        if path.exists() and not path.is_file():
            blockers.append('A private media path is not a regular file.')
            continue
        files.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()
                      if path.exists() else None})
    return blockers, files


def _media_task_rows(db, rows, add, steps, task_links):
    """Include a media task only when its single-use ownership is provable.

    The task's local reply routing is private Relay state. Channel conversation
    records (including orchestrator_messages) and delivered external messages
    are not task-owned and remain intact.
    """
    blockers = []
    task_ids = set()
    links = {link['step']: link for link in task_links}
    for stage in steps:
        if stage['target_kind'] != 'generate_image' or not stage['target']:
            continue
        link = links.get(stage['id'])
        job = db.execute('SELECT * FROM backend_jobs WHERE id=?', (stage['target'],)).fetchone()
        if (not link or not job or link['request_id'] != stage['request_id'] or
                link['backend_job_id'] != stage['target'] or link['task_id'] != job['thread_id'] or
                link['task_scope'] != 'separate_conversation'):
            blockers.append('A media stage has no verified agent task ownership link.')
            continue
        task, job_id = link['task_id'], link['backend_job_id']
        task_ids.add(task)
        if job['status'] != 'completed':
            blockers.append('A media task has unfinished or uncertain provider work.')
        watched = add('watched', 'id', {task})
        backend_task = add('backend_tasks', 'id', {task})
        if (len(watched) != 1 or watched[0]['status'] != 'idle' or
                len(backend_task) != 1 or backend_task[0]['backend'] != 'gemini'):
            blockers.append('A media task has missing, active, or unsupported task state.')
        if len(_ids(db, 'backend_jobs', 'thread_id', {task})) != 1:
            blockers.append('A media task has another backend job or turn.')
        if len(_ids(db, 'relay_pipeline_task_links', 'task_id', {task})) != 1:
            blockers.append('Another stage owns or shares this agent task.')
        image = _ids(db, 'orchestrator_image_requests', 'task_id', {task})
        if (len(image) != 1 or image[0]['job_id'] != stage['request_id'] or
                image[0]['backend_job_id'] != job_id):
            blockers.append('Another request owns or shares this media task.')
        run = add('gemini_runs', 'job_id', {job_id})
        history = add('gemini_history', 'job_id', {job_id})
        if (len(run) != 1 or run[0]['capability'] != 'image' or run[0]['stage'] != 'complete' or
                len(history) != 1 or history[0]['thread_id'] != task or history[0]['capability'] != 'image'):
            blockers.append('A media task has incomplete provider history.')
        tool_runs = add('gemini_tool_runs', 'job_id', {job_id})
        if tool_runs:
            blockers.append('A media task has provider tool records outside this cleanup contract.')
        artifacts = add('artifacts', 'thread_id', {task})
        if any(a['job_id'] not in (None, job_id) or
               (a['job_id'] is None and a['role'] != 'input') for a in artifacts):
            blockers.append('A media task has an artifact outside this media job.')
        incoming = add('incoming', 'thread_id', {task})
        if len(incoming) != 1 or incoming[0]['id'] != job['update_id'] or incoming[0]['status'] != 'completed':
            blockers.append('A media task has another or incomplete incoming request.')
        dispatch = add('capability_dispatches', 'job_id', {stage['request_id']})
        if len(dispatch) != 1 or dispatch[0]['thread_id'] != task:
            blockers.append('A media task has missing or conflicting dispatch evidence.')
        add('task_emojis', 'thread_id', {task})
        checkpoints = add('watch_checkpoints', 'thread_id', {task})
        if any(c['replaying'] for c in checkpoints):
            blockers.append('A media task is replaying its history.')
        add('gemini_models', 'thread_id', {task})
        bindings = add('relay_channel_bindings', 'entity', {task})
        if any(b['kind'] != 'task' for b in bindings):
            blockers.append('A channel binding uses the media task for another purpose.')
        task_outbox = add('outbox', 'thread_id', {task})
        allowed = ('image-request:' + str(stage['request_id']), 'backend:' + job_id + ':')
        if any(not (o['id'] == allowed[0] or o['id'].startswith(allowed[1]) or
                        re.fullmatch(r'tasks:\d+:' + re.escape(task), o['id'])) for o in task_outbox):
            blockers.append('A media task has delivery records outside the known task events.')
        task_media = add('media_outbox', 'thread_id', {task})
        if any(m['event_id'] not in {o['id'] for o in task_outbox} or m['status'] != 'sent'
               for m in task_media):
            blockers.append('A media task has pending or unowned media delivery.')
        reply_routes = add('messages', 'thread_id', {task})
        frozen_key = 'image-artifact-inputs:' + str(stage['request_id'])
        add('kv', 'key', {frozen_key})
        for key, in db.execute('SELECT key FROM kv WHERE key LIKE ?', ('%:' + str(stage['request_id']),)):
            if key != frozen_key:
                blockers.append('A media request has an unclassified saved preference.')
        for table_row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            table = table_row[0]
            if table == 'messages':
                continue
            columns = {column[1] for column in db.execute('PRAGMA table_info("' + table.replace('"', '""') + '")')}
            if 'message_id' not in columns:
                continue
            name = '"' + table.replace('"', '""') + '"'
            for route in reply_routes:
                query = f'SELECT 1 FROM {name} WHERE message_id=?'
                params = [route['message_id']]
                if 'chat_id' in columns:
                    query += ' AND chat_id=?'
                    params.append(route['chat_id'])
                if db.execute(query + ' LIMIT 1', params).fetchone():
                    blockers.append('A shared channel record references a media task reply route.')
                    break
        for key, value in db.execute('SELECT key,value FROM kv WHERE key LIKE ?', ('%' + task + '%',)):
            if key == 'gemini-reply-capability:' + task:
                add('kv', 'key', {key})
            else:
                blockers.append('A media task has an unclassified preference reference.')
        for key, value in db.execute('SELECT key,value FROM kv WHERE value LIKE ?', ('%' + task + '%',)):
            if key in ('selected', 'messages:selected') and value == json.dumps(task):
                add('kv', 'key', {key})
            else:
                blockers.append('Another preference or request references this media task.')
    # Future schema changes must not silently leave references to a deleted task.
    # This audit checks every typed task/job reference in the database, including
    # tables unknown to this version of the deletion contract.
    media_jobs = {link['backend_job_id'] for link in task_links if link['task_id'] in task_ids}
    task_artifacts = {r['id'] for r in rows.get('artifacts', ()) if r['thread_id'] in task_ids}
    for artifact in task_artifacts:
        if db.execute('SELECT 1 FROM gemini_runs WHERE job_id NOT IN (' +
                      ','.join('?' for _ in media_jobs) + ') AND instr(options_json,?)>0 LIMIT 1',
                      (*sorted(media_jobs), artifact)).fetchone():
            blockers.append('Another provider run references this media task artifact.')
    for table_row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        table = table_row[0]
        columns = {column[1] for column in db.execute('PRAGMA table_info("' + table.replace('"', '""') + '")')}
        selected = {r['_delete_rowid'] for r in rows.get(table, ())}
        for column, values in (('thread_id', task_ids), ('task_id', task_ids),
                               ('backend_job_id', media_jobs), ('job_id', media_jobs)):
            if column not in columns or not values:
                continue
            for record in _ids(db, table, column, values):
                if record['_delete_rowid'] not in selected:
                    blockers.append('Another record references this media task or backend job.')
    return blockers, sorted(task_ids)


def _graph(db, pid, paths):
    if not isinstance(pid, str) or not re.fullmatch(r'(?:job|pipe)-[a-f0-9]{24}', pid):
        raise JobDeleteError('Choose an exact saved pipeline.')
    owner = (db.execute('SELECT rowid AS _delete_rowid,* FROM relay_pipelines WHERE id=?',
                        (pid,)).fetchone() if _table(db, 'relay_pipelines') else None)
    standalone = (db.execute('SELECT rowid AS _delete_rowid,* FROM relay_standalone_jobs WHERE id=?',
                             (pid,)).fetchone() if _table(db, 'relay_standalone_jobs') else None)
    if bool(owner) == bool(standalone):
        raise JobDeleteError('This job has no unique ownership record. Refresh the list.')
    standalone_job = standalone is not None
    if standalone_job:
        root = db.execute('SELECT request_id,request,channel,parent_id FROM production_plans WHERE id=?',
                          (standalone['root_plan'],)).fetchone()
        owner = {'request_id': standalone['request_id'],
                 'title': root['request'].split('\n')[0][:180] if root else standalone['root_plan'],
                 'status': 'recorded'}
    rows = {}
    def add(table, column, values):
        selected = _ids(db, table, column, values)
        existing = {r['_delete_rowid']: r for r in rows.get(table, ())}
        existing.update({r['_delete_rowid']: r for r in selected})
        rows[table] = list(existing.values())
        return selected
    rows['relay_standalone_jobs' if standalone_job else 'relay_pipelines'] = [standalone if standalone_job else owner]
    steps = add('relay_pipeline_steps', 'pipeline', {pid})
    task_links = add('relay_pipeline_task_links', 'pipeline', {pid})
    add('relay_pipeline_requests', 'pipeline', {pid})
    add('relay_pipeline_events', 'pipeline', {pid})
    add('research_campaign_receipts', 'pipeline', {pid})
    repairs = add('production_auto_repairs', 'pipeline', {pid})
    add('relay_procedure_runs', 'pipeline', {pid})
    requests = {owner['request_id']} | {s['request_id'] for s in steps if s['request_id']}
    if not standalone_job:
        add('orchestrator_chats', 'id', requests)
        for table in ('orchestrator_chat_errors','orchestrator_guide_choices','orchestrator_proposals',
                      'orchestrator_image_requests','orchestrator_video_requests'):
            add(table, 'job_id', requests)
    plans = {standalone['root_plan']} if standalone_job else {
        s['target'] for s in steps if s['target_kind'] == 'plan_production' and s['target']}
    plans.update(r['plan_id'] for r in repairs if r['plan_id'])
    runs = {s['target'] for s in steps if s['target_kind'] == 'production_run' and s['target']}
    runs.update(r['preparation'] for r in repairs if r['preparation'])
    direct_runs = set(runs)
    # Follow descendants and the plan/run relation. Never absorb a parent: it may
    # belong to another job, so an external parent becomes a shared-work blocker.
    for _ in range(500):
        before = (len(plans), len(runs))
        for p in _ids(db, 'production_plans', 'id', plans):
            if p['run']: runs.add(p['run'])
        for p in _ids(db, 'production_plans', 'run', runs): plans.add(p['id'])
        if standalone_job:
            for p in _ids(db, 'production_plans', 'parent_id', plans): plans.add(p['id'])
        for link in _ids(db, 'production_stage_links', 'plan_id', plans):
            if link['child']: runs.add(link['child'])
        for link in _ids(db, 'production_stage_links', 'parent', runs):
            if link['child']: runs.add(link['child'])
            if link['plan_id']: plans.add(link['plan_id'])
        for link in _ids(db, 'production_continuations', 'parent', runs):
            if link['child']: runs.add(link['child'])
        if (len(plans), len(runs)) == before: break
        if len(plans) + len(runs) > 500:
            raise JobDeleteError('Pipeline ancestry is too large to delete safely.')
    else:
        raise JobDeleteError('Pipeline ancestry could not be resolved.')
    add('production_plans', 'id', plans)
    if standalone_job:
        direct_runs.update(runs)
    requests.update(p['request_id'] for p in rows['production_plans'] if p['request_id'])
    if not standalone_job:
        add('orchestrator_chats', 'id', requests)
        for table in ('orchestrator_chat_errors','orchestrator_guide_choices','orchestrator_proposals',
                      'orchestrator_image_requests','orchestrator_video_requests'):
            add(table, 'job_id', requests)
    direct_runs.update(p['run'] for p in rows['production_plans'] if p['run'])
    add('production_stage_links', 'plan_id', plans)
    direct_runs.update(link['child'] for link in rows['production_stage_links'] if link['child'])
    add('production_plan_calls', 'plan_id', plans)
    add('production_plan_messages', 'plan_id', plans)
    add('production_plan_replies', 'plan_id', plans)
    for table, col in (
        ('production_runs','id'), ('production_assignments','run'), ('production_tasks','run'),
        ('production_attempts','run'), ('production_artifacts','run'), ('production_events','run'),
        ('production_decisions','run'), ('production_revisions','run'), ('production_user_notes','run'),
        ('production_uploads','run'), ('production_albums','run'), ('production_folders','run'),
        ('production_folder_files','run'), ('production_selection_cards','run'),
        ('production_control_cards','run'), ('production_replacement_cards','run'),
        ('production_visual_review_cards','run'), ('relay_channel_bindings','entity')):
        add(table, col, runs)
    for table in ('production_stage_links', 'production_continuations'):
        add(table, 'parent', runs)
        add(table, 'child', runs)
    operation_attempts={r['id'] for r in rows.get('production_attempts',())}
    for table in ('operation_record_sets','operation_records','operation_submissions'):
        add(table,'attempt',operation_attempts)
    output_artifacts = {r['id'] for r in rows.get('production_artifacts', ())}
    decision_ids = {r['id'] for r in rows.get('production_decisions', ())}
    from orchestrator.artifact_replacements import scope
    scopes = set()
    malformed_scopes = False
    for run in runs:
        if not db.execute('SELECT 1 FROM production_runs WHERE id=?', (run,)).fetchone(): continue
        try: scopes.add(scope(db, run))
        except (ValueError, TypeError, KeyError): malformed_scopes = True
    add('production_replacement_heads', 'scope', scopes)
    heads = {r['id'] for r in rows.get('production_replacement_heads', ())}
    add('production_replacements', 'head', heads)
    add('production_artifact_validity', 'head', heads)
    add('production_artifact_validity', 'artifact', output_artifacts)
    for table, parent in (
        ('production_selection_messages','production_selection_cards'),
        ('production_control_messages','production_control_cards'),
        ('production_replacement_messages','production_replacement_cards'),
        ('production_visual_review_messages','production_visual_review_cards')):
        add(table, 'token', {r['token'] for r in rows.get(parent, ())})
    for table in ('relay_fact_bindings','relay_fact_coverage','relay_fact_revisions',
                  'relay_fact_external_submissions',
                  'relay_fact_candidate_reviews','relay_fact_selections','relay_translation_links',
                  'relay_translation_revisions','relay_translation_reviews','relay_translation_selections',
                  'relay_presentation_links','relay_presentation_coverage','relay_presentation_revisions',
                  'relay_presentation_reviews','relay_presentation_selections',
                  'relay_native_links','relay_native_coverage','relay_reviewed_impacts',
                  'relay_impact_handoffs','relay_agent_candidates',
                  'relay_agent_candidate_inputs', 'relay_agent_candidate_feedback',
                  'relay_revision_bundle_plans', 'relay_revision_bundles',
                  'relay_revision_bundle_files', 'relay_revision_bundle_reviews',
                  'relay_revision_bundle_selections',
                  'relay_bundle_continuation_plans', 'relay_bundle_continuations',
                  'relay_bundle_continuation_reviews',
                  'relay_bundle_continuation_selections',
                  'relay_computer_assignments',
                  'relay_computer_actions', 'relay_computer_decisions', 'relay_computer_packs', 'relay_computer_reviews'):
        add(table, 'job', {pid})
    computer_ids = {r['id'] for r in rows.get('relay_computer_assignments', ())}
    for table in ('relay_computer_actions', 'relay_computer_decisions', 'relay_computer_packs'):
        add(table, 'assignment', computer_ids)
    add('relay_computer_reviews', 'pack', {r['id'] for r in rows.get('relay_computer_packs', ())})
    agent_candidates = {r['candidate_artifact'] for r in rows.get('relay_agent_candidates', ())}
    for table in ('relay_agent_candidate_reviews', 'relay_agent_candidate_selections'):
        add(table, 'candidate_artifact', agent_candidates)
    agent_inputs = {r['artifact'] for r in rows.get('relay_agent_candidate_inputs', ())}
    handoff_input_blockers = []
    for handoff in rows.get('relay_impact_handoffs', ()):
        if handoff['kind'] != 'native_subject_replacement':
            continue
        try:
            replacement = json.loads(handoff['inputs'])['replacement_artifact']
            if not isinstance(replacement, str) or not replacement:
                raise ValueError('Missing replacement artifact.')
        except (ValueError, TypeError, KeyError):
            handoff_input_blockers.append('A replacement handoff has an unreadable picture input.')
        else:
            agent_inputs.add(replacement)
    agent_artifacts = agent_candidates | agent_inputs
    add('production_artifacts', 'id', agent_artifacts)
    agent_artifact_blockers = []
    agent_artifact_blockers.extend(handoff_input_blockers)
    registered = {r['id']: r for r in rows.get('production_artifacts', ())}
    for artifact in agent_artifacts:
        row = registered.get(artifact)
        expected_path = ('delivery/agent_candidate.pptx' if artifact in agent_candidates else None)
        if (row is None or row['run'] is not None or row['attempt'] is not None
                or row['task'] != 'agent_candidate'
                or (expected_path is not None and row['path'] != expected_path)
                or (artifact in agent_inputs and not row['path'].startswith('inputs/'))):
            agent_artifact_blockers.append('An agent candidate artifact has unproven ownership.')
    agent_events = []
    if agent_artifacts:
        for event in db.execute("""SELECT rowid AS _delete_rowid,* FROM production_events
                                   WHERE task='agent_candidate'"""):
            try:
                payload = json.loads(event['data'])
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and payload.get('artifact') in agent_artifacts:
                artifact = registered.get(payload['artifact'])
                if (event['run'] is not None or event['attempt'] is not None
                        or event['kind'] != 'artifact_registered' or artifact is None
                        or payload.get('sha256') != artifact['sha256']
                        or payload.get('path') != artifact['path']):
                    agent_artifact_blockers.append('An agent candidate registration receipt changed.')
                else:
                    agent_events.append(event)
        if (len(agent_events) != len(agent_artifacts)
                or {json.loads(event['data'])['artifact'] for event in agent_events} != agent_artifacts):
            agent_artifact_blockers.append('An agent candidate registration receipt is missing.')
        rows.setdefault('production_events', []).extend(agent_events)
    output_artifacts.update(agent_artifacts)
    computer_packs = rows.get('relay_computer_packs', ())
    computer_artifacts = {r['artifact'] for r in computer_packs if r['artifact']}
    add('production_artifacts', 'id', computer_artifacts)
    computer_registered = {r['id']: r for r in rows.get('production_artifacts', ())}
    for pack in computer_packs:
        artifact = computer_registered.get(pack['artifact'])
        if (pack['job'] != pid or pack['assignment'] not in computer_ids or pack['state'] != 'ready'
                or artifact is None or artifact['run'] is not None or artifact['attempt'] is not None
                or artifact['task'] != 'computer_evidence' or artifact['path'] != 'delivery/safari-evidence.zip'
                or artifact['sha256'] != pack['sha256']):
            agent_artifact_blockers.append('Native evidence pack needs publication recovery or has inconsistent ownership.')
    if computer_artifacts:
        pack_events = []
        for event in db.execute("SELECT rowid AS _delete_rowid,* FROM production_events WHERE task='computer_evidence'"):
            try: payload = json.loads(event['data'])
            except (ValueError, TypeError): continue
            if not isinstance(payload, dict) or payload.get('artifact') not in computer_artifacts: continue
            artifact = computer_registered[payload['artifact']]
            if (event['run'] is not None or event['attempt'] is not None or event['kind'] != 'artifact_registered'
                    or payload.get('sha256') != artifact['sha256'] or payload.get('path') != artifact['path']):
                agent_artifact_blockers.append('Native evidence pack registration receipt changed.')
            else: pack_events.append(event)
        if len(pack_events) != len(computer_artifacts) or {json.loads(e['data'])['artifact'] for e in pack_events} != computer_artifacts:
            agent_artifact_blockers.append('Native evidence pack registration receipt is missing.')
        rows.setdefault('production_events', []).extend(pack_events)
    output_artifacts.update(computer_artifacts)
    computer_reviews = rows.get('relay_computer_reviews', ())
    review_artifacts = {r['artifact'] for r in computer_reviews if r['artifact']}
    add('production_artifacts', 'id', review_artifacts)
    registered_reviews = {r['id']: r for r in rows.get('production_artifacts', ())}
    packs_by_id = {p['id']: p for p in computer_packs}
    for review in computer_reviews:
        pack = packs_by_id.get(review['pack'])
        artifact = registered_reviews.get(review['artifact'])
        if (review['job'] != pid or pack is None or review['pack_artifact'] != pack['artifact']
                or review['pack_sha256'] != pack['sha256']
                or review['state'] in ('prepared','responded')
                or (review['state'] in ('submitted','uncertain') and not review['resolved'])):
            agent_artifact_blockers.append('Native evidence review needs reconciliation or has inconsistent ownership.')
        if review['artifact'] and (artifact is None or artifact['task'] != 'computer_review'
                or artifact['run'] is not None or artifact['attempt'] is not None
                or artifact['path'] != 'delivery/safari-review.json' or review['state'] != 'completed'):
            agent_artifact_blockers.append('Native review artifact has unproven ownership.')
        if review['state'] == 'completed' and not review['artifact']:
            agent_artifact_blockers.append('Native review artifact is missing.')
    if review_artifacts:
        review_events = []
        for event in db.execute("SELECT rowid AS _delete_rowid,* FROM production_events WHERE task='computer_review'"):
            try: payload = json.loads(event['data'])
            except (ValueError,TypeError): continue
            if not isinstance(payload,dict) or payload.get('artifact') not in review_artifacts: continue
            artifact = registered_reviews[payload['artifact']]
            if (event['run'] is not None or event['attempt'] is not None or event['kind'] != 'artifact_registered'
                    or payload.get('sha256') != artifact['sha256'] or payload.get('path') != artifact['path']):
                agent_artifact_blockers.append('Native review registration receipt changed.')
            else: review_events.append(event)
        if len(review_events) != len(review_artifacts) or {json.loads(e['data'])['artifact'] for e in review_events} != review_artifacts:
            agent_artifact_blockers.append('Native review registration receipt is missing.')
        rows.setdefault('production_events', []).extend(review_events)
    output_artifacts.update(review_artifacts)
    bundle_files = rows.get('relay_revision_bundle_files', ())
    bundle_artifacts = {r['candidate_artifact'] for r in bundle_files}
    add('production_artifacts', 'id', bundle_artifacts)
    bundle_artifact_blockers = []
    registered.update({r['id']: r for r in rows.get('production_artifacts', ())})
    for item in bundle_files:
        artifact = registered.get(item['candidate_artifact'])
        expected_path = {'slides': 'delivery/slides.json',
                         'photo_manifest': 'delivery/selected-photo-manifest.json'}.get(item['role'])
        if (artifact is None or expected_path is None or artifact['run'] is not None
                or artifact['attempt'] is not None or artifact['task'] != 'revision_bundle'
                or artifact['path'] != expected_path
                or artifact['sha256'] != item['candidate_sha256']):
            bundle_artifact_blockers.append('A revision companion has unproven ownership.')
    bundle_events = []
    if bundle_artifacts:
        for event in db.execute("""SELECT rowid AS _delete_rowid,* FROM production_events
                                   WHERE task='revision_bundle'"""):
            try:
                payload = json.loads(event['data'])
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and payload.get('artifact') in bundle_artifacts:
                artifact = registered.get(payload['artifact'])
                if (event['run'] is not None or event['attempt'] is not None
                        or event['kind'] != 'artifact_registered' or artifact is None
                        or payload.get('sha256') != artifact['sha256']
                        or payload.get('path') != artifact['path']):
                    bundle_artifact_blockers.append('A companion registration receipt changed.')
                else:
                    bundle_events.append(event)
        if (len(bundle_events) != len(bundle_artifacts)
                or {json.loads(event['data'])['artifact'] for event in bundle_events}
                   != bundle_artifacts):
            bundle_artifact_blockers.append('A companion registration receipt is missing.')
        rows.setdefault('production_events', []).extend(bundle_events)
    output_artifacts.update(bundle_artifacts)
    continuation_rows = rows.get('relay_bundle_continuations', ())
    continuation_ids = {item[column] for item in continuation_rows for column in
                        ('pptx_artifact', 'slides_artifact', 'photo_manifest_artifact')}
    add('production_artifacts', 'id', continuation_ids)
    registered.update({r['id']: r for r in rows.get('production_artifacts', ())})
    continuation_artifacts = set()
    continuation_blockers = []
    for item in continuation_rows:
        for role, column, sha_column, path in (
                ('pptx', 'pptx_artifact', 'pptx_sha256', 'delivery/presentation.pptx'),
                ('slides', 'slides_artifact', 'slides_sha256', 'delivery/slides.json'),
                ('photo_manifest', 'photo_manifest_artifact', 'photo_manifest_sha256',
                 'delivery/selected-photo-manifest.json')):
            artifact = registered.get(item[column])
            if artifact is None or artifact['sha256'] != item[sha_column]:
                continuation_blockers.append('A continuation file has no exact owned version.')
            elif artifact['task'] == 'bundle_continuation':
                if (artifact['run'] is not None or artifact['attempt'] is not None
                        or artifact['path'] != path):
                    continuation_blockers.append('A continuation file has unproven ownership.')
                continuation_artifacts.add(item[column])
            elif item[column] not in output_artifacts:
                continuation_blockers.append('A reused continuation file belongs to another job.')
    continuation_events = []
    if continuation_artifacts:
        for event in db.execute("""SELECT rowid AS _delete_rowid,* FROM production_events
                                   WHERE task='bundle_continuation'"""):
            try:
                payload = json.loads(event['data'])
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and payload.get('artifact') in continuation_artifacts:
                artifact = registered.get(payload['artifact'])
                if (event['run'] is not None or event['attempt'] is not None
                        or event['kind'] != 'artifact_registered' or artifact is None
                        or payload.get('sha256') != artifact['sha256']
                        or payload.get('path') != artifact['path']):
                    continuation_blockers.append('A continuation registration receipt changed.')
                else:
                    continuation_events.append(event)
        if (len(continuation_events) != len(continuation_artifacts)
                or {json.loads(event['data'])['artifact'] for event in continuation_events}
                   != continuation_artifacts):
            continuation_blockers.append('A continuation registration receipt is missing.')
        rows.setdefault('production_events', []).extend(continuation_events)
    output_artifacts.update(continuation_artifacts)
    candidates = {r['candidate_artifact'] for table in (
        'relay_fact_revisions','relay_fact_candidate_reviews','relay_fact_selections',
        'relay_translation_revisions','relay_translation_reviews','relay_translation_selections',
        'relay_presentation_revisions','relay_presentation_reviews','relay_presentation_selections',
        'relay_reviewed_impacts') for r in rows.get(table, ())}
    add('relay_revision_action_receipts', 'candidate_artifact', candidates)
    add('relay_channel_bindings', 'entity', {pid})
    add('relay_channel_bindings', 'entity', plans)
    if not standalone_job:
        add('relay_request_channels', 'request_id', {owner['request_id']} |
            {r['request_id'] for r in steps if r['request_id']} |
            {r['request_id'] for r in rows.get('production_plans', ()) if r['request_id']})
    browser = {s['target'] for s in steps if s['target_kind'] == 'browser_research' and s['target']}
    for ident in requests:
        browser.update(r['id'] for r in _ids(db, 'browser_research_requests', 'source', {'orchestrator:' + str(ident)}))
    media = {s['target'] for s in steps if s['target_kind'] == 'generate_image' and s['target']}
    media.update(r['backend_job_id'] for r in rows.get('orchestrator_image_requests', ()) if r['backend_job_id'])
    for table, column, values in (
        ('browser_research_requests','id',browser), ('browser_research_transport','id',browser),
        ('browser_jobs','id',browser), ('browser_job_events','job',browser),
        ('backend_jobs','id',media), ('artifacts','job_id',media)):
        add(table, column, values)
    media_blockers, media_tasks = _media_task_rows(db, rows, add, steps, task_links)
    file_blockers, cleanup_files = _private_media_files(paths, rows, media)
    # Exact job-specific delivery receipts. Shared chat history remains outside this job.
    event_ids = {r['event_id'] for table in ('production_plans','production_selection_cards',
                 'production_control_cards','production_replacement_cards','production_visual_review_cards')
                 for r in rows.get(table, ()) if r['event_id']}
    event_ids.update(r['event_id'] for r in rows.get('orchestrator_proposals', ()) if r['event_id'])
    event_ids.update('orchestrator:' + str(ident) for ident in requests)
    shared_delivery = []
    if _table(db, 'outbox') and not standalone_job:
        for prefix in (f'pipeline:{pid}:', *(f'production:{r}:' for r in runs)):
            found = list(db.execute('SELECT rowid AS _delete_rowid,* FROM outbox WHERE substr(id,1,?)=? ORDER BY rowid', (len(prefix),prefix)))
            rows.setdefault('outbox', []).extend(found)
            if _table(db, 'media_outbox'):
                found_media = list(db.execute('SELECT rowid AS _delete_rowid,* FROM media_outbox WHERE substr(event_id,1,?)=? ORDER BY rowid', (len(prefix),prefix)))
                rows.setdefault('media_outbox', []).extend(found_media)
        add('outbox', 'id', event_ids)
        event_ids.update(r['id'] for r in rows.get('outbox', ()))
    if not standalone_job:
        add('outbox_parts', 'event_id', event_ids)
        add('relay_event_channels', 'event_id', event_ids)
        add('media_outbox', 'event_id', event_ids)
    if standalone_job and _table(db, 'outbox'):
        for prefix in (f'production:{r}:' for r in runs):
            shared_delivery.extend(db.execute('SELECT id,sent FROM outbox WHERE substr(id,1,?)=?',
                                              (len(prefix), prefix)).fetchall())
        shared_delivery.extend(_ids(db, 'outbox', 'id', event_ids))
    shared_event_ids = {r['id'] for r in shared_delivery}
    shared_history = {'version': 2, 'channel': standalone['channel'],
                      'event_ids': sorted(shared_event_ids),
                      'request_ids': sorted(requests)} if standalone_job else None
    shared_outbox = _ids(db, 'outbox', 'id', shared_event_ids)
    shared_parts = _ids(db, 'outbox_parts', 'event_id', shared_event_ids)
    blockers = []
    blockers.extend(media_blockers)
    blockers.extend(file_blockers)
    blockers.extend(agent_artifact_blockers)
    blockers.extend(bundle_artifact_blockers)
    blockers.extend(continuation_blockers)
    if malformed_scopes: blockers.append('A production has unreadable replacement ownership.')
    if standalone_job:
        from .job_ownership import standalone_id
        if standalone_id(standalone['root_plan']) != pid:
            blockers.append('The standalone job identity does not match its root plan.')
        if browser:
            blockers.append('Standalone browser research ownership is not proven.')
        if steps or task_links or repairs or any(rows.get(table) for table in
             ('relay_pipeline_requests','relay_pipeline_events','relay_procedure_runs')):
            blockers.append('A standalone job has orphaned pipeline ownership records.')
        if (not root or root['parent_id'] is not None or root['request_id'] != standalone['request_id'] or
                root['channel'] != standalone['channel'] or
                hashlib.sha256(root['request'].encode()).hexdigest() != standalone['request_sha256']):
            blockers.append('The standalone root request or channel changed.')
        if standalone['last_run'] not in runs or not runs:
            blockers.append('The standalone result run has no complete ownership ancestry.')
        if any(not row['sent'] for row in shared_delivery):
            blockers.append('A shared channel delivery is still pending.')
        if any(r['status'] != 'sent' for r in _ids(db, 'media_outbox', 'event_id',
                                                 {row['id'] for row in shared_delivery})):
            blockers.append('A shared media delivery is still pending.')
        if any(not r['sent'] for r in _ids(db, 'outbox_parts', 'event_id',
                                          {row['id'] for row in shared_delivery})):
            blockers.append('A shared channel delivery part is still pending.')
    if not standalone_job and owner['status'] in ('active','paused','queued','running'):
        blockers.append('Pipeline is active or paused; stop and resolve it first.')
    if any(r['state'] not in ('completed', 'cancelled') for r in rows.get('relay_computer_assignments', ())):
        blockers.append('Native computer assignment must be stopped and reconciled first.')
    if any(r['job'] != pid or r['assignment'] not in computer_ids
           for table in ('relay_computer_actions', 'relay_computer_decisions') for r in rows.get(table, ())):
        blockers.append('Native computer receipts have inconsistent job ownership.')
    if any(r['state'] in ('claimed', 'uncertain') and not r['resolved'] for r in rows.get('relay_computer_actions', ())):
        blockers.append('Native computer action has an unresolved outcome.')
    if any(r['status'] not in ('answered','failed','completed') for r in rows.get('orchestrator_chats', ())):
        blockers.append('An orchestrator request is still active or uncertain.')
    for table, ids, column in (('production_plans',plans,'id'),('production_runs',runs,'id'),
                               ('browser_research_requests',browser,'id'),('backend_jobs',media,'id')):
        found = {r[column] for r in rows.get(table, ())}
        if ids - found: blockers.append(f'{table} has a missing ownership record.')
    for table, statuses, column in (
        ('production_plans', {'queued','planning','active','running','awaiting_user','awaiting_review','needs_input','ready','uncertain'}, 'status'),
        ('production_tasks', {'queued','running','awaiting_user','awaiting_review','uncertain'}, 'status'),
        ('production_attempts', {'queued','running','dispatched','uncertain'}, 'state'),
        ('production_continuations', {'queued','running','uncertain'}, 'status'),
        ('production_revisions', {'queued','running','uncertain'}, 'status'),
        ('production_uploads', {'queued','running','uncertain'}, 'status'),
        ('media_outbox', {'queued','pending','sending','retry'}, 'status'),
        ('browser_research_requests', {'queued','running','inspect','uncertain'}, 'state'),
        ('browser_jobs', {'prepared','blocked','submitting','uncertain','running'}, 'status'),
        ('backend_jobs', {'queued','running','waiting','uncertain'}, 'status'),
        ('production_selection_cards', {'pending','awaiting_user'}, 'status'),
        ('production_replacement_cards', {'pending','awaiting_user'}, 'status'),
        ('production_visual_review_cards', {'pending','awaiting_user'}, 'status')):
        if any(r[column] in statuses for r in rows.get(table, ())):
            blockers.append(f'{table} has active or uncertain work.')
    links_by_stage = {link['step']: link for link in task_links}
    media_stages = {stage['id'] for stage in steps
                    if stage['target_kind'] == 'generate_image' and stage['target']}
    if any(link['step'] not in media_stages for link in task_links):
        blockers.append('An agent task link has no matching media stage target.')
    for stage in steps:
        if stage['target_kind'] != 'generate_image' or not stage['target']:
            continue
        link = links_by_stage.get(stage['id'])
        backend = next((job for job in rows.get('backend_jobs', ()) if job['id'] == stage['target']), None)
        if (not link or not backend or link['request_id'] != stage['request_id'] or
                link['backend_job_id'] != stage['target'] or link['task_id'] != backend['thread_id']):
            blockers.append('A media stage has no verified agent task ownership link.')
    if any(not r['sent'] for r in rows.get('outbox', ())):
        blockers.append('An outbound message is still pending.')
    if any(not r['sent'] for r in rows.get('outbox_parts', ())):
        blockers.append('An outbound message part is still pending.')
    for table in ('production_stage_links','production_continuations'):
        for link in rows.get(table, ()):
            if link['parent'] in runs and link['child'] and link['child'] not in runs:
                blockers.append('A production link crosses job ownership.')
            if table == 'production_continuations' and link['parent'] in runs and link['child'] and link['child'] not in direct_runs:
                blockers.append('A separate continuation depends on this run.')
    for item in rows.get('orchestrator_proposals', ()):
        if item['status'] in ('pending','offered'):
            blockers.append('A workflow proposal is still awaiting a decision.')
    for other in db.execute('SELECT pipeline,target_kind,target FROM relay_pipeline_steps WHERE pipeline<>?', (pid,)):
        if (other['target_kind'] == 'plan_production' and other['target'] in plans) or (other['target_kind'] == 'production_run' and other['target'] in runs):
            blockers.append('Another pipeline uses this plan or run.')
        if (other['target_kind'] == 'browser_research' and other['target'] in browser) or (other['target_kind'] == 'generate_image' and other['target'] in media):
            blockers.append('Another pipeline uses this browser or media job.')
    for other in db.execute('SELECT pipeline,plan_id,preparation FROM production_auto_repairs WHERE pipeline<>?', (pid,)):
        if other['plan_id'] in plans or other['preparation'] in runs:
            blockers.append('Another pipeline uses this repair work.')
    if _table(db, 'relay_standalone_jobs'):
        for other in db.execute('SELECT id,root_plan,last_run FROM relay_standalone_jobs WHERE id<>?',
                                (pid,)):
            if other['root_plan'] in plans or other['last_run'] in runs:
                blockers.append('Another standalone job shares this plan or run.')
    for table in ('production_stage_links','production_continuations'):
        for link in _ids(db, table, 'child', runs):
            if link['parent'] in runs and link['child'] not in runs:
                blockers.append('Another production depends on this run.')
    for plan in _ids(db, 'production_plans', 'parent_id', plans):
        if plan['id'] not in plans: blockers.append('Another plan depends on this plan.')
    for other in db.execute('SELECT id,plan FROM production_runs'):
        if other['id'] not in runs:
            try: other_scope = scope(db, other['id'])
            except (ValueError, TypeError, json.JSONDecodeError): continue
            if other_scope in scopes and heads:
                blockers.append('A replacement ledger is shared with another run.')
    exposed = output_artifacts | {r['id'] for r in rows.get('artifacts', ())} | {
        'media-' + r['id'] for r in rows.get('artifacts', ())}
    for other in db.execute('SELECT id,context,options FROM production_plans'):
        if other['id'] in plans: continue
        try: sources = json.loads(other['context']).get('sources', [])
        except (ValueError, TypeError, AttributeError): continue
        if any(isinstance(s, dict) and s.get('artifact') in exposed for s in sources):
            blockers.append('Another plan uses an output artifact from this job.')
        try: options = json.loads(other['options'])
        except (ValueError, TypeError): options = {}
        if isinstance(options, dict):
            selected_artifacts = options.get('artifact_ids', [])
            if isinstance(selected_artifacts, list) and any(
                    a in exposed for a in selected_artifacts if isinstance(a, str)):
                blockers.append('Another plan selects an output artifact from this job.')
            previous_run = options.get('previous_run')
            if isinstance(previous_run, str) and previous_run in runs:
                blockers.append('Another plan continues this job’s run.')
    for table, column in (('relay_pipeline_steps','sources'), ('relay_pipeline_requests','inputs')):
        if not _table(db, table): continue
        for other in db.execute(f'SELECT pipeline,{column} FROM {table} WHERE pipeline<>?', (pid,)):
            try: references = json.loads(other[column] or '[]')
            except (ValueError, TypeError): continue
            if isinstance(references, dict): references = references.get('sources', [])
            if isinstance(references, list) and any(isinstance(s, dict) and s.get('artifact') in exposed for s in references):
                blockers.append('Another pipeline cites an output artifact from this job.')
    for table, columns in (
        ('relay_fact_bindings',('source_artifact','output_artifact')),
        ('relay_translation_links',('source_artifact','output_artifact','review_report_artifact')),
        ('relay_presentation_links',('source_artifact','output_artifact')),
        ('relay_native_links',('source_artifact','output_artifact')),
        ('relay_native_coverage',('output_artifact',)),
        ('relay_impact_handoffs',('baseline_artifact',)),
        ('relay_agent_candidates',('candidate_artifact',)),
        ('relay_computer_packs',('artifact',)),
        ('relay_computer_reviews',('pack_artifact','artifact')),
        ('relay_agent_candidate_inputs',('artifact',)),
        ('relay_agent_candidate_feedback',('candidate_artifact',)),
        ('relay_revision_bundles',('pptx_candidate',)),
        ('relay_revision_bundle_files',('baseline_artifact','candidate_artifact')),
        ('relay_bundle_continuations',('pptx_artifact','slides_artifact',
                                       'photo_manifest_artifact')),
        ('relay_fact_revisions',('baseline_artifact','old_source','replacement_source')),
        ('relay_translation_revisions',('baseline_artifact','old_source','replacement_source')),
        ('relay_presentation_revisions',('baseline_artifact','old_source','replacement_source'))):
        if not _table(db, table): continue
        for column in columns:
            for other in _ids(db, table, column, exposed):
                if other['job'] != pid:
                    blockers.append('Another job has a reviewed link to this job’s artifact.')
    if _table(db, 'relay_impact_handoffs'):
        for other in db.execute('SELECT job,kind,inputs FROM relay_impact_handoffs WHERE job<>?', (pid,)):
            try:
                inputs = json.loads(other['inputs'])
            except (ValueError, TypeError, AttributeError):
                continue
            if not isinstance(inputs, dict):
                continue
            references = ({inputs.get('replacement_artifact')}
                          if other['kind'] == 'native_subject_replacement' else
                          {inputs.get('old_source'), inputs.get('replacement_source')}
                          if other['kind'] == 'xlsx_fact_change' else set())
            if references & exposed:
                blockers.append('Another job has a reviewed link to this job’s artifact.')
    if _table(db, 'relay_revision_bundle_plans'):
        for other in db.execute('SELECT job,plan FROM relay_revision_bundle_plans WHERE job<>?',
                                (pid,)):
            try:
                plan = json.loads(other['plan'])
                references = {plan['image_artifact']} | {
                    item['baseline_artifact'] for item in plan['companions']}
            except (ValueError, TypeError, KeyError):
                continue
            if references & exposed:
                blockers.append('Another job has a reviewed link to this job’s artifact.')
    if _table(db, 'relay_bundle_continuation_plans'):
        for other in db.execute('SELECT job,plan FROM relay_bundle_continuation_plans WHERE job<>?',
                                (pid,)):
            try:
                plan = json.loads(other['plan'])
                references = {plan['pptx_baseline_artifact'], plan['image_artifact']}
                references.update(item['baseline_artifact'] for item in plan['companions'])
                references.update(item['artifact'] for item in plan['reused'])
            except (ValueError, TypeError, KeyError):
                continue
            if references & exposed:
                blockers.append('Another job has a reviewed link to this job’s artifact.')
    if any(r['head'] not in heads for r in rows.get('production_artifact_validity', ())):
        blockers.append('An output validity record belongs to another replacement ledger.')
    for head in rows.get('production_replacement_heads', ()):
        try: members = set(json.loads(head['members']))
        except (TypeError, ValueError):
            blockers.append('A replacement ledger has unreadable members.')
            continue
        if members - decision_ids:
            blockers.append('A replacement ledger includes another job’s decision.')
    for other in db.execute('SELECT job_id,backend_job_id FROM orchestrator_image_requests') if _table(db, 'orchestrator_image_requests') else ():
        if other['backend_job_id'] in media and other['job_id'] not in requests:
            blockers.append('Another request uses this media job.')
    for binding in _ids(db, 'relay_channel_bindings', 'entity', runs):
        if binding['kind'] not in ('production', 'plan'):
            blockers.append('A shared channel binding uses this run.')
    if any(s['target'] and s['target_kind'] not in ('plan_production','production_run','browser_research','generate_image') for s in steps):
        blockers.append('A stage target has no supported ownership rule.')
    if candidates:
        for table in ('relay_fact_revisions','relay_fact_candidate_reviews','relay_fact_selections',
                      'relay_translation_revisions','relay_translation_reviews','relay_translation_selections',
                      'relay_presentation_revisions','relay_presentation_reviews','relay_presentation_selections',
                      'relay_reviewed_impacts'):
            for record in _ids(db, table, 'candidate_artifact', candidates):
                if record['job'] != pid: blockers.append('Another job references a revision candidate.')
    if standalone_job:
        # New tables with typed plan/run references must not become invisible
        # leftovers after the registered job is removed.
        for table_row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            table = table_row[0]
            columns = {column[1] for column in db.execute('PRAGMA table_info("' + table.replace('"','""') + '")')}
            selected = {row['_delete_rowid'] for row in rows.get(table, ())}
            for column, identities in (('run',runs),('plan_id',plans),('parent_id',plans),
                                       ('parent',runs),('child',runs)):
                if column not in columns or not identities:
                    continue
                for record in _ids(db, table, column, identities):
                    if record['_delete_rowid'] not in selected:
                        blockers.append('Another record has an unowned plan or run reference.')
                        break
    # A digest of exact rows makes the confirmation conditional on the same graph.
    digest = hashlib.sha256()
    for table in sorted(rows):
        unique = {r['_delete_rowid']: r for r in rows[table]}
        rows[table] = list(unique.values())
        for row in sorted(unique.values(), key=lambda r: r['_delete_rowid']):
            digest.update(json.dumps([table, list(row)], default=str, ensure_ascii=True).encode() + b'\n')
    digest.update(json.dumps(cleanup_files, sort_keys=True).encode() + b'\n')
    if shared_history is not None:
        digest.update(json.dumps(shared_history, sort_keys=True).encode() + b'\n')
        for table, records in (('retained-outbox', shared_outbox),
                               ('retained-outbox-parts', shared_parts)):
            for row in records:
                digest.update(json.dumps([table, list(row)], default=str,
                                         ensure_ascii=True).encode() + b'\n')
    return {'id':pid, 'kind':'production_result' if standalone_job else 'pipeline',
            'title':owner['title'], 'status':owner['status'], 'runs':sorted(runs),
            'plans':sorted(plans), 'media_tasks':media_tasks,
            'shared_history_preserved':True,
            'counts':{k:len(v) for k,v in rows.items() if v},
            'blockers':sorted(set(blockers)), 'digest':digest.hexdigest(),
            '_rows':rows, '_cleanup_files':cleanup_files,
            '_shared_history':shared_history}


def preview(pid, paths=PATHS):
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        result = _graph(db, pid, paths)
        return {k:v for k,v in result.items() if not k.startswith('_')}


def delete(pid, digest, paths=PATHS):
    if not isinstance(digest, str) or len(digest) != 64:
        raise JobDeleteError('Review the exact pipeline before deleting it.')
    with closing(_database(paths, writable=True)) as db:
        with transaction(db):
            _prepare(db)
            prior = db.execute('SELECT digest,status FROM relay_delete_receipts WHERE id=?', (pid,)).fetchone()
            if prior:
                if prior['digest'] != digest: raise JobDeleteError('Deletion confirmation is stale.')
            else:
                result = _graph(db, pid, paths)
                if result['digest'] != digest: raise JobDeleteError('Pipeline changed. Review it again.')
                if result['blockers']: raise JobDeleteError('Deletion blocked: ' + ' '.join(result['blockers']))
                # All related rows and the tombstone commit together.
                for table, records in result['_rows'].items():
                    if records:
                        db.executemany(f'DELETE FROM {table} WHERE rowid=?', ((r['_delete_rowid'],) for r in records))
                db.execute('''INSERT INTO relay_delete_receipts
                    (id,digest,status,created,error,files,shared_history)
                    VALUES (?,?,?, ?,NULL,?,?)''',
                    (pid, digest, 'cleanup_pending', time.time(),
                     json.dumps(result['_cleanup_files'], sort_keys=True),
                     json.dumps(result['_shared_history'], sort_keys=True)
                     if result['_shared_history'] is not None else None))
    return recover(pid, paths)


def _cleanup_view(folder, pid):
    marker = folder / '.relay-workflow.json'
    if marker.exists():
        if marker.is_symlink() or json.loads(marker.read_text()).get('workflow') != pid:
            raise ValueError('Workflow ownership marker does not match.')
    elif any((folder / name).exists() for name in ('.relay','manifest.json','README.md','request.txt')):
        raise ValueError('Private job view has no ownership marker.')
    def remove(path):
        if path.is_symlink(): raise ValueError('Private job view contains a symbolic link.')
        if path.is_dir(): shutil.rmtree(path)
        elif path.exists(): path.unlink()
    for stage in folder.iterdir():
        if stage.is_symlink(): continue  # An unrelated native-file link is not Relay metadata.
        if stage.is_dir() and re.fullmatch(r'\d{2}-[a-zA-Z0-9_-]+', stage.name):
            for name in ('README.md','result.md'):
                remove(stage / name)
    legacy = folder / 'snapshots'
    if legacy.exists():
        if legacy.is_symlink(): raise ValueError('Legacy snapshots are a symbolic link.')
        for snapshot in legacy.iterdir():
            if snapshot.is_symlink(): raise ValueError('Legacy snapshot is a symbolic link.')
            if snapshot.is_dir(): remove(snapshot / 'manifest.json')
    for name in ('.relay', 'manifest.json', 'README.md', 'request.txt', '.relay-workflow.json'):
        remove(folder / name)


def _cleanup_private_files(files, paths):
    if not isinstance(files, list):
        raise ValueError('Private media cleanup receipt is unreadable.')
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}:
            raise ValueError('Private media cleanup receipt has an invalid entry.')
        try:
            path = Path(entry['path'])
            relative = path.relative_to(paths.data)
        except (TypeError, ValueError):
            raise ValueError('Private media cleanup path is outside Relay data.') from None
        valid = False
        if len(relative.parts) == 2 and relative.parts[0] == 'gemini-runs':
            valid = bool(re.fullmatch(r'[A-Za-z0-9-]{1,80}(?:\.input)?\.json', relative.name))
        elif len(relative.parts) == 2 and relative.parts[0] == 'results':
            valid = bool(re.fullmatch(r'[A-Za-z0-9-]{1,80}\.md', relative.name))
        if not valid:
            raise ValueError('Private media cleanup path is not a Relay provider trace.')
        if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise ValueError('Private media cleanup path is a symbolic link.')
        if not path.exists():
            continue
        if (not path.is_file() or entry['sha256'] is None or
                hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']):
            raise ValueError('Private media file changed after deletion review.')
        path.unlink()


def recover(pid, paths=PATHS):
    with closing(_database(paths, writable=True)) as db:
        _prepare(db)
        receipt = db.execute('SELECT * FROM relay_delete_receipts WHERE id=?', (pid,)).fetchone()
        if not receipt: raise JobDeleteError('No deletion receipt exists for this pipeline.')
        if receipt['status'] == 'complete': return {'id':pid, 'status':'complete'}
    base = paths.generated.resolve() / 'workflows'
    folder = base / pid
    try:
        if folder.is_symlink(): raise ValueError('Workflow folder is a symbolic link.')
        if folder.exists():
            from .host import HOST
            if base.is_symlink(): raise ValueError('Workflow path contains a symbolic link.')
            lock = base / ('.' + pid + '.lock')
            if lock.is_symlink(): raise ValueError('Workflow lock is a symbolic link.')
            # The exporter uses this same lock. If publication is in progress,
            # leave the receipt pending for a later retry.
            with lock.open('a') as stream:
                HOST.lock(stream)
                _cleanup_view(folder, pid)
        _cleanup_private_files(json.loads(receipt['files']), paths)
        with closing(_database(paths, writable=True)) as db, transaction(db):
            db.execute("UPDATE relay_delete_receipts SET status='complete',error=NULL WHERE id=?", (pid,))
        return {'id':pid, 'status':'complete'}
    except Exception as exc:
        with closing(_database(paths, writable=True)) as db, transaction(db):
            db.execute("UPDATE relay_delete_receipts SET status='cleanup_pending',error=? WHERE id=?", (str(exc),pid))
        return {'id':pid, 'status':'cleanup_pending', 'error':str(exc)}


def pending(paths=PATHS):
    if not paths.state.is_file(): return []
    with closing(_database(paths)) as db:
        if not _table(db, 'relay_delete_receipts'): return []
        return [dict(r) for r in db.execute("SELECT id,status,error FROM relay_delete_receipts WHERE status='cleanup_pending' ORDER BY created")]


def recover_pending(paths=PATHS):
    """Retry committed cleanup receipts at service startup; never replay deletion."""
    return [recover(row['id'], paths) for row in pending(paths)]
