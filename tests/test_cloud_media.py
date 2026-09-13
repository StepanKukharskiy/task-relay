"""Controlled provider contracts and recovery with tiny byte fixtures, never paid work."""
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch

from orchestrator import cloud_media as media, execution
from task_relay import cloud_providers as providers, gemini, capability_defaults as defaults
from task_relay.relay_paths import Paths
from tests.test_gemini import PNG


def glb():
    doc=json.dumps({'asset':{'version':'2.0'},'meshes':[{'primitives':[]}]}).encode()
    doc+=b' '*(-len(doc)%4)
    return b'glTF'+struct.pack('<IIII',2,len(doc)+20,len(doc),0x4e4f534a)+doc


def mp4():
    return b''.join(struct.pack('>I4s',12,tag)+b'test' for tag in (b'ftyp',b'moov',b'mdat'))


def parameters(cap):
    provider,kind=cap.split('.')
    p={'model':providers.PROVIDERS[provider]['models'][kind][0],'prompt':'A small red ceramic vase.'}
    if kind!='mesh':p['aspect_ratio']='16:9'
    if kind=='video':p['duration']=5
    return p


class Fake:
    def __init__(self, provider, kind, fail=None):
        self.provider,self.kind,self.fail=provider,kind,fail;self.calls=[];self.polls=0
    def request(self,path,payload=None,**kwargs):
        self.calls.append((path,copy.deepcopy(payload)))
        if payload is not None:
            if self.fail: raise self.fail
            return {'id':'remote-1'} if self.provider=='runway' else {'request_id':'remote-1','status':'queued'} if self.provider=='higgsfield' else {'result':'remote-1'}
        self.polls+=1
        url='https://media.example/output'
        if self.provider=='runway':return {'id':'remote-1','status':'SUCCEEDED','output':[url]}
        if self.provider=='higgsfield':return {'request_id':'remote-1','status':'completed',**({'images':[{'url':url}]} if self.kind=='image' else {'video':{'url':url}})}
        return {'id':'remote-1','status':'SUCCEEDED','model_urls':{'glb':url},'consumed_credits':20}


