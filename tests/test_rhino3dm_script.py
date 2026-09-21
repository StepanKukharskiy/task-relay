"""Full library API, exact script grants and Rhino 7/8 file-format fixtures."""
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

from orchestrator import contracts as c,host_code,execution,rhino3dm_script as runner
from orchestrator import rhino3dm_script_contract as contract,rhino3dm_script_worker as worker
from orchestrator.runtime import Runtime,file_hash
from task_relay import production_planning as planning
from tests import test_mixed_execution as mixed,test_production_planning as planning_fixture
from tests.test_blender_operations import operation
from tests.test_orchestrator import plan


SCRIPT='''r = rhino3dm
model.Settings.ModelUnitSystem = r.UnitSystem.Meters
layer=r.Layer();layer.Name="Design";layer.Color=(20,80,120,255)
index=model.Layers.Add(layer)
material=r.Material();material.Name="Stone";material.DiffuseColor=(90,100,110,255)
model.Materials.Add(material)
model.Strings["project"]="Library fixture"
def add(name,geometry):
    attr=r.ObjectAttributes();attr.Name=name;attr.LayerIndex=index
    model.Objects.Add(geometry,attr)
add("Curve",r.NurbsCurve.Create(False,3,[r.Point3d(i,i%2,0) for i in range(5)]))
add("Surface",r.PlaneSurface(r.Plane.WorldXY(),r.Interval(0,3),r.Interval(0,4)).ToNurbsSurface())
add("Solid",r.Sphere(r.Point3d(0,0,0),2).ToBrep())
add("Note",r.TextDot("Library annotation",r.Point3d(1,2,3)))
add("Extrusion",r.Extrusion.Create(r.Circle(r.Point3d(0,0,0),1).ToNurbsCurve(),5,True))
'''


def checks(version=7,mode='create'):
    return dict(version=1,mode=mode,file_version=version,expected_units='Meters',expected_object_count=5,
        required_objects=['Curve','Surface','Solid','Note','Extrusion'],preserve_objects=[],expected_dimensions={'Solid':[4,4,4]})


def inputs(rt,root,script=SCRIPT,value=None,source=None,assets=()):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    result=[];params=dict(scene_sha256=None,permissions='unrestricted_host')
    entries=[('model.py',script.encode(),'text/x-python','script_sha256'),
             ('checks.json',json.dumps(value or checks()).encode(),'application/json','checks_sha256')]
    if source is not None:entries.append(('source.3dm',source,'application/vnd.rhino','scene_sha256'))
    entries.extend((name,raw,'application/octet-stream',None) for name,raw in assets)
    for name,raw,media,key in entries:
        path=root/name;path.write_bytes(raw);aid=rt.register(path,'Exact library input',path=name)
        result.append(dict(artifact=aid,path=name,purpose='Selected library input',authority='Explicit fixture',media_type=media))
        if key:params[key]=file_hash(path)
    op=operation('rhino3dm.run_python',result);op['execution']['parameters']=params
    op['user_gate']='Select library result'
    return op


class ContractTests(unittest.TestCase):
    def test_target_version_and_preservation_are_explicit(self):
        for v in (7,8):self.assertEqual(contract.validate_checks(checks(v))['file_version'],v)
        for change in (lambda v:v.pop('file_version'),lambda v:v.update(file_version=True),lambda v:v.update(file_version=0),
                       lambda v:v.update(file_version=9),lambda v:v.update(preserve_objects=['missing-id']),
                       lambda v:v.update(expected_dimensions={'Bad':[float('nan'),0,0]})):
            value=checks();change(value)
            with self.assertRaises(ValueError):contract.validate_checks(value)

    def test_uncertain_or_failed_library_phases_use_existing_recovery_policy(self):
        from orchestrator.native_recovery import assess
        receipt=dict(capability='rhino3dm.run_python',passed=False,runs=[dict(mode='before',passed=True),
            dict(mode='model',passed=False,returncode=1,worker=dict(passed=False,error='script exception'))])
        self.assertEqual(assess(receipt,'rhino3dm.run_python')['action'],'prepare_reviewed_repair')
        receipt['runs'][-1]['timeout']=True
        self.assertEqual(assess(receipt,'rhino3dm.run_python')['action'],'reconcile')


