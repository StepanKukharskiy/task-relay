import copy
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts, execution, host_code, native_apps
from orchestrator.runtime import Runtime, file_hash
from orchestrator.step_runner import execute
from orchestrator.sketchup_contract import MEDIA, compare, validate_checks
from task_relay import host_apps, sketchup_host
from tests.test_blender_operations import operation
from tests.test_orchestrator import FakeFactory, plan


SCRIPT="group = model.entities.add_group\ngroup.name = 'Box'\nface = group.entities.add_face([0,0,0], [100.mm,0,0], [100.mm,200.mm,0], [0,200.mm,0])\nface.reverse! if face.normal.z < 0\nface.pushpull(300.mm)\n"


def checks():
    return dict(version=1,mode='create',changed_entities=[],allow_additions=True,
        expected_entity_count=1,expected_dimensions_mm={'Box':[100,200,300]},preview={'resolution':[64,64]})


def inputs(rt, root, source=None, script=SCRIPT, contract=None):
    params=dict(scene_sha256=None,permissions='unrestricted_host');items=[]
    entries=[('model.rb',script.encode(),'text/x-ruby','script_sha256'),
             ('checks.json',json.dumps(contract or checks()).encode(),'application/json','checks_sha256')]
    if source is not None:entries.append(('source.skp',source,MEDIA,'scene_sha256'))
    for name,data,media,key in entries:
        path=root/name;path.write_bytes(data);aid=rt.register(path,'SketchUp fixture',path=name)
        items.append(dict(artifact=aid,path=name,purpose='Exact selected input',authority='Controlled fixture',media_type=media))
        params[key]=file_hash(path)
    op=operation('sketchup.run_ruby',items);op['execution']['parameters']=params
    return op


