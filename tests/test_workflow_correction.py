"""Rejected workflow correction is bounded, scope preserving and before dispatch."""
import json
import unittest
from unittest.mock import patch

from task_relay import orchestrator_chat as chat, pipelines, workflow_correction as correction
from tests import test_production_planning as fixtures
from tests.test_handoff_contracts import architecture


def proposal(bad=False):
    stages=architecture()
    if bad:
        stages[1]['handoff']['outputs']['model']['media_type']='application/x-rhino-3dm'
        stages[2]['handoff']['outputs']['visual']['media_type']='image/jpeg'
        stages[3]['handoff']['inputs'][1]['media_type']='image/jpeg'
    return dict(kind='plan_pipeline',contract_version=1,title='Cross-provider fixture',planning_only=True,stages=stages)


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self);del self.fail
    tearDown=fixtures.Tests.tearDown

    def run_request(self, responses, prompt='Research then model, render and create a three-slide deck.'):
        self.bridge.process({'update_id':1,'message':{'text':'/orchestrator '+prompt,'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        self.requests=[]
        def generate(job,payload):
            self.requests.append(payload)
            value=responses[min(len(self.requests)-1,len(responses)-1)]
            if isinstance(value,BaseException):raise value
            return json.dumps({'answer':'Proposed workflow','action':value})
        chat.Worker(self.state,generate).tick()
        return self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()

    def test_corrects_all_ports_once_and_keeps_original_response(self):
        old=proposal(True);new=proposal()
        row=self.run_request([old,new])
        self.assertEqual(row['status'],'answered',row['answer']);self.assertEqual(len(self.requests),2)
        request=self.requests[1]['routing_workflow_correction']
        self.assertEqual(request['previous_action'],old)
        self.assertEqual(request['operation_types']['gemini.image']['output_type'],'image/png')
        saved=self.state.get('orchestrator-workflow-correction:1')
        self.assertEqual(json.loads(saved['response'])['action'],old)
        self.assertEqual(json.loads(saved['corrected_response'])['action'],new)
        self.assertEqual(len(saved['changes']),3)
        p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertEqual(json.loads(p['spec']),new);self.assertEqual(p['request'],row['prompt'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_second_invalid_proposal_stops_without_loop_or_dispatch(self):
        row=self.run_request([proposal(True),proposal(True)])
        self.assertEqual(row['status'],'failed');self.assertEqual(len(self.requests),2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)

    def test_saved_rejection_recovery_preserves_request_and_dispatches_only_once(self):
        from orchestrator.storage import transaction
        old=dict(self.run_request([proposal(True),proposal(True)]))
        raw=json.dumps({'answer':'Corrected file type declarations','action':proposal()})
        snapshot=chat.snapshot(self.state,None)
        with transaction(self.state.db):first=correction.recover_saved(self.state,1,raw,snapshot)
        with transaction(self.state.db):second=correction.recover_saved(self.state,1,raw,snapshot)
        self.assertEqual(first,second)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()),old)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        revised=proposal();revised['stages'][-1]['handoff']['outputs']['deck']['slides']=2
        with self.assertRaisesRegex(ValueError,'scope'),transaction(self.state.db):
            correction.recover_saved(self.state,1,json.dumps({'answer':'Changed','action':revised}),snapshot)

    def test_saved_recovery_refuses_uncertain_provider_response(self):
        from orchestrator.storage import transaction
        self.run_request([proposal(True),TimeoutError('unknown')])
        with self.assertRaisesRegex(ValueError,'confirmed rejected'),transaction(self.state.db):
            correction.recover_saved(self.state,1,json.dumps({'answer':'Corrected','action':proposal()}),chat.snapshot(self.state,None))

    def test_scope_and_quantity_changes_are_not_accepted(self):
        revised=proposal();revised['stages'][-1]['handoff']['outputs']['deck']['slides']=2
        row=self.run_request([proposal(True),revised])
        self.assertEqual(row['status'],'failed');self.assertIn('scope, decisions or limits',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)

    def test_explicit_jpeg_request_needs_conversion_not_relabeling(self):
        row=self.run_request([proposal(True),proposal()],prompt='Generate a JPEG visualization and a three-slide deck.')
        self.assertEqual(row['status'],'failed');self.assertIn('explicitly named file format',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)

    def test_unsupported_scale_does_not_trigger_provider_correction(self):
        big=proposal();big['stages'][-1]['handoff']['outputs']['deck']['slides']=600
        row=self.run_request([big])
        self.assertEqual(row['status'],'failed');self.assertEqual(len(self.requests),1)
        self.assertIsNone(self.state.get('orchestrator-workflow-correction:1'))

    def test_provider_failure_during_correction_keeps_first_response_and_no_dispatch(self):
        row=self.run_request([proposal(True),TimeoutError('Response unknown')])
        self.assertEqual(row['status'],'failed');self.assertEqual(len(self.requests),2)
        self.assertEqual(json.loads(self.state.get('orchestrator-workflow-correction:1')['response'])['action'],proposal(True))
        chat.Worker(self.state,lambda *_:self.fail('An uncertain correction must not be replayed')).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)

    def test_only_media_fields_can_change_including_gates_and_named_providers(self):
        original=proposal(True)
        for field,value in [('gate','selection'),('instruction','Use a different provider'),('route','production')]:
            revised=proposal();revised['stages'][2][field]=value
            if revised['stages'][2][field]==original['stages'][2][field]:continue
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'scope, decisions or limits'):
                correction.verify(original,revised,'Generate an image.')


class TransportTests(unittest.TestCase):
    from tests.test_orchestrator_files import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    response=Fixture.response
    request=Fixture.request
    args=Fixture.args

    def test_type_correction_without_tools_is_one_call_for_every_provider(self):
        from task_relay import orchestrator_files as files
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            client=unittest.mock.Mock();client.request.return_value=self.response(provider)
            with self.subTest(provider=provider):
                files.run(provider,client,'fixture',self.request(provider),[],self.receipt)
                client.request.assert_called_once()
                self.assertNotIn('tools',client.request.call_args.args[1])

    def test_correction_transport_cannot_research_again(self):
        from task_relay import orchestrator_files as files
        client=unittest.mock.Mock();client.request.return_value=self.response('gemini','README.md')
        with patch.object(files,'execute') as execute,self.assertRaisesRegex(ValueError,'unavailable tool'):
            files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt)
        client.request.assert_called_once();execute.assert_not_called()

    def test_generate_uses_distinct_receipt_and_disables_all_read_tools(self):
        from task_relay import gemini,orchestrator_files as files
        payload={'user_message':'Original exact request','interface':'telegram',
                 'snapshot':{'project_roadmaps':{'available_projects':[str(self.root)]}},
                 'routing_workflow_correction':{'previous_action':proposal(True)}}
        with patch.object(gemini,'DATA',self.root),patch.object(gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(gemini,'Client'),patch.object(files,'run',return_value='fixture') as run:
            chat.generate({'id':1,'provider':'gemini','model':'test-model'},payload)
        args=run.call_args.args
        self.assertEqual(args[4],[]);self.assertIsNone(args[6]);self.assertIsNone(args[7])
        self.assertTrue(str(args[5]).endswith('-workflow-correction.json'))
        body=json.loads(args[3]['contents'][0]['parts'][0]['text'])
        self.assertEqual(body['user_message'],'Original exact request')
        self.assertIn('routing_workflow_correction',body)
