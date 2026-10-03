"""Desktop-independent, read-only process ledger for a committed Relay job."""

from collections import defaultdict
import json
from pathlib import Path
import sqlite3


SCHEMA = 'task-relay.job-process'
VERSION = 10  # Includes continuation review and selection decisions.
CATEGORIES = ('requests', 'stage_plans', 'assignments', 'attempts', 'checks',
              'decisions', 'exceptions', 'recovery_receipts', 'decision_controls',
              'change_plans',
              'events', 'channel_history')


def _table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def collect(db, report, plans, runs):
    """Copy exact authoritative rows inside the caller's committed read transaction."""
    if not db.in_transaction:
        raise ValueError('Read the job process inside the committed snapshot transaction.')
    records = []
    gaps = []
    counts = defaultdict(int)
    missing_tables = set()
    known_artifacts = {artifact['id'] for artifact in report['artifacts']}

    def add(category, table, row, *, stage=None, run=None, scope=None):
        value = dict(row)
        source_rowid = value.pop('_source_rowid', None)
        identity = next((value[key] for key in ('id', 'request_id', 'token') if key in value), None)
        if identity is None:
            identity = source_rowid
        records.append({'category': category, 'source_table': table, 'source_id': str(identity),
                        'stage': stage, 'run': run, 'scope': scope, 'data': value})
        counts[category] += 1

    def rows(table, where='', args=()):
        if not _table(db, table):
            if table not in missing_tables:
                missing_tables.add(table)
                gaps.append({'category': None, 'kind': 'source_table_unavailable',
                             'source_table': table, 'source_id': None,
                             'reason': 'This authoritative table is unavailable.'})
            return []
        return db.execute('SELECT rowid AS _source_rowid,* FROM ' + table + (' WHERE ' + where if where else '')
                          + ' ORDER BY rowid', args).fetchall()

    pid = report['id']
    for table, category in (('relay_computer_assignments', 'assignments'),
                            ('relay_computer_actions', 'attempts'),
                            ('relay_computer_decisions', 'recovery_receipts'),
                            ('relay_computer_packs', 'assignments'),
                            ('relay_computer_reviews', 'checks')):
        if _table(db, table):
            for row in rows(table, 'job=?', (pid,)):
                add(category, table, row, scope='native_computer_session')
    if report.get('kind') == 'production_result':
        owner = rows('relay_standalone_jobs', 'id=?', (pid,))
        if owner:
            add('assignments', 'relay_standalone_jobs', owner[0], scope='job_ownership')
        else:
            gaps.append({'category': 'assignments', 'kind': 'missing_standalone_ownership',
                         'source_table': 'relay_standalone_jobs', 'source_id': pid,
                         'reason': 'This exported result has no authoritative standalone ownership record.'})
    if report.get('kind', 'pipeline') == 'pipeline':
        pipeline = rows('relay_pipelines', 'id=?', (pid,))
        if not pipeline:
            gaps.append({'category': 'requests', 'kind': 'missing_pipeline', 'source_table': 'relay_pipelines',
                         'source_id': pid, 'reason': 'The referenced pipeline row is missing.'})
        for row in pipeline:
            add('requests', 'relay_pipelines', row)
        step_requests = rows('relay_pipeline_requests', 'pipeline=?', (pid,))
        for row in step_requests:
            add('requests', 'relay_pipeline_requests', row, stage=row['step'])
        requested = {row['request_id'] for row in step_requests}
        stages = rows('relay_pipeline_steps', 'pipeline=?', (pid,))
        saved_stages = {stage['id'] for stage in stages}
        for expected in report['plan'].get('stages', []):
            if isinstance(expected, dict) and expected.get('id') not in saved_stages:
                gaps.append({'category': 'stage_plans', 'kind': 'missing_stage',
                             'source_table': 'relay_pipeline_steps', 'source_id': str(expected.get('id')),
                             'reason': 'The pipeline specification names a stage with no committed row.'})
        for stage in stages:
            add('stage_plans', 'relay_pipeline_steps', stage, stage=stage['id'])
            if stage['error']:
                add('exceptions', 'relay_pipeline_steps', stage, stage=stage['id'])
            if stage['request_id'] is not None and stage['request_id'] not in requested:
                gaps.append({'category': 'requests', 'kind': 'missing_stage_request',
                             'source_table': 'relay_pipeline_requests', 'source_id': str(stage['request_id']),
                             'reason': 'A stage references a request without its frozen inputs.'})
        for row in rows('relay_pipeline_events', 'pipeline=?', (pid,)):
            category = ('recovery_receipts' if any(word in row['kind'] for word in
                        ('recover', 'repair', 'retry', 'continu', 'resume', 'correct')) else
                        'exceptions' if any(word in row['kind'] for word in
                        ('fail', 'block', 'cancel', 'uncertain')) else
                        'decisions' if any(word in row['kind'] for word in
                        ('select', 'accept', 'approve', 'reject', 'discard', 'decision')) else 'events')
            add(category, 'relay_pipeline_events', row, stage=row['step'])
        for row in rows('production_auto_repairs', 'pipeline=?', (pid,)):
            add('recovery_receipts', 'production_auto_repairs', row, stage=row['step'], run=row['parent'])
            if row['error']:
                add('exceptions', 'production_auto_repairs', row, stage=row['step'], run=row['parent'])

    for plan in sorted(plans):
        found = rows('production_plans', 'id=?', (plan,))
        if not found:
            gaps.append({'category': 'stage_plans', 'kind': 'missing_plan',
                         'source_table': 'production_plans', 'source_id': plan,
                         'reason': 'A stage references a plan that is absent.'})
            continue
        row = found[0]
        add('stage_plans', 'production_plans', row, run=row['run'])
        add('requests', 'production_plans', row, run=row['run'])
        if row['error']:
            add('exceptions', 'production_plans', row, run=row['run'])
        calls = rows('production_plan_calls', 'plan_id=?', (plan,))
        if row['calls'] > len(calls):
            gaps.append({'category': 'recovery_receipts', 'kind': 'missing_plan_call',
                         'source_table': 'production_plan_calls', 'source_id': plan,
                         'reason': 'The plan call counter exceeds its saved call receipts.'})
        for call in calls:
            add('recovery_receipts', 'production_plan_calls', call, run=row['run'])
            if call['error']:
                add('exceptions', 'production_plan_calls', call, run=row['run'])
        for link in rows('production_stage_links', 'plan_id=?', (plan,)):
            add('recovery_receipts', 'production_stage_links', link, run=link['parent'])

    for run in sorted(runs):
        found = rows('production_runs', 'id=?', (run,))
        if not found:
            gaps.append({'category': 'stage_plans', 'kind': 'missing_run',
                         'source_table': 'production_runs', 'source_id': run,
                         'reason': 'A stage or plan references a run that is absent.'})
        else:
            add('stage_plans', 'production_runs', found[0], run=run)
        assignments = rows('production_assignments', 'run=?', (run,))
        for row in assignments:
            add('assignments', 'production_assignments', row, run=run)
        assignment_ids = {row['id'] for row in assignments}
        tasks = rows('production_tasks', 'run=?', (run,))
        for row in tasks:
            if row['assignment'] not in assignment_ids:
                gaps.append({'category': 'assignments', 'kind': 'missing_assignment',
                             'source_table': 'production_assignments', 'source_id': row['assignment'],
                             'reason': 'A production task references an absent assignment.'})
        attempts = rows('production_attempts', 'run=?', (run,))
        attempt_ids = {row['id'] for row in attempts}
        for row in attempts:
            add('attempts', 'production_attempts', row, run=run)
            if row['receipt'] is not None:
                add('recovery_receipts', 'production_attempts', row, run=run)
            if row['assignment'] not in assignment_ids:
                gaps.append({'category': 'assignments', 'kind': 'missing_attempt_assignment',
                             'source_table': 'production_assignments', 'source_id': row['assignment'],
                             'reason': 'An attempt references an absent frozen assignment.'})
            if row['receipt'] is None:
                gaps.append({'category': 'recovery_receipts',
                             'kind': 'pending_receipt' if row['state'] in ('launching', 'running', 'cancelling') else 'missing_receipt',
                             'source_table': 'production_attempts', 'source_id': row['id'],
                             'reason': 'The attempt has no completion receipt at this snapshot.'})
            if row['error']:
                add('exceptions', 'production_attempts', row, run=run)
        for row in tasks:
            if row['latest'] and row['latest'] not in attempt_ids:
                gaps.append({'category': 'attempts', 'kind': 'missing_latest_attempt',
                             'source_table': 'production_attempts', 'source_id': row['latest'],
                             'reason': 'A production task references an absent latest attempt.'})
        checked_attempts = set()
        for row in rows('production_events', 'run=?', (run,)):
            kind = row['kind']
            if kind == 'checks_recorded' and row['attempt']:
                checked_attempts.add(row['attempt'])
            category = ('checks' if kind == 'checks_recorded' else
                        'recovery_receipts' if any(word in kind for word in ('recover', 'repair', 'retry', 'revis', 'continu', 'resum', 'correct')) else
                        'exceptions' if any(word in kind for word in ('fail', 'block', 'cancel', 'uncertain')) else
                        'decisions' if any(word in kind for word in
                        ('select', 'accept', 'approve', 'reject', 'discard', 'decision')) else 'events')
            add(category, 'production_events', row, run=run)
        for attempt in attempts:
            if attempt['id'] in checked_attempts:
                continue
            pending = attempt['state'] in ('launching', 'running', 'cancelling')
            succeeded = False
            if attempt['receipt']:
                receipt = json.loads(attempt['receipt'])
                succeeded = receipt.get('status') == 'finished' and receipt.get('exit_code') == 0
            gaps.append({'category': 'checks',
                         'kind': 'pending_checks' if pending else 'missing_checks' if succeeded else 'checks_not_reached',
                         'source_table': 'production_events', 'source_id': attempt['id'],
                         'reason': 'No checks_recorded event exists for this attempt at this snapshot.'})
        for row in rows('production_decisions', 'run=?', (run,)):
            add('decisions', 'production_decisions', row, run=run)
            if row['artifact'] not in known_artifacts:
                gaps.append({'category': 'decisions', 'kind': 'missing_selected_artifact',
                             'source_table': 'production_artifacts', 'source_id': row['artifact'],
                             'reason': 'A recorded decision references an artifact absent from the job view.'})
        for table, category in (('production_revisions', 'recovery_receipts'),
                                ('production_user_notes', 'requests'),
                                ('production_selection_cards', 'decision_controls'),
                                ('production_control_cards', 'decision_controls'),
                                ('production_replacement_cards', 'decision_controls'),
                                ('production_visual_review_cards', 'decision_controls')):
            for row in rows(table, 'run=?', (run,)):
                add(category, table, row, run=run)
        for row in rows('production_continuations', 'parent=? OR child=?', (run, run)):
            key = str(row['id'])
            if not any(r['source_table'] == 'production_continuations' and r['source_id'] == key for r in records):
                add('recovery_receipts', 'production_continuations', row, run=run)
                add('requests', 'production_continuations', row, run=run)
                if row['error']:
                    add('exceptions', 'production_continuations', row, run=run)

    from . import impact_handoff
    handoffs = rows('relay_impact_handoffs', 'job=?', (pid,))
    handoff_ids = {row['id'] for row in handoffs}
    for row in handoffs:
        add('change_plans', 'relay_impact_handoffs', row)
        if row['baseline_artifact'] not in known_artifacts:
            gaps.append({'category': 'change_plans', 'kind': 'missing_change_baseline',
                         'source_table': 'production_artifacts',
                         'source_id': row['baseline_artifact'],
                         'reason': 'A change plan references an absent baseline artifact.'})
        try:
            if impact_handoff._digest(json.loads(row['plan'])) != row['plan_digest']:
                raise ValueError('Plan digest changed.')
        except (ValueError, TypeError):
            gaps.append({'category': 'change_plans', 'kind': 'invalid_change_plan',
                         'source_table': 'relay_impact_handoffs', 'source_id': row['id'],
                         'reason': 'A frozen change plan is malformed or its digest changed.'})
        if row['kind'] == impact_handoff.XLSX_FACT_CHANGE:
            try:
                inputs = json.loads(row['inputs'])
                sources = (inputs['old_source'], inputs['replacement_source'])
                if any(not isinstance(item, str) or item not in known_artifacts
                       for item in sources):
                    raise ValueError('Source artifact missing.')
            except (ValueError, TypeError, KeyError):
                gaps.append({'category': 'change_plans', 'kind': 'missing_xlsx_handoff_source',
                             'source_table': 'relay_impact_handoffs', 'source_id': row['id'],
                             'reason': 'Frozen XLSX handoff has an absent or unreadable source version.'})

    submitted = rows('relay_agent_candidates', 'job=?', (pid,))
    submitted_ids = {row['candidate_artifact'] for row in submitted}
    for row in submitted:
        add('assignments', 'relay_agent_candidates', row)
        add('checks', 'relay_agent_candidates', row)
        if row['handoff_id'] not in handoff_ids:
            gaps.append({'category': 'change_plans', 'kind': 'missing_candidate_handoff',
                         'source_table': 'relay_impact_handoffs', 'source_id': row['handoff_id'],
                         'reason': 'An agent candidate references an absent change plan.'})
        if row['candidate_artifact'] not in known_artifacts:
            gaps.append({'category': 'assignments', 'kind': 'missing_agent_candidate',
                         'source_table': 'production_artifacts', 'source_id': row['candidate_artifact'],
                         'reason': 'An agent candidate artifact is absent from the job view.'})
        try:
            from orchestrator import pptx_edit
            manifest = pptx_edit.validate(json.loads(row['manifest']))
            expected_images = {edit['path'] for edit in manifest['edits']
                               if edit['kind'] == 'replace_image'}
        except (ValueError, TypeError, KeyError):
            gaps.append({'category': 'assignments', 'kind': 'invalid_agent_candidate_manifest',
                         'source_table': 'relay_agent_candidates', 'source_id': row['id'],
                         'reason': 'The saved candidate edit manifest is malformed.'})
        else:
            recorded_images = {item['path'] for item in rows(
                'relay_agent_candidate_inputs', 'candidate_artifact=?',
                (row['candidate_artifact'],))}
            if expected_images != recorded_images:
                gaps.append({'category': 'assignments', 'kind': 'missing_declared_candidate_input',
                             'source_table': 'relay_agent_candidate_inputs',
                             'source_id': row['candidate_artifact'],
                             'reason': 'Declared picture inputs do not match the saved input rows.'})
    for row in rows('relay_agent_candidate_inputs', 'job=?', (pid,)):
        add('assignments', 'relay_agent_candidate_inputs', row)
        if row['candidate_artifact'] not in submitted_ids or row['artifact'] not in known_artifacts:
            gaps.append({'category': 'assignments', 'kind': 'missing_agent_candidate_input',
                         'source_table': 'relay_agent_candidate_inputs',
                         'source_id': row['candidate_artifact'],
                         'reason': 'A declared candidate image or owner is absent.'})
    agent_artifacts = submitted_ids | {row['artifact'] for row in rows(
        'relay_agent_candidate_inputs', 'job=?', (pid,))}
    agent_events = set()
    artifact_versions = {artifact['id']: artifact for artifact in report['artifacts']}
    if agent_artifacts:
        for row in rows('production_events', 'task=?', ('agent_candidate',)):
            try:
                payload = json.loads(row['data'])
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict) or payload.get('artifact') not in agent_artifacts:
                continue
            add('events', 'production_events', row, scope='agent_candidate')
            artifact = artifact_versions.get(payload['artifact'])
            if (row['run'] is not None or row['attempt'] is not None
                    or row['kind'] != 'artifact_registered' or artifact is None
                    or payload.get('sha256') != artifact['sha256']
                    or payload.get('path') != artifact['path']):
                gaps.append({'category': 'events', 'kind': 'invalid_agent_registration_receipt',
                             'source_table': 'production_events',
                             'source_id': str(row['_source_rowid']),
                             'reason': 'An agent candidate registration event differs from its artifact.'})
            agent_events.add(payload['artifact'])
        for artifact in sorted(agent_artifacts - agent_events):
            gaps.append({'category': 'events', 'kind': 'missing_agent_registration_receipt',
                         'source_table': 'production_events', 'source_id': artifact,
                         'reason': 'An agent candidate artifact has no registration event.'})
    for table in ('relay_agent_candidate_reviews', 'relay_agent_candidate_selections'):
        for candidate_id in submitted_ids:
            for row in rows(table, 'candidate_artifact=?', (candidate_id,)):
                add('decisions', table, row)
    for row in rows('relay_agent_candidate_feedback', 'job=?', (pid,)):
        add('decisions', 'relay_agent_candidate_feedback', row,
            scope=row['scope'])
        if row['candidate_artifact'] not in submitted_ids:
            gaps.append({'category': 'decisions', 'kind': 'missing_feedback_candidate',
                         'source_table': 'relay_agent_candidate_feedback',
                         'source_id': row['id'],
                         'reason': 'Scoped feedback references an absent candidate.'})
    bundle_plans = rows('relay_revision_bundle_plans', 'job=?', (pid,))
    plan_ids = {row['id'] for row in bundle_plans}
    for row in bundle_plans:
        add('change_plans', 'relay_revision_bundle_plans', row)
        if row['handoff_id'] not in handoff_ids:
            gaps.append({'category': 'change_plans', 'kind': 'missing_bundle_handoff',
                         'source_table': 'relay_revision_bundle_plans',
                         'source_id': row['id'],
                         'reason': 'Companion plan has no frozen native handoff.'})
    bundles = rows('relay_revision_bundles', 'job=?', (pid,))
    bundle_ids = {row['id'] for row in bundles}
    for row in bundles:
        add('assignments', 'relay_revision_bundles', row)
        add('checks', 'relay_revision_bundles', row)
        if row['plan_id'] not in plan_ids or row['pptx_candidate'] not in submitted_ids:
            gaps.append({'category': 'assignments', 'kind': 'missing_bundle_parent',
                         'source_table': 'relay_revision_bundles',
                         'source_id': row['id'],
                         'reason': 'Revision bundle has no frozen plan or PPTX candidate.'})
    for row in rows('relay_revision_bundle_files', 'job=?', (pid,)):
        add('assignments', 'relay_revision_bundle_files', row)
        if row['bundle_id'] not in bundle_ids or row['candidate_artifact'] not in known_artifacts:
            gaps.append({'category': 'assignments', 'kind': 'missing_bundle_file',
                         'source_table': 'relay_revision_bundle_files',
                         'source_id': row['candidate_artifact'],
                         'reason': 'A companion candidate or parent bundle is absent.'})
    for table in ('relay_revision_bundle_reviews', 'relay_revision_bundle_selections'):
        for row in rows(table, 'job=?', (pid,)):
            add('decisions', table, row)
            if row['bundle_id'] not in bundle_ids:
                gaps.append({'category': 'decisions', 'kind': 'missing_bundle_decision_parent',
                             'source_table': table, 'source_id': row['bundle_id'],
                             'reason': 'Revision decision references an absent bundle.'})
    followon_plans = rows('relay_bundle_continuation_plans', 'job=?', (pid,))
    followon_plan_ids = {row['id'] for row in followon_plans}
    for row in followon_plans:
        add('change_plans', 'relay_bundle_continuation_plans', row)
        if row['parent_bundle'] not in bundle_ids:
            gaps.append({'category': 'change_plans', 'kind': 'missing_continuation_parent',
                         'source_table': 'relay_bundle_continuation_plans',
                         'source_id': row['id'],
                         'reason': 'Continuation plan has no selected parent bundle.'})
    followon_candidates = rows('relay_bundle_continuations', 'job=?', (pid,))
    followon_ids = {row['id'] for row in followon_candidates}
    for row in followon_candidates:
        add('assignments', 'relay_bundle_continuations', row)
        add('checks', 'relay_bundle_continuations', row)
        if (row['plan_id'] not in followon_plan_ids
                or any(row[key] not in known_artifacts for key in
                       ('pptx_artifact', 'slides_artifact', 'photo_manifest_artifact'))):
            gaps.append({'category': 'assignments', 'kind': 'missing_continuation_file',
                         'source_table': 'relay_bundle_continuations',
                         'source_id': row['id'],
                         'reason': 'Continuation parent or candidate artifact is absent.'})
    for table in ('relay_bundle_continuation_reviews',
                  'relay_bundle_continuation_selections'):
        for row in rows(table, 'job=?', (pid,)):
            add('decisions', table, row)
            if row['candidate_id'] not in followon_ids:
                gaps.append({'category': 'decisions', 'kind': 'missing_continuation_decision_parent',
                             'source_table': table, 'source_id': row['candidate_id'],
                             'reason': 'Continuation decision references an absent candidate.'})

    candidate_ids = set()
    for name in ('relay_fact', 'relay_translation', 'relay_presentation'):
        reviews, selections, revisions = (name + '_reviews', name + '_selections', name + '_revisions')
        if name == 'relay_fact':
            reviews = 'relay_fact_candidate_reviews'
        for table, category in ((reviews, 'checks'), (reviews, 'decisions'),
                                (selections, 'decisions'), (revisions, 'recovery_receipts')):
            for row in rows(table, 'job=?', (pid,)):
                add(category, table, row)
                if 'candidate_artifact' in row.keys():
                    candidate_ids.add(row['candidate_artifact'])
    for row in rows('relay_fact_external_submissions', 'job=?', (pid,)):
        add('assignments', 'relay_fact_external_submissions', row)
        add('checks', 'relay_fact_external_submissions', row)
        gaps.append({'category': 'assignments', 'kind': 'external_agent_dispatch_outside_runtime',
                     'source_table': 'relay_fact_external_submissions',
                     'source_id': row['id'],
                     'reason': 'The returned candidate is registered, but Relay has no provider dispatch or attempt receipt for this external agent.'})
        if row['handoff_id'] not in handoff_ids or row['candidate_artifact'] not in candidate_ids:
            gaps.append({'category': 'assignments', 'kind': 'missing_external_xlsx_parent',
                         'source_table': 'relay_fact_external_submissions',
                         'source_id': row['id'],
                         'reason': 'External XLSX submission has no frozen handoff or candidate.'})
    for candidate in sorted(candidate_ids):
        for row in rows('relay_revision_action_receipts', 'candidate_artifact=?', (candidate,)):
            add('decisions', 'relay_revision_action_receipts', row)

    if report.get('kind', 'pipeline') == 'pipeline':
        linked_stages = {stage['id'] for stage in stages
                         if stage['target_kind'] == 'generate_image' and stage['target']}
        for orphan in rows('relay_pipeline_task_links', 'pipeline=?', (pid,)):
            if orphan['step'] not in linked_stages:
                add('assignments', 'relay_pipeline_task_links', orphan,
                    stage=orphan['step'], scope='relationship')
                gaps.append({'category': 'assignments', 'kind': 'orphan_media_task_link',
                             'source_table': 'relay_pipeline_task_links', 'source_id': orphan['step'],
                             'reason': 'The saved agent task link has no matching media stage target.'})
        for stage in stages:
            if stage['target_kind'] != 'generate_image' or not stage['target']:
                continue
            sid, media_job = stage['id'], stage['target']
            link = rows('relay_pipeline_task_links', 'pipeline=? AND step=?', (pid, sid))
            backend = rows('backend_jobs', 'id=?', (media_job,))
            if not link:
                gaps.append({'category': 'assignments', 'kind': 'missing_media_task_link',
                             'source_table': 'relay_pipeline_task_links', 'source_id': sid,
                             'reason': 'This media stage has no verified request-to-agent-task link.'})
            for item in link:
                add('assignments', 'relay_pipeline_task_links', item, stage=sid, scope='relationship')
            if not backend:
                gaps.append({'category': 'attempts', 'kind': 'missing_media_backend_job',
                             'source_table': 'backend_jobs', 'source_id': media_job,
                             'reason': 'The media stage references a missing backend job.'})
                continue
            job = backend[0]
            media_requests = rows('orchestrator_image_requests', 'job_id=?', (stage['request_id'],))
            for item in media_requests:
                add('requests', 'orchestrator_image_requests', item, stage=sid, scope='stage_execution')
            if not media_requests or (media_requests[0]['backend_job_id'] != media_job or
                                      media_requests[0]['task_id'] != job['thread_id']):
                gaps.append({'category': 'requests', 'kind': 'media_request_mismatch',
                             'source_table': 'orchestrator_image_requests', 'source_id': str(stage['request_id']),
                             'reason': 'The saved image request does not identify this stage backend job and task.'})
            media_chats = rows('orchestrator_chats', 'id=?', (stage['request_id'],))
            if not media_chats:
                gaps.append({'category': 'requests', 'kind': 'missing_media_stage_request',
                             'source_table': 'orchestrator_chats', 'source_id': str(stage['request_id']),
                             'reason': 'The media stage request record is missing.'})
            for item in media_chats:
                add('requests', 'orchestrator_chats', item, stage=sid, scope='stage_execution')
            for item in rows('capability_dispatches', 'job_id=?', (stage['request_id'],)):
                add('recovery_receipts', 'capability_dispatches', item, stage=sid, scope='stage_execution')
            if link and (link[0]['request_id'] != stage['request_id'] or
                         link[0]['backend_job_id'] != media_job or link[0]['task_id'] != job['thread_id']):
                gaps.append({'category': 'assignments', 'kind': 'media_task_link_mismatch',
                             'source_table': 'relay_pipeline_task_links', 'source_id': sid,
                             'reason': 'The saved media link disagrees with the stage or backend job.'})
            add('attempts', 'backend_jobs', job, stage=sid, scope='stage_execution')
            task_id = job['thread_id']
            for table in ('backend_tasks', 'watched'):
                task_rows = rows(table, 'id=?', (task_id,))
                if not task_rows:
                    gaps.append({'category': 'assignments', 'kind': 'missing_media_task',
                                 'source_table': table, 'source_id': task_id,
                                 'reason': 'The separate agent task record is missing.'})
                for item in task_rows:
                    add('assignments', table, item, stage=sid, scope='separate_task_reference')
            gaps.append({'category': 'channel_history', 'kind': 'outside_job_scope',
                         'source_table': 'messages', 'source_id': task_id,
                         'reason': 'This task shares a conversation channel; individual channel messages cannot be assigned to this media stage.'})
            for table in ('gemini_runs', 'gemini_history', 'gemini_tool_runs', 'tool_requests'):
                for item in rows(table, 'job_id=?', (media_job,)):
                    add('attempts' if table != 'tool_requests' else 'decisions', table, item,
                        stage=sid, scope='stage_execution')
            for item in rows('artifacts', 'job_id=?', (media_job,)):
                add('assignments', 'artifacts', item, stage=sid, scope='stage_output')
            run = rows('gemini_runs', 'job_id=?', (media_job,))
            if not run:
                gaps.append({'category': 'attempts', 'kind': 'missing_media_run',
                             'source_table': 'gemini_runs', 'source_id': media_job,
                             'reason': 'The media backend job has no provider run record.'})
            else:
                try:
                    references = json.loads(run[0]['options_json']).get('references', [])
                except (ValueError, TypeError, AttributeError):
                    references = None
                if not isinstance(references, list):
                    gaps.append({'category': 'assignments', 'kind': 'unreadable_media_inputs',
                                 'source_table': 'gemini_runs', 'source_id': media_job,
                                 'reason': 'The frozen media input references are unreadable.'})
                else:
                    for reference in references:
                        ident = reference.get('id') if isinstance(reference, dict) else None
                        if not ident:
                            gaps.append({'category': 'assignments', 'kind': 'unidentified_media_input',
                                         'source_table': 'gemini_runs', 'source_id': media_job,
                                         'reason': 'A frozen media input has no artifact ID.'})
                            continue
                        input_rows = rows('artifacts', 'id=?', (ident,))
                        if not input_rows:
                            gaps.append({'category': 'assignments', 'kind': 'missing_media_input',
                                         'source_table': 'artifacts', 'source_id': ident,
                                         'reason': 'A frozen media input artifact is missing.'})
                        elif reference.get('sha256') != input_rows[0]['sha256']:
                            gaps.append({'category': 'assignments', 'kind': 'changed_media_input',
                                         'source_table': 'artifacts', 'source_id': ident,
                                         'reason': 'The registered media input hash differs from the frozen request.'})
                        for item in input_rows:
                            add('assignments', 'artifacts', item, stage=sid, scope='referenced_input')
            for item in rows('incoming', 'id=?', (job['update_id'],)):
                add('requests', 'incoming', item, stage=sid, scope='stage_execution')
            event_ids = {f'image-request:{job["update_id"]}'}
            for prefix in (f'backend:{media_job}:', f'pipeline:{pid}:{sid}:',
                           f'orchestrator:{stage["request_id"]}:'):
                for item in rows('outbox', 'substr(id,1,?)=?', (len(prefix), prefix)):
                    event_ids.add(item['id'])
            for event_id in sorted(event_ids):
                for item in rows('outbox', 'id=?', (event_id,)):
                    add('channel_history', 'outbox', item, stage=sid, scope='exact_delivery_receipt')
                for table in ('outbox_parts', 'media_outbox', 'relay_event_channels'):
                    for item in rows(table, 'event_id=?', (event_id,)):
                        add('channel_history', table, item, stage=sid, scope='exact_delivery_receipt')

    for item in report.get('missing_artifacts', []):
        gaps.append({'category': 'assignments', 'kind': 'missing_artifact',
                     'source_table': 'production_artifacts', 'source_id': item,
                     'reason': 'A referenced artifact is not registered.'})
    gaps.append({'category': 'channel_history', 'kind': 'outside_job_scope',
                 'source_table': 'outbox', 'source_id': None,
                 'reason': 'Exact stage delivery receipts are linked above; the wider messenger conversation has no per-job ownership key.'})
    non_missing = {'pending_receipt', 'pending_checks', 'checks_not_reached', 'outside_job_scope'}
    coverage = [{'category': category,
                 'state': ('incomplete' if any(g['category'] in (category, None) and g['kind'] not in non_missing for g in gaps)
                           else 'pending' if any(g['category'] == category and g['kind'] in ('pending_receipt', 'pending_checks') for g in gaps)
                           else 'not_recorded' if any(g['category'] == category and g['kind'] == 'checks_not_reached' for g in gaps)
                           else 'external' if any(g['category'] == category and g['kind'] == 'outside_job_scope' for g in gaps)
                           else 'complete' if counts[category] else 'empty'),
                 'record_count': counts[category]} for category in CATEGORIES]
    return {'schema': SCHEMA, 'version': VERSION, 'records': records, 'coverage': coverage,
            'gaps': gaps, 'complete': not any(g['kind'] not in non_missing for g in gaps),
            'scope': 'Committed records reachable from this pipeline and its registered plan/run ancestry; media tasks and shared conversations remain separate.'}


