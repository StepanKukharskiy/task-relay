"""Opt-in real-host qualification. Never uses a provider or a live messaging channel."""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
import unittest

from orchestrator import execution, host_code
from orchestrator.adapters import ExecutionFactory
from orchestrator.blender_host import scene
from orchestrator.runtime import Runtime, file_hash
from tests.test_blender_operations import operation, scene_data
from tests.test_blender_mesh import mesh_scene
from tests.test_orchestrator import FakeFactory, plan, task


# Every registered capability must have a real-host case. New capabilities fail coverage.
COVERAGE = {
    'blender.startup': 'test_01_startup',
    'blender.scene': 'test_02_produce_review_render_select_inspect_revision',
    'blender.mesh_scene': 'test_03_mesh',
    'blender.inspect': 'test_04_inspect',
    'blender.run_python': 'test_05_edit',
    'blender.import_asset': 'test_06_assets',
    'blender.animate': 'test_07_animation_and_checkpoint',
}


class FixtureAgents(FakeFactory):
    """Deterministic data producer/reviewer; real registered workers run separately."""
    def submit(self, session):
        super().submit(session)
        saved = self.sessions[session['id']]
        frozen = saved['frozen']; ws = Path(frozen['workspace'])
        if frozen['role'] == 'producer':
            data = json.loads((ws / 'request.json').read_text()) if (ws/'request.json').exists() else scene_data()
            # The producer receives and runs the same standalone validator as real agents.
            candidate = ws / frozen['outputs'][0]['path']; candidate.parent.mkdir(parents=True,exist_ok=True)
            candidate.write_text(json.dumps(data))
            validator=next(ws/i['path'] for i in frozen['inputs'] if i['path'].endswith('validate_scene.py'))
            checked = subprocess.run([os.sys.executable, '-I', str(validator), str(candidate)],
                                     capture_output=True, text=True, timeout=15)
            if checked.returncode: raise ValueError(checked.stderr)
            evidence = checked.stdout
        else:
            evidence = []
            for item in frozen['inputs']:
                path = ws/item['path']
                if file_hash(path) != item['sha256']: raise ValueError('Reviewer input changed')
                if item.get('media_type') == 'application/json':
                    value = json.loads(path.read_text())
                    if 'objects' in value: scene(value)
                if item.get('media_type') == 'image/png':
                    from orchestrator.blender_animation import png
                    png(path, [64, 64])
                evidence.append({'path': item['path'], 'sha256': file_hash(path)})
            (ws/'review.md').write_text(json.dumps(evidence))
        (ws/'.relay/result.json').write_text(json.dumps(dict(
            assignment_id=frozen['assignment_id'], summary='Deterministic fixture verification',
            decision='accept' if frozen['role']=='reviewer' else 'delivered', instruction='',
            checks=[dict(criterion=i, passed=True, evidence=str(evidence))
                    for i in range(1, len(frozen['criteria'])+1)])))
        saved['status'] = {'status':'finished', 'exit_code':0}
        return {'submitted': True}


