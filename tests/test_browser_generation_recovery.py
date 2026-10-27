"""Confirmed browser report-generation failures recover without website replay."""
import json,sqlite3,unittest
from contextlib import nullcontext,closing
from unittest.mock import Mock
from orchestrator import contracts as c
from orchestrator.browser_worker import run
from tests import test_gemini_executor as fixture
from tests.test_gemini_executor import CONFIG,report
from tests.test_general_browser import browser_graph,Driver

def response(name,args,reason='STOP',extra=None):
    parts=[{'functionCall':{'name':name,'args':args}}]
    if extra:parts.append({'functionCall':extra})
    return {'candidates':[{'finishReason':reason,'content':{'role':'model','parts':parts}}]}

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown

    def browser_frozen(self):
        f=c.assignment(browser_graph()['tasks'][0]);f.update(assignment_id='fixture',backend=browser_graph()['backend'],workspace=str(self.ws))
        f['limits']['provider_requests']=6
        return f

    def execute(self,f,replies,pending_on_limit=False):
        self.client=Mock();self.client.request.side_effect=replies;self.driver=Driver()
        with closing(sqlite3.connect(':memory:')) as db:
            if pending_on_limit:
                from task_relay.browser_journal import Journal
                saved=list(replies);count=0
                def provider(*args,**kwargs):
                    nonlocal count
                    count+=1
                    if count==2:Journal(db).claim(f['browser']['profile'],'unresolved-job','unresolved-action','browser_click',{},10,True)
                    return saved[count-1]
                self.client.request.side_effect=provider
            return run(f,self.control,db,self.root,client=self.client,config_reader=lambda:(CONFIG,f['backend']),driver_context=nullcontext(self.driver))

    def opened(self):return response('browser_open',{'url':'https://example.test/product'})
    def limited(self,reason='MAX_TOKENS',extra=None):return response('file_write',{'path':'output.txt','text':'MUST_NOT_EXECUTE'},reason,extra)
    def finish(self,f):return response('finish',{'report_json':json.dumps(report(f))})

    def test_report_recovers_in_sections_without_browser_replay(self):
        f=self.browser_frozen();f['limits']['provider_requests']=5
        result=self.execute(f,[self.opened(),self.limited(),response('file_write',{'path':'output.txt','text':'Observed price: $10.\n'}),response('file_append',{'path':'output.txt','text':'Observed size: 3 in.','expected_bytes':21}),self.finish(f)])
        self.assertEqual(result['decision'],'delivered');self.assertNotIn('MUST_NOT_EXECUTE',(self.ws/'output.txt').read_text())
        self.assertIn('Observed size',(self.ws/'output.txt').read_text())
        recovery=json.loads((self.control/'api-02.recovery.json').read_text());self.assertTrue(recovery['browser_file_only']);self.assertEqual(recovery['executed_calls'],0)
        for call in self.client.request.call_args_list[2:]:
            payload=call.args[1];names={t['name'] for t in payload['tools'][0]['functionDeclarations']}
            self.assertFalse(any(n.startswith('browser_') for n in names));self.assertNotIn('MUST_NOT_EXECUTE',json.dumps(payload))
            self.assertEqual(payload['generationConfig']['maxOutputTokens'],4096)
        self.assertIn('file_append',{t['name'] for t in self.client.request.call_args_list[3].args[1]['tools'][0]['functionDeclarations']})
        self.assertEqual(len(json.loads((self.control/'browser-result.json').read_text())['actions']),1)

    def test_mixed_browser_candidate_is_never_salvaged(self):
        f=self.browser_frozen()
        with self.assertRaisesRegex(ValueError,'unavailable'):
            self.execute(f,[self.opened(),self.limited(extra={'name':'browser_open','args':{'url':'https://example.test/other'}})])
        self.assertEqual(len(self.driver.pages),1);self.assertFalse((self.ws/'output.txt').exists())
        self.assertEqual(self.client.request.call_count,2)

    def test_repeat_failure_preserves_frozen_budget(self):
        f=self.browser_frozen()
        with self.assertRaisesRegex(ValueError,'exhausted'):self.execute(f,[self.opened(),self.limited(),self.limited()])
        self.assertEqual(self.client.request.call_count,3);self.assertFalse((self.ws/'output.txt').exists())

    def test_final_request_failure_cannot_add_requests(self):
        f=self.browser_frozen();f['limits']['provider_requests']=2
        with self.assertRaisesRegex(ValueError,'exhausted'):self.execute(f,[self.opened(),self.limited()])
        self.assertEqual(self.client.request.call_count,2)

    def test_transport_uncertainty_cannot_recover(self):
        from task_relay.gemini import ProviderError
        f=self.browser_frozen()
        with self.assertRaises(ProviderError):self.execute(f,[self.opened(),ProviderError('Lost reply',uncertain=True)])
        self.assertFalse(list(self.control.glob('*.recovery.json')));self.assertEqual(self.client.request.call_count,2)

    def test_browser_tools_remain_disabled_during_recovery(self):
        f=self.browser_frozen()
        self.execute(f,[self.opened(),self.limited(),response('browser_open',{'url':'https://example.test/other'}),response('file_write',{'path':'output.txt','text':'Confirmed product facts.'}),self.finish(f)])
        self.assertEqual(len(self.driver.pages),1)
        self.assertIn('unavailable',json.loads((self.control/'tool-03-00.json').read_text())['result']['error'])

    def test_unresolved_browser_intent_prevents_local_generation_recovery(self):
        f=self.browser_frozen()
        with self.assertRaisesRegex(ValueError,'unavailable'):
            self.execute(f,[self.opened(),self.limited()],pending_on_limit=True)
        self.assertEqual(self.client.request.call_count,2)
        self.assertFalse(json.loads((self.control/'api-02.recovery.json').read_text())['continued'])

    def test_cancel_after_received_failure_prevents_another_request(self):
        f=self.browser_frozen();count=0
        def provider(*args,**kwargs):
            nonlocal count
            count+=1
            if count==1:return self.opened()
            (self.control/'cancel.json').write_text('{}')
            return self.limited()
        with self.assertRaisesRegex(ValueError,'Cancelled'):
            self.execute(f,provider)
        self.assertEqual(self.client.request.call_count,2);self.assertFalse((self.ws/'output.txt').exists())
