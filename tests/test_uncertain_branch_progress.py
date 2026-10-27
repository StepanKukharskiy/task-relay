import unittest
from orchestrator.runtime import uncertainty_progress

class Tests(unittest.TestCase):
    def snapshot(self, slots=2, resource=None, locked=(), active=False):
        tasks=[dict(id='unknown',status='uncertain',attempts=1),dict(id='dependent',status='queued',attempts=0),dict(id='independent',status='running' if active else 'queued',attempts=0)]
        specs=[dict(id='unknown',dependencies=[],max_attempts=1),dict(id='dependent',dependencies=['unknown'],max_attempts=1),dict(id='independent',dependencies=[],max_attempts=1,resource=resource)]
        return uncertainty_progress(tasks,specs,[dict(state='uncertain')],slots,locked)
    def test_independent_progress_retains_dependent_hold(self):
        result=self.snapshot()
        self.assertTrue(result['can_continue'])
        self.assertEqual(result['runnable_independent'],['independent'])
        self.assertEqual(result['held_dependents'],['dependent'])
    def test_unknown_call_still_occupies_slot(self):
        self.assertFalse(self.snapshot(slots=1)['can_continue'])
    def test_unknown_resource_remains_locked(self):
        self.assertFalse(self.snapshot(resource='browser',locked=['browser'])['can_continue'])
    def test_running_independent_work_keeps_progress_visible(self):
        self.assertEqual(self.snapshot(slots=1,active=True)['active_independent'],['independent'])
    def test_transitive_input_hold(self):
        tasks=[dict(id='a',status='uncertain',attempts=1),dict(id='b',status='completed',attempts=1),dict(id='c',status='queued',attempts=0)]
        specs=[dict(id='a',dependencies=[],max_attempts=1),dict(id='b',dependencies=['a'],max_attempts=1),dict(id='c',dependencies=[],inputs=[dict(from_task='b')],max_attempts=1)]
        result=uncertainty_progress(tasks,specs,[dict(state='uncertain')],2)
        self.assertEqual(result['held_dependents'],['b','c'])
        self.assertFalse(result['can_continue'])

class PipelineTests(unittest.TestCase):
    def test_existing_grant_only_and_deduplicated_receipt(self):
        from unittest.mock import patch
        from tests.test_pipelines import Tests as Fixture
        from task_relay import pipelines as pipe, production_control as pc, production_repairs
        from orchestrator.runtime import Runtime
        from orchestrator.storage import transaction
        fixture=Fixture()
        fixture.setUp()
        try:
            p,row,_,_=fixture.recovered_selected_stage(select=False)
            step=fixture.step(p,'report')
            status={'status':'uncertain','uncertainty_progress':{'can_continue':True,'uncertain_tasks':['a'],'runnable_independent':['b']}}
            with patch.object(Runtime,'status',return_value=status),patch.object(pc,'runtime_digest',return_value='approved'),patch.object(production_repairs,'dispatch_allowed',return_value=True):
                with transaction(fixture.state.db):
                    fixture.state.put('production-enabled:'+row['run'],'approved')
                    pipe.advance_production(fixture.state,p,step,row['run'])
                    pipe.advance_production(fixture.state,p,step,row['run'])
                self.assertEqual(fixture.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='uncertain_branch_progress'").fetchone()[0],1)
                fixture.state.put('production-enabled:'+row['run'],False)
                with self.assertRaisesRegex(ValueError,'Production uncertain'):
                    pipe.advance_production(fixture.state,p,step,row['run'])
                status['uncertainty_progress']['can_continue']=False
                fixture.state.put('production-enabled:'+row['run'],'approved')
                with self.assertRaisesRegex(ValueError,'Production uncertain'):
                    pipe.advance_production(fixture.state,p,step,row['run'])
        finally:
            fixture.tearDown()

class WorkerTests(unittest.TestCase):
    def test_worker_drains_dispatched_producer_without_starting_review_after_uncertainty(self):
        from tests.test_production_control import Tests as Fixture
        from tests.test_orchestrator import pair,task
        from task_relay import production_control as pc
        fixture=Fixture();fixture.setUp()
        try:
            value=pair();value['id']='branch';value['concurrency']=2
            value['tasks'].insert(0,task('unknown'))
            fixture.rt.create(value)
            digest=pc.runtime_digest(fixture.rt,'branch')
            with fixture.state.db:fixture.state.put('production-enabled:branch',digest)
            worker=fixture.worker();worker.tick()
            unknown=fixture.rt.task('branch','unknown')['latest']
            fixture.factory.sessions[unknown]['status']={'status':'uncertain','local_terminal':True,'reason':'outcome unknown'}
            worker.tick()
            self.assertEqual(fixture.state.get('production-enabled:branch'),digest)
            producer=fixture.rt.task('branch','produce')['latest'];self.assertIsNotNone(producer)
            fixture.factory.finish(producer);worker.tick()
            self.assertIsNotNone(fixture.rt.output('branch','produce','output.txt'))
            self.assertIsNone(fixture.rt.task('branch','review')['latest'])
            self.assertFalse(fixture.state.get('production-enabled:branch'))
            self.assertEqual(fixture.rt.task('branch','unknown')['latest'],unknown)
            self.assertEqual(fixture.rt.task('branch','unknown')['attempts'],1)
            self.assertEqual(fixture.rt.status('branch')['status'],'uncertain')
            self.assertEqual(len(fixture.factory.calls),2)
        finally:fixture.tearDown()
