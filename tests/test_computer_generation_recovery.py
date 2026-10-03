"""Only received local-write failures recover; no native tools are replayed."""
import json,unittest
from contextlib import nullcontext
from unittest.mock import Mock
from orchestrator.computer_worker import run
from tests import test_computer_worker as fixture
from tests.test_computer_sessions import SessionHelper
from tests.test_gemini_executor import CONFIG,report


def response(name,args,reason='STOP',extra=None):
    parts=[{'functionCall':{'name':name,'args':args}}]
    if extra:parts.append({'functionCall':extra})
    return {'candidates':[{'finishReason':reason,'content':{'role':'model','parts':parts}}]}


class Helper(SessionHelper):
    def call(self,request):
        result=super().call(request)
        result['action_executed']=request['operation'] in ('navigate','scroll')
        return result


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    prepare=fixture.Tests.prepare

    def execute(self,replies,helper_class=Helper):
        db=self.prepare();helper=helper_class(db);self.helper=helper;self.client=Mock()
        self.client.request.side_effect=replies
        return run(self.frozen,self.control,db,client=self.client,config_reader=lambda:(CONFIG,self.frozen['backend']),helper=helper,lease_context=nullcontext())

    def scroll(self):return response('computer_scroll',{'token':'token-1','direction':'down'})
    def limited(self,reason='MAX_TOKENS',extra=None):return response('file_write',{'path':'output.txt','text':'MUST_NOT_EXECUTE'},reason,extra)
    def finish(self):return response('finish',{'report_json':json.dumps(report(self.frozen))})

    def test_known_write_limit_recovers_in_sections_without_native_replay(self):
        # report fixture identity is stable before prepare changes its executor.
        result=self.execute([self.scroll(),self.limited(),
            response('file_write',{'path':'output.txt','text':'First section.\n'}),
            response('file_append',{'path':'output.txt','text':'Second section.','expected_bytes':15}),self.finish()])
        self.assertEqual(result['decision'],'delivered')
        self.assertEqual((self.ws/'output.txt').read_text(),'First section.\nSecond section.')
        self.assertEqual([r['operation'] for r in self.helper.calls],['bind','scroll'])
        self.assertFalse((self.control/'tool-02-00.json').exists())
        recovery=json.loads((self.control/'api-02.recovery.json').read_text())
        self.assertTrue(recovery['continued']);self.assertTrue(recovery['computer_file_only']);self.assertEqual(recovery['executed_calls'],0)
        for call in self.client.request.call_args_list[2:]:
            payload=call.args[1];names={t['name'] for t in payload['tools'][0]['functionDeclarations']}
            self.assertNotIn('computer_scroll',names);self.assertNotIn('computer_navigate',names)
            self.assertNotIn('MUST_NOT_EXECUTE',json.dumps(payload))
            self.assertEqual(payload['generationConfig']['maxOutputTokens'],4096)

    def test_repeat_limit_exhausts_recovery_without_additional_tools(self):
        with self.assertRaisesRegex(ValueError,'exhausted'):self.execute([self.scroll(),self.limited(),self.limited()])
        self.assertEqual(self.client.request.call_count,3);self.assertEqual(len(self.helper.calls),2)
        self.assertFalse((self.ws/'output.txt').exists())
        self.assertFalse(json.loads((self.control/'api-03.recovery.json').read_text())['continued'])

    def test_mixed_native_partial_candidate_does_not_recover_or_execute_any_call(self):
        extra={'name':'computer_scroll','args':{'token':'token-2','direction':'down'}}
        with self.assertRaisesRegex(ValueError,'unavailable'):self.execute([self.scroll(),self.limited(extra=extra)])
        self.assertEqual(len(self.helper.calls),2);self.assertFalse((self.ws/'output.txt').exists())
        self.assertEqual(self.client.request.call_count,2)

    def test_no_action_refresh_must_be_resolved_before_writing_recovery(self):
        with self.assertRaisesRegex(ValueError,'unavailable'):self.execute([self.scroll(),self.limited()],fixture.DynamicHelper)
        self.assertEqual(len(self.helper.calls),2)
        self.assertTrue(json.loads((self.control/'computer-result.json').read_text())['unexecuted_actions'])

    def test_final_request_limit_does_not_expand_budget(self):
        self.frozen['limits']['provider_requests']=2
        with self.assertRaisesRegex(ValueError,'exhausted'):self.execute([self.scroll(),self.limited()])
        self.assertEqual(self.client.request.call_count,2)
        self.assertFalse(json.loads((self.control/'api-02.recovery.json').read_text())['continued'])

    def test_transport_uncertainty_is_never_a_generation_recovery(self):
        from task_relay.gemini import ProviderError
        with self.assertRaises(ProviderError):self.execute([self.scroll(),ProviderError('lost reply',uncertain=True)])
        self.assertEqual(self.client.request.call_count,2)
        self.assertFalse(list(self.control.glob('*.recovery.json')))

    def test_model_cannot_use_native_tools_after_writing_recovery(self):
        self.execute([self.scroll(),self.limited(),response('computer_scroll',{'token':'token-2','direction':'down'}),
                      response('file_write',{'path':'output.txt','text':'Saved observed evidence.'}),self.finish()])
        self.assertEqual(len(self.helper.calls),2)
        self.assertIn('unavailable',json.loads((self.control/'tool-03-00.json').read_text())['result']['error'])

    def test_append_remains_available_at_final_work_request(self):
        self.frozen['limits']['provider_requests']=5
        self.execute([self.scroll(),self.limited(),response('file_write',{'path':'output.txt','text':'First section.\n'}),
                      response('file_append',{'path':'output.txt','text':'Second section.','expected_bytes':15}),self.finish()])
        payload=self.client.request.call_args_list[3].args[1]
        self.assertIn('file_append',[t['name'] for t in payload['tools'][0]['functionDeclarations']])

    def test_pause_during_recovery_prevents_another_provider_request(self):
        count=0
        def provider(*args,**kwargs):
            nonlocal count
            count+=1
            if count==1:return self.scroll()
            (self.control/'computer-owner-event.json').write_text(json.dumps({'kind':'pause'}))
            return self.limited()
        with self.assertRaisesRegex(ValueError,'stopped'):self.execute(provider)
        self.assertEqual(self.client.request.call_count,2)
        self.assertEqual(len(self.helper.calls),2)
        self.assertEqual(json.loads((self.control/'computer-result.json').read_text())['state'],'paused')

    def test_malformed_local_write_uses_same_file_only_boundary(self):
        result=self.execute([self.scroll(),self.limited('MALFORMED_FUNCTION_CALL'),
                             response('file_write',{'path':'output.txt','text':'Actual observed evidence.'}),self.finish()])
        self.assertEqual(result['decision'],'delivered')
        self.assertTrue(json.loads((self.control/'api-02.recovery.json').read_text())['computer_file_only'])
        self.assertEqual(len(self.helper.calls),2)
