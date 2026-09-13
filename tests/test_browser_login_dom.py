"""Opt-in synthetic login pages in Chromium; all requests intercepted locally."""
import os
import unittest
from task_relay.perplexity_browser import PerplexityPage


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOGIN_BROWSER_FIXTURE')=='1','Local login browser opt-in required')
class Tests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.runtime=sync_playwright().start()
        self.addCleanup(self.runtime.stop)
        self.browser=self.runtime.chromium.launch(headless=True)
        self.addCleanup(self.browser.close)
        self.page=self.browser.new_page()
        self.calls=[]
        self.html='<form action="/auth/email"><input type="email" name="email"><button>Continue with email</button></form>'
        def serve(route):
            request=route.request
            self.calls.append((request.url,request.method,request.post_data))
            if request.method=='POST':
                self.html='<form method="POST" action="/auth/verify"><input name="code" autocomplete="one-time-code"><button>Verify code</button></form>'
            route.fulfill(status=200,content_type='text/html',body='<title>Fixture login</title>'+self.html)
        self.page.route('**/*',serve)
        self.driver=PerplexityPage(self.page)

    def open_form(self,html=None):
        if html:self.html=html
        self.driver.begin_login()

    def test_exact_email_and_code_forms_submit_once_each(self):
        self.open_form('<form method="POST" action="/auth/email"><input type="email" name="email"><button>Continue</button></form>')
        self.assertEqual(self.driver.login_stage(),'email')
        self.driver.login_submit('email','fixture@example.test')
        self.assertEqual(self.driver.login_stage(),'code')
        self.assertEqual([r[2] for r in self.calls if r[1]=='POST'],['email=fixture%40example.test'])
        # Change the next code form to POST so its submission can be counted too.
        self.page.locator('form').evaluate("form=>form.method='POST'")
        self.driver.login_submit('code','123456')
        self.assertEqual([r[2] for r in self.calls if r[1]=='POST'],['email=fixture%40example.test','code=123456'])

    def test_other_domain_and_cross_origin_form_never_receive_input(self):
        self.open_form('<form action="https://outside.invalid/login"><input type="email"><button>Continue</button></form>')
        with self.assertRaises(ValueError):self.driver.login_submit('email','fixture@example.test')
        self.assertEqual(self.page.locator('input').input_value(),'')
        self.page.goto('https://outside.invalid/')
        before=len(self.calls)
        with self.assertRaises(ValueError):self.driver.login_submit('email','fixture@example.test')
        self.assertEqual(len(self.calls),before)
        self.assertEqual(self.page.locator('input').input_value(),'')

    def test_existing_draft_and_duplicate_fields_require_browser_interaction(self):
        for inputs in ('<input type="email" value="existing@example.test">','<input type="email"><input type="email">'):
            self.open_form('<form>'+inputs+'<button>Continue</button></form>')
            before=self.page.locator('input').evaluate_all('(els)=>els.map(e=>e.value)')
            with self.assertRaises(ValueError):self.driver.login_submit('email','fixture@example.test')
            self.assertEqual(before,self.page.locator('input').evaluate_all('(els)=>els.map(e=>e.value)'))

    def test_challenge_and_unrecognized_controls_never_request_credentials(self):
        self.open_form('<h1>Verification required</h1>')
        self.page.evaluate("document.title='Just a moment...'")
        self.assertEqual(self.driver.login_stage(),'manual')
        with self.assertRaises(ValueError):self.driver.login_submit('code','123456')
        self.assertEqual(len(self.calls),1)

    def test_changed_form_and_get_transport_are_rejected_before_fill(self):
        self.open_form('<form method="POST" action="/auth/email"><input type="email"><button>Continue</button></form>')
        identity=self.driver.login_identity('email')
        self.page.locator('form').evaluate("form=>form.action='/different-operation'")
        with self.assertRaises(ValueError):self.driver.login_submit('email','fixture@example.test',identity)
        self.assertEqual(self.page.locator('input').input_value(),'')
        self.page.locator('form').evaluate("form=>form.method='GET'")
        with self.assertRaises(ValueError):self.driver.login_submit('email','fixture@example.test')
        self.assertEqual(self.page.locator('input').input_value(),'')
        self.assertEqual(len(self.calls),1)


if __name__=='__main__':unittest.main()
