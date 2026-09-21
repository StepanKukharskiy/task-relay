"""Small standalone 3DM fixtures; no Rhino, network, providers or user models."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from orchestrator import contracts, execution, rhino3dm_contract as contract, rhino3dm_document as document
from orchestrator.adapters import ExecutionFactory, RegisteredFactory
from orchestrator.runtime import Runtime, file_hash
from task_relay import production_planning as planning
from tests import test_mixed_execution as mixed, test_production_planning as planning_fixture
from tests.test_orchestrator import plan, task


def fixture():
    return dict(version=1, units='Meters', tolerance=.001,
        layers=[dict(name='Terrain', color=[40,120,50]), dict(name='Annotations', color=[200,30,10])],
        objects=[dict(type='mesh', name='Ground', layer='Terrain',
            vertices=[[0,0,0],[10,0,0],[10,10,0],[0,10,0],[5.123456789,5,2.123456789]],
            faces=[[0,1,4],[1,2,4],[2,3,4],[3,0,4]]),
            dict(type='polyline', name='Boundary', layer='Annotations', points=[[0,0,0],[10,0,0],[10,10,0],[0,0,0]]),
            dict(type='point', name='Survey marker', layer='Annotations', point=[3.123456789,4,2])])


def operation(inputs, **kwargs):
    spec=execution.REGISTRY['rhino3dm.create']
    return dict(id='model', role='procedure', objective='Create a standalone 3DM', instruction='Create the specified geometry.',
        execution=dict(capability='rhino3dm.create',version=1,parameters={}), inputs=inputs,
        outputs=[dict(path=p,media_type=m,purpose='Library candidate and verification') for p,m in spec['outputs'].items()],
        criteria=copy.deepcopy(spec['criteria']), user_gate='Select this model', **kwargs)


class ContractTests(unittest.TestCase):
    def test_rejects_code_native_features_and_invalid_geometry(self):
        mutations=[lambda d:d.update(script='import Rhino'), lambda d:d.update(source='old.3dm'),
            lambda d:d['objects'][0].update(type='nurbs'), lambda d:d['objects'][0]['vertices'][0].__setitem__(0,float('nan')),
            lambda d:d['objects'][0]['faces'].append([0,1,99]), lambda d:d['objects'][0]['faces'].append([0,0,1]),
            lambda d:d['objects'][0].update(layer='missing'), lambda d:d['objects'][1].update(name='Ground'),
            lambda d:d['layers'].append(dict(name='terrain',color=[1,2,3])), lambda d:d.update(tolerance=True),
            lambda d:d['objects'][1].update(points=[[0,0,0],[0,0,0]])]
        for change in mutations:
            with self.subTest(change=change):
                value=fixture();change(value)
                with self.assertRaises(ValueError):contract.validate(value)
        with self.assertRaisesRegex(ValueError,'Duplicate'):contract.load('{"version":1,"version":1}')
        with patch.object(contract,'MAX_POINTS',5),self.assertRaisesRegex(ValueError,'point limit'):contract.validate(fixture())

    def test_registered_route_rejects_scripts_duplicate_manifests_and_partial_outputs(self):
        inp=dict(artifact='manifest',path='geometry.json',purpose='Geometry',authority='Selected',media_type='application/json')
        contracts.assignment(operation([inp]))
        for change in (lambda t:t['inputs'].append(inp), lambda t:t['inputs'][0].update(media_type='text/x-python'),
                       lambda t:t['outputs'].pop(),lambda t:t['execution'].update(capability='rhino.run_python'),
                       lambda t:t['inputs'][0].update(path='delivery/geometry.json')):
            value=operation([copy.deepcopy(inp)]);change(value)
            with self.assertRaises(ValueError):contracts.assignment(value)

    def test_missing_library_is_an_explicit_blocker(self):
        with patch.dict(sys.modules,{'rhino3dm':None}),self.assertRaisesRegex(ValueError,'no Rhino fallback'):document.available()

    def test_library_file_can_feed_separately_declared_native_inspection(self):
        from orchestrator import handoff_contracts as handoffs
        from tests.test_handoff_contracts import stage, edge
        stages=[stage('create','production',{'model':{'media_type':contract.MEDIA}},['rhino3dm.create']),
                stage('inspect','production',{'inventory':{'media_type':'application/json'}},['rhino.inspect'],
                      [edge('create','model',contract.MEDIA,'rhino.inspect')])]
        result=handoffs.compile_workflow(stages,required=True)
        self.assertEqual(len(result['edges']),1)
        saved={'id':'rhino3dm.create',**execution.REGISTRY['rhino3dm.create'],'available':False}
        with self.assertRaisesRegex(handoffs.ContractError,'unavailable'):
            handoffs.compile_workflow(stages,[saved],True)


@unittest.skipUnless(importlib.util.find_spec('rhino3dm'), 'Install task-relay[rhino3dm] for actual library checks')
class DocumentTests(unittest.TestCase):
    def test_real_roundtrip_retains_double_precision_geometry_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'candidate.3dm';value=fixture()
            evidence=document.create(value,path,1000000)
            self.assertTrue(evidence['passed']);self.assertFalse(evidence['native_rhino_verified'])
            self.assertEqual(evidence['source_fidelity'],'not_verified')
            self.assertEqual(evidence['candidate_sha256'],file_hash(path))
            self.assertLess(evidence['objects'][0]['max_coordinate_error'],1e-9)
            self.assertEqual(evidence['objects'][0]['faces'],4)
            before=file_hash(path)
            with self.assertRaisesRegex(ValueError,'no replacement'):document.create(value,path,1000000)
            self.assertEqual(file_hash(path),before)

    def test_interior_vertex_and_topology_changes_fail_even_with_same_bounds(self):
        library=document.available()
        for kind in ('interior','topology','layer','units'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'candidate.3dm';value=fixture();document.create(value,path,1000000)
                model=library.File3dm.Read(str(path))
                if kind=='interior':model.Objects[0].Geometry.Vertices.SetPoint3dAt(4,library.Point3d(6,5,2.123456789))
                elif kind=='topology':model.Objects[0].Geometry.Faces.SetFace(0,0,2,4)
                elif kind=='layer':model.Objects[0].Attributes.LayerIndex=1
                else:model.Settings.ModelUnitSystem=library.UnitSystem.Millimeters
                self.assertTrue(model.Write(str(path),8))
                with self.assertRaises(ValueError):document.verify(path,value,library)

    def test_invalid_mesh_and_failed_reopen_never_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'candidate.3dm';value=fixture()
            value['objects'][0]['vertices']=[[0,0,0]]*5
            with self.assertRaisesRegex(ValueError,'Invalid generated geometry'):document.create(value,path,1000000)
            self.assertFalse(path.exists())
            path.write_text('not a 3dm')
            with self.assertRaisesRegex(ValueError,'could not reopen'):document.verify(path,fixture(),document.available())


@unittest.skipUnless(importlib.util.find_spec('rhino3dm'), 'Install task-relay[rhino3dm] for actual library checks')
class GraphTests(unittest.TestCase):
    setUp=mixed.Tests.setUp
    tearDown=mixed.Tests.tearDown

    def source_input(self, value=None):
        source=self.root/'geometry.json';source.write_text(json.dumps(fixture() if value is None else value))
        aid=self.rt.register(source,'Exact geometry specification',path='geometry.json')
        return dict(artifact=aid,path='geometry.json',purpose='Geometry data',authority='Selected source',media_type='application/json')

    def test_generation_review_selection_restart_without_native_app(self):
        producer=operation([self.source_input()])
        reviewer=task('review',dependencies=['model'],review_of='model',inputs=[dict(from_task='model',output=o['path'],
            path=o['path'],purpose='Review candidate',authority='Candidate',media_type=o['media_type']) for o in producer['outputs']])
        reviewer['criteria']=producer['criteria'].copy()
        with patch('task_relay.host_apps.rhino',side_effect=AssertionError('Do not discover/launch Rhino')):
            self.rt.create(plan([producer,reviewer]));self.rt.tick('demo');self.rt.tick('demo')
            artifact=self.rt.output('demo','model','delivery/candidate.3dm')
            rid=self.rt.task('demo','review')['latest'];self.agent.finish(rid,decision='accept');self.rt.tick('demo')
            self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')
            receipt=json.loads(self.rt.status('demo')['attempts'][0]['receipt'])['operation']
            self.assertEqual(receipt['execution_mode'],'standalone_library');self.assertFalse(receipt['host_execution'])
            self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory);self.rt.tick('demo')
            self.assertEqual(len(self.ops.calls),1)
            self.assertEqual(self.rt.output('demo','model','delivery/candidate.3dm')['id'],artifact['id'])
            self.rt.select('demo','model',artifact['id'],'Select this model','Use this exact model');self.rt.tick('demo')
            self.assertEqual(self.rt.status('demo')['status'],'completed')
        self.assertEqual(self.client.calls,[])

    def test_missing_dependency_blocks_before_attempt(self):
        self.rt.create(plan([operation([self.source_input()])]))
        with patch.object(document,'available',side_effect=ValueError('Missing rhino3dm; no fallback')):
            self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'blocked');self.assertEqual(self.rt.status('demo')['attempts'],[])

    def assert_failed_without_replay(self, partial=False):
        self.rt.tick('demo');self.rt.tick('demo')
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory);self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'blocked');self.assertEqual(len(self.ops.calls),1)
        if partial:
            artifact=self.rt.output('demo','model','delivery/candidate.3dm')
            with self.assertRaises(ValueError):self.rt.select('demo','model',artifact['id'],'Select this model','Use failed model')
        else:
            with self.assertRaisesRegex(ValueError,'Missing upstream artifact'):self.rt.output('demo','model','delivery/candidate.3dm')

    def test_bad_specification_does_not_replay_on_restart(self):
        self.rt.create(plan([operation([self.source_input({'version':1})])]))
        self.assert_failed_without_replay()

    def test_changed_input_and_implementation_block_before_generation(self):
        self.rt.create(plan([operation([self.source_input()])]))
        with patch('orchestrator.rhino3dm_document.file_hash',side_effect=lambda p:'0'*64 if Path(p).name=='rhino3dm_contract.py' else file_hash(p)):
            self.assert_failed_without_replay()

    def test_changed_input_copy_blocks_without_generation(self):
        original=self.ops.submit
        def tamper(session):
            launch=json.loads((Path(session['control'])/'launch.json').read_text())
            source=Path(launch['workspace'])/'geometry.json';source.chmod(0o600);source.write_text('{}')
            return original(session)
        self.ops.submit=tamper
        self.rt.create(plan([operation([self.source_input()])]))
        self.assert_failed_without_replay()

    def test_verification_failure_keeps_failed_receipt_and_partial_candidate(self):
        self.rt.create(plan([operation([self.source_input()])]))
        with patch.object(document,'verify',side_effect=ValueError('reopen failed')):self.assert_failed_without_replay(partial=True)
        frozen=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE run=?',('demo',)).fetchone()['frozen'])
        out=Path(frozen['workspace'])/'delivery'
        self.assertTrue((out/'candidate.3dm').exists())
        self.assertFalse(json.loads((out/'execution.json').read_text())['passed'])
        self.assertFalse((Path(frozen['workspace'])/'.relay/result.json').exists())

    def test_total_delivery_budget_includes_verification_receipts(self):
        sample=self.root/'sample.3dm';document.create(fixture(),sample,1000000)
        value=operation([self.source_input()]);value['limits']={'output_bytes':sample.stat().st_size+128}
        self.rt.create(plan([value]));self.assert_failed_without_replay(partial=True)
        attempt=self.rt.db.execute('SELECT frozen FROM production_attempts WHERE run=?',('demo',)).fetchone()
        out=Path(json.loads(attempt['frozen'])['workspace'])/'delivery'
        receipt=json.loads((out/'execution.json').read_text())
        self.assertFalse(receipt['passed']);self.assertIn('total output byte limit',receipt['error'])

    def test_real_supervised_child_retains_library_receipt(self):
        factory=RegisteredFactory();self.rt.factory=ExecutionFactory(self.agent,factory)
        self.rt.create(plan([operation([self.source_input()])]))
        self.rt.tick('demo');deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            status=self.rt.tick('demo')
            if status['status'] in ('awaiting_user','blocked'):break
            time.sleep(.05)
        for child in factory.children:child.wait(timeout=10)
        self.assertEqual(status['status'],'awaiting_user',status)
        receipt=json.loads(status['attempts'][0]['receipt'])['operation']
        self.assertFalse(receipt['native_rhino_verified']);self.assertEqual(receipt['library_version'],contract.LIBRARY_VERSION)


@unittest.skipUnless(importlib.util.find_spec('rhino3dm'), 'Install task-relay[rhino3dm] for planning availability')
class PlanningTests(unittest.TestCase):
    setUp=planning_fixture.Tests.setUp
    tearDown=planning_fixture.Tests.tearDown
    request=planning_fixture.Tests.request
    action=planning_fixture.Tests.action
    queue=planning_fixture.Tests.queue
    row=planning_fixture.Tests.row
    response=planning_fixture.Tests.response

    def test_library_catalog_remains_available_without_rhino_and_blocks_version_drift(self):
        library=document.available()
        with patch('task_relay.host_apps.rhino',return_value=dict(available=False,evidence='No Rhino installed',version=None)):
            entry=next(i for i in execution.catalog() if i['id']=='rhino3dm.create')
            self.assertTrue(entry['available']);self.assertIn('geometry_schema',entry)
            with patch.object(library,'__version__','different'):
                entry=next(i for i in execution.catalog() if i['id']=='rhino3dm.create')
                self.assertFalse(entry['available']);self.assertIn('no Rhino fallback',entry['blocker'])

    def model_response(self):
        result=self.response();producer,reviewer=result['plan']['tasks'];producer.pop('user_gate',None)
        producer['outputs']=[dict(path='geometry.json',purpose='Geometry specification',media_type='application/json')]
        reviewer['inputs']=[dict(from_task='produce',output='geometry.json',path='geometry.json',purpose='Review geometry',authority='Candidate',media_type='application/json')]
        model=contracts.assignment(operation([dict(from_task='produce',output='geometry.json',path='geometry.json',purpose='Geometry',authority='Reviewed data',media_type='application/json')],dependencies=['produce','review']))
        model_review=copy.deepcopy(reviewer)
        model_review.update(id='model-review',review_of='model',dependencies=['model'],criteria=model['criteria'].copy(),
            inputs=[dict(from_task='model',output=o['path'],path=o['path'],purpose='Review result',authority='Candidate',media_type=o['media_type']) for o in model['outputs']])
        result['plan']['tasks'] += [model,model_review]
        return result

    def test_planning_copies_dependency_free_validator_and_preserves_route(self):
        row=dict(self.queue(action=self.action(step_capabilities=['rhino3dm.create'])))
        _,resolved=planning.validate_result(json.dumps(self.model_response()),row)
        self.assertEqual(resolved['tasks'][2]['execution']['capability'],'rhino3dm.create')
        payload=json.loads(row['context']);support=[s for s in payload['sources'] if s.get('operation_support')=='rhino3dm.create']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for src in support:(root/Path(src['path']).name).write_bytes(Path(self.rt.artifact(src['artifact'])['blob']).read_bytes())
            source=root/'geometry.json';source.write_text(json.dumps(fixture()))
            result=subprocess.run([sys.executable,'-E','-S',str(root/'validate.py'),str(source)],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_missing_output_review_or_selection_gate_is_rejected(self):
        row=dict(self.queue(action=self.action(step_capabilities=['rhino3dm.create'])))
        for gate in (False,True):
            response=self.model_response()
            if gate:response['plan']['tasks'][2].pop('user_gate')
            else:response['plan']['tasks'].pop()
            with self.assertRaisesRegex(ValueError,'independent output review'):planning.validate_result(json.dumps(response),row)

    def test_native_scope_cannot_silently_switch_to_library(self):
        with patch('task_relay.host_apps.rhino',return_value=dict(available=True,evidence='fixture',version='8',major=8)):
            row=dict(self.queue(action=self.action(step_capabilities=['rhino.run_python'])))
        with self.assertRaises(ValueError):planning.validate_result(json.dumps(self.model_response()),row)


if __name__=='__main__':unittest.main()
