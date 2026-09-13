"""Controlled media graph and reply tests; no paid calls or native app launches."""
import base64
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from orchestrator import execution
from tests import test_mixed_execution as mixed
from tests import test_orchestrator_images as images
from tests.test_gemini import PNG, result
from tests.test_orchestrator import plan, task
import orchestrator_chat as chat
import gemini_runner
import routing_inputs


class GraphTests(unittest.TestCase):
    setUp=mixed.Tests.setUp
    tearDown=mixed.Tests.tearDown
    input=mixed.Tests.input

    def image_step(self, provider='gemini', inputs=None):
        cap=provider+'.image'
        params={'model':'test-image','max_output_tokens':128,'aspect_ratio':'16:9'} if provider=='gemini' else {
            'model':'gpt-image-2','size':'1024x1024','quality':'low'}
        return dict(id='photo',role='api',objective='Photograph from exact model preview',instruction='Make one architectural photo.',
            inputs=inputs or [self.input()],outputs=[{'path':'tower-photo.png','purpose':'Photoreal candidate','media_type':'image/png'}],
            criteria=copy.deepcopy(execution.REGISTRY[cap]['criteria']),
            execution={'capability':cap,'version':1,'parameters':params},user_gate='Select photo')

    def respond(self, provider='gemini'):
        payload=result([{'inlineData':{'mimeType':'image/png','data':base64.b64encode(PNG).decode()}}]) if provider=='gemini' else {
            'data':[{'b64_json':base64.b64encode(PNG).decode()}],'usage':{'total_tokens':42}}
        def request(path,body,**bounds):
            self.client.calls.append({'path':path,'payload':body})
            if self.client.error:raise self.client.error
            return payload
        self.client.request=request

    def test_model_preview_to_photo_dependency_and_independent_review(self):
        self.respond()
        produce=task('model')
        produce['outputs']=[{'path':'tower-preview.png','purpose':'Native render fixture','media_type':'image/png'}]
        source=dict(from_task='model',output='tower-preview.png',path='references/tower.png',purpose='Exact model view',authority='Candidate',media_type='image/png')
        photo=self.image_step(inputs=[source]);photo['dependencies']=['model']
        reviewer=task('review',dependencies=['photo'],review_of='photo',inputs=[dict(from_task='photo',output='tower-photo.png',path='photo.png',purpose='Check fidelity',authority='Candidate',media_type='image/png')])
        reviewer['criteria']=photo['criteria'].copy()
        self.rt.create(plan([produce,photo,reviewer]));self.rt.tick('demo')
        aid=self.rt.task('demo','model')['latest'];self.agent.finish(aid)
        ws=self.agent.sessions[aid]['workspace'];(ws/'tower-preview.png').write_bytes(PNG)
        for _ in range(4):self.rt.tick('demo')
        rid=self.rt.task('demo','review')['latest'];self.assertIsNotNone(rid)
        self.agent.finish(rid,decision='accept');self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')
        self.assertEqual(len(self.client.calls),1)
        encoded=self.client.calls[0]['payload']['contents'][0]['parts']
        self.assertEqual(base64.b64decode(encoded[-1]['inlineData']['data']),PNG)
        output=self.rt.output('demo','photo','tower-photo.png')
        self.assertTrue(Path(output['blob']).read_bytes().startswith(b'\x89PNG'))
        self.rt.tick('demo');self.assertEqual(len(self.client.calls),1)

    def test_openai_image_edit_uses_selected_provider_and_records_usage(self):
        self.respond('openai')
        path=self.root/'reference.png';path.write_bytes(PNG)
        aid=self.rt.register(path,'Selected preview',path='reference.png')
        image=dict(artifact=aid,path='reference.png',purpose='Model preview',authority='User source',media_type='image/png')
        with patch('task_relay.api_providers.read_config',return_value={'api_key':'fixture','models':{'image':'gpt-image-2'}}):
            self.rt.create(plan([self.image_step('openai',[image])]))
            self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')
        call=self.client.calls[0];self.assertEqual(call['path'],'images/edits')
        self.assertEqual(call['payload']['model'],'gpt-image-2')
        self.assertTrue(call['payload']['images'][0]['image_url'].endswith(base64.b64encode(PNG).decode()))
        self.assertEqual(len(self.client.calls),1)
        import sqlite3
        from task_relay import usage_tracker
        ledger=sqlite3.connect(':memory:');ledger.row_factory=sqlite3.Row
        try:
            usage_tracker.initialize(ledger)
            source=self.rt.db.execute('PRAGMA database_list').fetchone()[2]
            usage_tracker.collect_relay(ledger,Path(source))
            row=ledger.execute("SELECT provider,model,json_extract(counts,'$.total_tokens') FROM usage_events").fetchone()
            self.assertEqual(tuple(row),('openai','gpt-image-2',42))
        finally:ledger.close()

    def test_openrouter_image_uses_shared_graph_contract_and_retains_exact_reference(self):
        self.respond('openrouter')
        item=self.image_step();item['execution']={'capability':'openrouter.image','version':1,'parameters':{'model':'vendor/image-model','aspect_ratio':'16:9'}}
        source=self.root/'reference.png';source.write_bytes(PNG)
        aid=self.rt.register(source,'Exact reference',path='reference.png')
        item['inputs']=[dict(artifact=aid,path='reference.png',purpose='Exact reference',authority='User source',media_type='image/png')]
        with patch('task_relay.api_providers.read_config',return_value={'api_key':'fixture','models':{'image':'vendor/image-model'}}):
            self.rt.create(plan([item]));self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(len(self.client.calls),1)
        call=self.client.calls[0];self.assertEqual(call['path'],'images')
        self.assertEqual(call['payload']['provider'],{'allow_fallbacks':False})
        self.assertEqual(base64.b64decode(call['payload']['input_references'][0]['image_url']['url'].split(',')[1]),PNG)
        self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')

    def test_openrouter_transport_is_bounded_and_no_provider_fallback(self):
        from task_relay import api_providers as api
        from unittest.mock import MagicMock
        import io
        client=api.Client('openrouter','fixture')
        client.opener=MagicMock();client.opener.open.return_value.__enter__.return_value=io.BytesIO(b'{"data":[]}')
        client.request('images',{'model':'vendor/image','prompt':'Test','provider':{'allow_fallbacks':False}})
        call=client.opener.open.call_args
        self.assertEqual(call.args[0].full_url,'https://openrouter.ai/api/v1/images')
        self.assertEqual(call.kwargs['timeout'],300)
        with patch.object(api,'Client') as factory:
            factory.return_value.request.return_value={'data':[{'id':'vendor/text','architecture':{'output_modalities':['text']}},
                {'id':'vendor/image','architecture':{'output_modalities':['image']}}]}
            self.assertEqual(api.image_catalog('openrouter','fixture'),['vendor/image'])
            factory.return_value.request.assert_called_once_with('images/models')

    def test_ambiguous_image_submission_is_not_retried(self):
        import gemini
        self.respond();self.client.error=gemini.ProviderError('connection',uncertain=True)
        self.rt.create(plan([self.image_step()]))
        for _ in range(4):self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'uncertain')
        self.assertEqual(len(self.client.calls),1)

    def test_text_model_does_not_enable_openai_image_capability(self):
        with patch('task_relay.api_providers.read_config',return_value={'api_key':'fixture','model':'text-only'}):
            entry=next(x for x in execution.catalog() if x['id']=='openai.image')
        self.assertFalse(entry['available'])

    def test_missing_image_decoder_blocks_before_claim_or_provider_call(self):
        self.respond();self.rt.create(plan([self.image_step()]))
        with patch('orchestrator.execution.importlib.util.find_spec',return_value=None):
            self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'blocked')
        self.assertEqual(self.rt.status('demo')['attempts'],[])
        self.assertEqual(self.client.calls,[])

    def test_openai_image_transport_uses_bounded_json_edit_endpoint(self):
        from task_relay.api_providers import Client
        from unittest.mock import MagicMock
        client=Client('openai','fixture')
        response=MagicMock();response.read.return_value=json.dumps({'data':[{'b64_json':base64.b64encode(PNG).decode()}]}).encode()
        client.opener=MagicMock();client.opener.open.return_value.__enter__.return_value=response
        body={'model':'gpt-image-2','prompt':'Edit the exact reference','images':[{'image_url':'data:image/png;base64,'+base64.b64encode(PNG).decode()}]}
        client.request('images/edits',body)
        request=client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.openai.com/v1/images/edits')
        self.assertEqual(json.loads(request.data),body)
        self.assertEqual(response.read.call_args.args[0],70000001)
        other=Client('openrouter','fixture')
        with self.assertRaises(ValueError):other.request('images/edits',body)


