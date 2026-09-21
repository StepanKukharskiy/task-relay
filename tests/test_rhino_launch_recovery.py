"""A confirmed pre-launch refusal can re-propose exact code, never replay it."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from orchestrator.storage import transaction
from orchestrator.step_runner import execute
from task_relay import production_planning as planning,production_control as pc
from task_relay import production_continuations as continuations
from tests import test_rhino_planning as fixture


class Tests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self);del self.fail
        signature=patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/rhino'})
        signature.start();self.addCleanup(signature.stop)
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    setup_plan=fixture.Tests.setup_plan

    def delivered(self,row):
        self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
        self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))

    def stopped(self,launched=False,startup=False):
        row=self.setup_plan()
        with transaction(self.state.db):
            self.delivered(row);planning.apply(self.state,row['token'],'start')
        run=self.row()['run'];worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        aid=self.rt.task(run,'app')['latest'];session=self.factory.sessions[aid]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        refusal={'passed':False,'returncode':None,'worker':None,'launched':launched,
                 'error_code':'rhino_already_running','existing_pids':[42],'error':'Selected Rhino is already running.'}
        if startup:refusal.update(launched=True,returncode=-9,pid=314,timeout=True,startup_received=False,error_code='rhino_startup_timeout',error='Startup timed out.')
        with patch('task_relay.rhino_host.run',return_value=refusal):result=execute(session['frozen'],control)
        session['status']={'status':'finished','exit_code':0,'reason':None,'usage':[],'operation':result}
        worker.tick();self.assertEqual(self.rt.status(run)['status'],'blocked')
        return run

    def test_open_rhino_at_start_leaves_plan_ready_without_spending_attempt(self):
        row=self.setup_plan()
        with transaction(self.state.db):self.delivered(row)
        with patch('task_relay.rhino_host.running_instances',return_value=[42]),patch('task_relay.rhino_host.script_connection',side_effect=ValueError('No new execution attempt; continue this production again')),transaction(self.state.db):
            with self.assertRaisesRegex(ValueError,'No new execution attempt'):planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(len(self.factory.calls),0)

    def test_connected_open_session_allows_start_without_provider_call(self):
        row=self.setup_plan()
        with transaction(self.state.db):self.delivered(row)
        with patch('task_relay.rhino_host.running_instances',return_value=[42]),patch('task_relay.rhino_host.script_connection',return_value={'pid':42}),transaction(self.state.db):
            planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(len(self.factory.calls),0)

    def test_recovery_retains_exact_parameters_and_needs_new_start(self):
        run=self.stopped();old=self.rt.spec(self.rt.task(run,'app'))
        attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        with transaction(self.state.db):
            text=continuations.enqueue(self.state,{'id':99,'prompt':'Rhino is closed; continue the approved model execution.'},run)
        self.assertIn('Native execution recovery ready',text)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(self.row()['id'],)).fetchone()
        self.assertEqual(row['status'],'ready');self.assertEqual(row['calls'],0);self.assertIsNone(row['run'])
        new=next(t for t in json.loads(row['plan'])['tasks'] if t['id']=='app')
        self.assertEqual(new['execution'],old['execution']);self.assertEqual(new['limits'],old['limits'])
        self.assertEqual({i['artifact'] for i in old['inputs']},{i['artifact'] for i in new['inputs'] if i['artifact'] in {s['artifact'] for s in old['inputs']}})
        self.assertEqual(attempts,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')])
        self.assertEqual(len(self.factory.calls),1)
        with self.assertRaisesRegex(ValueError,'complete plan card'),transaction(self.state.db):planning.apply(self.state,row['token'],'start')
        with transaction(self.state.db):self.delivered(row);planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)
        self.assertEqual(len(self.factory.calls),1)  # Start commits; dispatch is a later scheduler action.

    def test_recovery_refreshes_old_registered_criteria_but_preserves_history(self):
        from orchestrator.execution import REGISTRY
        run=self.stopped()
        parent=self.row();old=self.rt.spec(self.rt.task(run,'app'))
        attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        assignments=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_assignments')]
        current=copy.deepcopy(REGISTRY['rhino.run_python'])
        current['criteria']=['Current registered completion evidence for the same operation version.']
        with patch.dict(REGISTRY,{'rhino.run_python':current}):
            with transaction(self.state.db):
                reply=continuations.enqueue(self.state,{'id':99,'prompt':'continue my landscape model'},run)
            self.assertIn('recovery ready',reply)
            row=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(parent['id'],)).fetchone()
            new=next(t for t in json.loads(row['plan'])['tasks'] if t['id']=='app')
            self.assertEqual(new['criteria'],current['criteria'])
            for key in ('execution','outputs','limits','max_attempts'):
                self.assertEqual(new[key],old[key])
            update=json.loads(row['context'])['registered_criteria_updates'][0]
            self.assertEqual(update['previous'],old['criteria']);self.assertEqual(update['current'],new['criteria'])
            self.assertIn('completion criteria refreshed',planning.preview(row))
            self.assertEqual(self.state.db.execute('SELECT result FROM production_plans WHERE id=?',(parent['id'],)).fetchone()[0],parent['result'])
            self.assertEqual(attempts,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')])
            self.assertEqual(assignments,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_assignments')])
            with self.assertRaisesRegex(ValueError,'complete plan card'),transaction(self.state.db):planning.apply(self.state,row['token'],'start')
            with transaction(self.state.db):self.delivered(row);planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)
            self.assertEqual(len(self.factory.calls),1)

    def test_recovery_cannot_silently_upgrade_operation_version(self):
        from orchestrator.execution import REGISTRY
        run=self.stopped();current=copy.deepcopy(REGISTRY['rhino.run_python']);current['version']+=1
        with patch.dict(REGISTRY,{'rhino.run_python':current}),transaction(self.state.db):
            with self.assertRaisesRegex(ValueError,'version is no longer supported'):
                planning.prepare_host_launch_recovery(self.state,run,'continue')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_terminated_startup_recovers_only_with_ready_connection_and_fresh_start(self):
        run=self.stopped(startup=True);old=self.rt.spec(self.rt.task(run,'app'))
        attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        with patch('task_relay.rhino_host.running_instances',return_value=[456]),patch('task_relay.rhino_host.script_connection',return_value={'pid':456}),transaction(self.state.db):
            ident=planning.prepare_host_launch_recovery(self.state,run,'Continue after resolving startup')
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        operation=next(t for t in json.loads(row['plan'])['tasks'] if t['id']=='app')
        self.assertEqual(operation['execution'],old['execution']);self.assertEqual(operation['limits'],old['limits'])
        self.assertEqual(json.loads(row['context'])['execution_recovery']['assessment']['action'],'retry_unchanged')
        self.assertIn('terminated before the script execution phase',planning.preview(row))
        self.assertEqual(attempts,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')])
        self.assertEqual(len(self.factory.calls),1)
        with self.assertRaisesRegex(ValueError,'complete plan card'),transaction(self.state.db):planning.apply(self.state,row['token'],'start')

    def test_startup_recovery_rejects_surviving_pid_or_unavailable_connection(self):
        run=self.stopped(startup=True)
        with patch('task_relay.rhino_host.running_instances',return_value=[314]),transaction(self.state.db):
            with self.assertRaisesRegex(ValueError,'still present'):planning.prepare_host_launch_recovery(self.state,run,'Continue')
        with patch('task_relay.rhino_host.script_connection',side_effect=ValueError('Connection unavailable')),transaction(self.state.db):
            with self.assertRaisesRegex(ValueError,'Connection unavailable'):planning.prepare_host_launch_recovery(self.state,run,'Continue')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_startup_recovery_never_replays_model_phase_or_ambiguous_exit(self):
        run=self.stopped(startup=True);task=self.rt.task(run,'app');artifact=self.rt.output(run,'app','delivery/execution.json')
        receipt=json.loads(Path(artifact['blob']).read_text());spec=self.rt.spec(task)
        for change in ({'mode':'model'},{'returncode':None},{'transport':'shared_document'},{'worker':{'passed':False}}):
            value=copy.deepcopy(receipt);value['runs'][0].update(change)
            with patch.object(self.rt,'spec',return_value=spec),patch.object(planning.json,'loads',return_value=value):
                self.assertNotEqual(planning.host_recovery_assessment(self.rt,run,task)[2]['action'],'retry_unchanged')

    def test_open_session_and_any_launch_evidence_refuse_unchanged_recovery(self):
        run=self.stopped()
        with patch('task_relay.rhino_host.running_instances',return_value=[42]),patch('task_relay.rhino_host.script_connection',side_effect=ValueError('No new execution attempt; continue this production again')),transaction(self.state.db):
            with self.assertRaisesRegex(ValueError,'continue this production again'):
                planning.prepare_host_launch_recovery(self.state,run,'Continue')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        task=self.rt.task(run,'app');artifact=self.rt.output(run,'app','delivery/execution.json')
        receipt=json.loads(Path(artifact['blob']).read_text());spec=self.rt.spec(task)
        for change in ({'launched':True},{'pid':42},{'worker':{'passed':False}},{'mode':'edit'}):
            value=copy.deepcopy(receipt);value['runs'][0].update(change)
            with patch.object(self.rt,'spec',return_value=spec),patch.object(planning.json,'loads',return_value=value):
                self.assertNotEqual(planning.host_recovery_assessment(self.rt,run,task)[2]['action'],'retry_unchanged')
