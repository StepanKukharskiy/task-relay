"""Versioned observations of saved execution records, never dispatch authority.

Adapters read database rows only. They neither open output files nor call workers.
An envelope records what the owning runtime knew at capture time; completion,
validation, selection and delivery remain separate observations.
"""
import json
import hashlib
from pathlib import Path
import time

from . import work_state as ws
from .project_context import encoded, model_evidence
from .filesystem import FILES, Grant

SCHEMA = 'task-relay.execution-result'
VERSION = 1
KINDS = ('production_attempt', 'backend_job', 'native_candidate', 'xlsx_candidate',
         'plugin_capture', 'work_text_run', 'revision_bundle', 'bundle_continuation')


class Reader:
    def __init__(self, db):
        self.db = db
        self.original = []

    def rows(self, table, where, args, optional=False):
        if not self.db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone():
            if optional:
                return []
            raise ValueError('Execution source table unavailable: ' + table)
        cursor = self.db.execute('SELECT * FROM ' + table + ' WHERE ' + where + ' ORDER BY rowid', args)
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, row)) for row in cursor.fetchmany(1001)]
        if len(rows) > 1000:
            raise ValueError('Execution source exceeds record budget')
        self.original.append({'table': table, 'rows': rows})
        return rows

    def one(self, table, where, args):
        rows = self.rows(table, where, args)
        if len(rows) != 1:
            raise ValueError('Missing or ambiguous execution source: ' + table)
        return rows[0]


def parsed(value, default=None):
    return json.loads(value) if value is not None else default


def artifact(row):
    return {key: row[key] for key in ('id', 'path', 'sha256', 'bytes', 'purpose', 'source') if key in row}


def observed_status(e, state):
    e['status']['source_state'] = state
    e['status']['execution'] = ({'queued': 'queued', 'prepared': 'queued',
        'launching': 'in_progress', 'running': 'in_progress', 'waiting': 'in_progress',
        'publishing': 'in_progress', 'cancelling': 'in_progress', 'completed': 'completed',
        'failed': 'failed', 'blocked': 'blocked', 'stopped': 'stopped', 'cancelled': 'stopped',
        'uncertain': 'uncertain'}).get(state, 'not_recorded')


def base(kind, ident):
    return {'schema': SCHEMA, 'version': VERSION, 'source': {'kind': kind, 'id': ident},
            'assignment': {'id': None, 'version': None, 'job_id': None, 'task_id': None, 'request': None},
            'executor': {'binding': None, 'provider': None, 'model': None, 'operation': None,
                         'locality': {'model': 'not_recorded', 'execution': 'not_recorded'}},
            'status': {'execution': 'not_recorded', 'source_state': None, 'certainty': 'not_recorded',
                       'validation': 'not_recorded', 'selection': 'not_projected', 'delivery': 'not_projected'},
            'inputs': [], 'outputs': {'artifacts': []}, 'evidence': [],
            'validation': {'checks': []}, 'issues': [], 'receipt': {},
            'limitations': ['Historical database observation; output bytes are not revalidated.',
                            'Capture does not select artifacts, accept work, dispatch or prove delivery.']}


