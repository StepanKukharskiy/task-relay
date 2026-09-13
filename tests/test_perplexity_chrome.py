"""External Chromium attachment preserves login and leaves task tabs inspectable."""
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit
from unittest.mock import Mock,patch

from task_relay.host_perplexity import attached_page,chrome_endpoint
from task_relay.perplexity_browser import PerplexityPage
from tests.test_browser_accounts_dom import Tests as BrowserFixture


class ScopeTests(unittest.TestCase):
    def test_transient_submit_url_can_be_observed_but_cannot_finish_receipt(self):
        from task_relay.browser_jobs import completed
        page=Mock(url='https://www.perplexity.ai/search/new?query=fixture')
        main=page.get_by_role.return_value
        main.inner_text.return_value='fixture'
        control=main.get_by_role.return_value
        control.count.return_value=1
        main.get_by_role.side_effect=lambda *args,**kw:Mock(count=lambda:0) if kw.get('name')=='Stop response' else control
        main.get_by_role.return_value.locator.return_value.filter.return_value.filter.return_value.count.return_value=1
        snapshot=PerplexityPage(page).snapshot()
        baseline={'queries':0,'answers':0,'text':''}
        self.assertFalse(completed(baseline,snapshot,'fixture'))
        page.url='https://www.perplexity.ai/search/00000000-0000-0000-0000-000000000001'
        self.assertTrue(completed(baseline,PerplexityPage(page).snapshot(),'fixture'))

    def test_missing_or_invalid_descriptor_never_selects_another_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);folder=home/'Library/Application Support/Google/Chrome';folder.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'enable remote debugging'):chrome_endpoint('darwin',home)
            for raw in ('0\n/devtools/browser/fixture','9222\n/devtools/browser/fixture?token=example','9222\n/other','9222\n/devtools/browser/a\nextra'):
                (folder/'DevToolsActivePort').write_text(raw)
                with self.assertRaises(ValueError):chrome_endpoint('darwin',home)
            (folder/'DevToolsActivePort').write_text('9222\n/devtools/browser/fixture')
            self.assertEqual(chrome_endpoint('darwin',home),'ws://127.0.0.1:9222/devtools/browser/fixture')

    def test_foreign_destination_is_rejected_before_reading_page_text(self):
        page=Mock(url='https://example.com/login')
        with self.assertRaises(ValueError):PerplexityPage(page).snapshot()
        page.get_by_role.assert_not_called()


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOCAL_BROWSER_FIXTURE')=='1','Requires local Chromium fixture')
class ConnectionTests(unittest.TestCase):
    setUp=BrowserFixture.setUp
    tearDown=BrowserFixture.tearDown
    user_pages=BrowserFixture.user_pages

    def test_search_uses_submit_when_enter_does_not_send_and_never_replays(self):
        import sqlite3
        from task_relay.browser_jobs import Journal, execute
        from tests.test_browser_jobs import URL
        endpoint='http://'+urlsplit(self.endpoint).netloc
        with attached_page(endpoint) as page, sqlite3.connect(':memory:') as db:
            page.route('https://www.perplexity.ai/**',lambda route:route.fulfill(content_type='text/html',body='''<main>
                <button aria-label="Profile avatar"></button><button aria-pressed="true">Search</button>
                <p id="decoration">Loading suggestions</p><section id="turn"></section><div id="draft" role="textbox" contenteditable="true"></div>
                <button aria-label="Use voice mode" id="submit" disabled>Voice</button></main><script>
                window.sends=0;window.enterKeys=0;
                draft.oninput=()=>setTimeout(()=>{submit.setAttribute('aria-label','Submit');submit.disabled=false},80);
                draft.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();window.enterKeys++}};
                submit.onclick=()=>{
                  window.sends++;
                  submit.setAttribute('aria-label','Use voice mode');submit.disabled=true;
                  const question=document.createElement('p');question.textContent=draft.innerText;
                  turn.append(question);draft.innerText='';
                  turn.insertAdjacentHTML('beforeend','<button>Edit query</button><p>Fixture answer</p><div><button>Copy</button><button>Share</button><button>Fork</button></div>');
                  history.pushState({},'', '/search/11111111-2222-3333-4444-555555555555');
                };</script>'''))
            journal=Journal(db);prompt='Research fixture contractors ✓'
            journal.prepare('submit-fixture',prompt)
            class HydratingPage(PerplexityPage):
                observations=0
                def snapshot(self):
                    self.observations+=1
                    if self.observations==2:
                        self.page.locator('#decoration').evaluate("e=>e.textContent='Suggestions loaded'")
                    return super().snapshot()
            driver=HydratingPage(page)
            result=execute(journal,'submit-fixture',driver,timeout=1)
            self.assertEqual(result['status'],'completed',result['error'])
            self.assertEqual(result['url'],URL)
            self.assertIn(prompt,result['result'])
            self.assertEqual(page.evaluate('window.sends'),1)
            self.assertEqual(page.evaluate('window.enterKeys'),0)
            execute(journal,'submit-fixture',driver,timeout=1)
            self.assertEqual(page.evaluate('window.sends'),1)
            from task_relay.browser_jobs import completed
            import json
            page.get_by_role('main').evaluate("e=>e.insertAdjacentHTML('beforeend','<button>Stop response</button>')")
            self.assertFalse(completed(json.loads(journal.get('submit-fixture')['baseline']),driver.snapshot(),prompt))

    def test_real_conversation_changes_and_existing_drafts_still_block(self):
        from task_relay.browser_jobs import SubmissionNotAttempted
        endpoint='http://'+urlsplit(self.endpoint).netloc
        with attached_page(endpoint) as page:
            page.route('https://www.perplexity.ai/**',lambda route:route.fulfill(content_type='text/html',body='''<main>
                <button aria-label="Profile avatar"></button><button aria-pressed="true">Search</button>
                <p id="answer">Existing answer</p><button>Edit query</button>
                <div><button>Copy</button><button>Share</button><button>Fork</button></div>
                <div role="textbox" contenteditable="true"></div><button onclick="window.sends++">Submit</button>
                </main><script>window.sends=0</script>'''))
            driver=PerplexityPage(page)
            driver.open('https://www.perplexity.ai/search/11111111-2222-3333-4444-555555555555')
            baseline=driver.snapshot()
            page.locator('#answer').evaluate("e=>e.textContent='Changed answer'")
            with self.assertRaisesRegex(SubmissionNotAttempted,'Conversation changed'):
                driver.submit('fixture',baseline)
            self.assertEqual(page.get_by_role('textbox').inner_text(),'')
            page.get_by_role('textbox').fill('User draft')
            with self.assertRaisesRegex(SubmissionNotAttempted,'existing draft'):
                driver.submit('fixture',driver.snapshot())
            self.assertEqual(page.get_by_role('textbox').inner_text(),'User draft')
            self.assertEqual(page.evaluate('window.sends'),0)

    def test_ambiguous_submit_controls_keep_draft_without_clicking(self):
        endpoint='http://'+urlsplit(self.endpoint).netloc
        with attached_page(endpoint) as page:
            page.route('https://www.perplexity.ai/**',lambda route:route.fulfill(content_type='text/html',body='''<main>
                <button aria-label="Profile avatar"></button><button aria-pressed="true">Search</button>
                <div role="textbox" contenteditable="true"></div>
                <button onclick="window.sends++">Submit</button><button onclick="window.sends++">Submit</button></main><script>window.sends=0</script>'''))
            driver=PerplexityPage(page);driver.open()
            with self.assertRaisesRegex(ValueError,'uniquely visible'):
                driver.submit('fixture',driver.snapshot())
            self.assertEqual(page.get_by_role('textbox').inner_text(),'fixture')
            self.assertEqual(page.evaluate('window.sends'),0)

    def test_read_only_inspection_observes_voice_control_without_sending(self):
        from task_relay.perplexity_browser import inspect_controls, inspect_open_pages
        endpoint='http://'+urlsplit(self.endpoint).netloc
        with attached_page(endpoint) as page:
            page.route('https://www.perplexity.ai/**',lambda route:route.fulfill(content_type='text/html',body='''<main>
                <div role="textbox" contenteditable="true"></div>
                <button aria-label="Use voice mode" onclick="window.sends++"></button>
                <button hidden aria-label="hidden control"></button></main><script>window.sends=0</script>'''))
            page.goto('https://www.perplexity.ai/')
            self.assertTrue(inspect_controls(page,'fixture')['draft_empty'])
            self.assertEqual(page.evaluate('window.sends'),0)
        before=self.user_pages()
        with patch('task_relay.host_managed_chrome.live_socket',return_value=self.endpoint):
            result=inspect_open_pages(self.root,{'id':'fixture','status':'uncertain','prompt':'fixture','url':None,'target':None})
        self.assertEqual(self.user_pages(),before)
        self.assertEqual(result['matching_tabs'],1)
        observed=result['observations'][0]
        self.assertTrue(observed['draft_empty'])
        self.assertFalse(observed['draft_matches_request'])
        self.assertEqual([b['aria-label'] for b in observed['buttons']],['Use voice mode'])
        with patch('task_relay.host_managed_chrome.live_socket',return_value=None):
            with self.assertRaisesRegex(ValueError,'did not launch'):
                inspect_open_pages(self.root,{'id':'fixture'})

    def test_inline_copy_does_not_count_as_another_answer(self):
        from task_relay.browser_jobs import completed
        endpoint='http://'+urlsplit(self.endpoint).netloc
        with attached_page(endpoint) as page:
            page.route('https://www.perplexity.ai/**',lambda route:route.fulfill(content_type='text/html',body='''
                <main><p>Fixture question</p><button>Edit query</button>
                <blockquote>Quoted text <button aria-label="Copy"></button></blockquote>
                <p>Fixture answer</p><div><button aria-label="Copy"></button>
                <button aria-label="Share"></button><button aria-label="Fork"></button></div>
                <div role="textbox" contenteditable="true"></div><button>Submit</button></main>'''))
            page.goto('https://www.perplexity.ai/search/00000000-0000-0000-0000-000000000001')
            driver=PerplexityPage(page);snapshot=driver.snapshot()
            self.assertEqual(snapshot['answers'],1)
            baseline={'queries':0,'answers':0,'text':''}
            self.assertTrue(completed(baseline,snapshot,'Fixture question'))
            page.get_by_role('button',name='Fork',exact=True).evaluate('el=>el.remove()')
            self.assertFalse(completed(baseline,driver.snapshot(),'Fixture question'))

    def test_login_survives_disconnect_and_error_retains_task_tab(self):
        endpoint='http://'+urlsplit(self.endpoint).netloc
        before=self.user_pages()
        with self.assertRaisesRegex(ValueError,'fixture disconnect'):
            with attached_page(endpoint) as page:
                page.goto(self.url+'/work')
                self.assertIn('Signed in',page.inner_text('body'))
                raise ValueError('fixture disconnect')
        self.assertIsNone(self.process.poll())
        self.assertCountEqual(self.user_pages(),before+[self.url+'/work'])
        with attached_page(endpoint) as page:
            page.goto(self.url+'/next')
            self.assertIn('Signed in',page.inner_text('body'))
        self.assertCountEqual(self.user_pages(),before+[self.url+'/work',self.url+'/next'])

    def test_discovered_browser_uses_same_session_without_launching(self):
        from task_relay import host_perplexity
        with patch.object(host_perplexity,'chrome_endpoint',return_value=self.endpoint):
            with attached_page(chrome=True) as page:
                page.goto(self.url+'/discovered')
                self.assertIn('Signed in',page.inner_text('body'))
        self.assertIsNone(self.process.poll())
        self.assertIn(self.url+'/discovered',self.user_pages())


del BrowserFixture

if __name__=='__main__':unittest.main()
