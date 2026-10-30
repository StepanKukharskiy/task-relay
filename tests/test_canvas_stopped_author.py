"""Explicit fresh local authorship; synthetic transport, no live recovery."""
import copy,json,unittest,uuid
from unittest.mock import patch
from tests.test_same_canvas_rerun import SameCanvas
from task_relay import desktop_node_runs as runs,desktop_workspace as workspace
from tests import test_same_canvas_rerun as fixtures

class StoppedAuthor(unittest.TestCase):
    python_tools=False
    def setUp(self):
        SameCanvas.setUp(self)
        if self.python_tools:
            p=patch('task_relay.code_runtime.available',return_value={'id':'a'*64});p.start();self.addCleanup(p.stop)
            workflow=copy.deepcopy(self.saved['workflow']);workflow['tasks'][1]['model']['tools']='python'
            saved=fixtures.drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Python canvas',workflow=workflow))
            req=dict(id=saved['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
            checked=runs.preview(req);self.run=runs.start(dict(req,fingerprint=checked['fingerprint'],allow_paid=False))['run']
            for task in ('first','second'):
                self.rt.tick(self.run);self.factory.finish(self.rt.task(self.run,task)['latest']);self.rt.tick(self.run)
            self.attempt=self.rt.task(self.run,'second')['latest']
        self.canvas=self.run
        row=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.attempt,)).fetchone())
        frozen=json.loads(row['frozen'])
        self.assertEqual(frozen['tools'],['files','python'] if self.python_tools else ['files'])
        receipt=dict(status='uncertain',local_terminal=True,exit_code=-15,token=self.attempt,
            backend=frozen['backend'],pending_requests=['api-11'],external_outcome='unknown',reason='time_limit')
        with self.rt.db:
            self.rt.db.execute("UPDATE production_attempts SET state='uncertain',receipt=? WHERE id=?",(json.dumps(receipt),self.attempt))
            self.rt.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run=? AND id='second'",(self.run,))
        self.old=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.attempt,)).fetchone())
        rec=runs.read_canvas({'run':self.canvas});w=copy.deepcopy(rec['workflow']);w['tasks'][1]['objective']='Compact new authoring'
        runs.save_canvas(dict(run=self.canvas,revision=rec['revision'],title=rec['title'],workflow=w))
    def preview(self,scope='second'):
        rec=runs.read_canvas({'run':self.canvas})
        req=dict(canvas=self.canvas,revision=rec['revision'],scope=scope,values={},request_id=str(uuid.uuid4()))
        check=runs.preview(req)
        return dict(req,fingerprint=check['fingerprint'],allow_paid=False,acknowledge_uncertain=check['uncertain_attempts']),check
    def test_composed_explicit_version_keeps_unknown_and_limits(self):
        cmd,check=self.preview()
        self.assertEqual(check['uncertain_attempts'][0]['attempt'],self.attempt)
        self.assertEqual(check['plan']['tasks'][0]['limits'],json.loads(self.old['frozen'])['limits'])
        with self.assertRaisesRegex(ValueError,'Confirm a separate'):
            runs.start({k:v for k,v in cmd.items() if k!='acknowledge_uncertain'})
        count=len(self.factory.calls);new=runs.start(cmd)
        self.assertEqual(len(self.factory.calls),count)
        self.assertTrue(runs.start(cmd)['reused'])
        self.rt.tick(new['run']);aid=self.rt.task(new['run'],'second')['latest']
        self.assertNotEqual(aid,self.attempt)
        self.factory.finish(aid);self.rt.tick(new['run'])
        self.assertEqual(dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.attempt,)).fetchone()),self.old)
        node=next(t for t in workspace.detail(self.canvas,self.paths)['tasks'] if t['id']=='second')
        self.assertEqual([v['status'] for v in node['versions']],['uncertain','completed'])
        self.assertEqual(len(self.factory.calls),count+1)
    def test_active_broader_tools_and_other_scope_remain_blocked(self):
        for scope in ('all','first'):
            with self.assertRaisesRegex(ValueError,'uncertain'):self.preview(scope)
        for field,change in [('receipt',{'local_terminal':False}),('receipt',{'token':'different'}),
                             ('receipt',{'exit_code':None}),('frozen',{'tools':['files','web']}),
                             ('frozen',{'execution':{'capability':'blender.run_python'}})]:
            with self.subTest(field=field,change=change):
                changed=json.loads(self.old[field]);changed.update(change)
                with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET '+field+'=? WHERE id=?',(json.dumps(changed),self.attempt))
                with self.assertRaisesRegex(ValueError,'uncertain'):self.preview()
                with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET '+field+'=? WHERE id=?',(self.old[field],self.attempt))
    def test_changed_pending_request_invalidates_confirmation(self):
        cmd,_=self.preview();r=json.loads(self.old['receipt']);r['pending_requests'].append('api-12')
        with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(r),self.attempt))
        with self.assertRaisesRegex(ValueError,'Confirm a separate|configuration changed'):runs.start(cmd)
    def test_interruption_does_not_acknowledge_old_attempt(self):
        cmd,_=self.preview()
        with patch('task_relay.relay_channels.bind',side_effect=ValueError('interrupted')):
            with self.assertRaisesRegex(ValueError,'interrupted'):runs.start(cmd)
        self.assertEqual(runs.node_versions(self.rt.db,self.canvas,'second'),[])
        self.assertEqual(self.preview()[1]['uncertain_attempts'],cmd['acknowledge_uncertain'])