def production(r, e, ident):
    attempt = r.one('production_attempts', 'id=?', (ident,))
    assignment = r.one('production_assignments', 'id=?', (attempt['assignment'],))
    if (assignment['run'], assignment['task']) != (attempt['run'], attempt['task']):
        raise ValueError('Attempt assignment ownership mismatch')
    frozen = parsed(attempt['frozen'])
    if (frozen['assignment_id'], frozen['assignment_version'], frozen['run']) != (ident, assignment['id'], attempt['run']):
        raise ValueError('Frozen attempt identity mismatch')
    spec = parsed(assignment['spec'])
    outputs = r.rows('production_artifacts', 'attempt=?', (ident,))
    if any((a['run'], a['task']) != (attempt['run'], attempt['task']) for a in outputs):
        raise ValueError('Output attempt ownership mismatch')
    events = r.rows('production_events', 'attempt=?', (ident,))
    if any((a['run'], a['task']) != (attempt['run'], attempt['task']) for a in events):
        raise ValueError('Event attempt ownership mismatch')
    e['assignment'].update(id=assignment['id'], version=assignment['version'], job_id=attempt['run'],
                           task_id=attempt['task'], request=spec['instruction'])
    e['assignment']['attempt_id'] = ident
    e['assignment']['brief'] = frozen.get('brief')
    backend = frozen.get('backend', {})
    e['executor'].update(binding=backend, provider=backend.get('provider'),
                         model=backend.get('model'), operation=frozen.get('execution'))
    e['executor']['binding_basis'] = 'frozen_attempt'
    e['executor']['receipt_adapter'] = parsed(attempt['session']).get('adapter')
    e['inputs'] = frozen.get('inputs', [])
    e['outputs']['artifacts'] = [artifact(a) for a in outputs]
    observed_status(e, attempt['state'])
    receipt = parsed(attempt['receipt'], {})
    e['receipt'] = {'attempt': receipt, 'session': parsed(attempt['session']), 'source_error': attempt['error']}
    e['status']['certainty'] = 'uncertain' if attempt['state'] == 'uncertain' or receipt.get('external_outcome') == 'unknown' else 'recorded'
    if attempt['error']:
        e['issues'].append({'basis': 'owning_runtime', 'message': attempt['error']})
    for event in events:
        item = {'id': event['id'], 'kind': event['kind'], 'created': event['created'], 'data': parsed(event['data'])}
        e['evidence'].append(item)
        if event['kind'] == 'checks_recorded':
            e['validation']['checks'].append(item)
            e['issues'].extend(item['data'].get('result', {}).get('findings', []))
    e['assignment']['specification_sha256'] = ws.digest(spec)
    for table in ('operation_record_sets', 'operation_records', 'operation_submissions'):
        rows = r.rows(table, 'attempt=?', (ident,), optional=True)
        if rows:
            e['evidence'].append({'kind': table, 'basis': 'saved_typed_operation_records', 'records': rows})


def backend(r, e, ident):
    job = r.one('backend_jobs', 'id=?', (ident,))
    binding = r.one('backend_tasks', 'id=?', (job['thread_id'],))
    e['assignment'].update(id=ident, job_id=ident, task_id=job['thread_id'], request=job['prompt'])
    e['executor'].update(binding={k: binding[k] for k in ('backend', 'model', 'session_id')},
                         provider=binding['backend'], model=binding['model'])
    e['executor']['binding_basis'] = 'current_task_not_frozen_assignment'
    observed_status(e, job['status'])
    e['status']['certainty'] = 'uncertain' if job['status'] == 'uncertain' else 'recorded'
    e['receipt'] = {k: job[k] for k in ('created_at', 'started_at', 'finished_at', 'cancel', 'cost_usd', 'result_path')}
    runs = r.rows('gemini_runs', 'job_id=?', (ident,), optional=True) + r.rows('api_runs', 'job_id=?', (ident,), optional=True)
    if len(runs) > 1:
        raise ValueError('Ambiguous provider run')
    if runs:
        run = runs[0]
        e['executor']['model'] = run['model']
        e['executor']['operation'] = run.get('capability')
        e['receipt']['provider_run'] = {k: run[k] for k in ('stage', 'operation_name', 'response_path', 'usage_json', 'attempts') if k in run}
        # The current backend task is mutable; do not present it as a frozen
        # historical provider assignment where the source did not save one.
    e['limitations'].append('Direct jobs retain the current task binding, not a frozen executor profile; input coverage may be incomplete.')
    outputs = r.rows('artifacts', 'job_id=?', (ident,), optional=True)
    if any(a['thread_id'] != job['thread_id'] for a in outputs):
        raise ValueError('Provider artifact ownership mismatch')
    for a in outputs:
        item = {**artifact(a), 'bytes': a['size'], 'purpose': a['role'], 'mime': a['mime']}
        (e['inputs'] if a['role'] == 'input' else e['outputs']['artifacts']).append(item)
    for table in ('api_history', 'gemini_history'):
        for item in r.rows(table, 'job_id=?', (ident,), optional=True):
            if item['thread_id'] != job['thread_id']:
                raise ValueError('Provider history ownership mismatch')
            e['evidence'].append({'basis': 'saved_provider_history', 'data': item})