def snapshot():
    return dict(entities={'101':dict(type='Group',name='Box',dimensions_mm=[100,200,300],children={})},document={})


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.factory=FakeFactory();self.rt=Runtime(self.root/'runtime',self.factory)
        self.app=patch('task_relay.host_apps.sketchup',return_value=dict(available=True,executable='/fixture/sketchup',version='26.0',evidence='fixture',blocker=None,interpreter='Ruby'));self.app.start()
        self.signature=patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/sketchup'});self.signature.start()
        self.op=inputs(self.rt,self.root)

    def tearDown(self):
        self.signature.stop();self.app.stop();self.rt.close();self.tmp.cleanup()

    def frozen(self,op=None):
        op=op or self.op;self.rt.create(plan([op]))
        if host_code.required(op):
            with self.rt.transaction():host_code.authorize(self.rt,'demo','app',dict(source='controlled_explicit_approval'))
        self.rt.tick('demo');task=self.rt.task('demo','app');entry=self.factory.sessions[task['latest']]
        control=Path(entry['session']['control']);control.mkdir(parents=True)
        return entry['frozen'],control

    def fake_run(self, executable, script, request_path, timeout, platform):
        request=json.loads(Path(request_path).read_text());out=Path(request['out']);mode=request['mode'];details={}
        if mode in ('before','verify','inspect'):
            snap=dict(entities={},document={}) if mode=='before' else snapshot()
            Path(request['snapshot']).write_text(json.dumps(snap));details['snapshot_sha256']=file_hash(request['snapshot'])
        if mode=='model':(out/'candidate.skp').write_bytes(b'\xffcontrolled-native-fixture')
        if mode=='verify':(out/'preview.png').write_bytes(b'\x89PNG\r\n\x1a\n0000IHDR'+struct.pack('>II',64,64))
        if mode in ('model','verify'):details['candidate_sha256']=file_hash(out/'candidate.skp')
        return dict(passed=True,worker=dict(passed=True,details=details),returncode=0)

    def test_create_runs_three_phases_and_never_replays(self):
        frozen,control=self.frozen()
        with patch('task_relay.sketchup_host.run',side_effect=self.fake_run) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaisesRegex(ValueError,'replay'):execute(frozen,control)
            self.assertEqual(run.call_count,3)
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertFalse(receipt['lineage']['selected'])
        self.assertTrue(json.loads((Path(frozen['workspace'])/'delivery/checks.json').read_text())['passed'])

    def test_ruby_failure_stops_before_verify_and_retains_failure(self):
        frozen,control=self.frozen()
        def run(*args):
            if json.loads(Path(args[2]).read_text())['mode']=='model':return dict(passed=False,error='Ruby: undefined method',worker=None)
            return self.fake_run(*args)
        with patch('task_relay.sketchup_host.run',side_effect=run) as calls:
            result=execute(frozen,control)
            self.assertEqual(result['outcome'],'failed');self.assertIn('undefined method',result['summary'])
            self.assertEqual(calls.call_count,2)
            with self.assertRaisesRegex(ValueError,'replay'):execute(frozen,control)

    def test_candidate_or_baseline_tampering_blocks_verification(self):
        for tamper in ('candidate','baseline'):
            with self.subTest(tamper=tamper):
                # Independent fixture runtimes preserve each receipt.
                self.rt.close();self.rt=Runtime(self.root/('runtime-'+tamper),self.factory)
                self.op=inputs(self.rt,self.root);frozen,control=self.frozen()
                def run(*args):
                    r=json.loads(Path(args[2]).read_text());result=self.fake_run(*args)
                    if r['mode']=='verify':
                        target=Path(r['out'])/'candidate.skp' if tamper=='candidate' else control/'sketchup-before/snapshot.json'
                        target.write_bytes(b'changed')
                    return result
                with patch('task_relay.sketchup_host.run',side_effect=run):
                    self.assertEqual(execute(frozen,control)['outcome'],'failed')

    def test_app_drift_blocks_without_launch(self):
        frozen,control=self.frozen()
        with patch('task_relay.host_apps.sketchup',return_value=dict(available=True,executable='/fixture/sketchup',version='26.1')),patch('task_relay.sketchup_host.run') as run:
            with self.assertRaisesRegex(ValueError,'changed'):execute(frozen,control)
            run.assert_not_called()

    def test_missing_authorization_blocks_dispatch(self):
        self.rt.create(plan([self.op]));self.rt.tick('demo')
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.rt.task('demo','app')['attempts'],0)

    def test_future_inputs_and_mismatched_create_edit_rejected(self):
        op=copy.deepcopy(self.op);op['inputs'][0].pop('artifact');op['inputs'][0].update(from_task='future',output='model.rb')
        with self.assertRaisesRegex(ValueError,'registered'):contracts.assignment(op)
        contract=checks();contract['mode']='edit'
        op=inputs(self.rt,self.root,contract=contract)
        with self.assertRaisesRegex(ValueError,'mode'):host_code.binding(self.rt,op)

    def test_independent_checks_detect_wrong_dimensions_and_preservation(self):
        before=snapshot();after=copy.deepcopy(before);contract=checks();contract.update(mode='edit',allow_additions=False)
        after['entities']['101']['dimensions_mm']=[100,200,301]
        errors=compare(before,after,contract)
        self.assertTrue(any('Untouched' in e for e in errors))
        from orchestrator.sketchup_contract import dimension_warnings
        self.assertTrue(dimension_warnings(after,contract))
        contract['changed_entities']=['101']
        self.assertEqual(compare(before,after,contract),[])
        after['entities']['101']['dimensions_mm']=[100,float('nan'),300]
        self.assertTrue(any('invalid dimension measurement' in e for e in compare(before,after,contract)))
        after=copy.deepcopy(before);after['document']['tags']={'changed':True}
        self.assertTrue(any('document' in e for e in compare(before,after,contract)))

    def test_existing_session_and_mismatched_reply_never_execute(self):
        request=self.root/'request.json';request.write_text(json.dumps(dict(token='one',mode='model')))
        with patch.object(sketchup_host,'running_instances',return_value=[123]),patch.object(sketchup_host.subprocess,'Popen') as launch:
            result=sketchup_host._run('/fixture/sketchup',self.root/'launch.rb',request,1,'darwin')
            self.assertFalse(result['launched']);launch.assert_not_called()
        response=self.root/'reply.json';response.write_text(json.dumps(dict(pid=123,token='other',mode='model',passed=True)))
        self.assertIsNone(sketchup_host.reply(response,123,dict(token='one',mode='model')))

    def test_lost_model_receipt_is_uncertain_and_never_replayed(self):
        from orchestrator.adapters import RegisteredFactory, CodexFactory
        frozen,control=self.frozen()
        def run(*args):
            if json.loads(Path(args[2]).read_text())['mode']=='model':
                return dict(passed=False,launched=True,worker=None,error='Owned process exited without receipt')
            return self.fake_run(*args)
        with patch('task_relay.sketchup_host.run',side_effect=run) as calls:
            self.assertEqual(execute(frozen,control)['outcome'],'uncertain')
            with self.assertRaisesRegex(ValueError,'replay'):execute(frozen,control)
            self.assertEqual(calls.call_count,2)
        session=dict(control=str(control),execution=frozen['execution'])
        with patch.object(CodexFactory,'inspect',return_value=dict(status='finished',exit_code=1)):
            result=RegisteredFactory().inspect(session)
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(result['external_outcome'],'unknown')

    def test_interrupted_intent_is_uncertain_on_recovery(self):
        from orchestrator.adapters import RegisteredFactory, CodexFactory
        control=self.root/'interrupted';control.mkdir()
        (control/'sketchup-intent.json').write_text('{}')
        session=dict(control=str(control),execution=self.op['execution'])
        with patch.object(CodexFactory,'inspect',return_value=dict(status='finished',exit_code=1)):
            result=RegisteredFactory().inspect(session)
        self.assertEqual(result['status'],'uncertain')
        self.assertTrue(result['local_terminal'])

    def test_startup_timeout_kills_only_owned_process(self):
        from unittest.mock import Mock
        request=self.root/'timeout.json';request.write_text(json.dumps(dict(token='one',mode='startup')))
        process=Mock(pid=100,returncode=-9)
        process.poll.return_value=None
        with patch.object(sketchup_host,'running_instances',return_value=[]),patch.object(sketchup_host.subprocess,'Popen',return_value=process) as launch:
            result=sketchup_host._run('/fixture/sketchup',self.root/'launch.rb',request,0,'darwin')
        self.assertFalse(result['passed']);self.assertTrue(result['timeout'])
        process.kill.assert_called_once_with();process.wait.assert_called_once_with(timeout=5)
        launch.assert_called_once()

    def test_inspect_binary_model_does_not_decode_or_modify(self):
        path=self.root/'source.skp';path.write_bytes(b'\xffnative');aid=self.rt.register(path,'source',path='source.skp')
        op=operation('sketchup.inspect',[dict(artifact=aid,path='source.skp',media_type=MEDIA,purpose='inspect',authority='fixture')])
        frozen,control=self.frozen(op)
        with patch('task_relay.sketchup_host.run',side_effect=self.fake_run):
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
        self.assertEqual(path.read_bytes(),b'\xffnative')


