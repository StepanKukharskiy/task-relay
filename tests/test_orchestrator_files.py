import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
        answer = json.dumps({'answer':'O03, per docs/delivery.md:1.','action':None})
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
            responses = iter([self.response('gemini','docs/delivery.md'),self.response('gemini')])
            def bounded_response(endpoint, request):
                if request['generationConfig']['maxOutputTokens'] <= 4096:
                    return {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[]}}]}
                return next(responses)
            client.return_value.request.side_effect = bounded_response
            raw=chat.generate({'id':77,'provider':'gemini','model':'test'},payload)
            self.assertIsNone(chat.interpret(raw, {})['action'])
            self.assertIn('file_read',json.dumps(client.return_value.request.call_args_list[0]))
            self.assertEqual(len(list((self.root/'orchestrator-reads').glob('*.json'))),1)

    def test_source_correction_keeps_separate_provider_and_read_receipts(self):
        payload={'snapshot':{},'user_message':'Continue the installation work.'}
        job={'id':77,'provider':'gemini','model':'test'}
        with patch.object(chat.gemini,'read_config',return_value={'api_key':'fake'}), patch.object(chat.gemini,'DATA',self.root), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.return_value=self.response('gemini')
            chat.generate(job,payload)
            original=next((self.root/'orchestrator-reads').glob('*.json'))
            saved=original.read_bytes()
            correction={'missing_fields':['artifact_ids'],'previous_action':{'kind':'route_task','task_id':'t0'}}
            chat.generate(job,{**payload,'routing_source_correction':correction})
            self.assertEqual(original.read_bytes(),saved)
            self.assertEqual(len(list((self.root/'orchestrator-reads').glob('*.json'))),2)
            request=client.return_value.request.call_args.args[1]
            data=json.loads(request['contents'][0]['parts'][0]['text'])
            self.assertEqual(data['routing_source_correction'],correction)
            self.assertEqual(data['user_message'],payload['user_message'])


if __name__ == '__main__':
    unittest.main()
