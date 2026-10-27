"""Scoped proposal repair preserves replies and cannot replace unrelated fields."""
import copy,json,unittest
from orchestrator import contracts as c
from task_relay import planner_correction as correction,production_planning as planning
from tests import test_production_planning as fixture


class Tests(unittest.TestCase):
    def test_worker_repairs_only_one_field_against_saved_reply(self):
        f=fixture.Tests();f.setUp();self.addCleanup(f.tearDown);row=f.queue()
        context=json.loads(row['context']);context['planner_correction_version']=1
        with f.state.db:f.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(context),c.digest(context),row['id']))
        proposal=f.response();proposal['plan']['tasks'][0]['instruction']=12
        first=c.encoded(proposal);requests=[]
        def generate(_row,payload):
            requests.append(copy.deepcopy(payload))
            if len(requests)==1:return first,{}
            contract=payload['structural_correction']['patch_contract']
            self.assertEqual(contract['path'],['plan','tasks',0,'instruction'])
            return c.encoded(dict(base_sha256=contract['base_sha256'],action='set',value_json=json.dumps('Write the requested brief'))),{}
        worker=planning.Worker(f.state,generate);worker.tick();worker.tick()
        self.assertEqual(f.row()['status'],'ready',f.row()['error'])
        calls=f.state.db.execute('SELECT response FROM production_plan_calls ORDER BY number').fetchall()
        self.assertEqual(calls[0][0],first);self.assertNotIn('plan',json.loads(calls[1][0]))
        receipt=f.state.get('planner-field-correction:'+row['id']+':2')
        self.assertEqual(receipt['base_sha256'],c.digest(proposal));self.assertEqual(f.factory.calls,[])

    def test_stale_base_or_unrelated_patch_is_held(self):
        previous=dict(plan=dict(tasks=[dict(instruction=12)]));payload=dict(planner_correction_version=1,structural_correction={},planner_instructions='Frozen')
        contract=correction.prepare(payload,previous,dict(field='$.plan.tasks[0].instruction'))
        patch=dict(base_sha256=contract['base_sha256'],action='set',value_json='"correct"')
        with self.assertRaises(ValueError):correction.apply(c.encoded({**patch,'path':'$.plan'}),previous,contract)
        with self.assertRaises(ValueError):correction.apply(c.encoded(patch),dict(plan={}),contract)
        self.assertIsNone(correction.prepare(payload,previous,dict(field='$.plan')))
