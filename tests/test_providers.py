import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import backends
import gemini
import providers
import provider_runner
from bridge import Bridge, State, TelegramError
from tests.test_bridge import TelegramFake, DesktopFake

KEY = 'AIza' + 'X' * 35


class Bot(TelegramFake):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.markup = None
        self.delete_error = None

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'sendMessage':
            self.markup = params.get('reply_markup')
            return self.send(params['chat_id'], params['text'])
        if method == 'deleteMessage' and self.delete_error:
            raise self.delete_error
        return True


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch('gemini.DATA', self.root/'private'), patch('gemini.ROOT', self.root), patch('gemini.WORKSPACES',self.root/'projects')]
        for p in self.patches:
            p.start()
        self.state = State(self.root/'private/state.sqlite')
        with self.state.db:
            self.state.put('user_id', 123)
            self.state.put('chat_id', 123)
        self.bot = Bot()
        self.bridge = Bridge(self.state, self.bot, {}, DesktopFake)
        self.uid = 500

    def tearDown(self):
        self.state.db.close()
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def send(self, text, user=123, reply=None):
        self.uid += 1
        msg = {'message_id': self.uid, 'text': text, 'chat': {'id': user, 'type': 'private'}, 'from': {'id': user}}
        if reply is not None:
            msg['reply_to_message'] = {'message_id': reply}
        self.bridge.process({'update_id': self.uid, 'message': msg})
        return self.uid

    def click(self, label, user=123, data=None):
        data = data or next(b['callback_data'] for row in self.bot.markup['inline_keyboard'] for b in row if b['text'] == label)
        self.uid += 1
        self.bridge.process({'update_id': self.uid, 'callback_query': {'id': str(self.uid), 'from': {'id': user}, 'message': {'chat': {'id': 123, 'type': 'private'}}, 'data': data}})
        return data

    def enter_flow(self):
        self.send('/providers')
        self.click('Gemini')
        self.click('Connect / update API key')
        self.assertIn('not end-to-end encrypted', self.bot.sent[-1][1])
        self.click('Enter key in this chat')
        self.assertTrue(self.bot.markup['force_reply'])

    def configure(self):
        with patch('providers.catalog', return_value=list(gemini.DEFAULT_MODELS.values())):
            providers.configure_gemini(KEY)

    def test_openai_image_default_is_selected_in_chat_without_changing_text_model(self):
        config={'api_key':'fixture','model':'text-model','catalog':['text-model','gpt-image-2'],'enabled':True}
        with patch('providers.stored',return_value=config),patch('providers.api.read_config',return_value=config),patch('providers.credentials.save') as save:
            self.send('/providers');self.click('OpenAI');self.click('Default models');self.click('Image');self.click('gpt-image-2')
        saved=save.call_args.args[1]
        self.assertEqual(saved['model'],'text-model')
        self.assertEqual(saved['models']['image'],'gpt-image-2')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)

    def test_openrouter_image_default_uses_discovered_image_catalog(self):
        config={'api_key':'fixture','model':'vendor/text','catalog':['vendor/text'],
                'image_catalog':['vendor/image'],'enabled':True}
        with patch('providers.stored',return_value=config),patch('providers.api.read_config',return_value=config),patch('providers.credentials.save') as save:
            self.send('/providers');self.click('OpenRouter');self.click('Default models');self.click('Image');self.click('vendor/image')
        saved=save.call_args.args[1]
        self.assertEqual(saved['model'],'vendor/text');self.assertEqual(saved['models']['image'],'vendor/image')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)

    def test_phone_only_connect_validates_saves_and_deletes_without_model_dispatch(self):
        self.enter_flow()
        mid = self.send(KEY)
        job = self.state.db.execute('SELECT * FROM provider_jobs').fetchone()
        self.assertEqual((job['provider'], job['operation'], job['status']), ('gemini', 'connect', 'queued'))
        self.assertIn(('deleteMessage', {'chat_id': 123, 'message_id': mid}), self.bot.calls)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertNotIn(KEY, '\n'.join(self.state.db.iterdump()))
        self.assertNotIn(KEY, str(self.bot.sent))
        path = gemini.DATA/'setup-input'/(job['id']+'.json')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.state.db:
            self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?", (job['id'],))
        with patch('providers.catalog', return_value=list(gemini.DEFAULT_MODELS.values())) as check:
            provider_runner.run_job(self.state, job['id'])
        check.assert_called_once_with(KEY)
        self.assertEqual(gemini.read_config()['api_key'], KEY)
        self.assertFalse(path.exists())
        self.bridge.flush()
        self.assertIn('Gemini connected', self.bot.sent[-1][1])

    def test_unauthorized_callback_and_key_cannot_change_connection(self):
        self.send('/providers')
        n = len(self.bot.calls)
        self.click('Gemini', user=456)
        self.assertEqual(len(self.bot.calls), n)
        self.send(KEY, user=456)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0], 0)

    def test_key_outside_flow_is_never_sent_to_a_task(self):
        self.configure()
        self.send(f'/new gemini "{self.root}" Existing task')
        self.send(KEY)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertIn('not used or sent to a task', self.bot.sent[-1][1])

    def test_expired_and_cancelled_key_prompts_never_dispatch_credentials(self):
        for cancel in (False, True):
            self.enter_flow()
            prompt = self.state.db.execute('SELECT prompt_id FROM provider_key_sessions ORDER BY expires_at DESC LIMIT 1').fetchone()[0]
            if cancel:
                self.send('/cancelsetup')
            else:
                with self.state.db:
                    self.state.db.execute('UPDATE provider_key_sessions SET expires_at=0')
            self.send(KEY, reply=prompt)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_stale_model_button_targets_original_task_and_rejects_busy(self):
        self.configure()
        self.send(f'/new gemini "{self.root}" One')
        first = self.state.get('selected')
        self.send('/models')
        self.click('Text')
        button = next(b['callback_data'] for row in self.bot.markup['inline_keyboard'] for b in row if b['text'] == gemini.DEFAULT_MODELS['text'])
        self.send(f'/new gemini "{self.root}" Two')
        second = self.state.get('selected')
        with self.state.db:
            self.state.db.execute("UPDATE backend_tasks SET model='custom' WHERE id IN (?,?)", (first,second))
        self.click('', data=button)
        self.assertEqual(backends.task(self.state, first)['model'], gemini.DEFAULT_MODELS['text'])
        self.assertEqual(backends.task(self.state, second)['model'], 'custom')
        self.send('/models')
        self.click('Text')
        button = self.bot.markup['inline_keyboard'][0][0]['callback_data']
        self.send('Start working')
        self.click('', data=button)
        self.assertIn('busy', self.bot.sent[-1][1])

    def test_new_task_button_is_one_time_and_does_not_start_generation(self):
        self.configure()
        self.send('/providers')
        self.click('Gemini')
        button = self.click('New task')
        self.click('', data=button)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_disable_requires_confirmation_and_preserves_key(self):
        self.configure()
        self.send('/providers')
        self.click('Gemini')
        self.click('Disable provider')
        self.assertIsNotNone(gemini.read_config())
        self.click('Disable')
        self.assertIsNone(gemini.read_config())
        self.assertEqual(providers.stored('gemini')['api_key'], KEY)

    def test_reply_to_old_key_prompt_cannot_consume_new_connection_step(self):
        self.enter_flow()
        old = self.state.db.execute('SELECT prompt_id FROM provider_key_sessions').fetchone()[0]
        self.enter_flow()
        self.send(KEY, reply=old)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM provider_key_sessions WHERE status='waiting'").fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0], 0)

    def test_failed_connection_keeps_prior_key_and_cleans_transient_input(self):
        self.configure()
        self.enter_flow()
        self.send('AIza' + 'Y'*35)
        job = self.state.db.execute('SELECT * FROM provider_jobs').fetchone()
        with self.state.db:
            self.state.db.execute("UPDATE provider_jobs SET status='running'")
        with patch('providers.catalog', side_effect=gemini.ProviderError(403)):
            provider_runner.run_job(self.state, job['id'])
        self.assertEqual(gemini.read_config()['api_key'], KEY)
        self.assertFalse((gemini.DATA/'setup-input'/(job['id']+'.json')).exists())
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs').fetchone()[0], 'failed')

    def test_deletion_failure_has_persistent_retry_and_no_key_echo(self):
        self.bot.delete_error = TelegramError('deleteMessage', 500)
        self.enter_flow()
        self.send(KEY)
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_deletions').fetchone()[0], 'pending')
        with self.state.db:
            self.state.db.execute('UPDATE provider_deletions SET next_attempt=0')
        self.bot.delete_error = None
        providers.delete_pending(self.state, self.bot)
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_deletions').fetchone()[0], 'deleted')
        self.assertNotIn(KEY, str(self.bot.calls))

    def test_supervisor_does_not_wait_for_validation_and_cleans_interrupted_input(self):
        self.enter_flow()
        self.send(KEY)
        process = Mock()
        process.poll.return_value = None
        popen = Mock(return_value=process)
        worker = providers.Worker(self.state, popen=popen)
        worker.tick()
        self.assertIn('provider_runner.py', popen.call_args.args[0][1])
        self.send('/providers')
        self.assertIn('Providers', self.bot.sent[-1][1])
        job = self.state.db.execute('SELECT id FROM provider_jobs').fetchone()[0]
        providers.Worker(self.state)  # restart recovery
        self.assertFalse((gemini.DATA/'setup-input'/(job+'.json')).exists())
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs').fetchone()[0], 'failed')


if __name__ == '__main__':
    unittest.main()
