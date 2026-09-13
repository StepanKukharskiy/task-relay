"""Complete controlled CLI pipeline and browser command/option coverage gate."""
import argparse
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from orchestrator.browser_contract import definitions
from orchestrator.gemini_worker import Files
from task_relay.general_browser import browser,Session
from task_relay.browser_journal import Journal,UncertainAction
from tests.browser_pipeline_support import MODEL
from tests.test_general_browser import policy

ROOT=Path(__file__).resolve().parents[1]
COVERED={};TOOLS=set();KEYS=set();POLICY=set()


class Site(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/redirect-chain':
            self.send_response(302);self.send_header('Location','/redirect');self.end_headers();return
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location',getattr(self.server,'redirect_url','https://outside.invalid'));self.end_headers();return
        self.send_response(200)
        if self.path=='/login':self.send_header('Set-Cookie','fixture=connected; Path=/; Max-Age=3600')
        if self.path.startswith('/download'):
            self.send_header('Content-Disposition','attachment; filename=result.txt');self.end_headers()
            self.wfile.write(b'\xff\xfe' if self.path.endswith('binary') else b'controlled download');return
        self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
        if self.path.endswith('/result'):
            self.wfile.write(('Submitted once' if self.server.posts else 'No submission').encode());return
        cookie='connected' if 'fixture=connected' in self.headers.get('Cookie','') else 'anonymous'
        self.wfile.write(('''<!doctype html><title>Browser gate</title><body><p>Session: '''+cookie+'''</p>
          <form method="POST" action="'''+('/lost/submit' if self.path.startswith('/lost') else '/redirect-submit' if self.path=='/post-redirect' else '/submit')+'''">
          <label>Request<input name="request"></label><button>Submit</button></form>
          <label>Colour<select><option value="red">Red</option><option value="blue">Blue</option></select></label>
          <textarea aria-label="Notes"></textarea><input type="file" aria-label="Upload">
          <a href="/download">Download</a><a href="/download-binary">Binary download</a>
          <a href="/form">Next page</a><input aria-label="Password" type="password">
          <input aria-label="Code" autocomplete="one-time-code">
          <button type="button" onclick="alert('fixture alert')">Dialog</button></body>''').encode())
    def do_POST(self):
        self.server.posts.append(self.rfile.read(int(self.headers.get('Content-Length',0))).decode())
        if self.path.startswith('/lost'):
            self.send_response(302);self.send_header('Location',getattr(self.server,'redirect_url','https://outside.invalid'));self.end_headers()
        elif self.path=='/redirect-submit':
            self.send_response(303);self.send_header('Location','/result');self.end_headers()
        else:
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<body>Submitted once</body>')


@unittest.skipUnless(os.environ.get('TASK_RELAY_LOCAL_BROWSER_FIXTURE')=='1','Run scripts/test_browser_pipeline.py with the browser Python')
class Tests(unittest.TestCase):
    def setUp(self):
        output=os.environ.get('RELAY_BROWSER_PIPELINE_OUTPUT')
        self.temp=None if output else tempfile.TemporaryDirectory()
        self.root=Path(output or self.temp.name).resolve()/self._testMethodName;self.root.mkdir(parents=True)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Site);self.server.posts=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        hook=self.root/'hook';hook.mkdir()
        (hook/'sitecustomize.py').write_text('from tests.browser_pipeline_support import install\ninstall()\n')
        self.env={**os.environ,'RELAY_BROWSER_PIPELINE_FIXTURE':'1','RELAY_BROWSER_PIPELINE_URL':self.url,
          'PYTHONPATH':str(hook)+os.pathsep+str(ROOT),'TASK_RELAY_DATA_DIR':str(self.root/'data'),
          'TASK_RELAY_WORKSPACE_DIR':str(self.root/'workspaces'),'TASK_RELAY_GENERATED_DIR':str(self.root/'generated'),
          'TASK_RELAY_BROWSER_PYTHON':sys.executable}
        self.commands=[];self.request=self.root/'request.txt';self.request.write_text('Submit pipeline request once to the local fixture. Record the result without inventing acceptance.')

    def tearDown(self):
        (self.root/'commands.json').write_text(json.dumps(self.commands,indent=2))
        self.server.shutdown();self.server.server_close();self.thread.join()
        if self.temp:self.temp.cleanup()

    def cli(self,*args,expect=0,input=None,env=None,module='task_relay'):
        argv=[sys.executable,'-m',module,*map(str,args)]
        r=subprocess.run(argv,cwd=ROOT,env=env or self.env,input=input,text=True,capture_output=True,timeout=45)
        index=len(self.commands);(self.root/f'command-{index:02d}.log').write_text(r.stdout+r.stderr)
        self.commands.append({'argv':argv,'returncode':r.returncode,'expected':expect,'log':f'command-{index:02d}.log'})
        self.assertEqual(r.returncode,expect,r.stdout+r.stderr)
        self.assertNotIn('Traceback (most recent call last)',r.stderr)
        if args[:1]==('browser',) and '--help' not in args:
            prefix='general' if args[1:2]==('general',) else 'perplexity';offset=2 if prefix=='general' else 1
            COVERED.setdefault(prefix+'.'+str(args[offset]),set()).update(str(x) for x in args[offset+1:] if str(x).startswith('--'))
        return r.stdout

    def value(self,text):
        decoder=json.JSONDecoder()
        for i,char in enumerate(text):
            if char not in '{[':continue
            try:value,end=decoder.raw_decode(text[i:])
            except ValueError:continue
            if not text[i+end:].strip():return value
        self.fail('No complete final JSON output: '+text[-1000:])

    def prepare(self,ident='pipeline',root=None):
        plan=self.root/(ident+'.json')
        args=['browser','general','prepare','--profile','fixture','--origin',self.url,
              '--origin','https://outside.invalid','--interaction-scope','Submit the local fixture request once',
              '--request-file',self.request,'--id',ident,'--model',MODEL,'--out',plan]
        if root:args+=['--root',root]
        self.cli(*args)
        return plan

    def test_cli_complete_pipeline_login_prepare_create_run_review_export(self):
        self.cli('browser','general','login','--profile','fixture','--url',self.url+'/login','--origin',self.url,input='\n')
        observed=self.value(self.cli('browser','general','inspect','--profile','fixture','--url',self.url+'/form','--origin',self.url))
        self.assertIn('Session: connected',observed['text'])
        root=self.root/'separate-runtime';plan=self.prepare(root=root)
        self.cli('verify-gemini',module='orchestrator.executors')
        self.cli('orchestrator','--root',root,'create',plan)
        first=self.value(self.cli('orchestrator','--root',root,'status','pipeline'));self.assertEqual(len(first['attempts']),0)
        result=self.value(self.cli('orchestrator','--root',root,'run','pipeline','--seconds','30'))
        self.assertEqual(result['status'],'completed',json.dumps(result))
        self.assertEqual(self.server.posts,['request=pipeline+request'])
        self.assertEqual(len(result['attempts']),2)
        self.cli('orchestrator','--root',root,'events','pipeline')
        self.cli('orchestrator','--root',root,'export','pipeline','produce',self.root/'export')
        self.assertTrue(list((self.root/'export').rglob('report.md')))
        receipts=self.value(self.cli('browser','general','status','--profile','fixture','--job',result['attempts'][0]['id']))
        self.assertTrue(receipts['actions']);self.assertFalse(receipts['unresolved'])
        self.cli('orchestrator','--root',root,'tick','pipeline')
        self.assertEqual(len(self.server.posts),1)
        for attempt in result['attempts']:
            receipt=json.loads(attempt['receipt']);self.assertTrue(receipt['usage'])
            self.assertFalse(receipt['browser']['uncertain_actions'])

    def test_read_navigation_blocks_reachable_redirect_before_contact_and_can_continue(self):
        visits=[]
        class Outside(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                visits.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'Outside policy')
        outside=ThreadingHTTPServer(('127.0.0.1',0),Outside)
        thread=threading.Thread(target=outside.serve_forever,daemon=True);thread.start()
        self.server.redirect_url='http://127.0.0.1:'+str(outside.server_port)+'/consent'
        scope=policy(origins=[self.url],interaction_scope='')
        try:
            with closing(sqlite3.connect(self.root/'redirect.sqlite')) as db,browser(self.root,scope,headless=True) as driver:
                session=Session(db,'redirect-job',scope,driver)
                args={'url':self.url+'/redirect-chain'}
                result=session.call('open','browser_open',args)
                self.assertEqual(result['outcome'],'blocked');self.assertEqual(result['blocked_navigation']['url'],self.server.redirect_url)
                self.assertEqual(visits,[]);self.assertFalse(session.journal.pending(scope['profile']))
                self.assertEqual(session.call('open','browser_open',args),result)
                page=session.call('alternative','browser_navigate',{'tab':result['tab'],'url':self.url+'/form'})
                self.assertIn('Session:',page['text']);self.assertEqual(visits,[])
                # A permitted redirect remains navigable; no blanket redirect ban.
                self.server.redirect_url=self.url+'/form'
                page=session.call('allowed','browser_navigate',{'tab':result['tab'],'url':self.url+'/redirect-chain'})
                self.assertEqual(page['url'],self.url+'/form');self.assertEqual(visits,[])
                # A POST followed by an allowed GET redirect is submitted once.
                scope['interaction_scope']='Submit the two local regression forms once each'
                page=session.call('post-form','browser_navigate',{'tab':result['tab'],'url':self.url+'/post-redirect'})
                page=session.call('post','browser_click',self.target(page,label='Submit'))
                self.assertIn('Submitted once',page['text']);self.assertEqual(len(self.server.posts),1)
                # A POST followed by a forbidden redirect stays uncertain, but
                # the reachable outside server must still receive no request.
                self.server.redirect_url='http://127.0.0.1:'+str(outside.server_port)+'/consent'
                page=session.call('lost-form','browser_navigate',{'tab':result['tab'],'url':self.url+'/lost'})
                args=self.target(page,label='Submit')
                with self.assertRaises(UncertainAction):session.call('lost-post','browser_click',args)
                with self.assertRaises(UncertainAction):session.call('lost-post','browser_click',args)
                self.assertEqual(len(self.server.posts),2);self.assertEqual(visits,[])
        finally:outside.shutdown();outside.server_close();thread.join()

    def test_cli_uncertain_result_inspect_resolve_cancel_without_resubmit(self):
        plan=self.prepare('lost')
        value=json.loads(plan.read_text())
        for task in value['tasks']:task['browser']['origins']=[self.url]
        plan.write_text(json.dumps(value))
        self.cli('verify-gemini',module='orchestrator.executors')
        self.cli('orchestrator','create',plan)
        env={**self.env,'RELAY_BROWSER_PIPELINE_URL':self.url+'/lost'}
        result=self.value(self.cli('orchestrator','run','lost','--seconds','30',env=env))
        self.assertEqual(result['status'],'uncertain');self.assertEqual(len(self.server.posts),1)
        state=self.value(self.cli('browser','general','status','--profile','fixture'))
        pending=state['unresolved'][0]
        self.cli('browser','general','inspect','--profile','fixture','--url',self.url+'/result')
        self.cli('browser','general','resolve','--profile','fixture','--job',pending['job'],'--action-id',pending['id'],
                 '--outcome','occurred','--note','Fixture server recorded exactly one POST')
        self.cli('orchestrator','cancel','lost')
        self.assertEqual(len(self.server.posts),1)
        # Simulate the other crash window: intent committed, no dispatch.
        with closing(sqlite3.connect(self.root/'data/state.sqlite')) as db:
            Journal(db).claim('fixture','before-send','intent','browser_click',{},20,True)
        self.cli('browser','general','resolve','--profile','fixture','--job','before-send','--action-id','intent',
                 '--outcome','not_occurred','--note','Fault injected before any driver call')

    def test_cli_errors_return_failure_and_preserve_prepared_files(self):
        plan=self.prepare()
        original=plan.read_bytes()
        self.cli('browser','general','prepare','--profile','fixture','--origin',self.url,'--request-file',self.request,
                 '--id','again','--model',MODEL,'--out',plan,expect=2)
        self.assertEqual(plan.read_bytes(),original)
        self.cli('browser','status','missing',expect=2)
        self.cli('browser','general','inspect','--profile','fixture','--url',self.url+'/redirect',expect=2)
        self.cli('browser','general','resolve','--profile','fixture','--job','none','--action-id','none',
                 '--outcome','occurred','--note','No matching action',expect=2)
        self.cli('browser','general','login','--profile','fixture','--url',self.url+'/login',input='',expect=2)

    def test_perplexity_all_commands_and_continuation_options(self):
        self.cli('browser','login',input='\n')
        output=self.value(self.cli('browser','send','--receipt','first','--prompt-file',self.request))
        self.assertEqual(output['status'],'completed');url=output['url']
        self.cli('browser','status','first')
        follow=self.root/'follow.txt';follow.write_text('Fixture follow-up')
        result=self.value(self.cli('browser','send','--receipt','second','--prompt-file',follow,'--url',url))
        self.assertEqual(result['status'],'completed')
        # Retain real prior baseline and observed page; inject lost completion receipt.
        with closing(sqlite3.connect(self.root/'data/state.sqlite')) as db:
            db.execute("UPDATE browser_jobs SET status='uncertain' WHERE id='second'");db.commit()
        self.assertEqual(self.value(self.cli('browser','reconcile','second','--url',url))['status'],'completed')
        self.cli('browser','reconcile','second')
        self.assertEqual(self.value(self.cli('browser','send','--receipt','second','--prompt-file',follow,'--url',url))['status'],'completed')

    def session(self,driver,scope,job='tools'):
        ws=self.root/'files';ws.mkdir(exist_ok=True);(ws/'input.txt').write_text('upload evidence')
        frozen=dict(workspace=str(ws),assignment_id=job,inputs=[dict(path='input.txt',sha256=hashlib.sha256(b'upload evidence').hexdigest())],
                    outputs=[dict(path='download.txt')],limits={'output_bytes':200000})
        self.db=sqlite3.connect(self.root/'tools.sqlite');self.addCleanup(self.db.close)
        POLICY.update(scope)
        return Session(self.db,job,scope,driver,Files(frozen))

    def call(self,session,name,args):
        ident='action-'+str(len(TOOLS))+'-'+str(self.db.execute('SELECT count(*) FROM general_browser_actions').fetchone()[0])
        result=session.call(ident,'browser_'+name,args);TOOLS.add('browser_'+name)
        if name=='press':KEYS.add(args['key'])
        return result

    def target(self,page,**attrs):
        entry=next(x for x in page['controls'] if all(x.get(k)==v for k,v in attrs.items()))
        return dict(tab=page['tab'],observation=page['observation'],ref=entry['ref'],purpose='Exercise the controlled fixture')

    def test_real_browser_all_tools_options_and_dialog(self):
        scope=policy(origins=[self.url],uploads=['input.txt'],downloads=['download.txt'],max_tabs=2,max_actions=60)
        with browser(self.root,scope,headless=True) as driver:
            session=self.session(driver,scope)
            try:
                page=self.call(session,'open',{'url':self.url+'/form'})
                other=self.call(session,'open',{'url':self.url+'/form'})
                self.assertEqual(len(self.call(session,'tabs',{})['tabs']),2)
                page=self.call(session,'read',{'tab':page['tab']})
                selector=next(x for x in page['controls'] if x['tag']=='SELECT')
                self.assertIn({'value':'blue','label':'Blue'},selector.get('options',[]),'The model cannot select options that observations omit')
                page=self.call(session,'select',{**self.target(page,tag='SELECT'),'value':'blue'})
                self.assertEqual(driver.page(page['tab']).locator('select').input_value(),'blue')
                page=self.call(session,'fill',{**self.target(page,tag='TEXTAREA'),'text':'Notes'})
                for key in ('Tab','Escape','ArrowDown','ArrowUp','Enter'):
                    page=self.call(session,'press',{**self.target(page,tag='TEXTAREA'),'key':key})
                page=self.call(session,'upload',{**self.target(page,type='file'),'path':'input.txt'})
                self.assertEqual(driver.page(page['tab']).locator('[type=file]').evaluate('el=>el.files[0].name'),'input.txt')
                page=self.call(session,'download',{**self.target(page,label='Download'),'path':'download.txt'})
                self.assertEqual((self.root/'files/download.txt').read_text(),'controlled download')
                page=self.call(session,'click',self.target(page,label='Dialog'))
                self.assertEqual(page['dialogs_dismissed'][-1]['message'],'fixture alert')
                page=self.call(session,'wait',{'tab':page['tab'],'seconds':0})
                page=self.call(session,'click',self.target(page,label='Next page'))
                page=self.call(session,'navigate',{'tab':page['tab'],'url':self.url+'/form'})
                self.call(session,'close',{'tab':other['tab']})
                self.assertEqual(len(driver.pages),1)
            except BaseException:
                for i,p in enumerate(driver.pages.values()):
                    if not p.is_closed():p.screenshot(path=str(self.root/f'failure-{i}.png'))
                raise

    def test_real_browser_stale_draft_and_negative_scope_boundaries(self):
        scope=policy(origins=[self.url],max_tabs=1,max_actions=60,uploads=['input.txt'],downloads=['download.txt'])
        with browser(self.root,scope,headless=True) as driver:
            session=self.session(driver,scope,'boundaries');page=self.call(session,'open',{'url':self.url+'/form'})
            with self.assertRaisesRegex(ValueError,'Tab budget'):session.call('extra','browser_open',{'url':self.url})
            page=self.call(session,'fill',{**self.target(page,tag='INPUT',type=''),'text':'original draft'})
            driver.page(page['tab']).locator('input[name=request]').fill('Changed by a human')
            with self.assertRaisesRegex(ValueError,'changed'):session.call('stale','browser_click',self.target(page,label='Submit'))
            page=self.call(session,'read',{'tab':page['tab']})
            for selector in ('[type=password]','[autocomplete=one-time-code]'):
                driver.page(page['tab']).locator(selector).fill('fixture-private-value')
            page=self.call(session,'read',{'tab':page['tab']})
            for entry in page['controls']:
                if entry['label'] in ('Password','Code'):
                    self.assertNotIn('value',entry);self.assertNotIn('value_sha256',entry);self.assertNotIn('_value',entry)
            for label in ('Password','Code'):
                with self.assertRaisesRegex(ValueError,'Credentials'):session.call('secret','browser_fill',{**self.target(page,label=label),'text':'never entered'})
            with self.assertRaisesRegex(ValueError,'Existing'):session.call('draft','browser_fill',{**self.target(page,tag='INPUT',type=''),'text':'overwrite'})
            with self.assertRaisesRegex(ValueError,'0–5'):session.call('wait','browser_wait',{'tab':page['tab'],'seconds':6})
            with self.assertRaisesRegex(ValueError,'key'):session.call('key','browser_press',{**self.target(page,tag='TEXTAREA'),'key':'Control+L'})
            with self.assertRaisesRegex(ValueError,'grant'):session.call('file','browser_upload',{**self.target(page,type='file'),'path':'other.txt'})
            session.policy['interaction_scope']=''
            with self.assertRaisesRegex(ValueError,'reading'):session.call('read-only','browser_click',self.target(page,label='Submit'))
            session.policy['interaction_scope']='Fixture transfer'
            with self.assertRaises(UncertainAction):session.call('binary','browser_download',{**self.target(page,label='Binary download'),'path':'download.txt'})
            self.assertFalse((self.root/'files/download.txt').exists());self.assertFalse(self.server.posts)

    def test_z_surface_coverage_requires_every_exposed_command_option_and_tool(self):
        from task_relay import browser_cli,perplexity_browser
        expected={}
        class Captured(Exception):pass
        for prefix,module in [('general',browser_cli),('perplexity',perplexity_browser)]:
            parsers=[]
            def capture(parser,*args,**kwargs):parsers.append(parser);raise Captured()
            with patch.object(argparse.ArgumentParser,'parse_args',capture):
                with self.assertRaises(Captured):module.main([])
            sub=next(a for a in parsers[0]._actions if isinstance(a,argparse._SubParsersAction))
            for name,p in sub.choices.items():
                expected[prefix+'.'+name]={flag for a in p._actions for flag in a.option_strings if flag not in ('-h','--help')}
        missing={name:sorted(flags-COVERED.get(name,set())) for name,flags in expected.items() if name not in COVERED or flags-COVERED.get(name,set())}
        report={'cli':{k:sorted(v) for k,v in COVERED.items()},'missing_cli':missing,'tools':sorted(TOOLS),
                'missing_tools':sorted({d['name'] for d in definitions()}-TOOLS),'keys':sorted(KEYS),'policy_fields':sorted(POLICY)}
        (self.root.parent/'coverage.json').write_text(json.dumps(report,indent=2))
        self.assertFalse(missing,report);self.assertFalse(report['missing_tools'],report)
        self.assertEqual(KEYS,{'Enter','Tab','Escape','ArrowDown','ArrowUp'})
        self.assertEqual(POLICY,{'profile','origins','interaction_scope','max_tabs','max_actions','uploads','downloads'})


if __name__=='__main__':unittest.main()
