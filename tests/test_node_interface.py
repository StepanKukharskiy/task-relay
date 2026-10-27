"""One runtime, named outputs, optional composition; no network/model calls."""
import copy,json,tempfile,unittest,sys,types,shutil
from pathlib import Path
from unittest.mock import patch,MagicMock
from orchestrator import job_owner,executors
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from tests import test_job_owner_loop as fixture
from tests.test_operation_session import CONFIG,Script

class Nodes(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.grant.update(delegation_version=4,execution_policy=dict(version=2,review='owner',public_read=True),execution_review_version=1)
        if self._testMethodName=='test_failed_completion_retains_text_and_restart_inherits_outputs':
            self.f.grant['execution_policy']['request_contract']=dict(mode='new_work',reason='Example',outcomes=[dict(id='report',kind='file',description='Code',count=1,format='.txt',checks=['fenced_code'],validation=[])])
        self.f.create();self.f.rt.tick('job')
        self.s=self.f.factory.sessions[self.f.rt.task('job','owner')['latest']]
        self.frozen=self.s['frozen'];self.control=Path(self.s['session']['control']);self.control.mkdir(parents=True,exist_ok=True)
        self.files=job_owner.files(self.frozen,self.control)
        self.owner=job_owner.Session(self.frozen,self.control,self.files);self.addCleanup(self.owner.rt.close)

    def result(self,text=None,**kw):
        return self.owner.call('node_result',dict(outputs={} if text is None else {'report':{'text':text}},summary='Requested result.',**kw))

    def test_one_call_actual_loop_delivers_text_without_model_bookkeeping(self):
        atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,fixture.BACKEND)))
        client=Script([('node_result',dict(outputs={'report':{'text':'Actual result.'}},summary='Done.'))])
        value=execute(self.frozen,self.control,client,lambda:(CONFIG,fixture.BACKEND))
        self.assertEqual(value['decision'],'delivered');self.assertEqual(len(client.requests),1)
        self.s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.f.rt.tick('job');self.assertEqual(self.f.rt.status('job')['status'],'completed')
        self.assertEqual(len(self.f.factory.calls),1)
        self.assertFalse(self.f.rt.db.execute("SELECT 1 FROM production_events WHERE run='job' AND kind='owner_artifact_inspected'").fetchone())
        names={x['name'] for x in job_owner.definitions(self.owner.grant)}
        self.assertIn('node_run',names);self.assertFalse(any(n.startswith('job_') for n in names))
        self.assertFalse(self.owner.completed)

    def test_failed_completion_retains_text_and_restart_inherits_outputs(self):
        with self.assertRaisesRegex(ValueError,'code example'):self.result('Incorrect prose')
        self.assertEqual(self.f.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='owner_result_saved'").fetchone()[0],1)
        self.result('```python\nprint(1)\n```',complete=False)
        self.owner.rt.close();self.owner=job_owner.Session(self.frozen,self.control,self.files);self.addCleanup(self.owner.rt.close)
        r=self.result();self.assertEqual(r['deliverables']['report']['review_status'],'unreviewed')
        self.assertFalse(r['user_acceptance']);self.assertEqual(len(self.f.factory.calls),1)

    def test_pending_external_read_blocks_finish_without_erasing_saved_result(self):
        p=self.owner.web.root/'source';p.mkdir(parents=True);(p/'http-claim.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unresolved'):self.result('Partial answer')
        self.assertEqual(self.f.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='node_output_bound'").fetchone()[0],1)
        self.assertFalse(self.owner.completed)

    def test_explicit_independent_review_is_not_waived(self):
        self.owner.grant['execution_policy']['review']='independent'
        with self.assertRaisesRegex(ValueError,'independent review'):self.result('Unreviewed draft')
        self.assertFalse(self.owner.completed)

    def test_batch_output_binding_is_atomic_and_rejects_unknown_ports(self):
        with self.assertRaisesRegex(ValueError,'Unknown output'):self.owner.call('node_result',dict(outputs={'report':{'text':'one'},'other':{'text':'two'}},summary='No'))
        self.assertFalse(self.f.rt.db.execute("SELECT 1 FROM production_events WHERE kind='owner_result_saved'").fetchone())

    def test_saved_versions_are_immutable_and_complete_uses_latest_binding(self):
        a=self.result('First',complete=False)['outputs']['report'];b=self.result('Second',complete=False)['outputs']['report']
        self.assertNotEqual(a,b);self.assertEqual(Path(self.f.rt.artifact(a)['blob']).read_text(),'First')
        self.assertIn('Second',json.dumps(self.owner.call('node_read',dict(reference={'task':'owner','output':'report'}))))
        self.assertEqual(self.result()['deliverables']['report']['artifact'],b)

    def test_node_composition_uses_existing_compiler_and_idempotent_admission(self):
        tasks=[dict(id='draft',objective='Write report',outputs=[dict(name='text',media_type='text/plain',purpose='Report')])]
        r=self.owner.call('node_run',dict(tasks=tasks))
        count=self.f.rt.db.execute("SELECT count(*) FROM production_tasks WHERE run='job'").fetchone()[0]
        self.assertEqual(count,2)
        self.assertEqual(self.owner.call('node_run',dict(tasks=tasks)),r)
        self.assertEqual(self.f.rt.db.execute("SELECT count(*) FROM production_tasks WHERE run='job'").fetchone()[0],count)
        self.assertEqual(self.f.rt.spec(self.f.rt.task('job','draft'))['outputs'][0]['path'],'outputs/text.txt')

    def test_connected_worker_output_is_resolved_by_code_and_requires_inspection(self):
        self.owner.call('node_run',dict(tasks=[dict(id='draft',objective='Write report',outputs=[dict(name='text',media_type='text/plain',purpose='Report')])]))
        self.f.rt.tick('job');aid=self.f.rt.task('job','draft')['latest']
        self.f.factory.finish(aid);self.f.rt.tick('job')
        # Existing owner is still physically running in this adapter fixture.
        args=dict(outputs={'report':{'task':'draft','output':'text'}},summary='Connected result.')
        with self.assertRaisesRegex(ValueError,'Inspect'):self.owner.call('node_result',args)
        a=self.f.rt.output('job','draft','outputs/text.txt')
        self.owner.call('node_read',dict(reference={'task':'draft','output':'text'}))
        result=self.owner.call('node_result',dict(outputs={},summary='Done.'))
        self.assertEqual(result['deliverables']['report']['artifact'],a['id'])
        self.assertEqual(len(self.f.rt.status('job')['tasks']),2)

    def test_failed_node_proposal_has_working_correction_surface_in_actual_loop(self):
        atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,fixture.BACKEND)))
        client=Script([
            ('node_run',dict(tasks=[dict(id='invalid',objective='Unavailable operation',operation='outside.grant')])),
            ('node_run',dict(tasks=[dict(id='corrected',objective='Write report',outputs=[dict(name='text',media_type='text/plain',purpose='Report')])]))])
        # Valid transport shape, but unavailable operation: existing recovery applies.
        value=execute(self.frozen,self.control,client,lambda:(CONFIG,fixture.BACKEND))
        self.assertEqual(value['outcome'],'yielded')
        self.assertEqual(self.f.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='owner_submission_rejected'").fetchone()[0],1)
        self.assertEqual(len(client.requests),2)
        self.assertEqual({t['id'] for t in self.f.rt.status('job')['tasks']},{'owner','corrected'})
        self.assertIn('node_run',json.dumps(client.requests[1]))
        self.assertNotIn('"name": "job_delegate"',json.dumps(client.requests[1]))

    def test_recovery_diagnostic_names_only_available_node_controls(self):
        r=self.owner.call('node_run',dict(tasks=[dict(id='bad',objective='Unavailable',operation='outside.grant')]))
        self.assertIn('node_run',r['correction']['next_action'])
        self.assertNotIn('job_delegate',r['correction']['next_action'])

    def test_partial_node_outputs_export_without_acceptance(self):
        a=self.result('Honest partial.',complete=False)['outputs']['report']
        self.s['status']=dict(status='finished',exit_code=1,reason='Source unavailable',external_outcome='no_pending_response',pending_requests=[])
        self.f.rt.tick('job');s=self.f.rt.status('job')
        self.assertEqual(s['status'],'blocked')
        self.assertEqual(s['delivery']['candidates'][0]['artifact'],a)
        self.assertEqual(s['delivery']['candidates'][0]['review_status'],'unreviewed')
        self.assertFalse(s['delivery']['user_acceptance'])

    def test_explicit_review_remains_in_shared_compiler(self):
        # Explicit semantic review remains a node; optional ordinary output
        # composition does not erase it or add a second runtime.
        self.owner.grant['execution_policy']['review']='independent'
        r=self.owner.call('node_run',dict(tasks=[dict(id='draft',objective='Write',outputs=[dict(name='text',media_type='text/plain',purpose='Report')])]))
        self.assertNotIn('error',r)
        self.assertGreater(len(self.f.rt.status('job')['tasks']),2)

class BrowserScratch(unittest.TestCase):
    def run_browser(self,*,close_error=False,body_error=False,ephemeral=True):
        from task_relay import general_browser as browser
        from tests.test_general_browser import policy
        module=types.ModuleType('playwright.sync_api');module.Error=type('Error',(Exception,),{})
        runtime=MagicMock();module.sync_playwright=lambda:runtime
        context=MagicMock();runtime.__enter__.return_value.chromium.launch_persistent_context.return_value=context
        captured=[]
        def launch(path,**kw):
            captured.append(Path(path));Path(path).mkdir(parents=True,exist_ok=True);(Path(path)/'cache').write_text('temporary');return context
        runtime.__enter__.return_value.chromium.launch_persistent_context.side_effect=launch
        if close_error:context.close.side_effect=module.Error('unknown close')
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,{'playwright.sync_api':module}),patch.object(browser,'PlaywrightDriver'):
            evidence=Path(root)/'source.txt';evidence.write_text('durable evidence')
            try:
                with browser.browser(root,policy(profile='public-source'),ephemeral=ephemeral):
                    if body_error:raise RuntimeError('read failed')
            except (ValueError,RuntimeError):
                if not (close_error or body_error):raise
            self.assertEqual(evidence.read_text(),'durable evidence');self.assertEqual(len(captured),1)
            exists=captured[0].exists()
            if ephemeral and close_error:
                # Test-owned orphan only; production never deletes unknown state.
                shutil.rmtree(captured[0].parents[2])
            return exists,context.close.call_count

    def test_confirmed_close_discards_only_temporary_profile(self):
        self.assertEqual(self.run_browser(),(False,1))
        self.assertEqual(self.run_browser(body_error=True),(False,1))

    def test_unknown_close_retains_scratch_and_historical_profiles_remain(self):
        self.assertEqual(self.run_browser(close_error=True),(True,1))
        self.assertEqual(self.run_browser(ephemeral=False),(True,1))

    def test_ephemeral_cannot_adopt_authenticated_settings(self):
        from task_relay import general_browser as browser
        from tests.test_general_browser import policy
        with self.assertRaisesRegex(ValueError,'isolated public'):
            with browser.browser('/unused',policy(profile='managed',session_source='settings'),ephemeral=True):pass
