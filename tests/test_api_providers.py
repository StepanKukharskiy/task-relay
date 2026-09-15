import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from task_relay import api_providers as api
from task_relay import api_runner
from task_relay import file_tools
from task_relay import backends
from task_relay import gemini
from task_relay import providers
from task_relay import provider_runner
from task_relay.bridge import Bridge, State
from tests.test_bridge import DesktopFake
from tests.test_providers import Bot

KEY = 'sk-' + 'x' * 40


def response(provider, text='Hello'):
    if provider == 'openai':
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}], 'usage': {'total_tokens': 8}}
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}], 'usage': {'total_tokens': 8}}


def tool_response(provider, name='file_read', arguments=None, call_id='call_1'):
    raw = json.dumps(arguments or {'path': 'README.md', 'offset': 0, 'limit': 1000})
    if provider == 'openai':
        return {'status': 'completed', 'output': [
            {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'encrypted_content': 'opaque'},
            {'type': 'function_call', 'call_id': call_id, 'name': name, 'arguments': raw}], 'usage': {'total_tokens': 5}}
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
            'reasoning_content': 'reasoning retained', 'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'opaque'}],
            'tool_calls': [{'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': raw}}]}}],
            'usage': {'total_tokens': 5}}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch('task_relay.gemini.DATA', self.root / 'private'), patch('task_relay.gemini.WORKSPACES', self.root/'projects')]
        for p in self.patches:
            p.start()
        self.state = State(self.root / 'private/state.sqlite')
        with self.state.db:
            self.state.put('user_id', 123)
            self.state.put('chat_id', 123)
        self.bot = Bot()
        self.bridge = Bridge(self.state, self.bot, {}, DesktopFake)
        self.uid = 1000

    def tearDown(self):
        self.state.db.close()
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def send(self, text, reply='task'):
        self.uid += 1
        message = {'message_id': self.uid, 'chat': {'id': 123, 'type': 'private'}, 'from': {'id': 123}, 'text': text}
        # Provider fixtures continue an explicit task; fresh messages route to orchestration.
        if reply == 'task':
            row = self.state.db.execute('SELECT message_id FROM messages WHERE thread_id=? ORDER BY message_id DESC LIMIT 1',
                                        (self.state.get('selected'),)).fetchone() if not text.startswith('/') else None
            reply = row[0] if row else None
        if reply is not None:
            message['reply_to_message'] = {'message_id': reply}
        self.bridge.process({'update_id': self.uid, 'message': message})

    def click(self, label):
        data = next(b['callback_data'] for row in self.bot.markup['inline_keyboard'] for b in row if b['text'] == label)
        self.uid += 1
        self.bridge.process({'update_id': self.uid, 'callback_query': {'id': str(self.uid), 'from': {'id': 123}, 'message': {'chat': {'id': 123, 'type': 'private'}}, 'data': data}})

    def create(self, provider):
        api.configure(provider, KEY, [api.SPECS[provider]['model']])
        self.send(f'/new {provider} "{self.root}" Test {provider}')
        return self.state.get('selected')

    def queue(self, provider):
        tid = self.create(provider)
        self.send('First prompt')
        job = self.state.db.execute('SELECT * FROM backend_jobs WHERE thread_id=?', (tid,)).fetchone()
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        return tid, job

    def test_all_four_providers_roundtrip_history_and_reply_routing(self):
        for provider in api.SPECS:
            with self.subTest(provider=provider):
                tid, job = self.queue(provider)
                client = Mock()
                client.request.return_value = response(provider, 'Provider answer')
                api_runner.run_job(self.state, job['id'], client=client)
                self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (job['id'],)).fetchone()[0], 'completed')
                self.bridge.flush()
                reply_id = len(self.bot.sent)
                self.send('Follow-up', reply=reply_id)
                run = self.state.db.execute('SELECT r.* FROM api_runs r JOIN backend_jobs j ON j.id=r.job_id WHERE j.thread_id=? ORDER BY j.created_at DESC LIMIT 1', (tid,)).fetchone()
                payload = json.loads(run['request_json'])
                messages = payload['input'] if provider == 'openai' else payload['messages'][1:]
                self.assertEqual([m['content'] for m in messages], ['First prompt', 'Provider answer', 'Follow-up'])
                self.assertNotIn(KEY, run['request_json'])
                self.assertEqual(client.request.call_args.args[0], 'responses' if provider == 'openai' else 'chat/completions')

    def test_all_provider_connection_flows_keep_keys_out_of_tasks_and_database(self):
        for provider, spec in api.SPECS.items():
            with self.subTest(provider=provider):
                self.send('/providers')
                self.click(spec['name'])
                self.click('Connect / update API key')
                self.click('Enter key in this chat')
                self.send(KEY)
                job = self.state.db.execute('SELECT * FROM provider_jobs WHERE provider=?', (provider,)).fetchone()
                with self.state.db:
                    self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?", (job['id'],))
                with patch('task_relay.api_providers.catalog', return_value=[spec['model']]):
                    provider_runner.run_job(self.state, job['id'])
                self.assertEqual(api.read_config(provider)['api_key'], KEY)
                self.assertEqual((gemini.DATA / (provider + '.json')).stat().st_mode & 0o777, 0o600)
                self.assertFalse((gemini.DATA / 'setup-input' / (job['id'] + '.json')).exists())
                self.assertNotIn(KEY, '\n'.join(self.state.db.iterdump()))
                self.assertNotIn(KEY, str(self.bot.sent))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_openrouter_model_slugs_and_pagination(self):
        tid = self.create('openrouter')
        api.configure('openrouter', KEY, ['openrouter/auto'] + [f'org/model-{i}:free' for i in range(30)])
        self.send('/models')
        self.click('Text')
        self.click('More models')
        choices = [b['text'] for row in self.bot.markup['inline_keyboard'] for b in row]
        model = next(m for m in choices if m.startswith('org/'))
        self.click(model)
        self.assertEqual(backends.task(self.state, tid)['model'], model)
        self.send('/model text openai/gpt-4.1-mini')
        self.assertEqual(backends.task(self.state, tid)['model'], 'openai/gpt-4.1-mini')

    def test_qwen_region_and_workspace_endpoint_are_restricted(self):
        self.send('/providers')
        self.click('Qwen')
        self.click('Region / endpoint')
        self.click('Beijing')
        self.assertEqual(api.stored('qwen')['base_url'], api.QWEN_ENDPOINTS['Beijing'])
        url = 'https://workspace123.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1'
        self.send('/endpoint qwen ' + url)
        self.assertEqual(api.stored('qwen')['base_url'], url)
        for bad in ('http://dashscope.aliyuncs.com/compatible-mode/v1', 'https://evil.example/compatible-mode/v1', 'https://api.openai.com/v1', 'https://dashscope.aliyuncs.com.evil.example/compatible-mode/v1'):
            with self.assertRaises(ValueError):
                api.endpoint('qwen', bad)

    def test_openrouter_catalog_checks_private_key_endpoint_first(self):
        client = Mock()
        client.request.side_effect = [{'data': {'label': 'test'}}, {'data': [{'id': 'org/model:free'}]}]
        with patch('task_relay.api_providers.Client', return_value=client):
            self.assertEqual(api.catalog('openrouter', KEY), ['org/model:free'])
        self.assertEqual([c.args[0] for c in client.request.call_args_list], ['key', 'models'])

    def test_post_timeout_is_uncertain_and_never_replayed(self):
        tid, job = self.queue('deepseek')
        client = Mock()
        client.request.side_effect = gemini.ProviderError('timeout', uncertain=True)
        api_runner.run_job(self.state, job['id'], client=client)
        api_runner.run_job(self.state, job['id'], client=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM watched WHERE id=?', (tid,)).fetchone()[0], 'uncertain')
        self.assertFalse(api.resume_job(self.state, job['id'], manual=True))

    def test_saved_response_survives_worker_restart_without_post(self):
        tid, job = self.queue('openai')
        path = Path(self.state.db.execute('SELECT response_path FROM api_runs WHERE job_id=?', (job['id'],)).fetchone()[0])
        gemini.atomic_bytes(path, json.dumps(response('openai', 'Saved answer')).encode())
        with self.state.db:
            self.state.db.execute("UPDATE api_runs SET stage='sending' WHERE job_id=?", (job['id'],))
        backends.BackendWorker(self.state, backend='openai')
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (job['id'],)).fetchone()[0], 'queued')
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        client = Mock()
        api_runner.run_job(self.state, job['id'], client=client)
        client.request.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT answer FROM api_history').fetchone()[0], 'Saved answer')

    def test_disabled_provider_and_request_size_fail_before_queue(self):
        tid = self.create('qwen')
        with patch('task_relay.api_providers.MAX_CONTEXT', 10):
            self.send('Too large')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        config = api.stored('qwen')
        config['enabled'] = False
        gemini.atomic_bytes(gemini.DATA / 'qwen.json', json.dumps(config).encode())
        self.send('Do not submit')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_remote_links_cannot_attach_local_files(self):
        tid, job = self.queue('openrouter')
        secret = self.root / 'private.txt'
        secret.write_text('private fixture')
        client = Mock()
        client.request.return_value = response('openrouter', f'[download](<{secret}>)')
        api_runner.run_job(self.state, job['id'], client=client)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 0)

    def test_partial_output_is_preserved_and_not_marked_complete(self):
        tid, job = self.queue('deepseek')
        data = response('deepseek', 'Partial answer')
        data['choices'][0]['finish_reason'] = 'length'
        client = Mock()
        client.request.return_value = data
        api_runner.run_job(self.state, job['id'], client=client)
        row = self.state.db.execute('SELECT status,result_path FROM backend_jobs').fetchone()
        self.assertEqual(row['status'], 'failed')
        self.assertIn('Partial answer', Path(row['result_path']).read_text())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM api_history').fetchone()[0], 0)

    def test_worker_uses_api_runner_and_cancellation_before_send_is_free(self):
        tid = self.create('openai')
        self.send('Queued')
        process = Mock()
        process.poll.return_value = None
        popen = Mock(return_value=process)
        worker = backends.BackendWorker(self.state, popen, backend='openai')
        worker.tick()
        self.assertEqual(popen.call_args.args[0][1:3], ['-m', 'task_relay.api_runner'])
        jid = self.state.db.execute('SELECT id FROM backend_jobs').fetchone()[0]
        self.send('/stop')
        client = Mock()
        api_runner.run_job(self.state, jid, client=client)
        client.request.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs').fetchone()[0], 'stopped')

    def test_transport_uses_bearer_auth_and_refuses_redirect(self):
        for provider in api.SPECS:
            client = api.Client(provider, KEY)
            client.opener = Mock()
            client.opener.open.return_value = io.BytesIO(b'{"data":[]}')
            client.request('models')
            request = client.opener.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer ' + KEY)
            base = api.SPECS[provider]['base_url']
            if provider == 'qwen':
                base = base.removesuffix('/compatible-mode/v1') + '/api/v1'
            self.assertEqual(request.full_url, base + '/models')
            client.opener.open.side_effect = urllib.error.HTTPError(request.full_url, 302, 'redirect', {'Location': 'https://evil.example'}, None)
            with self.assertRaises(gemini.ProviderError) as caught:
                client.request('models')
            self.assertEqual(caught.exception.status, 302)
            self.assertNotIn(KEY, str(caught.exception))

    def test_qwen_native_model_catalog_parses_and_paginates(self):
        client = Mock()
        client.request.side_effect = [
            {'output': {'total': 101, 'models': [{'model': 'qwen-plus', 'inference_metadata': {'response_modality': ['Text']}}]}},
            {'output': {'total': 101, 'models': [{'model': 'qwen-max'}]}},
        ]
        with patch('task_relay.api_providers.Client', return_value=client):
            self.assertEqual(api.catalog('qwen', KEY), ['qwen-max', 'qwen-plus'])
        self.assertIn('page_no=2', client.request.call_args.args[0])

    def test_file_tool_roundtrip_all_providers_keeps_reasoning_and_only_final_delivery(self):
        (self.root / 'README.md').write_text('Project fixture: blue roofs')
        for provider in api.SPECS:
            with self.subTest(provider=provider):
                tid, job = self.queue(provider)
                client = Mock()
                client.request.side_effect = [tool_response(provider), response(provider, 'The roofs are blue.')]
                api_runner.run_job(self.state, job['id'], client=client)
                self.assertEqual(client.request.call_count, 2)
                payload = client.request.call_args.args[1]
                items = payload['input'] if provider == 'openai' else payload['messages']
                output = items[-1]['output'] if provider == 'openai' else items[-1]['content']
                self.assertEqual(json.loads(output)['text'], 'Project fixture: blue roofs')
                if provider == 'openai':
                    self.assertEqual(items[-3]['encrypted_content'], 'opaque')
                    self.assertEqual(items[-1]['call_id'], 'call_1')
                else:
                    self.assertEqual(items[-2]['reasoning_content'], 'reasoning retained')
                    self.assertEqual(items[-2]['reasoning_details'][0]['data'], 'opaque')
                    self.assertEqual(items[-1]['tool_call_id'], 'call_1')
                self.assertEqual(self.state.db.execute('SELECT count(*) FROM api_steps WHERE job_id=?', (job['id'],)).fetchone()[0], 2)
                self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE id LIKE ?', ('backend:' + job['id'] + '%',)).fetchone()[0], 1)
                self.assertEqual(self.state.db.execute('SELECT answer FROM api_history WHERE job_id=?', (job['id'],)).fetchone()[0], 'The roofs are blue.')

    def test_private_file_errors_are_returned_to_model_without_contents(self):
        tid, job = self.queue('deepseek')
        client = Mock()
        client.request.side_effect = [tool_response('deepseek', arguments={'path': 'private/deepseek.json', 'offset': 0, 'limit': 1000}), response('deepseek', 'Private file excluded.')]
        api_runner.run_job(self.state, job['id'], client=client)
        result = client.request.call_args.args[1]['messages'][-1]['content']
        self.assertFalse(json.loads(result)['ok'])
        self.assertNotIn(KEY, result)

    def test_saved_tool_output_is_reused_after_restart_even_if_file_changes(self):
        (self.root / 'README.md').write_text('original')
        tid, job = self.queue('openai')
        path = Path(self.state.db.execute('SELECT response_path FROM api_runs WHERE job_id=?', (job['id'],)).fetchone()[0])
        data = tool_response('openai')
        gemini.atomic_bytes(path, json.dumps(data).encode())
        call = api.tool_calls('openai', data)[0]
        saved = json.dumps({'ok': True, 'text': 'saved before restart'})
        with self.state.db:
            self.state.db.execute("UPDATE api_runs SET stage='sending' WHERE job_id=?", (job['id'],))
            self.state.db.execute('INSERT INTO api_tool_calls VALUES (?,?,?,?,?,?)', (job['id'], 0, call['id'], call['name'], call['arguments'], saved))
        (self.root / 'README.md').write_text('changed')
        backends.BackendWorker(self.state, backend='openai')
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        client = Mock()
        client.request.return_value = response('openai', 'Recovered')
        with patch('task_relay.file_tools.execute') as execute:
            api_runner.run_job(self.state, job['id'], client=client)
        execute.assert_not_called()
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(client.request.call_args.args[1]['input'][-1]['output'], saved)

    def test_uncertain_second_submission_is_not_replayed(self):
        (self.root / 'README.md').write_text('test')
        tid, job = self.queue('qwen')
        client = Mock()
        client.request.side_effect = [tool_response('qwen'), gemini.ProviderError('timeout', uncertain=True)]
        api_runner.run_job(self.state, job['id'], client=client)
        self.assertFalse(api.resume_job(self.state, job['id'], manual=True))
        api_runner.run_job(self.state, job['id'], client=client)
        self.assertEqual(client.request.call_count, 2)
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (job['id'],)).fetchone()[0], 'uncertain')

    def test_prepared_followup_survives_restart_before_submission(self):
        tid, job = self.queue('openrouter')
        client = Mock()
        client.request.return_value = tool_response('openrouter')
        config = api.read_config('openrouter')
        with patch('task_relay.api_providers.read_config', side_effect=[config, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                api_runner.run_job(self.state, job['id'], client=client)
        run = self.state.db.execute('SELECT * FROM api_runs WHERE job_id=?', (job['id'],)).fetchone()
        self.assertEqual((run['step'], run['stage']), (1, 'prepared'))
        self.assertEqual(json.loads(run['request_json'])['messages'][-1]['role'], 'tool')
        self.assertTrue(api.resume_job(self.state, job['id']))
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        client = Mock()
        client.request.return_value = response('openrouter', 'Resumed')
        api_runner.run_job(self.state, job['id'], client=client)
        self.assertEqual(client.request.call_count, 1)

    def test_multi_tool_list_search_read_chain_is_one_result(self):
        (self.root / 'README.md').write_text('A blue roof')
        tid, job = self.queue('qwen')
        first = tool_response('qwen', 'file_list', {'path': '.', 'recursive': False, 'offset': 0, 'limit': 20})
        second = tool_response('qwen', 'file_search', {'path': '.', 'query': 'roof', 'case_sensitive': False, 'offset': 0, 'limit': 20}, 'call_2')
        first['choices'][0]['message']['tool_calls'].extend(second['choices'][0]['message']['tool_calls'])
        client = Mock()
        client.request.side_effect = [first, tool_response('qwen', call_id='call_3'), response('qwen', 'Blue roof in README.md:1')]
        api_runner.run_job(self.state, job['id'], client=client)
        history = client.request.call_args.args[1]['messages']
        outputs = [json.loads(m['content']) for m in history if m['role'] == 'tool']
        self.assertTrue(any(r['path'] == 'README.md' for r in outputs[0]['entries']))
        self.assertEqual(outputs[1]['matches'][0]['line'], 1)
        self.assertEqual(outputs[2]['text'], 'A blue roof')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM api_tool_calls WHERE job_id=?', (job['id'],)).fetchone()[0], 3)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE id LIKE ?', ('backend:' + job['id'] + '%',)).fetchone()[0], 1)

    def test_api_schema_upgrade_preserves_legacy_runs(self):
        db = sqlite3.connect(':memory:')
        try:
            db.execute('CREATE TABLE api_runs(job_id TEXT PRIMARY KEY, model TEXT,base_url TEXT,stage TEXT,response_path TEXT,request_json TEXT,usage_json TEXT)')
            db.execute("INSERT INTO api_runs VALUES ('old','model','url','sending','path','{}',NULL)")
            api.initialize(db)
            api.initialize(db)
            self.assertEqual(db.execute('SELECT job_id,stage,step,workspace FROM api_runs').fetchone(), ('old', 'sending', 0, None))
        finally:
            db.close()

    def test_stop_after_response_prevents_local_read_and_followup(self):
        tid, job = self.queue('openai')
        def request(*_):
            with self.state.db:
                self.state.db.execute('UPDATE backend_jobs SET cancel=1 WHERE id=?', (job['id'],))
            return tool_response('openai')
        client = Mock()
        client.request.side_effect = request
        with patch('task_relay.file_tools.execute') as execute:
            api_runner.run_job(self.state, job['id'], client=client)
        execute.assert_not_called()
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (job['id'],)).fetchone()[0], 'stopped')

    def test_tool_budget_requests_final_summary_then_stops(self):
        tid, job = self.queue('deepseek')
        client = Mock()
        client.request.side_effect = [tool_response('deepseek'), tool_response('deepseek', call_id='call_2'), response('deepseek', 'Partial findings')]
        with patch('task_relay.api_providers.MAX_TOOL_ROUNDS', 2):
            api_runner.run_job(self.state, job['id'], client=client)
        self.assertEqual(client.request.call_count, 3)
        self.assertEqual(client.request.call_args.args[1]['tool_choice'], 'none')
        self.assertIn('budget reached', client.request.call_args.args[1]['messages'][0]['content'])

    def test_incomplete_and_duplicate_calls_never_execute(self):
        data = tool_response('openai')
        data['status'] = 'incomplete'
        with self.assertRaises(ValueError):
            api.tool_calls('openai', data)
        data = tool_response('qwen')
        data['choices'][0]['message']['tool_calls'] *= 2
        with self.assertRaises(ValueError):
            api.tool_calls('qwen', data)

    def test_old_saved_request_does_not_gain_file_permissions(self):
        tid, job = self.queue('openai')
        with self.state.db:
            self.state.db.execute('UPDATE api_runs SET workspace=NULL WHERE job_id=?', (job['id'],))
        client = Mock()
        client.request.return_value = tool_response('openai')
        with patch('task_relay.file_tools.execute') as execute:
            api_runner.run_job(self.state, job['id'], client=client)
        execute.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (job['id'],)).fetchone()[0], 'failed')

    def test_provider_shortcuts_continue_matching_task_and_deduplicate(self):
        for provider in api.SPECS:
            tid = self.create(provider)
            self.send(f'/{provider} Read README.md')
            job = self.state.db.execute('SELECT * FROM backend_jobs WHERE thread_id=?', (tid,)).fetchone()
            self.assertEqual(job['prompt'], 'Read README.md')
            self.assertEqual(self.state.get('selected'), tid)
            self.uid -= 1
            self.send(f'/{provider} Read README.md')
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs WHERE thread_id=?', (tid,)).fetchone()[0], 1)

    def test_cross_provider_shortcut_creates_and_queues_in_source_folder(self):
        source = self.create('openai')
        api.configure('qwen', KEY, [api.SPECS['qwen']['model']])
        self.send('/qwen Read README.md\nand summarise it')
        tid = self.state.get('selected')
        self.assertNotEqual(tid, source)
        self.assertEqual(backends.task(self.state, tid)['cwd'], str(self.root.resolve()))
        job = self.state.db.execute('SELECT * FROM backend_jobs WHERE thread_id=?', (tid,)).fetchone()
        self.assertEqual(job['prompt'], 'Read README.md\nand summarise it')
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=?', (self.uid,)).fetchone()[0], 'queued')
        self.uid -= 1
        self.send('/qwen Read README.md\nand summarise it')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 2)

    def test_shortcut_failure_does_not_leave_orphan_task_or_change_selection(self):
        source = self.create('openai')
        api.configure('qwen', KEY, [api.SPECS['qwen']['model']])
        with patch('task_relay.api_providers.MAX_CONTEXT', 1):
            self.send('/qwen Too large')
        self.assertEqual(self.state.get('selected'), source)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertFalse(self.state.db.execute('SELECT 1 FROM incoming WHERE id=?', (self.uid,)).fetchone())

    def test_shortcut_reply_wins_over_selection_unknown_reply_is_rejected(self):
        original = self.create('openai')
        reply_id = len(self.bot.sent)
        self.create('qwen')
        self.send('/openai Read README.md', reply=reply_id)
        self.assertEqual(self.state.db.execute('SELECT thread_id FROM backend_jobs').fetchone()[0], original)
        self.send('/qwen Wrong reply', reply=999999)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        self.assertIn('not linked', self.bot.sent[-1][1])

    def test_shortcut_no_selection_uses_default_folder_and_bare_command_does_not_run(self):
        api.configure('openai', KEY, [api.SPECS['openai']['model']])
        self.send('/openai')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        with patch('task_relay.bridge.WORKSPACES', self.root/'projects'):
            self.send('/openai Hello')
        tid = self.state.get('selected')
        self.assertEqual(backends.task(self.state, tid)['cwd'], str((self.root / 'projects').resolve()))
        self.assertEqual(self.state.db.execute('SELECT prompt FROM backend_jobs').fetchone()[0], 'Hello')

    def test_shortcut_from_codex_uses_its_folder(self):
        api.configure('openai', KEY, [api.SPECS['openai']['model']])
        with self.state.db:
            self.state.put('selected', 'codex-source')
        with patch('task_relay.bridge.local_tasks', return_value=[{'id': 'codex-source', 'cwd': str(self.root)}]):
            self.send('/openai Summarise this project')
        self.assertEqual(backends.task(self.state, self.state.get('selected'))['cwd'], str(self.root.resolve()))
