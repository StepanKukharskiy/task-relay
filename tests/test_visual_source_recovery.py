"""Selected PNG bytes and saved unexecuted proposals retain visual authority."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import contracts as c, worker_capabilities
from orchestrator.storage import transaction
from task_relay import production_planning as planning, routing_inputs, external_evidence
from tests import test_production_planning as fixtures
from tests.test_gemini import PNG


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    queue=fixtures.Tests.queue
    action=fixtures.Tests.action
    row=fixtures.Tests.row
    response=fixtures.Tests.response

    def test_workflow_image_without_upload_id_reaches_both_assignments(self):
        image=self.rt.root/'room.png';image.write_bytes(PNG)
        def frozen(state,job):
            values=routing_inputs.capture(state,job,[(image,'room.png','exact workflow source',None,None)],section='pipeline')
            values[0]['workflow_artifact']='exact-room-version'
            return values
        with patch('task_relay.pipelines.frozen_sources',side_effect=frozen):row=dict(self.queue())
        payload=json.loads(row['context']);source=next(s for s in payload['sources'] if s.get('workflow_artifact'))
        self.assertNotIn('upload_id',source)
        self.assertTrue(source['visual_reference'])
        self.assertEqual(planning.verify_artifact(self.rt,source).read_bytes(),PNG)
        _,plan=planning.validate_result(c.encoded(self.response()),row)
        for task in plan['tasks']:
            bound=next(i for i in task['inputs'] if i.get('artifact')==source['artifact'])
            self.assertTrue(bound['visual_reference'])

    def legacy_inventory(self):
        row=dict(self.queue(text='Inventory visible furniture in the supplied room image.'))
        image=self.rt.root/'legacy.png';image.write_bytes(PNG);aid=self.rt.register(image,'Frozen workflow image')
        source=planning.source_entry(self.rt,aid,'room.png','Exact room','Pixels only');source.pop('visual_reference')
        payload=json.loads(row['context']);payload['sources'].append(source);payload['required_artifacts'].append(aid)
        profile=worker_capabilities.entry({'type':'gemini-agent','model':'fixture'})
        payload['options']['worker_catalog'].append(profile)
        value=self.response();producer,review=value['plan']['tasks']
        for task in value['plan']['tasks']:
            task.pop('tools',None);task.pop('user_gate',None)
            task['worker']={'requires':['files.text','images.view']}
            task['limits']=dict(seconds=600,tool_calls=24,provider_requests=24,output_bytes=200000)
        producer['outputs']=[dict(path='delivery/inventory.json',purpose='Inventory'),dict(path='delivery/inventory.md',purpose='Notes')]
        producer['inputs']=[{k:source[k] for k in ('artifact','path','purpose','authority','media_type')}]
        producer['sourcing']=dict(version=2,kind='inventory',image={'source':aid},max_records=3)
        review['inputs']=[dict(from_task=producer['id'],output=o['path'],path='upstream/'+o['path'],purpose='Review exact output',authority='Candidate') for o in producer['outputs']]
        raw=c.encoded(value)
        with self.state.db:
            self.state.db.execute("UPDATE production_plans SET status='blocked',calls=2,error=?,context=?,context_hash=?,options=? WHERE id=?",('Inventory reviewer must inspect original image pixels',c.encoded(payload),c.digest(payload),c.encoded(payload['options']),row['id']))
            self.state.db.execute('INSERT INTO production_plan_calls VALUES (?,?,?,?,?,?,?)',(row['id'],2,'{}',raw,'{}','Inventory reviewer must inspect original image pixels',1))
        return dict(self.row()),raw

    def test_saved_inventory_recovers_exact_bytes_without_provider_or_budget_reset(self):
        old,raw=self.legacy_inventory()
        with transaction(self.state.db),patch.object(planning.Worker,'tick',side_effect=AssertionError('No provider call')):
            ident,receipt=planning.recover_validated_response(self.state,old['id'])
        self.assertEqual(dict(self.row()),old)
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        self.assertEqual(successor['status'],'ready');self.assertIsNone(successor['run'])
        self.assertEqual(successor['request'],old['request'])
        self.assertEqual(json.loads(successor['options']),json.loads(old['options']))
        self.assertEqual(receipt['call'],2)
        self.assertEqual(self.state.db.execute('SELECT response FROM production_plan_calls').fetchone()[0],raw)
        self.assertTrue(receipt['visual_reference_recovery']['sources'][0]['visual_reference'])
        plan=json.loads(successor['plan']);self.assertEqual(plan['tasks'][0]['worker']['executor'],'gemini-agent')
        self.assertEqual(plan['tasks'][0]['operation_contract']['id'],'sourcing.inventory')
        planning.validate_bound_worker_inputs(self.rt,plan,json.loads(successor['context']))
        with self.assertRaisesRegex(ValueError,'already recovered'),transaction(self.state.db):
            planning.recover_validated_response(self.state,old['id'])
        self.bridge.flush(False)
        with transaction(self.state.db),patch('orchestrator.executors.available'):
            planning.apply(self.state,successor['token'],'start')
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?',(ident,)).fetchone()[0],'started')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def test_existing_false_visual_marker_is_not_overridden(self):
        old,_=self.legacy_inventory();payload=json.loads(old['context']);payload['sources'][-1]['visual_reference']=False
        with self.state.db:self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(payload),c.digest(payload),old['id']))
        with self.assertRaisesRegex(ValueError,'No saved proposal'),transaction(self.state.db):planning.recover_validated_response(self.state,old['id'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_global_evidence_goal_is_scoped_to_frozen_assignment(self):
        global_request='Verify public catalog sources and manufacturer SKU prices online.'
        payload={'original_request':global_request,'sources':[], 'pipeline_step':{'instruction':'Inspect the exact room pixels and inventory visible furniture.','deliverables':{'items':'Visual inventory JSON','notes':'Room notes'}}}
        self.assertTrue(external_evidence.required(global_request));self.assertFalse(external_evidence.needed(payload))
        research=copy.deepcopy(payload);research['pipeline_step']['instruction']='Verify public catalog sources and manufacturer SKU prices online.'
        self.assertTrue(external_evidence.needed(research))
        self.assertTrue(external_evidence.needed({'original_request':global_request,'sources':[]}))
