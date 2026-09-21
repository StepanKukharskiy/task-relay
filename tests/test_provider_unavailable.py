"""Received 503 failures differ from lost submissions; no live provider calls."""
import copy
import json
import unittest
from unittest.mock import patch
from orchestrator import executors
from orchestrator.adapters import GeminiFactory
from orchestrator.workers import CodexFactory,atomic
from orchestrator.gemini_worker import execute
from task_relay import gemini, pipelines, production_control, production_stages
from tests import test_gemini_executor as fixture


class Flaky:
    def __init__(self,frozen,failures=1,error=None):
        self.inner=fixture.Scripted(frozen);self.calls=0;self.failures=failures
        self.error=error or gemini.ProviderError(503,uncertain=True)
    def request(self,*args,**kwargs):
        self.calls+=1
        if self.calls<=self.failures:raise self.error
        return self.inner.request(*args,**kwargs)


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown

    def run_client(self,client):
        with patch('orchestrator.gemini_worker.time.sleep') as sleep:
            result=execute(self.frozen,self.control,client,lambda:(fixture.CONFIG,fixture.BACKEND))
        return result,sleep

    def request(self):
        return {'provider':'gemini','model':'fixture-model','endpoint':'models/fixture-model:generateContent',
                'payload':{'tools':[{'functionDeclarations':[{'name':'file_write'}]}]}}

    def inspect(self,exit_code=1):
        with patch.object(CodexFactory,'inspect',return_value={'status':'finished','exit_code':exit_code,'reason':None}):
            return GeminiFactory().inspect({'control':str(self.control),'backend':fixture.BACKEND})

    def test_one_received_503_continues_without_repeating_a_tool(self):
        client=Flaky(self.frozen);result,sleep=self.run_client(client)
        self.assertEqual(result['decision'],'delivered');self.assertEqual(client.calls,3)
        sleep.assert_called_once_with(2)
        self.assertEqual(len(list(self.control.glob('tool-*.json'))),2)
        self.assertEqual(json.loads((self.control/'api-01.outcome.json').read_text())['http_status'],503)
        self.assertEqual(self.inspect(0)['external_outcome'],'no_pending_response')
        self.assertFalse(self.inspect(0).get('reason'))

    def test_repeated_503_stops_with_actual_reason_and_no_unbounded_retry(self):
        client=Flaky(self.frozen,failures=5)
        with self.assertRaises(gemini.ProviderError):self.run_client(client)
        self.assertEqual(client.calls,2)
        receipt=self.inspect();self.assertEqual(receipt['status'],'finished')
        self.assertIn('HTTP 503',receipt['reason']);self.assertEqual(receipt['pending_requests'],[])
        self.assertEqual(production_stages.code_preparation_failure({'receipt':json.dumps(receipt)}),'provider_unavailable')

    def test_no_retry_after_missing_response_or_exhausted_request_budget(self):
        client=Flaky(self.frozen,error=gemini.ProviderError('connection-or-response',uncertain=True))
        with self.assertRaises(gemini.ProviderError):self.run_client(client)
        self.assertEqual(client.calls,1);self.assertEqual(self.inspect()['status'],'uncertain')
        self.assertIn('api-01',self.inspect()['pending_requests'])

    def test_last_request_prevents_retry(self):
        with patch.object(executors,'request_limit',return_value=1):
            client=Flaky(self.frozen)
            with self.assertRaises(gemini.ProviderError):self.run_client(client)
        self.assertEqual(client.calls,1)
        self.assertFalse(json.loads((self.control/'api-01.recovery.json').read_text())['continued'])

    def test_pending_code_prevents_retry(self):
        folder=self.control/'code-pending';folder.mkdir();atomic(folder/'intent.json',{'id':'pending'})
        client=Flaky(self.frozen)
        with self.assertRaises(gemini.ProviderError):self.run_client(client)
        self.assertEqual(client.calls,1);self.assertEqual(self.inspect()['status'],'uncertain')

    def test_legacy_receipt_reconciles_without_rewriting_evidence(self):
        atomic(self.control/'api-01.request.json',self.request())
        atomic(self.control/'api-01.outcome.json',{'outcome':'uncertain','status':'Gemini request failed (503)'})
        before={p.name:p.read_bytes() for p in self.control.iterdir()}
        receipt=self.inspect();self.assertEqual(receipt['status'],'finished');self.assertIn('HTTP 503',receipt['reason'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.control.iterdir()})
        folder=self.control/'code-pending';folder.mkdir();atomic(folder/'intent.json',{'id':'pending'})
        receipt=self.inspect();self.assertEqual(receipt['status'],'uncertain');self.assertIn('code-pending',receipt['pending_requests'])

    def test_browser_media_and_remote_tools_are_not_reclassified(self):
        outcome={'outcome':'uncertain','status':'Gemini request failed (503)'}
        self.assertFalse(executors.synchronous_unavailable({'type':'gemini-browser','model':'fixture-model'},self.request(),outcome))
        request=self.request();request['endpoint']='models/fixture-model:predictLongRunning'
        self.assertFalse(executors.synchronous_unavailable(fixture.BACKEND,request,outcome))
        request=self.request();request['payload']['tools'].append({'googleSearch':{}})
        self.assertFalse(executors.synchronous_unavailable(fixture.BACKEND,request,outcome))
        self.assertFalse(executors.synchronous_unavailable(fixture.BACKEND,self.request(),{'outcome':'uncertain','status':'Gemini request failed (connection-or-response)'}))

    def test_non_gemini_function_only_http_failures_use_same_rule(self):
        for provider,endpoint,payload in [('openai','responses',{'store':False,'tools':[{'type':'function'}]}),('qwen','chat/completions',{'stream':False,'tools':[{'type':'function'}]})]:
            self.assertTrue(executors.synchronous_unavailable({'type':provider+'-code'},dict(provider=provider,endpoint=endpoint,payload=payload),{'http_status':503,'outcome':'uncertain'}))

    def test_pause_message_identifies_task_and_reason_without_changing_machine_code(self):
        state=object();step={'target_kind':'production_run','target':'fixture'}
        error='Production uncertain; no attempts reset.'
        with patch.object(production_control,'inspect',return_value=[{'name':'fixture','tasks':[{'id':'prepare_slides','status':'uncertain','error':'ProviderError: Gemini request failed (503)'}]}]):
            text=pipelines.production_pause_text(state,step,error)
        self.assertIn(error,text);self.assertIn('prepare_slides',text);self.assertIn('HTTP 503',text)
