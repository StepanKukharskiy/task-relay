"""Controlled provider cooldown and retained-work continuation, no model/network."""
import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import provider_cooldown as pc
from orchestrator.runtime_outcomes import Hold
from orchestrator.workers import atomic
from tests.test_codex_executor import Tests as Flow,BACKEND
from tests.test_search_terminal import exhausted

class Clock:
    def __init__(self):self.value=1000;self.sleeps=[]
    def now(self):return self.value
    def sleep(self,n):self.value+=n;self.sleeps.append(n)

class Policy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.clock=Clock()
        self.frozen=dict(provider_cooldown=dict(policy=copy.deepcopy(pc.POLICY),database=str(self.root/'shared.sqlite')),
                         backend=BACKEND,assignment_id='first')
    def gate(self,ident='first',backend=None):
        f=dict(self.frozen,assignment_id=ident,backend=backend or BACKEND);control=self.root/ident;control.mkdir(exist_ok=True)
        return pc.Cooldown(f,control,clock=self.clock.now,sleep=self.clock.sleep)
    def reject(self,gate,stem='api-01',**kw):
        atomic(gate.control/(stem+'.request.json'),dict(request='exact'))
        atomic(gate.control/(stem+'.outcome.json'),dict(outcome='rejected',http_status=429))
        return gate.publish(stem,dict(http_status=429,provider_error=kw.pop('detail',{})),kw.pop('requests',10),kw.pop('seconds',500),**kw)
    def test_shared_scope_survives_reopen_and_staggers_without_blocking_other_provider(self):
        a=self.gate();self.assertTrue(self.reject(a))
        b=self.gate('second');b.wait('api-01',500)
        self.assertEqual(self.clock.now(),1030)
        # Reopening coordinator reads durable state rather than resetting the wait.
        self.gate('third').wait('api-01',500);self.assertEqual(self.clock.now(),1032)
        other=self.gate('other',dict(type='gemini-agent',model='fixture'));other.wait('api-01',500)
        self.assertEqual(self.clock.now(),1032)
    def test_repeated_failures_have_total_bound_and_original_request_deadline(self):
        a=self.gate();self.assertTrue(self.reject(a));a.wait('api-02',500)
        self.assertTrue(self.reject(a,'api-02'));a.wait('api-03',500)
        self.assertFalse(self.reject(a,'api-03'))
        self.assertEqual(sum(self.clock.sleeps),120)
        self.assertFalse(self.reject(self.gate('no-budget'),requests=0))
        self.assertFalse(self.reject(self.gate('no-time'),seconds=10))
        with self.assertRaises(Hold):self.gate('short').wait('api-01',10)
    def test_pending_cooldown_restart_cancel_and_changed_receipt_never_dispatch(self):
        a=self.gate();self.reject(a)
        self.clock.value+=5
        self.gate().wait('api-02',500);self.assertEqual(self.clock.now(),1030)
        self.assertTrue(self.reject(a)) # same durable failure, not a new retry
        self.assertEqual(json.loads((a.control/'api-01.cooldown.json').read_text())['ordinal'],1)
        (a.control/'api-01.outcome.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):a.publish('api-01',{},10,500)
        b=self.gate('cancelled');(b.control/'cancel.json').touch()
        with self.assertRaisesRegex(Hold,'Cancelled'):b.wait('api-01',500)
    def test_server_delay_is_honored_or_stops_not_shortened(self):
        a=self.gate();self.assertTrue(self.reject(a,detail=dict(retry_after_seconds=65)))
        a.wait('api-02',500);self.assertEqual(sum(self.clock.sleeps),65)
        self.assertFalse(self.reject(a,'api-02',detail=dict(retry_after_seconds=900)))
        with self.assertRaises(Hold):a.wait('api-03',500)
    def test_api_providers_share_policy_and_unknown_hosted_quota_are_excluded(self):
        for provider in ('gemini','openai','openrouter','qwen'):
            backend=dict(type=provider+'-agent',model='fixture')
            payload=dict(tools=[dict(functionDeclarations=[])] if provider=='gemini' else [dict(type='function')],store=False,stream=False)
            request=dict(provider=provider,model='fixture',endpoint='models/fixture:generateContent' if provider=='gemini' else 'responses' if provider=='openai' else 'chat/completions',payload=payload)
            outcome=dict(outcome='rejected',http_status=429)
            self.assertTrue(pc.eligible(backend,request,outcome),provider)
            self.assertFalse(pc.eligible(backend,request,dict(outcome,outcome='uncertain')))
            self.assertFalse(pc.eligible(backend,request,dict(outcome,provider_error=dict(code='insufficient_quota'))))
            payload['tools']=[dict(type='web_search')]
            self.assertFalse(pc.eligible(backend,request,outcome))

    def test_search_failure_cools_same_provider_without_replaying_search(self):
        from task_relay.gemini import ProviderError
        gate=self.gate('search')
        pc.search_failure(gate,'exact failed query',ProviderError(429,detail=dict(retry_after_seconds=40)),500)
        receipt=json.loads((gate.control/'provider-search.cooldown.json').read_text())
        self.assertFalse(receipt['continued'])
        self.gate('review').wait('api-01',500)
        self.assertEqual(sum(self.clock.sleeps),40)
        pc.search_failure(gate,'unknown effect',ProviderError(429,uncertain=True),500)
        self.assertEqual(json.loads((gate.control/'provider-search.request.json').read_text())['query'],'exact failed query')

    def test_http_delay_and_quota_details_preserved_across_api_adapters(self):
        import io,urllib.error
        from unittest.mock import Mock
        from task_relay import api_providers as api,gemini
        key='secret-key-fixture'
        for provider in ('gemini','openai','openrouter','qwen'):
            client=gemini.Client(key) if provider=='gemini' else api.Client(provider,key)
            error=urllib.error.HTTPError('https://example.org',429,'Too many',{'Retry-After':'65'},
                io.BytesIO(json.dumps(dict(error=dict(code='insufficient_quota',message=key+' quota'))).encode()))
            client.opener=Mock();client.opener.open.side_effect=error
            with self.assertRaises(gemini.ProviderError) as caught:
                client.request('models/fixture:generateContent' if provider=='gemini' else 'responses' if provider=='openai' else 'chat/completions',{})
            self.assertEqual(caught.exception.detail['retry_after_seconds'],65)
            self.assertEqual(caught.exception.detail['code'],'insufficient_quota')
            self.assertNotIn(key,json.dumps(caught.exception.detail))
            self.assertEqual(client.opener.open.call_count,1)

    def test_expired_deadline_never_claims_dispatch_slot(self):
        with self.assertRaises(Hold):self.gate().wait('api-01',0)

class Lifecycle(Flow):
    from tests.test_browser_fallback_lifecycle import retain_evidence as tearDown
    def test_partial_source_evidence_and_review_survive_restart_with_shared_cooldown(self):
        from tests.test_search_terminal import Lifecycle as SourceFlow
        self.grant['provider_cooldown']=copy.deepcopy(pc.POLICY)
        clock=Clock();real=pc.Cooldown
        with patch.object(pc,'Cooldown',side_effect=lambda f,c:real(f,c,clock=clock.now,sleep=clock.sleep)):
            SourceFlow.test_partial_pack_reaches_independent_review_after_restart(self)
        self.assertGreaterEqual(sum(clock.sleeps),30)
        receipts=list(self.root.rglob('provider-search.cooldown.json'))
        self.assertEqual(len(receipts),1)
        receipt=json.loads(receipts[0].read_text());self.assertFalse(receipt['continued'])
        for name,binding in receipt['journal_prefixes'].items():
            self.assertEqual(hashlib.sha256((receipts[0].parent/name).read_bytes()[:binding['bytes']]).hexdigest(),binding['sha256'])

    def test_written_artifact_survives_cooldown_and_same_thread_continuation(self):
        self.grant['provider_cooldown']=copy.deepcopy(pc.POLICY);self.create()
        self.invoke('owner',[('job_delegate',dict(request_id='write',tasks=[self.worker()]))]);self.rt.tick('job')
        clock=Clock();real=pc.Cooldown
        with patch.object(pc,'Cooldown',side_effect=lambda f,c:real(f,c,clock=clock.now,sleep=clock.sleep)):
            _,control,_=self.invoke('write',[('file_write',dict(path='outputs/result.txt',text='Retained exact work.')),
                dict(events=exhausted()),('finish',self.report('write'))])
        sent=[json.loads(s) for s in (control/'codex-sent.jsonl').read_text().splitlines()]
        self.assertEqual(sum(s.get('method')=='thread/start' for s in sent),1)
        self.assertEqual(sum(s.get('method')=='turn/start' for s in sent),2)
        tools=[json.loads(p.read_text()) for p in control.glob('tool-*.json')]
        self.assertEqual(sum(t.get('name')=='file_write' for t in tools),1)
        self.assertEqual(sum(clock.sleeps),30)
        receipt=json.loads((control/'api-02.cooldown.json').read_text())
        for name,binding in receipt['journal_prefixes'].items():
            self.assertEqual(hashlib.sha256((control/name).read_bytes()[:binding['bytes']]).hexdigest(),binding['sha256'])
        self.rt.tick('job',dispatch=False)
        artifact=self.rt.output('job','write','outputs/result.txt');self.assertEqual(Path(artifact['blob']).read_text(),'Retained exact work.')
    def test_owner_exhaustion_stops_after_two_cooldowns_with_no_delegated_effect(self):
        from task_relay.gemini import ProviderError
        self.grant['provider_cooldown']=copy.deepcopy(pc.POLICY);self.create()
        real=pc.Cooldown;clock=Clock()
        with patch.object(pc,'Cooldown',side_effect=lambda f,c:real(f,c,clock=clock.now,sleep=clock.sleep)):
            with self.assertRaises(ProviderError):self.invoke('owner',[dict(events=exhausted()),dict(events=exhausted('turn-2')),dict(events=exhausted('turn-3'))])
        control=Path(self.factory.sessions[self.rt.task('job','owner')['latest']]['session']['control'])
        self.assertEqual(len(list(control.glob('api-*.request.json'))),3)
        self.assertEqual(sum(clock.sleeps),120)
        self.assertFalse(json.loads((control/'api-03.cooldown.json').read_text())['continued'])
        self.assertFalse(list(control.glob('tool-*.json')))

    def test_confirmed_503_resumes_but_quota_does_not(self):
        from task_relay.gemini import ProviderError
        self.grant['provider_cooldown']=copy.deepcopy(pc.POLICY);self.create()
        real=pc.Cooldown;clock=Clock()
        with patch.object(pc,'Cooldown',side_effect=lambda f,c:real(f,c,clock=clock.now,sleep=clock.sleep)):
            _,control,_=self.invoke('owner',[dict(events=exhausted(status=503)),('job_delegate',dict(request_id='write',tasks=[self.worker()]))])
        self.assertEqual(sum(clock.sleeps),30)
        self.assertTrue(json.loads((control/'api-01.cooldown.json').read_text())['continued'])
        self.rt.tick('job')
        quota=dict(method='account/rateLimits/updated',params=dict(rateLimits=dict(primary=dict(usedPercent=100))))
        with self.assertRaises(ProviderError):self.invoke('write',[dict(events=[quota,*exhausted()])])
        control=Path(self.factory.sessions[self.rt.task('job','write')['latest']]['session']['control'])
        self.assertEqual(len(list(control.glob('api-*.request.json'))),1)
        self.assertFalse(list(control.glob('api-*.cooldown.json')))


class APIExecution(unittest.TestCase):
    from tests.test_generation_recovery import Tests as Fixture
    setUp=Fixture.setUp
    backend=Fixture.backend
    setup_worker=Fixture.setup_worker

    def test_real_worker_script_and_compatibility_entrypoints_preserve_written_artifact(self):
        import subprocess,sys
        from tests.test_gemini_executor import CONFIG,BACKEND
        from orchestrator import executors
        for mode in ('cooldown','cooldown-compat'):
            with self.subTest(entrypoint=mode),tempfile.TemporaryDirectory(dir=self.root) as folder:
                control=Path(folder);self.setup_worker(code=False,control=control)
                self.frozen['backend']=BACKEND
                self.frozen['provider_cooldown']=dict(policy=copy.deepcopy(pc.POLICY),database=str(control/'cooldown.sqlite'))
                self.frozen['assignment_id']=mode
                self.frozen['runtime_sources']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(pc.__file__).parent.glob('*.py')}
                atomic(self.ws/'.relay/ASSIGNMENT.json',self.frozen)
                atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
                result=subprocess.run([sys.executable,str(Path(__file__).with_name('test_gemini_executor.py')),'fixture',str(control),str(self.ws),mode],capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr+(control/'agent-result.json').read_text())
                self.assertEqual(json.loads((control/'agent-result.json').read_text())['outcome'],'completed')
                self.assertTrue(json.loads((control/'api-02.cooldown.json').read_text())['continued'])
                tools=[json.loads(p.read_text()) for p in control.glob('tool-*.json')]
                self.assertEqual(sum(t['name']=='file_write' for t in tools),1)
                if os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE'):
                    import shutil
                    destination=Path(os.environ['TASK_RELAY_OFFLINE_EVIDENCE'])/('process-'+mode)
                    shutil.copytree(control,destination)
                    (destination/'subprocess.stdout.txt').write_text(result.stdout)

    def test_function_generation_resumes_across_all_api_providers(self):
        from orchestrator.agent_loop import execute
        from task_relay.gemini import ProviderError
        from tests.test_shared_code_workers import Transport
        for provider in ('gemini','openai','openrouter','qwen'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as folder:
                control=Path(folder);reader=self.setup_worker(provider,code=False,control=control)
                self.frozen['provider_cooldown']=dict(policy=copy.deepcopy(pc.POLICY),database=str(control/'cooldown.sqlite'))
                self.frozen['assignment_id']=provider
                transport=Transport(provider,self.frozen,False);calls=[];real=pc.Cooldown;clock=Clock()
                def request(*args,**kwargs):
                    calls.append(1)
                    if len(calls)==1:raise ProviderError(429,detail=dict(retry_after_seconds=35))
                    return transport.request(*args,**kwargs)
                with patch.object(pc,'Cooldown',side_effect=lambda f,c:real(f,c,clock=clock.now,sleep=clock.sleep)):
                    result=execute(self.frozen,control,type('Client',(),{'request':staticmethod(request)})(),reader)
                self.assertEqual(result['decision'],'delivered')
                self.assertEqual(sum(clock.sleeps),37) # server delay plus two-second shared admission spacing
                self.assertEqual(len(calls),3)
                self.assertEqual(len(list(control.glob('tool-*.json'))),2)

    def test_unknown_response_or_pending_effect_prevents_retry(self):
        from orchestrator.agent_loop import execute
        from task_relay.gemini import ProviderError
        for mode in ('unknown','pending'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as folder:
                control=Path(folder);reader=self.setup_worker(code=False,control=control)
                self.frozen['provider_cooldown']=dict(policy=copy.deepcopy(pc.POLICY),database=str(control/'cooldown.sqlite'))
                self.frozen['assignment_id']=mode
                if mode=='pending':
                    sub=control/'code-unknown';sub.mkdir();atomic(sub/'intent.json',{})
                calls=[]
                def request(*args,**kwargs):
                    calls.append(1);raise ProviderError(429,uncertain=mode=='unknown')
                with self.assertRaises(ProviderError):execute(self.frozen,control,type('Client',(),{'request':staticmethod(request)})(),reader)
                self.assertEqual(len(calls),1)
                self.assertFalse(list(control.glob('api-*.cooldown.json')))
