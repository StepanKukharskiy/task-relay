import copy
import json
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from tests import test_production_planning as fixture
from tests.test_blender_operations import operation
from orchestrator import execution
import production_planning as planning


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    start=fixture.Tests.start
    click=fixture.Tests.click

    def bounded(self,op):
        spec=execution.REGISTRY[op['execution']['capability']]
        op['limits']={'seconds':spec['seconds'],'tool_calls':1,'output_bytes':spec['output_bytes']}
        return op

    def test_edit_asset_animation_contracts_reach_both_workers(self):
        import production_control as pc
        from tests.test_blender_assets import inputs as assets
        from tests.test_blender_animation import inputs as animation_inputs
        from orchestrator.blender_edit import validate_checks
        from orchestrator.blender_assets import validate as validate_assets
        from orchestrator.blender_animation import validate as validate_animation
        edit=dict(changed_objects=['Tower'],preserve_other_objects=True,preserve_cameras=True,preserve_materials=True,
                  expected_dimensions={'Tower':[2,3,4]},preview=dict(camera='Camera',resolution=[64,64],samples=1))
        asset_root=self.root/'asset-fixture';asset_root.mkdir()
        _,asset=assets(self.rt,asset_root)
        animation_root=self.root/'animation-fixture';animation_root.mkdir()
        _,animation=animation_inputs(self.rt,animation_root)
        cases=[('blender.run_python',edit,validate_checks),('blender.import_asset',asset,validate_assets),
               ('blender.animate',animation,validate_animation)]
        for ident,(cap,value,validate) in enumerate(cases,1):
            with self.subTest(cap=cap),patch('host_apps.blender',return_value=dict(available=True,executable='fixture',evidence='fixture')):
                self.queue(ident=ident,action=self.action(step_capabilities=[cap]))
                response=self.response();response['deferred_operations']={cap:'Prepare exact inputs for a separately approved host operation.'}
                producer,review=response['plan']['tasks']
                producer['outputs'].append({'path':'preparation.json','purpose':'Exact prepared manifest'})
                review['inputs'].append({'from_task':'produce','output':'preparation.json','path':'candidate/preparation.json','purpose':'Review prepared manifest','authority':'Candidate'})
                producer['selection_outputs']=[o['path'] for o in producer['outputs']]
                planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
                row=self.row(ident);self.assertEqual(row['status'],'ready',row['error']);self.start(row)
                run='production-'+str(ident);worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
                producer=self.rt.task(run,'produce')['latest'];self.factory.finish(producer);worker.tick()
                reviewer=self.rt.task(run,'review')['latest']
                for attempt in (producer,reviewer):
                    frozen=self.factory.sessions[attempt]['frozen'];workspace=Path(frozen['workspace'])
                    support=workspace/'operation-support'/cap
                    self.assertEqual(json.loads((support/'contract.json').read_text())['id'],cap)
                    for data,valid in ((value,True),({'provisional':True},False)):
                        candidate=workspace/'input-check.json';candidate.write_text(json.dumps(data))
                        result=subprocess.run([sys.executable,'-E','-S',str(support/'validate.py'),str(candidate)],cwd=workspace,capture_output=True,text=True)
                        self.assertEqual(result.returncode==0,valid,result.stderr)
                        if valid:validate(data)
                        else:
                            with self.assertRaises(ValueError):validate(data)
                self.factory.finish(reviewer,decision='accept');worker.tick()

    def test_scene_support_reaches_isolated_worker_and_validates_without_blender(self):
        from tests.test_blender_operations import scene_data
        from orchestrator.workers import CodexFactory
        for number,cap in enumerate(('blender.scene','blender.mesh_scene'),1):
            with self.subTest(cap=cap),patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
                self.queue(ident=number,action=self.action(step_capabilities=[cap]))
                planning.Worker(self.state,lambda *_:(json.dumps(self.untyped_scene_response(cap)),{})).tick()
                row=self.row(number);self.assertEqual(row['status'],'ready',row['error'])
                self.start(row);self.rt.tick(row['run'] or 'production-'+str(number))
                task=self.rt.task('production-'+str(number),'produce')
                frozen=self.factory.sessions[task['latest']]['frozen']
                workspace=Path(frozen['workspace'])
                support=workspace/'operation-support'/cap
                contract=json.loads((support/'contract.json').read_text())
                self.assertEqual(contract['scene_schema']['version'],number)
                self.assertIn('scene-data preparation/review only',frozen['instruction'])
                self.assertIn('Do not launch/probe Blender',frozen['instruction'])
                control=self.root/('prompt-check-'+str(number))
                with patch('orchestrator.workers.prepare_supervisor',return_value='fixture'):
                    CodexFactory('unused').create(control,workspace,frozen,frozen['backend'])
                prompt=(control/'prompt.txt').read_text()
                self.assertIn('The scheduler owns the later execution step',prompt)
                # -I prevents repository imports: only the copied stdlib validator
                # and small data fixture are available to this subprocess.
                data=scene_data();data['version']=number
                candidate=workspace/'test-scene.json';candidate.write_text(json.dumps(data))
                command=[sys.executable,'-I',str(support/'validate_scene.py'),str(candidate)]
                passed=subprocess.run(command,cwd=workspace,capture_output=True,text=True)
                self.assertEqual(passed.returncode,0,passed.stderr)
                self.assertIn('RELAY_SCENE_DATA_VALID',passed.stdout)
                data['objects'][0]['size']=[0,1,1];candidate.write_text(json.dumps(data))
                failed=subprocess.run(command,cwd=workspace,capture_output=True,text=True)
                self.assertNotEqual(failed.returncode,0)
                plan=json.loads(row['plan'])
                review=next(t for t in plan['tasks'] if t.get('review_of')=='produce')
                candidate_path=next(i['path'] for i in review['inputs'] if i.get('from_task')=='produce')
                self.assertIn(candidate_path,review['instruction'])
                self.assertTrue(any(i['path'].endswith('/validate_scene.py') for i in review['inputs']))

    def untyped_scene_response(self,cap='blender.scene'):
        response=self.response();tasks=response['plan']['tasks']
        tasks[0]['outputs'][0]['path']='scene.json'
        tasks[1]['inputs'][0]['output']='scene.json'
        host=self.bounded(operation(cap,[dict(from_task='produce',output='scene.json',path='scene.json',
            purpose='Scene data',authority='Candidate data')]))
        host['dependencies']=['review']
        host['limits']['tool_calls']=60
        for o in host['outputs']:o.pop('media_type')
        tasks.append(host)
        return response

    def test_untyped_scene_plan_compiles_before_approval_without_workers(self):
        for cap in ('blender.scene','blender.mesh_scene'):
            with self.subTest(cap=cap),patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
                row=self.queue(ident=1 if cap=='blender.scene' else 2,action=self.action(step_capabilities=[cap]),text='Create a twisting tower.')
                response=self.untyped_scene_response(cap);original=copy.deepcopy(response)
                _,plan=planning.validate_result(json.dumps(response),row)
                self.assertEqual(response,original)
                host=plan['tasks'][-1]
                self.assertEqual(host['dependencies'],['review','produce'])
                self.assertEqual(host['limits']['tool_calls'],1)
                self.assertEqual(host['inputs'][0]['media_type'],'application/json')
                self.assertEqual(plan['tasks'][0]['outputs'][0]['media_type'],'application/json')
                self.assertEqual(plan['tasks'][1]['inputs'][0]['media_type'],'application/json')
                self.assertEqual({o['path']:o['media_type'] for o in host['outputs']},execution.REGISTRY[cap]['outputs'])
                self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_conflicting_types_or_multiple_scene_candidates_are_not_guessed(self):
        with patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
            row=self.queue(action=self.action(step_capabilities=['blender.scene']))
        variants=[]
        bad=self.untyped_scene_response();bad['plan']['tasks'][-1]['inputs'][0]['media_type']='image/png';variants.append(bad)
        bad=self.untyped_scene_response();bad['plan']['tasks'][0]['outputs'][0]['media_type']='text/plain';variants.append(bad)
        bad=self.untyped_scene_response();bad['plan']['tasks'][-1]['outputs'][0]['media_type']='text/plain';variants.append(bad)
        bad=self.untyped_scene_response();host=bad['plan']['tasks'][-1]
        host['inputs'].append({**host['inputs'][0],'output':'other.json','path':'other.json'});variants.append(bad)
        for value in variants:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Conflicting media type|unambiguous'):
                planning.validate_result(json.dumps(value),row)

    def test_repaired_plan_reaches_ready_with_no_second_model_call(self):
        with patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
            self.queue(action=self.action(step_capabilities=['blender.scene']))
            response=self.untyped_scene_response();response['plan']['tasks'][-1]['limits']['tool_calls']=0
            calls=[]
            def generate(*args):calls.append(1);return json.dumps(response),{}
            worker=planning.Worker(self.state,generate);worker.tick();worker.tick()
        self.assertEqual(calls,[1]);self.assertEqual(self.row()['status'],'ready',self.row()['error'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_scene_plan_retains_host_boundary_types_and_approval_notice(self):
        with patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
            row=self.queue(action=self.action(step_capabilities=['blender.scene']),text='Make a twisting tower in Blender.')
            response=self.response();tasks=response['plan']['tasks']
            tasks[0]['outputs'][0]['media_type']='application/json'
            host=self.bounded(operation('blender.scene',[dict(from_task='produce',output='output.txt',path='scene.json',
                 purpose='Scene data',authority='Unaccepted geometry',media_type='application/json')]))
            host['dependencies']=['produce','review'];host['user_gate']='Review the model and preview'
            tasks.append(host)
            result,plan=planning.validate_result(json.dumps(response),row)
            host=plan['tasks'][-1]
            self.assertEqual(sum(i['media_type']=='application/json' for i in host['inputs']),1)
            self.assertTrue(any(i['path']=='request/USER-REQUEST.txt' for i in host['inputs']))
            r=dict(row);r['plan']=json.dumps(plan)
            self.assertIn('Host execution: Blender',planning.preview(r))
            self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],0)

    def test_unfamiliar_mesh_uses_general_host_operation_with_preserved_sources(self):
        with patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
            row=self.queue(action=self.action(step_capabilities=['blender.mesh_scene']),text='Make a gyroid in Blender.')
            response=self.response();tasks=response['plan']['tasks']
            tasks[0]['outputs'][0]['media_type']='application/json'
            host=self.bounded(operation('blender.mesh_scene',[dict(from_task='produce',output='output.txt',path='scene.json',
                purpose='Agent-computed mesh',authority='Unaccepted geometry',media_type='application/json')]))
            host['dependencies']=['produce','review'];tasks.append(host)
            _,plan=planning.validate_result(json.dumps(response),row)
            self.assertEqual(plan['tasks'][-1]['execution']['capability'],'blender.mesh_scene')
            self.assertEqual(plan['tasks'][-1]['dependencies'],['produce','review'])
            self.assertTrue(any(i['path']=='request/USER-REQUEST.txt' for i in plan['tasks'][-1]['inputs']))

    def test_native_artifact_is_carried_into_inspection_plan_and_review(self):
        # Register a native output through the runtime so the orchestrator catalog
        # can select its exact artifact version; no Blender/provider execution.
        from tests.test_orchestrator import plan as graph_plan
        from orchestrator.runtime import file_hash
        self.rt.create(graph_plan());self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        ws=self.factory.sessions[aid]['workspace'];(ws/'output.txt').write_bytes(b'\xffnative fixture')
        self.rt.tick('demo');artifact=self.rt.output('demo','produce','output.txt')
        self.state.db.execute("UPDATE production_artifacts SET path='scene.blend' WHERE id=?",(artifact['id'],))
        with patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
            row=self.queue(action=self.action(step_capabilities=['blender.inspect'],artifact_ids=[artifact['id']]),text='Inspect this exact scene; do not edit.')
            context=json.loads(row['context'])
            source=next(i for i in context['sources'] if i['path'].endswith('.blend'))
            host=self.bounded(operation('blender.inspect',[]))
            review=self.response()['plan']['tasks'][1];review['review_of']='app';review['dependencies']=['app'];review['criteria']=host['criteria']
            review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+o['path'].split('/')[-1],
                purpose='Inspect recorded findings',authority='Evidence',media_type=o['media_type']) for o in host['outputs']]
            value=dict(decision='ready',message='Inspect and review',plan=dict(brief='Scene inventory',tasks=[host,review]))
            _,plan=planning.validate_result(json.dumps(value),row)
            actual=next(i for i in plan['tasks'][0]['inputs'] if i['artifact']==source['artifact'])
            self.assertEqual(actual['media_type'],'application/x-blender')
            self.assertEqual(source['sha256'],file_hash(ws/'output.txt'))
            self.assertTrue(any(i.get('artifact')==source['artifact'] for i in plan['tasks'][1]['inputs']))
            preview_row=dict(row);preview_row['plan']=json.dumps(plan)
            self.assertIn('Linked libraries may resolve',planning.preview(preview_row))

    def test_startup_can_be_host_probe_and_independent_report_review(self):
        with patch('host_apps.blender',return_value={'available':True,'executable':'fixture','evidence':'fixture'}):
            row=self.queue(action=self.action(step_capabilities=['blender.startup']),text='Check Blender startup.')
            host=self.bounded(operation('blender.startup',[]))
            reviewer=self.response()['plan']['tasks'][1];reviewer['review_of']='app';reviewer['dependencies']=['app'];reviewer['criteria']=host['criteria']
            reviewer['inputs']=[dict(from_task='app',output='delivery/execution.json',path='candidate.json',purpose='Probe report',authority='Execution evidence',media_type='application/json')]
            response=dict(decision='ready',message='Probe and report review',plan=dict(brief='Blender startup',tasks=[host,reviewer]))
            _,plan=planning.validate_result(json.dumps(response),row)
            self.assertEqual(len(plan['tasks']),2)

if __name__=='__main__':unittest.main()