def candidate(r, e, ident, native):
    table = 'relay_agent_candidates' if native else 'relay_fact_external_submissions'
    row = r.one(table, 'id=?', (ident,))
    handoff = r.one('relay_impact_handoffs', 'id=?', (row['handoff_id'],))
    output = r.one('production_artifacts', 'id=?', (row['candidate_artifact'],))
    if handoff['job'] != row['job'] or output['sha256'] != row['candidate_sha256']:
        raise ValueError('Candidate handoff or artifact hash mismatch')
    if ws.digest(parsed(handoff['plan'])) != handoff['plan_digest']:
        raise ValueError('Candidate handoff plan hash mismatch')
    e['assignment'].update(id=handoff['id'], job_id=row['job'], request=handoff['exact_request'])
    e['assignment']['plan_digest'] = handoff['plan_digest']
    e['executor']['binding'] = {'submitted_by': row['submitted_by'], 'submission_key': row['submission_key']}
    e['inputs'] = [{'role': role, 'reference': value} for role, value in parsed(handoff['inputs']).items()]
    for item in e['inputs']:
        if item['role'] in {'baseline_artifact', 'replacement_artifact', 'old_source', 'replacement_source'}:
            item.update(artifact(r.one('production_artifacts', 'id=?', (item['reference'],))))
    if native:
        for item in r.rows('relay_agent_candidate_inputs', 'candidate_artifact=?', (output['id'],), optional=True):
            original = r.one('production_artifacts', 'id=?', (item['artifact'],))
            if item['job'] != row['job'] or item['sha256'] != original['sha256']:
                raise ValueError('Candidate declared input ownership or hash mismatch')
            e['inputs'].append({**artifact(original), 'path': item['path']})
    e['outputs']['artifacts'] = [artifact(output)]
    e['validation']['checks'] = [{'basis': 'submission_checks', 'data': parsed(row['checks'])}]
    e['receipt'] = {'submission_id': ident, 'created': row['created'], 'handoff_id': handoff['id']}
    e['limitations'].append('External submission has no Relay dispatch receipt; a checked candidate is not proof of worker execution.')


def plugin(r, e, ident, pid):
    if pid is None:
        raise ValueError('Plugin capture requires its source project')
    row = r.one('work_result_captures', 'project=? AND hash=?', (pid, ident))
    packet = r.one('work_packets', 'project=? AND id=?', (pid, row['packet_id']))
    original = parsed(row['original'])
    if ws.digest(original) != row['hash'] or ws.digest(parsed(packet['packet'])) != packet['sha256']:
        raise ValueError('Plugin capture or continuation hash mismatch')
    e['assignment'].update(id=packet['id'], version=packet['revision'], job_id=pid, request=packet['request'])
    e['assignment']['packet_sha256'] = packet['sha256']
    e['evidence'] = [{'basis': 'model_report', 'text': original['notes']}]
    e['issues'] = [{'basis': 'model_proposal', 'message': q} for q in original['questions']]
    e['receipt'] = parsed(row['receipt'])
    e['limitations'].append('Assistant notes are reports, not worker execution receipts.')


