"""Frozen scripting transport, truthful receipts and existing worker recovery."""
import copy,json,unittest
from unittest.mock import patch
from task_relay import computer_contract as native,computer_sessions as journal,computer_target
from orchestrator.computer_contract import resolve
from tests.test_computer_worker import Tests as WorkerFixture
from tests.test_computer_launch import LaunchHelper,runtime


def managed():
    selected={**runtime(),'mode':'new-scripting-window'}
    selected['selection']=native.digest({k:v for k,v in selected.items() if k!='selection'})
    return resolve({'selection':selected['selection'],'url':'https://example.com/one',
                    'allowed_urls':['https://example.com/one','https://example.com/two'],'max_seconds':120},selected)


class ScriptingHelper(LaunchHelper):
    def require_ready(self):raise AssertionError('Visual permission gate must not run for scripting')
    def require_scripting_ready(self):self.ready_checked=True
    def call(self,request):
        result=super().call(request)
        result.update(transport='safari-scripting',foreground_acquired=False)
        return result


class Tests(unittest.TestCase):
    setUp=WorkerFixture.setUp
    tearDown=WorkerFixture.tearDown
    prepare=WorkerFixture.prepare
    execute=WorkerFixture.execute

    def setup_scripting(self):
        db=self.prepare();self.frozen['computer']=managed();return db

    def test_background_worker_records_no_foreground_and_completes(self):
        db=self.setup_scripting();helper=ScriptingHelper(db)
        self.assertEqual(self.execute(db,helper)['decision'],'delivered')
        self.assertTrue(helper.ready_checked)
        a=db.execute('SELECT * FROM relay_computer_actions ORDER BY ordinal').fetchone()
        self.assertEqual(json.loads(a['request'])['observation_request']['target'],native.SCRIPTING_WINDOW)
        receipt=json.loads(a['receipt']);evidence=json.loads((__import__('pathlib').Path(receipt['folder'])/'evidence.json').read_text())
        self.assertFalse(evidence['foreground_acquired']);self.assertEqual(evidence['transport'],'safari-scripting')
        self.assertIn('built-in scripting',self.model.calls[0]['systemInstruction']['parts'][0]['text'])
        with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        self.assertEqual(len(helper.calls),3)

    def test_permission_denial_stops_before_window_and_provider(self):
        db=self.setup_scripting();helper=ScriptingHelper(db)
        with patch.object(helper,'require_scripting_ready',side_effect=ValueError('Automation required')):
            with self.assertRaisesRegex(ValueError,'Automation'):self.execute(db,helper)
        self.assertEqual(helper.calls,[]);self.assertEqual(self.model.calls,[])
        self.assertEqual(db.execute('SELECT count(*) FROM relay_computer_assignments').fetchone()[0],0)

    def test_mismatched_launch_transport_cannot_create_evidence(self):
        db=self.setup_scripting()
        helper=ScriptingHelper(db);real=helper.call
        def wrong(request):
            result=real(request);result.pop('transport');return result
        with patch.object(helper,'call',side_effect=wrong):
            with self.assertRaisesRegex(ValueError,'uncertain'):self.execute(db,helper)
        self.assertEqual(len(helper.calls),1);self.assertEqual(self.model.calls,[])
        self.assertEqual(db.execute('SELECT state FROM relay_computer_actions').fetchone()[0],'uncertain')

    def test_takeover_still_prevents_background_navigation(self):
        db=self.setup_scripting();helper=ScriptingHelper(db)
        with self.assertRaisesRegex(ValueError,'stopped'):self.execute(db,helper,'takeover')
        self.assertEqual(len(helper.calls),1)
        self.assertEqual(db.execute('SELECT state FROM relay_computer_assignments').fetchone()[0],'cancelled')

    def test_mode_cannot_switch_after_planning_and_no_screenshot_grant(self):
        value=managed()
        with patch.object(computer_target,'runtime',return_value=runtime()):
            with self.assertRaisesRegex(ValueError,'changed'):computer_target.verify_policy(value)
        spec=copy.deepcopy(value['spec']);spec['capture']=True
        with self.assertRaises(ValueError):native.session_spec(spec)

    def test_disabled_scroll_is_absent_and_rejected_before_native_claim(self):
        from task_relay.computer_worker_session import Session
        from orchestrator.computer_contract import definitions
        db=self.setup_scripting();helper=ScriptingHelper(db);real=helper.call
        def disabled(request):
            result=real(request);result['scroll_available']=False;return result
        helper.call=disabled
        ident=journal.approve(db,job='job',request_key='no-js',exact_request='Read synthetic text',spec=self.frozen['computer']['spec'],helper=helper.identity,output_root=self.root/'evidence',actor='fixture')
        session=Session(db,ident,helper,self.control,'Fixture')
        initial=session.call('initial','computer_observe',{'token':''})
        self.assertFalse(initial['scroll_available'])
        self.assertEqual([d['name'] for d in definitions(scroll=False)],['computer_observe','computer_navigate'])
        with self.assertRaisesRegex(ValueError,'no scroll was attempted'):
            session.call('scroll','computer_scroll',{'token':session.token,'direction':'down'})
        self.assertEqual(len(helper.calls),1)
        self.assertEqual(len(journal.actions(db,ident)),1)
        session.close()

    def test_native_failure_code_survives_without_replaying_launch(self):
        db=self.setup_scripting();helper=ScriptingHelper(db)
        with patch.object(helper,'call',return_value={'ok':False,'protocol':native.PROTOCOL,'error':'safari_scripting_document_not_stable'}):
            with self.assertRaisesRegex(ValueError,'safari_scripting_document_not_stable'):self.execute(db,helper)
        row=db.execute('SELECT * FROM relay_computer_actions').fetchone()
        self.assertEqual(row['state'],'uncertain')
        self.assertIn('safari_scripting_document_not_stable',row['error'])
        self.assertEqual(self.model.calls,[])
        with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)

    def test_timeout_phase_survives_without_provider_or_native_replay(self):
        self.assert_native_failure_not_replayed('safari_apple_event_timeout_no_replay_document_read')

    def test_creation_timeout_cannot_reopen_or_reach_provider(self):
        self.assert_native_failure_not_replayed('safari_apple_event_timeout_no_replay_window_create')

    def test_ambiguous_new_window_cannot_be_guessed_or_replayed(self):
        self.assert_native_failure_not_replayed('safari_window_identity_ambiguous')

    def test_bound_process_change_stops_without_native_or_provider_replay(self):
        self.assert_native_failure_not_replayed('safari_process_changed')

    def test_acknowledged_navigation_without_destination_cannot_be_replayed(self):
        self.assert_native_failure_not_replayed('safari_navigation_destination_not_reached_no_replay')

    def test_navigation_to_third_url_cannot_expand_grant_or_replay(self):
        self.assert_native_failure_not_replayed('safari_navigation_redirect_or_takeover')

    def assert_native_failure_not_replayed(self,code):
        from task_relay.host_computer import NativeSessionError
        db=self.setup_scripting();helper=ScriptingHelper(db)
        with patch.object(helper,'call',side_effect=NativeSessionError(code)) as native_call:
            with self.assertRaisesRegex(ValueError,code):self.execute(db,helper)
            with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        self.assertEqual(native_call.call_count,1)
        self.assertEqual(self.model.calls,[])
        row=db.execute('SELECT * FROM relay_computer_actions').fetchone()
        self.assertEqual(row['state'],'uncertain');self.assertEqual(row['resolved'],0)
        self.assertIn(code,row['error'])

    def test_pipe_failure_reaches_worker_and_supervisor_without_replay(self):
        import subprocess,sys
        from task_relay.host_computer import NativeSession
        from orchestrator.adapters import GeminiFactory
        from orchestrator.workers import atomic
        db=self.setup_scripting();helper=ScriptingHelper(db)
        script=('import sys,json; x=json.loads(sys.stdin.readline()); '
                'print(json.dumps({"protocol":x["protocol"],"ok":False,'
                '"error":"safari_scripting_document_not_stable"}),flush=True)')
        child=subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            with patch.object(helper,'call',side_effect=NativeSession(child).call) as call:
                with self.assertRaisesRegex(ValueError,'safari_scripting_document_not_stable'):self.execute(db,helper)
                self.assertEqual(call.call_count,1)
            self.assertEqual(self.model.calls,[])
            row=db.execute('SELECT * FROM relay_computer_actions').fetchone()
            self.assertEqual(row['state'],'uncertain');self.assertEqual(row['resolved'],0)
            self.assertIn('native_dispatch',row['error'])
            atomic(self.control/'done.json',{'exit_code':1,'token':self.frozen['assignment_id']})
            session={'control':str(self.control),'id':self.frozen['assignment_id'],'backend':self.frozen['backend']}
            result=GeminiFactory().inspect(session)
            self.assertEqual(result['status'],'uncertain')
            self.assertIn('Safari launch: safari_scripting_document_not_stable',result['reason'])
            with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        finally:
            if child.poll() is None:child.kill()
            child.wait(timeout=5);child.stdin.close();child.stdout.close()

    def test_untrusted_native_error_text_is_not_saved(self):
        from task_relay.host_computer import NativeSessionError
        db=self.setup_scripting();helper=ScriptingHelper(db)
        with patch.object(helper,'call',side_effect=NativeSessionError('Private page text https://example.com/?token=secret')):
            with self.assertRaisesRegex(ValueError,'invalid_native_error'):self.execute(db,helper)
        self.assertNotIn('secret',json.dumps(json.loads((self.control/'computer-result.json').read_text())))
        self.assertNotIn('secret',db.execute('SELECT error FROM relay_computer_actions').fetchone()[0])
