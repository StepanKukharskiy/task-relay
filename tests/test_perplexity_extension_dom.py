"""Real local Chromium executes the extension's page code on synthetic Search DOM."""
from pathlib import Path
import tempfile
import unittest

from task_relay.bridge import State
from task_relay import browser_research as research
from task_relay.perplexity_native import Driver
from task_relay.relay_paths import ASSETS
from tests.test_browser_jobs import URL

HTML = '''<!doctype html><title>Perplexity fixture</title>
<main><nav>Sidebar history is excluded</nav><button aria-label="Profile avatar Fixture">Account</button>
<article id="conversation"></article><textarea aria-label="Ask anything"></textarea>
<button aria-label="Search" aria-pressed="true">Search</button>
<button aria-label="Submit" onclick="send()">Submit</button></main>
<script>
window.sends=0;
function send(){
  sends++;
  const box=document.querySelector('textarea');
  const turn=document.createElement('section');
  const query=document.createElement('p'); query.textContent=box.value;
  turn.append(query);
  const edit=document.createElement('button');edit.setAttribute('aria-label','Edit query');turn.append(edit);
  const answer=document.createElement('p');answer.textContent='Observed fixture answer.';turn.append(answer);
  const link=document.createElement('a');link.href='https://official.example/docs';link.textContent='Official source';turn.append(link);
  const copy=document.createElement('button');copy.setAttribute('aria-label','Copy');turn.append(copy);
  document.querySelector('#conversation').append(turn);box.value='';
  history.pushState({},'', '/search/11111111-2222-3333-4444-555555555555');
}
</script>'''


class ExtensionDOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.runtime.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML))
        self.page.goto('https://www.perplexity.ai/')
        self.page.evaluate("window.browser={runtime:{id:'fixture',onMessage:{addListener:f=>window.receiver=f}}}")
        self.page.add_script_tag(content=(ASSETS / 'perplexity-page.js').read_text())

    def call(self, action, **values):
        return self.page.evaluate("m=>receiver({...m,relay:true},{id:'fixture'})", {'action': action, **values})

    def test_native_driver_and_real_dom_return_exact_once_answer_and_citations(self):
        page = self.page
        outer = self
        class BrowserPort:
            def write(self, message): self.message = message
            def read(self):
                m = self.message
                if m['action'] == 'open': value = True
                else: value = outer.call(m['action'], **{k:v for k,v in m.items() if k not in ('id','action')})
                return {'id': m['id'], 'value': value}
        with tempfile.TemporaryDirectory() as folder:
            state = State(Path(folder) / 'state.sqlite')
            try:
                research.initialize(state.db); research.connection(state.db, 'fixture')
                prompt = 'Exact question ✓\nSecond line'
                receipt = research.enqueue(state, 'dom', '/perplexity ' + prompt, 'local')
                result = research.run_next(state, Driver(BrowserPort()))
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['url'], URL)
                self.assertIn(prompt, result['result'])
                self.assertIn('https://official.example/docs', result['result'])
                self.assertNotIn('Sidebar history', result['result'])
                self.assertIsNone(research.run_next(state, Driver(BrowserPort())))
                self.assertEqual(page.evaluate('sends'), 1)
            finally: state.db.close()

    def test_changed_page_prevents_click_and_preserves_existing_draft(self):
        before = self.call('snapshot')
        self.page.locator('textarea').fill('A user draft')
        with self.assertRaisesRegex(Exception, 'existing draft'):
            self.call('submit', prompt='example', baseline=before)
        self.assertEqual(self.page.locator('textarea').input_value(), 'A user draft')
        self.assertEqual(self.page.evaluate('sends'), 0)

    def test_computer_mode_and_login_never_submit(self):
        before = self.call('snapshot')
        self.page.get_by_role('button', name='Search', exact=True).evaluate("e=>e.setAttribute('aria-pressed','false')")
        with self.assertRaisesRegex(Exception, 'ordinary Search'):
            self.call('submit', prompt='example', baseline=before)
        self.page.get_by_role('button', name='Profile avatar Fixture').evaluate('e=>e.remove()')
        self.assertIn('Sign in', self.call('snapshot')['blocked'])
        self.assertEqual(self.page.evaluate('sends'), 0)

    def test_replaying_same_submit_message_is_rejected(self):
        before = self.call('snapshot')
        self.call('submit', prompt='example', baseline=before)
        with self.assertRaisesRegex(Exception, 'changed before submission'):
            self.call('submit', prompt='example', baseline=before)
        self.assertEqual(self.page.evaluate('sends'), 1)

    def test_navigation_during_prompt_entry_cannot_submit_in_another_conversation(self):
        before = self.call('snapshot')
        self.page.locator('textarea').evaluate("e=>e.addEventListener('input',()=>history.pushState({},'', '/search/11111111-2222-3333-4444-555555555555'))")
        with self.assertRaisesRegex(Exception, 'conversation changed'):
            self.call('submit', prompt='example', baseline=before)
        self.assertEqual(self.page.evaluate('sends'), 0)

    def test_different_sender_cannot_control_the_page(self):
        before = self.call('snapshot')
        result = self.page.evaluate("m=>receiver(m,{id:'another-addon'})", {'relay':True,'action':'submit','prompt':'example','baseline':before})
        self.assertIsNone(result)
        self.assertEqual(self.page.evaluate('sends'), 0)


if __name__ == '__main__': unittest.main()