@unittest.skipUnless(importlib.util.find_spec('rhino3dm'),'Install task-relay[rhino3dm]')
class ScriptTests(unittest.TestCase):
    setUp=mixed.Tests.setUp
    tearDown=mixed.Tests.tearDown

    def start(self,op,approve=True):
        self.rt.create(plan([op]))
        if approve:
            with self.rt.transaction():host_code.authorize(self.rt,'demo','app',{'source':'controlled_exact_script_approval'})

    def finish(self):
        self.rt.tick('demo');self.rt.tick('demo')
        status=self.rt.status('demo')
        return status,json.loads(status['attempts'][0]['receipt'])['operation'] if status['attempts'] else None

    def check_rich_file(self,version):
        op=inputs(self.rt,self.root,value=checks(version));self.start(op)
        with patch('task_relay.host_apps.rhino',side_effect=AssertionError('No native Rhino discovery')):
            status,receipt=self.finish()
        self.assertEqual(status['status'],'awaiting_user',receipt)
        self.assertEqual(receipt['file_version'],version);self.assertFalse(receipt['native_application_execution'])
        self.assertFalse(receipt['native_rhino_verified']);self.assertIn('library_runtime',receipt['authorization']['binding'])
        library=runner.available();artifact=self.rt.output('demo','app','delivery/candidate.3dm')
        model=library.File3dm.Read(artifact['blob'])
        self.assertEqual(model.ArchiveVersion,version*10)
        self.assertEqual({type(o.Geometry).__name__ for o in model.Objects},{'NurbsCurve','NurbsSurface','Brep','TextDot','Extrusion'})
        self.assertEqual(model.Strings['project'],'Library fixture');self.assertEqual(model.Materials[0].Name,'Stone')
        self.assertEqual(model.Layers[0].Name,'Design')
        self.assertEqual([r['mode'] for r in receipt['runs']],['before','model','verify'])
        self.assertEqual(self.client.calls,[])

    def test_full_api_writes_rhino7_without_rhino(self):self.check_rich_file(7)
    def test_full_api_writes_rhino8_without_rhino(self):self.check_rich_file(8)

    def test_blocks_and_instance_references_are_available_without_whitelisting(self):
        value=checks();value.update(expected_object_count=2,required_objects=[],expected_dimensions={})
        script='''r=rhino3dm
model.Settings.ModelUnitSystem=r.UnitSystem.Meters
index=model.InstanceDefinitions.Add("Block","fixture","","",r.Point3d(0,0,0),
    (r.Point(r.Point3d(1,2,3)),),(r.ObjectAttributes(),))
model.Objects.Add(r.InstanceReference(model.InstanceDefinitions[index].Id,r.Transform.Translation(2,0,0)))
'''
        self.start(inputs(self.rt,self.root,script,value));status,receipt=self.finish()
        self.assertEqual(status['status'],'awaiting_user',receipt)
        model=runner.available().File3dm.Read(self.rt.output('demo','app','delivery/candidate.3dm')['blob'])
        self.assertEqual(len(model.InstanceDefinitions),1)
        self.assertIn('InstanceReference',{type(o.Geometry).__name__ for o in model.Objects})

    def test_real_supervised_full_library_execution(self):
        from orchestrator.adapters import ExecutionFactory,RegisteredFactory
        factory=RegisteredFactory();self.rt.factory=ExecutionFactory(self.agent,factory)
        self.start(inputs(self.rt,self.root));self.rt.tick('demo');deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            status=self.rt.tick('demo')
            if status['status'] in ('awaiting_user','blocked','uncertain'):break
            time.sleep(.05)
        for child in factory.children:child.wait(timeout=10)
        self.assertEqual(status['status'],'awaiting_user',status)
        receipt=json.loads(status['attempts'][0]['receipt'])['operation']
        self.assertEqual(receipt['file_version'],7);self.assertFalse(receipt['native_rhino_verified'])

    def test_edit_source_and_additional_binary_input_preserve_original(self):
        r=runner.available();model=r.File3dm();model.Settings.ModelUnitSystem=r.UnitSystem.Meters
        attr=r.ObjectAttributes();attr.Name='Original';ident=model.Objects.Add(r.Point(r.Point3d(1,2,3)),attr)
        source=self.root/'source-fixture.3dm';model.Write(str(source),7);raw=source.read_bytes()
        value=checks(mode='edit');value.update(expected_object_count=2,required_objects=['Original','Added'],preserve_objects=[str(ident)],expected_dimensions={})
        script='''import pathlib
assert pathlib.Path(input_paths["asset.bin"]).read_bytes() == b"\\xffasset"
attr=rhino3dm.ObjectAttributes();attr.Name="Added"
model.Objects.Add(rhino3dm.Sphere(rhino3dm.Point3d(0,0,0),1).ToBrep(),attr)
'''
        op=inputs(self.rt,self.root,script,value,raw,assets=[('asset.bin',b'\xffasset')]);self.start(op)
        status,receipt=self.finish();self.assertEqual(status['status'],'awaiting_user',receipt)
        self.assertEqual(source.read_bytes(),raw)
        self.assertEqual(Path(self.rt.artifact(op['inputs'][2]['artifact'])['blob']).read_bytes(),raw)
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory);self.rt.tick('demo')
        self.assertEqual(len(self.ops.calls),1)

    def test_no_grant_no_attempt(self):
        self.start(inputs(self.rt,self.root),approve=False)
        status,_=self.finish();self.assertEqual(status['status'],'blocked');self.assertEqual(status['attempts'],[])

    def test_changed_library_identity_invalidates_grant(self):
        self.start(inputs(self.rt,self.root));identity=runner.runtime_identity();identity['library_version']='changed'
        with patch.object(runner,'runtime_identity',return_value=identity):status,_=self.finish()
        self.assertEqual(status['status'],'blocked');self.assertEqual(status['attempts'],[])

    def test_changed_script_invalidates_grant(self):
        op=inputs(self.rt,self.root);self.start(op)
        source=Path(self.rt.artifact(op['inputs'][0]['artifact'])['blob']);source.chmod(0o600);source.write_text('raise RuntimeError("changed")')
        status,_=self.finish();self.assertEqual(status['status'],'blocked');self.assertEqual(status['attempts'],[])

    def test_upstream_unknown_script_cannot_get_initial_execution_approval(self):
        op=inputs(self.rt,self.root);op['inputs'][0].pop('artifact');op['inputs'][0].update(from_task='prepare',output='model.py')
        with self.assertRaisesRegex(ValueError,'already registered'):c.assignment(op)

    def test_script_exception_is_terminal_and_never_replayed(self):
        self.start(inputs(self.rt,self.root,script='raise RuntimeError("fixture failure")'))
        status,receipt=self.finish();self.assertEqual(status['status'],'blocked',receipt)
        self.assertEqual(receipt['outcome'],'failed');self.assertEqual(receipt['runs'][-1]['mode'],'model')
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory);self.rt.tick('demo')
        self.assertEqual(len(self.ops.calls),1)

    def test_timeout_requires_reconciliation_and_is_never_replayed(self):
        self.start(inputs(self.rt,self.root));original=runner.run_phase
        def stop(request,*args):
            if request['mode']=='model':return dict(mode='model',passed=False,timeout=True,returncode=None)
            return original(request,*args)
        with patch.object(runner,'run_phase',side_effect=stop):status,receipt=self.finish()
        self.assertEqual(receipt['outcome'],'uncertain')
        self.assertEqual(status['attempts'][0]['state'],'uncertain')
        self.rt.tick('demo');self.assertEqual(len(self.ops.calls),1)

    def test_bad_execution_receipt_requires_reconciliation(self):
        self.start(inputs(self.rt,self.root));original=runner.run_phase
        def corrupt(request,*args):
            if request['mode']=='model':raise ValueError('Library worker receipt identity mismatch')
            return original(request,*args)
        with patch.object(runner,'run_phase',side_effect=corrupt):status,receipt=self.finish()
        self.assertEqual(receipt['outcome'],'uncertain');self.assertEqual(status['attempts'][0]['state'],'uncertain')
        self.rt.tick('demo');self.assertEqual(len(self.ops.calls),1)

    def test_candidate_tampering_between_worker_and_parent_is_integrity_failure(self):
        self.start(inputs(self.rt,self.root));original=runner.run_phase
        def tamper(request,*args):
            result=original(request,*args)
            if request['mode']=='model':
                path=Path(request['out'])/'candidate.3dm'
                with path.open('ab') as stream:stream.write(b'changed')
            return result
        with patch.object(runner,'run_phase',side_effect=tamper):status,receipt=self.finish()
        self.assertEqual(status['status'],'blocked');self.assertFalse(receipt['passed'])
        self.assertIn('changed after script worker saved',receipt['validation_error'])

    def test_independent_reopen_rejects_wrong_archive_version(self):
        r=runner.available();model=r.File3dm();out=self.root/'delivery';out.mkdir()
        model.Write(str(out/'candidate.3dm'),8)
        manifest=self.root/'checks.json';manifest.write_text(json.dumps(checks(7)))
        with self.assertRaisesRegex(ValueError,'archive version'):
            worker.perform(dict(mode='verify',out=str(out),checks=str(manifest),library_runtime=runner.runtime_identity()))

    def test_preserved_source_geometry_change_blocks_and_retains_candidate(self):
        r=runner.available();model=r.File3dm();model.Settings.ModelUnitSystem=r.UnitSystem.Meters
        attr=r.ObjectAttributes();attr.Name='Keep';ident=model.Objects.Add(r.Point(r.Point3d(1,2,3)),attr)
        source=self.root/'baseline.3dm';model.Write(str(source),7)
        value=checks(mode='edit');value.update(preserve_objects=[str(ident)],expected_object_count=1,required_objects=['Keep'],expected_dimensions={})
        self.start(inputs(self.rt,self.root,'model.Objects[0].Geometry.Translate(rhino3dm.Vector3d(5,0,0))',value,source.read_bytes()))
        status,receipt=self.finish();self.assertEqual(status['status'],'blocked',receipt)
        self.assertIn('Preserved source object',receipt['runs'][-1]['worker']['error'])
        artifact=self.rt.output('demo','app','delivery/candidate.3dm')
        with self.assertRaises(ValueError):self.rt.select('demo','app',artifact['id'],'Select library result','accept')

    def test_dimensions_are_quality_findings_without_automatic_acceptance(self):
        value=checks();value['expected_dimensions']['Solid']=[40,4,4]
        self.start(inputs(self.rt,self.root,value=value));status,receipt=self.finish()
        self.assertTrue(receipt['passed']);self.assertTrue(receipt['findings'])
        self.assertEqual(status['status'],'awaiting_user')
        self.assertIsNotNone(self.rt.quality_review(self.rt.task('demo','app')))


