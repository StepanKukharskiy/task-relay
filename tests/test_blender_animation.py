import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from orchestrator import contracts as c
from orchestrator.runtime import Runtime,file_hash
from orchestrator.step_runner import execute
from orchestrator.blender_animation import validate,bind_registered,restore
from tests.test_blender_operations import operation
from tests.test_orchestrator import FakeFactory,plan


def inputs(rt,root):
    source=root/'source.blend';source.write_bytes(b'\xffnative')
    m=dict(version=1,scene_sha256=file_hash(source),mode='preview',frame_start=1,frame_end=3,fps=3,
           camera='Camera',resolution=[64,64],samples=1,
           tracks=[dict(object='Cube',property='rotation_euler',keys=[dict(frame=1,value=[0,0,0]),dict(frame=3,value=[0,0,1])])])
    manifest=root/'animation.json';manifest.write_text(json.dumps(m))
    items=[]
    for p,media in [(source,'application/x-blender'),(manifest,'application/json')]:
        aid=rt.register(p,'Selected exact input',path=p.name)
        items.append(dict(artifact=aid,path=p.name,purpose='Selected input',authority='User-approved scope',media_type=media))
    op=operation('blender.animate',items);op['execution']['parameters']={'manifest_sha256':file_hash(manifest)}
    return op,m


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.fake=FakeFactory();self.rt=Runtime(self.root/'runtime',self.fake)
        self.patches=[patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture')),
          patch('task_relay.host_apps.video_tools',return_value=dict(available=True,ffmpeg='/fixture/ffmpeg',ffprobe='/fixture/ffprobe')),
          patch('task_relay.host_evidence.application_signature',side_effect=lambda p:{'path':p})]
        for p in self.patches:p.start()
        self.op,self.manifest=inputs(self.rt,self.root)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.rt.close();self.temp.cleanup()
    def frozen(self):
        self.rt.create(plan([self.op]));self.rt.tick('demo');session=self.fake.sessions[self.rt.task('demo','app')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        return session['frozen'],control
    def process(self,argv,**kwargs):
        if argv[0].endswith('ffprobe'):
            return subprocess.CompletedProcess(argv,0,json.dumps({'streams':[dict(width=64,height=64,nb_read_frames='3',r_frame_rate='3/1')]}).encode(),b'')
        if argv[0].endswith('ffmpeg'):
            Path(argv[-1]).write_bytes(b'video');return subprocess.CompletedProcess(argv,0,b'',b'')
        mode=argv[argv.index('--')+1];root=Path(argv[-2])
        if mode=='build':(root/'candidate.blend').write_bytes(b'candidate')
        if mode in ('build','verify'):(root/'checks.json').write_text(json.dumps({'passed':mode=='verify'}))
        if mode=='frame':(root/f'frames/{int(argv[-1]):06d}.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00'*8+struct.pack('>II',64,64)+b'pixels')
        return subprocess.CompletedProcess(argv,0,b'RELAY_ANIMATION_OK',b'')
    def test_frames_encoded_and_receipts_retained_without_replay(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process) as proc:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(proc.call_count,7)
        out=Path(frozen['workspace'])/'delivery';state=json.loads((out/'frames.json').read_text())
        self.assertEqual({v['state'] for v in state['frames'].values()},{'completed'})
        self.assertTrue(all(v['sha256'] for v in state['frames'].values()))
        self.assertFalse(json.loads((out/'execution.json').read_text())['selected'])
        self.assertEqual({p.name for p in out.iterdir()},{'candidate.blend','animation.mp4','preview.png','checkpoint.zip','frames.json','execution.json'})
    def test_timeout_records_unresolved_intent_and_restore_refuses_replay(self):
        frozen,control=self.frozen()
        def fail(argv,**kwargs):
            if argv[0].endswith('blender') and argv[-1]=='2':raise subprocess.TimeoutExpired(argv,1)
            return self.process(argv,**kwargs)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=fail):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        out=Path(frozen['workspace'])/'delivery';dest=self.root/'restore';dest.mkdir()
        with self.assertRaisesRegex(ValueError,'Unresolved frame intent'):
            restore(out/'checkpoint.zip',dest,self.op['execution']['parameters']['manifest_sha256'],self.manifest,100000000)
        state=json.loads((out/'frames.json').read_text());self.assertEqual(state['frames']['1']['state'],'completed');self.assertEqual(state['frames']['2']['state'],'in_progress');self.assertEqual(state['frames']['3']['state'],'pending')
    def test_checkpoint_reuses_frames_and_does_not_claim_new_scope(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):execute(frozen,control)
        out=Path(frozen['workspace'])/'delivery';aid=self.rt.register(out/'checkpoint.zip','Saved checkpoint',run='demo',task='app',attempt=frozen['assignment_id'],path='delivery/checkpoint.zip')
        op=copy.deepcopy(self.op);op['inputs'].append(dict(artifact=aid,path='resume.zip',purpose='Checkpoint',authority='Explicit continuation',media_type='application/zip'))
        with self.assertRaisesRegex(ValueError,'confirmed stopped'):bind_registered(self.rt,op)
        self.rt.db.execute("UPDATE production_attempts SET state='completed',receipt=? WHERE id=?",(json.dumps({'status':'finished'}),frozen['assignment_id']))
        bind_registered(self.rt,op)
        value=plan([op]);value['id']='resume';self.rt.create(value);self.rt.tick('resume')
        session=self.fake.sessions[self.rt.task('resume','app')['latest']];newcontrol=Path(session['session']['control']);newcontrol.mkdir(parents=True)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process) as proc:
            self.assertEqual(execute(session['frozen'],newcontrol)['outcome'],'completed')
            self.assertEqual(proc.call_count,3) # Reopen verification, encode, video verification; zero frames.
    def test_between_frame_deadline_resumes_only_verified_missing_frames(self):
        frozen,control=self.frozen();clock=[0]
        def expire(argv,**kwargs):
            result=self.process(argv,**kwargs)
            if argv[0].endswith('blender') and argv[-1]=='1':clock[0]=1000
            return result
        with patch('orchestrator.blender_animation.time.monotonic',side_effect=lambda:clock[0]),patch('orchestrator.blender_animation.subprocess.run',side_effect=expire):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        out=Path(frozen['workspace'])/'delivery'
        aid=self.rt.register(out/'checkpoint.zip','Saved partial frames',run='demo',task='app',attempt=frozen['assignment_id'],path='delivery/checkpoint.zip')
        self.rt.db.execute("UPDATE production_attempts SET state='blocked',receipt=? WHERE id=?",(json.dumps({'status':'finished'}),frozen['assignment_id']))
        op=copy.deepcopy(self.op);op['inputs'].append(dict(artifact=aid,path='resume.zip',purpose='Checkpoint',authority='Explicit continuation',media_type='application/zip'))
        bind_registered(self.rt,op);value=plan([op]);value['id']='resume';self.rt.create(value);self.rt.tick('resume')
        s=self.fake.sessions[self.rt.task('resume','app')['latest']];nc=Path(s['session']['control']);nc.mkdir(parents=True)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process) as proc:
            self.assertEqual(execute(s['frozen'],nc)['outcome'],'completed')
        frames=[call.args[0][-1] for call in proc.call_args_list if 'frame' in call.args[0]]
        self.assertEqual(frames,['2','3'])
    def test_unresolved_checkpoint_preflight_does_not_consume_an_attempt(self):
        frozen,control=self.frozen()
        def fail(argv,**kwargs):
            if 'frame' in argv:raise subprocess.TimeoutExpired(argv,1)
            return self.process(argv,**kwargs)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=fail):execute(frozen,control)
        aid=self.rt.register(Path(frozen['workspace'])/'delivery/checkpoint.zip','Unresolved checkpoint',run='demo',task='app',attempt=frozen['assignment_id'],path='delivery/checkpoint.zip')
        self.rt.db.execute("UPDATE production_attempts SET state='blocked',receipt=? WHERE id=?",(json.dumps({'status':'finished'}),frozen['assignment_id']))
        op=copy.deepcopy(self.op);op['inputs'].append(dict(artifact=aid,path='resume.zip',purpose='Checkpoint',authority='Explicit continuation',media_type='application/zip'))
        with self.assertRaisesRegex(ValueError,'Unresolved frame intent'):bind_registered(self.rt,op)
        value=plan([op]);value['id']='resume';self.rt.create(value);count=len(self.fake.calls);self.rt.tick('resume')
        self.assertEqual(self.rt.task('resume','app')['attempts'],0);self.assertEqual(len(self.fake.calls),count)
    def test_limits_and_arbitrary_properties_rejected(self):
        for key,value in [('frame_end',121),('fps',0),('samples',16),('resolution',[513,512])]:
            m=copy.deepcopy(self.manifest);m[key]=value
            with self.assertRaises(ValueError):validate(m)
        m=copy.deepcopy(self.manifest);m['tracks'][0]['property']='python'
        with self.assertRaises(ValueError):validate(m)
        m=copy.deepcopy(self.manifest);m['tracks'][0]['keys'][0]['value'][0]=float('nan')
        with self.assertRaises(ValueError):validate(m)
    def test_future_inputs_and_changed_scene_stop_preflight(self):
        op=copy.deepcopy(self.op);op['inputs'][0].pop('artifact');op['inputs'][0].update(from_task='a',output='scene.blend')
        with self.assertRaisesRegex(ValueError,'already registered'):c.assignment(op)
        p=Path(self.rt.artifact(self.op['inputs'][0]['artifact'])['blob']);p.chmod(0o600);p.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):bind_registered(self.rt,self.op)
        self.rt.create(plan([self.op]));self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','app')['attempts'],0);self.assertEqual(self.fake.calls,[])
    def test_unlisted_checkpoint_paths_rejected(self):
        z=self.root/'bad.zip'
        with zipfile.ZipFile(z,'w') as f:f.writestr('../outside',b'data')
        with self.assertRaisesRegex(ValueError,'Unexpected checkpoint'):restore(z,self.root,'a'*64,self.manifest,100000000)

if __name__=='__main__':unittest.main()
