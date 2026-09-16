import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts as c
from orchestrator.runtime import Runtime, file_hash


class FakeFactory:
    def __init__(self):
        self.sessions = {}; self.calls = []; self.fail = False

    def create(self, control, workspace, frozen, backend):
        session = {'id': frozen['assignment_id'], 'control': str(control)}
        self.sessions[session['id']] = dict(session=session, workspace=workspace, frozen=frozen,
                                          status={'status': 'running'})
        return session

    def submit(self, session):
        self.calls.append(session['id'])
        if self.fail:
            raise TimeoutError('ambiguous delivery')
        return {'submitted': True}

    def inspect(self, session):
        return self.sessions[session['id']]['status']

    def cancel(self, session):
        self.sessions[session['id']]['status'] = {'status': 'finished', 'exit_code': -15, 'reason': 'cancelled'}

    def finish(self, aid, decision='delivered', missing=None, wrong=False):
        session = self.sessions[aid]; frozen = session['frozen']; ws = session['workspace']
        for output in frozen['outputs']:
            if output['path'] == missing:
                continue
            path = ws / output['path']; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('artifact from ' + aid)
        result = dict(assignment_id='wrong' if wrong else aid, summary='Inspected output', decision=decision,
                      instruction='Correct the stated criterion' if decision == 'revise' else '',
                      checks=[dict(criterion=i, passed=decision != 'revise', evidence='Evidence ' + str(i))
                              for i in range(1, len(frozen['criteria']) + 1)])
        (ws / '.relay/result.json').write_text(json.dumps(result))
        session['status'] = {'status': 'finished', 'exit_code': 0, 'reason': None, 'usage': [{'input_tokens': 100}]}


def task(tid='produce', **kwargs):
    return dict(id=tid, objective='One bounded output', role='producer', instruction='Write output.txt',
                criteria=['Matches brief'], outputs=[{'path': 'output.txt', 'purpose': 'Candidate text'}], **kwargs)


def plan(tasks=None, **kwargs):
    return dict(id='demo', brief='A small workflow', backend={'type': 'codex-cli', 'model': 'fixed-model', 'reasoning': 'high'},
                tasks=tasks or [task()], **kwargs)


def pair(gate=None, max_attempts=2):
    producer = task(max_attempts=max_attempts)
    if gate:
        producer['user_gate'] = gate
    reviewer = task('review', dependencies=['produce'], review_of='produce', max_attempts=max_attempts,
                    inputs=[dict(from_task='produce', output='output.txt', path='candidate.txt',
                                 purpose='Inspect candidate', authority='Unaccepted candidate')])
    reviewer['role'] = 'reviewer'; reviewer['outputs'] = [{'path': 'review.md', 'purpose': 'Model judgment'}]
    return plan([producer, reviewer])


