"""Recovery uses existing receipts; transports are synthetic, decisions tested separately."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from task_relay import orchestrator_web as web,source_browser
from orchestrator.runtime_outcomes import UncertainOperation

class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.receipt=Path(self.tmp.name)/'reads.json'
        self.url='https://example.com/article'
    def session(self):return web.Session(self.receipt,durable=True,rendered=True)
    def call(self,url=None,**kw):return self.session().execute(dict(name='web_fetch',arguments=json.dumps(dict(url=url or self.url,offset=0,limit=1000,**kw))))
    def http(self,url,domains,control):
        control.mkdir(parents=True,exist_ok=True);(control/'http').mkdir()
        text='Article navigation only'
        (control/'http/page-1.json').write_text(json.dumps(dict(text=text)))
        return dict(url=url,title='Article',text=text,links=[],sha256='http',retrieval_status='captured')
    def render(self,url,domains,control):
        control.mkdir(parents=True,exist_ok=True);text='Readable article body.'
        (control/'rendered-text.txt').write_text(text)
        return dict(url=url,title='Article',text=text,sha256='rendered',retrieval_status='captured')
    def test_shell_can_use_untried_renderer_then_restart_reuses_rendered_content(self):
        with patch.object(source_browser,'read_http',side_effect=self.http) as h,patch.object(source_browser,'render',side_effect=self.render) as r:
            first=self.call();second=self.call(method='rendered');third=self.call()
        self.assertTrue(first['rendered_available']);self.assertEqual(second['text'],'Readable article body.')
        self.assertEqual(third,second);self.assertEqual((h.call_count,r.call_count),(1,1))
        self.assertEqual(second['recovery']['methods_remaining'],4)
    def test_error_capture_preserves_literal_alternatives_then_other_source_works(self):
        def download(url):
            html=(b'<title>500</title><h1>500 - Something went wrong</h1><link rel="canonical" href="/readable">'
                  if url==self.url else b'<title>Article</title><p>Useful text about bounded recovery.</p>')
            return url,html,'text/html','utf-8'
        with patch.object(web,'download',side_effect=download) as h,patch.object(source_browser,'render',side_effect=ValueError('blocked')) as r:
            first=self.call();same=self.call()
            self.assertFalse(first['ok']);self.assertEqual(first,same)
            candidate=first['recovery']['observed_untried_links'][0]
            self.assertEqual(candidate['url'],'https://example.com/readable')
            self.assertEqual(candidate['basis'],'observed-link-canonical')
            second=self.call(candidate['url'])
        self.assertTrue(second['ok']);self.assertIn('Useful text',second['text'])
        self.assertEqual((h.call_count,r.call_count),(2,1));self.assertEqual(second['recovery']['methods_used'],3)
        evidence=list(self.receipt.with_suffix('').glob('*/http/http/page-1.json'))
        self.assertEqual(len(evidence),2)
    def test_uncertainty_on_one_url_blocks_different_url_and_method(self):
        with patch.object(source_browser,'read_http',side_effect=UncertainOperation('missing terminal')) as h,patch.object(source_browser,'render') as r:
            first=self.call();second=self.call('https://example.com/other',method='rendered')
        self.assertEqual(first['outcome'],'uncertain');self.assertEqual(second['outcome'],'uncertain')
        self.assertEqual(h.call_count,1);r.assert_not_called()
    def test_total_six_methods_includes_failed_reads_and_no_repeats(self):
        with patch.object(source_browser,'read_http',side_effect=ValueError('403')) as h,patch.object(source_browser,'render',side_effect=ValueError('blocked')) as r:
            for n in range(3):self.call('https://example.com/'+str(n))
            exhausted=self.call('https://example.com/other');again=self.call('https://example.com/0')
        self.assertEqual(exhausted['outcome'],'exhausted');self.assertEqual(exhausted['recovery']['methods_remaining'],0)
        self.assertEqual(again['outcome'],'unavailable');self.assertEqual((h.call_count,r.call_count),(3,3))
    def test_tampered_failed_capture_blocks_alternatives_without_new_effect(self):
        with patch.object(web,'download',return_value=(self.url,b'<h1>Page not found</h1>','text/html','utf-8')),patch.object(source_browser,'render',side_effect=ValueError('blocked')):
            self.call()
        next(self.receipt.with_suffix('').glob('*/http/http/page-1.json')).write_text('changed')
        with patch.object(source_browser,'read_http') as h:
            result=self.call('https://example.com/other')
        self.assertFalse(result['ok']);self.assertIn('changed',result['error']);h.assert_not_called()
    def test_error_words_inside_substantive_article_are_not_error_page(self):
        self.assertEqual(source_browser.availability('How to fix internal server errors','This article explains errors.\nFor example, something went wrong is a common message.',200)[0],'captured')
        self.assertEqual(source_browser.availability('Publisher','500—something went wrong\nTry later.',200)[0],'blocked')
    def test_partial_paywall_text_remains_available_for_honest_summary(self):
        text='A useful introduction.\nMember-only story. Subscribe to read the rest.'
        with patch.object(web,'download',return_value=(self.url,text.encode(),'text/plain','utf-8')),patch.object(source_browser,'render') as r:
            result=self.call()
        self.assertTrue(result['ok']);self.assertIn('Member-only',result['text']);r.assert_not_called()
        self.assertIn('completeness',result['note'])
    def test_navigation_before_error_body_is_failed_acquisition_with_preserved_links(self):
        text='Get app\nWrite\n\nSign up\n\nSign in\n\n500\nApologies, but something went wrong on our end.\n\nRefresh the page, check site status, or find something interesting to read.'
        def render(url,domains,control):
            control.mkdir(parents=True,exist_ok=True);(control/'rendered-text.txt').write_text(text)
            status,reason=source_browser.availability('Publisher',text,200)
            return dict(url=url,title='Publisher',text=text,sha256='fixture',links=['https://example.com/status'],retrieval_status=status,retrieval_reason=reason)
        with patch.object(source_browser,'read_http',side_effect=ValueError('403')),patch.object(source_browser,'render',side_effect=render):
            result=self.call()
        self.assertFalse(result['ok']);self.assertEqual(result['outcome'],'unavailable')
        self.assertEqual(result['recovery']['observed_untried_links'][0]['url'],'https://example.com/status')
        self.assertEqual(result['recovery']['methods_used'],2)
    def test_literal_link_discovery_excludes_unsafe_urls_and_has_bounded_omissions(self):
        html='<link rel="canonical" href="javascript:alert(1)"><link rel="amphtml" href="/amp">'+''.join('<a href="/p%d">link</a>'%n for n in range(30))
        with patch.object(web,'download',return_value=(self.url,html.encode(),'text/html','utf-8')):
            result=self.call()
        recovery=result['recovery'];self.assertEqual(len(recovery['observed_untried_links']),20)
        self.assertEqual(recovery['omitted_links'],11);self.assertEqual(recovery['observed_untried_links'][0]['url'],'https://example.com/amp')

if __name__=='__main__':unittest.main()

class NodeRecovery(unittest.TestCase):
    def test_actual_node_loop_receives_recovery_selects_observed_link_and_delivers(self):
        from tests.test_node_interface import Nodes
        from tests.test_operation_session import CONFIG,Script
        from tests.test_job_owner_loop import BACKEND
        from orchestrator import executors
        from orchestrator.gemini_worker import execute
        from orchestrator.workers import atomic
        f=Nodes();f.setUp();self.addCleanup(f.doCleanups)
        atomic(f.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        case=self
        class Decisions(Script):
            def request(inner,endpoint,payload,**kw):
                n=len(inner.requests)
                if n==0:step=('web_fetch',dict(url='https://example.com/article',offset=0,limit=1000))
                elif n==1:
                    case.assertIn('observed-link-canonical',json.dumps(payload))
                    case.assertIn('methods_remaining',json.dumps(payload))
                    step=('web_fetch',dict(url='https://example.com/readable',offset=0,limit=1000))
                else:
                    case.assertIn('Useful text about bounded recovery',json.dumps(payload))
                    step=('node_result',dict(outputs={'report':{'text':'The source describes bounded recovery.'}},summary='Source summarized.'))
                inner.steps=iter([step]);return super().request(endpoint,payload,**kw)
        def download(url):
            html=b'<h1>Page not found</h1><link rel="canonical" href="/readable">' if url.endswith('/article') else b'<p>Useful text about bounded recovery.</p>'
            return url,html,'text/html','utf-8'
        client=Decisions([])
        with patch.object(web,'download',side_effect=download),patch.object(source_browser,'render',side_effect=ValueError('blocked')):
            result=execute(f.frozen,f.control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.requests),3)
        f.s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        f.f.rt.tick('job');self.assertEqual(f.f.rt.status('job')['status'],'completed')
        self.assertEqual(len(f.f.factory.calls),1)
