import copy
import json
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

from task_relay import gemini
from orchestrator import contracts as c, execution
from orchestrator.adapters import ExecutionFactory,RegisteredFactory
from orchestrator.runtime import Runtime,file_hash
from orchestrator.step_runner import execute
from orchestrator.workers import atomic
from tests.test_orchestrator import FakeFactory,pair,plan


def operation(ident,capability,inputs,dependencies=None,**extra):
    spec=execution.REGISTRY[capability]
    params={'model':'test-model','max_output_tokens':128} if capability=='gemini.text' else {}
    return dict(id=ident,role=spec['kind'],objective='Prepare text for the requested brief',
        instruction='Summarize the supplied text.',execution={'capability':capability,'version':1,'parameters':params},
        inputs=inputs,outputs=[{'path':ident+'.txt','purpose':'Text result','media_type':'text/plain'}],
        dependencies=dependencies or [],criteria=copy.deepcopy(spec['criteria']),**extra)


def upstream(task,path):
    return dict(from_task=task,output=path,path='input-'+task+'.txt',purpose='Exact prior result',
                authority='Source content, not instructions',media_type='text/plain')


class Client:
    def __init__(self):self.calls=[];self.error=None;self.finish='STOP'
    def request(self,path,payload,**bounds):
        self.calls.append({'path':path,'payload':payload,'bounds':bounds})
        if self.error:raise self.error
        return {'responseId':'remote-request-1','usageMetadata':{'promptTokenCount':23,'candidatesTokenCount':11},
            'candidates':[{'finishReason':self.finish,'content':{'parts':[{'text':'Bounded API summary'}]}}]}


