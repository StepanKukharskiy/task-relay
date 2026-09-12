"""Setup interruption/recovery and local diagnostics, with synthetic credentials."""
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from task_relay import bridge, credentials, diagnostics, gemini, onboarding
from task_relay.host import Host
from task_relay.relay_paths import Paths


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.paths = Paths(self.root / 'installed', self.root / 'data', self.root / 'projects', self.root / 'generated')
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.output = io.StringIO()
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(redirect_stdout(self.output))
        self.stack.enter_context(patch.object(onboarding, 'PATHS', self.paths))
        self.stack.enter_context(patch.object(bridge, 'DATA', self.paths.data))
        self.stack.enter_context(patch.object(gemini, 'DATA', self.paths.data))
        self.transport = self.stack.enter_context(patch.object(bridge.Telegram, 'call', side_effect=self.telegram))
        self.stack.enter_context(patch.object(bridge.getpass, 'getpass', return_value='fixture-telegram-token'))
        self.catalog = self.stack.enter_context(patch.object(onboarding.api, 'catalog', return_value=['fixture-text']))

    def telegram(self, method, **kwargs):
        return {'getMe': {'username': 'fixture_relay_bot'}, 'getWebhookInfo': {}}[method]

    def ask(self, values):
        values = iter(values)
        return lambda prompt: next(values)

    def fresh(self):
        onboarding.setup(self.ask(['openai', '', str(self.project)]), lambda _: 'fixture-api-key')

    def test_fresh_setup_saves_selected_model_and_only_reads_telegram_metadata(self):
        self.fresh()
        config = credentials.private_json(self.paths.data / 'openai.json')
        self.assertEqual(config['model'], 'fixture-text')
        self.assertEqual([c.args[0] for c in self.transport.call_args_list], ['getMe', 'getWebhookInfo'])
        db = sqlite3.connect(self.paths.state)
        self.addCleanup(db.close)
        self.assertEqual(db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 0)
        command = next(line for line in self.output.getvalue().splitlines() if line.startswith('/new'))
        self.assertEqual(shlex.split(command)[2], str(self.project))
        self.assertNotIn('fixture-api-key', self.output.getvalue())
        self.assertNotIn('fixture-telegram-token', self.output.getvalue())
        self.assertEqual((self.paths.data / 'openai.json').stat().st_mode & 0o777, 0o600)

    def test_interruption_after_provider_save_resumes_without_reentering_or_rechecking_key(self):
        def interrupted(prompt):
            if prompt.startswith('Existing project'):
                raise KeyboardInterrupt
            return 'openai' if prompt.startswith('Provider') else ''
        with self.assertRaises(KeyboardInterrupt):
            onboarding.setup(interrupted, lambda _: 'fixture-api-key')
        before = (self.paths.data / 'openai.json').read_bytes()
        onboarding.setup(self.ask(['', str(self.project)]), lambda _: self.fail('Key requested twice'))
        self.assertEqual(self.catalog.call_count, 1)
        self.assertEqual(before, (self.paths.data / 'openai.json').read_bytes())

    def test_failed_telegram_check_leaves_provider_and_project_for_retry(self):
        self.transport.side_effect = OSError('fixture transport unavailable')
        with self.assertRaises(OSError):
            self.fresh()
        self.assertFalse((self.paths.data / 'config.json').exists())
        self.assertEqual(credentials.private_json(self.paths.data / 'onboarding.json')['project'], str(self.project))
        self.transport.side_effect = self.telegram
        onboarding.setup(self.ask(['', '']), lambda _: self.fail('Key requested twice'))
        self.assertEqual(self.catalog.call_count, 1)

    def test_invalid_saved_credential_is_preserved_without_prompt_or_network(self):
        credentials.save(self.paths.data / 'openai.json', {})
        before = (self.paths.data / 'openai.json').read_bytes()
        with self.assertRaises(ValueError):
            onboarding.setup_provider('openai', hidden=lambda _: self.fail('Unexpected key prompt'))
        self.assertEqual(before, (self.paths.data / 'openai.json').read_bytes())
        self.catalog.assert_not_called()

    def test_expired_unpaired_link_renews_preserving_credential_reference_and_settings(self):
        with patch.dict(os.environ, {'RELAY_FIXTURE_TOKEN': 'fixture-token'}):
            credentials.save(self.paths.data / 'config.json', dict(
                token_ref={'source': 'environment', 'name': 'RELAY_FIXTURE_TOKEN'},
                username='fixture_relay_bot', pair_code='fixture-old-pair', pair_expires=0, extra='retained'))
            onboarding.setup_telegram()
        config = credentials.private_json(self.paths.data / 'config.json')
        self.assertNotIn('token', config)
        self.assertEqual(config['token_ref']['name'], 'RELAY_FIXTURE_TOKEN')
        self.assertEqual(config['extra'], 'retained')
        self.assertGreater(config['pair_expires'], time.time())
        self.assertNotEqual(config['pair_code'], 'fixture-old-pair')
        self.transport.assert_not_called()

    def test_repeat_setup_preserves_paired_account_and_config_without_network(self):
        self.fresh()
        state = bridge.State(self.paths.state)
        with state.db:
            state.put('user_id', 42)
            state.put('chat_id', 43)
            state.put('decision-receipt', {'exact': 'retained'})
        state.db.close()
        before = (self.paths.data / 'config.json').read_bytes()
        self.transport.reset_mock()
        onboarding.setup(self.ask(['', '']), lambda _: self.fail('Key requested twice'))
        self.assertEqual(before, (self.paths.data / 'config.json').read_bytes())
        self.transport.assert_not_called()
        state = bridge.State(self.paths.state)
        self.assertEqual(state.get('decision-receipt'), {'exact': 'retained'})
        self.assertEqual(state.get('user_id'), 42)
        state.db.close()

    def test_concurrent_setup_rejected_and_lock_released_after_interruption(self):
        with self.assertRaises(KeyboardInterrupt):
            with onboarding.setup_lock():
                with self.assertRaisesRegex(ValueError, 'Another setup'):
                    with onboarding.setup_lock():
                        self.fail('Second setup acquired lock')
                raise KeyboardInterrupt
        with onboarding.setup_lock():
            pass

    def test_unlisted_model_does_not_save_key(self):
        with self.assertRaisesRegex(ValueError, 'not in the returned catalog'):
            onboarding.setup_provider('openai', self.ask(['other-model']), lambda _: 'fixture-key')
        self.assertFalse((self.paths.data / 'openai.json').exists())

    def test_gemini_selected_model_and_key_are_saved_together(self):
        from task_relay import providers
        with patch.object(providers, 'catalog', return_value=['fixture-text']):
            onboarding.setup_provider('gemini', self.ask(['fixture-text']), lambda _: 'fixture-key')
        config = credentials.private_json(self.paths.data / 'gemini.json')
        self.assertEqual(config['models']['text'], 'fixture-text')
        self.assertTrue(gemini.read_config())

    def test_doctor_does_not_create_fresh_state_and_detects_corrupt_database(self):
        result = diagnostics.inspect(self.paths, Host('darwin'))
        self.assertFalse(result['ok'])
        self.assertFalse(self.paths.data.exists())
        self.paths.data.mkdir()
        self.paths.state.write_text('invalid sqlite fixture')
        result = diagnostics.inspect(self.paths, Host('darwin'))
        self.assertIn('pairing', [c['check'] for c in result['checks'] if c['status'] == 'fail'])
        self.transport.assert_not_called()

    def test_doctor_redacts_credentials_and_does_not_claim_live_acceptance(self):
        self.fresh()
        result = diagnostics.inspect(self.paths, Host('darwin'))
        output = json.dumps(result)
        self.assertNotIn('fixture-api-key', output)
        self.assertNotIn('fixture-telegram-token', output)
        self.assertIn('delivery are unchecked', output)
        self.assertEqual(next(c['status'] for c in result['checks'] if c['check'] == 'pairing'), 'warn')

    def test_project_protects_data_and_installation_and_windows_fails_before_mutation(self):
        self.paths.data.mkdir()
        for folder in (self.root, self.paths.data):
            with self.assertRaises(ValueError):
                diagnostics.project_folder(str(folder), self.paths)
        with patch.object(onboarding, 'HOST', Host('win32')):
            with self.assertRaises(RuntimeError):
                onboarding.setup(lambda _: self.fail('Prompt on unsupported host'))
        self.assertEqual(list(self.paths.data.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
