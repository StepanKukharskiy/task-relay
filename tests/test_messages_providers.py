import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import backends
import gemini
import gemini_runner
from messages_pilot import Pilot, Store
from messages_providers import ProviderRouter
from messages_service import definition
from tests.test_messages_pilot import Desktop, Transport


class Worker:
    def __init__(self, state, backend):
        self.state = state
    def tick(self):
        pass
    def close(self):
        pass


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = patch('gemini.read_config', return_value={'api_key': 'test-only', 'models': gemini.DEFAULT_MODELS})
        self.config.start()
        self.store = Store(self.root / 'pilot/state.sqlite')
        self.router = ProviderRouter(self.root / 'provider/state.sqlite', worker_factory=Worker)
        self.transport, self.desktop = Transport(), Desktop()
        log = self.root / 'rollout.jsonl'
        log.write_text(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_complete'}}) + '\n')
        self.task = {'id': 'codex-task', 'title': 'Codex task', 'rollout_path': str(log), 'cwd': str(self.root)}
        self.pilot = Pilot(self.store, self.transport, 'codex-task', lambda: self.desktop, lambda: [self.task], self.router)
        with self.store.db:
            self.store.put('chat', {'id': 42, 'guid': 'any;-;self@example.test'})
            self.pilot.baseline()
        self.sequence = 0

    def tearDown(self):
        self.router.close()
        self.store.db.close()
        self.config.stop()
        self.temp.cleanup()

    def send(self, text, guid=None):
        import datetime
        self.sequence += 1
        msg = {'guid': guid or str(self.sequence), 'chat_id': 42, 'chat_guid': 'any;-;self@example.test',
               'is_group': False, 'is_from_me': True, 'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'text': text}
        self.pilot.receive(msg)
        return msg

    def job(self):
        return self.router.state.db.execute('SELECT * FROM backend_jobs ORDER BY created_at DESC LIMIT 1').fetchone()

    def complete(self, answer='Gemini reply'):
        job = self.job()
        with self.router.state.db:
            self.router.state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=?", (job['id'],))
        client = Mock()
        client.request.return_value = {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [{'text': answer}]}}]}
        gemini_runner.run_job(self.router.state, job['id'], client=client)
        self.assertEqual(self.router.state.db.execute('SELECT status FROM backend_jobs WHERE id=?', (job['id'],)).fetchone()[0], 'completed')
        return client

    def test_gemini_reuses_config_and_preserves_conversation_history(self):
        self.send('/gemini Remember that my courtyard is shaded.')
        tid = self.job()['thread_id']
        self.assertEqual(self.job()['prompt'], 'Remember that my courtyard is shaded.')
        self.assertEqual(self.router.state.db.execute('SELECT model FROM backend_tasks').fetchone()[0], gemini.DEFAULT_MODELS['text'])
        self.complete('I will remember the shade.')
        self.send('/ask What did I say about the courtyard?')
        self.assertEqual(self.job()['thread_id'], tid)
        client = self.complete('It is shaded.')
        payload = client.request.call_args.args[1]
        self.assertTrue(any('shaded' in json.dumps(content) for content in payload['contents'][:-1]))

    def test_switch_to_codex_does_not_misroute_gemini_reply(self):
        self.send('/gemini Hello')
        self.send('/codex Continue the implementation')
        self.assertEqual(self.desktop.starts, [('codex-task', 'Continue the implementation')])
        self.complete('A Gemini answer')
        self.router.tick(self.pilot)
        rows = self.store.db.execute("SELECT text FROM delivery WHERE id LIKE 'backend:%'").fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(r['text'].startswith('🤖 Gemini') for r in rows))
        self.assertTrue(any('A Gemini answer' in r['text'] for r in rows))

    def test_duplicate_message_and_provider_submission_queue_once(self):
        message = self.send('/gemini Hello', 'same-guid')
        self.pilot.receive(message)
        before = self.job()['id']
        self.assertEqual(self.router.submit('same-guid', 'Hello', self.root), before)
        self.assertEqual(self.router.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)

    def test_switch_only_and_multiline_prompt(self):
        self.send('/gemini')
        self.send('/ask\nFirst line\nSecond line')
        self.assertEqual(self.job()['prompt'], 'First line\nSecond line')
        self.assertEqual(self.desktop.starts, [])

    def test_missing_connection_has_no_jobs_and_no_codex_fallback(self):
        with patch('gemini.read_config', return_value=None):
            self.send('/gemini Hello')
        self.assertIsNone(self.job())
        self.assertEqual(self.desktop.starts, [])
        self.assertIn('not connected', self.store.db.execute('SELECT text FROM delivery').fetchone()[0])

    def test_cancel_and_new_conversation(self):
        self.send('/gemini Hello')
        original = self.job()['thread_id']
        self.send('/new gemini')
        self.assertEqual(self.router.state.get('messages:gemini_task'), original)
        self.send('/stop gemini')
        self.assertEqual(self.job()['cancel'], 1)
        backends.finish(self.router.state, self.job()['id'], 'stopped', 'Cancelled')
        self.send('/new gemini')
        self.send('/gemini Fresh start')
        self.assertNotEqual(self.job()['thread_id'], original)

    def test_outbox_recovery_deduplicates_result(self):
        self.send('/gemini Hello')
        self.complete()
        self.router.tick(self.pilot)
        count = self.store.db.execute('SELECT count(*) FROM delivery').fetchone()[0]
        with self.router.state.db:
            self.router.state.db.execute('UPDATE outbox SET sent=0')
        self.router.tick(self.pilot)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM delivery').fetchone()[0], count)

    def test_restart_keeps_selected_provider_and_gemini_conversation(self):
        self.send('/gemini Hello')
        self.complete()
        tid = self.job()['thread_id']
        self.router.close()
        self.router = ProviderRouter(self.root / 'provider/state.sqlite', worker_factory=Worker)
        self.pilot.providers = self.router
        self.send('/ask Follow up after restart')
        self.assertEqual(self.job()['thread_id'], tid)
        self.assertEqual(self.desktop.starts, [])

    def test_login_service_uses_app_and_keeps_private_logs(self):
        plist = definition()
        self.assertTrue(plist['KeepAlive'])
        self.assertTrue(plist['RunAtLoad'])
        self.assertEqual(plist['Umask'], 0o077)
        self.assertTrue(plist['ProgramArguments'][0].endswith('Messages Relay.app/Contents/MacOS/MessagesRelay'))
        self.assertNotIn('Terminal', str(plist))


if __name__ == '__main__':
    unittest.main()
