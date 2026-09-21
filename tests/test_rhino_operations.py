import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts as c, execution, host_code
from orchestrator.runtime import Runtime, file_hash
from orchestrator.step_runner import execute
from orchestrator.rhino_contract import compare, dimension_warnings, validate_checks, MEDIA
from tests.test_blender_operations import operation
from tests.test_orchestrator import FakeFactory, plan


CREATE_SCRIPT = '''import Rhino
box = Rhino.Geometry.BoundingBox(Rhino.Geometry.Point3d(0,0,0), Rhino.Geometry.Point3d(2,3,4))
attributes = Rhino.DocObjects.ObjectAttributes()
attributes.Name = "Tower"
doc.Objects.AddBrep(Rhino.Geometry.Brep.CreateFromBox(box), attributes)
'''


def checks():
    return dict(mode='create', units='Meters', changed_objects=[], allow_additions=True,
                expected_object_count=1, expected_dimensions={'Tower':[2,3,4]}, preview={'resolution':[128,128]})


def inputs(rt, root, source=None, script=CREATE_SCRIPT, contract=None):
    result = []
    params = {'scene_sha256':None, 'permissions':'unrestricted_host'}
    entries = [('model.py',script.encode(),'text/x-python','script_sha256'),
               ('checks.json',json.dumps(contract or checks()).encode(),'application/json','checks_sha256')]
    if source is not None:entries.append(('source.3dm',source,MEDIA,'scene_sha256'))
    for name, data, media, key in entries:
        path = root/name;path.write_bytes(data)
        aid = rt.register(path,'Exact Rhino test input',path=name)
        result.append(dict(artifact=aid,path=name,purpose='Selected Rhino input',authority='Explicit test version',media_type=media))
        params[key] = file_hash(path)
    op = operation('rhino.run_python',result)
    op['execution']['parameters'] = params
    return op


