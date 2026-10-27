"""Terminal search rejection, bounded partial evidence and restart; no network."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import codex_sources, web_sources
from orchestrator.codex_transport import Client
from orchestrator.workers import atomic
from task_relay.gemini import ProviderError
from tests.test_codex_executor import CONFIG, BACKEND, Tests as Flow
from tests.test_web_sources import FakeSession


def exhausted(turn='turn', status=429):
    error=dict(message='exceeded retry limit, last status: 429 Too Many Requests',
               codexErrorInfo=dict(responseTooManyFailedAttempts=dict(httpStatusCode=status)))
    return [dict(method='error',params=dict(threadId='thread',turnId=turn,error=error,willRetry=False)),
            dict(method='turn/completed',params=dict(threadId='thread',turn=dict(id=turn,status='failed',error=error,items=[],itemsView='notLoaded')))]


def peer(root, steps):
    root.mkdir(parents=True,exist_ok=True);script=root/'script.json';atomic(script,steps)
    return Client(CONFIG,BACKEND,root,10,command=[sys.executable,'-B',str(Path(__file__).with_name('codex_protocol_fixture.py')),str(script)])


class Terminal(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        if os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE'):
            self.root=Path(os.environ['TASK_RELAY_OFFLINE_EVIDENCE'])/self._testMethodName
            self.root.mkdir(parents=True,exist_ok=False)
        self.config=dict(backend=BACKEND,cli_executor=CONFIG,models=dict(text='fixture'))

    def test_exact_terminal_shape_no_retry_and_hashed_restart(self):
        folder=self.root/'query'
        with patch.object(codex_sources,'configuration',return_value=(CONFIG,BACKEND)),patch.object(codex_sources,'Client',side_effect=lambda a,b,c,d:peer(c,[dict(events=exhausted())])) as factory:
            for _ in range(2):
                with self.assertRaises(ProviderError) as error:codex_sources.Session(folder.with_suffix('.json'),self.config).search('fixture')
                self.assertFalse(error.exception.uncertain)
                self.assertEqual(error.exception.status,429)
                self.assertTrue(error.exception.detail['retry_exhausted'])
                self.assertIsNone(error.exception.detail['usage'])
            self.assertEqual(factory.call_count,1)
        sent=[json.loads(v) for v in (folder/'codex/codex-sent.jsonl').read_text().splitlines()]
        self.assertEqual(sum(s.get('method')=='turn/start' for s in sent),1)
        record=json.loads((folder/'search-0.json').read_text());self.assertEqual(record['status'],'rejected')
        for name,sha in record['detail']['journals'].items():self.assertEqual(hashlib.sha256((folder/'codex'/name).read_bytes()).hexdigest(),sha)
        with (folder/'codex/codex-events.jsonl').open('a') as stream:stream.write('{}\n')
        with patch.object(codex_sources,'Client') as factory:
            with self.assertRaisesRegex(ProviderError,'no verified response') as error:codex_sources.Session(folder.with_suffix('.json'),self.config).search('fixture')
            self.assertTrue(error.exception.uncertain)
            factory.assert_not_called()

    def test_pending_foreign_unmatched_or_prose_failure_stays_uncertain(self):
        for kind in ('pending','foreign','unmatched','missing','prose','retrying'):
            events=exhausted()
            if kind=='pending':events.insert(0,dict(method='item/started',params=dict(threadId='thread',turnId='turn',item=dict(type='webSearch',id='pending'))))
            if kind=='foreign':events[0]['params']['turnId']='foreign'
            if kind=='unmatched':events[-1]['params']['turn']['error']=dict(message='different')
            if kind=='missing':events.pop()
            if kind=='prose':
                for e in events:
                    error=e['params'].get('error',e['params'].get('turn',{}).get('error'))
                    error.pop('codexErrorInfo',None)
            if kind=='retrying':events[0]['params']['willRetry']=True
            with self.subTest(kind=kind),peer(self.root/kind,[dict(events=events)]) as client:
                if kind=='missing':
                    import time
                    client.deadline=time.monotonic()+0.05
                with self.assertRaises((ProviderError,OSError)) as error:client.search('fixture')
                if isinstance(error.exception,ProviderError):self.assertTrue(error.exception.uncertain)

    def test_completed_read_retained_after_exhaustion_without_replay(self):
        events=[dict(method='item/completed',params=dict(threadId='thread',turnId='turn',item=dict(id='read',type='webSearch',query='fixture',results=[dict(url='https://example.org/item')]))),*exhausted()]
        with peer(self.root/'read',[dict(events=events)]) as client:result=client.search('fixture')
        self.assertEqual(result['sources'][0]['url'],'https://example.org/item')
        self.assertFalse(result['observation_outcome']['replayed'])

    def test_provider_neutral_batch_stop_preserves_pages_and_unsubmitted_queries(self):
        for status in (429,503,'serverOverloaded'):
            class Sources(FakeSession):
                calls=[]
                def search(self,query):
                    if query=='second':
                        self.calls.append(('search',query));raise ProviderError(status,uncertain=False,detail=dict(message='Synthetic confirmed rejection'))
                    return super().search(query)
            raw,counts=web_sources.collect(['first','second','third'],[],'fixture',self.root/str(status),self.config,session_factory=Sources)
            pack=json.loads(raw);self.assertEqual([e['status'] for e in pack['entries']],['source_fetched','unavailable','not_submitted'])
            self.assertEqual(pack['entries'][0]['pages'][0]['sha256'],'a'*64)
            self.assertEqual(counts['fetched'],1)
            self.assertFalse(pack['entries'][1]['search_outcome']['retry_allowed'])
            self.assertNotIn(('search','third'),Sources.calls)
        class Unknown(FakeSession):
            error=ProviderError(429,uncertain=True)
        with self.assertRaises(ProviderError):web_sources.collect(['first','second'],[],'fixture',self.root/'unknown',self.config,session_factory=Unknown)

    def test_internal_retry_progress_is_not_new_authority(self):
        events=exhausted();progress=copy.deepcopy(events[0]);progress['params']['willRetry']=True
        with peer(self.root/'progress',[dict(events=[progress,*events])]) as client:
            with self.assertRaises(ProviderError) as error:client.search('fixture')
        self.assertFalse(error.exception.uncertain);self.assertEqual(error.exception.detail['internal_retry_notifications'],1)

    def test_unverified_saved_submission_stops_whole_batch_without_new_dispatch(self):
        for malformed in (False,True):
            root=self.root/str(malformed);folder=root/'query-01';folder.mkdir(parents=True)
            (folder/'search-0.json').write_text('{' if malformed else json.dumps(dict(
                query='first',backend=BACKEND,request_id='saved',status='submitted')))
            with patch.object(codex_sources,'Client') as provider:
                with self.assertRaises(ProviderError) as error:
                    web_sources.collect(['first','second'],[],'fixture',root,self.config,session_factory=codex_sources.Session)
                self.assertTrue(error.exception.uncertain)
                provider.assert_not_called()
                self.assertFalse((root/'query-02').exists())


class Lifecycle(Flow):
    from tests.test_browser_fallback_lifecycle import retain_evidence as tearDown
    def test_partial_pack_reaches_independent_review_after_restart(self):
        from orchestrator import step_runner
        from orchestrator.runtime import Runtime
        selector=patch('orchestrator.codex_sources.configuration',return_value=(CONFIG,BACKEND));selector.start();self.addCleanup(selector.stop)
        self.grant['operations']=['web.sources.codex'];self.create()
        self.invoke('owner',[('job_delegate',dict(request_id='sources',tasks=[dict(id='search',objective='Collect source evidence',operation='web.sources.codex',parameters=dict(queries=['first','second','third'],domains=[])),dict(id='review',objective='Assess retained evidence and disclose unresolved queries',review_of='search')]))])
        self.rt.tick('job');state=self.factory.sessions[self.rt.task('job','search')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True);f['codex_executor']=CONFIG
        calls=[]
        def factory(a,b,folder,seconds):
            calls.append(str(folder))
            events=exhausted() if len(calls)==2 else [dict(method='item/completed',params=dict(threadId='thread',turnId='turn',item=dict(id='read',type='webSearch',query='first',results=[dict(url='https://example.org/item')]))),dict(method='turn/completed',params=dict(threadId='thread',turn=dict(id='turn',status='completed')))]
            return peer(folder,[dict(events=events)])
        page=FakeSession(self.root/'fixture',{}).fetch('https://example.org/item',0,100)
        with patch.object(codex_sources,'Client',side_effect=factory),patch.object(codex_sources.Session,'fetch',return_value=page):step_runner.execute(f,control)
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job',dispatch=False)
        artifact=self.rt.output('job','search','delivery/source-pack.json')
        self.assertEqual(len(calls),2)
        original=copy.deepcopy(artifact)
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory);self.addCleanup(self.rt.close)
        self.assertEqual(self.rt.output('job','search','delivery/source-pack.json'),original)
        self.rt.tick('job')
        spec=self.rt.spec(self.rt.task('job','review'))
        self.assertTrue(any(i.get('from_task')=='search' for i in spec['inputs']))
        frozen=self.factory.sessions[self.rt.task('job','review')['latest']]['frozen']
        _,review_control,_=self.invoke('review',[('finish',self.report('review','accept'))])
        supplied=json.loads((review_control/'api-01.request.json').read_text())
        self.assertIn('not_submitted',json.dumps(supplied))
        self.assertIn('unavailable',json.dumps(supplied))
        self.rt.tick('job',dispatch=False)
        self.assertEqual(self.rt.task('job','review')['status'],'completed')
        self.assertNotEqual(self.rt.status('job')['status'],'uncertain')