class Tests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()

    def generate(self, cap, client, root=None, downloader=None, **kwargs):
        root=root or self.root
        return media.generate(cap,parameters(cap),[],root,120,50000000,client=client,
            downloader=downloader or (lambda *_: PNG if cap.endswith('image') else mp4() if cap.endswith('video') else glb()),sleep=lambda _:None,**kwargs)

    def test_every_registered_provider_posts_once_downloads_and_reuses_remote_identity(self):
        for cap,kind in media.KINDS.items():
            with self.subTest(cap=cap):
                root=self.root/cap;root.mkdir();provider=cap.split('.')[0];client=Fake(provider,kind)
                first,ident,usage=self.generate(cap,client,root)
                self.assertEqual(ident,'remote-1');self.assertTrue(first)
                self.assertEqual(client.calls[0],media.request(cap,parameters(cap),[]))
                self.assertEqual(json.loads((root/'remote.json').read_text())['task_id'],'remote-1')
                self.generate(cap,client,root)
                self.assertEqual(sum(payload is not None for _,payload in client.calls),1)
                self.assertEqual(json.loads((root/'request.json').read_text())['payload']['promptText' if provider=='runway' else 'prompt'],parameters(cap)['prompt'])

    def test_unknown_submission_is_never_posted_again(self):
        client=Fake('runway','video',gemini.ProviderError('connection',uncertain=True))
        with self.assertRaises(gemini.ProviderError): self.generate('runway.video',client)
        with self.assertRaisesRegex(ValueError,'unknown'): self.generate('runway.video',client)
        self.assertEqual(len(client.calls),1)
        self.assertEqual(json.loads((self.root/'operation.json').read_text())['outcome'],'uncertain')

    def test_restart_after_acceptance_polls_without_second_generation(self):
        client=Fake('meshy','mesh');original=client.request
        def interrupt(path,payload=None,**kwargs):
            if payload is None:raise KeyboardInterrupt
            return original(path,payload,**kwargs)
        client.request=interrupt
        with self.assertRaises(KeyboardInterrupt):self.generate('meshy.mesh',client)
        self.assertTrue((self.root/'accepted.json').exists())
        client.request=original
        self.generate('meshy.mesh',client)
        self.assertEqual(sum(payload is not None for _,payload in client.calls),1)
        self.assertEqual(client.polls,1)

    def test_pending_deadline_preserves_remote_identity(self):
        client=Fake('runway','video');original=client.request
        def pending(path,payload=None,**kwargs):
            return original(path,payload,**kwargs) if payload is not None else {'id':'remote-1','status':'RUNNING'}
        client.request=pending
        times=iter([0,1,21])
        with self.assertRaisesRegex(ValueError,'pending'):
            self.generate('runway.video',client,clock=lambda:next(times))
        self.assertEqual(json.loads((self.root/'remote.json').read_text())['task_id'],'remote-1')
        self.assertFalse((self.root/'response.json').exists())

    def test_different_remote_identity_and_changed_prompt_cannot_be_accepted(self):
        client=Fake('higgsfield','image');original=client.request
        client.request=lambda path,payload=None,**kw: original(path,payload) if payload is not None else {'request_id':'foreign','status':'completed','images':[{'url':'https://media.example/o'}]}
        download=Mock()
        with self.assertRaisesRegex(ValueError,'another task'):self.generate('higgsfield.image',client,downloader=download)
        download.assert_not_called()
        with self.assertRaisesRegex(ValueError,'differs'):
            media.generate('higgsfield.image',{**parameters('higgsfield.image'),'prompt':'Changed'},[],self.root,120,50000000,client=client)
        self.assertEqual(sum(payload is not None for _,payload in client.calls),1)

    def test_download_failure_does_not_repeat_generation(self):
        client=Fake('meshy','mesh')
        with self.assertRaisesRegex(ValueError,'download'):
            self.generate('meshy.mesh',client,downloader=Mock(side_effect=ValueError('download fixture')))
        self.generate('meshy.mesh',client)
        self.assertEqual(sum(payload is not None for _,payload in client.calls),1)

    def test_actual_wire_endpoints_auth_version_and_no_credential_in_output_fetch(self):
        for provider,cap in [('runway','runway.video'),('higgsfield','higgsfield.image'),('meshy','meshy.mesh')]:
            client=providers.Client(provider,'fixture-secret')
            client.opener=MagicMock();client.opener.open.return_value.__enter__.return_value=io.BytesIO(b'{"id":"test"}')
            path,body=media.request(cap,parameters(cap),[]);client.request(path,body)
            request=client.opener.open.call_args.args[0]
            self.assertEqual(request.full_url,providers.PROVIDERS[provider]['base']+path)
            self.assertEqual(request.get_header('Authorization'),('Key ' if provider=='higgsfield' else 'Bearer ')+'fixture-secret')
            if provider=='runway':self.assertEqual(request.get_header('X-runway-version'),'2024-11-06')
            with self.assertRaises(ValueError):client.request('https://foreign.example/steal',body)
        response=Mock(status=200);response.getheader.side_effect=lambda k,d=None:d;response.read.side_effect=[b'file',b'']
        connection=Mock();connection.getresponse.return_value=response
        with patch('task_relay.orchestrator_web.public_addresses',return_value=['93.184.216.34']),patch('task_relay.orchestrator_web.PublicHTTPS',return_value=connection):
            self.assertEqual(providers.download('https://media.example/file?signature=fixture',100),b'file')
            self.assertNotIn('Authorization',connection.request.call_args.kwargs['headers'])
        with self.assertRaises(ValueError):providers.download('https://127.0.0.1/file',100)

    def test_references_preserved_or_rejected_before_transport(self):
        path,body=media.request('runway.image',parameters('runway.image'),[('image/png',PNG)])
        self.assertEqual(body['referenceImages'][0]['tag'],'ref1')
        self.assertEqual(body['referenceImages'][0]['uri'].split(',')[1],__import__('base64').b64encode(PNG).decode())
        for cap in ('meshy.mesh','higgsfield.image','higgsfield.video'):
            with self.assertRaisesRegex(ValueError,'reference'):media.request(cap,parameters(cap),[('image/png',PNG)])
        for cap in media.KINDS:
            bad={**parameters(cap),'model':'invented-model'}
            with self.assertRaises(ValueError):media.request(cap,bad,[])

    def test_output_validation_rejects_text_and_external_mesh_resources(self):
        for kind in ('image','video','mesh'):
            with self.assertRaises((ValueError,OSError)):media.validate_output(kind,b'not media')
        doc=json.dumps({'meshes':[{}],'buffers':[{'uri':'file:///private/secret'}]}).encode();doc+=b' '*(-len(doc)%4)
        raw=b'glTF'+struct.pack('<IIII',2,len(doc)+20,len(doc),0x4e4f534a)+doc
        with self.assertRaisesRegex(ValueError,'self-contained'):media.validate_output('mesh',raw)

    def test_connections_and_defaults_reuse_credentials_without_enabling_text(self):
        from task_relay.bridge import State
        paths=Paths(self.root,self.root/'data',self.root/'work',self.root/'generated')
        state=State(paths.state);self.addCleanup(state.db.close)
        with patch('task_relay.onboarding.PATHS',paths),patch.object(gemini,'DATA',paths.data):
            for provider in providers.PROVIDERS:
                key='fixture:secret' if provider=='higgsfield' else 'fixture-secret'
                providers.connect({'provider':provider,'key':key},paths)
            snap=defaults.snapshot(paths)
            self.assertFalse(next(x for x in snap['capabilities'] if x['capability']=='text')['options'])
            for cap,provider in [('image','higgsfield'),('video','runway'),('mesh','meshy')]:
                defaults.update({'revision':defaults.read(state.db)['revision'],'capability':cap,'provider':provider,'model':providers.PROVIDERS[provider]['models'][cap][0]},paths)
                self.assertEqual(providers.read_config(provider)['models'][cap],providers.PROVIDERS[provider]['models'][cap][0])
            self.assertNotIn('fixture-secret',json.dumps(defaults.snapshot(paths)))
            self.assertNotIn('fixture:secret',json.dumps(providers.connections(paths)))
            self.assertTrue(all(x['connected'] for x in providers.connections(paths)))
            providers.connect({'provider':'meshy','key':''},paths)
            with self.assertRaises(ValueError):providers.connect({'provider':'higgsfield','key':'wrong-format'},paths)


