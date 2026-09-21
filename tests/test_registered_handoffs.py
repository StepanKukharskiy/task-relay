"""Procedural registered output binding; no network, images or paid workers."""
import copy
import json
import time
import unittest
from orchestrator import contracts as c, handoff_contracts as h
from orchestrator.storage import transaction
from task_relay import pipelines, production_planning as planning, workflow_correction as correction
from tests import test_production_planning as fixture
from tests.test_handoff_contracts import stage, edge
from tests import test_workflow_correction as routing_fixture
from tests.test_mixed_execution import operation


def workflow():
    return dict(kind='plan_pipeline',contract_version=1,title='Research photos and deck',planning_only=True,stages=[
        stage('research','conversation',{'facts':{'media_type':'text/markdown'}}),
        stage('photos','production',{'photos':{'media_type':'application/json'}},['images.collect'],[edge('research','facts','text/markdown')]),
        stage('deck','production',{'deck':{'media_type':h.PPTX_MIME}},['pptx.create'],[edge('photos','photos','application/json','pptx.create')])])


class BindingTests(unittest.TestCase):
    def test_operation_owns_type_and_downstream_edge(self):
        original=workflow();before=copy.deepcopy(original)
        corrected,changes=correction.bind_registered_outputs(original,'Research plants and find their photos for a deck.')
        self.assertEqual(original,before)
        self.assertEqual(corrected['stages'][1]['handoff']['outputs']['photos']['media_type'],'application/zip')
        self.assertEqual(corrected['stages'][2]['handoff']['inputs'][0]['media_type'],'application/zip')
        self.assertEqual(len(changes),2);h.compile_workflow(corrected['stages'],required=True)

    def test_other_registered_operations_use_same_binding(self):
        for cap,media in [('images.fetch','application/zip'),('pptx.create',h.PPTX_MIME),('gemini.image','image/png'),('text.bundle','text/plain')]:
            original=dict(stages=[stage('result','production',{'result':{'media_type':'application/json'}},[cap])])
            corrected,_=correction.bind_registered_outputs(original,'Produce the result.')
            self.assertEqual(corrected['stages'][0]['handoff']['outputs']['result']['media_type'],media)

    def test_explicit_format_and_ambiguous_outputs_are_not_guessed(self):
        with self.assertRaisesRegex(ValueError,'explicitly named'):
            correction.bind_registered_outputs(workflow(),'Deliver the photos as JSON.')
        ambiguous=workflow();ambiguous['stages'][1]['handoff']['outputs']['summary']={'media_type':'application/json'}
        ambiguous['stages'][1]['deliverables']['summary']='summary'
        same,changes=correction.bind_registered_outputs(ambiguous,'Collect photos.')
        self.assertEqual(same,ambiguous);self.assertEqual(changes,[])
        with self.assertRaisesRegex(h.ContractError,'bundle'):h.compile_workflow(same['stages'],required=True)
        ambiguous['stages'][1]['handoff']['outputs']['photos']['media_type']='application/zip'
        ambiguous['stages'][2]['handoff']['inputs'][0]['media_type']='application/zip'
        h.compile_workflow(ambiguous['stages'],required=True)