class FailureDetailTests(unittest.TestCase):
    def test_registered_failure_receipt_exposes_exact_reason(self):
        from orchestrator.runtime import failure_detail
        reason='Image must name an exact declared PNG/JPEG input: images/rendering.jpg'
        attempt={'state':'blocked','error':'Worker failed','receipt':json.dumps({'status':'finished','exit_code':1,'operation':{'outcome':'failed','reason':reason}})}
        self.assertEqual(failure_detail(None,attempt),'Registered operation failed: '+reason)
        attempt['state']='uncertain';self.assertEqual(failure_detail(None,attempt),'Worker failed')


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name).resolve()
        self.factory = FakeFactory(); self.rt = Runtime(self.root / 'runtime', self.factory)

    def tearDown(self):
        self.rt.db.close(); self.tmp.cleanup()

    def latest(self, tid='produce'):
        return self.rt.task('demo', tid)['latest']

    def finish(self, tid='produce', **kwargs):
        self.factory.finish(self.latest(tid), **kwargs); return self.rt.tick('demo')

    def test_create_does_not_dispatch_then_owns_complete_delivery(self):
        self.rt.create(plan()); self.assertEqual(self.factory.calls, [])
        self.rt.tick('demo'); aid = self.latest(); status = self.finish()
        self.assertEqual(status['status'], 'completed')
        self.assertEqual(len(status['artifacts']), 1)
        self.rt.tick('demo'); self.assertEqual(self.factory.calls, [aid])
        self.assertIn('input_tokens', status['attempts'][0]['receipt'])

    def test_restart_recovers_existing_worker_without_replay(self):
        self.rt.create(plan()); self.rt.tick('demo'); aid = self.latest()
        self.rt.db.close(); self.rt = Runtime(self.root / 'runtime', self.factory)
        self.rt.tick('demo'); self.factory.finish(aid)
        self.assertEqual(self.rt.tick('demo')['status'], 'completed')
        self.assertEqual(self.factory.calls, [aid])

    def test_claim_before_submit_does_not_replay_after_crash(self):
        self.rt.create(plan()); session = self.rt.claim('demo')
        self.factory.sessions[session['id']]['status'] = {'status': 'uncertain', 'reason': 'No receipt'}
        self.rt.tick('demo'); self.rt.tick('demo')
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(self.rt.task('demo', 'produce')['status'], 'uncertain')

    def test_ambiguous_submission_can_reconcile_but_never_replays(self):
        self.factory.fail = True; self.rt.create(plan()); self.rt.tick('demo'); self.rt.tick('demo')
        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.finish()['status'], 'completed')

    def test_parallel_independent_tasks_and_dependency_handoff(self):
        downstream = task('last', dependencies=['a', 'b'], inputs=[dict(from_task='a', output='output.txt',
                           path='input.txt', purpose='Geometry', authority='Dimensions only')])
        self.rt.create(plan([task('a'), task('b'), downstream])); self.rt.tick('demo')
        self.assertEqual(len(self.factory.calls), 2)
        self.finish('a'); self.assertIsNone(self.latest('last'))
        self.finish('b'); self.assertIsNotNone(self.latest('last'))
        frozen = self.factory.sessions[self.latest('last')]['frozen']
        self.assertEqual(frozen['inputs'][0]['authority'], 'Dimensions only')
        self.assertEqual(file_hash(Path(frozen['workspace']) / 'input.txt'), frozen['inputs'][0]['sha256'])
        self.assertNotEqual(frozen['workspace'], self.factory.sessions[self.latest('a')]['frozen']['workspace'])

    def test_resource_lock_survives_uncertain_state(self):
        self.rt.create(plan([task('a', resource='composition'), task('b', resource='composition')]))
        self.rt.tick('demo'); self.assertEqual(len(self.factory.calls), 1)
        self.factory.sessions[self.latest('a')]['status'] = {'status': 'uncertain', 'reason': 'Lost receipt'}
        self.rt.tick('demo'); self.assertIsNone(self.latest('b'))
        self.finish('a'); self.assertIsNotNone(self.latest('b'))

    def test_review_revision_creates_new_workers_preserves_first_files_and_scope(self):
        self.rt.create(pair()); self.rt.tick('demo'); first = self.latest()
        self.finish(); review1 = self.latest('review')
        self.finish('review', decision='revise'); second = self.latest()
        self.assertNotEqual(first, second)
        self.assertEqual(self.factory.sessions[first]['frozen']['criteria'], self.factory.sessions[second]['frozen']['criteria'])
        self.assertTrue(any(i.get('previous_delivery') for i in self.factory.sessions[second]['frozen']['inputs']))
        self.finish(); self.assertNotEqual(review1, self.latest('review'))
        self.assertEqual(self.finish('review', decision='accept')['status'], 'completed')
        self.assertEqual(len(self.factory.calls), 4)
        artifacts = self.rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?', (first,)).fetchall()
        self.assertEqual(len(artifacts), 1); self.assertIn(first, Path(artifacts[0]['blob']).read_text())

    def test_revision_budget_blocks_without_extra_worker(self):
        self.rt.create(pair(max_attempts=1)); self.rt.tick('demo'); self.finish(); self.finish('review', decision='revise')
        self.rt.tick('demo'); self.assertEqual(len(self.factory.calls), 2)
        self.assertEqual(self.rt.status('demo')['status'], 'blocked')
        from orchestrator.runtime import failure_detail
        attempt=self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.latest('produce'),)).fetchone()
        self.assertEqual(attempt['state'],'completed')
        self.assertIn('correction allowance exhausted',failure_detail(self.rt.db,attempt))

    def test_retry_failed_api_review_preserves_candidate_and_old_attempt(self):
        from orchestrator import executors
        value=pair(max_attempts=2);value['backend']={'type':'gemini-agent','model':'fixture'}
        for t in value['tasks']:t.update(tools=['files'],limits=executors.GEMINI_LIMITS.copy())
        self.rt.create(value);self.rt.tick('demo');self.finish()
        producer=self.latest();review=self.latest('review')
        receipt={'status':'finished','exit_code':1,'external_outcome':'no_pending_response','pending_requests':[],'reason':'Final report file missing'}
        self.factory.sessions[review]['status']=receipt;self.rt.tick('demo')
        before=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(review,)).fetchone())
        self.rt.retry_review('demo','review','Review the same candidate and finish its report.')
        self.assertEqual(self.latest(),producer);self.rt.tick('demo')
        self.assertNotEqual(self.latest('review'),review)
        self.assertEqual(self.rt.task('demo','review')['attempts'],2)
        self.assertEqual(before,dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(review,)).fetchone()))
        self.finish('review',decision='accept')
        self.assertEqual(self.rt.status('demo')['status'],'completed')
        self.assertEqual(len(self.factory.calls),3)

    def test_review_recovery_rejects_pending_response_and_exhausted_budget(self):
        from orchestrator import executors
        value=pair(max_attempts=2);value['backend']={'type':'gemini-agent','model':'fixture'}
        for t in value['tasks']:t.update(tools=['files'],limits=executors.GEMINI_LIMITS.copy())
        self.rt.create(value);self.rt.tick('demo');self.finish();review=self.latest('review')
        receipt={'status':'finished','exit_code':1,'external_outcome':'unknown','pending_requests':['api-01']}
        self.factory.sessions[review]['status']=receipt;self.rt.tick('demo')
        with self.assertRaisesRegex(ValueError,'uncertain replay'):self.rt.retry_review('demo','review','Retry')
        self.assertEqual(len(self.factory.calls),2)
        with self.rt.transaction():self.rt.db.execute("UPDATE production_tasks SET attempts=2 WHERE run='demo' AND id='review'")
        with self.assertRaisesRegex(ValueError,'budget exhausted'):self.rt.retry_review('demo','review','Retry')

    def test_model_acceptance_is_not_user_selection_and_purpose_is_exact(self):
        self.rt.create(pair(gate='audio preference')); self.rt.tick('demo'); self.finish(); self.finish('review', decision='accept')
        self.assertEqual(self.rt.status('demo')['status'], 'awaiting_user')
        artifact = self.rt.output('demo', 'produce', 'output.txt')
        with self.assertRaises(ValueError):
            self.rt.select('demo', 'produce', artifact['id'], 'geometry approval', 'B')
        self.rt.select('demo', 'produce', artifact['id'], 'audio preference', 'User chose this candidate')
        self.assertEqual(self.rt.status('demo')['status'], 'completed')
        self.assertEqual(self.rt.db.execute('SELECT purpose FROM production_decisions').fetchone()[0], 'audio preference')

    def test_future_assignment_changes_are_versioned_and_running_frozen(self):
        self.rt.create(plan()); before = self.rt.task('demo', 'produce')['assignment']
        changed = task(); changed['objective'] = 'Revised objective'
        self.rt.replace_future('demo', changed)
        self.assertNotEqual(before, self.rt.task('demo', 'produce')['assignment'])
        self.rt.tick('demo')
        with self.assertRaises(ValueError): self.rt.replace_future('demo', task())
        self.assertEqual(self.factory.sessions[self.latest()]['frozen']['objective'], 'Revised objective')

    def test_cancel_drains_worker_and_does_not_dispatch_dependents(self):
        self.rt.create(pair()); self.rt.tick('demo'); self.rt.cancel('demo'); self.rt.tick('demo')
        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.rt.task('demo', 'produce')['status'], 'cancelled')
        self.assertEqual(self.rt.status('demo')['status'], 'cancelled')

    def test_missing_output_blocks_but_preserves_first_response(self):
        self.rt.create(plan()); self.rt.tick('demo'); status = self.finish(missing='output.txt')
        self.assertEqual(status['status'], 'blocked')
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='first_response'").fetchone()[0], 1)

    def test_wrong_assignment_result_cannot_advance(self):
        self.rt.create(pair()); self.rt.tick('demo'); self.finish(wrong=True)
        self.assertIsNone(self.latest('review')); self.assertEqual(len(self.factory.calls), 1)

    def test_malformed_model_check_blocks_without_crashing_scheduler(self):
        self.rt.create(pair()); self.rt.tick('demo'); aid=self.latest(); self.factory.finish(aid)
        path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
        value=json.loads(path.read_text()); value['checks']=[None]; path.write_text(json.dumps(value))
        self.assertEqual(self.rt.tick('demo')['status'],'blocked')
        self.assertIsNone(self.latest('review'))

    def test_input_copy_mutation_blocks_and_original_remains_frozen(self):
        source = self.root / 'source.txt'; source.write_text('approved')
        artifact = self.rt.register(source, 'Guide')
        p = plan([task(inputs=[dict(artifact=artifact, path='guide.txt', purpose='Guide', authority='Requirements')])])
        self.rt.create(p); self.rt.tick('demo')
        ws = self.factory.sessions[self.latest()]['workspace']; path = ws / 'guide.txt'; path.chmod(0o600); path.write_text('changed')
        self.assertEqual(self.finish()['status'], 'blocked')
        self.assertEqual(Path(self.rt.artifact(artifact)['blob']).read_text(), 'approved')

    def test_output_symlink_is_not_registered(self):
        self.rt.create(plan()); self.rt.tick('demo'); aid = self.latest(); self.factory.finish(aid)
        ws = self.factory.sessions[aid]['workspace']; out = ws / 'output.txt'; out.unlink()
        external = self.root / 'outside'; external.write_text('private'); out.symlink_to(external)
        self.rt.tick('demo'); self.assertEqual(self.rt.status('demo')['status'], 'blocked')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0], 0)

    def test_timeout_preserves_drafts_without_starting_review_or_resetting_attempts(self):
        self.rt.create(pair()); self.rt.tick('demo'); aid=self.latest()
        self.factory.finish(aid)
        self.factory.sessions[aid]['status'].update(reason='time_limit',exit_code=-15)
        self.rt.tick('demo')
        task=self.rt.task('demo','produce')
        self.assertEqual(task['status'],'blocked');self.assertEqual(task['attempts'],1)
        self.assertIsNone(self.latest('review'))
        drafts=self.rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(aid,)).fetchall()
        self.assertEqual(len(drafts),1);self.assertIn('Unreviewed draft',drafts[0]['purpose'])
        with self.rt.db:
            recovered=self.rt.preserve_stopped_outputs(aid)
        self.assertEqual(recovered['artifacts'],[drafts[0]['id']])
        self.assertFalse(recovered['approved'])
        self.assertEqual(len(self.factory.calls),1)

    def test_draft_recovery_rejects_active_and_unsafe_outputs(self):
        self.rt.create(plan());self.rt.tick('demo');aid=self.latest()
        with self.assertRaises(ValueError):self.rt.preserve_stopped_outputs(aid)
        self.factory.finish(aid)
        ws=self.factory.sessions[aid]['workspace'];out=ws/'output.txt';out.unlink()
        external=self.root/'outside';external.write_text('private');out.symlink_to(external)
        self.factory.sessions[aid]['status'].update(reason='time_limit',exit_code=-15)
        self.rt.tick('demo')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],0)
        event=self.rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='draft_outputs_preserved'",(aid,)).fetchone()
        self.assertTrue(json.loads(event['data'])['failures'])

    def test_graph_validation_rejects_cycles_missing_artifacts_and_hidden_inputs(self):
        for p in [plan([task('a', dependencies=['b']), task('b', dependencies=['a'])]),
                  plan([task(dependencies=['missing'])]),
                  plan([task(inputs=[dict(artifact='missing', path='../bad', purpose='X', authority='X')])])]:
            with self.subTest(p=p), self.assertRaises(ValueError): self.rt.create(p)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_second_scheduler_cannot_claim_same_assignment(self):
        self.rt.create(plan()); self.rt.claim('demo')
        other = Runtime(self.root / 'runtime', self.factory)
        try:
            self.assertIsNone(other.claim('demo'))
        finally:
            other.db.close()

    def test_changed_registered_blob_prevents_dispatch(self):
        source = self.root / 'source.txt'; source.write_text('one'); aid = self.rt.register(source, 'Input')
        self.rt.create(plan([task(inputs=[dict(artifact=aid, path='in.txt', purpose='X', authority='X')])]))
        blob = Path(self.rt.artifact(aid)['blob']); blob.chmod(0o600); blob.write_text('two')
        self.assertEqual(self.rt.tick('demo')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],0)
        self.assertEqual(self.factory.calls, [])

    def test_future_step_can_be_added_but_late_review_gate_cannot(self):
        self.rt.create(plan()); self.rt.tick('demo')
        self.rt.add_future('demo', task('later', dependencies=['produce']))
        self.assertEqual(self.rt.task('demo','later')['status'], 'queued')
        with self.assertRaises(ValueError): self.rt.add_future('demo', pair()['tasks'][1])
        self.finish(); self.assertIsNotNone(self.latest('later'))

    def test_weaker_review_contract_is_rejected(self):
        value = pair(); value['tasks'][1]['criteria'] = ['Just say it is fine']
        with self.assertRaises(ValueError): self.rt.create(value)

    def test_false_self_report_does_not_release_downstream(self):
        self.rt.create(pair()); self.rt.tick('demo'); aid = self.latest(); self.factory.finish(aid)
        path = self.factory.sessions[aid]['workspace'] / '.relay/result.json'
        value = json.loads(path.read_text()); value['checks'][0]['passed'] = False
        path.write_text(json.dumps(value)); self.rt.tick('demo')
        self.assertIsNone(self.latest('review'))
        self.assertEqual(self.rt.status('demo')['status'], 'blocked')

    def test_blocked_notice_includes_failed_check_and_retains_full_report(self):
        self.rt.create(pair());self.rt.tick('demo');aid=self.latest();self.factory.finish(aid,decision='blocked')
        path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
        value=json.loads(path.read_text());value['summary']='Created candidate files.'
        value['checks'][0].update(passed=False,evidence='Required source could not be read')
        value['instruction']='Provide the missing readable source.'
        path.write_text(json.dumps(value));self.rt.tick('demo')
        attempt=self.rt.db.execute('SELECT error FROM production_attempts WHERE id=?',(aid,)).fetchone()
        self.assertTrue(attempt['error'].startswith('Criterion 1: Required source'))
        self.assertIsNone(self.latest('review'))
        records=self.rt.db.execute("SELECT data FROM production_events WHERE kind='checks_recorded'").fetchall()
        self.assertTrue(any(json.loads(r['data']).get('result')==value for r in records))

    def test_missing_outputs_keep_worker_cause_and_old_status_is_read_only(self):
        from orchestrator.runtime import failure_detail
        from types import SimpleNamespace
        from task_relay import host_apps
        self.rt.create(pair());self.rt.tick('demo');aid=self.latest()
        self.factory.finish(aid,decision='blocked',missing='output.txt')
        path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
        value=json.loads(path.read_text())
        value.update(summary='Blender crashed before Python.',instruction='Diagnose startup before another generation.')
        value['checks'][0].update(passed=False,evidence='Blender Metal initialization crashed; no native file was created.')
        path.write_text(json.dumps(value));self.rt.tick('demo')
        row=self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()
        self.assertIn('Blender Metal initialization',row['error'])
        self.assertIn('Missing, linked',row['error'])
        self.assertIsNone(self.latest('review'));self.assertEqual(self.rt.task('demo','produce')['attempts'],1)
        legacy='Missing, linked, or non-regular artifact: output.txt'
        self.rt.db.execute('UPDATE production_attempts SET error=? WHERE id=?',(legacy,aid))
        row=self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()
        self.assertIn('Blender Metal initialization',failure_detail(self.rt.db,row))
        self.assertEqual(self.rt.db.execute('SELECT error FROM production_attempts WHERE id=?',(aid,)).fetchone()[0],legacy)
        observations=host_apps.catalog(SimpleNamespace(db=self.rt.db))[0]['execution_environments']['agent_shell']['historical_failures']
        self.assertEqual(observations[0]['attempt'],aid)
        self.assertEqual(self.factory.calls,[aid])

    def test_malformed_blocked_report_settles_once_and_preserves_evidence(self):
        cases = [None, [None], [{}], [{'criterion': 1, 'passed': False, 'evidence': None}],
                 [{'criterion': 1, 'passed': 'false', 'evidence': 'Denied'}],
                 [{'criterion': True, 'passed': False, 'evidence': 'Denied'}],
                 [{'criterion': 2, 'passed': False, 'evidence': 'Unknown criterion'}],
                 [{'criterion': 1, 'passed': False, 'evidence': 'Denied'}] * 2]
        for index, checks in enumerate(cases):
            with self.subTest(checks=checks):
                value = pair(); value['id'] = 'blocked-' + str(index)
                run = self.rt.create(value); self.rt.tick(run)
                aid = self.rt.task(run, 'produce')['latest']; self.factory.finish(aid, decision='blocked')
                path = self.factory.sessions[aid]['workspace'] / '.relay/result.json'
                report = json.loads(path.read_text()); report['checks'] = checks
                raw = json.dumps(report); path.write_text(raw)
                self.assertEqual(self.rt.tick(run)['status'], 'blocked')
                self.assertIsNone(self.rt.task(run, 'review')['latest'])
                self.rt.tick(run)
                self.assertEqual(self.factory.calls.count(aid), 1)
                self.assertEqual(self.rt.task(run, 'produce')['attempts'], 1)
                events = self.rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='first_response'", (aid,)).fetchall()
                self.assertEqual([json.loads(e['data'])['text'] for e in events], [raw])
                self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_artifacts WHERE attempt=?', (aid,)).fetchone()[0], 1)

    def test_blocked_instruction_is_validated_before_formatting(self):
        self.rt.create(pair()); self.rt.tick('demo'); aid = self.latest()
        self.factory.finish(aid, decision='blocked')
        path = self.factory.sessions[aid]['workspace'] / '.relay/result.json'
        value = json.loads(path.read_text()); value['instruction'] = 123
        path.write_text(json.dumps(value))
        self.assertEqual(self.rt.tick('demo')['status'], 'blocked')
        attempt = self.rt.db.execute('SELECT error FROM production_attempts WHERE id=?', (aid,)).fetchone()
        self.assertEqual(attempt['error'], 'Invalid result instruction')

    def test_blocked_report_can_preserve_partial_checks_without_acceptance(self):
        value = pair()
        for t in value['tasks']: t['criteria'] = ['First check', 'Second check']
        self.rt.create(value); self.rt.tick('demo'); aid = self.latest()
        self.factory.finish(aid, decision='blocked')
        path = self.factory.sessions[aid]['workspace'] / '.relay/result.json'
        report = json.loads(path.read_text()); report['checks'] = [dict(criterion=2, passed=False, evidence='Source unavailable')]
        path.write_text(json.dumps(report))
        self.assertEqual(self.rt.tick('demo')['status'], 'blocked')
        attempt = self.rt.db.execute('SELECT error FROM production_attempts WHERE id=?', (aid,)).fetchone()
        self.assertIn('Criterion 2: Source unavailable', attempt['error'])
        self.assertIsNone(self.latest('review'))

    def test_stale_artifact_cannot_be_selected_after_revision(self):
        self.rt.create(pair(gate='audio')); self.rt.tick('demo'); self.finish(); self.finish('review',decision='accept')
        first = self.rt.output('demo','produce','output.txt')['id']
        self.rt.revise('demo','produce','A bounded correction'); self.rt.tick('demo')
        self.finish(); self.finish('review',decision='accept')
        with self.assertRaises(ValueError): self.rt.select('demo','produce',first,'audio','Use old candidate')

    def test_all_templates_share_the_runtime_review_and_user_gate(self):
        from orchestrator.templates import STAGES, build
        for name in STAGES:
            p=build(name,name,[],{'type':'codex-cli','model':'fixed-model','reasoning':'high'})
            self.rt.create(p); self.rt.tick(name)
            self.factory.finish(self.rt.task(name,'produce')['latest']); self.rt.tick(name)
            self.factory.finish(self.rt.task(name,'review')['latest'], decision='accept')
            self.assertEqual(self.rt.tick(name)['status'], 'awaiting_user')

    def test_export_uses_registered_version_and_refuses_overwrite(self):
        self.rt.create(plan()); self.rt.tick('demo'); self.finish()
        ws=self.factory.sessions[self.latest()]['workspace']; (ws/'output.txt').write_text('later edit')
        destination=self.root/'export'
        manifest=self.rt.export('demo','produce',destination)
        self.assertIn(self.latest(),(destination/'output.txt').read_text())
        self.assertEqual(manifest['decisions'],[])
        with self.assertRaises(FileExistsError): self.rt.export('demo','produce',destination)


if __name__ == '__main__':
    unittest.main()