def add_projection(db, report):
    """Add exact process rows to a disposable job SQLite file."""
    process = report['process']
    db.execute('''CREATE TABLE process_records(
        category TEXT NOT NULL, source_table TEXT NOT NULL, source_id TEXT NOT NULL,
        stage TEXT, run TEXT, scope TEXT, record TEXT NOT NULL)''')
    db.execute('CREATE INDEX process_records_category ON process_records(category,source_table)')
    db.execute('''CREATE TABLE process_coverage(
        category TEXT PRIMARY KEY,state TEXT NOT NULL,record_count INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE process_gaps(
        category TEXT,kind TEXT NOT NULL,source_table TEXT NOT NULL,
        source_id TEXT,reason TEXT NOT NULL)''')
    for row in process['records']:
        db.execute('INSERT INTO process_records VALUES (?,?,?,?,?,?,?)',
                   (row['category'], row['source_table'], row['source_id'], row['stage'], row['run'], row['scope'],
                    json.dumps(row['data'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))))
    for row in process['coverage']:
        db.execute('INSERT INTO process_coverage VALUES (?,?,?)',
                   (row['category'], row['state'], row['record_count']))
    for row in process['gaps']:
        db.execute('INSERT INTO process_gaps VALUES (?,?,?,?,?)',
                   tuple(row[k] for k in ('category', 'kind', 'source_table', 'source_id', 'reason')))
    db.execute('INSERT INTO meta VALUES (?,?)', ('process_schema', SCHEMA))
    db.execute('INSERT INTO meta VALUES (?,?)', ('process_version', str(VERSION)))
    db.execute('INSERT INTO meta VALUES (?,?)', ('process_complete', str(process['complete']).lower()))


def inspect(path):
    """Read a published per-job view without the desktop app or the shared database."""
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        meta = dict(db.execute('SELECT key,value FROM meta'))
        if 'process_schema' not in meta:
            return {'job': meta.get('job'), 'snapshot': meta.get('snapshot'),
                    'process_schema': None, 'process_version': None, 'complete': False,
                    'coverage': [], 'gaps': [{'category': None, 'kind': 'legacy_process_missing',
                    'source_table': 'process_records', 'source_id': None,
                    'reason': 'This older job view does not contain the process ledger.'}]}
        coverage = [dict(row) for row in db.execute('SELECT * FROM process_coverage ORDER BY category')]
        gaps = [dict(row) for row in db.execute('SELECT * FROM process_gaps ORDER BY rowid')]
    return {'job': meta['job'], 'snapshot': meta['snapshot'], 'process_schema': meta['process_schema'],
            'process_version': int(meta['process_version']),
            'complete': meta['process_complete'] == 'true', 'coverage': coverage, 'gaps': gaps}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inspect a read-only .relay/job.sqlite process record.')
    parser.add_argument('path')
    print(json.dumps(inspect(parser.parse_args().path), ensure_ascii=False, indent=2))
