"""Bounded text executor: scripted transport and real supervisor processes, no API calls."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from task_relay import gemini
from orchestrator import contracts as c, executors
from orchestrator.adapters import ExecutionFactory, GeminiFactory
from orchestrator.gemini_worker import Files, execute
from orchestrator.runtime import Runtime
from orchestrator.workers import atomic
from tests.test_orchestrator import pair

BACKEND={'type':'gemini-agent','model':'fixture-model'}
CONFIG={'api_key':'fixture-only','models':{'text':'fixture-model'}}

def graph():
    p=pair(gate='Select the output',max_attempts=1);p['backend']=BACKEND.copy()
    for t in p['tasks']:t.update(tools=['files'],limits=executors.GEMINI_LIMITS.copy())
    return p


def report(frozen):
    return dict(assignment_id=frozen['assignment_id'],summary='Inspected declared files',
                decision='accept' if frozen.get('review_of') else 'delivered',instruction='',
                checks=[dict(criterion=i,passed=True,evidence='Exact declared text matches') for i in range(1,len(frozen['criteria'])+1)])


class Scripted:
    def __init__(self,frozen,mode='normal'):
        self.frozen=frozen;self.mode=mode;self.calls=[]
    def request(self,path,payload,**kwargs):
        self.calls.append(copy.deepcopy(payload));n=len(self.calls)
        if self.mode=='uncertain':raise gemini.ProviderError('Disconnected',uncertain=True)
        if self.mode=='wait' and n==2:time.sleep(30)
        if self.mode=='finish-only':name,args='finish',report(self.frozen)
        elif self.mode=='loop':name,args='file_list',{}
        elif n==1 and self.frozen['inputs']:
            name,args='file_read',dict(path=self.frozen['inputs'][0]['path'],offset=0,limit=24000)
        elif n==(2 if self.frozen['inputs'] else 1):
            name,args='file_write',dict(path=self.frozen['outputs'][0]['path'],text='bounded fixture output')
        else:name,args='finish',report(self.frozen)
        if name=='finish':args={'report_json':json.dumps(args)}
        return {'responseId':'fixture-'+str(n),'usageMetadata':{'promptTokenCount':3,'candidatesTokenCount':2},
                'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[
                    {'thoughtSignature':'opaque-signature','functionCall':{'id':'call-'+str(n),'name':name,'args':args}}]}}]}


class SupervisorFixture(GeminiFactory):
    def __init__(self,mode='normal'):super().__init__();self.mode=mode
    def create(self,control,workspace,frozen,backend):
        session=super().create(control,workspace,frozen,backend)
        path=Path(control)/'launch.json';launch=json.loads(path.read_text())
        launch['registered_command']=[sys.executable,str(Path(__file__).resolve()),'fixture',str(control),str(workspace),self.mode]
        atomic(path,launch);return session


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.ws=self.root/'workspace';self.ws.mkdir();(self.ws/'.relay').mkdir()
        self.control=self.root/'control';self.control.mkdir()
        self.frozen=c.assignment(graph()['tasks'][0]);self.frozen.update(assignment_id='fixture',backend=BACKEND,workspace=str(self.ws))
        atomic(self.control/'launch.json',{'credential_fingerprint':executors.fingerprint(CONFIG,BACKEND)})
    def tearDown(self):self.temp.cleanup()
    def run_script(self,mode='normal',reader=None):
        client=Scripted(self.frozen,mode)
        result=execute(self.frozen,self.control,client,reader or (lambda:(CONFIG,BACKEND)))
        return result,client

    def input(self,path,text,**metadata):
        target=self.ws/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
        self.frozen['inputs'].append(dict(path=path,sha256=hashlib.sha256(text.encode()).hexdigest(),**metadata))

    def test_loop_preserves_signatures_ids_usage_and_report(self):
        result,client=self.run_script()
        history=client.calls[1]['contents']
        self.assertEqual(history[1]['parts'][0]['thoughtSignature'],'opaque-signature')
        self.assertEqual(history[2]['parts'][0]['functionResponse']['id'],'call-1')
        self.assertEqual(result['decision'],'delivered')
        self.assertEqual((self.ws/'output.txt').read_text(),'bounded fixture output')
        self.assertEqual(len(list(self.control.glob('api-*.response.json'))),2)

    def test_review_finish_saves_exact_judgment_without_duplicate_write_call(self):
        self.frozen['review_of']='producer';self.frozen['outputs']=[{'path':'findings.md','purpose':'Independent findings'}]
        self.input('candidate.txt','The exact candidate to review.',from_task='producer')
        result,client=self.run_script('finish-only')
        self.assertEqual(result['decision'],'accept');self.assertEqual(len(client.calls),1)
        text=(self.ws/'findings.md').read_text()
        self.assertIn(result['summary'],text)
        self.assertTrue(all(check['evidence'] in text for check in result['checks']))
        supplied=json.loads(client.calls[0]['contents'][0]['parts'][0]['text'])['source_pack']
        self.assertEqual(supplied['files'][0]['text'],'The exact candidate to review.')

    def test_placeholder_is_retained_but_cannot_be_delivered(self):
        scripted=Scripted(self.frozen)
        class Stub:
            def request(_,path,payload,**kwargs):
                response=scripted.request(path,payload,**kwargs)
                call=response['candidates'][0]['content']['parts'][0]['functionCall']
                if call['name']=='file_write':call['args']['text']='# Placeholder'
                return response
        with self.assertRaisesRegex(ValueError,'request budget'):
            execute(self.frozen,self.control,Stub(),lambda:(CONFIG,BACKEND))
        self.assertEqual((self.ws/'output.txt').read_text(),'# Placeholder')
        self.assertFalse((self.ws/'.relay/result.json').exists())
        self.assertIn('placeholder-only',json.loads((self.control/'tool-02-00.json').read_text())['result']['error'])

    def test_partial_candidate_cannot_be_approved_until_all_pages_are_supplied(self):
        self.frozen['review_of']='producer'
        self.input('guide.txt','guide'*100)
        self.input('candidate.txt','A'*96001,from_task='producer')
        files=Files(self.frozen);pack=files.source_pack()
        self.assertEqual(pack['files'][0]['path'],'candidate.txt')
        self.assertEqual(pack['files'][0]['next_offset'],96000)
        with self.assertRaisesRegex(ValueError,'complete exact candidate'):files.validate_text_delivery(report(self.frozen))
        files.call('file_read',dict(path='candidate.txt',offset=96000,limit=1))
        files.validate_text_delivery(report(self.frozen))
        (self.ws/'candidate.txt').write_text('B'*96001)
        with self.assertRaisesRegex(ValueError,'changed'):files.validate_text_delivery(report(self.frozen))

    def test_candidate_read_gaps_and_absent_candidate_do_not_count_as_review(self):
        self.frozen['review_of']='producer';files=Files(self.frozen)
        with self.assertRaisesRegex(ValueError,'No declared candidate'):files.validate_text_delivery(report(self.frozen))
        self.input('candidate.txt','123456789',from_task='producer');files=Files(self.frozen)
        for offset in (0,6):files.call('file_read',dict(path='candidate.txt',offset=offset,limit=3))
        with self.assertRaisesRegex(ValueError,'complete exact candidate'):files.validate_text_delivery(report(self.frozen))
        files.call('file_read',dict(path='candidate.txt',offset=3,limit=3));files.validate_text_delivery(report(self.frozen))

    def test_source_pack_keeps_unicode_and_explicit_omissions_within_bound(self):
        self.input('source.txt','я'*10);self.input('omitted.txt','later')
        pack=Files(self.frozen).source_pack(max_bytes=5)
        self.assertEqual(pack['text_bytes'],5)
        self.assertEqual(pack['files'][0]['text'],'яя');self.assertEqual(pack['files'][0]['next_offset'],2)
        self.assertEqual(pack['files'][1]['text'],'l');self.assertEqual(pack['files'][1]['next_offset'],1)

    def test_placeholder_candidate_requires_correction_even_when_supplied(self):
        self.frozen['review_of']='producer';self.input('candidate.txt','# Placeholder',from_task='producer')
        files=Files(self.frozen);files.source_pack();value=report(self.frozen)
        with self.assertRaisesRegex(ValueError,'placeholder-only candidate'):files.validate_text_delivery(value)
        value['decision']='revise';files.validate_text_delivery(value)
        files.call('file_write',dict(path='output.txt',text='# Review in progress'))
        with self.assertRaisesRegex(ValueError,'placeholder-only output'):files.validate_text_delivery(value)
        value['decision']='blocked';files.validate_text_delivery(value)

    def test_append_preserves_sections_and_rejects_replay_unknown_paths_and_overflow(self):
        files=Files(self.frozen)
        args=dict(path='output.txt',text='next',expected_bytes=0)
        with self.assertRaisesRegex(ValueError,'already written'):files.call('file_append',args)
        first=files.call('file_write',dict(path='output.txt',text='я\n'))
        args.update(expected_bytes=first['bytes'])
        result=files.call('file_append',args)
        self.assertEqual((self.ws/'output.txt').read_text(),'я\nnext');self.assertEqual(result['bytes'],7)
        with self.assertRaisesRegex(ValueError,'size changed'):files.call('file_append',args)
        self.frozen['limits']['output_bytes']=8;args.update(expected_bytes=7)
        with self.assertRaisesRegex(ValueError,'budget'):files.call('file_append',args)
        self.assertEqual((self.ws/'output.txt').read_text(),'я\nnext')
        args.update(path='../outside')
        with self.assertRaises(ValueError):files.call('file_append',args)

    def test_text_generation_failure_discards_all_calls_and_resumes_saved_sections(self):
        from unittest.mock import Mock
        def response(name,args,reason='STOP'):
            return {'candidates':[{'finishReason':reason,'content':{'role':'model','parts':[
                {'functionCall':{'name':name,'args':args}}]}}]}
        client=Mock();client.request.side_effect=[
            response('file_write',dict(path='output.txt',text='First section.\n')),
            response('file_write',dict(path='output.txt',text='MUST NOT EXECUTE'),'MALFORMED_FUNCTION_CALL'),
            response('file_append',dict(path='output.txt',text='Second section.',expected_bytes=15)),
            response('finish',{'report_json':json.dumps(report(self.frozen))})]
        result=execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered')
        self.assertEqual((self.ws/'output.txt').read_text(),'First section.\nSecond section.')
        self.assertFalse((self.control/'tool-02-00.json').exists())
        recovery=json.loads((self.control/'api-02.recovery.json').read_text())
        self.assertTrue(recovery['continued']);self.assertEqual(recovery['executed_calls'],0)
        third=client.request.call_args_list[2].args[1]
        self.assertNotIn('MUST NOT EXECUTE',json.dumps(third))
        self.assertEqual(client.request.call_count,4)

    def test_repeated_malformed_text_response_stops_without_extra_requests_or_tools(self):
        from unittest.mock import Mock
        client=Mock();client.request.return_value={'candidates':[{'finishReason':'MALFORMED_FUNCTION_CALL'}]}
        with self.assertRaisesRegex(ValueError,'MALFORMED_FUNCTION_CALL'):
            execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(client.request.call_count,2);self.assertFalse(list(self.control.glob('tool-*')))
        self.assertFalse(json.loads((self.control/'api-02.recovery.json').read_text())['continued'])

    def test_output_limit_on_final_request_cannot_expand_text_budget(self):
        from unittest.mock import Mock
        self.frozen['limits']['provider_requests']=1
        client=Mock();client.request.return_value={'candidates':[{'finishReason':'MAX_TOKENS'}]}
        with self.assertRaisesRegex(ValueError,'output limit'):
            execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(client.request.call_count,1)
        self.assertFalse(json.loads((self.control/'api-01.recovery.json').read_text())['continued'])

    def test_gemini_parameterless_wire_form_preserves_shared_schemas(self):
        from orchestrator.gemini_worker import definitions
        shared=definitions(self.frozen);original=copy.deepcopy(shared)
        scripted=Scripted(self.frozen)
        class StrictTransport:
            def request(_,path,payload,**kwargs):
                for tool in payload['tools'][0]['functionDeclarations']:
                    if tool.get('parameters',{}).get('type')=='object' and not tool['parameters'].get('properties'):
                        raise gemini.ProviderError(400)
                return scripted.request(path,payload,**kwargs)
        result=execute(self.frozen,self.control,StrictTransport(),lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered')
        tools=scripted.calls[0]['tools'][0]['functionDeclarations']
        self.assertNotIn('parameters',next(t for t in tools if t['name']=='file_list'))
        self.assertEqual([t for t in tools if t['name'] not in ('file_list','finish')],[t for t in shared if t['name'] not in ('file_list','finish')])
        self.assertEqual(definitions(self.frozen),original)

    def test_confirmed_rejection_keeps_diagnostic_and_never_retries(self):
        from unittest.mock import Mock
        client=Mock();client.request.side_effect=gemini.ProviderError(400,detail={
            'status':'INVALID_ARGUMENT','message':'Invalid function declaration.'})
        with self.assertRaises(gemini.ProviderError):
            execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        outcome=json.loads((self.control/'api-01.outcome.json').read_text())
        self.assertEqual(outcome['outcome'],'rejected')
        self.assertEqual(outcome['provider_error']['status'],'INVALID_ARGUMENT')
        self.assertEqual(client.request.call_count,1)
        self.assertFalse((self.ws/'output.txt').exists())

    def test_producer_finish_does_not_fabricate_missing_outputs(self):
        with self.assertRaisesRegex(ValueError,'request budget'):self.run_script('finish-only')
        self.assertFalse((self.ws/'output.txt').exists())

    def test_files_reject_undeclared_reads_writes_and_symlink_parents(self):
        files=Files(self.frozen)
        for name,args in [('shell',{}),('file_read',{'path':'../secret','offset':0,'limit':10}),('file_write',{'path':'../secret','text':'x'})]:
            with self.assertRaises(ValueError):files.call(name,args)
        self.frozen['outputs']=[{'path':'linked/out.txt'}];files=Files(self.frozen)
        outside=self.root/'outside';outside.mkdir();(self.ws/'linked').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):files.call('file_write',dict(path='linked/out.txt',text='x'))
        self.assertFalse((outside/'out.txt').exists())

    def test_input_integrity_and_total_output_budget(self):
        source=self.ws/'source.txt';source.write_text('source')
        self.frozen['inputs']=[{'path':'source.txt','sha256':hashlib.sha256(b'wrong').hexdigest()}]
        with self.assertRaisesRegex(ValueError,'changed'):Files(self.frozen)
        self.frozen['inputs'][0]['sha256']=hashlib.sha256(b'source').hexdigest()
        self.frozen['outputs']=[{'path':'one.txt','purpose':'one'},{'path':'two.txt','purpose':'two'}];self.frozen['limits']['output_bytes']=4
        files=Files(self.frozen);files.call('file_write',dict(path='one.txt',text='abc'))
        with self.assertRaisesRegex(ValueError,'budget'):files.call('file_write',dict(path='two.txt',text='de'))
        with self.assertRaises(ValueError):files.call('file_write',dict(path='source.txt',text='bad'))
        self.assertEqual(source.read_text(),'source')
        self.frozen['inputs'][0]['path']='one.txt';self.frozen['inputs'][0].update(artifact='test',purpose='test',authority='test')
        with self.assertRaisesRegex(ValueError,'unique'):c.assignment(self.frozen)

    def test_cancel_and_configuration_change_prevent_dispatch(self):
        atomic(self.control/'cancel.json',{})
        with self.assertRaisesRegex(ValueError,'Cancelled'):self.run_script()
        self.assertFalse(list(self.control.glob('api-*.request.json')))
        (self.control/'cancel.json').unlink()
        with self.assertRaisesRegex(ValueError,'connection changed'):self.run_script(reader=lambda:({'api_key':'new'},BACKEND))
        self.assertFalse(list(self.control.glob('api-*.request.json')))

    def test_uncertain_submission_is_not_replayed(self):
        with self.assertRaises(gemini.ProviderError):self.run_script('uncertain')
        with self.assertRaises(FileExistsError):self.run_script()
        self.assertEqual(len(list(self.control.glob('api-*.request.json'))),1)
        self.assertFalse((self.ws/'.relay/result.json').exists())

    def test_request_and_tool_budgets_stop_before_extra_execution(self):
        with self.assertRaisesRegex(ValueError,'request budget'):self.run_script('loop')
        self.assertEqual(len(list(self.control.glob('api-*.request.json'))),8)
        self.assertFalse((self.ws/'.relay/result.json').exists())

    def test_file_workers_reserve_final_request_and_enforce_allowed_tools(self):
        with self.assertRaisesRegex(ValueError,'request budget'):self.run_script('loop')
        last=json.loads((self.control/'api-08.request.json').read_text())['payload']
        self.assertEqual([t['name'] for t in last['tools'][0]['functionDeclarations']],['finish'])
        self.assertIn('request 8 of 8',last['systemInstruction']['parts'][0]['text'])
        self.assertIn('Tool unavailable',json.loads((self.control/'tool-08-00.json').read_text())['result']['error'])

    def test_failed_agent_reason_survives_the_supervisor_receipt(self):
        from orchestrator.workers import CodexFactory
        atomic(self.control/'agent-result.json',{'outcome':'failed','reason':'Provider request budget exhausted'})
        session={'control':str(self.control),'backend':BACKEND}
        with patch.object(CodexFactory,'inspect',return_value={'status':'finished','exit_code':1,'reason':None}):
            receipt=GeminiFactory().inspect(session)
        self.assertEqual(receipt['reason'],'Provider request budget exhausted')
        self.assertEqual(receipt['external_outcome'],'no_pending_response')

    def test_tool_limit_prevents_a_second_write(self):
        self.frozen['limits']['tool_calls']=1
        with self.assertRaisesRegex(ValueError,'Tool budget'):self.run_script()
        self.assertEqual(len(list(self.control.glob('tool-*.json'))),1)
        self.assertFalse((self.ws/'.relay/result.json').exists())

    def test_real_process_unknown_request_stays_terminal_without_replay(self):
        with patch.object(executors,'available'),patch.object(executors,'configured',return_value=(CONFIG,BACKEND)):
            rt=Runtime(self.root/'runtime',ExecutionFactory(gemini=SupervisorFixture('uncertain')))
            rt.create(graph());rt.tick('demo')
            try:
                result=self.until(rt,lambda s:s['status']=='uncertain')
                self.assertTrue(json.loads(result['attempts'][0]['receipt'])['local_terminal'])
                for _ in range(3):self.assertEqual(len(rt.tick('demo')['attempts']),1)
                self.assertEqual(len(list((rt.root/'workers').glob('*/api-*.request.json'))),1)
            finally:
                for child in rt.factory.gemini.children:child.wait(timeout=5)
                rt.db.close()

    def test_contract_rejects_provider_switch_and_shell_profile(self):
        p=graph();p['tasks'][0]['tools']=['files','shell']
        with self.assertRaisesRegex(ValueError,'provider'):c.plan(p)
        p=graph();p['backend']['type']='unknown'
        with self.assertRaisesRegex(ValueError,'fallback'):c.plan(p)
        with self.assertRaisesRegex(ValueError,'fallback'):ExecutionFactory().adapter({'adapter':'unknown'})

    def test_file_eligibility_persists_but_credential_changes_and_failed_probe_invalidate(self):
        with patch.object(executors,'receipt_path',return_value=self.control/'verification.json'),patch.object(executors,'configured',return_value=(CONFIG,BACKEND)):
            with patch.object(gemini.Client,'request',return_value={'name':'models/fixture-model','supportedGenerationMethods':['generateContent']}):
                result=executors.probe();self.assertNotIn('fingerprint',result);executors.available(BACKEND)
            with patch.object(executors,'configured',return_value=({'api_key':'changed'},BACKEND)):
                with self.assertRaisesRegex(ValueError,'stale'):executors.available(BACKEND)
            with patch.object(executors.time,'time',return_value=time.time()+86400):
                executors.available(BACKEND)
                receipt=json.loads((self.control/'verification.json').read_text())
                self.assertTrue(executors.verification_current(receipt,CONFIG,BACKEND))
            with patch.object(executors.time,'time',return_value=1):
                with self.assertRaisesRegex(ValueError,'stale'):executors.available(BACKEND)
            with patch.object(gemini.Client,'request',side_effect=gemini.ProviderError('Rejected')):
                with self.assertRaises(gemini.ProviderError):executors.probe()
            with self.assertRaisesRegex(ValueError,'stale'):executors.available(BACKEND)

    def until(self,rt,predicate):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            status=rt.tick('demo')
            if predicate(status):return status
            time.sleep(.05)
        self.fail(str(rt.status('demo')))

    def test_real_process_pair_reopen_exact_handoff_without_codex(self):
        with patch.object(executors,'available'),patch.object(executors,'configured',return_value=(CONFIG,BACKEND)):
            factory=ExecutionFactory(gemini=SupervisorFixture());rt=Runtime(self.root/'runtime',factory)
            rt.create(graph());rt.tick('demo');rt.db.close()
            rt=Runtime(self.root/'runtime',factory)
            try:
                status=self.until(rt,lambda s:s['status']=='awaiting_user')
                self.assertEqual(len(status['attempts']),2)
                produced=rt.output('demo','produce','output.txt')
                review=rt.task('demo','review')['latest'];frozen=json.loads((rt.root/'workspaces'/review/'.relay/ASSIGNMENT.json').read_text())
                self.assertEqual(frozen['inputs'][0]['sha256'],produced['sha256'])
                for a in status['attempts']:
                    self.assertEqual(json.loads(a['receipt'])['backend'],BACKEND)
                    self.assertTrue(json.loads(a['receipt'])['usage'])
                self.assertEqual(len(rt.tick('demo')['attempts']),2)
            finally:
                for child in rt.factory.gemini.children:child.wait(timeout=5)
                rt.db.close()

    def test_real_process_cancel_preserves_partial_output_and_remote_uncertainty(self):
        with patch.object(executors,'available'),patch.object(executors,'configured',return_value=(CONFIG,BACKEND)):
            rt=Runtime(self.root/'runtime',ExecutionFactory(gemini=SupervisorFixture('wait')))
            p=graph();p['tasks']=p['tasks'][:1];rt.create(p);rt.tick('demo')
            try:
                self.until(rt,lambda s:bool(list((rt.root/'workers').glob('*/api-02.request.json'))))
                rt.cancel('demo');status=self.until(rt,lambda s:s['tasks'][0]['status']=='cancelled')
                receipt=json.loads(status['attempts'][0]['receipt'])
                self.assertEqual(receipt['external_outcome'],'unknown')
                self.assertTrue(rt.db.execute('SELECT 1 FROM production_artifacts').fetchone())
                self.assertEqual(len(status['attempts']),1)
            finally:
                for child in rt.factory.gemini.children:child.wait(timeout=5)
                rt.db.close()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='fixture':
        control,workspace,mode=map(str,sys.argv[2:]);frozen=json.loads((Path(workspace)/'.relay/ASSIGNMENT.json').read_text())
        # Exercise the same script entry point as GeminiFactory, with only the
        # provider connection/transport replaced. Importing execute as a package
        # hid script-only relative-import failures before any provider request.
        script=Path(__file__).resolve().parents[1]/'orchestrator/gemini_worker.py'
        sys.argv=[str(script),control,workspace]
        with patch.object(executors,'configured_worker',return_value=(CONFIG,BACKEND)), \
             patch.object(gemini,'Client',return_value=Scripted(frozen,mode)):
            runpy.run_path(str(script),run_name='__main__')
    else:unittest.main()
