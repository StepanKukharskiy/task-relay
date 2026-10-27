import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import intake_fixtures as intake
from task_relay import orchestrator_files as files
from task_relay import orchestrator_chat as chat


class Tests(unittest.TestCase):
    def test_truncated_provider_actions_are_saved_without_tool_execution_or_retry(self):
        for provider in ('gemini', 'openai', 'qwen', 'deepseek', 'openrouter'):
            with self.subTest(provider=provider):
                response = self.response(provider, 'README.md')
                if provider == 'gemini':
                    response['candidates'][0]['finishReason'] = 'MAX_TOKENS'
                    response['usageMetadata'] = {'thoughtsTokenCount': 3788, 'candidatesTokenCount': 304}
                elif provider == 'openai':
                    response.update(status='incomplete', incomplete_details={'reason':'max_output_tokens'})
                else:
                    response['choices'][0]['finish_reason'] = 'length'
                with patch.object(files, 'execute') as execute:
                    client = unittest.mock.Mock()
                    client.request.return_value = response
                    with self.assertRaises(files.ProviderResponseError) as failure:
                        files.run(provider, client, 'fixture', self.request(provider), [str(self.root)], self.receipt)
                    self.assertTrue(failure.exception.output_limit)
                    client.request.assert_called_once()
                    execute.assert_not_called()
                journal = json.loads(self.receipt.read_text())
                self.assertEqual(journal[0]['response'], response)
                self.assertNotIn('reads', journal[0])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'docs').mkdir()
        (self.root / 'README.md').write_text('Current plan: docs/delivery.md')
        (self.root / 'docs/delivery.md').write_text('Next: O03. Observer deferred.')
        self.receipt = self.root / 'receipt.json'

    def tearDown(self):
        self.temp.cleanup()

    def args(self, path):
        return {'project':str(self.root),'path':path,'offset':0,'limit':1000}

    def response(self, provider, path=None):
        answer = json.dumps({'answer':'O03, per docs/delivery.md:1.','action':None,'next_options':[],'research_advice':{'recommended_mode':'none','requirement':'unnecessary','reason':'Use the current supplied project records.','questions':[]}})
        if provider == 'gemini':
            parts = ([{'functionCall':{'name':'file_read','args':self.args(path)},'thoughtSignature':'keep-me'}]
                     if path else [{'text':answer}])
            return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':parts}}]}
        if provider == 'openai':
            output = ([{'type':'function_call','call_id':'c1','name':'file_read','arguments':json.dumps(self.args(path))}]
                      if path else [{'type':'message','content':[{'type':'output_text','text':answer}]}])
            return {'status':'completed','output':output}
        message = ({'role':'assistant','content':None,'reasoning_content':'keep-me', 'tool_calls':[
            {'id':'c1','type':'function','function':{'name':'file_read','arguments':json.dumps(self.args(path))}}]}
                   if path else {'role':'assistant','content':answer})
        return {'choices':[{'finish_reason':'tool_calls' if path else 'stop','message':message}]}

    def request(self, provider):
        if provider == 'gemini':
            return {'systemInstruction':{'parts':[{'text':'Return JSON'}]},'contents':[],
                    'generationConfig':{'responseMimeType':'application/json'}}
        if provider == 'openai':
            return {'instructions':'Return JSON','input':[]}
        return {'messages':[{'role':'system','content':'Return JSON'}]}

    def test_explicit_research_choice_compiles_advice_without_replay_or_action_change(self):
        from task_relay import orchestrator_advice as advice
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                response=self.response(provider);client=unittest.mock.Mock()
                client.request.return_value=response
                raw=files.run(provider,client,'fixture',self.request(provider),[],self.receipt,research_mode='sources')
                client.request.assert_called_once()
                value=json.loads(raw);self.assertIsNone(value['action'])
                self.assertEqual(value['research_advice']['recommended_mode'],'sources')
                self.assertEqual(value['research_advice']['requirement'],'required')
                journal=json.loads(self.receipt.read_text())
                self.assertEqual(journal[0]['response'],response)
                receipt=journal[0]['research_choice_compilation']
                original=json.loads(receipt['original_response'])
                self.assertEqual(value['answer'],original['answer'])
                self.assertEqual(value['action'],original['action'])
                self.assertFalse(receipt['acceptance'])
                # Policy binding cannot turn absent retrieval into verified facts.
                value.update(answer_basis='source_findings',claim_sources=[])
                with self.assertRaisesRegex(advice.AdviceError,'recorded page reads'):
                    advice.validate(json.dumps(value),'Research current facts',evidence={'sources':[]},research_mode='sources')

    def test_all_provider_formats_follow_local_reference_with_audit(self):
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                requests = []
                responses = iter([self.response(provider,'README.md'),self.response(provider,'docs/delivery.md'),self.response(provider)])
                class Client:
                    def request(inner, endpoint, request):
                        requests.append(copy.deepcopy(request))
                        return next(responses)
                result = files.run(provider,Client(),'test',self.request(provider),[str(self.root)],self.receipt)
                self.assertIsNone(json.loads(result)['action'])
                self.assertIn('Observer deferred',json.dumps(requests[-1]))
                journal = json.loads(self.receipt.read_text())
                self.assertEqual(len(journal),3)
                self.assertTrue(journal[1]['reads'][0]['result']['ok'])
                if provider == 'gemini':
                    self.assertIn('keep-me', json.dumps(requests[-1]))
                    self.assertNotIn('responseMimeType',requests[0]['generationConfig'])

    def test_scope_traversal_and_private_files_rejected(self):
        (self.root / 'private').mkdir(); (self.root / 'private/key.txt').write_text('do not read')
        for project, path in ((str(self.root.parent),'README.md'),(str(self.root),'../outside'),(str(self.root),'private/key.txt')):
            args = self.args(path); args['project'] = project
            result = files.execute([str(self.root)],{'name':'file_read','arguments':json.dumps(args)})
            self.assertFalse(result['ok'])
            self.assertNotIn('do not read',json.dumps(result))

    def test_only_complete_json_fence_is_unwrapped_and_schema_stays_strict(self):
        raw = '{"answer":"O03", "action":null}'
        self.assertEqual(chat.interpret(files.final_text('```json\n'+raw+'\n```'),{})['answer'],'O03')
        for bad in ('Extra prose\n```json\n'+raw+'\n```',
                    '```json\n{"answer":"a","answer":"b","action":null}\n```'):
            with self.assertRaises(ValueError):
                chat.interpret(files.final_text(bad),{})

    def test_exhaustion_disables_tools_then_rejects_further_calls(self):
        requests=[]
        response=self.response('gemini','README.md')
        class Client:
            def request(inner,endpoint,request):
                requests.append(copy.deepcopy(request));return response
        with patch.object(files,'MAX_ROUNDS',1):
            with self.assertRaisesRegex(ValueError,'budget exhausted'):
                files.run('gemini',Client(),'test',self.request('gemini'),[str(self.root)],self.receipt)
        self.assertEqual(requests[-1]['tools'],[])
        self.assertNotIn('toolConfig',requests[-1])
        self.assertEqual(requests[-1]['generationConfig']['responseMimeType'],'application/json')
        self.assertEqual(sum(len(r.get('reads',[])) for r in json.loads(self.receipt.read_text())),1)

    def test_budget_final_turn_preserves_evidence_without_advertising_more_reads(self):
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                requests=[]
                responses=iter([self.response(provider,'docs/delivery.md'),self.response(provider)])
                class Client:
                    def request(inner,endpoint,request):
                        requests.append(copy.deepcopy(request));return next(responses)
                with patch.object(files,'MAX_ROUNDS',1):
                    raw=files.run(provider,Client(),'test',self.request(provider),[str(self.root)],self.receipt)
                self.assertEqual(json.loads(raw)['answer'],'O03, per docs/delivery.md:1.')
                self.assertIn('Observer deferred',json.dumps(requests[-1]))
                self.assertEqual(requests[-1]['tools'],[])
                self.assertEqual(len(requests),2)
                journal=json.loads(self.receipt.read_text())
                self.assertEqual(sum(len(r.get('reads',[])) for r in journal),1)

    def test_actual_chat_generate_offers_tools_and_keeps_final_action_contract(self):
        payload={'snapshot':{'project_roadmaps':{'available_projects':[str(self.root)]}},'user_message':'Read the current delivery plan'}
        with patch.object(chat.gemini,'read_config',return_value={'api_key':'fake'}), patch.object(chat.gemini,'DATA',self.root), patch.object(chat.gemini,'Client') as client:
            responses = iter([intake.response('gemini'),self.response('gemini','docs/delivery.md'),self.response('gemini')])
            def bounded_response(endpoint, request):
                if request['generationConfig']['maxOutputTokens'] <= 4096:
                    return {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[]}}]}
                return next(responses)
            client.return_value.request.side_effect = bounded_response
            raw=chat.generate({'id':77,'provider':'gemini','model':'test'},payload)
            self.assertIsNone(chat.interpret(raw, {})['action'])
            self.assertIn('file_read',json.dumps(client.return_value.request.call_args_list[1]))
            self.assertEqual(len(list((self.root/'orchestrator-reads').glob('*.json'))),1)

    def test_source_correction_keeps_separate_provider_and_read_receipts(self):
        payload={'snapshot':{},'user_message':'Continue the installation work.'}
        job={'id':77,'provider':'gemini','model':'test'}
        with patch.object(chat.gemini,'read_config',return_value={'api_key':'fake'}), patch.object(chat.gemini,'DATA',self.root), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),self.response('gemini'),self.response('gemini')]
            chat.generate(job,payload)
            original=next((self.root/'orchestrator-reads').glob('*.json'))
            saved=original.read_bytes()
            correction={'missing_fields':['artifact_ids'],'previous_action':{'kind':'route_task','task_id':'t0'}}
            chat.generate(job,{**payload,'routing_source_correction':correction,'request_contract':intake.ANSWER})
            self.assertEqual(original.read_bytes(),saved)
            self.assertEqual(len(list((self.root/'orchestrator-reads').glob('*.json'))),2)
            request=client.return_value.request.call_args.args[1]
            data=json.loads(request['contents'][0]['parts'][0]['text'])
            self.assertEqual(data['routing_source_correction'],correction)
            self.assertEqual(data['user_message'],payload['user_message'])

    def test_frozen_output_binding_retains_raw_reply_and_needs_no_provider_retry(self):
        contract=intake.work([intake.outcome('deck',format='.pptx')])
        action=dict(kind='plan_pipeline',stage_details=[dict(id='deliver',outputs={'deck':dict(description='Paraphrased outcome',format='pptx')})])
        exact=json.dumps(dict(answer='Prepare the requested workflow.',action=action))
        response={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':exact}]}}]}
        client=unittest.mock.Mock();client.request.return_value=response
        value=json.loads(files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,frozen_intake=contract))
        client.request.assert_called_once()
        self.assertEqual(value['action']['stage_details'][0]['outputs']['deck']['description'],contract['outcomes'][0]['description'])
        journal=json.loads(self.receipt.read_text())
        self.assertEqual(journal[0]['response'],response)
        self.assertEqual(journal[0]['frozen_outcome_compilation']['previous_action'],action)
        self.assertEqual(journal[0]['frozen_outcome_compilation']['compiled_action'],value['action'])

    def test_confirmed_workflow_errors_return_to_same_loop_with_frozen_scope(self):
        contract=intake.work([intake.outcome('deck',format='.pptx')]);requests=[]
        def reply(fmt):
            value=dict(answer='Unexecuted proposal',action=dict(kind='plan_pipeline',stage_details=[dict(id='deliver',outputs={'alias':dict(format=fmt,description='A presentation')})]))
            return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':json.dumps(value)}]}}]}
        replies=iter([reply('pdf'),reply('markdown'),reply('pptx')])
        client=unittest.mock.Mock()
        def send(endpoint,request):requests.append(copy.deepcopy(request));return next(replies)
        client.request.side_effect=send
        value=json.loads(files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,frozen_intake=contract))
        self.assertIn('deck',value['action']['stage_details'][0]['outputs'])
        self.assertEqual(len(requests),3)
        journal=json.loads(self.receipt.read_text())
        self.assertEqual([r['routing_correction']['number'] for r in journal if 'routing_correction' in r],[1,2])
        self.assertTrue(all(r['routing_correction']['no_dispatch'] for r in journal if 'routing_correction' in r))
        self.assertEqual(journal[0]['routing_correction']['frozen_request_contract'],contract)
        client.request.side_effect=None;client.request.return_value=reply('pdf');client.reset_mock()
        with self.assertRaisesRegex(ValueError,'workflow stages'):
            files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,frozen_intake=contract)
        self.assertEqual(client.request.call_count,3)

    def test_full_captured_graph_preflight_repairs_missing_producer_before_dispatch(self):
        from task_relay.orchestrator_context import Evidence
        from orchestrator.execution import REGISTRY
        import hashlib
        contract=intake.work([intake.outcome('deck',format='.pptx')])
        catalog=[dict(copy.deepcopy(REGISTRY[c]),id=c,available=True) for c in ('pptx.create','pptx.render')]
        context=Evidence(dict(snapshot=dict(capabilities=dict(graph_operations=catalog)),exact_attachment='Unchanged captured identity'))
        action=dict(kind='plan_pipeline',title='Compatible fixture',planning_only=False,stage_details=[
            dict(id='prepare',route='production',gate='none',instruction='Prepare a brief',capabilities=[],uses=[],outputs={'brief':dict(format='markdown',description='Brief')}),
            dict(id='finish',route='production',gate='none',instruction='Create the presentation',capabilities=[],uses=[],outputs={'alias':dict(format='pptx',description='Presentation')})])
        def response(value):return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':json.dumps(dict(answer='Proposed work',action=value))}]}}]}
        corrected=copy.deepcopy(action);corrected['stage_details'][-1]['capabilities']=['pptx.create']
        client=unittest.mock.Mock();client.request.side_effect=[response(action),response(corrected)]
        result=json.loads(files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,context=context,frozen_intake=contract))
        self.assertEqual(client.request.call_count,2);self.assertIn('deck',result['action']['stage_details'][-1]['outputs'])
        journal=json.loads(self.receipt.read_text());capture=journal[0]['captured_context'];raw=Path(capture['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),capture['sha256']);self.assertEqual(json.loads(raw),context.payload)
        self.assertIn('No selected native/document capability',journal[0]['routing_correction']['error'])
        changed=Evidence({**context.payload,'exact_attachment':'Different identity'})
        client.reset_mock()
        with self.assertRaisesRegex(ValueError,'context changed'):
            files.run('gemini',client,'fixture',self.request('gemini'),[],self.receipt,context=changed,frozen_intake=contract)
        client.request.assert_not_called()

    def late_proposal_fixture(self, provider):
        from task_relay.orchestrator_context import Evidence
        from task_relay import orchestrator_advice
        contract=intake.work([intake.outcome('report')])
        action=dict(kind='plan_pipeline',title='Text workflow',planning_only=False,stage_details=[
            dict(id='prepare',route='production',gate='none',instruction='Prepare notes',capabilities=[],uses=[],
                 outputs={'notes':dict(format='markdown',description='Notes')}),
            dict(id='finish',route='production',gate='none',instruction='Write report',capabilities=[],
                 uses=[dict(stage='prepare',output='notes',consumer='context')],
                 outputs={'report':dict(format='markdown',description='Report')})])
        def reply(value):
            data=dict(answer='Proposed work',action_json=json.dumps(value),work_status='respond',
                      answer_basis='proposed_work',next_options=[],claim_sources=[],
                      research_advice=dict(recommended_mode='none',requirement='unnecessary',reason='Use supplied material',questions=[]))
            if provider=='gemini':return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[
                {'functionCall':{'name':'relay_respond','args':data},'thoughtSignature':'retained'}]}}]}
            if provider=='openai':return {'status':'completed','output':[
                {'type':'function_call','call_id':'finish','name':'relay_respond','arguments':json.dumps(data)}]}
            return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                'tool_calls':[{'id':'finish','type':'function','function':{'name':'relay_respond','arguments':json.dumps(data)}}]}}]}
        context=Evidence(dict(snapshot=dict(capabilities=dict(graph_operations=[]))))
        options=dict(context=context,frozen_intake=contract,
                     response_definition=orchestrator_advice.response_definition('Write a report',[]))
        reads=[self.response(provider,'README.md') for _ in range(files.MAX_ROUNDS)]
        return action,reply,options,reads

    def test_last_discovery_round_still_corrects_schema_for_every_provider(self):
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                action,reply,options,reads=self.late_proposal_fixture(provider)
                bad=reply(dict(action,capabilities=[]));good=reply(action);requests=[]
                responses=iter(reads+[bad,good]);client=unittest.mock.Mock()
                def send(endpoint,request):
                    requests.append(copy.deepcopy(request));return next(responses)
                client.request.side_effect=send
                result=json.loads(files.run(provider,client,'fixture',self.request(provider),[str(self.root)],self.receipt,**options))
                self.assertNotIn('capabilities',result['action'])
                self.assertEqual(result['request_contract'],options['frozen_intake'])
                journal=json.loads(self.receipt.read_text())
                self.assertEqual(len(journal),files.MAX_ROUNDS+2)
                self.assertEqual(journal[-2]['response'],bad)
                self.assertIn('unsupported field',journal[-2]['routing_correction']['error'])
                self.assertEqual(sum(len(r.get('reads',[])) for r in journal),files.MAX_ROUNDS)
                tools=requests[-1]['tools']
                names=([x['name'] for x in tools[0]['functionDeclarations']] if provider=='gemini'
                       else [x['name'] if provider=='openai' else x['function']['name'] for x in tools])
                self.assertEqual(names,['relay_respond'])

    def test_late_invalid_proposals_exhaust_only_original_correction_allowance(self):
        action,reply,options,reads=self.late_proposal_fixture('gemini')
        bad=reply(dict(action,capabilities=[]));client=unittest.mock.Mock()
        client.request.side_effect=reads+[bad]*3
        with self.assertRaisesRegex(ValueError,'unsupported field'):
            files.run('gemini',client,'fixture',self.request('gemini'),[str(self.root)],self.receipt,**options)
        journal=json.loads(self.receipt.read_text())
        self.assertEqual(client.request.call_count,files.MAX_ROUNDS+3)
        self.assertEqual([r['routing_correction']['number'] for r in journal if 'routing_correction' in r],[1,2])
        self.assertEqual(journal[-1]['response'],bad)

    def test_correction_cannot_reopen_reads_or_retry_uncertain_submission(self):
        for late in (False,True):
            for failure in ('read','uncertain'):
                with self.subTest(late=late,failure=failure):
                    action,reply,options,reads=self.late_proposal_fixture('gemini')
                    bad=reply(dict(action,capabilities=[]))
                    next_reply=self.response('gemini','README.md')
                    if failure=='uncertain':next_reply=TimeoutError('Unknown provider outcome')
                    if failure=='truncated':next_reply=reply(action);next_reply['candidates'][0]['finishReason']='MAX_TOKENS'
                    client=unittest.mock.Mock();client.request.side_effect=(reads if late else [])+[bad,next_reply]
                    with self.assertRaises((files.ReadLimitError,files.ProviderResponseError,TimeoutError)):
                        files.run('gemini',client,'fixture',self.request('gemini'),[str(self.root)],self.receipt,**options)
                    journal=json.loads(self.receipt.read_text())
                    self.assertEqual(len(journal),2+(files.MAX_ROUNDS if late else 0))
                    self.assertNotIn('reads',journal[-1])
                    self.assertEqual('response' in journal[-1],failure!='uncertain')


if __name__ == '__main__':
    unittest.main()
