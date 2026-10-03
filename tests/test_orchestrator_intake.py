"""Intake precedes any drafting, preserves scope and cannot masquerade as output."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from task_relay import orchestrator_advice as advice, orchestrator_chat as chat, orchestrator_files as files
from task_relay import request_contract as contracts
from tests import intake_fixtures as intake, test_orchestrator_files as file_fixture
from tests import test_production_planning as stage_fixture
from tests.test_response_data import DATA,response


class Tests(unittest.TestCase):
    def setUp(self):
        stage_fixture.Tests.setUp(self)
        del self.fail
    tearDown=stage_fixture.Tests.tearDown
    row=stage_fixture.Tests.row

    def run_model(self,scope,data,request='Please create drafts in md for all 5 articles with examples and code snippets necessary to use these algorithms'):
        self.bridge.process({'update_id':1,'message':{'text':'/orchestrator '+request,'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        client=Mock();client.submitted_requests=[]
        replies=iter([intake.response('gemini',scope),response('gemini',data)])
        def submit(endpoint,request):
            client.submitted_requests.append(copy.deepcopy(request));return next(replies)
        client.request.side_effect=submit
        with patch.object(chat.gemini,'DATA',self.root),patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(chat.gemini,'Client',return_value=client):
            worker=chat.Worker(self.state);worker.tick();worker.tick()
        return client,self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()

    def test_five_file_request_reaches_general_planner_after_frozen_intake(self):
        scope=intake.work([intake.outcome('articles',5,checks=['nonempty','utf8','fenced_code'])])
        data={**copy.deepcopy(DATA),'answer':'Preparing the requested file-production plan.',
              'action_json':json.dumps(stage_fixture.Tests.action(self)),'next_options':[]}
        client,row=self.run_model(scope,data)
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(client.request.call_count,2)
        first=client.submitted_requests[0]
        self.assertEqual([d['name'] for d in first['tools'][0]['functionDeclarations']],['relay_intake'])
        self.assertEqual(first['toolConfig']['functionCallingConfig']['allowedFunctionNames'],['relay_intake'])
        second=client.submitted_requests[1]
        final=second['tools'][0]['functionDeclarations'][-1]['parametersJsonSchema']
        self.assertEqual(final['properties']['action_json']['type'],['string','null'])
        self.assertEqual(final['properties']['work_status']['enum'],['respond','needs_input','blocked'])
        plan=self.row();self.assertEqual(plan['request'],row['prompt'])
        options=json.loads(plan['options']);self.assertEqual(options['request_contract'],scope)
        self.assertEqual(set(options['deliverables']),{f'articles-{i}' for i in range(1,6)})
        self.assertEqual(self.state.get('orchestrator-request-contract:1')['contract'],scope)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])
        journal=json.loads((self.root/'orchestrator-reads'/(hashlib.sha256(b'1').hexdigest()+'.json')).read_text())
        self.assertEqual(journal[0]['intake'],scope)
        self.assertEqual(json.loads(journal[-1]['response_data']),data)

    def test_inline_substitute_is_saved_and_refused_without_replay_or_dispatch(self):
        scope=intake.work([intake.outcome('configs',2,format='.json',checks=['nonempty','json'])])
        data={**copy.deepcopy(DATA),'answer':'Here are both config files: {"a":1}, {"b":2}'}
        client,row=self.run_model(scope,data,'Мне нужны два отдельных файла настроек JSON.')
        self.assertEqual(row['status'],'failed',row['answer'])
        self.assertIn('inline text',row['answer'])
        self.assertEqual(json.loads(row['response'])['answer'],data['answer'])
        self.assertEqual(json.loads(row['response'])['request_contract'],scope)
        self.assertEqual(client.request.call_count,2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_status_and_ambiguity_do_not_authorize_work(self):
        for mode in ('answer','clarify'):
            with self.subTest(mode=mode):
                scope={'mode':mode,'reason':'A status question or unresolved source identity.','outcomes':[]}
                data={**copy.deepcopy(DATA),'action_json':json.dumps(stage_fixture.Tests.action(self))}
                with self.assertRaisesRegex(ValueError,'cannot dispatch'):
                    contracts.route({**chat.response_json(json.dumps(data)),'request_contract':scope})
        client,row=self.run_model(intake.ANSWER,copy.deepcopy(DATA),'Why did my request for five files fail?')
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertIsNone(self.row());self.assertEqual(client.request.call_count,2)

    def test_final_reply_cannot_reinterpret_the_frozen_request(self):
        scope=intake.work([intake.outcome(count=5)])
        data={**copy.deepcopy(DATA),'request_contract':intake.ANSWER}
        client,row=self.run_model(scope,data)
        self.assertEqual(row['status'],'failed');self.assertIn('change the frozen',row['answer'])
        self.assertIsNone(self.row());self.assertEqual(client.request.call_count,2)

    def test_late_missing_input_keeps_requested_outcomes_and_asks_without_dispatch(self):
        scope=intake.work([intake.outcome('configs',2,format='.json',checks=['nonempty','json'])])
        data={**copy.deepcopy(DATA),'work_status':'needs_input','answer':'Which of the two saved source versions should these configurations use?'}
        client,row=self.run_model(scope,data,'Produce two configurations using the saved source.')
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(json.loads(row['response'])['request_contract'],scope)
        self.assertEqual(json.loads(row['response'])['work_status'],'needs_input')
        self.assertEqual(self.state.get('orchestrator-request-contract:1')['contract'],scope)
        self.assertIsNone(self.row());self.assertEqual(self.factory.calls,[])
        self.assertEqual(client.request.call_count,2)



class TransportTests(unittest.TestCase):
    setUp=file_fixture.Tests.setUp
    tearDown=file_fixture.Tests.tearDown
    request=file_fixture.Tests.request
    args=file_fixture.Tests.args

    def test_intake_is_separate_from_the_unchanged_evidence_budget_for_all_providers(self):
        for name in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=name):
                scope=intake.ANSWER
                client=Mock();client.request.side_effect=[intake.response(name,scope),file_fixture.Tests.response(self,name,'README.md'),response(name,DATA)]
                with patch.object(files,'MAX_ROUNDS',1):
                    raw=files.run(name,client,'fixture',self.request(name),[str(self.root)],self.receipt,
                                  response_definition=advice.response_definition('Explain the file.',[]),intake_definition=contracts.definition())
                self.assertEqual(json.loads(raw)['request_contract'],scope)
                self.assertEqual(client.request.call_count,3)
                journal=json.loads(self.receipt.read_text())
                self.assertEqual(sum(len(r.get('reads',[])) for r in journal),1)
                self.assertEqual(journal[0]['intake'],scope)
                self.assertEqual(json.loads(journal[-1]['response_data']),DATA)

    def test_reads_or_draft_answers_cannot_skip_intake(self):
        for reply in (response('gemini',DATA),file_fixture.Tests.response(self,'gemini','README.md')):
            client=Mock();client.request.return_value=reply
            with patch.object(files,'execute') as execute,self.assertRaisesRegex(ValueError,'intake must precede'):
                files.run('gemini',client,'fixture',self.request('gemini'),[str(self.root)],self.receipt,
                          response_definition=advice.response_definition('Create files.',[]),intake_definition=contracts.definition())
            client.request.assert_called_once();execute.assert_not_called()

    def test_routing_correction_reuses_the_frozen_intake_without_reclassification(self):
        client=Mock();client.request.return_value=response('gemini',DATA)
        raw=files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,
                      response_definition=advice.response_definition('Explain status.',[]),frozen_intake=intake.ANSWER)
        self.assertEqual(json.loads(raw)['request_contract'],intake.ANSWER)
        client.request.assert_called_once()
        self.assertEqual(json.loads(self.receipt.read_text())[0]['frozen_intake'],intake.ANSWER)

    def test_source_patch_keeps_frozen_outcomes_for_validation_after_the_existing_merge(self):
        scope=intake.work([intake.outcome(count=5)])
        data={**copy.deepcopy(DATA),'action_json':json.dumps({'artifact_ids':['source-version']})}
        client=Mock();client.request.return_value=response('gemini',data)
        raw=files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,
                      response_definition=advice.response_definition('Create the outputs.',[]),frozen_intake=scope,route_patch=True)
        value=json.loads(raw);self.assertEqual(value['request_contract'],scope)
        self.assertEqual(value['action'],{'artifact_ids':['source-version']})
        # This is only a selection patch. It cannot dispatch as a complete route.
        with self.assertRaisesRegex(ValueError,'does not produce'):
            contracts.route(value)
        client.request.assert_called_once()
