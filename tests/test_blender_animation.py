import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
import base64
from orchestrator import contracts as c
from orchestrator.runtime import Runtime,file_hash
from orchestrator.step_runner import execute
from orchestrator.blender_animation import validate,bind_registered,restore
from orchestrator.blender_animation_worker import render_frames,compact_png
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
        if mode=='frames':
            def render(f,path):
                if getattr(self,'frame_handler',None):self.frame_handler(f,path)
                path.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00'*8+struct.pack('>II',64,64)+b'pixels')
            try:render_frames(root,json.loads((root/'manifest.json').read_text()),render)
            except ValueError as e:return subprocess.CompletedProcess(argv,1,b'',str(e).encode())
        return subprocess.CompletedProcess(argv,0,b'RELAY_ANIMATION_OK',b'')
    def test_frames_encoded_and_receipts_retained_without_replay(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process) as proc:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(proc.call_count,5) # build, reopen, one frame batch, encode, probe
            self.assertEqual(sum('frames' in call.args[0] for call in proc.call_args_list),1)
        out=Path(frozen['workspace'])/'delivery';state=json.loads((out/'frames.json').read_text())
        self.assertEqual({v['state'] for v in state['frames'].values()},{'completed'})
        self.assertTrue(all(v['sha256'] for v in state['frames'].values()))
        self.assertFalse(json.loads((out/'execution.json').read_text())['selected'])
        self.assertEqual({p.name for p in out.iterdir()},{'candidate.blend','animation.mp4','preview.png','checkpoint.zip','frames.json','execution.json'})
        with zipfile.ZipFile(out/'checkpoint.zip') as archive:
            self.assertEqual([n for n in archive.namelist() if n.startswith('frames/')],['frames/000001.png'])
        dest=self.root/'expanded';dest.mkdir()
        restore(out/'checkpoint.zip',dest,self.op['execution']['parameters']['manifest_sha256'],self.manifest,100000000)
        self.assertEqual([file_hash(dest/f'frames/{i:06d}.png') for i in (1,2,3)],[state['frames']['1']['sha256']]*3)
    def test_lossless_png_compression_preserves_samples_and_metadata(self):
        def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body))
        samples=(b'\0'+bytes(range(192)))*64
        header=chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0));meta=chunk(b'tEXt',b'test\0retained')
        raw=b'\x89PNG\r\n\x1a\n'+header+meta+chunk(b'IDAT',zlib.compress(samples,0))+chunk(b'IEND',b'')
        p=self.root/'frame.png';p.write_bytes(raw);metadata=compact_png(p,[64,64]);result=p.read_bytes()
        self.assertLess(len(result),len(raw)//4);self.assertEqual([base64.b64decode(v) for v in metadata],[meta])
        self.assertNotIn(meta,result)
        offset=result.index(b'IDAT');size=struct.unpack('>I',result[offset-4:offset])[0]
        self.assertEqual(zlib.decompress(result[offset+4:offset+4+size]),samples)
        digest=file_hash(p);compact_png(p,[64,64]);self.assertEqual(file_hash(p),digest)
        p.write_bytes(raw[:-1]+b'x')
        with self.assertRaisesRegex(ValueError,'checksum'):compact_png(p,[64,64])
        self.assertEqual(p.read_bytes(),raw[:-1]+b'x')
    def test_png_payload_and_dimensions_rejected_before_replace(self):
        def chunk(k,b):return struct.pack('>I',len(b))+k+b+struct.pack('>I',zlib.crc32(k+b))
        for samples in (b'short',b'\0'*(64*193+1)):
            p=self.root/'bad.png';raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(samples))+chunk(b'IEND',b'');p.write_bytes(raw)
            with self.assertRaises(ValueError):compact_png(p,[64,64])
            self.assertEqual(p.read_bytes(),raw)
        with self.assertRaisesRegex(ValueError,'RGB8'):compact_png(p,[128,64])
    def test_checkpoint_dedup_cap_and_tampered_alias(self):
        from orchestrator.blender_animation import checkpoint
        frozen,control=self.frozen()
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):execute(frozen,control)
        root=control/'animation';out=Path(frozen['workspace'])/'delivery';state=json.loads((out/'frames.json').read_text())
        # Distinct frames still count against the identical half-budget cap.
        state['frames']['2']['sha256']='a'*64
        cap=sum((root/p).stat().st_size for p in ('candidate.blend','checks.json','frames.json'))+(root/'frames/000001.png').stat().st_size
        with self.assertRaisesRegex(ValueError,'budget'):checkpoint(root,out,state,cap*2)
        state=json.loads((out/'frames.json').read_text());checkpoint(root,out,state,100000000)
        dest=self.root/'tampered';dest.mkdir()
        with zipfile.ZipFile(out/'checkpoint.zip','a') as archive:archive.writestr('frames/000002.png',b'unlisted duplicate')
        with self.assertRaisesRegex(ValueError,'Unlisted'):restore(out/'checkpoint.zip',dest,self.op['execution']['parameters']['manifest_sha256'],self.manifest,100000000)
    def test_timeout_records_unresolved_intent_and_restore_refuses_replay(self):
        frozen,control=self.frozen()
        def fail(frame,path):
            if frame==2:raise subprocess.TimeoutExpired(['fixture'],1)
        self.frame_handler=fail
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):
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
        self.frame_handler=lambda frame,path:clock.__setitem__(0,1000)
        with patch('orchestrator.blender_animation.time.monotonic',side_effect=lambda:clock[0]),patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        out=Path(frozen['workspace'])/'delivery'
        aid=self.rt.register(out/'checkpoint.zip','Saved partial frames',run='demo',task='app',attempt=frozen['assignment_id'],path='delivery/checkpoint.zip')
        self.rt.db.execute("UPDATE production_attempts SET state='blocked',receipt=? WHERE id=?",(json.dumps({'status':'finished'}),frozen['assignment_id']))
        op=copy.deepcopy(self.op);op['inputs'].append(dict(artifact=aid,path='resume.zip',purpose='Checkpoint',authority='Explicit continuation',media_type='application/zip'))
        bind_registered(self.rt,op);value=plan([op]);value['id']='resume';self.rt.create(value);self.rt.tick('resume')
        s=self.fake.sessions[self.rt.task('resume','app')['latest']];nc=Path(s['session']['control']);nc.mkdir(parents=True)
        rendered=[];self.frame_handler=lambda frame,path:rendered.append(frame)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process) as proc:
            self.assertEqual(execute(s['frozen'],nc)['outcome'],'completed')
        self.assertEqual(rendered,[2,3])
    def test_corrupt_batch_ledger_never_relabels_dispatched_frames_pending(self):
        frozen,control=self.frozen()
        def corrupt(argv,**kwargs):
            if 'frames' in argv:
                (Path(argv[-2])/'frames.json').write_text('{}')
                raise subprocess.TimeoutExpired(argv,1)
            return self.process(argv,**kwargs)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=corrupt):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        out=Path(frozen['workspace'])/'delivery';state=json.loads((out/'frames.json').read_text())
        self.assertEqual({row['state'] for row in state['frames'].values()},{'in_progress'})
        self.assertFalse((out/'animation.mp4').exists())
    def test_wrong_frame_pixels_and_byte_overflow_do_not_encode(self):
        for error in ('pixels','budget'):
            with self.subTest(error=error):
                # Each independent fixture uses its own existing contract/run envelope.
                with tempfile.TemporaryDirectory() as d:
                    from orchestrator.blender_animation import frame_progress
                    root=Path(d);(root/'frames').mkdir()
                    (root/'candidate.blend').write_bytes(b'candidate');(root/'checks.json').write_text('{}')
                    state=dict(version=1,frames={str(f):dict(path=f'frames/{f:06d}.png',state='pending') for f in range(1,4)})
                    (root/'frames.json').write_text(json.dumps(state))
                    batch=dict(assignment='fixture',deadline=10,retained_bytes=1 if error=='budget' else 100000,state_sha256=file_hash(root/'frames.json'))
                    (root/'batch.json').write_text(json.dumps(batch))
                    def render(f,path):path.write_bytes(b'bad' if error=='pixels' else b'\x89PNG\r\n\x1a\n'+b'\x00'*8+struct.pack('>II',64,64))
                    with self.assertRaises(ValueError):render_frames(root,self.manifest,render,clock=lambda:0)
                    retained=frame_progress(root,state,self.manifest,'fixture',100000)
                    self.assertEqual(retained['frames']['1']['state'],'in_progress')
                    self.assertEqual(retained['frames']['2']['state'],'pending')
    def test_batch_parent_rechecks_png_hashes_before_encoding(self):
        frozen,control=self.frozen()
        def corrupt(argv,**kwargs):
            result=self.process(argv,**kwargs)
            if 'frames' in argv:(Path(argv[-2])/'frames/000001.png').write_bytes(b'changed')
            return result
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=corrupt) as proc:
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        self.assertFalse(any(call.args[0][0].endswith('ffmpeg') for call in proc.call_args_list))
    def test_batch_does_not_rewrite_existing_frame(self):
        frozen,control=self.frozen()
        def collide(argv,**kwargs):
            if 'frames' in argv:(Path(argv[-2])/'frames/000001.png').write_bytes(b'existing')
            return self.process(argv,**kwargs)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=collide):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        self.assertEqual((control/'animation/frames/000001.png').read_bytes(),b'existing')
    def test_unresolved_checkpoint_preflight_does_not_consume_an_attempt(self):
        frozen,control=self.frozen()
        def fail(frame,path):raise subprocess.TimeoutExpired(['fixture'],1)
        self.frame_handler=fail
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):execute(frozen,control)
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
