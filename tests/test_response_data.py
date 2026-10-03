"""Runtime-owned response contracts, exact data receipts and bounded recovery."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from task_relay import orchestrator_advice as advice, orchestrator_chat as chat, orchestrator_files as files
from tests import intake_fixtures as intake
from tests import test_orchestrator_advice as direct_fixture, test_orchestrator_files as file_fixture

DATA = {'answer':'A small controller could be a useful UI for an external assistant.', 'action_json':None,
        'research_advice':{'recommended_mode':'none','requirement':'optional','reason':'Try the UI first; documentation can establish interface compatibility.',
                           'questions':['Which documented interfaces are compatible?']},'next_options':[],'claim_sources':[]}


def response(provider, data, extra=None):
    if provider == 'gemini':
        parts=[{'functionCall':{'name':'relay_respond','args':data}}]
        if extra:parts.append({'functionCall':extra})
        return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':parts}}]}
    call={'type':'function_call','call_id':'reply','name':'relay_respond','arguments':json.dumps(data)}
    if provider == 'openai':return {'status':'completed','output':[call]}
    return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
             'tool_calls':[{'id':'reply','type':'function','function':{'name':call['name'],'arguments':call['arguments']}}]}}]}


class DataTests(unittest.TestCase):
    setUp = direct_fixture.DirectTests.setUp
    tearDown = direct_fixture.DirectTests.tearDown
    message = direct_fixture.DirectTests.message

    def test_long_drafts_survive_response_data_validation_and_delivery_once(self):
        request='Write five article drafts inline in chat with examples and code snippets.'
        data=copy.deepcopy(DATA)
        data['answer']=''.join(f'## Article {i}\n'+('Example:\n```python\nprint("example")\n```\n'*90) for i in range(1,6))
        data['research_advice']={'recommended_mode':'none','requirement':'unnecessary',
                                 'reason':'Drafting from supplied context.','questions':[]}
        self.assertGreater(len(data['answer']),12000)
        self.assertLess(len(data['answer']),advice.MAX_DIRECT_ANSWER_CHARACTERS)
        self.message(request)
        with patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),response('gemini',data)]
            worker=chat.Worker(self.state);worker.tick();worker.tick()
            self.assertEqual(client.return_value.request.call_count,2)
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertGreater(len(row['response']),16000)
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(json.loads(row['response']),{**chat.response_json(json.dumps(data)),'request_contract':intake.ANSWER})
        self.assertEqual(row['answer'],data['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)

    def test_unicode_escaping_does_not_consume_the_decoded_answer_budget(self):
        data={**DATA,'answer':'\u4f60'*advice.MAX_DIRECT_ANSWER_CHARACTERS}
        raw=json.dumps(data,ensure_ascii=True)
        self.assertGreater(len(raw),16000)
        self.assertEqual(advice.validate(raw,'Write an article.'),raw)
        self.assertEqual(chat.interpret(raw,{})['answer'],data['answer'])

    def test_oversized_responses_answers_and_action_data_still_fail(self):
        with self.assertRaises(chat.ResponseLengthError):
            chat.response_json(' '*(advice.MAX_RESPONSE_CHARACTERS+1))
        with self.assertRaises(chat.ResponseLengthError):
            chat.interpret(json.dumps({**DATA,'answer':'x'*(advice.MAX_DIRECT_ANSWER_CHARACTERS+1)}),{})
        with self.assertRaises(ValueError):
            chat.response_json(json.dumps({**DATA,'action_json':'x'*(advice.MAX_ACTION_DATA_CHARACTERS+1)}))
        action={'kind':'run','workflow':'spellshape','items':1,'direction':'Run one step'}
        with self.assertRaises(chat.ResponseLengthError):
            chat.interpret(json.dumps({**DATA,'answer':'x'*(advice.MAX_ACTION_ANSWER_CHARACTERS+1),
                                       'action_json':json.dumps(action)}),{})

    def test_explicit_writing_schema_and_parser_share_the_answer_budget(self):
        definition=advice.response_definition('Write five complete articles.',[])
        self.assertEqual(definition['parameters']['properties']['answer']['maxLength'],
                         advice.MAX_DIRECT_ANSWER_CHARACTERS)
        self.assertEqual(definition['parameters']['properties']['action_json']['maxLength'],
                         advice.MAX_ACTION_DATA_CHARACTERS)

    def test_all_transports_freeze_intake_then_finish_without_a_post_response_turn(self):
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider), patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'} if provider=='gemini' else None), patch.object(chat.api,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini if provider=='gemini' else chat.api,'Client') as client, patch.object(files,'execute') as execute:
                client.return_value.request.side_effect=[intake.response(provider),response(provider,DATA)]
                raw=chat.generate({'id':provider,'provider':provider,'model':'fixture'}, {'user_message':direct_fixture.REQUEST,'snapshot':{}})
                self.assertEqual(json.loads(raw),{**chat.response_json(json.dumps(DATA)),'request_contract':intake.ANSWER})
                self.assertIsNone(chat.interpret(raw,{})['action'])
                self.assertEqual(client.return_value.request.call_count,2);execute.assert_not_called()
                sent=client.return_value.request.call_args.args[1]
                if provider=='gemini':schema=sent['tools'][0]['functionDeclarations'][-1]['parametersJsonSchema']
                elif provider=='openai':schema=sent['tools'][-1]['parameters']
                else:schema=sent['tools'][-1]['function']['parameters']
                self.assertEqual(schema['properties']['research_advice']['properties']['recommended_mode']['enum'],['none','sources'])
                self.assertFalse(schema['additionalProperties'])
                path=Path(self.temp.name)/'orchestrator-reads'/(hashlib.sha256(provider.encode()).hexdigest()+'.json')
                journal=json.loads(path.read_text())
                self.assertEqual(json.loads(journal[-1]['response_data']),DATA)
                self.assertEqual(journal[0]['intake'],intake.ANSWER)
                self.assertEqual(journal[-1]['response_contract']['owner'],'relay runtime')
                self.assertNotIn('reads',journal[0])

    def test_optional_in_wrong_field_keeps_direct_data_and_records_no_invented_mode(self):
        self.message(direct_fixture.REQUEST)
        data=copy.deepcopy(DATA);data['research_advice']['recommended_mode']='optional'
        data['answer']='Ideas for a controller. '+('More ideas. '*200)
        with patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),response('gemini',data)]
            worker=chat.Worker(self.state);worker.tick();worker.tick()
            self.assertEqual(client.return_value.request.call_count,2)
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(json.loads(row['response']),{**chat.response_json(json.dumps(data)),'request_contract':intake.ANSWER})
        self.assertTrue(row['answer'].startswith(data['answer']))
        self.assertNotIn(data['research_advice']['reason'],row['answer'])
        self.assertIn('Sources: not checked yet',row['answer'])
        self.assertNotIn('Recommended approach:',row['answer'])
        self.assertNotIn('valid, scoped recommendation',row['answer'])
        receipt=self.state.get('orchestrator-response-notes:1')
        self.assertEqual(receipt['response'],row['response']);self.assertEqual(receipt['notes'],['Invalid research recommendation.'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)
        self.assertEqual(self.telegram.sent,[])

    def test_action_data_is_still_strict_without_contract_repair_or_dispatch(self):
        self.message('Prepare a bounded plan for a controller UI.')
        data=copy.deepcopy(DATA);data['action_json']=json.dumps({'kind':'plan_production'})
        data['research_advice']['recommended_mode']='optional'
        with patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),response('gemini',data)]
            worker=chat.Worker(self.state);worker.tick();worker.tick()
            self.assertEqual(client.return_value.request.call_count,2)
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['status'],'failed');self.assertEqual(json.loads(row['response']),{**chat.response_json(json.dumps(data)),'request_contract':intake.ANSWER})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)

    def test_response_data_cannot_supply_contracts_or_ambiguous_actions(self):
        for bad in ({**DATA,'contract':{'allowed_tools':['arbitrary']}}, {**DATA,'action':{'kind':'run'}},
                    {**DATA,'action_json':'{"kind":"plan","kind":"run"}'}, {**DATA,'action_json':'["run"]'}):
            with self.subTest(data=bad), self.assertRaises(ValueError):
                chat.response_json(json.dumps(bad))
        action={'kind':'plan_production','template':'custom','project':None,'reference_pack_id':None,'research_ids':[],'planning_only':True}
        self.assertEqual(chat.response_json(json.dumps({**DATA,'action_json':json.dumps(action)}))['action'],action)


class BudgetTests(unittest.TestCase):
    setUp = file_fixture.Tests.setUp
    tearDown = file_fixture.Tests.tearDown
    request = file_fixture.Tests.request
    args = file_fixture.Tests.args

    def test_final_response_after_exhausted_reads_uses_the_runtime_schema(self):
        definition=advice.response_definition(direct_fixture.REQUEST,[])
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                requests=[]
                first=file_fixture.Tests.response(self,provider,'README.md')
                responses=iter([first,response(provider,DATA)])
                class Client:
                    def request(inner,endpoint,request):
                        requests.append(copy.deepcopy(request));return next(responses)
                with patch.object(files,'MAX_ROUNDS',1):
                    raw=files.run(provider,Client(),'fixture',self.request(provider),[str(self.root)],self.receipt,response_definition=definition)
                self.assertEqual(json.loads(raw),DATA);self.assertEqual(len(requests),2)
                last=requests[-1]
                if provider=='gemini':names=[d['name'] for d in last['tools'][0]['functionDeclarations']]
                elif provider=='openai':names=[d['name'] for d in last['tools']]
                else:names=[d['function']['name'] for d in last['tools']]
                self.assertEqual(names,['relay_respond'])
                journal=json.loads(self.receipt.read_text())
                self.assertEqual(sum(len(turn.get('reads',[])) for turn in journal),1)
                self.assertEqual(journal[-1]['response_data'],raw)

    def test_mixed_read_and_response_stops_without_evidence_execution(self):
        client=unittest.mock.Mock();client.request.return_value=response('gemini',DATA,{'name':'file_read','args':self.args('README.md')})
        with patch.object(files,'execute') as execute, self.assertRaisesRegex(ValueError,'separately from evidence reads'):
            files.run('gemini',client,'fixture',self.request('gemini'),[str(self.root)],self.receipt,response_definition=advice.response_definition(direct_fixture.REQUEST,[]))
        client.request.assert_called_once();execute.assert_not_called()