def bundle(r, e, ident, continuation=False):
    table = 'relay_bundle_continuations' if continuation else 'relay_revision_bundles'
    plans = 'relay_bundle_continuation_plans' if continuation else 'relay_revision_bundle_plans'
    row = r.one(table, 'id=?', (ident,))
    plan = r.one(plans, 'id=?', (row['plan_id'],))
    frozen = parsed(plan['plan'])
    if plan['job'] != row['job'] or ws.digest(frozen) != plan['plan_digest']:
        raise ValueError('Bundle plan ownership or hash mismatch')
    e['assignment'].update(id=plan['id'], job_id=row['job'], request=plan['exact_request'])
    e['assignment']['plan_digest'] = plan['plan_digest']
    e['assignment']['set_digest'] = row['set_digest']
    e['executor']['binding'] = {'submitted_by': row['submitted_by'], 'submission_key': row['submission_key']}
    if continuation:
        members = [{'role': role, 'candidate_artifact': row[key + '_artifact'], 'candidate_sha256': row[key + '_sha256']}
                   for role, key in (('pptx', 'pptx'), ('slides', 'slides'), ('photo_manifest', 'photo_manifest'))]
        e['assignment']['parent_bundle'] = plan['parent_bundle']
        parent = r.one('relay_revision_bundles', 'id=?', (plan['parent_bundle'],))
        selected = r.one('relay_revision_bundle_selections', 'bundle_id=?', (parent['id'],))
        if (parent['job'] != row['job'] or parent['set_digest'] != frozen['parent_set_digest']
                or hashlib.sha256(selected['receipt'].encode()).hexdigest() != frozen['parent_selection_sha256']):
            raise ValueError('Continuation selected parent receipt mismatch')
        e['evidence'].append({'kind': 'parent_selection_receipt', 'authority': 'owning_runtime_decision', 'data': selected})
        e['inputs'] = [{'artifact': frozen['pptx_baseline_artifact'], 'sha256': frozen['pptx_baseline_sha256']},
                       {'artifact': frozen['image_artifact'], 'sha256': frozen['image_sha256']},
                       *frozen['companions'], *frozen['reused']]
    else:
        handoff = r.one('relay_impact_handoffs', 'id=?', (plan['handoff_id'],))
        if handoff['job'] != row['job']:
            raise ValueError('Bundle handoff ownership mismatch')
        native = r.one('production_artifacts', 'id=?', (row['pptx_candidate'],))
        members = [{'role': 'pptx', 'candidate_artifact': native['id'], 'candidate_sha256': native['sha256']},
                   *r.rows('relay_revision_bundle_files', 'bundle_id=?', (ident,))]
        if any(m.get('job', row['job']) != row['job'] for m in members):
            raise ValueError('Bundle member ownership mismatch')
        e['inputs'] = [{'role': role, 'reference': value} for role, value in parsed(handoff['inputs']).items()]
        e['inputs'] += [{'artifact': m['baseline_artifact'], 'sha256': m['baseline_sha256']} for m in members[1:]]
    for member in members:
        output = r.one('production_artifacts', 'id=?', (member['candidate_artifact'],))
        if output['sha256'] != member['candidate_sha256']:
            raise ValueError('Bundle member hash mismatch')
        e['outputs']['artifacts'].append({**artifact(output), 'role': member['role']})
    e['validation']['checks'] = [{'basis': 'bundle_submission_checks', 'data': parsed(row['checks'])}]
    e['receipt'] = {'submission_id': ident, 'created': row['created'], 'plan_id': plan['id'], 'set_digest': row['set_digest']}
    prefix, key = ('relay_bundle_continuation', 'candidate_id') if continuation else ('relay_revision_bundle', 'bundle_id')
    for suffix in ('reviews', 'selections'):
        for decision in r.rows(prefix + '_' + suffix, key + '=?', (ident,), optional=True):
            e['evidence'].append({'kind': suffix, 'authority': 'owning_runtime_decision', 'data': decision})
    e['limitations'].append('Saved native set checks are observations; external worker dispatch is not recorded.')


def work_text(r, e, ident):
    row = r.one('work_text_runs', 'id=?', (ident,))
    packet = r.one('work_packets', 'project=? AND id=?', (row['project'], row['packet_id']))
    if ws.digest(parsed(packet['packet'])) != packet['sha256']:
        raise ValueError('Text continuation hash mismatch')
    e['assignment'].update(id=ident, job_id=row['project'], request=row['request'])
    e['assignment']['packet_sha256'] = packet['sha256']
    e['executor'].update(binding='relay-reviewed-text', operation='write_exact_text')
    e['executor']['locality']['execution'] = 'local'
    observed_status(e, row['status'])
    e['status']['certainty'] = 'recorded'
    e['inputs'] = [{'id': a['id'], **a['data']} for a in parsed(packet['packet'])['selected_artifacts']]
    e['assignment']['specification_sha256'] = ws.digest(parsed(row['specification']))
    e['receipt'] = parsed(row['receipt'], {})
    if e['receipt'].get('artifact_id'):
        record = r.one('work_records', 'project=? AND id=?', (row['project'], e['receipt']['artifact_id']))
        if record['kind'] != 'artifact':
            raise ValueError('Text receipt output is not an artifact')
        e['outputs']['artifacts'] = [{'id': record['id'], **parsed(record['data'])}]


