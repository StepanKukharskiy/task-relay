import copy,json,unittest
from unittest.mock import Mock,patch
from tests import test_orchestrator_files as fixtures,intake_fixtures as intake
from task_relay import orchestrator_files as files,request_contract
from orchestrator.provider_responses import generation_failure

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    args=fixtures.Tests.args
    response=fixtures.Tests.response
    late_proposal_fixture=fixtures.Tests.late_proposal_fixture

    def bad(self,provider,reply,action):
        r=reply(action)
        if provider=='gemini':r['candidates'][0]['finishReason']='MALFORMED_FUNCTION_CALL'
        elif provider=='openai':r['output'][0]['arguments']='{"unfinished":'
        else:r['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"unfinished":'
        return r

    def test_confirmed_provider_failure_reuses_context_after_last_read_for_all_providers(self):
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                action,reply,options,reads=self.late_proposal_fixture(provider);bad=self.bad(provider,reply,action)
                client=Mock();client.request.side_effect=reads+[bad,reply(action)]
                result=json.loads(files.run(provider,client,'fixture',self.request(provider),[str(self.root)],self.receipt,**options))
                self.assertEqual(result['request_contract'],options['frozen_intake'])
                journal=json.loads(self.receipt.read_text());r=journal[-2]
                self.assertEqual(r['response'],bad);self.assertEqual(r['provider_recovery']['executed_calls'],0)
                self.assertEqual(r['provider_recovery']['outcome']['code'],'malformed_function_call')
                self.assertNotIn('reads',r);self.assertEqual(client.request.call_count,8)

    def test_mixed_schema_and_generation_failures_share_one_ceiling(self):
        action,reply,options,reads=self.late_proposal_fixture('gemini')
        schema_bad=reply(dict(action,capabilities=[]));bad=self.bad('gemini',reply,action)
        client=Mock();client.request.side_effect=reads+[schema_bad,bad,bad]
        with self.assertRaises(files.ProviderResponseError):
            files.run('gemini',client,'fixture',self.request('gemini'),[str(self.root)],self.receipt,**options)
        journal=json.loads(self.receipt.read_text());self.assertEqual(len(journal),9)
        self.assertFalse(journal[-1]['provider_recovery']['continued'])
        self.assertNotIn('reads',journal[-1])

    def test_parseable_calls_in_truncated_response_never_execute(self):
        action,reply,options,_=self.late_proposal_fixture('gemini')
        bad=self.response('gemini','README.md');bad['candidates'][0]['finishReason']='MAX_TOKENS'
        client=Mock();client.request.side_effect=[bad,reply(action)]
        with patch.object(files,'execute') as execute:
            files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,**options)
            execute.assert_not_called()
        self.assertEqual(json.loads(self.receipt.read_text())[0]['provider_recovery']['outcome']['code'],'generation_output_limit')

    def test_intake_recovery_has_one_shared_attempt_and_never_uses_partial_scope(self):
        action,reply,options,_=self.late_proposal_fixture('gemini');scope=options.pop('frozen_intake')
        bad=intake.response('gemini',scope);bad['candidates'][0]['finishReason']='MALFORMED_FUNCTION_CALL'
        client=Mock();client.request.side_effect=[bad,intake.response('gemini',scope),reply(action)]
        result=json.loads(files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,intake_definition=request_contract.definition(),**options))
        self.assertEqual(result['request_contract'],scope)
        client.request.side_effect=[bad,bad];client.reset_mock()
        with self.assertRaises(files.ProviderResponseError):files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,intake_definition=request_contract.definition(),**options)
        self.assertEqual(client.request.call_count,2)

    def test_safety_ambiguous_or_unreceived_outcomes_never_gain_retry_permission(self):
        for reason in ('SAFETY','RECITATION','OTHER'):
            action,reply,options,_=self.late_proposal_fixture('gemini');bad=reply(action);bad['candidates'][0]['finishReason']=reason
            client=Mock();client.request.return_value=bad
            with self.assertRaises(files.ProviderResponseError):files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,**options)
            client.request.assert_called_once()
        for provider,key in (('gemini','candidates'),('qwen','choices')):
            for malformed in (None,{},[None],['bad']):
                self.assertIsNone(generation_failure(provider,{key:malformed}))
        self.assertIsNone(generation_failure('gemini',{'candidates':[{'finishReason':'MALFORMED_FUNCTION_CALL'}]*2}))
        self.assertIsNone(generation_failure('openai',{'status':'in_progress','output':[{'type':'function_call','call_id':'x','name':'finish','arguments':'{'}]}))
        client=Mock();client.request.side_effect=TimeoutError('Unknown remote outcome')
        with self.assertRaises(TimeoutError):files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,**options)
        client.request.assert_called_once();self.assertNotIn('response',json.loads(self.receipt.read_text())[-1])
