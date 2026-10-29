import copy
import json
from pathlib import Path
import tempfile
import unittest
from orchestrator.contracts import digest
from orchestrator.operation_inspection import native_effect


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.control=self.root/'control';self.control.mkdir()
        self.workspace=self.root/'workspace';(self.workspace/'.relay').mkdir(parents=True)
        self.execution=dict(capability='hyperframes.preview',version=1,parameters={})
        self.frozen=dict(assignment_id='a',execution=self.execution,inputs=[],media_runtime={'id':'fixture'},limits={'seconds':5})
        self.write(self.workspace/'.relay/ASSIGNMENT.json',self.frozen)
        self.write('launch.json',dict(token='a',workspace=str(self.workspace),execution=self.execution))
        self.write('done.json',dict(token='a',exit_code=1,reason=None,finished=20))
        self.write('operation-dispatch.json',dict(binding=digest(self.frozen)))
        self.intent=dict(capability='hyperframes.preview',assignment='a',passed=False,selected=False,input_versions=[],runtime={'id':'fixture'},limits={'seconds':5})
        self.write('hyperframes-intent.json',self.intent)
        self.details=dict(self.intent,outcome='failed',reason='missing timeline',recorded_at=19)
        self.write('operation.json',self.details)
        self.write('hyperframes-work/command-1/guard.json',{})
        self.write('hyperframes-work/command-1/outcome.json',{'returncode':1})

    def write(self,name,value):
        path=self.control/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path

    def inspect(self):
        result=dict(status='finished',execution=self.execution)
        native_effect(self.control,result,copy.deepcopy(self.details));return result

    def test_exact_stopped_failure_is_observed_without_writing_or_dispatch(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.inspect()
        self.assertEqual(result['status'],'finished');self.assertTrue(result['operation_terminal_confirmed'])
        self.assertFalse(result['local_failure_binding']['replayed'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_ambiguous_or_changed_evidence_stays_uncertain(self):
        for name,value in [('done.json',dict(token='a',exit_code=1,reason=None)),
            ('done.json',dict(token='other',exit_code=1,reason=None,finished=20)),
            ('done.json',dict(token='a',exit_code=0,reason=None,finished=20)),
            ('operation-dispatch.json',dict(binding='changed')),
            ('hyperframes-work/command-1/outcome.json',dict(error='cleanup failed')),
            ('hyperframes-work/command-1/outcome.json',dict(returncode=0)),
            ('hyperframes-intent.json',{**self.intent,'input_versions':[{'artifact':'changed'}]})]:
            with self.subTest(name=name,value=value):
                path=self.control/name;before=path.read_bytes();self.write(name,value)
                self.assertEqual(self.inspect()['status'],'uncertain');path.write_bytes(before)
        path=self.control/'hyperframes-work/command-1/outcome.json';path.unlink()
        self.assertEqual(self.inspect()['status'],'uncertain')

    def test_mismatched_execution_or_success_never_uses_compatibility(self):
        for change in ({'execution':{}},{'outcome':'completed'},{'passed':True},{'capability':'blender.animate'}):
            original=self.details;self.details={**original,**change}
            self.assertEqual(self.inspect()['status'],'uncertain');self.details=original

    def test_new_bound_failure_needs_no_legacy_inference(self):
        self.details['execution']=self.execution
        result=self.inspect();self.assertTrue(result['operation_terminal_confirmed'])
        self.assertNotIn('local_failure_binding',result)
