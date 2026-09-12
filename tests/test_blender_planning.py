import copy
import json
import unittest
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

    def bounded(self,op):
        spec=execution.REGISTRY[op['execution']['capability']]
        op['limits']={'seconds':spec['seconds'],'tool_calls':1,'output_bytes':spec['output_bytes']}
        return op

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
