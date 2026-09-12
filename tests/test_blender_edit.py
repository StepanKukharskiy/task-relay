import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import contracts as c,host_code
from orchestrator.runtime import Runtime,file_hash
from orchestrator.step_runner import execute
from orchestrator.blender_edit import validate_checks
from orchestrator.blender_snapshot import compare
from tests.test_blender_operations import operation
from tests.test_orchestrator import FakeFactory,plan

def checks():
    return dict(changed_objects=['Roof'],preserve_other_objects=True,preserve_cameras=True,preserve_materials=True,
        expected_dimensions={'Roof':[2,2,2.6]},preview=dict(camera='Camera',resolution=[64,64],samples=1))

def inputs(rt,root):
    result=[];hashes={}
    for name,data,media,key in [('source.blend',b'\xffnative','application/x-blender','scene_sha256'),
        ('edit.py',b'bpy.data.objects["Roof"].scale.z *= 1.3\n','text/x-python','script_sha256'),
        ('edit-checks.json',json.dumps(checks()).encode(),'application/json','checks_sha256')]:
        p=root/name;p.write_bytes(data);aid=rt.register(p,'Exact selected '+name,path=name)
        result.append(dict(artifact=aid,path=name,purpose='Selected '+name,authority='Exact review version',media_type=media))
        hashes[key]=file_hash(p)
    op=operation('blender.run_python',result);op['execution']['parameters']={**hashes,'permissions':'unrestricted_host'}
    return op

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.fake=FakeFactory();self.rt=Runtime(self.root/'runtime',self.fake)
        self.app=patch('host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture'));self.app.start()
        self.signature=patch('host_evidence.application_signature',return_value={'path':'/fixture/blender'});self.signature.start()
        self.op=inputs(self.rt,self.root);self.rt.create(plan([self.op]))

    def tearDown(self):self.signature.stop();self.app.stop();self.rt.close();self.tmp.cleanup()

    def authorize(self):
        with self.rt.transaction():host_code.authorize(self.rt,'demo','app',{'source':'controlled_test_explicit_approval'})

    def frozen(self):
        self.authorize();self.rt.tick('demo');a=self.fake.sessions[self.rt.task('demo','app')['latest']]
        control=Path(a['session']['control']);control.mkdir(parents=True)
        return a['frozen'],control

    def fake_run(self,argv,**kwargs):
        mode=argv[argv.index('--')+1];out=Path(argv[-1])
        if mode=='before':
            (out/'checks.json').write_text(json.dumps({'before':{},'passed':False}))
            (out/'before.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        elif mode=='edit':(out/'candidate.blend').write_bytes(b'candidate')
        else:
            (out/'checks.json').write_text(json.dumps({'before':{},'after':{},'passed':True}))
            (out/'after.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        return subprocess.CompletedProcess(argv,0,('RELAY_EDIT_'+mode.upper()+'_OK').encode(),b'')

    def test_no_approval_means_no_attempt_or_dispatch(self):
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','app')['attempts'],0);self.assertEqual(self.fake.calls,[])
        self.assertEqual(self.rt.task('demo','app')['status'],'blocked')

    def test_uncertain_submission_does_not_duplicate_the_approved_attempt(self):
        self.authorize();self.fake.fail=True;self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','app')['attempts'],1)
        self.assertEqual(len(self.fake.calls),1)

    def test_cancellation_does_not_relaunch_approved_code(self):
        self.authorize();self.rt.tick('demo');self.rt.cancel('demo');self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','app')['attempts'],1)
        self.assertEqual(len(self.fake.calls),1)
        self.assertEqual(self.rt.status('demo')['status'],'cancelled')

    def test_approved_candidate_preserves_lineage_and_prevents_replay(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_edit.subprocess.run',side_effect=self.fake_run) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(run.call_count,3)
        r=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertFalse(r['lineage']['selected']);self.assertEqual(r['lineage']['script_sha256'],self.op['execution']['parameters']['script_sha256'])

    def test_approval_survives_restart_but_not_contract_change(self):
        self.authorize();self.rt.close();self.rt=Runtime(self.root/'runtime',self.fake)
        task=self.rt.task('demo','app');spec=self.rt.spec(task)
        self.assertTrue(host_code.approved(self.rt,'demo','app',spec))
        spec['limits']['seconds']-=1
        with self.assertRaisesRegex(ValueError,'changed after'):host_code.approved(self.rt,'demo','app',spec)

    def test_changed_script_before_claim_is_blocked_without_consuming_attempt(self):
        self.authorize();a=self.rt.artifact(self.op['inputs'][1]['artifact']);p=Path(a['blob']);p.chmod(0o600);p.write_text('changed')
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','app')['attempts'],0);self.assertEqual(self.fake.calls,[])

    def test_future_script_and_fake_permissions_are_rejected(self):
        a=copy.deepcopy(self.op);a['inputs'][1].pop('artifact');a['inputs'][1].update(from_task='produce',output='edit.py');a['dependencies']=['produce']
        with self.assertRaisesRegex(ValueError,'already registered'):c.assignment(a)
        a=copy.deepcopy(self.op);a['execution']['parameters']['permissions']='workspace_only'
        with self.assertRaisesRegex(ValueError,'no isolation'):c.assignment(a)

    def test_missing_or_changed_frozen_authorization_stops_before_host(self):
        frozen,control=self.frozen();frozen['limits']['seconds']-=1
        with patch('orchestrator.blender_edit.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'assignment changed'):execute(frozen,control)
            run.assert_not_called()

    def test_crash_preserves_receipt_and_never_reopens_or_retries(self):
        frozen,control=self.frozen()
        def crash(argv,**kw):
            if argv[argv.index('--')+1]=='edit':return subprocess.CompletedProcess(argv,-11,b'',b'crash')
            return self.fake_run(argv,**kw)
        with patch('orchestrator.blender_edit.subprocess.run',side_effect=crash) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(run.call_count,2)
        self.assertEqual(json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())['runs'][-1]['returncode'],-11)

    def test_timeout_stops_with_receipt(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_edit.subprocess.run',side_effect=subprocess.TimeoutExpired([],1,output=b'partial')) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(run.call_count,1)
        self.assertTrue(json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())['runs'][0]['timeout'])

    def test_changed_baseline_fails_before_independent_verification(self):
        frozen,control=self.frozen()
        def mutate(argv,**kw):
            r=self.fake_run(argv,**kw)
            if argv[argv.index('--')+1]=='edit':(Path(argv[-1])/'checks.json').write_text('{}')
            return r
        with patch('orchestrator.blender_edit.subprocess.run',side_effect=mutate) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(run.call_count,2)

    def test_semantic_checks_detect_camera_and_unrelated_geometry_changes(self):
        before=dict(objects={'Roof':{'type':'MESH','mesh_hash':'roof'},'Other':{'type':'MESH','mesh_hash':'original'},'Camera':{'type':'CAMERA','lens':50}},materials={'Material':{'roughness':.5}},camera='Camera',dimensions={'Roof':[2,2,2]},collections={},frame=1)
        after=copy.deepcopy(before);after['objects']['Roof']['mesh_hash']='changed';after['dimensions']['Roof']=[2,2,2.6]
        self.assertEqual(compare(before,after,checks()),[])
        after['objects']['Camera']['lens']=30;after['objects']['Other']['mesh_hash']='lost';after['materials']['Material']['roughness']=1
        errors=compare(before,after,checks());self.assertEqual(len(errors),3)

    def test_invalid_checks_and_oversized_previews_rejected(self):
        value=checks();value['preview']['resolution']=[100000,64]
        with self.assertRaises(ValueError):validate_checks(value)

    def test_material_json_roundtrip_does_not_report_false_change(self):
        after=dict(objects={'Roof':{'type':'MESH'}},materials={'Blue':{'inputs':[('Color',[0,0,1,1])],
            'links':[('Shader','BSDF','Output','Surface')]}},camera='Camera',dimensions={'Roof':[2,2,2.6]},collections={},frame=1)
        before=json.loads(json.dumps(after))
        self.assertEqual(compare(before,after,checks()),[])
        after['materials']['Blue']['inputs'][0]=('Color',[1,0,0,1])
        self.assertIn('Material properties or node graphs changed',compare(before,after,checks()))

if __name__=='__main__':unittest.main()
