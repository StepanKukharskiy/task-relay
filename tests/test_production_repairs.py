import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from orchestrator import contracts as c
from orchestrator.storage import transaction
from orchestrator.step_runner import execute
from task_relay import production_repairs as repairs, pipelines, production_planning as planning, production_control as pc
from tests import test_rhino_planning as fixtures, test_rhino_operations as native


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        del self.fail
        self.signature = patch('host_evidence.application_signature', return_value={'path': '/fixture/rhino'})
        self.signature.start()

    def tearDown(self):
        self.signature.stop()
        fixtures.Tests.tearDown(self)

    request = fixtures.Tests.request
    action = fixtures.Tests.action
    queue = fixtures.Tests.queue
    row = fixtures.Tests.row
    response = fixtures.Tests.response
    setup_plan = fixtures.Tests.setup_plan

    def setup_failure(self, startup=False, legacy=False):
        row = self.setup_plan()
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?", (row['event_id'],))
            planning.apply(self.state, row['token'], 'start')
        run = self.row()['run'];worker = pc.Worker(self.state, lambda _: self.rt);worker.tick()
        attempt = self.rt.task(run, 'app')['latest'];session = self.factory.sessions[attempt]
        control = Path(session['session']['control']);control.mkdir(parents=True)
        def host(*args):
            request = json.loads(Path(args[2]).read_text())
            if startup:return dict(passed=False, returncode=0, worker=None, error_code='rhino_no_worker_response')
            if request['mode'] == 'before':return native.Tests.fake_run(self, *args)
            return dict(passed=False, returncode=1, worker=dict(passed=False, error='AttributeError: unsupported camera method'))
        with patch('task_relay.rhino_host.run', side_effect=host):result = execute(session['frozen'], control)
        session['status'] = dict(status='finished', exit_code=0, reason=None, usage=[], operation=result)
        worker.tick();self.assertEqual(self.rt.status(run)['status'], 'blocked')
        pid = 'pipe-' + 'a' * 24
        stage = dict(id='model', instruction='Produce the requested model', route='production', gate='selection',
                     capabilities=['rhino.run_python'], deliverables={})
        spec = dict(stages=[stage, dict(id='finish', instruction='Present selected results', route='conversation', gate='none', capabilities=[], deliverables={})], planning_only=False)
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO relay_pipelines VALUES (?,?,?,?,?,?,?,?,?,?)',
                (pid, 500, 'Create my model and presentation; preserve originals.', 'Saved workflow', c.encoded(spec), 'telegram', 'gemini', 'fixture', 'active', 0))
            self.state.db.execute('INSERT INTO relay_pipeline_steps(pipeline,position,id,status,target_kind,target) VALUES (?,?,?,?,?,?)',
                (pid, 0, 'model', 'running', 'plan_production', row['id']))
            self.state.db.execute('INSERT INTO relay_pipeline_steps(pipeline,position,id,status) VALUES (?,?,?,?)', (pid, 1, 'finish', 'pending'))
            pipelines.event(self.state, pid, None, 'created', {} if legacy else {'automatic_script_repair': repairs.POLICY})
        self.pid, self.parent, self.worker = pid, run, worker
        self.before = [tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?', (run,))]
        return run

    def repair(self):return self.state.db.execute('SELECT * FROM production_auto_repairs').fetchone()
    def step(self):return self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id='model'", (self.pid,)).fetchone()

    def finish_preparation(self, decision='script_repair', rejected=False):
        child = self.repair()['preparation'];self.rt.tick(child)
        attempt = self.rt.task(child, 'prepare_repair')['latest']
        self.factory.finish(attempt)
        ws = self.factory.sessions[attempt]['workspace']
        (ws / 'delivery/model.py').write_text(native.CREATE_SCRIPT + '\n# minimal camera correction\n')
        (ws / 'delivery/diagnosis.json').write_text(json.dumps(dict(decision=decision, cause='Unsupported API method',
            evidence='model phase AttributeError in exact receipt', changes='Use supported camera API', required_action='Review host settings' if decision=='needs_input' else '')))
        self.rt.tick(child)
        reviewer = self.rt.task(child, 'review_repair')['latest'];self.assertIsNotNone(reviewer)
        self.factory.finish(reviewer, decision='blocked' if rejected else 'accept')
        self.rt.tick(child)
        return child

    def test_repair_preserves_the_assigned_review_worker_model(self):
        from orchestrator import worker_capabilities
        self.setup_failure()
        run=self.row()['run'];reviewer=self.rt.reviewer(run,'app')
        spec=self.rt.spec(reviewer)
        backend={'type':'codex-cli','model':'fixed-review-model','reasoning':'high'}
        spec['worker']={'requires':['code.execute']}
        worker_capabilities.resolve(spec,[worker_capabilities.entry(backend)],backend)
        self.rt.replace_future(run,spec)
        pipelines.tick(self.state)
        row=self.repair();self.assertEqual(row['status'],'preparing',row['error'])
        plan=json.loads(self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',(row['preparation'],)).fetchone()[0])
        self.assertEqual(plan['backend'],backend)

    def test_failure_diagnosis_review_start_and_saved_workflow_lineage(self):
        self.setup_failure();pipelines.tick(self.state)
        row = self.repair();self.assertEqual(row['status'], 'preparing');self.assertEqual(self.step()['status'], 'repairing')
        self.assertEqual(len(self.factory.calls), 1)  # Queue commit never dispatches.
        pipelines.tick(self.state);self.assertEqual(self.repair()['preparation'], row['preparation'])
        child = self.finish_preparation()
        frozen = self.factory.sessions[self.rt.task(child, 'prepare_repair')['latest']]['frozen']
        self.assertIn('failure/execution.json', [i['path'] for i in frozen['inputs']])
        self.assertNotIn('execution', frozen)
        pipelines.tick(self.state)
        row = self.repair();self.assertEqual(row['status'], 'awaiting_start', row['error'])
        plan = self.state.db.execute('SELECT * FROM production_plans WHERE id=?', (row['plan_id'],)).fetchone()
        self.assertEqual(plan['status'], 'ready');self.assertIsNone(plan['run'])
        self.assertIn('SAVED WORKFLOW REPAIR POLICY', plan['request'])
        self.assertEqual(self.before, [tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?', (self.parent,))])
        pipelines.tick(self.state);self.assertIsNone(self.state.db.execute('SELECT run FROM production_plans WHERE id=?', (plan['id'],)).fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'complete plan card'), transaction(self.state.db):planning.apply(self.state, plan['token'], 'start')
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', (plan['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?", (plan['event_id'],))
            planning.apply(self.state, plan['token'], 'start')
        fresh = self.state.db.execute('SELECT run FROM production_plans WHERE id=?', (plan['id'],)).fetchone()[0]
        self.assertEqual(pipelines.owner_of_run(self.state, fresh)['id'], self.pid)
        old = self.rt.spec(self.rt.task(self.parent, 'app'));new = self.rt.spec(self.rt.task(fresh, 'app'))
        self.assertEqual(old['limits'], new['limits'])
        self.assertEqual(old['execution']['parameters']['checks_sha256'], new['execution']['parameters']['checks_sha256'])
        self.assertNotEqual(old['execution']['parameters']['script_sha256'], new['execution']['parameters']['script_sha256'])
        self.assertEqual(len(self.factory.calls), 3)  # Failed original + repair author/reviewer, no host replay.
        self.assertEqual(self.repair()['status'], 'resumed')
        self.rt.tick(fresh)
        attempt=self.rt.task(fresh,'app')['latest'];session=self.factory.sessions[attempt]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        with patch('task_relay.rhino_host.run',side_effect=lambda *args:native.Tests.fake_run(self,*args)):
            result=execute(session['frozen'],control)
        session['status']=dict(status='finished',exit_code=0,reason=None,usage=[],operation=result)
        self.rt.tick(fresh)
        review=self.rt.reviewer(fresh,'app');self.factory.finish(review['latest'],decision='accept');self.rt.tick(fresh)
        self.assertEqual(self.rt.status(fresh)['status'],'awaiting_user')
        pipelines.tick(self.state)
        self.assertIsNone(self.state.db.execute("SELECT request_id FROM relay_pipeline_steps WHERE pipeline=? AND id='finish'",(self.pid,)).fetchone()[0])
        artifact=self.rt.output(fresh,'app','delivery/candidate.3dm')
        spec=self.rt.spec(self.rt.task(fresh,'app'));paths=spec.get('selection_outputs',[artifact['path']])
        members=[self.rt.output(fresh,'app',p)['id'] for p in paths]
        self.rt.select(fresh,'app',artifact['id'],spec['user_gate'],'Explicit fixture selection',artifacts=members)
        pipelines.tick(self.state);pipelines.tick(self.state)
        next_step=self.state.db.execute("SELECT request_id FROM relay_pipeline_steps WHERE pipeline=? AND id='finish'",(self.pid,)).fetchone()
        self.assertIsNotNone(next_step[0])
        context=pipelines.request_context(self.state,next_step[0])
        self.assertEqual({a['artifact'] for a in context['inputs']['sources']},set(members))

    def test_startup_and_legacy_workflows_do_not_launch_repair_workers(self):
        self.setup_failure(startup=True);pipelines.tick(self.state)
        self.assertEqual(self.repair()['status'], 'blocked');self.assertIsNone(self.repair()['preparation'])
        self.assertIn('does not confirm', self.repair()['error']);self.assertEqual(len(self.factory.calls), 1)

    def test_no_retroactive_budget_grant(self):
        self.setup_failure(legacy=True);pipelines.tick(self.state)
        self.assertIsNone(self.repair());self.assertEqual(len(self.factory.calls), 1)

    def test_uncertain_submission_is_never_repaired(self):
        self.setup_failure()
        with transaction(self.state.db):self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE run=?", (self.parent,))
        pipelines.tick(self.state);self.assertIsNone(self.repair());self.assertEqual(len(self.factory.calls), 1)

    def test_reviewer_rejection_does_not_publish_start_or_repeat(self):
        self.setup_failure();pipelines.tick(self.state);self.finish_preparation(rejected=True)
        pipelines.tick(self.state);pipelines.tick(self.state)
        self.assertEqual(self.repair()['status'], 'blocked');self.assertIsNone(self.repair()['plan_id'])
        self.assertEqual(len(self.factory.calls), 3)

    def test_diagnosis_requiring_input_does_not_publish_code_start(self):
        self.setup_failure();pipelines.tick(self.state);self.finish_preparation(decision='needs_input')
        pipelines.tick(self.state)
        self.assertEqual(self.repair()['status'], 'blocked');self.assertIn('Review host settings', self.repair()['error'])

    def test_pause_stops_queued_repair_dispatch_and_resume_keeps_identity(self):
        self.setup_failure();pipelines.tick(self.state);child = self.repair()['preparation']
        with transaction(self.state.db):pipelines.control(self.state, self.pid, 'pause')
        self.worker.tick();self.worker.tick();self.assertEqual(len(self.factory.calls), 1)
        with transaction(self.state.db):pipelines.control(self.state, self.pid, 'resume')
        self.worker.tick();self.worker.tick();self.assertEqual(len(self.factory.calls), 2)
        self.assertEqual(self.repair()['preparation'], child)

    def test_changed_failure_evidence_blocks_prepared_repair(self):
        self.setup_failure();pipelines.tick(self.state);self.finish_preparation()
        with transaction(self.state.db):self.state.put('production-control-epoch:' + self.parent, 99)
        pipelines.tick(self.state);self.assertIn('changed', self.repair()['error']);self.assertIsNone(self.repair()['plan_id'])

    def test_tampered_reviewed_candidate_blocks_start(self):
        self.setup_failure();pipelines.tick(self.state);child = self.finish_preparation();pipelines.tick(self.state)
        row = self.repair();self.assertIsNotNone(row['plan_id'], row['error'])
        plan = self.state.db.execute('SELECT * FROM production_plans WHERE id=?', (row['plan_id'],)).fetchone()
        artifact = self.rt.output(child, 'prepare_repair', 'delivery/model.py');Path(artifact['blob']).chmod(0o600);Path(artifact['blob']).write_text('tampered')
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?', (plan['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?", (plan['event_id'],))
        with self.assertRaises(ValueError), transaction(self.state.db):planning.apply(self.state, plan['token'], 'start')
        self.assertIsNone(self.state.db.execute('SELECT run FROM production_plans WHERE id=?', (plan['id'],)).fetchone()[0])

    def test_blender_and_rhino_receipts_share_policy_without_template_matching(self):
        self.assertTrue(repairs.script_failure({'runs': [dict(mode='edit', returncode=1, stderr='Traceback (most recent call last):\nAPI error')]}, 'blender.run_python'))
        self.assertFalse(repairs.script_failure({'runs': [dict(mode='edit', returncode=None, timeout=True)]}, 'blender.run_python'))
        self.assertFalse(repairs.script_failure({'runs': [dict(mode='before', returncode=1, stderr='Traceback (most recent call last)')]}, 'blender.run_python'))

    def test_atomic_queue_rollback_leaves_no_worker_or_duplicate_and_restart_resumes(self):
        from bridge import State
        self.setup_failure()
        with self.assertRaisesRegex(RuntimeError,'rollback'),transaction(self.state.db):
            pipelines.advance_production(self.state,self.state.db.execute('SELECT * FROM relay_pipelines').fetchone(),self.step(),self.parent)
            raise RuntimeError('rollback')
        self.assertIsNone(self.repair());self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        pipelines.tick(self.state);child=self.repair()['preparation']
        self.state.db.close();self.state=State(self.root/'state.sqlite')
        pipelines.tick(self.state);pipelines.tick(self.state)
        self.assertEqual(self.repair()['preparation'],child)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_auto_repairs').fetchone()[0],1)
        self.assertEqual(len(self.factory.calls),1)

    def test_repair_budget_is_not_reset_by_another_failure(self):
        self.setup_failure();pipelines.tick(self.state);self.finish_preparation(rejected=True);pipelines.tick(self.state)
        with transaction(self.state.db):
            p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
            self.assertFalse(repairs.begin(self.state,p,self.step(),self.parent))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_auto_repairs').fetchone()[0],1)
        self.assertEqual(len(self.factory.calls),3)

    def test_repair_files_are_in_original_workflow_history(self):
        from task_relay import workflow_files
        self.setup_failure();pipelines.tick(self.state);child=self.finish_preparation()
        snapshot=workflow_files._snapshot(self.state,self.pid)
        self.assertIn(child,snapshot['stages'][0]['runs'])
        paths={a['path'] for a in snapshot['artifacts'] if a['run']==child}
        self.assertTrue({'delivery/model.py','delivery/diagnosis.json','delivery/review.md'}<=paths)

    def test_pending_feedback_and_cancellation_prevent_repair_dispatch(self):
        self.setup_failure();pipelines.tick(self.state)
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,status,created) VALUES (999,'Change the scope',?,'gemini','fixture','queued',0)",(self.parent,))
        self.worker.tick();self.worker.tick();self.assertEqual(len(self.factory.calls),1)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE orchestrator_chats SET status='answered' WHERE id=999")
            pipelines.control(self.state,self.pid,'cancel')
        self.worker.tick();self.worker.tick();pipelines.tick(self.state)
        self.assertEqual(len(self.factory.calls),1)

    def test_missing_failure_receipt_is_actionable_without_an_ai_call(self):
        self.setup_failure()
        artifact=self.rt.output(self.parent,'app','delivery/execution.json');Path(artifact['blob']).unlink()
        pipelines.tick(self.state)
        self.assertEqual(self.repair()['status'],'blocked');self.assertIsNone(self.repair()['preparation'])
        self.assertEqual(len(self.factory.calls),1)

    def test_failure_after_registration_rolls_back_queued_worker(self):
        self.setup_failure()
        with patch('task_relay.pipelines.notice',side_effect=[ValueError('fixture failed notice'),None]):pipelines.tick(self.state)
        self.assertEqual(self.repair()['status'],'blocked');self.assertIsNone(self.repair()['preparation'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)

    def test_repair_review_attachments_are_required_for_start(self):
        self.setup_failure();pipelines.tick(self.state);self.finish_preparation();pipelines.tick(self.state)
        plan=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(self.repair()['plan_id'],)).fetchone()
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(plan['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=? AND id NOT LIKE '%:repair-review'",(plan['event_id'],))
        with self.assertRaisesRegex(ValueError,'independent review'),transaction(self.state.db):planning.apply(self.state,plan['token'],'start')


if __name__ == '__main__':unittest.main()
