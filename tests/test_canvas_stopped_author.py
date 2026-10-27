"""Explicit fresh file-only authorship; synthetic transport, no live recovery."""
import copy,json,unittest,uuid
from unittest.mock import patch
from tests.test_same_canvas_rerun import SameCanvas
from task_relay import desktop_node_runs as runs,desktop_workspace as workspace

class StoppedAuthor(unittest.TestCase):
    def setUp(self):
        SameCanvas.setUp(self)
        self.canvas=self.run
        row=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.attempt,)).fetchone())
        frozen=json.loads(row['frozen'])
        self.assertEqual(frozen['tools'],['files'])
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