class GraphTests(unittest.TestCase):
    from tests.test_mixed_execution import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    input=Fixture.input

    def test_mesh_runs_through_existing_dispatch_artifact_and_selection_journal(self):
        from tests.test_orchestrator import plan
        cap='meshy.mesh';client=Fake('meshy','mesh')
        self.ops.client=client
        item={'id':'mesh','role':'api','objective':'Create a vase mesh','instruction':'Preserve the exact request.',
              'execution':{'capability':cap,'version':1,'parameters':parameters(cap)},'inputs':[self.input()],
              'outputs':[{'path':'vase.glb','purpose':'Untextured vase','media_type':'model/gltf-binary'}],
              'criteria':execution.REGISTRY[cap]['criteria'],'user_gate':'Select mesh'}
        with patch.object(providers,'read_config',return_value={'api_key':'fixture','models':{'mesh':'meshy-6'}}),patch.object(providers,'download',return_value=glb()):
            self.rt.create(plan([item]));self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')
        output=self.rt.output('demo','mesh','vase.glb')
        self.assertEqual(Path(output['blob']).read_bytes(),glb())
        self.assertEqual(sum(p is not None for _,p in client.calls),1)
        row=self.rt.db.execute('SELECT receipt FROM production_attempts').fetchone()
        self.assertIn('remote-1',row[0])
        self.rt.tick('demo');self.assertEqual(sum(p is not None for _,p in client.calls),1)
        import sqlite3
        from task_relay import usage_tracker
        ledger=sqlite3.connect(':memory:');self.addCleanup(ledger.close)
        usage_tracker.initialize(ledger)
        usage_tracker.collect_relay(ledger,Path(self.rt.db.execute('PRAGMA database_list').fetchone()[2]))
        row=ledger.execute('SELECT provider,model,cost_usd FROM usage_events').fetchone()
        self.assertEqual(tuple(row),('meshy','meshy-6',None))


class PlanningTests(unittest.TestCase):
    from tests.test_mixed_planning import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    request=Fixture.request
    action=Fixture.action
    queue=Fixture.queue
    row=Fixture.row
    response=Fixture.response
    image_response=Fixture.image_response

    def test_cloud_media_plan_freezes_prompt_model_and_selection_gate(self):
        import production_planning as planning
        from orchestrator import contracts
        response=self.image_response();item,review=response['plan']['tasks']
        item['execution']={'capability':'meshy.mesh','version':1,'parameters':parameters('meshy.mesh')}
        item['outputs'][0].update(path='vase.glb',media_type='model/gltf-binary')
        item['criteria']=execution.REGISTRY['meshy.mesh']['criteria']
        item['inputs']=[{'artifact':'fixture','path':'request.txt','purpose':'Request','authority':'User','media_type':'text/plain'}]
        item=contracts.assignment(item);item['inputs']=[]
        review.update(criteria=item['criteria'].copy(),inputs=[{'from_task':'image','output':'vase.glb','path':'vase.glb','purpose':'Review generated mesh','authority':'Unselected candidate','media_type':'model/gltf-binary'}])
        response['plan']['tasks']=[item,review]
        with patch.object(providers,'read_config',return_value={'api_key':'fixture','models':{'mesh':'meshy-6'}}):
            self.queue(action=self.action(step_capabilities=['meshy.mesh']))
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.assertIn('External generation',planning.preview(row))
        self.assertIn('meshy-6',planning.preview(row))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
        changed=copy.deepcopy(response);changed['plan']['tasks'][0]['execution']['parameters']['model']='meshy-7'
        with self.assertRaisesRegex(ValueError,'frozen configured'):planning.validate_result(json.dumps(changed),row)
        changed=copy.deepcopy(response);changed['plan']['tasks'][0].pop('user_gate')
        with self.assertRaisesRegex(ValueError,'selection gate'):planning.validate_result(json.dumps(changed),row)


if __name__=='__main__':unittest.main()