def _inspect(db, kind, ident, source_project=None):
    if kind not in KINDS:
        raise ValueError('Unsupported execution source kind')
    ws.identity(ident)
    r = Reader(db); e = base(kind, ident)
    if kind == 'production_attempt': production(r, e, ident)
    elif kind == 'backend_job': backend(r, e, ident)
    elif kind in {'native_candidate', 'xlsx_candidate'}: candidate(r, e, ident, kind == 'native_candidate')
    elif kind == 'plugin_capture': plugin(r, e, ident, source_project)
    elif kind in {'revision_bundle', 'bundle_continuation'}: bundle(r, e, ident, kind == 'bundle_continuation')
    else: work_text(r, e, ident)
    if e['validation']['checks']:
        e['status']['validation'] = 'recorded'
    e['source_record_sha256'] = ws.digest(r.original)
    if len(encoded(r.original)) > ws.LIMIT or len(encoded(e)) > ws.LIMIT:
        raise ValueError('Execution source exceeds byte budget')
    return {'envelope': e, 'sha256': ws.digest(e), 'original': r.original}


def inspect(db, kind, ident, source_project=None):
    with ws.transaction(db, write=False):
        value = _inspect(db, kind, ident, source_project)
        return {'envelope': model_evidence(value['envelope']), 'sha256': value['sha256']}


def capture(db, pid, packet_id, *, source_db, kind, ident, expected_sha256,
            request_key, request, source_project=None, observation_id=None, request_authority='explicit_local_request'):
    """Explicit local capture with source hash guard and immutable retry receipt.

    source_db is a trusted host connection, never a model-provided database grant.
    The packet anchors provenance, not authorization for the source's execution.
    """
    ws.identity(request_key); ws.text(request, 'exact result capture request')
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Expected exact execution source hash')
    source_path = source_db.execute('PRAGMA database_list').fetchone()[2]
    original = {'packet_id': packet_id, 'kind': kind, 'id': ident, 'source_project': source_project,
                'source_database': source_path, 'expected_sha256': expected_sha256, 'request': request}
    if observation_id is not None:
        original.update(observation_id=observation_id, request_authority=request_authority)
    with ws.transaction(db):
        ws.project(db, pid)
        old = db.execute('SELECT * FROM work_execution_captures WHERE project=? AND request_key=?', (pid, request_key)).fetchone()
        if old:
            if old['original'] != encoded(original):
                raise ValueError('Result capture key conflicts with its saved request')
            return model_evidence(parsed(old['receipt']))
        packet = db.execute('SELECT * FROM work_packets WHERE project=? AND id=?', (pid, packet_id)).fetchone()
        if packet is None or ws.digest(parsed(packet['packet'])) != packet['sha256']:
            raise ValueError('Unknown or changed continuation in this project')
        with ws.transaction(source_db, write=False):
            if observation_id is None:
                result = _inspect(source_db, kind, ident, source_project)
            else:
                from .execution_capture import observation
                result = observation(source_db, observation_id)
                if result['envelope']['source'] != {'kind': kind, 'id': ident}:
                    raise ValueError('Saved observation source mismatch')
        if result['sha256'] != expected_sha256:
            raise ValueError('Execution source changed; inspect before capture')
        changed = ws.project(db, pid)['revision'] != packet['revision']
        frozen_packet = parsed(packet['packet'])
        input_changed = False
        try:
            ws._validate_packet_files(db, pid, frozen_packet)
        except ValueError:
            input_changed = True
        request_id = ws.append(db, pid, 'request', 'Execution result capture request', request_authority, {'text': request})
        record_id = ws.append(db, pid, 'execution', 'Captured execution result', 'relay_record_projection',
                              {'envelope': result['envelope'], 'sha256': result['sha256'], 'packet_id': packet_id,
                               'packet_sha256': packet['sha256'], 'refs': [request_id],
                               'relationship': 'explicitly_linked_observation',
                               'continuation_inputs_changed': input_changed,
                               'state_changed_since_continuation': changed})
        evidence_id = ws.append(db, pid, 'evidence', 'Saved execution observation', 'relay_record_projection',
                                {'text': encoded(result['envelope']), 'origin': 'explicitly_supplied',
                                 'refs': [record_id], 'packet_id': packet_id})
        receipt = {'project_id': pid, 'request_key': request_key, 'record_id': record_id, 'evidence_id': evidence_id,
                   'packet_id': packet_id, 'result_sha256': result['sha256'], 'captured_at': time.time(),
                   'revision': ws.project(db, pid)['revision'], 'state_changed_since_continuation': changed,
                   'continuation_inputs_changed': input_changed,
                   'status': 'captured', 'authority': 'relay_record_projection', 'execution_dispatch': False}
        db.execute('INSERT INTO work_execution_captures VALUES (?,?,?,?,?,?)',
                   (pid, request_key, encoded(original), encoded(result), result['sha256'], encoded(receipt)))
        return model_evidence(receipt)


