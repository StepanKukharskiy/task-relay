"""Received incomplete generations are not executable. No live provider calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import executors
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from task_relay import code_runtime, gemini, native_code_host
from task_relay.production_stages import code_preparation_failure
from tests import test_shared_code_workers as shared
from tests.test_gemini_executor import report


def limited(provider,response):
    if provider=='gemini':response['candidates'][0]['finishReason']='MAX_TOKENS'
    elif provider=='openai':response.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
    else:response['choices'][0]['finish_reason']='length'
    return response


class Tests(unittest.TestCase):
    setUp=shared.Tests.setUp
    backend=shared.Tests.backend
    host_result=shared.Tests.host_result

    def setup_worker(self,provider='gemini',code=True,control=None):
        control=control or self.control
        backend=self.backend(provider,code);self.frozen['backend']=backend
        self.frozen['tools']=['files','python'] if code else ['files']
        config={'api_key':'fixture-only'}
        atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
        return lambda:(config,backend)

    def test_all_providers_discard_incomplete_calls_then_finish_within_allowance(self):
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as temp:
                control=Path(temp);reader=self.setup_worker(provider,control=control)
                transport=shared.Transport(provider,self.frozen,True)
                responses=[]
                def request(*args,**kwargs):
                    response=transport.request(*args,**kwargs)
                    # First response contains a valid-looking Python call which
                    # must never run. Next response writes the actual deliverable.
                    if len(responses)==0:limited(provider,response)
                    elif len(responses)==1:
                        actual=shared.Transport(provider,self.frozen,True)
                        response=actual.request(*args,**kwargs)
                    responses.append(response);return response
                with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result) as host:
                    client=type('Client',(),{'request':staticmethod(request)})()
                    self.assertEqual(execute(self.frozen,control,client,reader)['decision'],'delivered')
                self.assertEqual(host.call_count,1)
                self.assertEqual(len(responses),3)
                self.assertTrue(json.loads((control/'api-01.recovery.json').read_text())['continued'])
                self.assertEqual(json.loads((control/'agent-result.json').read_text())['tool_calls'],2)
                second=json.dumps(transport.requests[1][1])
                self.assertIn('NONE of its tools executed',second)
                self.assertNotIn('opaque',second)
                self.assertNotIn('retained',second)

    def test_second_generation_limit_stops_without_tools(self):
        reader=self.setup_worker();transport=shared.Transport('gemini',self.frozen,True)
        def request(*args,**kwargs):return limited('gemini',transport.request(*args,**kwargs))
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run') as host:
            with self.assertRaisesRegex(ValueError,'Bounded recovery unavailable or exhausted'):
                execute(self.frozen,self.control,type('Client',(),{'request':staticmethod(request)})(),reader)
        self.assertEqual(len(transport.requests),2);host.assert_not_called()
        self.assertFalse(json.loads((self.control/'api-02.recovery.json').read_text())['continued'])

    def test_length_then_malformed_recovers_without_executing_either_candidate(self):
        reader=self.setup_worker();seen=[];frozen=self.frozen
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                reason={1:'MAX_TOKENS',2:'MALFORMED_FUNCTION_CALL'}.get(n,'STOP')
                name,args=('file_write',{'path':'output.txt','text':'only complete response'}) if n<4 else ('finish',report(frozen))
                return {'candidates':[{'finishReason':reason,'content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT):
            self.assertEqual(execute(frozen,self.control,Client(),reader)['decision'],'delivered')
        self.assertFalse((self.control/'tool-01-00.json').exists())
        self.assertFalse((self.control/'tool-02-00.json').exists())
        self.assertEqual(json.loads((self.control/'agent-result.json').read_text())['tool_calls'],2)
        self.assertEqual(len(seen),4)

    def test_repeated_malformed_response_stops_with_specific_reason(self):
        reader=self.setup_worker();requests=[]
        def request(*args,**kwargs):
            requests.append(1);return {'candidates':[{'finishReason':'MALFORMED_FUNCTION_CALL','finishMessage':'invalid code must not be executed'}]}
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT):
            with self.assertRaisesRegex(ValueError,'MALFORMED_FUNCTION_CALL'):
                execute(self.frozen,self.control,type('Client',(),{'request':staticmethod(request)})(),reader)
        self.assertEqual(len(requests),2)

    def test_oversized_code_is_rejected_before_execution_and_logs_are_excerpted(self):
        reader=self.setup_worker();seen=[];frozen=self.frozen
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                name,args=('python_run',{'code':'x'*6001 if n==1 else 'small transform','seconds':5}) if n<3 else ('finish',report(frozen))
                return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        def host(*args):
            result=self.host_result(*args);result['log']='a'*20000+'validation complete';return result
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run',side_effect=host) as run:
            self.assertEqual(execute(frozen,self.control,Client(),reader)['decision'],'delivered')
        self.assertEqual(run.call_count,1)
        self.assertIn('no code ran',json.dumps(seen[1]))
        full=json.loads((self.control/'tool-02-00.json').read_text())['result']['log']
        self.assertGreater(len(full),20000)
        reply=seen[2]['contents'][-1]['parts'][0]['functionResponse']['response']
        self.assertGreater(reply['log_chars_omitted'],10000)
        self.assertLess(len(reply['log']),6100)
        self.assertIn('validation complete',reply['log'])

    def test_final_request_limit_cannot_gain_extra_request(self):
        self.frozen['limits']['provider_requests']=1
        reader=self.setup_worker();transport=shared.Transport('gemini',self.frozen,True)
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT):
            with self.assertRaisesRegex(ValueError,'generation output limit'):
                execute(self.frozen,self.control,type('Client',(),{'request':staticmethod(lambda *a,**k:limited('gemini',transport.request(*a,**k)))})(),reader)
        self.assertEqual(len(transport.requests),1)

    def test_explicit_response_budget_reaches_each_provider_and_accepts_larger_code(self):
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as temp:
                control=Path(temp);reader=self.setup_worker(provider,control=control)
                self.frozen['limits']['response_tokens']=16384
                transport=shared.Transport(provider,self.frozen,True)
                code='# A representative data transformation\n'+'# retained local editing instructions\n'*400
                def request(*args,**kwargs):
                    result=transport.request(*args,**kwargs)
                    if len(transport.requests)==1:
                        if provider=='gemini':result['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']=code
                        elif provider=='openai':result['output'][1]['arguments']=json.dumps({'code':code,'seconds':5})
                        else:result['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps({'code':code,'seconds':5})
                    return result
                with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result) as host:
                    self.assertEqual(execute(self.frozen,control,type('Client',(),{'request':staticmethod(request)})(),reader)['decision'],'delivered')
                payload=transport.requests[0][1]
                value=payload['generationConfig']['maxOutputTokens'] if provider=='gemini' else payload['max_output_tokens'] if provider=='openai' else payload['max_tokens']
                self.assertEqual(value,16384)
                self.assertEqual(host.call_count,1);self.assertEqual(host.call_args.args[2],code)
                self.assertEqual(len(transport.requests),2)

    def test_legacy_response_budget_is_not_expanded(self):
        reader=self.setup_worker();transport=shared.Transport('gemini',self.frozen,True)
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result):
            execute(self.frozen,self.control,transport,reader)
        self.assertEqual(transport.requests[0][1]['generationConfig']['maxOutputTokens'],4096)
        self.assertNotIn('response_tokens',self.frozen['limits'])

    def test_partial_checkpoint_preserves_real_work_without_placeholder_outputs(self):
        reader=self.setup_worker();self.frozen['limits'].update(provider_requests=12,tool_calls=12)
        self.frozen['outputs'].append({'path':'summary.md','purpose':'Exact work summary'})
        seen=[];frozen=self.frozen
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                if n<5:name,args='file_list',{}
                elif n==5:name,args='python_checkpoint',{'code':'save only the meaningful first output','seconds':5}
                elif n==6:
                    assert 'python_run' in {t['name'] for t in payload['tools'][0]['functionDeclarations']}
                    name,args='file_write',{'path':'summary.md','text':'Transformation completed; original data retained.'}
                else:name,args='finish',report(frozen)
                return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result):
            self.assertEqual(execute(self.frozen,self.control,Client(),reader)['decision'],'delivered')
        saved=json.loads((self.control/'tool-05-00.json').read_text())['result']
        self.assertNotIn('error',saved)
        self.assertEqual(set(saved['outputs']),{'output.txt'})

    def test_transport_uncertainty_and_safety_stop_without_continuation(self):
        for mode in ('uncertain','safety','pending_code'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as temp:
                control=Path(temp);reader=self.setup_worker(code=mode!='not_code',control=control)
                transport=shared.Transport('gemini',self.frozen,True);requests=[]
                if mode=='pending_code':
                    folder=control/'code-pending';folder.mkdir();atomic(folder/'intent.json',{})
                def request(*args,**kwargs):
                    requests.append(1)
                    if mode=='uncertain':raise gemini.ProviderError('connection lost',uncertain=True)
                    response=limited('gemini',transport.request(*args,**kwargs))
                    if mode=='safety':response['candidates'][0]['finishReason']='SAFETY'
                    return response
                with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run') as host:
                    with self.assertRaises((ValueError,gemini.ProviderError)):
                        execute(self.frozen,control,type('Client',(),{'request':staticmethod(request)})(),reader)
                self.assertEqual(len(requests),1);host.assert_not_called()

    def test_saved_drafts_do_not_disable_later_progress_checkpoints(self):
        reader=self.setup_worker();self.frozen['limits'].update(provider_requests=16,tool_calls=16)
        seen=[];frozen=self.frozen
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                offered={t['name'] for t in payload['tools'][0]['functionDeclarations']}
                if n==1:name,args='file_write',{'path':'output.txt','text':'baseline'}
                elif n<=5:name,args='file_list',{}
                elif n==6:
                    assert 'python_run' not in offered
                    name,args='python_checkpoint',{'code':'rewrite unchanged','seconds':5}
                elif n==7:
                    assert 'python_run' not in offered
                    name,args='file_write',{'path':'output.txt','text':'corrected draft'}
                elif n==8:
                    assert 'python_run' in offered
                    name,args='file_read',{'path':'output.txt','offset':0,'limit':100}
                else:name,args='finish',report(frozen)
                return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        def unchanged(runtime,folder,*args):
            out=folder/'outputs';out.mkdir();(out/'output.txt').write_text('baseline')
            return {'returncode':0,'log':'same bytes','outputs':str(out)}
        with patch.object(code_runtime,'available',return_value=shared.RECEIPT),patch.object(native_code_host,'run',side_effect=unchanged):
            self.assertEqual(execute(self.frozen,self.control,Client(),reader)['decision'],'delivered')
        self.assertEqual((self.ws/'output.txt').read_text(),'corrected draft')
        self.assertIn('did not change',json.loads((self.control/'tool-06-00.json').read_text())['result']['error'])

    def test_legacy_incomplete_receipt_needs_explicit_saved_generation_limit(self):
        attempt={'receipt':json.dumps({'reason':'ValueError: Incomplete provider response; retained without retry.'}),
                 'session':json.dumps({'control':str(self.control),'backend':self.backend('gemini',True)})}
        self.assertIsNone(code_preparation_failure(attempt))
        atomic(self.control/'api-16.request.json',{})
        atomic(self.control/'api-16.response.json',{'candidates':[{'finishReason':'SAFETY'}]})
        self.assertIsNone(code_preparation_failure(attempt))
        atomic(self.control/'api-16.response.json',{'candidates':[{'finishReason':'MAX_TOKENS'}]})
        self.assertEqual(code_preparation_failure(attempt),'generation_limit')
