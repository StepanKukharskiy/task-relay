"""Bounded text executor: scripted transport and real supervisor processes, no API calls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import gemini
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
        if self.mode=='loop':name,args='file_list',{}
        elif n==1 and self.frozen['inputs']:
            name,args='file_read',dict(path=self.frozen['inputs'][0]['path'],offset=0,limit=24000)
        elif n==(2 if self.frozen['inputs'] else 1):
            name,args='file_write',dict(path=self.frozen['outputs'][0]['path'],text='bounded fixture output')
        else:name,args='finish',report(self.frozen)
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

    def test_loop_preserves_signatures_ids_usage_and_report(self):
        result,client=self.run_script()
        history=client.calls[1]['contents']
        self.assertEqual(history[1]['parts'][0]['thoughtSignature'],'opaque-signature')
        self.assertEqual(history[2]['parts'][0]['functionResponse']['id'],'call-1')
        self.assertEqual(result['decision'],'delivered')
        self.assertEqual((self.ws/'output.txt').read_text(),'bounded fixture output')
        self.assertEqual(len(list(self.control.glob('api-*.response.json'))),2)

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

    def test_eligibility_is_credential_bound_expires_and_failed_probe_invalidates(self):
        with patch.object(executors,'receipt_path',return_value=self.control/'verification.json'),patch.object(executors,'configured',return_value=(CONFIG,BACKEND)):
            with patch.object(gemini.Client,'request',return_value={'name':'models/fixture-model','supportedGenerationMethods':['generateContent']}):
                result=executors.probe();self.assertNotIn('fingerprint',result);executors.available(BACKEND)
            with patch.object(executors,'configured',return_value=({'api_key':'changed'},BACKEND)):
                with self.assertRaisesRegex(ValueError,'stale'):executors.available(BACKEND)
            with patch.object(executors.time,'time',return_value=time.time()+1000):
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
        execute(frozen,control,Scripted(frozen,mode),lambda:(CONFIG,BACKEND))
    else:unittest.main()
