import base64
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from tests import test_orchestrator_chat as fixtures
from tests.test_gemini import PNG
import orchestrator_chat as chat
import orchestrator_images as images
import production_control as pc
import gemini_runner


class Tests(unittest.TestCase):
    message=fixtures.Tests.message
    def setUp(self):
        fixtures.Tests.setUp(self)
        self.gemini_patch=patch('gemini.read_config',return_value={'api_key':'fixture','models':{'text':'test','image':'test-image'}});self.gemini_patch.start()
        self.root_patch=patch('backends.WORKSPACES',Path(self.temp.name).resolve()/'projects');self.root_patch.start()
        with self.state.db:
            self.state.put('orchestrator_mode',True)
            self.state.put('orchestrator_production_focus','an-old-video')
    def tearDown(self):
        self.root_patch.stop();self.gemini_patch.stop();fixtures.Tests.tearDown(self)

    def upload(self):
        message={'message_id':9,'chat':{'id':7,'type':'private'},'from':{'id':7},
                 'document':{'file_id':'drawing','file_name':'scribble.png','file_size':len(PNG)}}
        self.bridge.process({'update_id':9,'message':message})
        def download(fid,path,limit):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(PNG)
        self.telegram.download_file=download
        pc.Worker(self.state,telegram=self.telegram).download()
        return self.state.db.execute('SELECT * FROM production_uploads WHERE id=9').fetchone()

    def generate(self,ident=10):
        self.message('Can we make task relay logo based on this scribble drawing?',ident)
        action={'kind':'generate_image','reference_ids':[9]}
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Requested','action':action})).tick()
        return self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()

    def test_unfocused_upload_and_exact_logo_request_reach_native_image_input(self):
        upload=self.upload()
        self.assertEqual(upload['run'],images.UPLOAD_SCOPE)
        self.assertEqual(upload['status'],'ready')
        job=self.generate()
        self.assertEqual(job['status'],'answered')
        backend=self.state.db.execute('SELECT * FROM backend_jobs').fetchone()
        run=self.state.db.execute('SELECT * FROM gemini_runs').fetchone()
        self.assertEqual(run['capability'],'image')
        self.assertEqual(backend['prompt'],job['prompt'])
        refs=json.loads(run['options_json'])['references']
        self.assertEqual(len(refs),1)
        self.assertEqual(Path(refs[0]['path']).read_bytes(),PNG)
        request=gemini_runner.make_request(self.state,backend,run)
        self.assertIn(base64.b64encode(PNG).decode(),json.dumps(request))
        self.assertEqual(self.state.db.execute('SELECT status FROM production_uploads WHERE id=9').fetchone()[0],'used')
        self.assertTrue(self.state.get('orchestrator_mode'))
        self.bridge.flush(False)
        self.assertTrue(self.state.db.execute('SELECT 1 FROM messages WHERE thread_id=?',(backend['thread_id'],)).fetchone())
        with self.state.db:
            images.queue(self.state,job,[9])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)

    def test_failed_enqueue_rolls_back_task_reference_consumption_and_receipt(self):
        self.upload()
        with patch('backends.enqueue',side_effect=ValueError('quota fixture')):
            job=self.generate()
        self.assertEqual(job['status'],'failed')
        for table in ('backend_jobs','backend_tasks','orchestrator_image_requests','artifacts'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_uploads WHERE id=9').fetchone()[0],'ready')

    def test_selected_guide_text_reaches_image_worker(self):
        import routing_inputs
        self.upload()
        root=Path(self.temp.name).resolve();source=root/'image-guide.md'
        source.write_text('Use clean blue lines on white. No mockup or paper texture.')
        records=routing_inputs.capture(self.state,{'id':10},[(source,source.name,'project guide',str(root),None)],section='conversation-guides')
        with self.state.db:self.state.db.execute('INSERT INTO orchestrator_guide_choices VALUES (?,?,?,?,?,?,?)',(10,'image-guide-choice','selected',json.dumps(records),'[]','[0]',9999999999))
        self.assertEqual(self.generate()['status'],'answered')
        prompt=self.state.db.execute('SELECT prompt FROM backend_jobs').fetchone()[0]
        self.assertIn('No mockup or paper texture.',prompt)
        self.assertIn(records[0]['sha256'],prompt)

    def test_tampered_reference_cannot_queue_an_image_job(self):
        row=self.upload();p=Path(row['path']);p.chmod(0o600);p.write_bytes(b'changed')
        self.assertEqual(self.generate()['status'],'failed')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)

    def test_unavailable_or_foreign_reference_rejected(self):
        self.upload()
        snap=chat.snapshot(self.state,None)
        for refs in ([True],[777],[9,9]):
            with self.assertRaises(ValueError):chat.interpret(json.dumps({'answer':'x','action':{'kind':'generate_image','reference_ids':refs}}),snap)
        with self.state.db:self.state.db.execute("UPDATE production_uploads SET run='other-production' WHERE id=9")
        self.assertEqual(chat.snapshot(self.state,None)['uploaded_files'],[])
        self.assertEqual(self.generate()['status'],'failed')

    def test_capability_question_does_not_launch_image(self):
        self.upload();self.message('What can you do with uploaded images?',10)
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Generate an image from your references.','action':None})).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)
