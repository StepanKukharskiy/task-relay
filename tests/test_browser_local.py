"""Opt-in local Chromium fixture; no external websites, accounts or model calls."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from orchestrator import contracts as c,executors
from orchestrator.browser_worker import run
from orchestrator.gemini_worker import Files
from orchestrator.workers import atomic
from task_relay.general_browser import browser,Session
from task_relay.browser_journal import UncertainAction
from tests.test_browser_executor import ScriptedBrowser
from tests.test_general_browser import browser_graph,policy
from tests.test_gemini_executor import CONFIG


class Page(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','https://outside.invalid/');self.end_headers();return
        if self.path=='/download':
            self.send_response(200);self.send_header('Content-Disposition','attachment; filename=fixture.txt')
            self.end_headers();self.wfile.write(b'Fixture download');return
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
        self.wfile.write(b'''<title>Local browser fixture</title><body><h1>Fixture</h1>
          <form method="POST"><label>Request<input name="request"></label><button>Submit</button></form>
          <label>Upload<input type="file"></label><a href="/download" download>Download</a></body>''')
    def do_POST(self):
        self.server.submissions.append(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
        self.wfile.write(b'<title>Result</title><body><h1>Submitted once</h1></body>')


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOCAL_BROWSER_FIXTURE')=='1','Explicit local Chromium fixture opt-in required')
class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Page);self.server.submissions=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.scope=policy(origins=[self.origin])
        self.db=sqlite3.connect(self.root/'state.sqlite')
    def tearDown(self):
        self.db.close();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def target(self,page,**match):
        control=next(x for x in page['controls'] if all(x.get(k)==v for k,v in match.items()))
        return dict(tab=page['tab'],observation=page['observation'],ref=control['ref'],purpose='Perform the requested local fixture operation')

    def test_scripted_model_completes_real_form_with_one_submission(self):
        workspace=self.root/'workspace';(workspace/'.relay').mkdir(parents=True);control=self.root/'control';control.mkdir()
        frozen=c.assignment(browser_graph()['tasks'][0]);frozen.update(assignment_id='fixture',workspace=str(workspace),backend=browser_graph()['backend'])
        frozen['browser']=self.scope
        atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(CONFIG,frozen['backend'])})
        result=run(frozen,control,self.db,self.root,client=ScriptedBrowser(frozen),config_reader=lambda:(CONFIG,frozen['backend']),
                   driver_context=browser(self.root,self.scope,headless=True))
        self.assertEqual(result['decision'],'delivered');self.assertEqual(self.server.submissions,[b'request=Fixture+request'])
        action=json.loads(self.db.execute("SELECT result FROM general_browser_actions WHERE id='call-03-00'").fetchone()[0])
        self.assertIn('Submitted once',action['text']);self.assertEqual(action['remote_outcome'],'not_independently_verified')
        self.assertTrue((workspace/'output.txt').exists())

    def test_multiple_tabs_text_transfers_and_outside_redirect(self):
        workspace=self.root/'workspace';workspace.mkdir();(workspace/'source.txt').write_text('Fixture upload')
        frozen=dict(workspace=str(workspace),assignment_id='transfers',inputs=[{'path':'source.txt','sha256':hashlib.sha256(b'Fixture upload').hexdigest()}],
                    outputs=[{'path':'download.txt'}],limits=executors.GEMINI_LIMITS.copy())
        files=Files(frozen);scope={**self.scope,'uploads':['source.txt'],'downloads':['download.txt']}
        with browser(self.root,scope,headless=True) as driver:
            session=Session(self.db,'transfers',scope,driver,files)
            page=session.call('open','browser_open',{'url':self.origin+'/form'})
            other=session.call('other','browser_open',{'url':self.origin+'/other'})
            self.assertNotEqual(page['tab'],other['tab'])
            page=session.call('upload','browser_upload',{**self.target(page,type='file'),'path':'source.txt'})
            chosen=driver.page(page['tab']).locator('input[type=file]').evaluate('el => el.files[0].name')
            self.assertEqual(chosen,'source.txt')
            session.call('download','browser_download',{**self.target(page,tag='A'),'path':'download.txt'})
            self.assertEqual((workspace/'download.txt').read_text(),'Fixture download')
            self.assertEqual(driver.page(other['tab']).url,self.origin+'/other')
            result=session.call('redirect','browser_navigate',{'tab':other['tab'],'url':self.origin+'/redirect'})
            self.assertEqual(result['outcome'],'blocked')
            self.assertFalse(session.journal.pending(scope['profile']))
            self.assertFalse(self.server.submissions)


if __name__=='__main__':unittest.main()
