"""Recovery decisions must hold across applications and unfamiliar error text."""
import unittest
from orchestrator.native_recovery import assess
from orchestrator.recovery import Evidence, decide


class PolicyTests(unittest.TestCase):
    def test_unknown_or_live_work_always_requires_reconciliation(self):
        for evidence in (Evidence(), Evidence('not_started', False), Evidence('failed', False, True)):
            self.assertEqual(decide(evidence)['action'], 'reconcile')
        self.assertEqual(decide(Evidence('completed', True))['action'], 'retain_result')
        self.assertEqual(decide(Evidence('failed', True))['action'], 'resolve_environment')

    def test_pre_execution_is_not_tied_to_a_specific_error(self):
        for capability in ('rhino.run_python', 'sketchup.run_ruby'):
            for message in ('License unavailable', 'New unrecognized startup problem', ''):
                receipt={'runs':[dict(mode='before', launched=False, error=message)]}
                self.assertEqual(assess(receipt,capability)['action'], 'retry_unchanged')
        receipt={'runs':[dict(mode='before', returncode=1, stderr='New platform error')]}
        self.assertEqual(assess(receipt,'blender.run_python')['action'], 'retry_unchanged')

    def test_owned_baseline_exit_is_not_an_execution_timeout(self):
        for capability in ('rhino.run_python', 'sketchup.run_ruby'):
            baseline=dict(mode='before', launched=True, pid=10, returncode=-9, timeout=True)
            self.assertEqual(assess({'runs':[baseline]},capability)['action'],'retry_unchanged')
            for changes in ({'mode':'model'}, {'returncode':None}, {'transport':'shared_document'}, {'submitted':True}):
                entry={**baseline,**changes}
                self.assertEqual(assess({'runs':[entry]},capability)['action'],'reconcile')

    def test_order_contradictions_and_validation_failures_never_allow_retry(self):
        before=dict(mode='before',launched=False)
        variants=[{'runs':[dict(mode='model'),before]}, {'runs':[before,before]},
                  {'runs':[before],'validation_error':'Mismatched receipt'},
                  {'runs':[before],'passed':True}, {'runs':[before],'capability':'unknown'},
                  {'runs':'malformed'}, {'runs':[None]}]
        for receipt in variants:
            with self.subTest(receipt=receipt):
                self.assertEqual(assess(receipt,'rhino.run_python')['action'],'reconcile')
        self.assertEqual(assess({'runs':[before]},'unregistered.run')['action'],'reconcile')

    def test_terminal_failures_route_to_reviewed_repair_across_hosts(self):
        for capability,mode in [('rhino.run_python','model'),('sketchup.run_ruby','model'),('blender.run_python','edit')]:
            failure=dict(mode=mode,returncode=1,worker=dict(passed=False,error='API failure'),stderr='Traceback (most recent call last):\nAPI failure')
            result=assess({'runs':[failure]},capability)
            self.assertEqual(result['action'],'prepare_reviewed_repair')
            self.assertFalse(result['automatic_dispatch'])
            failure['timeout']=True
            self.assertEqual(assess({'runs':[failure]},capability)['action'],'reconcile')


class BlenderContinuationTests(unittest.TestCase):
    def setUp(self):
        from tests import test_production_planning as fixture
        from unittest.mock import patch
        fixture.Tests.setUp(self)
        for target,value in [('task_relay.host_apps.blender',dict(available=True,executable='/fixture/blender',evidence='fixture')),
                             ('task_relay.host_evidence.application_signature',{'path':'/fixture/blender'})]:
            mock=patch(target,return_value=value);mock.start();self.addCleanup(mock.stop)

    from tests.test_production_planning import Tests as _Fixture
    from tests.test_blender_edit_planning import Tests as _Blender
    tearDown=_Fixture.tearDown
    request=_Fixture.request
    action=_Fixture.action
    queue=_Fixture.queue
    row=_Fixture.row
    response=_Fixture.response
    setup_plan=_Blender.setup_plan

    def test_blender_pre_execution_failure_uses_same_bounded_successor_planner(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from orchestrator.storage import transaction
        from orchestrator.step_runner import execute
        from task_relay import production_planning as planning, production_control as pc
        from task_relay import production_continuations as continuations
        row=self.setup_plan()
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
            planning.apply(self.state,row['token'],'start')
        run=self.row()['run'];worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        aid=self.rt.task(run,'app')['latest'];session=self.factory.sessions[aid]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        with patch('orchestrator.blender_edit.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=b'',stderr=b'Baseline could not open scene')):
            result=execute(session['frozen'],control)
        session['status']={'status':'finished','exit_code':0,'reason':None,'usage':[],'operation':result}
        worker.tick();self.assertEqual(self.rt.status(run)['status'],'blocked')
        old=self.rt.spec(self.rt.task(run,'app'))
        attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        with transaction(self.state.db):
            reply=continuations.enqueue(self.state,{'id':99,'prompt':'Environment fixed; continue'},run)
        self.assertIn('Native execution recovery ready',reply)
        fresh=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(row['id'],)).fetchone()
        self.assertIsNone(fresh['run']);self.assertEqual(fresh['calls'],0)
        new=next(t for t in json.loads(fresh['plan'])['tasks'] if t['id']=='app')
        for key in ('execution','limits','outputs'):
            self.assertEqual(new[key],old[key])
        self.assertEqual(attempts,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')])
        self.assertEqual(len(self.factory.calls),1)
        with self.assertRaisesRegex(ValueError,'complete plan card'),transaction(self.state.db):
            planning.apply(self.state,fresh['token'],'start')


if __name__=='__main__':unittest.main()
