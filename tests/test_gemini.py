import base64
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
import wave
from unittest.mock import Mock, patch

from task_relay import backends
from task_relay import gemini
from task_relay import gemini_runner
from task_relay.bridge import State, Bridge, Telegram, TelegramError
from tests.test_bridge import TelegramFake, DesktopFake

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')

def result(parts):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': parts}}], 'usageMetadata': {'totalTokenCount': 17}}


def file_call(name='file_read', args=None, cid='read-1'):
    return result([{'thoughtSignature': 'opaque-signature', 'functionCall': {
        'id': cid, 'name': name, 'args': args or {'path': 'README.md', 'offset': 0, 'limit': 1000}}}])


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'private/state.sqlite')
        with self.state.db:
            self.state.put('user_id', 123)
            self.state.put('chat_id', 123)
        self.telegram = TelegramFake()
        self.bridge = Bridge(self.state, self.telegram, {}, DesktopFake)
        self.patches = [patch('task_relay.gemini.read_config', return_value={'api_key': 'test-secret', 'models': gemini.DEFAULT_MODELS}), patch('task_relay.gemini.ROOT', self.root), patch('task_relay.gemini.WORKSPACES',self.root/'projects'), patch('task_relay.gemini.GENERATED',self.root/'generated')]
        for p in self.patches:
            p.start()
        self.uid = 10
        self.send(f'/new gemini "{self.root}" Plan review')
        self.tid = self.state.get('selected')

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.state.db.close()
        self.temp.cleanup()

    def send(self, text='', user=123, reply='task', **extra):
        self.uid += 1
        message = {'chat': {'id': user, 'type': 'private'}, 'from': {'id': user}, 'text': text, **extra}
        # These provider-execution fixtures continue their task by explicit reply.
        # Pass reply=None to exercise a fresh orchestrator message instead.
        if reply == 'task':
            row = self.state.db.execute('SELECT message_id FROM messages WHERE thread_id=? ORDER BY message_id DESC LIMIT 1',
                                        (self.state.get('selected'),)).fetchone() if not text.startswith('/') else None
            reply = row[0] if row else None
        if reply is not None:
            message['reply_to_message'] = {'message_id': reply}
        self.bridge.process({'update_id': self.uid, 'message': message})

    def queued(self, prompt='Review the plan'):
        self.send(prompt)
        job = self.state.db.execute('SELECT * FROM backend_jobs ORDER BY created_at DESC LIMIT 1').fetchone()
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        return job['id']

    def status(self, jid):
        return self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (jid,)).fetchone()[0]

    def execute(self, jid, response):
        client = Mock()
        client.request.return_value = response
        gemini_runner.run_job(self.state, jid, client=client, sleep=lambda _: None)
        return client

    def test_creation_configuration_and_status_are_independent_of_claude(self):
        self.assertTrue(self.tid.startswith('gemini:'))
        with patch.object(DesktopFake, '__enter__', side_effect=AssertionError()):
            self.send('/status')
        self.assertIn('Gemini: idle', self.telegram.sent[-1][1])
        self.send('/model image custom-image-model')
        self.send('/model custom-text-model')
        self.assertEqual(backends.task(self.state, self.tid)['model'], 'custom-text-model')
        jid = self.queued('/image Courtyard')
        row = self.state.db.execute('SELECT * FROM gemini_runs WHERE job_id=?', (jid,)).fetchone()
        self.assertEqual((row['model'], row['capability']), ('custom-image-model', 'image'))
        self.send('/model other')
        self.assertEqual(backends.task(self.state, self.tid)['model'], 'custom-text-model')

    def test_gemini_shortcut_reads_file_and_returns_summary(self):
        (self.root / 'README.md').write_text('Project: courtyard with blue roofs.')
        jid = self.queued('/gemini read README.md and summarise it')
        job = self.state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (jid,)).fetchone()
        self.assertEqual(job['prompt'], 'read README.md and summarise it')
        self.assertEqual(job['thread_id'], self.tid)
        client = Mock()
        first = file_call()
        client.request.side_effect = [first, result([{'text': 'A courtyard with blue roofs.'}])]
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(self.status(jid), 'completed')
        self.assertEqual(client.request.call_count, 2)
        payload = client.request.call_args.args[1]
        self.assertEqual(payload['contents'][-2], first['candidates'][0]['content'])
        tool = payload['contents'][-1]['parts'][0]['functionResponse']
        self.assertEqual(tool['id'], 'read-1')
        self.assertEqual(tool['response']['text'], 'Project: courtyard with blue roofs.')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE id LIKE ?', ('backend:' + jid + '%',)).fetchone()[0], 1)
        self.assertEqual(len(json.loads(self.state.db.execute('SELECT usage_json FROM gemini_runs WHERE job_id=?', (jid,)).fetchone()[0])['steps']), 2)
        # Later turns keep the original prompt and final answer, not a dangling call.
        next_jid = self.queued('/gemini Explain more')
        following = self.execute(next_jid, result([{'text': 'More detail'}]))
        history = following.request.call_args.args[1]['contents']
        self.assertEqual(history[0]['parts'][0]['text'], job['prompt'])
        self.assertEqual(history[1]['parts'][0]['text'], 'A courtyard with blue roofs.')

    def test_shortcut_from_codex_creates_gemini_task_in_same_project(self):
        with self.state.db:
            self.state.put('selected', 'codex-source')
        with patch('task_relay.bridge.local_tasks', return_value=[{'id': 'codex-source', 'cwd': str(self.root)}]):
            self.send('/gemini@my_bot Read README.md')
        tid = self.state.get('selected')
        self.assertNotEqual(tid, self.tid)
        self.assertEqual(backends.task(self.state, tid)['cwd'], str(self.root.resolve()))
        self.assertEqual(self.state.db.execute('SELECT thread_id FROM backend_jobs').fetchone()[0], tid)

    def test_standalone_media_shortcuts_create_correct_runs_and_deduplicate(self):
        for capability in ('image', 'video'):
            with self.subTest(capability=capability):
                with self.state.db:
                    self.state.put('selected', None)
                with patch('task_relay.bridge.WORKSPACES', self.root/'projects'):
                    self.send(f'/{capability}@my_bot A courtyard\nwith trees')
                    self.uid -= 1
                    self.send(f'/{capability}@my_bot A courtyard\nwith trees')
                tid = self.state.get('selected')
                self.assertEqual(backends.task(self.state, tid)['cwd'], str((self.root / 'projects').resolve()))
                rows = self.state.db.execute('SELECT j.prompt,r.capability,r.model FROM backend_jobs j JOIN gemini_runs r ON r.job_id=j.id WHERE j.thread_id=?', (tid,)).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(tuple(rows[0]), ('A courtyard\nwith trees', capability, gemini.DEFAULT_MODELS[capability]))
                self.assertEqual(self.bridge.target_task({'reply_to_message': {'message_id': len(self.telegram.sent)}}, 123), tid)

    def test_media_reply_wins_and_busy_task_does_not_create_another(self):
        reply = len(self.telegram.sent)
        with self.state.db:
            self.state.put('selected', 'codex-source')
        self.send('/image Courtyard', reply=reply)
        self.send('/video Camera move', reply=reply)
        self.assertEqual(self.state.db.execute('SELECT thread_id FROM backend_jobs').fetchone()[0], self.tid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)
        self.assertIn('busy', self.telegram.sent[-1][1])

    def test_media_shortcuts_reject_missing_prompt_unknown_reply_and_unpaired_user(self):
        for command in ('/image', '/video'):
            self.send(command)
            self.send(command + ' Courtyard', reply=99999)
            self.send(command + ' Courtyard', user=456)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)

    def test_media_from_codex_creates_gemini_task_and_failure_rolls_back(self):
        with self.state.db:
            self.state.put('selected', 'codex-source')
        with patch('task_relay.bridge.local_tasks', return_value=[{'id': 'codex-source', 'cwd': str(self.root)}]):
            with patch('task_relay.gemini.prepare_run', side_effect=ValueError('Media unavailable')):
                self.send('/image Courtyard')
            self.assertEqual(self.state.get('selected'), 'codex-source')
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)
            self.send('/video Courtyard')
        tid = self.state.get('selected')
        self.assertEqual(backends.task(self.state, tid)['cwd'], str(self.root.resolve()))
        self.assertEqual(self.state.db.execute('SELECT capability FROM gemini_runs').fetchone()[0], 'video')

    def test_standalone_media_without_gemini_connection_gives_setup_guidance(self):
        with self.state.db:
            self.state.put('selected', None)
        with patch('task_relay.bridge.WORKSPACES', self.root/'projects'), patch('task_relay.gemini.read_config', return_value=None):
            self.send('/image Courtyard')
        self.assertIn('Connect Gemini', self.telegram.sent[-1][1])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertIsNone(self.state.get('selected'))

    def test_file_tool_error_returns_to_gemini_without_private_data(self):
        (self.root / 'private/key.txt').write_text('confidential')
        jid = self.queued()
        client = Mock()
        client.request.side_effect = [file_call(args={'path': 'private/key.txt', 'offset': 0, 'limit': 1000}), result([{'text': 'Private path excluded.'}])]
        gemini_runner.run_job(self.state, jid, client=client)
        output = client.request.call_args.args[1]['contents'][-1]['parts'][0]['functionResponse']['response']
        self.assertFalse(output['ok'])
        self.assertNotIn('confidential', json.dumps(output))

    def test_gemini_tool_unknown_second_submission_is_not_replayed(self):
        jid = self.queued()
        client = Mock()
        client.request.side_effect = [file_call(), gemini.ProviderError('timeout', uncertain=True)]
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(self.status(jid), 'uncertain')
        self.assertFalse(gemini.resume_job(self.state, jid, manual=True))
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(client.request.call_count, 2)

    def test_gemini_prepared_continuation_resumes_with_saved_file_result(self):
        (self.root / 'README.md').write_text('before restart')
        jid = self.queued()
        job = self.state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (jid,)).fetchone()
        run = self.state.db.execute('SELECT * FROM gemini_runs WHERE job_id=?', (jid,)).fetchone()
        client = Mock()
        client.request.return_value = file_call()
        def crash_after_advance():
            current = self.state.db.execute('SELECT step,stage FROM gemini_tool_runs WHERE job_id=?', (jid,)).fetchone()
            if current and current['step'] == 1 and current['stage'] == 'prepared':
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            gemini_runner.text_with_tools(self.state, job, run, client, crash_after_advance)
        (self.root / 'README.md').write_text('after restart')
        self.assertTrue(gemini.resume_job(self.state, jid))
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (jid,))
        client.reset_mock()
        client.request.return_value = result([{'text': 'Recovered summary'}])
        with patch('task_relay.file_tools.execute') as execute:
            gemini_runner.run_job(self.state, jid, client=client)
        execute.assert_not_called()
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(client.request.call_args.args[1]['contents'][-1]['parts'][0]['functionResponse']['response']['text'], 'before restart')
        self.assertEqual(self.status(jid), 'completed')

    def test_saved_gemini_tool_response_resumes_before_file_execution(self):
        (self.root / 'README.md').write_text('fixture')
        jid = self.queued()
        client = Mock()
        client.request.return_value = file_call()
        with patch('task_relay.file_tools.execute', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                gemini_runner.run_job(self.state, jid, client=client)
        self.assertTrue(gemini.resume_job(self.state, jid))
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (jid,))
        client.reset_mock()
        client.request.return_value = result([{'text': 'Recovered'}])
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(self.status(jid), 'completed')

    def test_gemini_tool_round_budget_requests_final_answer(self):
        jid = self.queued()
        client = Mock()
        client.request.side_effect = [file_call(), result([{'text': 'Available findings'}])]
        with patch('task_relay.api_providers.MAX_TOOL_ROUNDS', 1):
            gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(client.request.call_count, 2)
        self.assertEqual(client.request.call_args.args[1]['toolConfig']['functionCallingConfig']['mode'], 'NONE')

    def test_stop_during_gemini_file_read_prevents_next_request(self):
        jid = self.queued()
        client = Mock()
        client.request.return_value = file_call()
        def execute(*_):
            with self.state.db:
                self.state.db.execute('UPDATE backend_jobs SET cancel=1 WHERE id=?', (jid,))
            return {'ok': True, 'text': 'fixture'}
        with patch('task_relay.file_tools.execute', side_effect=execute):
            gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(self.status(jid), 'stopped')

    def test_duplicate_gemini_calls_are_rejected_before_files(self):
        jid = self.queued()
        data = file_call()
        data['candidates'][0]['content']['parts'] *= 2
        with patch('task_relay.file_tools.execute') as execute:
            self.execute(jid, data)
        execute.assert_not_called()
        self.assertEqual(self.status(jid), 'failed')

    def test_reference_authorization_dedup_pending_and_utf8(self):
        doc = {'file_id': 'f', 'file_name': 'brief.md', 'file_size': 20}
        self.send(document=doc, user=456)
        self.send(document=doc, reply=999)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM incoming_files').fetchone()[0], 0)
        self.send(document=doc, caption='This caption must not run')
        self.send('Too early')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.telegram.download_file = lambda fid, path, limit: gemini.atomic_bytes(path, b'Courtyard area: 100 m2')
        gemini.InputWorker(self.state, self.telegram).tick()
        jid = self.queued('Review the attached brief')
        client = self.execute(jid, result([{'text': 'The brief specifies 100 m2.'}]))
        payload = client.request.call_args.args[1]
        self.assertIn('Courtyard area: 100 m2', json.dumps(payload))
        self.assertEqual(self.status(jid), 'completed')
        ref = self.state.db.execute("SELECT id FROM artifacts WHERE role='input'").fetchone()[0]
        self.send('/forget ' + ref)
        self.assertEqual(self.state.db.execute('SELECT active FROM artifacts WHERE id=?', (ref,)).fetchone()[0], 0)

    def test_invalid_and_oversized_references_fail_before_generation(self):
        self.send(document={'file_id': 'f', 'file_name': 'plan.pdf', 'file_size': gemini.MAX_INPUT + 1})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM incoming_files').fetchone()[0], 0)
        self.send(document={'file_id': 'f', 'file_name': 'plan.pdf'})
        self.telegram.download_file = lambda fid, path, limit: gemini.atomic_bytes(path, b'not a PDF')
        gemini.InputWorker(self.state, self.telegram).tick()
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming_files').fetchone()[0], 'failed')

    def test_text_history_preserves_native_parts_and_blocks_arbitrary_file_uploads(self):
        private = self.root / 'confidential.txt'
        private.write_text('must never be attached based on model output')
        jid = self.queued()
        response = result([{'text': 'analysis', 'thought': True}, {'text': f'[read me](<{private}>)', 'thoughtSignature': 'signature'}])
        self.execute(jid, response)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 0)
        jid2 = self.queued('Explain your answer')
        client = self.execute(jid2, result([{'text': 'Explanation'}]))
        self.assertEqual(client.request.call_args.args[1]['contents'][1], response['candidates'][0]['content'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM gemini_history').fetchone()[0], 2)

    def test_image_edit_history_and_preview_original_delivery(self):
        image_response = result([{'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}, 'thoughtSignature': 'keep-me'}])
        jid = self.queued('/image Draw a courtyard')
        self.execute(jid, image_response)
        self.assertEqual(self.status(jid), 'completed')
        self.assertEqual({r[0] for r in self.state.db.execute('SELECT kind FROM media_outbox')}, {'preview', 'original'})
        jid2 = self.queued('/image Add trees to that image')
        client = self.execute(jid2, image_response)
        self.assertEqual(client.request.call_args.args[1]['contents'][1]['parts'][0]['thoughtSignature'], 'keep-me')
        self.bridge.flush()
        self.assertTrue(self.telegram.sent)

    def test_speech_wav_header_mp3_and_reply_mapping(self):
        jid = self.queued('/speak Welcome to the courtyard')
        audio = result([{'inlineData': {'mimeType': 'audio/L16;codec=pcm;rate=24000', 'data': base64.b64encode(b'\x00\x00' * 2400).decode()}}])
        self.execute(jid, audio)
        self.assertEqual(self.status(jid), 'completed')
        wavpath = Path(self.state.db.execute("SELECT path FROM artifacts WHERE mime='audio/wav'").fetchone()[0])
        self.assertTrue(wavpath.name.startswith('plan-review-'), wavpath.name)
        self.assertNotEqual(wavpath.name, 'speech.wav')
        with wave.open(str(wavpath)) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()), (24000, 1, 2, 2400))
        self.assertIn('audio', {r[0] for r in self.state.db.execute('SELECT kind FROM media_outbox')})
        self.bridge.flush()
        self.assertTrue(self.state.db.execute('SELECT 1 FROM messages WHERE thread_id=?', (self.tid,)).fetchone())

    def speech_source(self, backend='codex'):
        tid = backend + '-source'
        with self.state.db:
            self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                                  (tid, '', 0, 'Review project positioning', 'running', 1))
            if backend == 'claude':
                self.state.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,0)',
                                      (tid, backend, 'session', str(self.root), 'sonnet'))
            self.state.remember(123, 500, tid)
        return tid

    def test_speech_from_codex_reply_preserves_source_and_audio_routing(self):
        source = self.speech_source()
        self.send('/speak **I would adopt delegation.**', reply=500)
        job = self.state.db.execute('SELECT * FROM backend_jobs').fetchone()
        self.assertNotEqual(job['thread_id'], source)
        self.assertEqual(self.state.get('selected'), self.tid)
        self.assertEqual(self.state.db.execute('SELECT status FROM watched WHERE id=?', (source,)).fetchone()[0], 'running')
        self.assertEqual(job['prompt'], 'I would adopt delegation.')
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        audio = result([{'inlineData': {'mimeType': 'audio/L16;rate=24000', 'data': base64.b64encode(b'\x00\x00' * 2400).decode()}}])
        client = self.execute(job['id'], audio)
        self.assertEqual(self.status(job['id']), 'completed')
        self.assertEqual(client.request.call_args.args[1]['contents'], [{'role': 'user', 'parts': [{'text': job['prompt']}]}])
        self.assertEqual({r[0] for r in self.state.db.execute('SELECT thread_id FROM media_outbox')}, {source})
        filenames = [r[0] for r in self.state.db.execute('SELECT filename FROM media_outbox')]
        self.assertTrue(all(name.startswith('review-project-positioning-') for name in filenames), filenames)
        self.bridge.flush()
        last_message = len(self.telegram.sent)
        self.assertEqual(self.state.db.execute('SELECT thread_id FROM messages WHERE message_id=?', (last_message,)).fetchone()[0], source)
        self.assertEqual(self.state.db.execute('SELECT status FROM watched WHERE id=?', (source,)).fetchone()[0], 'running')
        self.send('/speak Another passage', reply=500)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM speech_tasks').fetchone()[0], 1)
        self.assertEqual({r[0] for r in self.state.db.execute('SELECT thread_id FROM backend_jobs')}, {job['thread_id']})

    def test_speech_selected_claude_runs_in_gemini_worker_only(self):
        source = self.speech_source('claude')
        with self.state.db:
            self.state.put('selected', source)
        self.send('/speak\nRead this text')
        job = self.state.db.execute('SELECT * FROM backend_jobs').fetchone()
        self.assertEqual(job['prompt'], 'Read this text')
        self.assertEqual(self.state.get('selected'), source)
        popen = Mock()
        backends.BackendWorker(self.state, popen, backend='claude').tick()
        popen.assert_not_called()
        backends.BackendWorker(self.state, popen, backend='gemini').tick()
        self.assertEqual(popen.call_args.args[0][1:3], ['-m', 'task_relay.gemini_runner'])

    def test_speech_without_task_and_duplicate_delivery(self):
        with self.state.db:
            self.state.put('selected', None)
        self.send('/speak Standalone text')
        self.uid -= 1
        self.send('/speak Standalone text')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        self.assertIsNone(self.state.get('selected'))

    def test_bare_speak_reads_reply_and_explicit_text_overrides_it(self):
        self.speech_source()
        self.send('/speak', reply_to_message={'message_id': 500, 'text': '**Read this reply.**'})
        job = self.state.db.execute('SELECT * FROM backend_jobs').fetchone()
        self.assertEqual(job['prompt'], 'Read this reply.')
        backends.finish(self.state, job['id'], 'failed', 'Test failure')
        self.send('/speak Use this instead', reply_to_message={'message_id': 500, 'text': 'Ignore this'})
        self.assertEqual(self.state.db.execute('SELECT prompt FROM backend_jobs ORDER BY created_at DESC LIMIT 1').fetchone()[0], 'Use this instead')

    def test_speech_missing_text_or_configuration_does_not_create_jobs(self):
        source = self.speech_source()
        self.send('/speak', reply=500)
        self.assertIn('followed by text', self.telegram.sent[-1][1])
        with patch('task_relay.gemini.read_config', return_value=None):
            self.send('/speak Hello', reply=500)
        self.assertIn('/providers', self.telegram.sent[-1][1])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM speech_tasks').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_busy_speech_has_usable_controls_and_does_not_block_source(self):
        source = self.speech_source()
        self.send('/speak Hello', reply=500)
        queue_message = len(self.telegram.sent)
        self.send('/status', reply=queue_message)
        self.assertIn('Gemini: queued', self.telegram.sent[-1][1])
        self.send('/speak More', reply=500)
        self.assertIn('/use gemini:', self.telegram.sent[-1][1])
        self.send('/stop', reply=queue_message)
        self.assertEqual(self.state.db.execute('SELECT cancel FROM backend_jobs').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM watched WHERE id=?', (source,)).fetchone()[0], 'running')

    def test_speech_normalizes_copied_markdown_without_reading_links(self):
        value = r'**I would adopt delegation.&#x20;**&#x54;he [POSITIONING.md]\(/private/secret.md\) file.'
        self.assertEqual(gemini.speech_text(value), 'I would adopt delegation. The POSITIONING.md file.')
        self.assertEqual(gemini.speech_text(r'[claude\_runner.py]\(/tmp/claude\_runner.py:130\)'), 'claude_runner.py')
        self.assertEqual(gemini.speech_text('hello_world and 2 * 3'), 'hello_world and 2 * 3')

    def test_speech_failure_rolls_back_task_creation(self):
        self.speech_source()
        with patch('task_relay.gemini.prepare_run', side_effect=ValueError('Invalid speech model')):
            self.send('/speak Hello', reply=500)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM speech_tasks').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)

    def test_video_saved_operation_restart_only_gets_and_downloads(self):
        jid = self.queued('/video Camera moves through a courtyard')
        run = self.state.db.execute('SELECT * FROM gemini_runs WHERE job_id=?', (jid,)).fetchone()
        gemini.atomic_bytes(Path(run['response_path']), json.dumps({'name': 'models/veo-3.1-fast-generate-preview/operations/abc'}).encode())
        with self.state.db:
            self.state.db.execute("UPDATE gemini_runs SET stage='sending' WHERE job_id=?", (jid,))
        backends.BackendWorker(self.state, backend='gemini')
        self.assertEqual(self.status(jid), 'queued')
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (jid,))
        client = Mock()
        client.request.side_effect = [{'done': False}, {'done': True, 'response': {'generateVideoResponse': {'generatedSamples': [{'video': {'uri': 'https://generativelanguage.googleapis.com/v1beta/files/video:download'}}]}}}]
        client.download.side_effect = lambda url, path: gemini.atomic_bytes(path, b'\x00\x00\x00\x18ftypisomvideo')
        gemini_runner.run_job(self.state, jid, client=client, sleep=lambda _: None)
        self.assertEqual(self.status(jid), 'completed')
        self.assertTrue(all(len(call.args) == 1 for call in client.request.call_args_list))
        self.assertEqual(self.state.db.execute('SELECT kind FROM media_outbox').fetchone()[0], 'video')

    def test_unknown_submission_is_never_replayed_and_worker_isolation(self):
        jid = self.queued('/video test')
        with self.state.db:
            self.state.db.execute("UPDATE gemini_runs SET stage='sending' WHERE job_id=?", (jid,))
        backends.BackendWorker(self.state)  # Claude worker must not touch Gemini.
        self.assertEqual(self.status(jid), 'running')
        backends.BackendWorker(self.state, backend='gemini')
        self.assertEqual(self.status(jid), 'uncertain')
        self.send('/resume')
        self.assertEqual(self.status(jid), 'uncertain')
        self.assertIn('No interrupted', self.telegram.sent[-1][1])

    def test_ambiguous_post_is_once_and_429_is_known_failure(self):
        jid = self.queued()
        client = Mock()
        client.request.side_effect = gemini.ProviderError('timeout', uncertain=True)
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(self.status(jid), 'uncertain')
        self.assertEqual(client.request.call_count, 1)
        self.send('/recover')
        jid2 = self.queued()
        client.request.side_effect = gemini.ProviderError(429)
        gemini_runner.run_job(self.state, jid2, client=client)
        self.assertEqual(self.status(jid2), 'failed')

    def test_filtered_and_empty_results_are_failures(self):
        for response in ({'promptFeedback': {'blockReason': 'SAFETY'}}, result([]), result([{'text': '', 'thought': True}])):
            jid = self.queued()
            self.execute(jid, response)
            self.assertEqual(self.status(jid), 'failed')

    def test_request_cap_rejects_without_submitting(self):
        jid = self.queued('a' * 100)
        client = Mock()
        with patch('task_relay.gemini.MAX_CONTEXT', 20):
            gemini_runner.run_job(self.state, jid, client=client)
        client.request.assert_not_called()
        self.assertEqual(self.status(jid), 'failed')

    def test_media_transport_sends_key_only_to_api_origin(self):
        client = gemini.Client('test-secret')
        requests = []
        def open_request(req, **kwargs):
            requests.append(req)
            if len(requests) == 1:
                raise urllib.error.HTTPError(req.full_url, 302, 'moved', {'Location': 'https://storage.googleapis.com/result.mp4'}, io.BytesIO())
            return io.BytesIO(b'video')
        client.opener = Mock()
        client.opener.open.side_effect = open_request
        client.download('https://generativelanguage.googleapis.com/v1beta/files/a:download', self.root / 'v.mp4')
        self.assertEqual(requests[0].get_header('X-goog-api-key'), 'test-secret')
        self.assertIsNone(requests[1].get_header('X-goog-api-key'))
        with self.assertRaises(gemini.ProviderError):
            client.download('https://evil.example/file', self.root / 'evil.mp4')
        self.assertEqual(len(requests), 2)

    def test_expired_video_download_resume_refreshes_operation_without_post(self):
        jid = self.queued('/video Courtyard')
        response = {'done': True, 'response': {'generateVideoResponse': {'generatedSamples': [{'video': {'uri': 'https://storage.googleapis.com/expired.mp4'}}]}}}
        client = Mock()
        client.request.side_effect = [{'name': 'operations/saved'}, response]
        client.download.side_effect = gemini.ProviderError(403)
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(self.status(jid), 'uncertain')
        self.send('/resume')
        self.assertEqual(self.status(jid), 'queued')
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (jid,))
        client.reset_mock()
        client.request.side_effect = [response]
        client.download.side_effect = lambda url, path: gemini.atomic_bytes(path, b'0000ftypisom')
        gemini_runner.run_job(self.state, jid, client=client)
        self.assertEqual(self.status(jid), 'completed')
        self.assertEqual(client.request.call_args.args, ('operations/saved',))

    def test_stopped_prepared_job_cannot_claim_to_resume_without_generation(self):
        jid = self.queued('/video Courtyard')
        with self.state.db:
            self.state.db.execute('UPDATE backend_jobs SET cancel=1 WHERE id=?', (jid,))
        client = Mock()
        gemini_runner.run_job(self.state, jid, client=client)
        client.request.assert_not_called()
        self.assertEqual(self.status(jid), 'stopped')
        self.assertFalse(gemini.resume_job(self.state, jid, manual=True))

    def test_gemini_supervisor_uses_system_runner_and_status_remains_local(self):
        self.send('Review this')
        process = Mock()
        process.poll.return_value = None
        popen = Mock(return_value=process)
        worker = backends.BackendWorker(self.state, popen, backend='gemini')
        worker.tick()
        self.assertEqual(popen.call_args.args[0][1:3], ['-m', 'task_relay.gemini_runner'])
        with patch.object(DesktopFake, '__enter__', side_effect=AssertionError()):
            self.send('/status')
            self.send('/tasks')
            self.bridge.flush()
        self.assertIn('Gemini · running', self.telegram.sent[-1][1])
        self.send('/stop')
        worker.tick()
        process.terminate.assert_called_once()

    def test_generation_claim_is_atomic_against_a_stale_runner(self):
        jid = self.queued()
        original = gemini_runner.make_request
        def concurrent_claim(state, job, run):
            payload = original(state, job, run)
            with state.db:
                state.db.execute("UPDATE gemini_runs SET stage='sending' WHERE job_id=?", (jid,))
            return payload
        client = Mock()
        with patch('task_relay.gemini_runner.make_request', side_effect=concurrent_claim):
            gemini_runner.run_job(self.state, jid, client=client)
        client.request.assert_not_called()
        self.assertEqual(self.status(jid), 'uncertain')

    def test_transport_errors_hide_credentials_and_do_not_retry(self):
        client = gemini.Client('test-secret')
        client.opener = Mock()
        client.opener.open.side_effect = urllib.error.HTTPError('https://private?key=test-secret', 503, 'secret', {}, io.BytesIO(b'test-secret'))
        with self.assertRaises(gemini.ProviderError) as caught:
            client.request('models/test:generateContent', {'contents': []})
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn('test-secret', str(caught.exception))
        self.assertEqual(client.opener.open.call_count, 1)

    def test_structured_rejection_retains_bounded_redacted_diagnostic_without_retry(self):
        client=gemini.Client('test-secret/+');client.opener=Mock()
        body=json.dumps({'error':{'code':400,'status':'INVALID_ARGUMENT','message':
            'function_declarations[0].parameters: invalid test-secret/+ test-secret%2F%2B '
            'https://private.example/?key=another-secret Bearer unknown-token'}}).encode()
        client.opener.open.side_effect=urllib.error.HTTPError('https://private',400,'secret',{},io.BytesIO(body))
        with self.assertRaises(gemini.ProviderError) as caught:client.request('models/test:generateContent',{})
        error=caught.exception
        self.assertFalse(error.uncertain);self.assertEqual(error.status,400)
        self.assertEqual(error.detail['status'],'INVALID_ARGUMENT')
        self.assertIn('function_declarations[0].parameters',str(error))
        for secret in ('test-secret','another-secret','unknown-token','private.example'):
            self.assertNotIn(secret,json.dumps(error.detail))
        self.assertEqual(client.opener.open.call_count,1)

    def test_oversized_or_unstructured_error_body_is_not_exposed(self):
        for body in (b'private raw error',b'x'*8193,b'[]',b'{"error":{"message":123}}'):
            client=gemini.Client('secret');client.opener=Mock()
            stream=io.BytesIO(body)
            client.opener.open.side_effect=urllib.error.HTTPError('https://private',400,'secret',{},stream)
            with self.subTest(body=body[:20]),self.assertRaises(gemini.ProviderError) as caught:
                client.request('models/test:generateContent',{})
            self.assertEqual(caught.exception.detail,{})
            self.assertEqual(str(caught.exception),'Gemini request failed (400)')
            self.assertTrue(stream.closed)

    def test_audio_multipart_and_document_fallback(self):
        path = self.root / 'speech.mp3'
        path.write_bytes(b'ID3audio')
        telegram = Telegram('fake')
        with patch.object(telegram, 'request', return_value={'message_id': 1}) as request:
            telegram.send_media(123, path, path.name, 'audio', 'Speech')
        self.assertEqual(request.call_args.args[0], 'sendAudio')
        self.assertIn(b'name="audio"', request.call_args.args[1])


    def test_plain_image_reply_reaches_intent_router_without_generating(self):
        image_response = result([{'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}, 'thoughtSignature': 'original-image-signature'}])
        first=self.queued('/image Make a logo from this drawing')
        self.execute(first,image_response)
        self.bridge.flush()
        message=self.state.db.execute('SELECT message_id FROM messages WHERE thread_id=? ORDER BY message_id DESC LIMIT 1',(self.tid,)).fetchone()[0]
        original='No, please make it just a scribble, no need for relay reference nothing like that. Just a nice scribble that will fit on a circle logo or a square logo.'
        self.send(original,reply=message)
        job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(self.uid,)).fetchone()
        self.assertEqual(job['prompt'],original)
        self.assertEqual(job['status'],'queued')
        self.assertEqual(self.state.get('orchestrator-media-reply:'+str(self.uid)),self.tid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)

    def test_explicit_text_switch_and_restart_preserve_reply_mode(self):
        image_response=result([{'inlineData': {'mimeType':'image/png','data':base64.b64encode(PNG).decode()}}])
        self.execute(self.queued('/image Draw a scribble'),image_response)
        other=State(self.root/'private/state.sqlite')
        try:self.assertEqual(backends.reply_capability(other,self.tid),'image')
        finally:other.db.close()
        jid=self.queued('/gemini Explain the symbolism without making a new image')
        self.assertEqual(self.state.db.execute('SELECT capability FROM gemini_runs WHERE job_id=?',(jid,)).fetchone()[0],'text')
        self.execute(jid,result([{'text':'Explanation'}]))
        self.assertEqual(backends.reply_capability(self.state,self.tid),'text')
        self.execute(self.queued('Explain further'),result([{'text':'More explanation'}]))
        self.execute(self.queued('/image Make the lines thinner'),image_response)
        self.assertEqual(backends.reply_capability(self.state,self.tid),'image')

    def test_legacy_orchestrator_image_task_recovers_from_accidental_text_turns(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_image_requests VALUES (1,?,'original','[]')",(self.tid,))
        self.execute(self.queued('/gemini Old wrong text reply'),result([{'text':'SVG code'}]))
        with self.state.db:self.state.db.execute('DELETE FROM kv WHERE key=?',('gemini-reply-capability:'+self.tid,))
        self.assertEqual(backends.reply_capability(self.state,self.tid),'image')
        self.send('Can you make an image of this')
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=?',(self.uid,)).fetchone()[0],'queued')

    def test_text_context_handoff_can_read_exact_earlier_response(self):
        first=self.queued('Preserve every original constraint.')
        original='Retained earlier evidence. '*2000
        self.execute(first,result([{'text':original}]))
        second=self.queued('Inspect the earlier evidence before continuing.')
        client=Mock();client.request.side_effect=[file_call('context_read',{'turn':0,'field':'response','offset':3,'limit':40}),result([{'text':'Reviewed earlier evidence.'}])]
        with patch.object(gemini,'MAX_CONTEXT',12000):
            gemini_runner.run_job(self.state,second,client=client)
        self.assertEqual(self.status(second),'completed')
        saved=json.loads(self.state.db.execute('SELECT result_json FROM api_tool_calls WHERE job_id=?',(second,)).fetchone()[0])
        self.assertEqual(saved['text'],original[3:43]);self.assertEqual(client.request.call_count,2)

    def test_image_context_handoff_keeps_latest_pixels_exact_instructions_and_archives(self):
        response=result([{'inlineData':{'mimeType':'image/png','data':base64.b64encode(PNG).decode()},'thoughtSignature':'opaque'*500}])
        first=self.queued('/image A tower');self.execute(first,response)
        previous=self.state.db.execute('SELECT * FROM gemini_history').fetchone()
        original=Path(previous['response_path']).read_bytes()
        second=self.queued('/image Keep the tower, change the sky')
        with patch.object(gemini,'MAX_CONTEXT',2000):
            client=self.execute(second,response)
        self.assertEqual(self.status(second),'completed')
        payload=client.request.call_args.args[1]
        self.assertEqual(len(payload['contents']),1)
        self.assertIn('A tower',json.dumps(payload))
        self.assertIn('Keep the tower, change the sky',json.dumps(payload))
        self.assertIn(base64.b64encode(PNG).decode(),json.dumps(payload))
        self.assertNotIn('thoughtSignature',json.dumps(payload))
        self.assertEqual(Path(previous['response_path']).read_bytes(),original)
        saved=self.state.db.execute('SELECT response_path FROM gemini_runs WHERE job_id=?',(second,)).fetchone()[0]
        receipt=json.loads(Path(saved).with_suffix('.context.json').read_text())
        self.assertEqual(receipt['sources'][0]['job_id'],first)
        self.assertEqual(client.request.call_count,1)

    def test_oversized_current_image_request_never_calls_provider(self):
        jid=self.queued('/image A tower')
        with patch.object(gemini,'MAX_CONTEXT',10):
            client=self.execute(jid,result([{'text':'no'}]))
        client.request.assert_not_called()
        self.assertEqual(self.status(jid),'failed')


if __name__ == '__main__':
    unittest.main()
