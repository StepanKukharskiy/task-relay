import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay import orchestrator_context as context
from task_relay import orchestrator_files as files
from task_relay import orchestrator_chat as chat
from tests import test_orchestrator_files as file_fixtures


class ContextTests(unittest.TestCase):
    def test_short_choice_keeps_latest_exchange_with_original_history_pointer(self):
        payload = self.payload()
        payload['user_message'] = 'concept 1'
        payload['history'] = [{'id': i, 'prompt': 'Earlier request', 'answer': 'Old answer ' * 100}
                              for i in range(50)]
        latest = {'id': 51, 'prompt': 'Plan research, a model, image and deck.',
                  'answer': 'Concept 1: Terraces. Concept 2: Courtyards. Choose one.'}
        payload['history'].append(latest)
        original = copy.deepcopy(payload)
        view = context.overview(payload)
        selected = view['recent_conversation'][-1]
        self.assertEqual(selected['exchange'], latest)
        full = context.Evidence(payload).execute({'arguments': json.dumps({
            'pointer': selected['history_pointer'], 'offset': 0, 'limit': context.MAX_PAGE})})
        self.assertEqual(json.loads(full['text']), latest)
        self.assertEqual(payload, original)
        self.assertLessEqual(len(context.encoded(view).encode()), context.MAX_OVERVIEW)

    def test_named_task_survives_large_overview_without_changing_source_pointers(self):
        payload = self.payload()
        payload['user_message'] = 'Use the existing Codex task "Review and continue roadmap" for Perplexity.'
        payload['snapshot']['codex_tasks'][0].update(title='Review roadmap next steps', status='running')
        payload['snapshot']['codex_tasks'][199].update(title='Review and continue roadmap', status='idle', routing_blocker=None)
        original = copy.deepcopy(payload)
        small = context.overview(payload)
        match = small['mentioned_codex_tasks']['matches'][0]
        self.assertEqual(small['mentioned_codex_tasks']['match_count'], 1)
        self.assertEqual((match['id'], match['title'], match['status']), ('199', 'Review and continue roadmap', 'idle'))
        evidence = context.Evidence(payload)
        full = evidence.execute({'arguments': json.dumps({'pointer':match['catalog_pointer'], 'offset':0, 'limit':context.MAX_PAGE})})
        self.assertEqual(json.loads(full['text'])['id'], '199')
        self.assertEqual(payload, original)
        self.assertLessEqual(len(context.encoded(small).encode()), context.MAX_OVERVIEW)

    def test_duplicate_titles_preserve_ambiguity_and_mentions_are_not_actions(self):
        payload = {'user_message':'Do not use "Browser pilot". What is its status?',
                   'snapshot':{'codex_tasks':[{'id':str(i), 'title':'Browser pilot', 'status':'idle'} for i in range(8)]}}
        small = context.overview(payload)
        self.assertEqual(small['mentioned_codex_tasks']['match_count'], 8)
        self.assertFalse(small['mentioned_codex_tasks']['complete'])
        self.assertEqual(len(small['mentioned_codex_tasks']['matches']), 5)
        self.assertNotIn('action', small)
        payload['user_message'] = 'Browser pilots are useful'
        self.assertEqual(context.task_mentions(payload)['match_count'], 0)

    def payload(self):
        return {'user_message': '  Use my exact direction.\nKeep the acceptance criteria.  ',
                'snapshot': {'focus': 'chosen', 'production_runs': [
                    {'name': 'chosen', 'revision': 456, 'status': 'blocked',
                     'criteria': ('Exact criterion 🚀\n' * 12000) + 'FINAL REQUIRED CONDITION',
                     'files': [{'id': str(i), 'text': 'Reference\n' * 200} for i in range(150)]}],
                    'codex_tasks': [{'id': str(i), 'title': 'Task ' + str(i), 'summary': 'Historical evidence ' * 200} for i in range(200)]}}

    def test_overview_is_bounded_preserves_prompt_and_discloses_omissions(self):
        payload = self.payload()
        original = copy.deepcopy(payload)
        small = context.overview(payload)
        self.assertLessEqual(len(context.encoded(small).encode()), context.MAX_OVERVIEW)
        self.assertEqual(small['user_message'], payload['user_message'])
        self.assertFalse(small['context_overview']['complete'])
        self.assertIn('/snapshot/production_runs/0/criteria', [v['pointer'] for v in small['context_overview']['omissions']])
        self.assertEqual(small['snapshot']['production_runs'][0]['revision'], 456)
        self.assertEqual(payload, original)

    def test_pages_reconstruct_exact_frozen_evidence_and_reject_bad_pointers(self):
        payload = self.payload()
        evidence = context.Evidence(payload)
        expected = context.encoded(payload['snapshot']['production_runs'][0]['criteria'])
        payload['snapshot']['production_runs'][0]['criteria'] = 'Modified after capture'
        offset, pages, hashes = 0, [], set()
        while offset is not None:
            result = evidence.execute({'arguments': json.dumps({'pointer': '/snapshot/production_runs/0/criteria', 'offset': offset, 'limit': context.MAX_PAGE})})
            self.assertTrue(result['ok'])
            pages.append(result['text']); hashes.add(result['sha256']); offset = result['next_offset']
        self.assertEqual(''.join(pages), expected)
        self.assertEqual(len(hashes), 1)
        for at, start, limit in [('/snapshot/../../secrets', 0, 100), ('bad', 0, 100), ('', -1, 100), ('', 0, 20000), ('', True, 100)]:
            result = evidence.execute({'arguments': json.dumps({'pointer': at, 'offset': start, 'limit': limit})})
            self.assertFalse(result['ok'])

    def test_context_tools_work_without_project_access_for_every_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = file_fixtures.Tests()
            fixture.root = Path(folder)
            for provider in ('gemini', 'openai', 'qwen', 'deepseek', 'openrouter'):
                with self.subTest(provider=provider):
                    payload = {'snapshot': {'criteria': 'The final criterion must remain unchanged.'}}
                    args = {'pointer': '/snapshot/criteria', 'offset': 0, 'limit': 1000}
                    first = fixture.response(provider, 'README.md')
                    if provider == 'gemini':
                        call = first['candidates'][0]['content']['parts'][0]['functionCall']
                        call.update(name='context_read', args=args)
                    elif provider == 'openai':
                        first['output'][0].update(name='context_read', arguments=json.dumps(args))
                    else:
                        first['choices'][0]['message']['tool_calls'][0]['function'].update(name='context_read', arguments=json.dumps(args))
                    responses = iter([first, fixture.response(provider)])
                    requests = []
                    class Client:
                        def request(self, endpoint, request):
                            requests.append(copy.deepcopy(request))
                            return next(responses)
                    receipt = Path(folder) / (provider + '.json')
                    answer = files.run(provider, Client(), 'fixture', fixture.request(provider), [], receipt,
                                       context=context.Evidence(payload))
                    self.assertIsNone(json.loads(answer)['action'])
                    self.assertIn('final criterion', json.dumps(requests[-1]))
                    recorded = json.loads(receipt.read_text())
                    self.assertEqual(recorded[0]['reads'][0]['result']['text'], json.dumps(payload['snapshot']['criteria']))

    def test_snapshot_count_does_not_block_a_large_workflow_catalog(self):
        from tests.test_orchestrator_chat import Tests as ChatFixtures
        fixture = ChatFixtures()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with fixture.state.db:
            template = fixture.state.db.execute('SELECT * FROM workflows LIMIT 1').fetchone()
            for i in range(35):
                values = dict(template)
                values['name'] = 'extra-' + str(i)
                data = json.loads(values['data']); data['name'] = values['name']
                data['direction'] = 'Past direction ' * 1500
                values['data'] = json.dumps(data)
                fixture.state.db.execute('INSERT INTO workflows(' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))
        snap = chat.snapshot(fixture.state, None)
        self.assertGreater(len(snap['workflows']), 30)
        self.assertLessEqual(len(context.encoded(context.overview({'snapshot': snap})).encode()), context.MAX_OVERVIEW)

    def test_large_context_reaches_provider_with_exact_prompt_and_no_dispatch(self):
        from tests.test_orchestrator_chat import Tests as ChatFixtures
        fixture = ChatFixtures()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        original = '  Explain the current blocker.\nDo not start workers.  '
        fixture.message('/orchestrator ' + original)
        snap = chat.snapshot(fixture.state, None)
        snap['background_evidence'] = 'Historical detail\n' * 40000
        requests = []
        class Client:
            def request(self, endpoint, request):
                requests.append(copy.deepcopy(request))
                return {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [
                    {'text': fixture.result()}]}}]}
        with patch.object(chat, 'snapshot', return_value=snap), \
             patch.object(chat.gemini, 'DATA', Path(fixture.temp.name)), \
             patch.object(chat.gemini, 'read_config', return_value={'api_key': 'test-only'}), \
             patch.object(chat.gemini, 'Client', return_value=Client()):
            chat.Worker(fixture.state).tick()
        self.assertEqual(len(requests), 1)
        sent = json.loads(requests[0]['contents'][0]['parts'][0]['text'])
        row = fixture.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(sent['user_message'], row['prompt'])
        self.assertEqual(row['status'], 'answered')
        self.assertLessEqual(len(context.encoded(sent).encode()), context.MAX_OVERVIEW)
        self.assertIn('context_read', json.dumps(requests[0]['tools']))
        self.assertIn('context_overview', json.loads(row['snapshot']))
        self.assertEqual(fixture.state.db.execute('SELECT count(*) FROM workflow_dispatches').fetchone()[0], 0)
        self.assertEqual(fixture.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