class Tests(unittest.TestCase):
    def test_dimension_difference_is_advisory_with_expected_measured_and_tolerance(self):
        contract=checks()
        after=dict(objects={'one':dict(name='Tower',dimensions=[1.9,3,4],valid=True)},units='Meters',tolerance=.001,named_views={})
        self.assertEqual(compare({'objects':{}},after,contract),[])
        warnings=dimension_warnings(after,contract)
        self.assertEqual(len(warnings),1)
        for detail in ('Tower','expected XYZ=[2, 3, 4]','measured XYZ=[1.9, 3, 4]','tolerance XYZ=','Meters'):
            self.assertIn(detail,warnings[0])
        self.assertEqual(contract['expected_dimensions']['Tower'],[2,3,4])
        after['objects']['one']['dimensions']=[2.0005,3,4]
        self.assertEqual(compare({'objects':{}},after,contract),[])
        self.assertEqual(dimension_warnings(after,contract),[])

    def test_worker_keeps_preview_on_size_warning_but_blocks_invalid_geometry(self):
        from types import SimpleNamespace as NS
        from orchestrator import rhino_worker, rhino_contract
        out=self.root/'verify';out.mkdir()
        (out/'candidate.3dm').write_bytes(b'native fixture')
        baseline=self.root/'baseline.json';baseline.write_text('{"objects":{}}')
        contract=self.root/'verify-input.json';contract.write_text(json.dumps(checks()))
        doc=NS(Dispose=lambda:None)
        rhino=NS(RhinoApp=NS(Version=NS(Major=8)),RhinoDoc=NS(OpenHeadless=lambda _:doc))
        after=dict(objects={'one':dict(name='Tower',dimensions=[1.9,3,4],valid=True)},units='Meters',tolerance=.001,named_views={},dependencies=[])
        request=dict(mode='verify',out=str(out),baseline=str(baseline),checks=str(contract),source=None,rhino_major=8)
        with patch.dict('sys.modules',{'Rhino':rhino,'scriptcontext':NS(),'rhinoscriptsyntax':NS(),'rhino_contract':rhino_contract}),patch.object(rhino_worker,'snapshot',return_value=after),patch.object(rhino_worker,'preview') as preview:
            result=rhino_worker.perform(request)
            preview.assert_called_once()
            self.assertEqual(result['candidate_sha256'],file_hash(out/'candidate.3dm'))
            report=json.loads((out/'checks.json').read_text())
            self.assertTrue(report['passed']);self.assertEqual(report['errors'],[]);self.assertEqual(len(report['warnings']),1)
            (out/'checks.json').unlink();preview.reset_mock();after['objects']['one']['valid']=False
            with self.assertRaisesRegex(ValueError,'invalid geometry'):rhino_worker.perform(request)
            preview.assert_not_called()
            self.assertFalse(json.loads((out/'checks.json').read_text())['passed'])

    def test_usable_model_reports_quality_findings_for_user_review(self):
        from task_relay.production_activity import snapshot, lines
        frozen,control=self.frozen()
        warning='Dimensions differ: Tower; expected XYZ=[2, 3, 4], measured XYZ=[1.9, 3, 4] Meters'
        def native(*args):
            result=self.fake_run(*args)
            request=json.loads(Path(args[2]).read_text())
            if request['mode']=='verify':
                (Path(request['out'])/'checks.json').write_text(json.dumps(dict(passed=True,warnings=[warning])))
            return result
        with patch('task_relay.rhino_host.run',side_effect=native):result=execute(frozen,control)
        self.assertEqual(result['outcome'],'completed');self.assertEqual(result['warnings'],[warning])
        report=json.loads((Path(frozen['workspace'])/'.relay/result.json').read_text())
        self.assertEqual(report['decision'],'delivered')
        from orchestrator.outcomes import disposition
        self.assertEqual(disposition(report['findings']),'user_review')
        self.assertIn('user review required',report['summary'])
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertTrue(receipt['passed']);self.assertEqual(receipt['warnings'],[warning])
        attempt=dict(id=frozen['assignment_id'],frozen=json.dumps(frozen),receipt=json.dumps(dict(status='finished',operation=result)),state='completed')
        activity=snapshot(self.rt.root,attempt,self.op,frozen['backend'])
        self.assertIn('Warning: '+warning,lines(dict(status='completed',activity=activity,latest_attempt=attempt['id'])))

    def test_snapshot_checks_hidden_and_locked_geometry_and_hidden_references(self):
        import types
        from orchestrator.rhino_worker import snapshot
        ns=types.SimpleNamespace
        class Settings:
            HiddenObjects=False;LockedObjects=True;NormalObjects=True;ReferenceObjects=False;VisibleFilter=False
        vector=ns(X=1,Y=2,Z=3)
        box=ns(IsValid=True,Min=vector,Max=vector,Diagonal=vector)
        def obj(ident,name,hidden=False,locked=False,reference=False):
            return ns(Id=ident,IsDeleted=False,Geometry=ns(IsValid=True,GetBoundingBox=lambda _:box,UserData=ns(Count=0)),
                      Attributes=ns(Name=name,LayerIndex=0,MaterialIndex=-1,UserData=ns(Count=0)),
                      ObjectType='Brep',IsReference=reference,hidden=hidden,locked=locked)
        objects=[obj('visible','Visible'),obj('hidden','Zone',hidden=True),obj('locked','Locked',locked=True),
                 obj('ref','HiddenReference',hidden=True,reference=True)]
        def enumerate_objects(settings):
            if not isinstance(settings,Settings):return objects[:1] # SDK ObjectType overload omits hidden geometry
            return [o for o in objects if (not o.hidden or settings.HiddenObjects) and (not o.locked or settings.LockedObjects)
                    and (not o.IsReference or settings.ReferenceObjects)]
        doc=ns(Objects=ns(GetObjectList=enumerate_objects),Materials=[],Layers=[],NamedViews=[],InstanceDefinitions=[],
               ModelUnitSystem='Meters',ModelAbsoluteTolerance=.001,ModelAngleToleranceRadians=.01)
        rhino=ns(DocObjects=ns(ObjectEnumeratorSettings=Settings,ObjectType=ns(AnyObject=0,InstanceReference='InstanceReference')),RhinoApp=ns(Version='fixture'))
        with patch.dict('sys.modules',{'Rhino':rhino}),patch('orchestrator.rhino_worker.fingerprint',return_value='fixed'):
            result=snapshot(doc)
        self.assertEqual({o['name'] for o in result['objects'].values()},{'Visible','Zone','Locked','HiddenReference'})
        self.assertEqual(result['dependencies'],[{'kind':'reference_or_block','object':'ref'}])
        contract=checks();contract.update(expected_object_count=4,expected_dimensions={'Zone':[1,2,3]})
        self.assertEqual(compare({'objects':{}},result,contract),[])
        result['objects']['duplicate']=dict(result['objects']['hidden'])
        self.assertIn('Expected object name is missing or ambiguous: Zone',compare({'objects':{}},result,contract))

    def test_preview_named_view_is_required_in_reopened_scene(self):
        contract=checks();contract['preview']['named_view']='FacadeSheet';validate_checks(contract)
        snap=dict(objects={'one':dict(name='Tower',dimensions=[2,3,4],valid=True)},units='Meters',tolerance=.001,named_views={})
        self.assertIn('Preview named view is missing: FacadeSheet',compare({'objects':{}},snap,contract))
        snap['named_views']['FacadeSheet']='orthographic camera'
        self.assertEqual(compare({'objects':{}},snap,contract),[])
        contract['preview']['named_view']=''
        with self.assertRaises(ValueError):validate_checks(contract)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.fake=FakeFactory();self.rt=Runtime(self.root/'runtime',self.fake)
        self.app=patch('task_relay.host_apps.rhino',return_value=dict(available=True,executable='/fixture/rhino',evidence='fixture'));self.app.start()
        self.signature=patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/rhino'});self.signature.start()
        self.op=inputs(self.rt,self.root)

    def tearDown(self):self.signature.stop();self.app.stop();self.rt.close();self.tmp.cleanup()

    def frozen(self, op=None):
        op=op or self.op
        self.rt.create(plan([op]))
        if host_code.required(op):
            with self.rt.transaction():host_code.authorize(self.rt,'demo','app',{'source':'controlled_test_explicit_approval'})
        self.rt.tick('demo');a=self.fake.sessions[self.rt.task('demo','app')['latest']]
        control=Path(a['session']['control']);control.mkdir(parents=True)
        return a['frozen'],control

    def fake_run(self, executable, script, request_path, timeout, platform):
        r=json.loads(Path(request_path).read_text());out=Path(r['out']);mode=r['mode']
        details={}
        if mode=='before':Path(r['baseline']).write_text('{"objects":{}}')
        elif mode=='model':(out/'candidate.3dm').write_bytes(b'\xffnative-rhino')
        elif mode=='inspect':(out/'inspection.json').write_text('{"objects":{}}')
        elif mode=='verify':
            (out/'checks.json').write_text('{"passed":true}')
            (out/'preview.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            details['candidate_sha256']=file_hash(out/'candidate.3dm')
        return dict(passed=True,returncode=0,worker=dict(passed=True,details=details))

    def render_op(self):
        args=[]
        for name,blob,media in [('source.3dm',b'\xffnative',MEDIA),('render.json',json.dumps(dict(version=1,engine='rhino_render',named_view='Overview',resolution=[64,64])).encode(),'application/json')]:
            p=self.root/name;p.write_bytes(blob);aid=self.rt.register(p,'Selected render input',path=name)
            args.append(dict(artifact=aid,path=name,purpose='Render',authority='Test fixture',media_type=media))
        op=operation('rhino.render',args);op['execution']['parameters']={'manifest_sha256':file_hash(self.root/'render.json')}
        return op

    def test_render_checks_dimensions_hashes_and_no_replay(self):
        import struct
        frozen,control=self.frozen(self.render_op())
        def run(*args):
            r=json.loads(Path(args[2]).read_text());self.assertEqual(r['mode'],'render');out=Path(r['out'])
            (out/'render.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'0000IHDR'+struct.pack('>II',64,64))
            sha=file_hash(out/'render.png')
            (out/'checks.json').write_text(json.dumps(dict(passed=True,engine='rhino_render',render_sha256=sha)))
            return dict(passed=True,worker=dict(details=dict(render_sha256=sha)))
        with patch('task_relay.rhino_host.run',side_effect=run) as calls:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaisesRegex(ValueError,'replay'):execute(frozen,control)
            self.assertEqual(calls.call_count,1)

    def test_render_timeout_never_substitutes_preview_or_retries(self):
        frozen,control=self.frozen(self.render_op())
        with patch('task_relay.rhino_host.run',return_value=dict(passed=False,timeout=True)) as calls:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(calls.call_count,1)
        self.assertFalse((Path(frozen['workspace'])/'delivery/render.png').exists())

    def test_model_exception_reaches_result_without_verification_or_replay(self):
        frozen,control=self.frozen()
        def run(*args):
            request=json.loads(Path(args[2]).read_text())
            if request['mode']=='before':return self.fake_run(*args)
            return dict(passed=False,returncode=1,worker={'error':"Traceback (most recent call last):\n  File 'model.py', line 270\nAttributeError: 'RhinoViewport' object has no attribute 'SetCameraUp'\n"})
        with patch('task_relay.rhino_host.run',side_effect=run) as calls:
            result=execute(frozen,control)
            self.assertEqual(result['outcome'],'failed')
            self.assertIn("AttributeError: 'RhinoViewport' object has no attribute 'SetCameraUp'",result['summary'])
            with self.assertRaisesRegex(ValueError,'replay'):execute(frozen,control)
            self.assertEqual(calls.call_count,2)
        saved=json.loads((Path(frozen['workspace'])/'.relay/result.json').read_text())
        self.assertEqual(saved['decision'],'blocked');self.assertIn('SetCameraUp',saved['checks'][0]['evidence'])

    def test_render_manifest_drift_and_future_inputs_block_dispatch(self):
        from orchestrator.rhino_render import bind_registered
        op=self.render_op();op['execution']['parameters']['manifest_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'manifest hash'):bind_registered(self.rt,op)
        op['inputs'][0].pop('artifact');op['inputs'][0].update(from_task='future',output='delivery/candidate.3dm')
        with self.assertRaisesRegex(ValueError,'registered'):c.assignment(op)

    def test_wrong_render_dimensions_cannot_pass(self):
        frozen,control=self.frozen(self.render_op())
        def run(*args):
            r=json.loads(Path(args[2]).read_text());out=Path(r['out'])
            (out/'render.png').write_bytes(b'\x89PNG\r\n\x1a\ninvalid')
            (out/'checks.json').write_text('{"passed":true}')
            return dict(passed=True,worker=dict(details={}))
        with patch('task_relay.rhino_host.run',side_effect=run):self.assertEqual(execute(frozen,control)['outcome'],'failed')

    def test_changed_worker_between_phases_stops_before_modeling(self):
        frozen,control=self.frozen()
        def run(*args):
            value=self.fake_run(*args)
            frozen['runtime_sources']['rhino_worker.py']='changed-after-baseline'
            return value
        with patch('task_relay.rhino_host.run',side_effect=run) as calls:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(calls.call_count,1)
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertIn('between phases',receipt['validation_error'])

    def test_source_loader_preserves_encoding_declaration(self):
        from orchestrator.rhino_worker import load_code
        p=self.root/'utf8.py';p.write_bytes('# -*- coding: utf-8 -*-\nname = u"façade"\n'.encode('utf-8'))
        scope={};eval(load_code(str(p)),scope);self.assertEqual(scope['name'],'façade')

    def test_runtime_version_drift_blocks_even_with_same_executable(self):
        frozen,control=self.frozen()
        with patch('task_relay.host_apps.rhino',return_value=dict(available=True,executable='/fixture/rhino',evidence='fixture',major=7,version='7.32')),patch('task_relay.rhino_host.run') as run:
            with self.assertRaisesRegex(ValueError,'version changed'):execute(frozen,control)
            run.assert_not_called()

    def test_python2_script_approval_uses_selected_legacy_runtime(self):
        p=self.root/'legacy';p.mkdir()
        op=inputs(self.rt,p,script='print "legacy fixture"\n')
        with patch('task_relay.host_apps.rhino',return_value=dict(available=True,executable='/fixture/rhino',evidence='fixture',major=7,version='7.32')):
            self.assertEqual(host_code.binding(self.rt,op)['rhino_runtime']['major'],7)
        with self.assertRaises(SyntaxError):host_code.binding(self.rt,op)

    def test_no_approval_blocks_without_attempt(self):
        self.rt.create(plan([self.op]));self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','app')['attempts'],0);self.assertEqual(self.fake.calls,[])

    def test_create_reopens_candidate_and_preserves_lineage_without_replay(self):
        frozen,control=self.frozen()
        with patch('task_relay.rhino_host.run',side_effect=self.fake_run) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaisesRegex(ValueError,'replay'):execute(frozen,control)
            self.assertEqual(run.call_count,3)
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertIsNone(receipt['lineage']['source_scene_sha256']);self.assertFalse(receipt['lineage']['selected'])

    def test_binary_inspection_input_is_not_decoded_as_text(self):
        p=self.root/'native.3dm';p.write_bytes(b'\xffnative')
        aid=self.rt.register(p,'Selected native',path=p.name)
        op=operation('rhino.inspect',[dict(artifact=aid,path=p.name,purpose='Inspect',authority='Selected',media_type=MEDIA)])
        frozen,control=self.frozen(op)
        with patch('task_relay.rhino_host.run',side_effect=self.fake_run):
            self.assertEqual(execute(frozen,control)['outcome'],'completed')

    def test_failed_startup_is_a_diagnostic_not_successful_startup(self):
        p=self.root/'request.txt';p.write_text('Check Rhino startup')
        aid=self.rt.register(p,'Request',path=p.name)
        frozen,control=self.frozen(operation('rhino.startup',[dict(artifact=aid,path=p.name,purpose='Request',authority='User',media_type='text/plain')]))
        with patch('task_relay.rhino_host.run',return_value=dict(passed=False,timeout=True,returncode=-9)):
            result=execute(frozen,control)
        self.assertEqual(result['outcome'],'completed');self.assertIn('startup failed',result['summary'])
        self.assertFalse(json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())['passed'])

    def test_crash_stops_before_verification_and_retains_receipt(self):
        frozen,control=self.frozen()
        def run(*args):
            if json.loads(Path(args[2]).read_text())['mode']=='model':return dict(passed=False,returncode=-11)
            return self.fake_run(*args)
        with patch('task_relay.rhino_host.run',side_effect=run) as calls:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(calls.call_count,2)
        self.assertTrue((control/'rhino-intent.json').exists())

    def test_changed_baseline_stops_before_verification(self):
        frozen,control=self.frozen()
        def run(*args):
            value=self.fake_run(*args);r=json.loads(Path(args[2]).read_text())
            if r['mode']=='model':Path(r['baseline']).write_text('{}')
            return value
        with patch('task_relay.rhino_host.run',side_effect=run) as calls:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(calls.call_count,2)

    def test_changed_input_blocks_before_launch(self):
        frozen,control=self.frozen();p=Path(frozen['workspace'])/'model.py';p.chmod(0o600);p.write_text('changed')
        with patch('task_relay.rhino_host.run') as run:
            with self.assertRaisesRegex(ValueError,'content changed'):execute(frozen,control)
            run.assert_not_called()

    def test_changed_adapter_blocks_before_launch(self):
        frozen,control=self.frozen();frozen['rhino_host_sources']={}
        with patch('task_relay.rhino_host.run') as run:
            with self.assertRaisesRegex(ValueError,'adapter changed'):execute(frozen,control)
            run.assert_not_called()

    def test_changed_frozen_approval_blocks_before_launch(self):
        frozen,control=self.frozen();frozen['limits']['seconds']-=1
        with patch('task_relay.rhino_host.run') as run:
            with self.assertRaisesRegex(ValueError,'assignment changed'):execute(frozen,control)
            run.assert_not_called()

    def test_uncertain_dispatch_and_cancel_do_not_relaunch(self):
        self.rt.create(plan([self.op]))
        with self.rt.transaction():host_code.authorize(self.rt,'demo','app',{'source':'controlled_test_explicit_approval'})
        self.fake.fail=True;self.rt.tick('demo');self.rt.tick('demo');self.rt.cancel('demo');self.rt.tick('demo')
        self.assertEqual(len(self.fake.calls),1);self.assertEqual(self.rt.task('demo','app')['attempts'],1)

    def test_approval_survives_restart_but_rejects_changed_code(self):
        self.rt.create(plan([self.op]))
        with self.rt.transaction():host_code.authorize(self.rt,'demo','app',{'source':'controlled_test_explicit_approval'})
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.fake)
        spec=self.rt.spec(self.rt.task('demo','app'));self.assertTrue(host_code.approved(self.rt,'demo','app',spec))
        p=Path(self.rt.artifact(spec['inputs'][0]['artifact'])['blob']);p.chmod(0o600);p.write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):host_code.approved(self.rt,'demo','app',spec)

    def test_future_code_undeclared_source_and_gh_are_rejected(self):
        op=copy.deepcopy(self.op);op['inputs'][0].pop('artifact');op['inputs'][0].update(from_task='producer',output='model.py')
        with self.assertRaisesRegex(ValueError,'already registered'):c.assignment(op)
        op=copy.deepcopy(self.op);op['execution']['parameters']['scene_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'scene only'):c.assignment(op)
        op=copy.deepcopy(self.op);op['execution']['capability']='grasshopper.run_python'
        with self.assertRaisesRegex(ValueError,'Unknown capability'):c.assignment(op)

    def test_checks_mode_must_match_create_or_edit_source(self):
        op=copy.deepcopy(self.op);contract=checks();contract['mode']='edit'
        p=self.root/'edit-checks.json';p.write_text(json.dumps(contract))
        aid=self.rt.register(p,'Checks',path=p.name)
        op['inputs'][1]['artifact']=aid;op['execution']['parameters']['checks_sha256']=file_hash(p)
        with self.assertRaisesRegex(ValueError,'mode'):host_code.binding(self.rt,op)

    def test_preservation_detects_undeclared_changes_and_dimension_failure(self):
        contract=checks();contract.update(mode='edit',allow_additions=False)
        before=dict(objects={'object':dict(name='Tower',dimensions=[2,3,4],valid=True,geometry_sha256='old')},units='Meters',tolerance=.001,angle_tolerance=.01,layers={},materials={},named_views={})
        after=copy.deepcopy(before);self.assertEqual(compare(before,after,contract),[])
        after['objects']['object']['geometry_sha256']='new';after['objects']['object']['dimensions']=[2,3,6];after['layers']={'unexpected':'layer'}
        errors=compare(before,after,contract)
        self.assertTrue(any('Untouched' in e for e in errors));self.assertTrue(dimension_warnings(after,contract));self.assertTrue(any('layers' in e for e in errors))

    def test_invalid_bounds_rejected(self):
        contract=checks();contract['expected_dimensions']['Tower'][0]=float('nan')
        with self.assertRaises(ValueError):validate_checks(contract)

    def test_render_camera_requirement_fails_before_candidate_acceptance(self):
        contract=checks();contract['expected_named_views']=['Overview'];validate_checks(contract)
        snap=dict(objects={'one':dict(name='Tower',dimensions=[2,3,4],valid=True)},units='Meters',tolerance=.001,named_views={})
        self.assertIn('Expected render named view is missing: Overview',compare(dict(objects={}),snap,contract))
        snap['named_views']['Overview']='frozen camera'
        self.assertEqual(compare(dict(objects={}),snap,contract),[])
        contract['expected_named_views']=['Overview','Overview']
        with self.assertRaises(ValueError):validate_checks(contract)
        contract=checks();contract['preview']['resolution']=[8000,64]
        with self.assertRaises(ValueError):validate_checks(contract)

    def test_missing_native_response_preserves_clear_failure_and_does_not_run_model(self):
        frozen,control=self.frozen()
        with patch('task_relay.rhino_host.run',return_value=dict(passed=False,worker=None,returncode=0)) as calls:
            result=execute(frozen,control)
        self.assertEqual(result['outcome'],'failed')
        self.assertIn('without a matching worker response',result['summary'])
        self.assertNotIn('NoneType',result['summary'])
        self.assertEqual(calls.call_count,1)
        self.assertFalse((Path(frozen['workspace'])/'delivery/candidate.3dm').exists())
        self.assertEqual(json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())['runs'][0]['worker'],None)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        guard=patch('task_relay.rhino_host.running_instances',return_value=[])
        guard.start();self.addCleanup(guard.stop)

    def test_failed_owner_receipt_closes_new_process_before_returning(self):
        from task_relay.rhino_host import run
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='startup')))
            with patch('task_relay.rhino_host.subprocess.Popen') as spawn,patch('orchestrator.workers.atomic',side_effect=OSError('disk full')):
                process=spawn.return_value;process.pid=123;process.poll.return_value=None
                with self.assertRaisesRegex(OSError,'disk full'):run('/rhino',Path(tmp)/'script.py',p,1,'darwin')
                process.kill.assert_called_once();process.wait.assert_called_once()

    def test_owned_shutdown_receives_failure_only_after_receipt_is_closed(self):
        import types
        from unittest.mock import Mock
        from orchestrator.rhino_worker import main
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='startup',rhino_major=7)))
            p.with_suffix('.owner.json').write_text(json.dumps(dict(pid=123,token='test')))
            def shutdown(code):
                result=json.loads(p.with_suffix('.result.json').read_text())
                self.assertEqual(code,1);self.assertFalse(result['passed']);self.assertIn('fixture failure',result['error'])
            exit_process=Mock(side_effect=shutdown)
            system=types.SimpleNamespace(Diagnostics=types.SimpleNamespace(Process=types.SimpleNamespace(GetCurrentProcess=lambda:types.SimpleNamespace(Id=123))))
            with patch.dict('sys.modules',{'System':system}),patch('orchestrator.rhino_worker.perform',side_effect=ValueError('fixture failure')):
                main(p,exit_process)
            exit_process.assert_called_once_with(1)

    def test_macos_exit_adapter_preserves_exit_code_without_managed_finalizers(self):
        import types
        from unittest.mock import Mock
        from task_relay.rhino_host import shutdown_script
        from task_relay.host import UnsupportedHost
        native=Mock();managed=Mock(side_effect=AssertionError('Managed finalizer path'))
        scope={'System':types.SimpleNamespace(Environment=types.SimpleNamespace(Exit=managed))}
        library=Mock(return_value=types.SimpleNamespace(_exit=native))
        with patch.dict('sys.modules',{'ctypes':types.SimpleNamespace(CDLL=library,c_int=int)}):
            exec(shutdown_script(7,'darwin'),scope);scope['relay_exit'](1)
        native.assert_called_once_with(1);managed.assert_not_called()
        with self.assertRaises(UnsupportedHost):shutdown_script(7,'win32')

    def test_rhino8_owned_exit_avoids_managed_finalizers_and_preserves_failure(self):
        from task_relay.rhino_host import shutdown_script
        from unittest.mock import Mock
        scope={'System':Mock()}
        with patch('os._exit') as native:
            exec(shutdown_script(8,'darwin'),scope)
            scope['relay_exit'](0);scope['relay_exit'](1)
            self.assertEqual([x.args[0] for x in native.call_args_list],[0,1])
        scope['System'].Environment.Exit.assert_not_called()

    def test_forwarded_startup_cannot_operate_on_or_exit_existing_rhino(self):
        import types
        from orchestrator.rhino_worker import main
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='startup')))
            p.with_suffix('.owner.json').write_text(json.dumps(dict(pid=100,token='test')))
            with patch.dict('sys.modules',{'System':types.SimpleNamespace(Diagnostics=types.SimpleNamespace(
                    Process=types.SimpleNamespace(GetCurrentProcess=lambda:types.SimpleNamespace(Id=999))))}),patch('orchestrator.rhino_worker.perform') as perform:
                with self.assertRaisesRegex(ValueError,'owned process'):main(p)
                perform.assert_not_called()
            self.assertFalse(p.with_suffix('.result.json').exists())

    def test_clean_native_exit_cannot_hide_a_failed_worker(self):
        from task_relay.rhino_host import run
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='startup')))
            with patch('task_relay.rhino_host.subprocess.Popen') as spawn:
                process=spawn.return_value;process.pid=123;process.returncode=0;process.poll.return_value=0
                def reply(**kw):
                    p.with_suffix('.result.json').write_text(json.dumps(dict(pid=123,token='test',mode='startup',passed=False,error='fixture failure')))
                process.wait.side_effect=reply
                result=run('/rhino',Path(tmp)/'script.py',p,1,'darwin')
                self.assertEqual(result['returncode'],0);self.assertFalse(result['passed'])
                self.assertEqual(result['worker']['error'],'fixture failure')

    def test_exit_zero_without_matching_worker_identity_cannot_claim_success(self):
        from task_relay.rhino_host import run
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='startup')))
            with patch('task_relay.rhino_host.subprocess.Popen') as spawn:
                process=spawn.return_value;process.pid=123;process.returncode=0;process.poll.return_value=0
                def reply(**kw):
                    p.with_suffix('.result.json').write_text(json.dumps(dict(pid=999,token='test',mode='startup',passed=True)))
                process.wait.side_effect=reply
                result=run('/rhino',Path(tmp)/'script.py',p,1,'darwin')
                self.assertFalse(result['passed']);self.assertIsNone(result['worker'])

    def test_presence_never_launches_and_unsupported_host_never_falls_back(self):
        from task_relay.host_apps import rhino
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'Rhino.app/Contents/MacOS/Rhinoceros';p.parent.mkdir(parents=True);p.write_text('fixture');p.chmod(0o700)
            import plistlib
            (p.parents[1]/'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'7.32'}))
            with patch('subprocess.Popen',side_effect=AssertionError('Discovery launched')):
                found=rhino({'TASK_RELAY_RHINO':str(p)},'darwin')
                self.assertTrue(found['available']);self.assertEqual(found['major'],7)
                self.assertFalse(rhino({'TASK_RELAY_RHINO':str(p),'TASK_RELAY_RHINO_VERSION':'8'},'darwin')['available'])
                self.assertFalse(rhino({'TASK_RELAY_RHINO':str(p),'TASK_RELAY_RHINO_VERSION':'6'},'darwin')['available'])
                self.assertFalse(rhino({'TASK_RELAY_RHINO':str(p)},'linux')['available'])
                self.assertFalse(rhino({'TASK_RELAY_RHINO':'/missing'},'darwin')['available'])

    def test_platform_and_macro_path_are_checked(self):
        from task_relay.rhino_host import command
        from task_relay.host import UnsupportedHost
        with self.assertRaises(UnsupportedHost):command('/rhino','/script.py','win32')
        with self.assertRaises(ValueError):command('/rhino','/bad" _Quit.py','darwin')
        self.assertIn('"/some path/script.py"',command('/rhino','/some path/script.py','darwin')[-1])

    def test_timeout_kills_only_spawned_process_and_never_retries(self):
        from task_relay.rhino_host import run
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='startup')))
            with patch('task_relay.rhino_host.subprocess.Popen') as spawn:
                process=spawn.return_value;process.pid=123;process.returncode=-9
                def timed_out(**kwargs):
                    if kwargs.get('timeout')==5:return -9
                    clock[0]+=kwargs['timeout']
                    raise subprocess.TimeoutExpired([],kwargs['timeout'])
                clock=[0.]
                process.wait.side_effect=timed_out;process.poll.return_value=-9
                with patch('task_relay.rhino_host.time.monotonic',side_effect=lambda:clock[0]):
                    result=run('/rhino',Path(tmp)/'script.py',p,1,'darwin')
                process.kill.assert_called_once();spawn.assert_called_once()
                self.assertNotIn('start_new_session',spawn.call_args.kwargs)
                self.assertTrue(result['timeout']);self.assertFalse(result['passed'])

    def test_existing_unconnected_rhino_prevents_launch_without_touching_process(self):
        from task_relay.rhino_host import run
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='before')))
            with patch('task_relay.rhino_host.running_instances',return_value=[42]),patch('task_relay.rhino_host.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'script connection'):
                    run('/Applications/Unavailable.app/Contents/MacOS/Rhinoceros',Path(tmp)/'script.py',p,600,'darwin')
                spawn.assert_not_called()

    def test_startup_timeout_is_separate_and_only_stops_owned_process(self):
        from task_relay.rhino_host import run
        clock=[0.]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='before')))
            with patch('task_relay.rhino_host.subprocess.Popen') as spawn,patch('task_relay.rhino_host.time.monotonic',side_effect=lambda:clock[0]):
                process=spawn.return_value;process.pid=123;process.returncode=-9;process.poll.return_value=-9
                def waiting(**kwargs):
                    if kwargs['timeout']==5:return -9
                    clock[0]+=kwargs['timeout'];raise subprocess.TimeoutExpired([],kwargs['timeout'])
                process.wait.side_effect=waiting
                result=run('/rhino',Path(tmp)/'script.py',p,600,'darwin')
                process.kill.assert_called_once();spawn.assert_called_once()
        self.assertEqual(result['error_code'],'rhino_startup_timeout')
        self.assertEqual(result['elapsed_seconds'],60)
        self.assertFalse(result['startup_received'])

    def test_owned_startup_allows_long_work_but_wrong_pid_does_not(self):
        from task_relay.rhino_host import run
        for owner in (123,999):
            with self.subTest(owner=owner),tempfile.TemporaryDirectory() as tmp:
                clock=[0.];p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='model')))
                p.with_suffix('.started.json').write_text(json.dumps(dict(pid=owner,token='test',mode='model')))
                with patch('task_relay.rhino_host.subprocess.Popen') as spawn,patch('task_relay.rhino_host.time.monotonic',side_effect=lambda:clock[0]):
                    process=spawn.return_value;process.pid=123;process.returncode=0;process.poll.return_value=0
                    def waiting(**kwargs):
                        if kwargs['timeout']==5:return 0
                        clock[0]+=kwargs['timeout']
                        if clock[0]>=75:
                            p.with_suffix('.result.json').write_text(json.dumps(dict(pid=123,token='test',mode='model',passed=True)))
                            return 0
                        raise subprocess.TimeoutExpired([],kwargs['timeout'])
                    process.wait.side_effect=waiting
                    result=run('/rhino',Path(tmp)/'script.py',p,600,'darwin')
                self.assertEqual(result['passed'],owner==123)
                self.assertEqual(result['startup_received'],owner==123)


class ProcessInspectionTests(unittest.TestCase):
    def test_exact_application_match_ignores_other_versions_and_helper_processes(self):
        from task_relay.rhino_host import running_instances
        output='42 /Applications/Rhino 8.app/Contents/MacOS/Rhinoceros\n43 /Applications/Rhino 7.app/Contents/MacOS/Rhinoceros\n44 /Applications/Rhino 8.app/Contents/Frameworks/RhinoMonitor.app/Contents/MacOS/RhinoMonitor\n'
        with patch('task_relay.rhino_host.subprocess.run',return_value=subprocess.CompletedProcess([],0,output,'')):
            self.assertEqual(running_instances('/Applications/Rhino 8.app/Contents/MacOS/Rhinoceros','darwin'),[42])

    def test_unavailable_process_inspection_does_not_launch(self):
        from task_relay.rhino_host import run
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'request.json';p.write_text(json.dumps(dict(token='test',mode='before')))
            with patch('task_relay.rhino_host.subprocess.run',side_effect=PermissionError('Denied')),patch('task_relay.rhino_host.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError,'no worker was launched'):
                    run('/rhino',Path(tmp)/'script.py',p,600,'darwin')
                spawn.assert_not_called()


if __name__=='__main__':unittest.main()
