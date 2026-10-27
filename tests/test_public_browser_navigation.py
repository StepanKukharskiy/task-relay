import unittest
from unittest.mock import patch
from task_relay.public_browser_navigation import Guard

class Session:
    def __init__(self):self.calls=[];self.handlers={}
    def on(self,event,handler):self.handlers[event]=handler
    def send(self,name,args=None):self.calls.append((name,args))

class Tests(unittest.TestCase):
    def test_cancelled_subresource_requires_exact_independent_receipt_without_replay(self):
        for receipt_first in (False,True):
            with self.subTest(receipt_first=receipt_first):
                session=Session();guard=Guard(session,'main',[])
                original=session.send
                def send(method,args=None):
                    original(method,args)
                    if method=='Fetch.continueRequest':raise ValueError('Protocol error (Fetch.continueRequest): Invalid InterceptionId.')
                session.send=send
                event=dict(requestId='fetch-1',networkId='network-1',request=dict(url='https://example.com/optional',method='GET'),resourceType='XHR',frameId='main')
                if receipt_first:guard.failed(dict(requestId='network-1',canceled=True))
                with patch('task_relay.orchestrator_web.public_addresses',return_value=['8.8.8.8']):guard.paused(event)
                if not receipt_first:
                    self.assertTrue(guard.errors)
                    guard.failed(dict(requestId='other-request',canceled=True))
                    guard.failed(dict(requestId='network-1',canceled=False))
                    self.assertTrue(guard.errors)
                    guard.failed(dict(requestId='network-1',canceled=True))
                self.assertFalse(guard.errors)
                self.assertEqual(guard.evidence()['settlements'][0]['outcome'],'cancelled')
                self.assertEqual(sum(n=='Fetch.continueRequest' for n,_ in session.calls),1)

    def test_main_document_denial_and_unrelated_protocol_errors_still_fail_closed(self):
        for resource,method,network,error in [('Document','GET','network','Invalid InterceptionId'),
                ('XHR','POST','network','Invalid InterceptionId'),('XHR','GET',None,'Invalid InterceptionId'),
                ('XHR','GET','network','Target page closed')]:
            with self.subTest(resource=resource,method=method,network=network,error=error):
                session=Session();guard=Guard(session,'main',[])
                def send(*a,**k):raise ValueError(error)
                session.send=send;guard.failed(dict(requestId='network',canceled=True))
                with patch('task_relay.orchestrator_web.public_addresses',return_value=['8.8.8.8']):
                    with self.assertRaises(ValueError):guard.paused(dict(requestId='fetch',networkId=network,request=dict(url='https://example.com/a',method=method),resourceType=resource,frameId='main'))
                self.assertTrue(guard.errors)

    def test_native_request_preserves_browser_headers_and_rechecks_redirects(self):
        session=Session();guard=Guard(session,'main',['example.com'])
        with patch('task_relay.orchestrator_web.public_addresses',return_value=['8.8.8.8']):
            for ident,url in [('one','https://example.com/a'),('two','https://example.com/b'),('three','https://outside.example/a')]:
                guard.paused(dict(requestId=ident,request=dict(url=url,method='GET',headers={'Observed':'browser'}),resourceType='Document',frameId='main',redirectedRequestId='one' if ident!='one' else None))
        continued=[args for method,args in session.calls if method=='Fetch.continueRequest']
        self.assertEqual(continued,[dict(requestId='one'),dict(requestId='two')])
        self.assertEqual(session.calls[-1][0],'Fetch.failRequest')
        self.assertIn('selected source domains',guard.requests[-1]['reason'])

    def test_private_subresource_and_mutation_are_denied_before_send(self):
        session=Session();guard=Guard(session,'main',[])
        for url,method in [('https://127.0.0.1/a','GET'),('https://example.com/a','POST')]:
            guard.paused(dict(requestId=url,request=dict(url=url,method=method),resourceType='XHR',frameId='main'))
        self.assertEqual([m for m,_ in session.calls[-2:]],['Fetch.failRequest','Fetch.failRequest'])

    def test_dns_failure_and_capacity_fail_closed(self):
        session=Session();guard=Guard(session,'main',[],maximum=1)
        with patch('task_relay.orchestrator_web.public_addresses',side_effect=OSError('DNS unavailable')):
            for n in range(2):guard.paused(dict(requestId=str(n),request=dict(url='https://example.com/a',method='GET'),resourceType='Document',frameId='main'))
        self.assertEqual([r['outcome'] for r in guard.requests],['blocked','blocked'])
        self.assertIn('allowance',guard.requests[-1]['reason'])
        self.assertNotIn('Fetch.continueRequest',[m for m,_ in session.calls])

    def test_body_timeout_is_recoverable_inside_original_window(self):
        import sys,types
        from task_relay.source_browser import settle
        class Timeout(Exception):pass
        class Page:
            now=0
            def locator(self,_):return self
            def inner_text(self,**_):
                if self.now<2:raise Timeout('Body not yet attached')
                return 'Observed document'
            def wait_for_timeout(self,ms):self.now+=ms/1000
            def is_closed(self):return False
        page=Page()
        with patch.dict(sys.modules,{'playwright.sync_api':types.SimpleNamespace(Error=Timeout,TimeoutError=Timeout)}):
            result=settle(page,clock=lambda:page.now)
        self.assertGreater(result['transient_documents'],0)
        self.assertGreaterEqual(result['seconds'],5)
        self.assertLessEqual(result['seconds'],15)

    def test_absent_body_and_closed_page_do_not_extend_deadline(self):
        import sys,types
        from task_relay.source_browser import settle
        class Timeout(Exception):pass
        class Page:
            now=0;closed=False
            def locator(self,_):return self
            def inner_text(self,**_):raise Timeout('Missing')
            def wait_for_timeout(self,ms):self.now+=ms/1000
            def is_closed(self):return self.closed
        with patch.dict(sys.modules,{'playwright.sync_api':types.SimpleNamespace(Error=Timeout,TimeoutError=Timeout)}):
            page=Page()
            with self.assertRaisesRegex(ValueError,'observation window'):settle(page,maximum=2,clock=lambda:page.now)
            self.assertEqual(page.now,2)
            page=Page();page.closed=True
            with self.assertRaises(Timeout):settle(page,clock=lambda:page.now)
            self.assertEqual(page.now,0)

    def test_navigation_module_is_frozen_before_registered_dispatch(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from orchestrator.operation_bindings import rendered
        from orchestrator.operation_execution import Context,rendered_sources
        from orchestrator.runtime import file_hash
        from task_relay import public_browser_navigation
        frozen=dict(runtime_sources={})
        rendered(frozen)
        key='task_relay/public_browser_navigation.py'
        self.assertEqual(frozen['runtime_sources'][key],file_hash(Path(public_browser_navigation.__file__)))
        frozen['runtime_sources'][key]='0'*64
        with TemporaryDirectory() as root,patch('task_relay.source_browser.render') as launch:
            with self.assertRaisesRegex(ValueError,'changed after dispatch'):
                rendered_sources(Context(frozen,Path(root),Path(root),{},[]))
            launch.assert_not_called()

if __name__=='__main__':unittest.main()
