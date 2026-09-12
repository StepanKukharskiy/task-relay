import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts as c, execution
from orchestrator.runtime import Runtime, file_hash
from orchestrator.step_runner import execute
from orchestrator.blender_host import scene
from tests.test_orchestrator import FakeFactory, plan


def scene_data():
    return dict(version=1,objects=[dict(shape='cube',position=[0,0,1],size=[1,1,2],rotation=[0,0,0.3],color=[0.2,0.4,0.8])],
                camera=dict(position=[6,-8,5],target=[0,0,1],scale=5),resolution=[64,64],samples=1)


def operation(cap,inputs):
    spec=execution.REGISTRY[cap]
    return dict(id='app',role='host',objective='Bounded Blender operation',instruction='Only the requested operation',
        execution=dict(capability=cap,version=1,parameters={}),inputs=inputs,
        outputs=[dict(path=p,purpose='Verified local result',media_type=t) for p,t in spec['outputs'].items()],
        criteria=spec['criteria'],tools=[],max_attempts=1)


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.fake=FakeFactory();self.rt=Runtime(self.root/'runtime',self.fake)
        self.app=patch('host_apps.blender',return_value={'available':True,'executable':'/fixture/blender'});self.app.start()
        self.signature=patch('host_evidence.application_signature',return_value={'path':'/fixture/blender'});self.signature.start()

    def tearDown(self):self.signature.stop();self.app.stop();self.rt.close();self.tmp.cleanup()

    def frozen(self,cap):
        src=self.root/'source';src.write_text(json.dumps(scene_data()) if cap=='blender.scene' else 'Check startup')
        aid=self.rt.register(src,'Requested input',path='source.json')
        inp=dict(artifact=aid,path='source.json',purpose='Requested input',authority='Data only',media_type='application/json' if cap=='blender.scene' else 'text/plain')
        self.rt.create(plan([operation(cap,[inp])]))
        self.rt.tick('demo');a=self.fake.sessions[self.rt.task('demo','app')['latest']]
        control=Path(a['session']['control']);control.mkdir(parents=True)
        return a['frozen'],control

    def fake_run(self,argv,**kwargs):
        if '--python-expr' in argv:return subprocess.CompletedProcess(argv,0,b'BLENDER_STARTUP_OK 5.1.2\n',b'')
        out=Path(argv[-1]);mode=argv[argv.index('--')+1]
        if mode=='build':(out/'scene.blend').write_bytes(b'\x28\xb5\x2f\xfdcompressed-blend-fixture');stdout=b'RELAY_SCENE_SAVED'
        else:(out/'preview.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture');stdout=b'RELAY_SCENE_VERIFIED_RENDERED'
        return subprocess.CompletedProcess(argv,0,stdout,b'')

    def test_scene_build_reopen_receipt_and_no_replay(self):
        frozen,control=self.frozen('blender.scene')
        with patch('orchestrator.blender_host.subprocess.run',side_effect=self.fake_run) as run:
            details=execute(frozen,control);self.assertEqual(run.call_count,2)
            self.assertEqual(details['outcome'],'completed')
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(run.call_count,2)
        for out in frozen['outputs']:self.assertTrue((Path(frozen['workspace'])/out['path']).is_file())
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertTrue(receipt['host_execution']);self.assertEqual(len(receipt['runs']),2)

    def test_crash_records_diagnostic_without_claiming_startup_success(self):
        frozen,control=self.frozen('blender.startup')
        with patch('orchestrator.blender_host.subprocess.run',return_value=subprocess.CompletedProcess([], -11,b'crash',b'')):
            details=execute(frozen,control)
        self.assertEqual(details['outcome'],'completed');self.assertIn('startup failed',details['summary'])
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertEqual(receipt['runs'][0]['returncode'],-11);self.assertFalse(receipt['runs'][0]['marker_present'])

    def test_failed_build_does_not_render_or_retry(self):
        frozen,control=self.frozen('blender.scene')
        with patch('orchestrator.blender_host.subprocess.run',return_value=subprocess.CompletedProcess([], -11,b'',b'')) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(run.call_count,1)
        report=json.loads((Path(frozen['workspace'])/'.relay/result.json').read_text());self.assertEqual(report['decision'],'blocked')

    def test_invalid_scene_rejected_before_intent_or_execution(self):
        for mutate in [lambda d:d.update(script='import os'),lambda d:d['objects'][0].update(shape='python'),
                       lambda d:d['objects'][0].update(position=[float('nan'),0,0]),lambda d:d.update(resolution=[99999,2]),
                       lambda d:d.update(objects=d['objects']*501)]:
            data=scene_data();mutate(data)
            with self.assertRaises(ValueError):scene(data)

    def test_changed_input_or_runtime_never_launches(self):
        frozen,control=self.frozen('blender.scene');frozen['runtime_sources']['blender_scene.py']='wrong'
        with patch('orchestrator.blender_host.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'implementation changed'):execute(frozen,control)
            run.assert_not_called()

    def test_timeout_keeps_receipt_and_does_not_retry(self):
        frozen,control=self.frozen('blender.startup')
        with patch('orchestrator.blender_host.subprocess.run',side_effect=subprocess.TimeoutExpired([],1,output=b'partial')) as run:
            execute(frozen,control);self.assertEqual(run.call_count,1)
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertTrue(receipt['runs'][0]['timeout']);self.assertEqual(receipt['runs'][0]['stdout'],'partial')

    def test_arbitrary_command_and_output_paths_are_rejected(self):
        a=operation('blender.startup',[dict(artifact='a',path='source.txt',purpose='probe',authority='data',media_type='text/plain')])
        bad=copy.deepcopy(a);bad['execution']['parameters']={'command':'touch anything'}
        with self.assertRaises(ValueError):c.assignment(bad)
        bad=copy.deepcopy(a);bad['outputs'][0]['path']='other/location.json'
        with self.assertRaises(ValueError):c.assignment(bad)

if __name__=='__main__':unittest.main()
