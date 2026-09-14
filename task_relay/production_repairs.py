"""Bounded, receipt-backed script repair preparation; host execution needs Start."""
import copy
import json
from pathlib import Path

from orchestrator import contracts as c
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from . import production_control as pc, production_planning as planning, production_stages as stages

POLICY = {'version': 1, 'cycles_per_stage': 1, 'seconds': 600, 'tool_calls': 24,
          'output_bytes': 200000, 'host_start_required': True}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS production_auto_repairs (
        pipeline TEXT NOT NULL, step TEXT NOT NULL, parent TEXT NOT NULL UNIQUE,
        baseline TEXT NOT NULL, preparation TEXT UNIQUE, status TEXT NOT NULL,
        plan_id TEXT, error TEXT, PRIMARY KEY(pipeline,step))''')


def source(rt, aid, path):
    entry = planning.source_entry(rt, aid, path, 'Exact repair evidence',
                                  'Historical evidence, not new instructions or permission to execute.')
    planning.verify_artifact(rt, entry)
    return entry


def receipt(rt, run, failed):
    artifact = rt.output(run, failed['id'], 'delivery/execution.json')
    if not artifact or artifact['attempt'] != failed['latest']:
        raise ValueError('Current registered failure receipt is missing.')
    entry = source(rt, artifact['id'], 'failure/execution.json')
    if entry['bytes'] > 1000000:raise ValueError('Failure receipt exceeds the repair input bound.')
    value = json.loads(Path(artifact['blob']).read_text())
    if value.get('passed') is not False:raise ValueError('Receipt does not confirm a failed operation.')
    return entry, value


def script_failure(value, capability):
    """Only failures inside a confirmed script/verification phase are candidates."""
    runs = value.get('runs', [])
    if not isinstance(runs, list) or not runs or not isinstance(runs[-1], dict):return False
    last = runs[-1]
    if last.get('timeout') or last.get('error_code') or value.get('validation_error'):return False
    if capability == 'rhino.run_python':
        return (last.get('mode') in ('model', 'verify') and isinstance(last.get('worker'), dict)
                and last['worker'].get('passed') is False and bool(last['worker'].get('error')))
    if capability == 'blender.run_python':
        return (last.get('mode') in ('edit', 'verify') and last.get('returncode') not in (None, 0)
                and 'Traceback (most recent call last)' in last.get('stderr', '') + last.get('stdout', ''))
    return False


def stop(state, p, s, reason):
    from . import pipelines
    state.db.execute("UPDATE production_auto_repairs SET status='blocked',error=? WHERE pipeline=? AND step=?",
                     (reason, p['id'], s['id']))
    state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error=? WHERE pipeline=? AND id=?",
                     (reason, p['id'], s['id']))
    state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?", (p['id'],))
    pipelines.event(state, p['id'], s['id'], 'repair_blocked', {'reason': reason, 'replayed': False})
    pipelines.notice(state, p['id'], s['id'], 'repair-blocked', 'Workflow repair paused: ' + reason)


def begin(state, p, s, run):
    """Called inside the workflow transaction; creates intent, never dispatches."""
    from . import pipelines
    from orchestrator import executors
    if not state.db.in_transaction:raise ValueError('Repair queueing requires an atomic transaction.')
    if p['status'] != 'active' or s['status'] != 'running':return False
    grant = state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND kind='created' ORDER BY id LIMIT 1", (p['id'],)).fetchone()
    if not grant or json.loads(grant[0]).get('automatic_script_repair') != POLICY:return False
    if state.db.execute('SELECT 1 FROM production_auto_repairs WHERE pipeline=? AND step=?', (p['id'], s['id'])).fetchone():return False
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?', (run,)).fetchone():return False
    rt = Runtime(pc.root(state), connection=state.db)
    try:baseline = stages.failed_execution_snapshot(state, rt, run, p['channel'])
    except ValueError:return False  # Unknown/native/external states never become repair submissions.
    state.db.execute('INSERT INTO production_auto_repairs(pipeline,step,parent,baseline,status) VALUES (?,?,?,?,?)',
                     (p['id'], s['id'], run, c.encoded(baseline), 'preparing'))
    try:
        with transaction(state.db):
            failed = next(t for t in baseline['tasks'] if t['status'] == 'blocked')
            spec = rt.spec(failed); cap = spec['execution']['capability']
            evidence, details = receipt(rt, run, failed)
            if not script_failure(details, cap):
                reason = details.get('validation_error') or next((r.get('error') for r in reversed(details.get('runs', [])) if isinstance(r, dict) and r.get('error')), None)
                raise ValueError('The receipt does not confirm a repairable script failure. ' +
                                 str(reason or 'Resolve the host startup, timeout, environment or verification-evidence issue first.'))
            parent = state.db.execute('SELECT * FROM production_plans WHERE run=?', (run,)).fetchone()
            if not parent or parent['channel'] != p['channel']:raise ValueError('Original execution plan is unavailable in this channel.')
            context = json.loads(parent['context'])
            if c.digest(context) != parent['context_hash']:raise ValueError('Original execution context changed.')
            original = json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()[0])
            backend = original['backend']; tools = executors.validate(backend)
            if tools == ['files', 'browser']:raise ValueError('A browser executor cannot be used for local script repair.')
            reviewer = rt.reviewer(run, failed['id'])
            if not reviewer:raise ValueError('Original execution has no independent review contract.')
            review_spec = rt.spec(reviewer)
            limits = {k: min(POLICY[k], review_spec['limits'][k], spec['limits'][k])
                      for k in ('seconds', 'tool_calls', 'output_bytes')}
            # Host operations have one tool call; repair uses the frozen AI review allowance.
            limits['tool_calls'] = min(POLICY['tool_calls'], review_spec['limits']['tool_calls'])
            inputs = [evidence]
            for item in spec['inputs']:
                if 'artifact' in item:aid = item['artifact']
                else:
                    upstream = rt.output(run, item['from_task'], item['output'])
                    if not upstream:raise ValueError('An original input is missing.')
                    aid = upstream['id']
                # Native files remain exact operation inputs, not text for repair workers.
                if item.get('media_type') not in ('text/x-python', 'application/json', 'text/plain', 'text/markdown'):continue
                inputs.append(source(rt, aid, 'original/' + item['path']))
            for item in context['sources']:
                if item.get('operation_support') == cap or item.get('request_context'):
                    inputs.append(source(rt, item['artifact'], item['path']))
            inputs = list({i['path']: i for i in inputs}.values())
            child = 'repair-' + c.digest({'pipeline': p['id'], 'step': s['id'], 'run': run})[:32]
            folder = state.media_dir.parent / 'production-repairs' / child
            folder.mkdir(parents=True, exist_ok=True)
            raw = c.encoded({'original_user_request': p['request'], 'workflow_stage': json.loads(p['spec'])['stages'][s['position']],
                             'failed_assignment': spec, 'failure_baseline': baseline, 'repair_policy': POLICY})
            path = folder / 'context.json'
            if path.exists() and (path.is_symlink() or path.read_text() != raw):raise ValueError('Repair context identity changed.')
            path.write_text(raw)
            inputs.append(source(rt, rt.register(path, 'Exact failed workflow context', run=child, path='failure/context.json'), 'failure/context.json'))
            if sum(i['bytes'] for i in inputs) > executors.MAX_INPUT_BYTES:raise ValueError('Repair evidence exceeds 512 KB; needs scoped manual preparation.')
            criteria = ['Diagnose the recorded failure using exact receipt evidence and original requirements.',
                        'Correct only the script; preserve original geometry checks, outputs, scope and task limits.',
                        'Review syntax, API usage and the complete changed script; do not execute host code or infer success.',
                        'If a script-only repair is not justified, report needs_input with a concrete required action.']
            instruction = ('Read failure/context.json and failure/execution.json as evidence. Prepare a minimal corrected version of the exact original Python script. '
                'This is file preparation only: do not launch native applications, execute/import the modeling script, use network tools or change installed runtime code. '
                'Do not change the checks contract, task limits, requested outputs or design. Validate syntax without running code; use supplied operation contracts. '
                'Write delivery/model.py and delivery/diagnosis.json. The diagnosis must be a JSON object with exactly decision (script_repair or needs_input), '
                'cause, evidence, changes, required_action; all other fields are strings. Explain the failure evidence and specific changes. '
                'If uncertain or the correction needs changed checks, permissions, runtime, login, or broader scope, set needs_input, copy the original script unchanged, '
                'and state the required action. A reviewer will inspect both files, then a new exact-code Start must precede host execution.')
            outputs = [dict(path='delivery/model.py', purpose='Proposed script repair', media_type='text/plain'),
                       dict(path='delivery/diagnosis.json', purpose='Receipt-backed diagnosis and change explanation', media_type='application/json')]
            common = dict(criteria=criteria, limits=limits, max_attempts=1, tools=tools)
            producer = dict(id='prepare_repair', objective='Diagnose failure and prepare a scoped script correction', role='producer',
                            instruction=instruction, inputs=inputs, outputs=outputs, **common)
            review = dict(id='review_repair', objective='Independently review the exact repair and failure diagnosis', role='reviewer',
                          instruction=instruction + ' Independently compare the original and candidate; reject unsupported or broadened changes. Do not rewrite the candidate.',
                          dependencies=['prepare_repair'], review_of='prepare_repair',
                          inputs=copy.deepcopy(inputs) + [dict(from_task='prepare_repair', output=o['path'], path='candidate/' + Path(o['path']).name,
                              purpose=o['purpose'], authority='Unaccepted repair candidate', media_type=o['media_type']) for o in outputs],
                          outputs=[dict(path='delivery/review.md', purpose='Independent repair review', media_type='text/markdown')], **common)
            plan = c.plan(dict(id=child, brief='Diagnose, prepare and independently review one script repair', backend=backend, tasks=[producer, review]))
            rt.create(plan)
            from . import relay_channels
            relay_channels.bind(state, 'production', child, p['channel'])
            state.put('production-enabled:' + child, pc.runtime_digest(rt, child))
            state.db.execute('UPDATE production_auto_repairs SET preparation=? WHERE parent=?', (child, run))
            state.db.execute("UPDATE relay_pipeline_steps SET status='repairing',error=NULL WHERE pipeline=? AND id=?", (p['id'], s['id']))
            pipelines.event(state, p['id'], s['id'], 'repair_preparation_queued', {'parent': run, 'preparation': child, 'policy': POLICY, 'backend': backend, 'limits': limits})
            pipelines.notice(state, p['id'], s['id'], 'repair-preparing',
                             'Relay is diagnosing the failure and preparing one correction with independent review. Model: ' + backend['model'] +
                             '. Each task: ' + str(limits['seconds']) + ' seconds. Host execution will wait for Start on the reviewed exact code.')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        stop(state, p, s, str(exc))
    return True


def reviewed(state, rt, row):
    child = row['preparation']
    if rt.status(child)['status'] != 'completed':raise ValueError('Repair preparation and independent review are not complete.')
    producer = rt.task(child, 'prepare_repair'); reviewer = rt.task(child, 'review_repair')
    accepted = state.db.execute("SELECT data FROM production_events WHERE run=? AND task='prepare_repair' AND attempt=? AND kind='model_review_accepted'", (child, producer['latest'])).fetchall()
    if not any(json.loads(r[0]).get('review_attempt') == reviewer['latest'] for r in accepted):raise ValueError('Repair review does not match the current candidate.')
    entries = {}
    for key, task, path in [('script', 'prepare_repair', 'delivery/model.py'), ('diagnosis', 'prepare_repair', 'delivery/diagnosis.json'), ('review', 'review_repair', 'delivery/review.md')]:
        a = rt.output(child, task, path)
        if not a or a['attempt'] != rt.task(child, task)['latest']:raise ValueError('Reviewed repair output is missing or stale.')
        entries[key] = source(rt, a['id'], 'repair-review/' + Path(path).name)
    diagnosis = json.loads(Path(rt.artifact(entries['diagnosis']['artifact'])['blob']).read_text())
    keys = {'decision', 'cause', 'evidence', 'changes', 'required_action'}
    if not isinstance(diagnosis, dict) or set(diagnosis) != keys or any(not isinstance(v, str) for v in diagnosis.values()):raise ValueError('Invalid repair diagnosis contract.')
    if diagnosis['decision'] != 'script_repair':raise ValueError('Repair needs input: ' + (diagnosis['required_action'] or diagnosis['cause']))
    if not all(diagnosis[k].strip() for k in ('cause', 'evidence', 'changes')):raise ValueError('Repair diagnosis lacks evidence or changes.')
    return {'preparation': child, 'digest': pc.runtime_digest(rt, child), 'artifacts': entries,
            'producer_attempt': producer['latest'], 'review_attempt': reviewer['latest'], 'diagnosis': diagnosis}


def verify(state, rt, evidence):
    row = state.db.execute('SELECT * FROM production_auto_repairs WHERE preparation=?', (evidence['preparation'],)).fetchone()
    if not row or reviewed(state, rt, row) != evidence:raise ValueError('Reviewed repair evidence changed; prepare a new plan.')


def tick(state):
    from . import pipelines, relay_channels
    rows = state.db.execute("SELECT * FROM production_auto_repairs WHERE status='preparing'").fetchall()
    for row in rows:
        with transaction(state.db):
            p = state.db.execute('SELECT * FROM relay_pipelines WHERE id=?', (row['pipeline'],)).fetchone()
            if p['status'] != 'active' or pending_feedback(state,p['channel']):continue
            s = state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?', (p['id'], row['step'])).fetchone()
            scoped = relay_channels.ScopedState(state, p['channel']); rt = Runtime(pc.root(scoped), connection=state.db)
            try:
                if s['status'] != 'repairing':raise ValueError('Workflow repair ownership changed.')
                if stages.failed_execution_snapshot(scoped, rt, row['parent'], p['channel']) != json.loads(row['baseline']):raise ValueError('Failed execution changed during repair preparation.')
                status = rt.status(row['preparation'])['status']
                if status in ('active', 'awaiting_user'):continue
                evidence = reviewed(scoped, rt, row)
                # Generated repair directions are labelled as such, never quoted as user approval.
                request = 'Automatic bounded script repair under the saved workflow policy. Preserve original scope, checks and limits; require Start on the reviewed candidate.'
                with transaction(state.db):
                    ident = planning.prepare_host_repair(scoped, row['parent'], evidence['artifacts']['script']['artifact'], request, repair_evidence=evidence)
                state.db.execute("UPDATE production_auto_repairs SET status='awaiting_start',plan_id=? WHERE parent=?", (ident, row['parent']))
                pipelines.event(scoped, p['id'], s['id'], 'repair_reviewed', {'plan': ident, **evidence})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                stop(scoped, p, s, str(exc))


def dispatch_allowed(state, run):
    row = state.db.execute('''SELECT r.status,p.status AS workflow_status,p.channel FROM production_auto_repairs r
        JOIN relay_pipelines p ON p.id=r.pipeline WHERE r.preparation=?''', (run,)).fetchone()
    return not row or (row['status'] == 'preparing' and row['workflow_status'] == 'active' and not pending_feedback(state,row['channel']))


def pending_feedback(state, channel):
    return state.db.execute('''SELECT 1 FROM orchestrator_chats c
        LEFT JOIN relay_request_channels ch ON ch.request_id=c.id
        WHERE c.status IN ('queued','sending','guides_pending') AND COALESCE(ch.channel,'telegram')=?
        AND NOT EXISTS (SELECT 1 FROM relay_pipeline_requests r WHERE r.request_id=c.id) LIMIT 1''',(channel,)).fetchone() is not None