class RoutingTests(unittest.TestCase):
    setUp=routing_fixture.Tests.setUp
    tearDown=routing_fixture.Tests.tearDown
    run_request=routing_fixture.Tests.run_request

    def test_bad_photo_type_binds_without_second_model_call(self):
        original=workflow();row=self.run_request([original],prompt='Research plants, collect their photos and create a presentation.')
        self.assertEqual(row['status'],'answered',row['answer']);self.assertEqual(len(self.requests),1)
        saved=self.state.get('orchestrator-handoff-binding:1')
        self.assertEqual(json.loads(saved['response'])['action'],original)
        spec=json.loads(self.state.db.execute('SELECT spec FROM relay_pipelines').fetchone()[0])
        self.assertEqual(spec['stages'][1]['handoff']['outputs']['photos']['media_type'],'application/zip')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_binding_cannot_hide_duplicate_fields_in_provider_response(self):
        from task_relay import orchestrator_chat as chat
        self.bridge.process({'update_id':1,'message':{'text':'/orchestrator Collect photos and make a deck.','from':{'id':7},'chat':{'id':7,'type':'private'}}})
        raw='{"answer":"Plan","action":null,"action":'+json.dumps(workflow())+'}'
        chat.Worker(self.state,lambda *_:raw).tick()
        row=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertEqual(row['status'],'failed')
        self.assertIsNone(self.state.get('orchestrator-handoff-binding:1'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)


class RecoveryTests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response

    def saved(self):
        row=dict(self.queue());action=workflow();action['stages'][1]['handoff']['inputs']=[]
        payload=json.loads(row['context']);options=json.loads(row['options'])
        options.update(step_capabilities=['images.collect'],deliverables={'photos':'Photos'},max_tasks=6)
        payload.update(options=options,pipeline_step=action['stages'][1],handoff_sources=[])
        response=self.response();review=response['plan']['tasks'][1]
        collect=operation('collect','images.collect',[],max_attempts=1,tools=[],limits=dict(seconds=600,tool_calls=1,output_bytes=45000000))
        collect['execution']['parameters']={'subjects':[dict(id='sample',label='Sample',query='Sample') ]}
        collect['outputs']=[dict(path='delivery/photos.zip',purpose='Attributed photos and manifest',media_type='application/zip')]
        review.update(criteria=copy.deepcopy(collect['criteria']),review_of='collect',dependencies=['collect'],inputs=[dict(from_task='collect',output='delivery/photos.zip',path='candidate/photos.zip',purpose='Review coverage and identity',authority='Unaccepted candidate',media_type='application/zip')])
        response['plan']['tasks']=[collect,review];response['deliverable_map']={'photos':{'task':'collect','output':'delivery/photos.zip'}}
        with self.state.db:
            self.state.db.execute("UPDATE production_plans SET status='blocked',context=?,context_hash=?,options=? WHERE id=?",(c.encoded(payload),c.digest(payload),c.encoded(options),row['id']))
            self.state.db.execute('INSERT INTO production_plan_calls VALUES (?,?,?,?,?,?,?)',(row['id'],1,'{}',json.dumps(response),'{}','Concrete output type differs',time.time()))
            self.state.db.execute('INSERT INTO relay_pipelines VALUES (?,?,?,?,?,?,?,?,?,?)',('fixture-pipe',2,'Research and collect photos then create a deck.',action['title'],c.encoded(action),'telegram','fixture','model','blocked',time.time()))
            for i,s in enumerate(action['stages']):
                self.state.db.execute('INSERT INTO relay_pipeline_steps(pipeline,position,id,status) VALUES (?,?,?,?)',('fixture-pipe',i,s['id'],['completed','blocked','pending'][i]))
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='plan_production',target=?,request_id=1 WHERE id='photos'",(row['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET result='Exact completed research' WHERE id='research'")
        return dict(self.row()),action

    def test_recovery_reuses_exact_proposal_preserves_research_and_needs_start(self):
        old,spec=self.saved()
        with transaction(self.state.db):pipelines.control(self.state,'fixture-pipe','recover_planning')
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(old['id'],)).fetchone()
        self.assertIsNotNone(successor);self.assertEqual(successor['status'],'ready');self.assertIsNone(successor['run'])
        self.assertEqual(dict(self.row()),old)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plan_calls').fetchone()[0],1)
        pipe=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        step=self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE id='photos'").fetchone()
        self.assertFalse(pipelines.check_plan(self.state,pipe,step,successor))
        self.assertEqual(self.state.db.execute("SELECT result FROM relay_pipeline_steps WHERE id='research'").fetchone()[0],'Exact completed research')
        plan=json.loads(successor['plan']);self.assertEqual(len(plan['tasks']),2)
        self.assertEqual(plan['tasks'][1]['review_of'],'collect')
        self.assertEqual(json.loads(successor['context'])['stage_type_recovery']['previous_spec'],spec)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'Only blocked'),transaction(self.state.db):pipelines.control(self.state,'fixture-pipe','recover_planning')

    def test_started_downstream_and_missing_review_leave_state_unchanged(self):
        old,spec=self.saved()
        with self.state.db:self.state.db.execute("UPDATE relay_pipeline_steps SET status='running' WHERE id='deck'")
        with self.assertRaisesRegex(ValueError,'another started'),transaction(self.state.db):pipelines.control(self.state,'fixture-pipe','recover_planning')
        self.assertEqual(json.loads(self.state.db.execute('SELECT spec FROM relay_pipelines').fetchone()[0]),spec)
        with self.state.db:
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='pending' WHERE id='deck'")
            call=self.state.db.execute('SELECT response FROM production_plan_calls').fetchone()[0]
            bad=json.loads(call);bad['plan']['tasks'][1]['inputs']=[]
            self.state.db.execute('UPDATE production_plan_calls SET response=?',(json.dumps(bad),))
        with self.assertRaisesRegex(ValueError,'No saved proposal'),transaction(self.state.db):pipelines.control(self.state,'fixture-pipe','recover_planning')
        self.assertEqual(json.loads(self.state.db.execute('SELECT spec FROM relay_pipelines').fetchone()[0]),spec)