class DiscoveryTests(unittest.TestCase):
    def test_discovery_override_access_and_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);contents=root/'SketchUp 2026/SketchUp.app/Contents';(contents/'MacOS').mkdir(parents=True)
            executable=contents/'MacOS/SketchUp';executable.write_text('fixture');executable.chmod(0o700)
            (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'26.0.1'}))
            with patch.object(host_apps,'APPLICATIONS',root),patch('task_relay.app_access.enabled',return_value=True),patch('subprocess.Popen',side_effect=AssertionError('Discovery cannot launch')):
                self.assertTrue(host_apps.sketchup({},'darwin')['available'])
                self.assertFalse(host_apps.sketchup({'TASK_RELAY_SKETCHUP':'/missing'},'darwin')['available'])
                self.assertFalse(host_apps.sketchup({'TASK_RELAY_SKETCHUP':str(executable)},'win32')['available'])
            with patch('task_relay.app_access.enabled',return_value=False):
                self.assertFalse(host_apps.sketchup({'TASK_RELAY_SKETCHUP':str(executable)},'darwin')['available'])

    def test_unknown_native_app_has_no_blender_fallback(self):
        with self.assertRaisesRegex(ValueError,'no fallback'):native_apps.profile('unknown.run')

    def test_catalog_uses_sketchup_availability_independently(self):
        with patch('task_relay.host_apps.blender',return_value=dict(available=True,evidence='fixture')):
            with patch('task_relay.host_apps.sketchup',return_value=dict(available=False,evidence='missing',blocker='missing',version=None,interpreter='Ruby')):
                self.assertFalse(next(i for i in execution.catalog() if i['id']=='sketchup.run_ruby')['available'])