@unittest.skipUnless(os.environ.get('RELAY_BLENDER_QUALIFICATION_DIR'), 'Use scripts/qualify_blender.py --host')
class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['RELAY_BLENDER_QUALIFICATION_DIR']).resolve()/'host'
        cls.root.mkdir(parents=True, exist_ok=False)
        cls.factory = ExecutionFactory(agents=FixtureAgents())
        cls.rt = Runtime(cls.root/'runtime', cls.factory)
        cls.outputs = {}; cls.records = []

    @classmethod
    def tearDownClass(cls):
        cls.rt.close()

    def input(self, path, media, target=None):
        aid = self.rt.register(path, 'Qualification fixture', path=Path(path).name)
        return dict(artifact=aid, path=target or Path(path).name, purpose='Qualification input',
                    authority='Exact synthetic test fixture', media_type=media)

    def source(self, name, value, media='application/json'):
        path=self.root/name
        path.write_text(json.dumps(value) if media=='application/json' else value)
        return self.input(path, media)

    def result_input(self, run, output, target=None, tid='app'):
        a=self.rt.output(run, tid, output)
        spec=self.rt.spec(self.rt.task(run,tid))
        media=next(o['media_type'] for o in spec['outputs'] if o['path']==output)
        return dict(artifact=a['id'], path=target or Path(output).name, purpose='Exact prior result',
                    authority='Synthetic qualification selection', media_type=media)

    def wait(self, run, expected='completed'):
        deadline=time.monotonic()+660
        while time.monotonic()<deadline:
            status=self.rt.tick(run)
            if status['status'] not in ('active','paused'):
                (self.root/(run+'-status.json')).write_text(json.dumps(status, indent=2))
                self.assertEqual(status['status'], expected, str(status))
                return status
            time.sleep(.25)
        self.rt.cancel(run)
        # Runtime's existing supervisor owns termination; do not abandon a live process.
        for _ in range(120):
            status=self.rt.tick(run)
            if status['status'] not in ('active','cancelling'): break
            time.sleep(.25)
        self.fail('Qualification deadline exceeded: '+json.dumps(status))

    def run_plan(self, name, tasks, expected='completed', approve=False):
        p=plan(tasks);p['id']=name
        self.rt.create(p)
        if approve:
            with self.rt.transaction():
                host_code.authorize(self.rt,name,'app',{'source':'explicit synthetic qualification script'})
        self.rt.tick(name)
        # Recover the actual supervisor receipt across a controller restart.
        self.rt.close();type(self).rt=Runtime(self.root/'runtime',self.factory)
        status=self.wait(name,expected)
        before=[(t['id'],t['attempts']) for t in status['tasks']]
        again=self.rt.tick(name)
        self.assertEqual(before,[(t['id'],t['attempts']) for t in again['tasks']])
        for artifact in status['artifacts']:
            self.assertEqual(file_hash(self.rt.artifact(artifact['id'])['blob']),artifact['sha256'])
        self.records.append({'run':name,'status':status['status'],'attempts':before})
        (self.root/'runs.json').write_text(json.dumps(self.records,indent=2))
        return status

    def run_operation(self, name, cap, inputs, parameters=None, approve=False):
        op=operation(cap,inputs)
        op['execution']['parameters']=parameters or {}
        self.run_plan(name,[op],approve=approve)
        artifact=self.rt.output(name,'app','delivery/execution.json')
        receipt=json.loads(Path(artifact['blob']).read_text())
        self.assertTrue(receipt.get('passed',True),str(receipt))
        runs=receipt['runs'] if 'runs' in receipt else [receipt]
        self.assertTrue(all(r['returncode']==0 for r in runs),str(receipt))
        type(self).outputs[name]=self.rt.output(name,'app',op['outputs'][0]['path'])
        return receipt

    def need(self, name):
        if name not in self.outputs: self.skipTest('Upstream host qualification failed: '+name)

    def test_01_startup(self):
        r=self.run_operation('startup','blender.startup',[self.source('request.txt','Check Blender startup','text/plain')])
        self.assertTrue(r['runs'][0]['marker_present'])

    def test_02_produce_review_render_select_inspect_revision(self):
        from orchestrator.blender_host import validator_source
        data=scene_data();data['objects'][0]['rotation']=[0,0,0]
        cylinder=copy.deepcopy(data['objects'][0]);cylinder.update(shape='cylinder',position=[2,0,1])
        data['objects'].append(cylinder)
        request=self.source('request.json',data)
        validator=self.source('validate_scene.py',validator_source(),'text/plain')
        producer=task('produce',inputs=[request,validator],max_attempts=1)
        producer['outputs']=[dict(path='delivery/scene.json',purpose='Scene data',media_type='application/json')]
        def edge(t,p,target,media):
            return dict(from_task=t,output=p,path=target,purpose='Checked prior result',authority='Candidate',media_type=media)
        review=task('review-data',dependencies=['produce'],review_of='produce',
                    inputs=[edge('produce','delivery/scene.json','scene.json','application/json')],max_attempts=1)
        review.update(role='reviewer',outputs=[dict(path='review.md',purpose='Verification')])
        render=operation('blender.scene',[edge('produce','delivery/scene.json','scene.json','application/json')])
        render.update(id='render',dependencies=['produce','review-data'],user_gate='Select fixture scene')
        rr=task('review-render',dependencies=['render'],review_of='render',max_attempts=1,
                inputs=[edge('render','delivery/preview.png','preview.png','image/png')])
        rr.update(role='reviewer',outputs=[dict(path='review.md',purpose='Verification')])
        rr['criteria']=render['criteria']
        rr['inputs']=[edge('render',o['path'],Path(o['path']).name,o['media_type']) for o in render['outputs']]
        inspect=operation('blender.inspect',[edge('render','delivery/scene.blend','selected.blend','application/x-blender')])
        inspect.update(id='inspect',dependencies=['render','review-render'])
        self.run_plan('pipeline',[producer,review,render,rr,inspect],expected='awaiting_user')
        self.assertEqual(self.rt.task('pipeline','inspect')['attempts'],0)
        baseline=self.rt.output('pipeline','render','delivery/scene.blend')
        self.rt.select('pipeline','render',baseline['id'],'Select fixture scene','Synthetic test selection')
        self.wait('pipeline')
        type(self).outputs['baseline']=baseline
        original=self.rt.output('pipeline','produce','delivery/scene.json')
        original_hash=original['sha256']
        revised=json.loads(Path(original['blob']).read_text())
        for obj in revised['objects']:
            obj['size'][2]*=2;obj['position'][2]*=2
        self.run_operation('revision','blender.scene',[self.source('revision.json',revised),
            self.input(Path(original['blob']),'text/plain','baseline-context.txt')])
        self.assertEqual(file_hash(original['blob']),original_hash)
        self.assertNotEqual(self.outputs['revision']['sha256'],baseline['sha256'])

    def test_03_mesh(self):
        self.run_operation('mesh','blender.mesh_scene',[self.source('mesh.json',mesh_scene())])

    def test_04_inspect(self):
        self.need('baseline')
        self.run_operation('inspect','blender.inspect',[self.input(Path(self.outputs['baseline']['blob']),'application/x-blender','source.blend')])
        value=json.loads(Path(self.outputs['inspect']['blob']).read_text())
        self.assertIn('RelayObject_000',json.dumps(value))

    def test_05_edit(self):
        self.need('baseline')
        script=self.source('edit.py','bpy.data.objects["RelayObject_000"].scale.z *= 2\n','text/x-python')
        checks=self.source('checks.json',dict(changed_objects=['RelayObject_000'],preserve_other_objects=True,
            preserve_cameras=True,preserve_materials=True,expected_dimensions={'RelayObject_000':[1,1,4]},
            preview=dict(camera='RelayCamera',resolution=[64,64],samples=1)))
        base=self.input(Path(self.outputs['baseline']['blob']),'application/x-blender','source.blend')
        params={key:self.rt.artifact(item['artifact'])['sha256'] for key,item in
                [('scene_sha256',base),('script_sha256',script),('checks_sha256',checks)]}
        params['permissions']='unrestricted_host'
        self.run_operation('edit','blender.run_python',[base,script,checks],params,approve=True)

    def test_06_assets(self):
        self.need('baseline');self.need('mesh')
        # Fixed test fixture prepares existing texture slots and two real image formats.
        # The operation being tested still performs all binding, append and relocation.
        from task_relay.host_apps import blender
        stage=self.root/'asset-fixtures';stage.mkdir()
        script=stage/'fixture.py'
        script.write_text('''import bpy, sys
from pathlib import Path
source, library, out = sys.argv[sys.argv.index('--')+1:]
out=Path(out)
bpy.ops.wm.open_mainfile(filepath=source, load_ui=False, use_scripts=False)
mat=bpy.data.materials['RelayMaterial_000']
for name in ('PNG slot','JPEG slot'):
    node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.name=name
for name, fmt in [('texture.png','PNG'),('texture.jpg','JPEG')]:
    image=bpy.data.images.new(name,width=8,height=8)
    image.generated_color=(.1,.5,.9,1)
    bpy.context.scene.render.image_settings.file_format=fmt
    image.save_render(str(out/name),scene=bpy.context.scene)
    bpy.data.images.remove(image)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(out/'source.blend'))
bpy.ops.wm.open_mainfile(filepath=library, load_ui=False, use_scripts=False)
bpy.data.objects['RelayObject_000'].name='ImportedMesh'
bpy.ops.wm.save_as_mainfile(filepath=str(out/'library.blend'))
''')
        argv=[blender()['executable'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
              '--python',str(script),'--',self.outputs['baseline']['blob'],self.outputs['mesh']['blob'],str(stage)]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=120)
        (stage/'fixture.log').write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode,0,result.stderr)
        specs=[(stage/'source.blend','scene','application/x-blender'),
               (stage/'library.blend','library','application/x-blender'),
               (stage/'texture.png','image','image/png'),(stage/'texture.jpg','image','image/jpeg')]
        files=[];inputs=[]
        for n,(path,kind,media) in enumerate(specs):
            name=('library.blend' if kind=='library' else path.name)
            files.append(dict(path='source/'+name,sha256=file_hash(path),kind=kind,
                              provenance=dict(source='Synthetic qualification fixture',license=None)))
            inputs.append(self.input(path,media,name))
        imports=[dict(type='append_objects',library='source/library.blend',names=['ImportedMesh'],collection='Imported')]
        for filename,node in [('texture.png','PNG slot'),('texture.jpg','JPEG slot')]:
            imports.append(dict(type='image_texture',file='source/'+filename,material='RelayMaterial_000',node=node,image_name=filename))
        manifest=self.source('assets.json',dict(version=1,scene='source/source.blend',files=files,imports=imports,
                preview=dict(camera='RelayCamera',resolution=[64,64],samples=1)))
        self.run_operation('assets','blender.import_asset',inputs+[manifest],
                           {'manifest_sha256':self.rt.artifact(manifest['artifact'])['sha256']})

    def test_07_animation_and_checkpoint(self):
        self.need('baseline')
        base=self.input(Path(self.outputs['baseline']['blob']),'application/x-blender','source.blend')
        tracks=[]
        for prop,start,end in [('location',[0,0,1],[.2,0,1]),('rotation_euler',[0,0,0],[0,0,.3]),('scale',[1,1,2],[1,1,2.2])]:
            tracks.append(dict(object='RelayObject_000',property=prop,keys=[dict(frame=1,value=start),dict(frame=3,value=end)]))
        value=dict(version=1,scene_sha256=self.outputs['baseline']['sha256'],mode='preview',frame_start=1,frame_end=3,
                   fps=3,camera='RelayCamera',resolution=[64,64],samples=1,tracks=tracks)
        manifest=self.source('animation.json',value)
        params={'manifest_sha256':self.rt.artifact(manifest['artifact'])['sha256']}
        self.run_operation('animation','blender.animate',[base,manifest],params)
        checkpoint=self.result_input('animation','delivery/checkpoint.zip','checkpoint.zip')
        receipt=self.run_operation('animation-resume','blender.animate',[base,manifest,checkpoint],params)
        self.assertFalse(any(r.get('phase','').startswith(('frame:','build:')) for r in receipt['runs']))
        value.update(mode='final',tracks=[])
        # Empty tracks preserve existing animation from the preceding native candidate.
        animated=self.rt.output('animation','app','delivery/candidate.blend')
        value['scene_sha256']=animated['sha256']
        final=self.source('final-animation.json',value)
        self.run_operation('animation-final','blender.animate',[
            self.input(Path(animated['blob']),'application/x-blender','source.blend'),final],
            {'manifest_sha256':self.rt.artifact(final['artifact'])['sha256']})

    def test_08_chat_plan_start_review_resume_and_delivery(self):
        """Real Relay entrypoints and native outputs; only model/chat transport are fixtures."""
        from unittest.mock import patch
        from task_relay.bridge import State, Bridge
        from tests.test_bridge import TelegramFake
        from task_relay import orchestrator_chat as chat, production_planning as planning, production_control as pc
        state=State(self.root/'channel/state.sqlite')
        factory=ExecutionFactory(agents=FixtureAgents())
        rt=Runtime(pc.root(state),factory,connection=state.db)
        telegram=TelegramFake();bridge=Bridge(state,telegram,{})
        try:
            with state.db:
                state.put('user_id',7);state.put('chat_id',7)
                state.put('production-planner-policy',{'backend':plan()['backend']})
            request='Create a small Blender qualification scene. Pause after data review so I can select it, then render and deliver the native scene and preview.'
            action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                        research_ids=[],artifact_ids=[],planning_only=False,step_capabilities=['blender.scene'])
            with patch.object(chat,'provider',return_value=('gemini','fixture')),patch('task_relay.bridge.local_tasks',return_value=[]):
                bridge.process({'update_id':700,'message':{'text':'/orchestrator '+request,'from':{'id':7},'chat':{'id':7,'type':'private'}}})
                chat.Worker(state,lambda *_:json.dumps({'answer':'Prepare the requested bounded plan','action':action})).tick()
            row=state.db.execute('SELECT * FROM production_plans').fetchone()
            self.assertIsNotNone(row)
            producer=task('produce',inputs=[],max_attempts=1,user_gate='Select prepared data')
            producer['outputs']=[dict(path='scene.json',purpose='Scene data',media_type='application/json')]
            data_input=dict(from_task='produce',output='scene.json',path='scene.json',purpose='Review data',authority='Candidate',media_type='application/json')
            review=task('review',dependencies=['produce'],review_of='produce',inputs=[data_input],max_attempts=1)
            review.update(role='reviewer',outputs=[dict(path='review.md',purpose='Data review')])
            render=operation('blender.scene',[data_input]);render.update(dependencies=['produce','review'],user_gate='Select rendered scene')
            rr=task('render-review',dependencies=['app'],review_of='app',max_attempts=1,
                    inputs=[dict(from_task='app',output=o['path'],path=Path(o['path']).name,purpose='Inspect rendered output',
                                 authority='Candidate',media_type=o['media_type']) for o in render['outputs']])
            rr.update(role='reviewer',criteria=render['criteria'],outputs=[dict(path='review.md',purpose='Render review')])
            tasks=[producer,review,render,rr]
            for spec in tasks:
                if spec.get('execution'):
                    reg=execution.REGISTRY[spec['execution']['capability']]
                    spec['limits']=dict(seconds=reg['seconds'],tool_calls=1,output_bytes=reg['output_bytes'])
                else:
                    spec['tools']=['files','shell'];spec['limits']=dict(seconds=60,tool_calls=10,output_bytes=1000000)
            response=dict(decision='ready',message='Qualification plan',input_basis={'mode':'new','artifacts':[]},
                          plan=dict(brief=request,tasks=tasks))
            planning.Worker(state,lambda *_:(json.dumps(response),{})).tick()
            row=state.db.execute('SELECT * FROM production_plans').fetchone()
            self.assertEqual(row['status'],'ready',row['error'])
            bridge.flush(False)
            bridge.process({'update_id':701,'callback_query':{'id':'start','data':'plan:start:'+row['token'],
                            'from':{'id':7},'message':{'chat':{'id':7,'type':'private'}}}})
            row=state.db.execute('SELECT * FROM production_plans').fetchone()
            self.assertEqual(row['status'],'started',row['error']);run=row['run']
            worker=pc.Worker(state,lambda _:rt)
            def until_gate():
                deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    worker.tick();status=rt.status(run)
                    if status['status']!='active':return status
                    time.sleep(.25)
                rt.cancel(run);self.fail('Channel pipeline did not reach review within its test deadline')
            self.assertEqual(until_gate()['status'],'awaiting_user')
            self.assertFalse(state.get('production-enabled:'+run))
            self.assertEqual(rt.task(run,'app')['attempts'],0)
            bridge.flush(False);bridge.flush_media()
            card=state.db.execute('SELECT * FROM production_selection_cards WHERE run=? AND task=?',(run,'produce')).fetchone()
            mid=state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
            callback={'update_id':702,'callback_query':{'id':'select','data':'prodselect:'+card['token'],
                      'from':{'id':7},'message':{'chat':{'id':7,'type':'private'},'message_id':mid}}}
            bridge.process(callback);bridge.process(callback)
            self.assertTrue(state.get('production-enabled:'+run))
            self.assertEqual(until_gate()['status'],'awaiting_user')
            bridge.flush(False)
            for _ in range(5):bridge.flush_media()
            self.assertFalse(state.get('production-enabled:'+run))
            media=[dict(r) for r in state.db.execute('SELECT * FROM media_outbox')]
            for suffix in ('scene.blend','preview.png'):
                matches=[r for r in media if r['filename'].endswith(suffix)]
                self.assertTrue(matches,suffix);self.assertTrue(all(r['status']=='sent' for r in matches))
                expected=rt.output(run,'app','delivery/'+suffix)
                self.assertTrue(all(file_hash(r['path'])==expected['sha256'] for r in matches))
            self.assertTrue(all(t['attempts']==1 for t in rt.status(run)['tasks']))
            calls=state.db.execute('SELECT request FROM production_plan_calls').fetchone()
            self.assertEqual(json.loads(calls[0])['original_request'],request)
            # A reply to the delivered native file retains the production identity.
            native=next(r for r in media if r['filename'].endswith('scene.blend'))
            mid=next(i for i,(_,text) in enumerate(telegram.sent,1) if text==native['caption'])
            bridge.process({'update_id':703,'message':{'text':'Make this twice as tall.','from':{'id':7},
                'chat':{'id':7,'type':'private'},'reply_to_message':{'message_id':mid}}})
            reply=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=703').fetchone()
            self.assertEqual(reply['focus'],run)
            (self.root/'channel-receipt.json').write_text(json.dumps(dict(status=rt.status(run),media=media,
                model='controlled fixture',transport='TelegramFake',reply_focus=reply['focus']),indent=2))
        finally:
            # Drain only this isolated fixture's workers, including on assertion failure.
            for row in state.db.execute('SELECT id FROM production_runs').fetchall():
                if rt.status(row['id'])['status']=='active':
                    rt.cancel(row['id'])
                    for _ in range(120):
                        if rt.tick(row['id'])['status']=='cancelled':break
                        time.sleep(.25)
            state.db.close()