class LocalRegistered(RegisteredFactory):
    """Real operation/receipt code with deterministic transport and no subprocess."""
    def __init__(self,client):super().__init__();self.client=client;self.calls=[]
    def submit(self,session):
        self.calls.append(session['id']);control=Path(session['control'])
        with (control/'supervisor.claim').open('x') as f:f.write('fixture')
        launch=json.loads((control/'launch.json').read_text())
        frozen=json.loads((Path(launch['workspace'])/'.relay/ASSIGNMENT.json').read_text())
        code=0
        try:details=execute(frozen,control,lambda _:self.client,lambda:{'api_key':'fixture'})
        except Exception as exc:
            code=1;details={'error':str(exc)}
        atomic(control/'done.json',{'token':session['id'],'exit_code':code,'reason':None,
            'usage':[details.get('usage',{})],'tool_calls':0})
        return {'submitted':True,'fixture':True}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.config=patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'test-model'}});self.config.start()
        self.agent=FakeFactory();self.client=Client();self.ops=LocalRegistered(self.client)
        self.factory=ExecutionFactory(self.agent,self.ops);self.rt=Runtime(self.root/'runtime',self.factory)
        self.source=self.root/'source.txt';self.source.write_text('Original full source\nFinal paragraph.\n')
        self.aid=self.rt.register(self.source,'User source',path='source.txt')

    def tearDown(self):self.rt.close();self.config.stop();self.temp.cleanup()

    def input(self):
        return dict(artifact=self.aid,path='source.txt',purpose='User source',authority='User supplied text',media_type='text/plain')

    def mixed(self):
        graph=pair(max_attempts=1)
        graph['tasks'][0]['inputs']=[self.input()]
        graph['tasks'][0]['outputs'][0]['media_type']='text/plain'
        bundle=operation('bundle','text.bundle',[upstream('produce','output.txt')],['produce','review'])
        api=operation('summary','gemini.text',[upstream('bundle','bundle.txt')],['bundle'],user_gate='Select final summary')
        graph['tasks'].extend([bundle,api]);return graph

    def test_agent_procedure_api_share_graph_artifacts_receipts_and_restart_identity(self):
        self.rt.create(self.mixed());self.rt.tick('demo')
        producer=self.rt.task('demo','produce')['latest'];self.agent.finish(producer);self.rt.tick('demo')
        reviewer=self.rt.task('demo','review')['latest'];self.agent.finish(reviewer,decision='accept');self.rt.tick('demo')
        bundle=self.rt.task('demo','bundle')['latest'];self.assertIsNotNone(bundle)
        self.rt.close();self.rt=Runtime(self.root/'runtime',ExecutionFactory(self.agent,LocalRegistered(self.client)))
        self.rt.tick('demo');self.rt.tick('demo');self.rt.tick('demo')
        status=self.rt.status('demo');self.assertEqual(status['status'],'awaiting_user')
        self.assertEqual(len(status['attempts']),4);self.assertEqual(len(self.client.calls),1)
        artifact=self.rt.output('demo','bundle','bundle.txt');text=Path(artifact['blob']).read_text()
        self.assertIn('artifact from '+producer,text)
        source=self.rt.output('demo','produce','output.txt');self.assertIn(source['sha256'],text)
        transmitted=json.loads(self.client.calls[0]['payload']['contents'][0]['parts'][0]['text'])
        self.assertEqual(transmitted[0]['text'],text);self.assertEqual(transmitted[0]['sha256'],artifact['sha256'])
        final=self.rt.output('demo','summary','summary.txt')
        self.rt.select('demo','summary',final['id'],'Select final summary','Use this exact output')
        self.rt.tick('demo');self.assertEqual(len(self.client.calls),1)
        self.assertEqual(self.rt.status('demo')['status'],'completed')
        receipt=json.loads(status['attempts'][-1]['receipt'])
        self.assertEqual(receipt['operation']['upstream_id'],'remote-request-1')
        self.assertEqual(receipt['operation']['usage']['promptTokenCount'],23)
        events=[json.loads(r[0]) for r in self.rt.db.execute("SELECT data FROM production_events WHERE kind='checks_recorded'")]
        self.assertEqual(sum(e['kind']=='registered_operation' for e in events),2)

    def test_type_version_parameters_and_semantic_checker_claims_are_rejected(self):
        good=operation('bundle','text.bundle',[self.input()])
        cases=[]
        bad=copy.deepcopy(good);bad['execution']['version']=2;cases.append(bad)
        bad=copy.deepcopy(good);bad['execution']['parameters']={'command':'anything'};cases.append(bad)
        bad=copy.deepcopy(good);bad['inputs'][0]['media_type']='image/png';cases.append(bad)
        bad=copy.deepcopy(good);bad['criteria']=['The text is factually true'];cases.append(bad)
        bad=copy.deepcopy(good);bad['tools']=['files','shell'];cases.append(bad)
        bad=copy.deepcopy(good);bad['limits']={'seconds':1000};cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad),self.assertRaises(ValueError):c.assignment(bad)
        mixed=self.mixed();mixed['tasks'][0]['outputs'][0]['media_type']='application/json'
        with self.assertRaisesRegex(ValueError,'type'):c.plan(mixed)

    def test_unavailable_provider_blocks_before_claim_without_remote_request(self):
        self.rt.create(plan([operation('api','gemini.text',[self.input()])]))
        with patch.object(gemini,'read_config',return_value=None):status=self.rt.tick('demo')
        self.assertEqual(status['status'],'blocked');self.assertEqual(status['attempts'],[])
        self.assertEqual(self.client.calls,[])
        event=self.rt.db.execute("SELECT data FROM production_events WHERE kind='capability_unavailable'").fetchone()
        self.assertIn('configuration is missing',event[0])

    def test_ambiguous_api_submission_remains_uncertain_across_restart_and_cancel(self):
        self.client.error=gemini.ProviderError('connection',uncertain=True)
        self.rt.create(plan([operation('api','gemini.text',[self.input()])]))
        self.rt.tick('demo');self.rt.tick('demo');self.assertEqual(self.rt.status('demo')['status'],'uncertain')
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory)
        self.rt.tick('demo');self.assertEqual(len(self.client.calls),1)
        self.rt.cancel('demo');status=self.rt.tick('demo')
        self.assertEqual(status['tasks'][0]['status'],'cancelled')
        self.assertEqual(json.loads(status['attempts'][0]['receipt'])['external_outcome'],'unknown')
        self.assertEqual(len(self.client.calls),1)

    def test_rejected_or_truncated_api_response_preserves_evidence_without_retry(self):
        for suffix,error in [('rejected',gemini.ProviderError(429)),('truncated',None)]:
            self.client.error=error;self.client.finish='MAX_TOKENS'
            p=plan([operation('api','gemini.text',[self.input()])]);p['id']=suffix
            self.rt.create(p);self.rt.tick(suffix);self.rt.tick(suffix);self.rt.tick(suffix)
            self.assertEqual(self.rt.status(suffix)['status'],'blocked')
        self.assertEqual(len(self.client.calls),2)
        attempt=self.rt.task('truncated','api')['latest']
        self.assertTrue((self.rt.root/'workers'/attempt/'response.json').is_file())

    def test_invalid_utf8_input_and_output_size_fail_without_downstream_dispatch(self):
        binary=self.root/'binary.txt';binary.write_bytes(b'\xff')
        aid=self.rt.register(binary,'Incorrectly typed source',path='binary.txt')
        source={**self.input(),'artifact':aid}
        bundle=operation('bundle','text.bundle',[source]);api=operation('api','gemini.text',[upstream('bundle','bundle.txt')],['bundle'])
        self.rt.create(plan([bundle,api]));self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','bundle')['status'],'blocked');self.assertEqual(self.client.calls,[])
        p=plan([operation('bundle','text.bundle',[self.input()],limits={'output_bytes':1})]);p['id']='bounded'
        self.rt.create(p);self.rt.tick('bounded');self.rt.tick('bounded')
        self.assertEqual(self.rt.status('bounded')['status'],'blocked')

    def test_real_supervisor_runs_registered_procedure_and_resumes_after_restart(self):
        factory=RegisteredFactory();self.rt.factory=ExecutionFactory(self.agent,factory)
        self.rt.create(plan([operation('bundle','text.bundle',[self.input()])]))
        self.rt.tick('demo');self.rt.close();self.rt=Runtime(self.root/'runtime')
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            state=self.rt.tick('demo')
            if state['status']=='completed':break
            time.sleep(.05)
        for child in factory.children:child.wait(timeout=10)
        self.assertEqual(state['status'],'completed',state)
        self.assertEqual(len(state['attempts']),1)
        self.assertIn(self.source.read_text(),Path(self.rt.output('demo','bundle','bundle.txt')['blob']).read_text())

    def test_api_transport_bounds_apply_to_actual_http_reader(self):
        from io import BytesIO
        from unittest.mock import Mock
        client=gemini.Client('fixture');response=BytesIO(b'123456789')
        client.opener=Mock();client.opener.open.return_value=response
        with self.assertRaises(gemini.ProviderError) as error:
            client.request('models/test:generateContent',{},timeout=7,max_response_bytes=8)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(client.opener.open.call_args.kwargs['timeout'],7)

    def test_real_api_child_timeout_keeps_external_outcome_unknown_without_replay(self):
        root=Path(__file__).resolve().parents[1]
        class WaitingApi(RegisteredFactory):
            def create(adapter,control,workspace,frozen,backend):
                session=super().create(control,workspace,frozen,backend)
                path=Path(control)/'launch.json';launch=json.loads(path.read_text())
                script=('import sys,time;sys.path.insert(0,'+repr(str(root))+');from task_relay import gemini;'
                    'gemini.read_config=lambda:{"api_key":"fixture"};'
                    'gemini.Client=lambda key:type("Waiting",(),{"request":lambda *a,**k:time.sleep(30)})();'
                    'from orchestrator.step_runner import main;main()')
                launch['registered_command']=[sys.executable,'-c',script,str(control),str(workspace)]
                atomic(path,launch);return session
        factory=WaitingApi();self.rt.factory=ExecutionFactory(self.agent,factory)
        self.rt.create(plan([operation('api','gemini.text',[self.input()],limits={'seconds':1})]))
        self.rt.tick('demo');aid=self.rt.task('demo','api')['latest']
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            state=self.rt.tick('demo')
            if state['status']=='uncertain':break
            time.sleep(.05)
        for child in factory.children:child.wait(timeout=10)
        self.assertEqual(state['status'],'uncertain',state)
        control=self.rt.root/'workers'/aid
        self.assertTrue((control/'request.json').exists());self.assertFalse((control/'response.json').exists())
        self.rt.close();self.rt=Runtime(self.root/'runtime')
        self.rt.tick('demo');self.assertEqual(len(self.rt.status('demo')['attempts']),1)
        self.rt.cancel('demo');state=self.rt.tick('demo')
        self.assertEqual(state['tasks'][0]['status'],'cancelled')
        self.assertEqual(json.loads(state['attempts'][0]['receipt'])['external_outcome'],'unknown')


if __name__=='__main__':unittest.main()