def export(db, pid, request_key, path):
    """Export a frozen public envelope with read-back recovery, never overwrite.

    Only local administration grants a destination. A missing projection can be
    rewritten from saved bytes; this never repeats the underlying worker job.
    """
    if db.in_transaction:
        raise ValueError('Export must happen after commit')
    ws.relative(path)
    with ws.transaction(db):
        p = ws.project(db, pid)
        if p['root'] is None:
            raise ValueError('Execution export needs a locally granted project folder')
        row = db.execute('SELECT * FROM work_execution_captures WHERE project=? AND request_key=?', (pid, request_key)).fetchone()
        if row is None:
            raise ValueError('Unknown result capture in this project')
        result = parsed(row['result'])
        if (not isinstance(result, dict) or set(result) != {'envelope', 'sha256', 'original'}
                or ws.digest(result['envelope']) != row['sha256'] or result['sha256'] != row['sha256']
                or ws.digest(result['original']) != result['envelope']['source_record_sha256']):
            raise ValueError('Saved execution capture hash mismatch')
        raw = (encoded(model_evidence({'envelope': result['envelope'], 'source_sha256': row['sha256']})) + '\n').encode()
        sha = hashlib.sha256(raw).hexdigest()
        old = db.execute('SELECT * FROM work_execution_exports WHERE project=? AND request_key=? AND path=?', (pid, request_key, path)).fetchone()
        if old and (old['root'] != p['root'] or old['sha256'] != sha):
            raise ValueError('Execution export destination or saved bytes changed')
        if not old:
            db.execute('INSERT INTO work_execution_exports VALUES (?,?,?,?,?,NULL)', (pid, request_key, path, p['root'], sha))
    grant = Grant(Path(p['root']), 'Explicit execution result export', reads=frozenset({path}), writes=frozenset({path}))
    try:
        existing = FILES.read(grant, path, ws.LIMIT)
    except FileNotFoundError:
        FILES.write(grant, path, raw, exclusive=True)
        existing = FILES.read(grant, path, ws.LIMIT)
    if existing != raw:
        raise ValueError('Execution export differs from saved bytes; refusing overwrite')
    receipt = {'project_id': pid, 'request_key': request_key, 'path': path,
               'sha256': sha, 'bytes': len(raw), 'status': 'verified', 'execution_dispatch': False}
    with ws.transaction(db):
        db.execute('UPDATE work_execution_exports SET receipt=? WHERE project=? AND request_key=? AND path=?',
                   (encoded(receipt), pid, request_key, path))
    return receipt
