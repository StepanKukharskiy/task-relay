"""Provider-neutral rendered evidence: scope, retention and exact-once reads."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator.source_fallback import collect,candidates
from orchestrator.runtime_outcomes import UncertainOperation
from task_relay.source_browser import availability,settle,checked_page
from task_relay.source_batches import bind_fallback
from tests.test_evidence_workload import page,pack

URL='https://publisher.example/doc/alpha'

def fixture():
    return pack([dict(query='specific source',target_ids=['A'],pages=[],errors=['HTTP 403'],
                      grounding=[dict(url=URL)],retrievals=[dict(url=URL,outcome='failed')])])

class Tests(unittest.TestCase):
    def test_successful_http_price_is_not_completeness_and_nonproduct_urls_work(self):
        source=fixture();source['entries'][0]['pages']=[dict(page(URL,'Price $10'),products=[dict(offers=[dict(price=10)])])]
        self.assertEqual(candidates(source,[])[0]['url'],URL)
        with tempfile.TemporaryDirectory() as root:
            raw,_=collect(source,[],1,root,lambda *_:page(URL,'Price $10. Width 24.'))
            out=json.loads(raw)
            self.assertEqual(out['entries'][:1],source['entries'])
            self.assertIn('Width 24.',out['entries'][1]['pages'][0]['text'])
            self.assertEqual(candidates(out,[]),[])

    def test_original_domains_cannot_be_widened_and_successful_text_is_preserved(self):
        source=fixture();source['domains']=['publisher.example']
        source['entries'][0]['grounding'].append(dict(url='https://other.example/doc/a'))
        self.assertEqual([x['url'] for x in candidates(source,[])],[URL])
        before=copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as root:
            raw,stats=collect(source,[],1,root,lambda *_:page('https://other.example/doc/a','Wrong domain'))
        self.assertEqual(json.loads(raw)['entries'][:1],before['entries'])
        self.assertEqual(stats['rendered'],0)
        self.assertIn('left selected domains',json.loads(raw)['entries'][1]['errors'][0])

    def test_original_navigation_scope_reaches_renderer_before_dispatch(self):
        source=fixture();source['domains']=['publisher.example'];observed=[]
        with tempfile.TemporaryDirectory() as root:
            collect(source,[],1,root,lambda url,domains,_:(observed.append(domains) or page(url,'Observed')))
        self.assertEqual(observed,[['publisher.example']])
        from orchestrator.source_fallback import domain_intersection
        self.assertEqual(domain_intersection(['example.com'],['sub.example.com']),['sub.example.com'])
        with tempfile.TemporaryDirectory() as root:
            collect(source,['elsewhere.example'],1,root,lambda *_:self.fail('No disjoint-scope dispatch'))

    def test_blocked_browser_capture_is_diagnostic_not_usable_source(self):
        source=fixture()
        blocked=dict(page(URL,'Access denied'),retrieval_status='blocked',retrieval_reason='HTTP 403')
        with tempfile.TemporaryDirectory() as root:
            raw,stats=collect(source,[],1,root,lambda *_:blocked)
        entry=json.loads(raw)['entries'][-1]
        self.assertEqual(entry['pages'],[]);self.assertEqual(entry['diagnostic_capture'],blocked)
        self.assertEqual(stats['rendered'],0);self.assertEqual(stats['unavailable'],1)
        self.assertEqual(candidates(json.loads(raw),[]),[])

    def test_completed_reads_are_reused_exactly_and_changed_source_stops(self):
        source=fixture();calls=[]
        with tempfile.TemporaryDirectory() as root:
            first=collect(source,[],1,root,lambda *args:(calls.append(args[0]) or page(URL,'Observed')))
            second=collect(source,[],1,root,lambda *_:self.fail('No redispatch'))
            self.assertEqual(first,second);self.assertEqual(calls,[URL])
            altered=copy.deepcopy(source);altered['entries'][0]['query']='Different scope'
            with self.assertRaisesRegex(ValueError,'source, selection or grant changed'):
                collect(altered,[],1,root,lambda *_:self.fail('No changed-input dispatch'))

    def test_crash_between_read_and_confirmation_never_replays(self):
        source=fixture()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(UncertainOperation):
                collect(source,[],1,root,lambda *_:(_ for _ in ()).throw(UncertainOperation('lost confirmation')))
            with self.assertRaisesRegex(UncertainOperation,'no confirmed outcome'):
                collect(source,[],1,root,lambda *_:self.fail('No uncertain replay'))
            result={}
            from orchestrator.operation_inspection import rendered
            rendered(Path(root),result,{})
            self.assertEqual(result['status'],'uncertain')

    def test_partial_batch_restart_retains_first_capture_without_dispatching_second_again(self):
        source=fixture();source['entries'].append(dict(query='beta',target_ids=['B'],pages=[],grounding=[dict(url=URL+'/b')],retrievals=[dict(url=URL+'/b',outcome='failed')]))
        calls=[]
        def renderer(url,*_):
            calls.append(url)
            if url.endswith('/b'):raise UncertainOperation('interrupted')
            return page(url,'Retained alpha')
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(UncertainOperation):collect(source,[],2,root,renderer)
            with self.assertRaises(UncertainOperation):collect(source,[],2,root,lambda *_:self.fail('No replay'))
            saved=json.loads((Path(root)/'render-1/fallback-read-outcome.json').read_text())
            self.assertEqual(saved['result']['page']['text'],'Retained alpha')
        self.assertEqual(calls,[URL,URL+'/b'])

    def test_altered_receipt_stops_and_bounded_selection_preserves_all_target_mappings(self):
        source=fixture();source['entries'].append(dict(query='second target',target_ids=['B'],pages=[],grounding=[dict(url=URL),dict(url=URL+'/b')],retrievals=[dict(url=URL+'/b',outcome='failed')]))
        with tempfile.TemporaryDirectory() as root:
            raw,_=collect(source,[],1,root,lambda *_:page(URL,'Observed'))
            self.assertEqual(json.loads(raw)['entries'][-1]['target_ids'],['A','B'])
            path=Path(root)/'render-1/fallback-read-outcome.json';saved=json.loads(path.read_text());saved['result']['page']['text']='Edited';path.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError,'evidence changed'):collect(source,[],1,root,lambda *_:self.fail('No replay'))

    def test_blocked_and_empty_pages_are_not_semantically_accepted(self):
        self.assertEqual(availability('Product','Description',403)[0],'blocked')
        self.assertEqual(availability('Access Denied - Publisher','Navigation and footer',200)[0],'blocked')
        self.assertEqual(availability('Just a moment...','Challenge',200)[0],'blocked')
        self.assertEqual(availability('Document','',200)[0],'empty')
        self.assertEqual(availability('How access denied errors work','Article',200)[0],'captured')

    def test_delayed_dom_is_observed_without_unbounded_networkidle_wait(self):
        class Page:
            now=0
            def locator(self,_):return self
            def inner_text(self,**_):return 'Shell' if self.now<3 else 'Details rendered'
            def wait_for_timeout(self,ms):self.now+=ms/1000
        browser=Page();result=settle(browser,clock=lambda:browser.now)
        self.assertGreaterEqual(result['seconds'],5);self.assertLessEqual(result['seconds'],15)
        self.assertEqual(browser.inner_text(),'Details rendered')
        class Busy(Page):
            def inner_text(self,**_):return str(self.now)
        busy=Busy();result=settle(busy,clock=lambda:busy.now)
        self.assertFalse(result['stable']);self.assertEqual(result['seconds'],15)

    def test_saved_dom_tampering_does_not_redispatch(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'rendered-dom.html';p.write_text('Original')
            value=dict(page=page(URL,'Original'),evidence={'rendered-dom.html':hashlib.sha256(p.read_bytes()).hexdigest()})
            self.assertEqual(checked_page(value,root)['text'],'Original')
            p.write_text('Edited')
            with self.assertRaisesRegex(ValueError,'evidence changed'):checked_page(value,root)

    def test_compiler_composes_both_registered_search_providers_and_respects_absent_grant(self):
        from orchestrator.execution import REGISTRY
        for cap in ('web.sources.prepared','web.sources.prepared.codex'):
            source=dict(id='source',execution=dict(capability=cap,parameters=dict(domains=['publisher.example'])),outputs=[dict(path='delivery/source-pack.json')])
            review=dict(id='review',review_of='source',inputs=[dict(from_task='source',output='delivery/source-pack.json')],outputs=[dict(path='review.md')],dependencies=['source'],criteria=['Review'])
            consumer=dict(id='consumer',inputs=[dict(from_task='source',output='delivery/source-pack.json')],dependencies=['review'],sourcing=dict(source_pack=dict(producer='source',output='delivery/source-pack.json')))
            proposal=dict(plan=dict(tasks=[source,review,consumer]));before=copy.deepcopy(proposal)
            scope=dict(connector_companions_version=1,delivery_completion_policy_version=1,graph_operations=[dict(id=cap,companions=REGISTRY[cap]['companions'])])
            options=dict(max_tasks=5,limits=dict(seconds=120,tool_calls=24,output_bytes=3000000))
            self.assertEqual(bind_fallback(proposal,scope,options),[]);self.assertEqual(before,proposal)
            scope['graph_operations'].append(dict(id='web.sources.rendered',available=True,criteria=['Observed read'],seconds=900))
            receipt=bind_fallback(proposal,scope,options)
            self.assertEqual(receipt[0]['maximum'],1)
            self.assertEqual(proposal['plan']['tasks'][-2]['execution']['parameters']['domains'],['publisher.example'])
            self.assertEqual(consumer['inputs'][0]['from_task'],'source_rendered')
            self.assertEqual(bind_fallback(proposal,scope,options),[])

    def test_confirmed_capture_survives_browser_cleanup_error(self):
        from contextlib import contextmanager
        from unittest.mock import MagicMock
        from task_relay.source_browser import execute
        browser=MagicMock();browser.page.return_value.url=URL
        browser.page.return_value.content.return_value='<html><title>Document</title><body>Observed text</body></html>'
        browser.page.return_value.title.return_value='Document'
        browser.page.return_value.locator.return_value.inner_text.return_value='Observed text'
        @contextmanager
        def cleanup_fault(*args,**kwargs):
            yield browser
            raise PermissionError('cleanup fixture')
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'render-intent.json').write_text(json.dumps(dict(url=URL,domains=[])))
            guard=MagicMock();guard.errors=[];guard.responses=[];guard.evidence.return_value=dict(version=1,requests=[])
            with patch('task_relay.general_browser.browser',cleanup_fault),patch('task_relay.public_browser_navigation.open_page',return_value=(browser.page.return_value,guard)),patch('task_relay.source_browser.settle',return_value=dict(stable=True)):
                execute(root)
            receipt=json.loads((root/'render-outcome.json').read_text())
            self.assertEqual(checked_page(receipt,root)['text'],'Observed text')
            self.assertIn('cleanup fixture',(root/'render-cleanup-error.json').read_text())

    def test_late_unresolved_guard_error_cannot_be_promoted_to_capture(self):
        from contextlib import contextmanager
        from unittest.mock import MagicMock
        from task_relay.source_browser import execute
        browser=MagicMock();page=browser.page.return_value;page.url=URL
        page.content.return_value='<html><body>Observed text</body></html>'
        page.title.return_value='Document';page.locator.return_value.inner_text.return_value='Observed text'
        guard=MagicMock();guard.errors=[];guard.responses=[]
        guard.evidence.return_value=dict(version=1,errors=['unresolved request settlement'])
        browser.public_read_guard=guard
        @contextmanager
        def opened(*args,**kwargs):yield browser
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'render-intent.json').write_text(json.dumps(dict(url=URL,domains=[])))
            with patch('task_relay.general_browser.browser',opened),patch('task_relay.public_browser_navigation.open_page',return_value=(page,guard)),patch('task_relay.source_browser.settle',return_value=dict(stable=True)):
                execute(root)
            receipt=json.loads((root/'render-outcome.json').read_text())
            self.assertEqual(receipt['error'],'Browser request guard failed');self.assertNotIn('page',receipt)
            self.assertEqual(json.loads((root/'network-guard.json').read_text())['errors'],guard.evidence.return_value['errors'])

    def test_page_allowance_is_rejected_before_dispatch(self):
        from orchestrator.operation_validators import rendered_sources
        with self.assertRaisesRegex(ValueError,'time allowance'):
            rendered_sources(dict(execution=dict(parameters=dict(domains=[],max_pages=2)),limits=dict(seconds=120)),dict(seconds=900))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'1–12'):collect(fixture(),[],0,root,lambda *_:self.fail('No dispatch'))

if __name__=='__main__':unittest.main()
