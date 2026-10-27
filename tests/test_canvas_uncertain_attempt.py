"""Explicit new API versions; scripted transport only, never paid calls."""
import base64,copy,json,unittest,uuid
from unittest.mock import patch
from pathlib import Path
from tests.test_same_canvas_rerun import SameCanvas
from tests.test_mixed_execution import Client,LocalRegistered
from tests.test_gemini import PNG,result
from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts,desktop_workspace as workspace,gemini
from orchestrator.adapters import ExecutionFactory

class NewAttempt(unittest.TestCase):
    def setUp(self):
        SameCanvas.setUp(self)
        self.available=patch('orchestrator.execution.available');self.available.start();self.addCleanup(self.available.stop)
        self.config=patch.object(gemini,'read_config',return_value={'api_key':'fixture'});self.config.start();self.addCleanup(self.config.stop)
        self.client=Client();self.client.error=gemini.ProviderError('connection-or-response',uncertain=True,detail={'failure_kind':'timeout','exception_type':'TimeoutError'})
        self.ops=LocalRegistered(self.client);self.rt.factory=ExecutionFactory(self.factory,self.ops)
        node=dict(schema_version=3,id='image',operation='gemini.image',objective='Cup',inputs=dict(prompt={'value':'Original red cup'},model={'value':'gemini-3.1-flash-image'}))
        saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Image canvas',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[node])))
        req=dict(id=saved['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
        check=runs.preview(req);self.canvas=runs.start(dict(req,fingerprint=check['fingerprint'],allow_paid=True))['run']
        self.rt.tick(self.canvas);self.rt.tick(self.canvas)
        self.aid=self.rt.task(self.canvas,'image')['latest']
        self.old=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.aid,)).fetchone())
        self.control=Path(json.loads(self.old['session'])['control'])
        self.files={str(p):p.read_bytes() for p in self.control.rglob('*') if p.is_file()}
        self.assertEqual(self.old['state'],'uncertain')
        record=runs.read_canvas({'run':self.canvas});w=copy.deepcopy(record['workflow']);w['tasks'][0]['inputs']['prompt']={'value':'Edited blue cup'}
        self.saved=runs.save_canvas(dict(run=self.canvas,revision=record['revision'],title=record['title'],workflow=w))

    def preview(self,scope='image'):
        r=runs.read_canvas({'run':self.canvas})
        req=dict(canvas=self.canvas,revision=r['revision'],scope=scope,values={},request_id=str(uuid.uuid4()))
        check=runs.preview(req)
        cmd=dict(req,fingerprint=check['fingerprint'],allow_paid=True,acknowledge_uncertain=check['uncertain_attempts'])
        return cmd,check

    def test_explicit_paid_version_preserves_uncertain_history_and_exact_retry(self):
        cmd,check=self.preview()
        self.assertEqual(check['uncertain_attempts'][0]['attempt'],self.aid)
        self.assertEqual(check['plan']['tasks'][0]['execution']['parameters']['prompt'],'Edited blue cup')
        self.assertEqual(check['plan']['tasks'][0]['limits'],json.loads(self.old['frozen'])['limits'])
        self.assertEqual(check['plan']['tasks'][0]['max_attempts'],1)
        self.assertTrue(workspace.detail(self.canvas,self.paths)['tasks'][0]['can_start_new_attempt'])
        with self.assertRaisesRegex(ValueError,'Confirm a separate'):
            runs.start({k:v for k,v in cmd.items() if k!='acknowledge_uncertain'})
        with self.assertRaisesRegex(ValueError,'Paid API'):
            runs.start(dict(cmd,allow_paid=False))
        self.assertEqual(len(self.client.calls),1)
        receipt=runs.start(cmd);self.assertTrue(runs.start(cmd)['reused'])
        with self.assertRaisesRegex(ValueError,'running or uncertain'):self.preview()
        self.assertEqual(len(self.client.calls),1,'admission never dispatches')
        self.client.error=None
        response=result([{'inlineData':{'mimeType':'image/png','data':base64.b64encode(PNG).decode()}}])
        def success(path,payload,**bounds):self.client.calls.append(payload);return response
        self.client.request=success
        self.rt.tick(receipt['run']);self.rt.tick(receipt['run'])
        view=workspace.detail(self.canvas,self.paths);node=view['tasks'][0]
        self.assertEqual(node['status'],'completed')
        self.assertEqual([v['status'] for v in node['versions']],['uncertain','completed'])
        self.assertEqual([v['prompt'] for v in node['versions']],['Original red cup','Edited blue cup'])
        self.assertEqual(dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(self.aid,)).fetchone()),self.old)
        self.assertEqual({str(p):p.read_bytes() for p in self.control.rglob('*') if p.is_file()},self.files)
        self.assertEqual(len(self.client.calls),2)
        again,check=self.preview();self.assertEqual(check['uncertain_attempts'],[],'historical unknown remains in history, not a new authorization requirement')
        self.assertTrue(runs.start(cmd)['reused']);self.assertEqual(len(self.client.calls),2)

    def test_exact_uncertainty_and_prompt_bound_to_confirmation(self):
        cmd,_=self.preview()
        row=json.loads(self.old['receipt']);row['reason']='New information'
        with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(row),self.aid))
        with self.assertRaisesRegex(ValueError,'Confirm a separate|configuration changed'):runs.start(cmd)
        self.assertEqual(len(self.client.calls),1)

    def test_running_unknown_and_workflow_scope_stay_blocked(self):
        with self.assertRaisesRegex(ValueError,'uncertain'):self.preview('all')
        row=json.loads(self.old['receipt']);row.pop('local_terminal')
        with self.rt.db:self.rt.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(row),self.aid))
        with self.assertRaisesRegex(ValueError,'uncertain'):self.preview()
        self.assertFalse(workspace.detail(self.canvas,self.paths)['tasks'][0]['can_start_new_attempt'])
        self.assertEqual(len(self.client.calls),1)

    def test_authorization_rolls_back_with_admission(self):
        cmd,_=self.preview()
        with patch('task_relay.relay_channels.bind',side_effect=ValueError('interrupted')):
            with self.assertRaisesRegex(ValueError,'interrupted'):runs.start(cmd)
        self.assertEqual(runs.node_versions(self.rt.db,self.canvas,'image'),[])
        self.assertEqual(self.preview()[1]['uncertain_attempts'],cmd['acknowledge_uncertain'])
        r=runs.start(cmd);self.assertTrue(runs.start(cmd)['reused']);self.assertEqual(len(self.client.calls),1)
