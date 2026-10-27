"""Offline regressions from real Codex handoff failures; no external dispatch."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import contracts as c, worker_tools, execution
from orchestrator.codex_transport import Client
from tests import test_worker_tools as work_fixture


class BoundaryTests(unittest.TestCase):
    def test_persistent_codex_reuses_confirmed_pixels_but_delivers_new_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            client=Client({}, {},Path(folder),30)
            old='data:image/png;base64,'+base64.b64encode(b'large image'*500000).decode()
            new='data:image/png;base64,'+base64.b64encode(b'new preview').decode()
            client.thread='thread';client.pending=(4,dict(callId='call'))
            client.confirmed_pixels.add(client.image_hash(old))
            payload=dict(messages=[dict(role='tool',tool_call_id='thread:call',content='View receipt'),dict(role='user',content=[dict(type='image_url',image_url=dict(url=u)) for u in (old,new)])],tools=[])
            before=copy.deepcopy(payload)
            reply=client.pending_reply(payload)
            self.assertEqual(payload,before)
            self.assertEqual([p['imageUrl'] for p in reply['result']['contentItems'] if p['type']=='inputImage'],[new])
            self.assertLess(len(json.dumps(reply)),2000)
            client.confirmed_pixels.clear()
            self.assertEqual(len([p for p in client.pending_reply(payload)['result']['contentItems'] if p['type']=='inputImage']),2)

    def fixture(self):
        f=work_fixture.Tests();f.setUp();self.addCleanup(f.doCleanups)
        f.grant['worker_tools_version']=2
        return f

    def test_unaffordable_inline_graph_is_rejected_before_admission(self):
        f=self.fixture();f.grant['operations']=['web.sources.prepared']
        f.create()
        before=len(f.rt.status('job')['tasks'])
        with self.assertRaisesRegex(ValueError,'cannot fit'):
            worker_tools.configure(dict(id='search',objective='Search',instruction='Search',inputs=[]),dict(operation='web.sources.prepared',parameters=dict(model='fixture',domains=[])),f.grant)
        self.assertEqual(len(f.rt.status('job')['tasks']),before)

    def test_native_work_prepares_typed_data_without_relabeling_inventory(self):
        from orchestrator.operation_records import Store
        from tests.test_blender_operations import scene_data
        f=self.fixture();f.grant['operations']=['blender.scene']
        ref=f.source(json.dumps(dict(items=[dict(label='Chest',dimensions='estimated')])), 'inventory.json','application/json')
        frozen,control,state=f.admit('blender.scene',[ref])
        self.assertEqual(frozen['operation_contract']['parameters']['target'],'blender.scene')
        files=worker_tools.files(frozen,control);store=Store(frozen)
        session=worker_tools.Session(files,control)
        with self.assertRaises(ValueError):session.inputs('build')
        doc=scene_data();revision=0
        for field,value in doc.items():
            if field=='version':continue
            records=[dict(kind='append',field=field,index=n,value=v) for n,v in enumerate(value)] if isinstance(value,list) else [dict(kind='field',field=field,value=value)]
            for record in records:
                store.submit(dict(request_key=str(revision),revision=revision,records=[record]),{})
                revision+=1
        store.submit(dict(request_key='seal',revision=revision,records=[dict(kind='end')]),{})
        inputs=session.inputs('build')
        data=next(i for i in inputs if i['media_type']=='application/json')
        self.assertEqual(json.loads(files.read_bytes(data['source'])),doc)
        self.assertNotEqual(data['source'],ref['path'])
        self.assertEqual(json.loads(files.read_bytes(ref['path']))['items'][0]['label'],'Chest')

    def test_preflight_rejects_untyped_native_data_without_dispatch(self):
        task=dict(producer_binding_version=1,execution=dict(capability='blender.scene'),inputs=[dict(path='inventory.json',media_type='application/json')])
        with self.assertRaises(ValueError):
            execution.adapter('blender.scene').validate_content(task,lambda _:b'{"items":[]}')

    def test_native_script_text_output_uses_declared_file_worker(self):
        f=self.fixture();f.create();f.rt.tick('job')
        f.session().delegate(dict(request_id='script',tasks=[dict(id='script',objective='Write an exact script for later approval; no execution',outputs=[dict(name='script',media_type='text/x-python',purpose='Native script source')])]))
        spec=f.rt.spec(f.rt.task('job','script'))
        self.assertEqual(spec['tools'],['files'])
        self.assertEqual(spec['outputs'][0]['media_type'],'text/x-python')

    def test_trusted_repair_resolves_only_rejected_hold_without_new_allowance(self):
        from orchestrator import job_owner
        f=self.fixture();f.create();f.rt.tick('job');session=f.session()
        args=dict(request_id='bad',tasks=[])
        for _ in range(3):session.reject_submission(args,ValueError('Runtime contract mismatch'))
        with self.assertRaises(ValueError):session.check_progress(3,3)
        aid=f.rt.task('job','owner')['latest']
        f.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,reason='Contract mismatch',external_outcome='no_pending_response',pending_requests=[])
        f.rt.tick('job');before=f.rt.spec(f.rt.task('job','owner'))
        with self.assertRaises(ValueError):job_owner.resolve_submission_hold(f.rt,'job',dict(source='test',evidence='Offline repair passed'))
        with f.rt.transaction():job_owner.resolve_submission_hold(f.rt,'job',dict(source='test',evidence='Offline repair passed'))
        self.assertIsNone(f.session().pending_submission)
        self.assertEqual(f.rt.spec(f.rt.task('job','owner')),before)
        self.assertEqual(f.rt.task('job','owner')['attempts'],1)
        self.assertEqual(len(f.factory.calls),1)

    def test_owner_correction_survives_compact_brief_and_checkpoint_restore(self):
        from orchestrator.working_context import owner_brief
        f=self.fixture();f.create();f.rt.tick('job');session=f.session()
        revision=dict(instruction='Use the corrected exact consumer contract; preserve limits.',source='supervisor:repair',previous_attempt='prior')
        session.frozen['revision']=revision
        self.assertEqual(owner_brief(session.frozen)['revision'],revision)
        session.saved=dict(contents=[dict(role='user',parts=[dict(text='Old checkpoint')])],history=[dict(role='user',content='Old checkpoint')])
        contents,history=session.restore([],[])
        self.assertIn(c.encoded(revision),contents[-1]['parts'][0]['text'])
        self.assertIn(c.encoded(revision),history[-1]['content'])
        self.assertEqual(session.snapshot()['revision'],revision)

    def test_invalid_frozen_capacity_rejected_before_owner_admission(self):
        from orchestrator import job_owner
        for field,value in [('provider_requests',48),('response_tokens',512),('seconds',1801),('tool_calls',201),('output_bytes',500000001)]:
            with self.subTest(field=field):
                f=self.fixture();f.grant['task_limits'][field]=value
                with self.assertRaisesRegex(ValueError,'limit'):
                    f.create()
                self.assertEqual(f.rt.db.execute('SELECT COUNT(*) FROM production_runs').fetchone()[0],0)
                self.assertEqual(f.factory.calls,[])

    def test_record_validation_correction_and_finish_fit_original_grant(self):
        from tests.test_owner_compilation import Tests as Fixture
        f=Fixture();f.setUp();self.addCleanup(f.doCleanups)
        f.grant['task_limits'].update(tool_calls=24,provider_requests=24)
        text='\n'.join('Item '+str(n) for n in range(1,13))
        ref=f.source(text)
        f.create(inputs=[ref]);f.rt.tick('job')
        f.session().delegate(dict(request_id='subjects',tasks=[dict(id='subjects',objective='Describe exact fixture subjects',content=dict(family='collection.subjects',sources=dict(source_path=dict(artifact=ref['artifact'])),parameters=dict(fields=['name'],max_records=12)))]))
        def steps(frozen):
            self.assertEqual(frozen['limits']['provider_requests'],24)
            calls=[('file_read',dict(path=frozen['operation_contract']['parameters']['source_path'],offset=0,limit=1000))]
            for n in range(1,13):
                record=dict(kind='item',slot=n,label='Item '+str(n),attributes=dict(name='Item '+str(n)),quote='Item '+str(n),bbox=None,notes='Synthetic source')
                calls.append(('operation_submit',dict(request_key=str(n),revision=n-1,records=[record])))
            calls.extend([('operation_submit',dict(request_key='invalid-end',revision=12,records=[dict(kind='end',count=12,notes='x'*601)])),
                          ('operation_submit',dict(request_key='corrected-end',revision=12,records=[dict(kind='end',count=12,notes='All twelve source items preserved')]))])
            return calls
        frozen,script=f.run_worker('subjects',steps)
        control=Path(f.factory.sessions[frozen['assignment_id']]['session']['control'])
        self.assertEqual(f.rt.task('job','subjects')['status'],'awaiting_review')
        diagnostics=[json.loads(p.read_text()).get('result',{}).get('error','') for p in control.glob('tool-*.json')]
        self.assertTrue(any('601 characters; maximum 600' in value for value in diagnostics))
        artifact=f.rt.output('job','subjects','outputs/result.json')
        doc=json.loads(Path(artifact['blob']).read_text())
        self.assertTrue(doc['complete']);self.assertEqual(len(doc['items']),12)
        self.assertFalse(any(r.get('notes')=='x'*601 for r in doc['records']))
