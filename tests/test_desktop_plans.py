"""Desktop planner request identity, local review and exact Start boundary."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from orchestrator import executors
from orchestrator.storage import transaction
from task_relay.bridge import State
from task_relay.desktop_plans import DesktopPlanError, create, decide, detail, list_plans, prepare, process_requests
from task_relay.production_planning import Worker
from task_relay.relay_paths import Paths
from task_relay import relay_channels
from tests.test_orchestrator import pair


class DesktopPlansTests(unittest.TestCase):
    def setUp(self):
        from orchestrator import worker_capabilities
        catalog=patch.object(worker_capabilities,'capture',side_effect=lambda _state,default,locked=False:[worker_capabilities.entry(default)])
        catalog.start();self.addCleanup(catalog.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.paths = Paths(root / 'app', root / 'data', root / 'workspaces', root / 'generated')
        self.project = root / 'project'
        self.project.mkdir()
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        with self.state.db:
            self.state.put('health:desktop-plans', {'interface_version': 1, 'last_success': time.time()})
            self.state.put('production-planner-policy', {'backend': pair()['backend']})

    def request(self, request_id=None):
        return create('Write a source-grounded brief.', 'No rendering.', str(self.project), None,
                      request_id or str(uuid.uuid4()), self.paths)

    def test_duplicate_request_is_one_planning_job_and_channel_is_desktop(self):
        request_id = str(uuid.uuid4())
        first = self.request(request_id)
        second = self.request(request_id)
        self.assertEqual(first['plan_id'], second['plan_id'])
        with self.assertRaises(DesktopPlanError):
            create('Different brief', '', str(self.project), None, request_id, self.paths)
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()['status'],
                         'accepted', self.state.db.execute('SELECT result FROM desktop_plan_requests').fetchone()[0])
        row = self.state.db.execute('SELECT * FROM production_plans').fetchone()
        self.assertEqual(row['channel'], 'desktop')
        self.assertEqual(row['status'], 'queued')
        self.assertTrue(json.loads(row['options'])['planning_only'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0], 1)
        self.assertEqual(list_plans(self.paths)['plans'][0]['request_status'], 'accepted')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_failed_admission_rolls_back_partial_database_work_and_keeps_receipt(self):
        self.request()
        def fail(state, *_):
            state.db.execute("INSERT INTO relay_event_channels VALUES ('partial-desktop-plan','desktop')")
            raise ValueError('Configured executor unavailable')
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch('task_relay.production_planning.enqueue', side_effect=fail)):
            process_requests(self.state)
        row = self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()
        self.assertEqual(row['status'], 'rejected')
        self.assertIn('executor unavailable', row['result'])
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM relay_event_channels WHERE event_id='partial-desktop-plan'").fetchone())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0], 0)

    def test_missing_input_question_is_visible_for_revision(self):
        self.request()
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        answer = {'research_advice': {'recommended_mode':'none','requirement':'optional','reason':'A brief can use the supplied text; documentation could resolve missing facts.','questions':['Which source version supports the brief?']}, 'decision': 'needs_input', 'message': 'Which source version should be revised?', 'plan': None}
        Worker(self.state, lambda *_: (json.dumps(answer), {'total_tokens': 1})).tick()
        ident = self.state.db.execute('SELECT id FROM production_plans').fetchone()[0]
        view = detail(ident, self.paths)
        self.assertEqual(view['project'], str(self.project))
        self.assertEqual(view['status'], 'needs_input')
        self.assertEqual(view['preview'], answer['message'])
        self.assertEqual(view['research_advice'],answer['research_advice'])
        self.assertTrue(view['review_digest'])
        create('Use version 2 of the saved brief.', '', str(self.project), ident,
               str(uuid.uuid4()), self.paths)
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        revised = self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?', (ident,)).fetchone()
        self.assertIsNotNone(revised)
        self.assertIn('Write a source-grounded brief.', revised['request'])
        self.assertIn('Use version 2 of the saved brief.', revised['request'])
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?', (ident,)).fetchone()[0], 'superseded')

    def test_exact_review_required_before_desktop_start(self):
        self.request()
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()['status'],
                         'accepted', self.state.db.execute('SELECT result FROM desktop_plan_requests').fetchone()[0])
        proposal = pair(gate='User selects the brief', max_attempts=1)
        for task in proposal['tasks']:
            task['tools'] = ['files', 'shell']
            task['limits'] = {'seconds': 600, 'tool_calls': 60, 'output_bytes': 100000000}
        answer = {'research_advice': {'recommended_mode':'none','requirement':'optional','reason':'Draft the requested brief from its existing context.','questions':['Which external facts need documentation?']}, 'decision': 'ready', 'message': 'One brief and independent review.',
                  'input_basis': {'mode': 'new', 'artifacts': []},
                  'plan': {key: proposal[key] for key in ('brief', 'tasks')}}
        Worker(self.state, lambda *_: (json.dumps(answer), {'total_tokens': 1})).tick()
        ident = self.state.db.execute('SELECT id FROM production_plans').fetchone()[0]
        first = detail(ident, self.paths)
        self.assertEqual(first['status'], 'ready')
        self.assertTrue(first['planning_only'])
        self.assertEqual(first['research_advice'],answer['research_advice'])
        self.assertEqual(first['research']['advice'],answer['research_advice'])
        self.assertTrue(first['documents'])
        with self.assertRaisesRegex(ValueError, 'no execution authorization'):
            decide(ident, 'start', first['review_digest'], self.paths)
        with self.assertRaisesRegex(DesktopPlanError, 'Restart|changed|ready'):
            decide(ident, 'start', 'incorrect', self.paths)
        prepared = prepare(ident, self.paths)
        self.assertFalse(prepared['planning_only'])
        self.assertNotEqual(first['review_digest'], prepared['review_digest'])
        with self.assertRaisesRegex(DesktopPlanError, 'changed'):
            decide(ident, 'start', first['review_digest'], self.paths)
        result = decide(ident, 'start', prepared['review_digest'], self.paths)
        self.assertEqual(result['status'], 'started')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans').fetchone()[0], 'started')
        event = self.state.db.execute("SELECT id FROM outbox WHERE id LIKE 'production:%:planner-started'").fetchone()[0]
        self.assertEqual(relay_channels.event_channel(self.state, event), 'desktop')
        # Desktop Start remains local and does not need a messenger pairing.
        from task_relay import result_handoff, job_ownership
        run=self.state.db.execute('SELECT run FROM production_plans WHERE id=?',(ident,)).fetchone()[0]
        scoped=relay_channels.ScopedState(self.state,'desktop')
        self.assertEqual(result_handoff.ancestry(scoped,run)[0],ident)
        with transaction(self.state.db):
            owner=job_ownership.record_standalone(self.state.db,ident,run,'desktop')
        self.assertTrue(owner.startswith('job-'))
        self.assertIsNone(self.state.db.execute("SELECT data FROM production_events WHERE run=? AND kind='desktop_plan_transferred'",(run,)).fetchone())
        self.assertEqual(detail(ident,self.paths)['status'],'started')
        with self.assertRaises(DesktopPlanError):decide(ident,'start',prepared['review_digest'],self.paths)

    def saved_ready_plan(self, channel='telegram'):
        self.request()
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai','fixture-model')),
              patch.object(executors,'available')):
            process_requests(self.state)
        proposal=pair(gate='User selects the brief',max_attempts=1)
        for task in proposal['tasks']:
            task['tools']=['files','shell']
            task['limits']={'seconds':600,'tool_calls':60,'output_bytes':100000000}
        answer={'research_advice': {'recommended_mode':'none','requirement':'optional','reason':'Draft the requested brief from its existing context.','questions':['Which external facts need documentation?']}, 'decision':'ready','message':'One brief and review.',
                'input_basis':{'mode':'new','artifacts':[]},
                'plan':{key:proposal[key] for key in ('brief','tasks')}}
        Worker(self.state,lambda *_:(json.dumps(answer),{'total_tokens':1})).tick()
        row=self.state.db.execute('SELECT * FROM production_plans').fetchone()
        with self.state.db:
            self.state.db.execute('UPDATE production_plans SET channel=? WHERE id=?',(channel,row['id']))
            self.state.db.execute('UPDATE relay_request_channels SET channel=? WHERE request_id=?',(channel,row['request_id']))
        return row['id']

    def test_expired_shared_plan_requires_renewal_and_exact_documents_then_deduplicates_start(self):
        ident=self.saved_ready_plan()
        with self.state.db:self.state.db.execute('UPDATE production_plans SET expires=1 WHERE id=?',(ident,))
        first=detail(ident,self.paths,shared=True)
        self.assertTrue(first['expired'])
        with self.assertRaisesRegex(ValueError,'expired'):
            decide(ident,'start',first['review_digest'],self.paths)
        prepared=prepare(ident,self.paths,review_digest=first['review_digest'])
        self.assertFalse(prepared['expired']);self.assertFalse(prepared['planning_only'])
        with self.assertRaisesRegex(DesktopPlanError,'changed'):
            decide(ident,'start',first['review_digest'],self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        request_id=str(uuid.uuid4())
        started=decide(ident,'start',prepared['review_digest'],self.paths,request_id=request_id)
        self.assertEqual(decide(ident,'start',prepared['review_digest'],self.paths,request_id=request_id),started)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        run=self.state.db.execute('SELECT run FROM production_plans WHERE id=?',(ident,)).fetchone()[0]
        from task_relay.result_handoff import channel_for
        self.assertEqual(channel_for(self.state,run),'telegram')
        with self.assertRaisesRegex(DesktopPlanError,'different decision'):
            decide(ident,'discard',prepared['review_digest'],self.paths,request_id=request_id)

    def test_shared_start_still_checks_workflow_ownership_and_changed_documents(self):
        ident=self.saved_ready_plan('messages')
        prepared=prepare(ident,self.paths)
        document=self.state.db.execute('SELECT path FROM media_outbox WHERE id=?',(prepared['documents'][0]['id'],)).fetchone()
        original=Path(document[0]).read_text();Path(document[0]).chmod(0o600);Path(document[0]).write_text(original+'\nChanged document')
        with self.assertRaisesRegex(DesktopPlanError,'changed'):
            decide(ident,'start',prepared['review_digest'],self.paths)
        Path(document[0]).write_text(original)
        with patch('task_relay.pipelines.verify_start',side_effect=ValueError('Workflow is paused')):
            with self.assertRaisesRegex(ValueError,'paused'):
                decide(ident,'start',prepared['review_digest'],self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?',(ident,)).fetchone()[0],'ready')

    def test_discard_remove_and_restore_retains_exact_plan_and_documents(self):
        ident=self.saved_ready_plan();view=prepare(ident,self.paths)
        decide(ident,'discard',view['review_digest'],self.paths)
        view=detail(ident,self.paths,shared=True)
        counts=[self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('production_plans','production_plan_calls','media_outbox')]
        key=str(uuid.uuid4());result=decide(ident,'archive',view['review_digest'],self.paths,request_id=key)
        self.assertEqual(decide(ident,'archive',view['review_digest'],self.paths,request_id=key),result)
        from task_relay.desktop_workspace import jobs
        self.assertEqual(jobs(paths=self.paths)['total'],0)
        self.assertEqual(counts,[self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('production_plans','production_plan_calls','media_outbox')])
        decide(ident,'restore',detail(ident,self.paths,shared=True)['review_digest'],self.paths)
        self.assertEqual(jobs(paths=self.paths)['total'],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_expired_or_missing_document_plan_can_be_discarded_without_start(self):
        ident=self.saved_ready_plan()
        with self.state.db:self.state.db.execute('UPDATE production_plans SET expires=1 WHERE id=?',(ident,))
        view=detail(ident,self.paths,shared=True)
        self.assertTrue(view['expired'])
        document=self.state.db.execute('SELECT path FROM media_outbox WHERE id=?',(view['documents'][0]['id'],)).fetchone()
        Path(document[0]).unlink()
        view=detail(ident,self.paths,shared=True)
        self.assertTrue(view['review_error'])
        with self.assertRaisesRegex(DesktopPlanError,'unavailable'):
            decide(ident,'start',view['review_digest'],self.paths)
        decide(ident,'discard',view['review_digest'],self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_cancelled_workflow_stage_has_a_visible_blocker_and_cannot_start(self):
        ident=self.saved_ready_plan();view=prepare(ident,self.paths)
        with self.state.db:
            self.state.db.execute("INSERT INTO relay_pipelines VALUES ('pipeline',999,'Exact workflow','Workflow','{}','telegram','test','test','cancelled',0)")
            self.state.db.execute("INSERT INTO relay_pipeline_steps (pipeline,position,id,status,target_kind,target) VALUES ('pipeline',0,'stage','running','plan_production',?)",(ident,))
        current=detail(ident,self.paths,shared=True)
        self.assertIn('cancelled',current['execution_blocker'])
        with self.assertRaisesRegex(DesktopPlanError,'changed'):
            decide(ident,'start',view['review_digest'],self.paths)
        with self.assertRaisesRegex(ValueError,'paused or cancelled'):
            decide(ident,'start',current['review_digest'],self.paths)
        from task_relay.desktop_workspace import jobs
        self.assertEqual(jobs(paths=self.paths)['items'][0]['status'],'blocked')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_restoring_then_removing_again_gets_a_new_confirmation_identity(self):
        ident=self.saved_ready_plan();view=detail(ident,self.paths,shared=True)
        decide(ident,'discard',view['review_digest'],self.paths)
        original=detail(ident,self.paths,shared=True)
        decide(ident,'archive',original['review_digest'],self.paths,request_id=str(uuid.uuid4()))
        removed=detail(ident,self.paths,shared=True)
        decide(ident,'restore',removed['review_digest'],self.paths,request_id=str(uuid.uuid4()))
        restored=detail(ident,self.paths,shared=True)
        self.assertNotEqual(original['review_digest'],restored['review_digest'])
        decide(ident,'archive',restored['review_digest'],self.paths,request_id=str(uuid.uuid4()))
        self.assertTrue(detail(ident,self.paths,shared=True)['archived'])

    def test_transfer_preserves_parent_requests_and_rejects_foreign_or_executed_ancestry(self):
        from task_relay.desktop_plans import transfer_to_telegram
        from orchestrator.runtime import Runtime
        from task_relay.production_control import root
        from task_relay import result_handoff
        runtime=Runtime(root(self.state),connection=self.state.db)
        with self.state.db:
            for n,parent in [(1,None),(2,'transfer-1')]:
                self.state.db.execute("""INSERT INTO production_plans
                    (id,request_id,parent_id,channel,request,options,context,context_hash,provider,model,status,token,expires,created)
                    VALUES (?,?,?,'desktop',?,'{}','{}','hash','test','test','ready',?,0,0)""",
                    ('transfer-'+str(n),100+n,parent,'Exact request '+str(n),'token-'+str(n)))
        before=[dict(r) for r in self.state.db.execute("SELECT * FROM production_plans ORDER BY id")]
        for mutation in ("channel='messages'", "run='already-executed'"):
            with self.assertRaisesRegex(DesktopPlanError,'unexecuted'):
                with transaction(self.state.db):
                    self.state.db.execute("UPDATE production_plans SET "+mutation+" WHERE id='transfer-1'")
                    transfer_to_telegram(self.state,runtime,'transfer-2','transfer-run')
            self.assertEqual([dict(r) for r in self.state.db.execute('SELECT * FROM production_plans ORDER BY id')],before)
            self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_events WHERE kind='desktop_plan_transferred'").fetchone()[0],0)
        with transaction(self.state.db):
            transfer_to_telegram(self.state,runtime,'transfer-2','transfer-run')
            self.state.db.execute("UPDATE production_plans SET run='transfer-run',status='started' WHERE id='transfer-2'")
            relay_channels.bind(self.state,'production','transfer-run','telegram')
        self.assertEqual(result_handoff.ancestry(self.state,'transfer-run')[0],'transfer-1')
        after=[dict(r) for r in self.state.db.execute('SELECT * FROM production_plans ORDER BY id')]
        self.assertEqual([r['request'] for r in before],[r['request'] for r in after])
        receipt=json.loads(self.state.db.execute("SELECT data FROM production_events WHERE kind='desktop_plan_transferred'").fetchone()[0])
        self.assertEqual([r['id'] for r in receipt['plans']],['transfer-2','transfer-1'])


if __name__ == '__main__':
    unittest.main()