@unittest.skipUnless(importlib.util.find_spec('rhino3dm'),'Install task-relay[rhino3dm]')
class PlanningTests(unittest.TestCase):
    def setUp(self):
        planning_fixture.Tests.setUp(self)
        del self.fail
    tearDown=planning_fixture.Tests.tearDown
    request=planning_fixture.Tests.request
    action=planning_fixture.Tests.action
    queue=planning_fixture.Tests.queue
    row=planning_fixture.Tests.row
    response=planning_fixture.Tests.response

    def setup_plan(self,script=SCRIPT):
        row=self.queue(action=self.action(step_capabilities=['rhino3dm.run_python']),text='Create a Rhino 7 .3dm using the standalone library.')
        host=inputs(self.rt,self.rt.root/'library-inputs',script=script,assets=[('additional.bin',b'\xffbinary fixture')]);host['limits']=dict(seconds=600,tool_calls=1,output_bytes=100000000)
        payload=json.loads(row['context'])
        for item in host['inputs']:
            source=planning.source_entry(self.rt,item['artifact'],item['path'],item['purpose'],item['authority'])
            payload['sources'].append(source);payload['required_artifacts'].append(item['artifact'])
        self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(payload),c.digest(payload),row['id']))
        review=self.response()['plan']['tasks'][1]
        review.update(review_of='app',dependencies=['app'],criteria=host['criteria'])
        review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+Path(o['path']).name,purpose='Review',authority='Candidate',media_type=o['media_type']) for o in host['outputs']]
        response=dict(decision='ready',message='Approve standalone script',geometry_basis=dict(mode='procedural',artifacts=[],checks=[]),
            plan=dict(brief='Library model',tasks=[host,review]))
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error']);return row

    def test_delivered_scripts_required_for_atomic_approval_without_native_rhino(self):
        row=self.setup_plan();self.assertIn('not a Rhino application',planning.preview(row))
        self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],));self.state.db.commit()
        with self.assertRaisesRegex(ValueError,'complete editing script'),self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],));self.state.db.commit()
        with patch('task_relay.rhino_host.require_available',side_effect=AssertionError('No Rhino startup')),self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
        task=self.rt.task(self.row()['run'],'app');grant=host_code.approved(self.rt,self.row()['run'],'app',self.rt.spec(task))
        self.assertEqual(grant['decision']['source'],'delivered_plan_start');self.assertEqual(task['attempts'],0)
        self.assertIn('library_runtime',grant['binding'])
        self.assertIn('application/octet-stream',[i['media_type'] for i in grant['binding']['assignment']['inputs']])

    def test_terminal_failure_proposes_reviewed_library_repair_without_replay(self):
        from orchestrator.storage import transaction
        from orchestrator.step_runner import execute
        from task_relay import production_control as pc,production_review_corrections as correction
        row=self.setup_plan(script='raise ValueError("controlled library script failure")')
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
            planning.apply(self.state,row['token'],'start')
        run=self.row()['run'];production=pc.Worker(self.state,lambda _:self.rt);production.tick()
        session=self.factory.sessions[self.rt.task(run,'app')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        result=execute(session['frozen'],control)
        session['status']=dict(status='finished',exit_code=0,reason=None,usage=[],operation=result)
        production.tick();before=self.rt.status(run);calls=len(self.factory.calls)
        self.assertEqual(before['status'],'blocked');self.assertEqual(correction.details(self.state,run)['kind'],'execution_failure')
        with transaction(self.state.db):ident=correction.propose(self.state,run)
        proposed=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        repaired=json.loads(proposed['plan'])
        self.assertTrue(all(not t.get('execution') for t in repaired['tasks']))
        self.assertIn('rhino3dm.run_python',repaired['deferred_operations'])
        self.assertIn('target file_version',repaired['tasks'][0]['instruction'])
        self.assertEqual(self.rt.status(run),before);self.assertEqual(len(self.factory.calls),calls)

    def test_preparation_defers_unknown_script_and_ships_standalone_validator(self):
        row=self.queue(action=self.action(step_capabilities=['rhino3dm.run_python']))
        response=self.response();response['deferred_operations']={'rhino3dm.run_python':'Prepare exact script/checks before separately approved execution.'}
        author,review=response['plan']['tasks'];author['outputs']=[dict(path='model.py',purpose='Script'),dict(path='checks.json',purpose='Checks')]
        author['selection_outputs']=['model.py','checks.json']
        review['inputs']=[dict(from_task='produce',output=o['path'],path=o['path'],purpose='Review',authority='Candidate') for o in author['outputs']]
        _,resolved=planning.validate_result(json.dumps(response),row)
        self.assertEqual(resolved['deferred_operations'],response['deferred_operations'])
        self.assertIn('full installed rhino3dm API',resolved['tasks'][0]['instruction'])
        payload=json.loads(row['context'])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for src in payload['sources']:
                if src.get('operation_support')=='rhino3dm.run_python':
                    (root/Path(src['path']).name).write_bytes(Path(self.rt.artifact(src['artifact'])['blob']).read_bytes())
            (root/'checks.json').write_text(json.dumps(checks()));(root/'model.py').write_text(SCRIPT)
            result=subprocess.run([sys.executable,'-E','-S',str(root/'validate.py'),str(root/'checks.json'),str(root/'model.py')],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