class StoppedPythonAuthor(StoppedAuthor):
    python_tools=True

    def test_unknown_local_effects_and_incomplete_receipts_remain_blocked(self):
        changes=[{'pending_requests':p} for p in (['code-01'],['work-operations/step'],['api-11','code-01'],['computer_actions'],None,'api-11',[11])]
        changes += [{'exit_code':False},{'backend':{}},{'operation':{'remote':'unknown'}}]
        for change in changes:
            with self.subTest(change=change):
                receipt=json.loads(self.old['receipt']);receipt.update(change)
                with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),self.attempt))
                with self.assertRaisesRegex(ValueError,'uncertain'):self.preview()
        with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(self.old['receipt'],self.attempt))

    def test_extra_authority_and_changed_worker_identity_remain_blocked(self):
        for change in ({'work_tools':{'version':1}},{'job_owner':{'version':1}},
                       {'worker':{'executor':'codex-agent','backend':json.loads(self.old['frozen'])['backend']}},
                       {'tools':['files','python','shell']}):
            with self.subTest(change=change):
                frozen=json.loads(self.old['frozen']);frozen.update(change)
                with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),self.attempt))
                with self.assertRaisesRegex(ValueError,'uncertain'):self.preview()
        with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(self.old['frozen'],self.attempt))

    def test_worker_inspection_distinguishes_unknown_model_reply_from_unfinished_python(self):
        from orchestrator.adapters import AgentFactory
        from orchestrator.workers import atomic
        frozen=json.loads(self.old['frozen']);control=self.root/'terminal-code-worker';control.mkdir()
        session=dict(id=self.attempt,control=str(control),backend=frozen['backend'])
        atomic(control/'done.json',dict(token=self.attempt,exit_code=-15,reason='time_limit'))
        atomic(control/'api-11.request.json',{'fixture':'model-response-unknown'})
        code=control/'code-01';code.mkdir();atomic(code/'intent.json',{'assignment':self.attempt})
        factory=AgentFactory();before={str(p):p.read_bytes() for p in control.rglob('*') if p.is_file()}
        receipt=factory.inspect(session)
        self.assertTrue(receipt['local_terminal']);self.assertIn('code-01',receipt['pending_requests'])
        self.assertFalse(runs.stopped_author_receipt(frozen,receipt,self.attempt))
        self.assertEqual(before,{str(p):p.read_bytes() for p in control.rglob('*') if p.is_file()})
        atomic(code/'outcome.json',dict(returncode=0,outputs={}))
        receipt=factory.inspect(session)
        self.assertEqual(receipt['pending_requests'],['api-11'])
        self.assertTrue(runs.stopped_author_receipt(frozen,receipt,self.attempt))
        with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),self.attempt))
        original=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.attempt,)).fetchone())
        files={str(p):p.read_bytes() for p in control.rglob('*') if p.is_file()}
        cmd,_=self.preview();calls=len(self.factory.calls);runs.start(cmd)
        self.assertTrue(runs.start(cmd)['reused']);self.assertEqual(len(self.factory.calls),calls)
        self.assertEqual(original,dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.attempt,)).fetchone()))
        self.assertEqual(files,{str(p):p.read_bytes() for p in control.rglob('*') if p.is_file()})
