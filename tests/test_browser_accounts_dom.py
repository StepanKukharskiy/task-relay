"""Real local CDP browser; no public websites, accounts, or live messages."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest

from task_relay import browser_sites as sites,host_browser_accounts as host
from task_relay.general_browser import browser,Session,NavigationBlocked
from tests.test_general_browser import policy


class Site(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','http://localhost:'+str(self.server.server_port)+'/unapproved');self.end_headers();return
        self.send_response(200)
        if self.path=='/auth':self.send_header('Set-Cookie','fixture=signed-in; Path=/')
        self.send_header('Content-Type','text/html');self.end_headers()
        content=('<input type="password" value="fixture-secret">' if self.path=='/login' else
                 '<p>Signed in</p>' if 'fixture=signed-in' in self.headers.get('Cookie','') else '<p>Anonymous</p>')
        self.wfile.write(('<title>Fixture</title><body>'+content+'</body>').encode())


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOCAL_BROWSER_FIXTURE')=='1','Run with the local browser fixture flag')
class Tests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Site)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        with sync_playwright() as p:
            executable=p.chromium.executable_path
            p.request.new_context().dispose()
        self.process=subprocess.Popen([executable,'--headless=new','--no-sandbox','--remote-debugging-port=0',
            '--user-data-dir='+str(self.root/'chrome'),'--no-first-run','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        portfile=self.root/'chrome/DevToolsActivePort'
        deadline=time.monotonic()+15
        while not portfile.exists() and time.monotonic()<deadline:time.sleep(.1)
        self.endpoint=host.resolve_endpoint('http://127.0.0.1:'+portfile.read_text().splitlines()[0])
        with sync_playwright() as p:
            remote=host.attach(p,self.endpoint)
            remote.contexts[0].pages[0].goto(self.url+'/auth')
            remote.close()
        self.data=self.root/'data';self.data.mkdir()
        with closing(sqlite3.connect(self.data/'state.sqlite')) as db:
            sites.set_source(db,self.endpoint)
            revision=db.execute('SELECT revision FROM browser_account_source').fetchone()[0]
            with db:db.execute('INSERT INTO browser_sites VALUES(?,?,?,?)',(self.url,'confirmed_by_user',revision,time.time()))
        self.scope=policy(profile='accounts',origins=[self.url],interaction_scope='')

    def tearDown(self):
        self.process.terminate();self.process.wait(timeout=10)
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def user_pages(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            remote=host.attach(p,self.endpoint)
            result=[page.url for page in remote.contexts[0].pages]
            remote.close()
            return result

    def test_existing_session_cookie_reused_and_unrelated_tab_survives(self):
        before=self.user_pages()
        with browser(self.data,self.scope,headless=True) as driver:
            driver.open('task',self.url+'/work')
            raw,_=driver.snapshot('task')
            self.assertIn('Signed in',raw['text'])
            self.assertEqual(len(driver.context.pages),len(before)+1)
            # A user tab opened while attached is never closed by Relay's tab limit.
            personal=driver.context.new_page();personal.goto(self.url+'/personal')
        self.assertCountEqual(self.user_pages(),before+[self.url+'/personal'])
        self.assertIsNone(self.process.poll())

    def test_unknown_redirect_is_blocked_without_expanding_site_list(self):
        with browser(self.data,self.scope,headless=True) as driver:
            with self.assertRaises(NavigationBlocked):driver.open('task',self.url+'/redirect')
        with closing(sqlite3.connect(self.data/'state.sqlite')) as db:
            self.assertEqual(len(sites.catalog(db)),1)
        self.assertEqual(self.user_pages(),[self.url+'/auth'])

    def test_login_form_invalidates_saved_confirmation_without_exposing_value(self):
        with closing(sqlite3.connect(self.data/'state.sqlite')) as db:
            with browser(self.data,self.scope,headless=True) as driver:
                session=Session(db,'login-check',self.scope,driver)
                result=session.call('open','browser_open',{'url':self.url+'/login'})
                self.assertEqual(result['outcome'],'manual_verification_required')
                self.assertNotIn('fixture-secret',str(result))
            self.assertEqual(sites.catalog(db)[0]['status'],'needs_verification')
            self.assertNotIn('fixture-secret','\n'.join(db.iterdump()))
        self.assertEqual(self.user_pages(),[self.url+'/auth'])

    def test_removed_site_stops_existing_driver_before_further_observation(self):
        with browser(self.data,self.scope,headless=True) as driver:
            driver.open('task',self.url+'/work');driver.snapshot('task')
            with closing(sqlite3.connect(self.data/'state.sqlite')) as db,db:
                db.execute("UPDATE browser_sites SET status='removed'")
            with self.assertRaises(sites.VerificationRequired):driver.snapshot('task')


if __name__=='__main__':unittest.main()
