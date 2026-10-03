"""Controlled routing/transport fixtures: no live video generation or rendering."""
import base64
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from task_relay import gemini, gemini_runner, orchestrator_chat as chat
from task_relay import orchestrator_images as media, orchestrator_context, relay_channels
from tests import test_orchestrator_images as image_fixtures
from tests.test_gemini import PNG


class Tests(unittest.TestCase):
    setUp = image_fixtures.Tests.setUp
    tearDown = image_fixtures.Tests.tearDown
    message = image_fixtures.Tests.message
    upload = image_fixtures.Tests.upload
    production_image = image_fixtures.Tests.production_image

    def generate(self, text='use gemini to generate video with my image', refs=None, artifacts=None, ident=10, channel=None):
        self.message(text,ident)
        if channel:
            with self.state.db:
                self.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
        action=dict(kind='generate_video',provider='gemini',reference_ids=[9] if refs is None else refs,
                    artifact_ids=artifacts or [])
        chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Requested',action=action))).tick()
        return self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()

    def queued(self):
        return (self.state.db.execute('SELECT * FROM backend_jobs').fetchone(),
                self.state.db.execute('SELECT * FROM gemini_runs').fetchone())

    def test_exact_first_frame_prompt_model_and_delivery_are_bound_once(self):
        upload=self.upload()
        job=self.generate(text='/video Animate this image with a slow camera move.')
        self.assertEqual(job['status'],'answered',job['answer'])
        backend,run=self.queued()
        self.assertEqual(backend['prompt'],job['prompt'])
        self.assertEqual((run['capability'],run['model']),('video',gemini.DEFAULT_MODELS['video']))
        refs=json.loads(run['options_json'])['references']
        self.assertEqual(refs[0]['sha256'],upload['sha256'])
        payload=gemini_runner.make_request(self.state,backend,run)
        self.assertEqual(payload['instances'],[dict(prompt=job['prompt'],image=dict(
            bytesBase64Encoded=base64.b64encode(PNG).decode(),mimeType='image/png'))])
        self.assertEqual(self.state.db.execute('SELECT status FROM production_uploads WHERE id=9').fetchone()[0],'used')
        self.bridge.flush(False)
        self.assertTrue(self.state.db.execute('SELECT 1 FROM messages WHERE thread_id=?',(backend['thread_id'],)).fetchone())
        with self.state.db:
            media.queue(self.state,job,[9],capability='video')
            media.queue(self.state,job,[9])  # Same orchestration request cannot change media kind on replay.
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)

    def test_enqueue_failure_rolls_back_all_media_state(self):
        self.upload()
        with patch('task_relay.backends.enqueue',side_effect=ValueError('fixture enqueue failure')):
            row=self.generate()
        self.assertEqual(row['status'],'failed')
        for table in ('backend_jobs','backend_tasks','orchestrator_video_requests','artifacts','capability_dispatches'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_uploads WHERE id=9').fetchone()[0],'ready')

    def test_changed_upload_blocks_before_queue(self):
        row=self.upload();path=Path(row['path']);path.chmod(0o600);path.write_bytes(b'changed')
        self.assertEqual(self.generate()['status'],'failed')
        self.assertIsNone(self.queued()[0])

    def test_changed_first_frame_blocks_before_provider_submission(self):
        self.upload();self.generate();backend,run=self.queued()
        ref=json.loads(run['options_json'])['references'][0]
        path=Path(ref['path']);path.chmod(0o600);path.write_bytes(b'changed')
        with self.state.db:self.state.db.execute("UPDATE backend_jobs SET status='running'")
        client=Mock();gemini_runner.run_job(self.state,backend['id'],client=client)
        client.request.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0],'failed')
        self.assertEqual(self.state.db.execute('SELECT attempts FROM gemini_runs').fetchone()[0],0)

    def test_exact_production_artifact_can_be_first_frame(self):
        artifact=self.production_image()
        row=self.generate(refs=[],artifacts=[artifact['id']])
        self.assertEqual(row['status'],'answered',row['answer'])
        receipt=self.state.get('video-artifact-inputs:10')[0]
        self.assertEqual((receipt['artifact_id'],receipt['attempt']),(artifact['id'],artifact['attempt']))
        backend,run=self.queued()
        self.assertEqual(gemini_runner.make_request(self.state,backend,run)['instances'][0]['image']['mimeType'],'image/png')

    def test_no_silent_extra_reference_or_provider_drop(self):
        self.upload();snap=chat.snapshot(self.state,None)
        snap['uploaded_files'].append(dict(id=11,status='ready'))
        base=dict(kind='generate_video',reference_ids=[9],artifact_ids=[],provider='gemini')
        for changes in (dict(reference_ids=[9,11]),dict(reference_ids=[True]),dict(reference_ids=[999]),dict(provider='runway')):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                media.validate_selection({**base,**changes},snap)
        snap['capabilities']['model_defaults']['video']={'provider':'runway'}
        action={k:v for k,v in base.items() if k!='provider'}
        with self.assertRaises(ValueError):media.validate_selection(action,snap)
        media.validate_selection(base,snap)  # Explicit Gemini selection overrides another default.

    def test_non_image_reference_is_not_silently_ignored(self):
        row=self.upload();path=Path(row['path']);path.chmod(0o600);path.write_bytes(b'guide text')
        from orchestrator.runtime import file_hash
        with self.state.db:self.state.db.execute('UPDATE production_uploads SET filename=?,bytes=?,sha256=? WHERE id=9',
                                                ('guide.txt',path.stat().st_size,file_hash(path)))
        job=self.generate()
        self.assertEqual(job['status'],'failed')
        self.assertIsNone(self.queued()[0])

    def test_text_only_video_and_frozen_model(self):
        with patch('task_relay.gemini.read_config',return_value={'api_key':'fixture','models':{'text':'test','video':'veo-fixture'}}):
            row=self.generate('Use Gemini to generate a moving cloud.',refs=[])
        self.assertEqual(row['status'],'answered',row['answer'])
        backend,run=self.queued()
        self.assertEqual(run['model'],'veo-fixture')
        self.assertNotIn('image',gemini_runner.make_request(self.state,backend,run)['instances'][0])

    def test_unavailable_config_has_no_dispatch(self):
        self.upload()
        with patch('task_relay.gemini.read_config',return_value=None):
            self.assertFalse(chat.snapshot(self.state,None)['capabilities']['gemini_video']['available'])
            self.assertEqual(self.generate()['status'],'failed')
        self.assertIsNone(self.queued()[0])

    def test_discovery_survives_compaction_and_unqualified_local_renderer(self):
        from tests.test_orchestrator_context import ContextTests
        from task_relay.capabilities import gemini_video, local_video
        payload=ContextTests().payload()
        payload['snapshot']['capabilities']={'graph_operations':[],'gemini_video':gemini_video(),'local_video':local_video([])}
        availability=orchestrator_context.overview(payload)['current_execution_availability']
        self.assertTrue(availability['gemini_video']['available'])
        self.assertFalse(availability['local_video']['available'])

    def test_messages_request_notice_and_completion_stay_in_messages(self):
        artifact=self.production_image()
        row=self.generate(channel='messages',refs=[],artifacts=[artifact['id']])
        self.assertEqual(row['status'],'answered',row['answer'])
        backend,_=self.queued()
        with self.state.db:
            self.state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)',('video-fixture-complete',backend['thread_id'],'Complete'))
        for event in ('video-request:10','video-fixture-complete'):
            self.assertEqual(relay_channels.event_channel(self.state,event),'messages')
        self.assertFalse(any(r['id']=='video-request:10' for r in relay_channels.pending(self.state,'telegram')))

    def test_status_question_never_queues_video(self):
        self.upload();self.message('Can Gemini make a video? What is its status?',10)
        chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Configured; access checked when used.',action=None))).tick()
        self.assertIsNone(self.queued()[0])

    def test_uncertain_submission_is_not_repeated(self):
        self.upload();self.generate();backend,_=self.queued()
        with self.state.db:self.state.db.execute("UPDATE backend_jobs SET status='running'")
        client=Mock();client.request.side_effect=gemini.ProviderError('connection',uncertain=True)
        gemini_runner.run_job(self.state,backend['id'],client=client)
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0],'uncertain')
        with self.state.db:self.state.db.execute("UPDATE backend_jobs SET status='running'")
        gemini_runner.run_job(self.state,backend['id'],client=client)
        self.assertEqual(client.request.call_count,1)
        self.assertEqual(self.state.db.execute('SELECT attempts FROM gemini_runs').fetchone()[0],1)

    def test_saved_video_operation_recovers_without_reading_or_resending_image(self):
        self.upload();self.generate();backend,run=self.queued()
        operation='models/veo-fixture/operations/saved'
        gemini.atomic_bytes(Path(run['response_path']),json.dumps({'name':operation}).encode())
        ref=json.loads(run['options_json'])['references'][0]
        path=Path(ref['path']);path.chmod(0o600);path.write_bytes(b'changed after submission')
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running'")
            self.state.db.execute("UPDATE gemini_runs SET stage='sending',attempts=1")
        client=Mock()
        client.request.return_value={'done':True,'response':{'generateVideoResponse':{'generatedSamples':[
            {'video':{'uri':'https://generativelanguage.googleapis.com/v1beta/files/video:download'}}]}}}
        client.download.side_effect=lambda url,path:gemini.atomic_bytes(path,b'\x00\x00\x00\x18ftypisomfixture')
        with patch.object(gemini,'GENERATED',Path(self.temp.name)/'generated'):
            gemini_runner.run_job(self.state,backend['id'],client=client,sleep=lambda _:None)
        client.request.assert_called_once_with(operation)
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0],'completed')
        self.assertEqual(self.state.db.execute('SELECT kind FROM media_outbox').fetchone()[0],'video')

    def test_reported_photo_caption_binds_exact_bytes_once(self):
        from tests.test_attachment_batches import Tests as BatchFixtures, PHOTO
        caption='do me a video from this image using /video'
        BatchFixtures.upload(self,100,caption,album=None)
        BatchFixtures.download(self,1)
        BatchFixtures.finish(self)
        calls=[]
        def generate(job,payload):
            calls.append(payload)
            self.assertEqual(payload['snapshot']['current_attachment_ids'],[100])
            return json.dumps(dict(answer='Requested',action=dict(kind='generate_video',provider='gemini',
                reference_ids=[100],artifact_ids=[])))
        chat.Worker(self.state,generate).tick()
        backend,run=self.queued()
        self.assertIsNotNone(backend)
        self.assertTrue(backend['prompt'].startswith(caption))
        first=gemini_runner.make_request(self.state,backend,run)['instances'][0]['image']
        self.assertEqual(first,dict(bytesBase64Encoded=base64.b64encode(PHOTO).decode(),mimeType='image/jpeg'))
        BatchFixtures.finish(self);chat.Worker(self.state,generate).tick()
        self.assertEqual(len(calls),1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)