class ReplyTests(unittest.TestCase):
    def setUp(self):
        images.Tests.setUp(self)
        self.state.media_dir=self.state.media_dir.resolve()
    tearDown=images.Tests.tearDown
    upload=images.Tests.upload
    generate=images.Tests.generate
    message=images.Tests.message

    def generated(self):
        self.upload();self.generate()
        job=self.state.db.execute('SELECT * FROM backend_jobs').fetchone()
        from unittest.mock import Mock
        client=Mock();client.request.return_value=result([{'inlineData':{'mimeType':'image/png','data':base64.b64encode(PNG).decode()}}])
        root=Path(self.temp.name).resolve()/'generated'
        with patch('gemini.GENERATED',root):
            with self.state.db:self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?",(job['id'],))
            gemini_runner.run_job(self.state,job['id'],client=client)
        self.bridge.flush()
        message=self.state.db.execute('SELECT message_id FROM messages WHERE thread_id=? ORDER BY message_id DESC LIMIT 1',(job['thread_id'],)).fetchone()[0]
        return job,message,root

    def test_rhino_reply_is_interpreted_with_exact_media_context_and_no_image_call(self):
        job,mid,root=self.generated()
        self.message('Use Rhino to make this drawing',20,reply=mid)
        captured=[]
        def decide(*args):
            captured.append(args[-1])
            return json.dumps({'answer':'A native Rhino model needs a bounded preparation stage. What dimensions should it use?','action':None})
        chat.Worker(self.state,decide).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=20').fetchone()[0],'answered')
        self.assertIn('media_reply',json.dumps(captured))
        self.assertIn(job['thread_id'],json.dumps(captured))
        self.assertIn('Use Rhino to make this drawing',json.dumps(captured))
        catalog=routing_inputs.artifact_catalog(self.state)
        media=next(a for a in catalog if a['run']==job['thread_id'])
        with patch('gemini.GENERATED',root):
            frozen=routing_inputs.freeze_artifacts(self.state,{'id':21},[media['id']])
            self.assertEqual(Path(frozen[0]['path']).read_bytes(),PNG)
            original=self.state.db.execute("SELECT path FROM artifacts WHERE role='output'").fetchone()[0]
            Path(original).write_bytes(b'changed')
            with self.assertRaises(ValueError):routing_inputs.freeze_artifacts(self.state,{'id':22},[media['id']])

    def test_image_edit_decision_keeps_same_task_history_and_no_duplicate_reference(self):
        job,mid,root=self.generated()
        self.message('Keep everything; change only the weather',20,reply=mid)
        media=next(a for a in routing_inputs.artifact_catalog(self.state) if a['run']==job['thread_id'])
        action={'kind':'generate_image','reference_ids':[],'artifact_ids':[media['id']]}
        with patch('gemini.GENERATED',root):
            chat.Worker(self.state,lambda *_:json.dumps({'answer':'Edit the selected image','action':action})).tick()
        follow=self.state.db.execute('SELECT * FROM backend_jobs ORDER BY created_at DESC LIMIT 1').fetchone()
        self.assertEqual(follow['thread_id'],job['thread_id'])
        self.assertEqual(follow['prompt'],'Keep everything; change only the weather')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM gemini_history').fetchone()[0],1)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM artifacts WHERE role='input'").fetchone()[0],1)

    def test_selected_media_is_frozen_into_rhino_planning_without_launching_a_worker(self):
        job,mid,root=self.generated()
        with self.state.db:self.state.put('production-planner-policy',{'backend':{'type':'codex-cli','model':'fixed-model','reasoning':'high'}})
        self.message('Use Rhino to make this drawing',20,reply=mid)
        media=next(a for a in routing_inputs.artifact_catalog(self.state) if a['run']==job['thread_id'])
        action={'kind':'plan_production','template':'custom','project':None,'reference_pack_id':None,
            'research_ids':[],'artifact_ids':[media['id']],'planning_only':False,'step_capabilities':['rhino.run_python']}
        with patch('gemini.GENERATED',root),patch('orchestrator.executors.available'),patch('task_relay.host_apps.rhino',return_value={'available':True,'evidence':'fixture','version':'8','interpreter':'cpython'}):
            chat.Worker(self.state,lambda *_:json.dumps({'answer':'Prepare native Rhino work','action':action})).tick()
        row=self.state.db.execute('SELECT * FROM production_plans WHERE request_id=20').fetchone()
        self.assertIsNotNone(row,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=20').fetchone()[0])
        self.assertEqual(row['status'],'queued')
        self.assertEqual(row['request'],'Use Rhino to make this drawing')
        self.assertIn(media['sha256'],row['context'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)


if __name__=='__main__':unittest.main()
