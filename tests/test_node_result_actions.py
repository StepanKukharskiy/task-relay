"""Exact baseline actions composed with existing canvas admission and Runtime."""
import copy,json,sqlite3,uuid,unittest
from unittest.mock import patch
from tests import test_canvas_node_run as canvas_tests
from tests.test_orchestrator import FakeFactory
from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts,desktop_node_files as files
from orchestrator.runtime import Runtime


class Results(unittest.TestCase):
    command=canvas_tests.Canvas.command
    def setUp(self):
        canvas_tests.Canvas.setUp(self)
        for p in (patch.object(files,'PATHS',self.paths),patch.object(files,'_database',runs._database)):
            p.start();self.addCleanup(p.stop)
        self.factory=FakeFactory()
        self.run=runs.start(self.command())['run']
        self.rt=Runtime(self.root/'orchestrator',self.factory);self.addCleanup(self.rt.close)
        self.rt.tick(self.run)
        self.first=self.rt.task(self.run,'write')['latest'];self.factory.finish(self.first);self.rt.tick(self.run)
        self.second=self.rt.task(self.run,'summary')['latest'];self.factory.finish(self.second);self.rt.tick(self.run)
        self.artifact=dict(self.rt.db.execute("SELECT * FROM production_artifacts WHERE attempt=?",(self.second,)).fetchone())
        self.original=[tuple(r) for r in self.rt.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))]

    def action(self,mode='edit'):
        a=self.artifact
        return dict(run=self.run,task='summary',attempt=self.second,mode=mode,request_id=str(uuid.uuid4()),
            artifact=a['id'] if mode!='edit' else None,sha256=a['sha256'] if mode!='edit' else None,
            operation=None,question='')

    def finish(self,run):
        self.rt.tick(run);a=self.rt.task(run,'answer' if 'answer' in [t['id'] for t in self.rt.status(run)['tasks']] else 'summary')['latest']
        self.factory.finish(a);self.rt.tick(run);return a

    def test_edit_inherits_executed_inputs_not_changed_draft_or_new_producer(self):
        changed=copy.deepcopy(self.w);changed['tasks'][1]['objective']='Wrong later draft'
        drafts.dispatch('node-draft-save',dict(id=self.saved['id'],revision=self.saved['revision'],title='Changed',workflow=changed))
        value=self.action();draft=runs.result_draft(value)
        self.assertEqual(draft,runs.result_draft(value))
        task=draft['workflow']['tasks'][0]
        self.assertEqual(task['objective'],'Summarize')
        self.assertEqual(task['model']['id'],'second')
        original=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(self.second,)).fetchone()[0])
        self.assertEqual(task['inputs']['article'],dict(artifact=original['inputs'][0]['artifact']))
        self.assertEqual(len(draft['workflow']['tasks']),1)
        req=dict(id=draft['id'],revision=draft['revision'],values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req);new=runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=True))
        self.finish(new['run'])
        self.assertEqual(len(self.factory.calls),3,'only selected node executes again')
        self.assertEqual(self.original,[tuple(r) for r in self.rt.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])

    def test_reuse_exact_output_and_chat_restart_followup_without_paid_calls(self):
        v=self.action('input');v['operation']='model'
        draft=runs.result_draft(v)
        self.assertEqual(draft['workflow']['tasks'][0]['inputs']['result'],{'artifact':self.artifact['id']})
        v=self.action('chat');v['question']='What does this contain?'
        first=runs.result_chat(v);self.assertTrue(runs.result_chat(v)['reused'])
        self.finish(first['run'])
        with runs._database() as db:turns=runs.result_chats(db,self.run)
        self.assertEqual(len(turns),1);self.assertTrue(turns[0]['answer']);self.assertEqual(turns[0]['status'],'completed')
        v2={**v,'request_id':str(uuid.uuid4()),'question':'Explain your previous answer briefly.'}
        second=runs.result_chat(v2);self.rt.tick(second['run'])
        attempt=self.rt.task(second['run'],'answer')['latest'];frozen=self.factory.sessions[attempt]['frozen']
        self.assertEqual(frozen['worker']['backend']['type'],'codex-agent')
        self.assertEqual({i['artifact'] for i in frozen['inputs']},{self.artifact['id'],turns[0]['answer_artifact']})
        self.factory.finish(attempt);self.rt.tick(second['run'])
        self.assertTrue(runs.result_chat(v2)['reused'])
        self.assertEqual(len(self.factory.calls),4)
        command=json.loads(self.rt.db.execute('SELECT command FROM desktop_node_runs WHERE run=?',(second['run'],)).fetchone()[0])
        self.assertFalse(command['allow_paid'])

    def test_wrong_version_foreign_output_uncertain_and_changed_identity_reject(self):
        v=self.action('chat');v['question']='Explain'
        with self.assertRaisesRegex(ValueError,'identity'):runs.result_draft({**v,'sha256':'wrong'})
        with self.assertRaisesRegex(ValueError,'identity'):runs.result_draft({**v,'attempt':self.first,'task':'write'})
        runs.result_draft(v)
        with self.assertRaisesRegex(ValueError,'identity'):runs.result_draft({**v,'question':'Different'})
        self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(self.second,));self.rt.db.commit()
        with self.assertRaisesRegex(ValueError,'uncertain'):runs.result_draft(self.action())

    def test_changed_bytes_fail_before_draft_or_run(self):
        from pathlib import Path
        Path(self.artifact['blob']).chmod(0o600);Path(self.artifact['blob']).write_text('tampered')
        v=self.action('chat');v['question']='Explain'
        with self.assertRaisesRegex(ValueError,'bytes changed'):runs.result_chat(v)
        self.assertFalse((self.root/'node-drafts'/(uuid.UUID(v['request_id']).hex+'.json')).exists())

    def test_completed_source_is_visible_but_only_new_node_runs_after_save_reload(self):
        v=self.action('input');v['operation']='model'
        draft=runs.result_draft(v)
        self.assertEqual(len(draft['completed_sources']),1)
        source=draft['completed_sources'][0]
        self.assertTrue(source['node']['reused_source'])
        self.assertEqual(source['node']['latest_attempt'],self.second)
        self.assertEqual(source['file']['sha256'],self.artifact['sha256'])
        workflow=copy.deepcopy(draft['workflow']);workflow['tasks'][0]['objective']='Use the saved result'
        saved=drafts.dispatch('node-draft-save',dict(id=draft['id'],revision=draft['revision'],title='Continuation',workflow=workflow))
        reopened=drafts.dispatch('node-draft',dict(id=draft['id']))
        self.assertEqual(reopened['completed_sources'],saved['completed_sources'])
        req=dict(id=draft['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req)
        self.assertEqual([t['id'] for t in checked['plan']['tasks']],['adjust'])
        self.assertEqual(checked['reused_nodes'],[source['node']['id']])
        command=dict(**req,fingerprint=checked['fingerprint'],allow_paid=False)
        run=runs.start(command)['run'];self.rt.tick(run)
        attempt=self.rt.task(run,'adjust')['latest']
        frozen=self.factory.sessions[attempt]['frozen']
        self.assertEqual(frozen['inputs'][0]['artifact'],self.artifact['id'])
        self.assertEqual(frozen['inputs'][0]['sha256'],self.artifact['sha256'])
        self.factory.finish(attempt);self.rt.tick(run)
        self.assertEqual(self.rt.status(run)['status'],'completed')
        self.assertTrue(runs.start(command)['reused'])
        self.assertEqual(len(self.factory.calls),3,'two original nodes plus only one continuation')
        self.assertEqual(self.original,[tuple(r) for r in self.rt.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])

    def test_continuation_rechecks_completed_source_before_admission(self):
        v=self.action('input');v['operation']='model';draft=runs.result_draft(v)
        req=dict(id=draft['id'],revision=draft['revision'],values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req)
        self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(self.second,));self.rt.db.commit()
        with self.assertRaisesRegex(ValueError,'completed'):
            runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=False))
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)

    def test_image_edit_and_image_input_keep_frozen_defaults_with_real_adapter(self):
        import base64,io
        from unittest.mock import MagicMock
        from task_relay import gemini
        from orchestrator.adapters import ExecutionFactory
        from tests.test_mixed_execution import LocalRegistered
        from tests.test_gemini import PNG,result
        client=gemini.Client('fixture');client.opener=MagicMock()
        client.opener.open.return_value.__enter__.side_effect=lambda:io.BytesIO(json.dumps(
            result([{'inlineData':{'mimeType':'image/png','data':base64.b64encode(PNG).decode()}}])).encode())
        document=dict(schema_version=1,kind='workflow',inputs={},tasks=[
            dict(schema_version=3,id='cup',operation='gemini.image',objective='Cup image',
                inputs={'prompt':{'value':'A red cup'},'model':{'value':'fixture-image'}})])
        d=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Image fixture',workflow=document))
        req=dict(id=d['id'],revision=d['revision'],values={},request_id=str(uuid.uuid4()))
        p=runs.preview(req);run=runs.start(dict(**req,fingerprint=p['fingerprint'],allow_paid=True))['run']
        rt=Runtime(self.root/'orchestrator',ExecutionFactory(self.factory,LocalRegistered(client)))
        self.addCleanup(rt.close)
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture'}):
            rt.tick(run);rt.tick(run)
        self.assertEqual(rt.status(run)['status'],'completed')
        a=rt.output(run,'cup','outputs/result.png')
        value=dict(run=run,task='cup',attempt=a['attempt'],mode='edit',request_id=str(uuid.uuid4()),
            artifact=None,sha256=None,operation=None,question='')
        edit=runs.result_draft(value)['workflow']['tasks'][0]
        self.assertEqual(edit['inputs']['max_output_tokens'],{'value':4096})
        self.assertEqual(edit['inputs']['aspect_ratio'],{'value':'1:1'})
        self.assertEqual(edit['inputs']['prompt'],{'value':'A red cup'})
        reused=runs.result_draft(dict(value,mode='input',request_id=str(uuid.uuid4()),artifact=a['id'],
            sha256=a['sha256'],operation='gemini.image'))
        reuse=reused['workflow']['tasks'][0]
        self.assertEqual(reuse['inputs']['files'],{'value':[{'artifact':a['id']}]})
        self.assertEqual(reuse['inputs']['model'],{'value':'fixture-image'})
        self.assertNotIn('prompt',reuse['inputs'],'new adjustment needs its own prompt')
        client.opener.open.assert_called_once()
        reuse['inputs']['prompt']={'value':'Make it blue'}
        saved=drafts.dispatch('node-draft-save',dict(id=reused['id'],revision=reused['revision'],title='Blue cup',workflow=reused['workflow']))
        req=dict(id=saved['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
        preview=runs.preview(req)
        self.assertEqual(len(preview['plan']['tasks']),1)
        self.assertEqual(preview['paid_nodes'],['adjust'])
        with self.assertRaisesRegex(ValueError,'Paid API'):
            runs.start(dict(**req,fingerprint=preview['fingerprint'],allow_paid=False))
        new=runs.start(dict(**req,fingerprint=preview['fingerprint'],allow_paid=True))['run']
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture'}):
            rt.tick(new);rt.tick(new)
        self.assertEqual(rt.status(new)['status'],'completed')
        self.assertEqual(client.opener.open.call_count,2,'one original fake call, one edit; no producer rerun')
        self.assertEqual(rt.db.execute('SELECT count(*) FROM production_attempts WHERE run=?',(run,)).fetchone()[0],1)
        latest=rt.task(new,'adjust')['latest']
        prompt=runs.save_node_prompt(dict(run=new,task='adjust',attempt=latest,prompt='Keep blue; use softer light'))
        request=dict(run=new,task='adjust',attempt=latest,revision=prompt['revision'],request_id=str(uuid.uuid4()))
        checked=runs.preview(request)
        self.assertEqual(checked['paid_nodes'],['adjust'])
        with self.assertRaisesRegex(ValueError,'Paid API'):
            runs.start(dict(**request,fingerprint=checked['fingerprint'],allow_paid=False))
        self.assertEqual(client.opener.open.call_count,2)
        version=runs.start(dict(**request,fingerprint=checked['fingerprint'],allow_paid=True))
        self.assertEqual(version['canvas_run'],new)
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture'}):
            rt.tick(version['run']);rt.tick(version['run'])
        self.assertEqual(rt.status(version['run'])['status'],'completed')
        self.assertEqual(client.opener.open.call_count,3)
        self.assertEqual(rt.db.execute('SELECT count(*) FROM production_attempts WHERE run=?',(new,)).fetchone()[0],1)
        # The imported producer is now an ordinary editable node in the same
        # canonical graph. Whole-workflow execution binds its NEW image output.
        document=runs.read_canvas({'run':new})
        first=document['workflow']['tasks'][0]
        first['inputs']['prompt']={'value':'A green cup'}
        document=runs.save_canvas(dict(run=new,revision=document['revision'],title=document['title'],workflow=document['workflow']))
        request=dict(canvas=new,revision=document['revision'],scope='all',values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(request)
        self.assertEqual(checked['paid_nodes'],[first['id'],'adjust'])
        self.assertEqual(len(checked['plan']['tasks']),2)
        with self.assertRaisesRegex(ValueError,'Paid API'):
            runs.start(dict(**request,fingerprint=checked['fingerprint'],allow_paid=False))
        self.assertEqual(client.opener.open.call_count,3)
        whole=runs.start(dict(**request,fingerprint=checked['fingerprint'],allow_paid=True))
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture'}):
            for _ in range(4):rt.tick(whole['run'])
        self.assertEqual(rt.status(whole['run'])['status'],'completed')
        self.assertEqual(client.opener.open.call_count,5)
        produced=rt.output(whole['run'],first['id'],'outputs/result.png')
        adjusted=rt.task(whole['run'],'adjust')
        frozen=json.loads(rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(adjusted['latest'],)).fetchone()[0])
        self.assertEqual(frozen['inputs'][0]['artifact'],produced['id'])
        self.assertNotEqual(produced['id'],a['id'])
        self.assertEqual(rt.output(run,'cup','outputs/result.png')['id'],a['id'])
