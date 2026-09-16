"""Exact uploaded sources survive planning and independent worker handoff."""
import json
from pathlib import Path
import unittest

from tests import test_production_planning as fixtures
from tests.test_gemini import PNG
from tests import test_orchestrator_images as image_fixtures
from task_relay import production_planning as planning, production_control as pc, routing_inputs
from orchestrator import worker_capabilities


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    start=fixtures.Tests.start
    click=fixtures.Tests.click
    upload=image_fixtures.Tests.upload

    def test_photo_reaches_author_and_reviewer_unchanged(self):
        upload=self.upload()
        row=self.queue(action=self.action(reference_ids=[9]),text='Model this image in Rhino.')
        payload=json.loads(row['context']);source=next(s for s in payload['sources'] if s.get('upload_id')==9)
        self.assertEqual(source['media_type'],'image/png')
        self.assertTrue(source['visual_reference'])
        self.assertIn(source['artifact'],payload['required_artifacts'])
        planning.Worker(self.state,lambda *_:(json.dumps(self.response()),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.start(row)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        first=self.rt.task('production-1','produce')['latest']
        self.factory.finish(first);worker.tick()
        self.assertEqual(len(self.factory.sessions),2)
        for session in self.factory.sessions.values():
            refs=[i for i in session['frozen']['inputs'] if i.get('visual_reference')]
            self.assertEqual(len(refs),1)
            self.assertEqual(refs[0]['sha256'],upload['sha256'])
            self.assertEqual((Path(session['workspace'])/refs[0]['path']).read_bytes(),PNG)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_uploads WHERE id=9').fetchone()[0],'ready')

    def test_omitted_selection_requests_bounded_correction_and_empty_excludes(self):
        self.upload()
        snap={'uploaded_files':[{'id':9,'status':'ready'}]}
        with self.assertRaises(routing_inputs.MissingSourceSelection) as error:
            planning.validate_action(self.action(),snap)
        self.assertEqual(error.exception.fields,['reference_ids'])
        row=self.queue(action=self.action(reference_ids=[]))
        self.assertFalse(any(s.get('upload_id') for s in json.loads(row['context'])['sources']))

    def test_invalid_or_other_scope_uploads_rejected(self):
        self.upload()
        for ids in ([9,9],[10],[True]):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                routing_inputs.freeze_uploads(self.state,{'id':42,'focus':None},ids)
        with self.state.db:self.state.db.execute("UPDATE production_uploads SET run='other' WHERE id=9")
        with self.assertRaises(ValueError):routing_inputs.freeze_uploads(self.state,{'id':42,'focus':None},[9])

    def test_tampered_upload_cannot_queue(self):
        upload=self.upload();p=Path(upload['path']);p.chmod(0o600);p.write_bytes(b'changed')
        self.request(self.action(reference_ids=[9]),'Model this image.',1)
        self.assertIsNone(self.row())

    def test_native_document_not_limited_by_image_provider_formats(self):
        upload=self.upload()
        folder=Path(upload['path']).parent;p=folder/'reference.3dm';p.write_bytes(b'native model fixture')
        from orchestrator.runtime import file_hash
        with self.state.db:self.state.db.execute('UPDATE production_uploads SET filename=?,path=?,bytes=?,sha256=? WHERE id=9',(p.name,str(p),p.stat().st_size,file_hash(p)))
        row=self.queue(action=self.action(reference_ids=[9]))
        s=next(s for s in json.loads(row['context'])['sources'] if s.get('upload_id'))
        self.assertFalse(s.get('visual_reference'));self.assertEqual(s['sha256'],file_hash(p))

    def test_binary_code_access_does_not_claim_image_understanding(self):
        from tests.test_orchestrator import task,pair
        code={'type':'gemini-code','model':'test','runtime':'a'*64}
        t=task();t['inputs']=[{'path':'photo.png','visual_reference':True}];t['worker']={'requires':['files.text']}
        catalog=[worker_capabilities.entry(b) for b in (code,pair()['backend'])]
        worker_capabilities.resolve(t,catalog,pair()['backend'])
        self.assertEqual(t['worker']['backend']['type'],'codex-cli')
        t['worker']={'requires':['files.text'],'executor':'gemini-code'}
        with self.assertRaisesRegex(ValueError,'No eligible'):worker_capabilities.resolve(t,catalog,pair()['backend'])

    def test_recovery_preserves_original_request_and_failure_and_is_idempotent(self):
        self.upload()
        row=self.queue(action=self.action(reference_ids=[]),text='Model this exact uploaded image in Rhino.')
        with self.state.db:
            self.state.db.execute("UPDATE production_plans SET status='needs_input',result=? WHERE id=?",(json.dumps({'decision':'needs_input','message':'Image missing'}),row['id']))
        original=dict(self.row())
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            ident,receipt=planning.recover_uploaded_sources(self.state,row['id'],[9])
        self.assertEqual(dict(self.row()),original)
        new=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        self.assertEqual(new['request'],original['request']);self.assertEqual(new['status'],'queued')
        self.assertIsNone(new['run']);self.assertEqual(new['parent_id'],original['id'])
        context=json.loads(new['context']);photo=next(s for s in context['sources'] if s.get('upload_id')==9)
        self.assertIn(photo['artifact'],context['required_artifacts'])
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            self.assertEqual(planning.recover_uploaded_sources(self.state,row['id'],[9]),(ident,receipt))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)

    def test_parent_clarification_retains_exact_photo_without_reupload(self):
        self.upload()
        row=self.queue(action=self.action(reference_ids=[9]))
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='needs_input' WHERE id=?",(row['id'],))
        child=self.queue(2,self.action(reference_ids=[],parent_id=row['id']),text='Use a height of three metres.')
        a=next(s for s in json.loads(row['context'])['sources'] if s.get('upload_id')==9)
        b=next(s for s in json.loads(child['context'])['sources'] if s.get('upload_id')==9)
        self.assertEqual(a,b)

    def test_routing_correction_adds_photo_before_any_planning_dispatch(self):
        from task_relay import orchestrator_chat as chat
        self.upload();original=self.action();responses=iter([original,{**original,'reference_ids':[9]}])
        self.bridge.process({'update_id':1,'message':{'text':'/orchestrator Model this image in Rhino.', 'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        calls=[]
        def provider(*args):
            calls.append(args)
            return json.dumps({'answer':'Plan requested','action':next(responses)})
        chat.Worker(self.state,provider).tick()
        self.assertEqual(len(calls),2)
        row=self.row();self.assertIsNotNone(row)
        self.assertEqual(row['status'],'queued')
        self.assertEqual(json.loads(row['options'])['reference_ids'],[9])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_pending_and_corrupted_image_rejected(self):
        upload=self.upload()
        with self.state.db:self.state.db.execute("UPDATE production_uploads SET status='pending' WHERE id=9")
        with self.assertRaises(ValueError):routing_inputs.freeze_uploads(self.state,{'id':42,'focus':None},[9])
        p=Path(upload['path']);p.chmod(0o600);p.write_bytes(b'not image bytes')
        from orchestrator.runtime import file_hash
        with self.state.db:self.state.db.execute("UPDATE production_uploads SET status='ready',sha256=?,bytes=? WHERE id=9",(file_hash(p),p.stat().st_size))
        with self.assertRaisesRegex(ValueError,'image bytes'):routing_inputs.freeze_uploads(self.state,{'id':42,'focus':None},[9])
