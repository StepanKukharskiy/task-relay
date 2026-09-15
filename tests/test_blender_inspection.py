import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts as c,execution
from orchestrator.runtime import Runtime,file_hash
from orchestrator.step_runner import execute
from tests.test_blender_operations import operation
from tests.test_mixed_execution import operation as text_operation
from tests.test_orchestrator import FakeFactory,plan


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.fake=FakeFactory();self.rt=Runtime(self.root/'runtime',self.fake)
        self.app=patch('task_relay.host_apps.blender',return_value={'available':True,'executable':'/fixture/blender'});self.app.start()
        self.signature=patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/blender'});self.signature.start()

    def tearDown(self):self.signature.stop();self.app.stop();self.rt.close();self.tmp.cleanup()

    def frozen(self):
        self.source=self.root/'original.blend';self.source.write_bytes(b'\x28\xb5\x2f\xfd\xffnative-binary-fixture')
        aid=self.rt.register(self.source,'Selected scene',path='original.blend')
        item=dict(artifact=aid,path='source.blend',purpose='Selected original',authority='Read-only scene',media_type='application/x-blender')
        self.rt.create(plan([operation('blender.inspect',[item])]))
        self.rt.tick('demo');a=self.fake.sessions[self.rt.task('demo','app')['latest']]
        control=Path(a['session']['control']);control.mkdir(parents=True)
        return a['frozen'],control

    def completed(self,argv,**kwargs):
        Path(argv[-1]).write_text(json.dumps({'objects':[{'name':'Fixture'}],'auto_scripts_enabled':False}))
        return subprocess.CompletedProcess(argv,0,b'RELAY_INSPECTION_WRITTEN 1',b'')

    def test_binary_scene_reaches_inspector_without_text_decode_and_keeps_identity(self):
        frozen,control=self.frozen();before=file_hash(self.source)
        with patch('orchestrator.blender_inspection.subprocess.run',side_effect=self.completed) as run:
            details=execute(frozen,control)
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(run.call_count,1)
        self.assertEqual(details['source_sha256'],before);self.assertEqual(file_hash(self.source),before)
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertTrue(receipt['source_unchanged']);self.assertIn('--disable-autoexec',receipt['command'])

    def test_changed_input_or_implementation_stops_before_launch(self):
        frozen,control=self.frozen();frozen['runtime_sources']['blender_inspect.py']='changed'
        with patch('orchestrator.blender_inspection.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'implementation changed'):execute(frozen,control)
            run.assert_not_called()

    def test_probe_crash_is_blocked_with_receipt_and_no_replay(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_inspection.subprocess.run',return_value=subprocess.CompletedProcess([], -11,b'crash',b'')) as run:
            result=execute(frozen,control);self.assertEqual(result['outcome'],'failed')
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(run.call_count,1)
        self.assertEqual(json.loads((Path(frozen['workspace'])/'.relay/result.json').read_text())['decision'],'blocked')

    def test_timeout_is_preserved(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_inspection.subprocess.run',side_effect=subprocess.TimeoutExpired([],1,output=b'partial')):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertTrue(receipt['timeout']);self.assertEqual(receipt['stdout'],'partial')

    def test_invalid_inventory_keeps_failure_receipt(self):
        frozen,control=self.frozen()
        def corrupt(argv,**kwargs):
            result=self.completed(argv,**kwargs)
            Path(argv[-1]).write_text('{broken')
            return result
        with patch('orchestrator.blender_inspection.subprocess.run',side_effect=corrupt):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertIn('validation_error',receipt)

    def test_input_mutation_during_inspection_cannot_pass(self):
        frozen,control=self.frozen()
        def mutate(argv,**kwargs):
            p=Path(argv[-2]);p.chmod(0o600);p.write_bytes(b'changed')
            return self.completed(argv,**kwargs)
        with patch('orchestrator.blender_inspection.subprocess.run',side_effect=mutate):
            self.assertEqual(execute(frozen,control)['outcome'],'failed')

    def test_exactly_one_native_input_required_and_other_operations_stay_text_only(self):
        item=dict(artifact='a',path='source.blend',purpose='scene',authority='source',media_type='application/x-blender')
        a=operation('blender.inspect',[item]);self.assertEqual(c.assignment(a)['execution']['capability'],'blender.inspect')
        a['inputs'].append({**item,'path':'other.blend'})
        with self.assertRaises(ValueError):c.assignment(a)
        with self.assertRaises(ValueError):c.assignment(text_operation('bundle','text.bundle',[item]))

if __name__=='__main__':unittest.main()
