"""Local launcher setup recovery and loopback request boundaries."""
import http.client
import json
import os
from pathlib import Path
import shlex
import tempfile
import threading
import unittest
from unittest.mock import patch

from task_relay import credentials, launcher, onboarding
from task_relay.host import Host
from task_relay.relay_paths import Paths


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.paths = Paths(root / 'installed', root / 'data', root / 'workspaces', root / 'generated')
        self.project = root / 'Sample project'
        self.project.mkdir()
        self.enterContext(patch.object(launcher, 'PATHS', self.paths))
        self.enterContext(patch.object(onboarding, 'PATHS', self.paths))
        self.enterContext(patch.object(launcher, 'HOST', Host('darwin')))
        self.server = launcher.make_server()
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.prefix = '/l/' + self.server.launcher_token + '/'
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def _stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)

    def request(self, method, path, value=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        body = json.dumps(value).encode() if value is not None else None
        supplied = {'Host': f'127.0.0.1:{self.server.server_port}'}
        if body is not None:
            supplied.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        supplied.update(headers or {})
        connection.request(method, self.prefix + path, body, supplied)
        response = connection.getresponse()
        content = response.read()
        return response.status, content, dict(response.getheaders())

    def test_page_and_status_are_local_and_do_not_initialize_data(self):
        code, page, headers = self.request('GET', '')
        self.assertEqual(code, 200)
        self.assertIn(b'Download source files', page)
        self.assertIn(b'src="messages-icon.png"', page)
        self.assertIn(b'double-click <code>Setup.command</code>', page)
        self.assertIn(b'id="install-guide"', page)
        self.assertIn(b'id="live-setup" hidden', page)
        self.assertIn(b'task-relay/archive/refs/heads/main.zip', page)
        self.assertIn(b'Set up in a few steps', page)
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn("img-src 'self'", headers['Content-Security-Policy'])
        code, logo, headers = self.request('GET', 'messages-icon.png')
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertTrue(logo.startswith(b'\x89PNG\r\n\x1a\n'))
        code, raw, _ = self.request('GET', 'api/status')
        self.assertEqual(code, 200)
        data = json.loads(raw)
        self.assertEqual(data['project']['available'], False)
        self.assertEqual(data['telegram']['configured'], False)
        self.assertFalse(self.paths.data.exists())
        self.assertEqual(self.request('GET', 'launcher.js')[0], 200)

    def test_project_save_recovers_and_preserves_previous_setup(self):
        code, raw, _ = self.request('POST', 'api/provider', {'name': 'later'})
        self.assertEqual(code, 200, raw)
        code, raw, _ = self.request('POST', 'api/project', {'path': str(self.project)})
        self.assertEqual(code, 200, raw)
        before = credentials.private_json(self.paths.data / 'onboarding.json')
        self.assertEqual(before['provider'], 'later')
        self.assertEqual(before['project'], str(self.project))
        code, _, _ = self.request('POST', 'api/project', {'path': str(self.paths.data)})
        self.assertEqual(code, 400)
        self.assertEqual(credentials.private_json(self.paths.data / 'onboarding.json'), before)
        code, raw, _ = self.request('GET', 'api/status')
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(raw)['project']['available'])

    def test_provider_catalog_failure_does_not_save_key_and_retry_preserves_it(self):
        with patch.object(onboarding.api, 'catalog', side_effect=ValueError('Catalog unavailable')):
            code, raw, _ = self.request('POST', 'api/provider', {'name': 'openai', 'key': 'fixture-secret'})
        self.assertEqual(code, 400)
        self.assertNotIn(b'fixture-secret', raw)
        self.assertFalse((self.paths.data / 'openai.json').exists())
        with patch.object(onboarding.api, 'catalog', return_value=['fixture-text']) as catalog:
            code, raw, _ = self.request('POST', 'api/provider', {'name': 'openai', 'key': 'fixture-secret'})
            self.assertEqual(code, 200, raw)
            self.assertEqual(catalog.call_count, 1)
        saved = credentials.private_json(self.paths.data / 'openai.json')
        self.assertEqual(saved['model'], 'fixture-text')
        self.assertEqual((self.paths.data / 'openai.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.request('POST', 'api/project', {'path': str(self.project)})[0], 200)
        first_task = json.loads(self.request('GET', 'api/status')[1])['first_task_command']
        self.assertEqual(first_task, f'/new openai {shlex.quote(str(self.project))} First task')
        with patch.object(onboarding.api, 'catalog', side_effect=AssertionError('Rechecked')):
            self.assertEqual(self.request('POST', 'api/provider', {'name': 'openai'})[0], 200)
            self.assertEqual(self.request('POST', 'api/provider', {'name': 'openai', 'key': 'replacement-key'})[0], 400)
            self.assertEqual(self.request('POST', 'api/provider', {'name': 'openai', 'model': 'replacement-model'})[0], 400)
        self.assertEqual(credentials.private_json(self.paths.data / 'openai.json'), saved)
        self.assertNotIn(b'fixture-secret', self.request('GET', 'api/status')[1])

    def test_telegram_failure_retry_and_pairing_preserve_token(self):
        with patch('task_relay.bridge.Telegram.call', side_effect=OSError('token fixture should not leak')):
            code, raw, _ = self.request('POST', 'api/telegram', {'token': 'fixture-secret-token'})
        self.assertEqual(code, 500)
        self.assertNotIn(b'fixture-secret', raw)
        self.assertFalse((self.paths.data / 'config.json').exists())
        def telegram(method, **_):
            return {'getMe': {'username': 'fixture_bot'}, 'getWebhookInfo': {}}[method]
        with patch('task_relay.bridge.Telegram.call', side_effect=telegram) as call:
            code, raw, _ = self.request('POST', 'api/telegram', {'token': 'fixture-secret-token'})
            self.assertEqual(code, 200, raw)
            self.assertEqual(call.call_count, 2)
        data = json.loads(raw)
        self.assertTrue(data['pairing_url'].startswith('https://t.me/fixture_bot?start='))
        saved = credentials.private_json(self.paths.data / 'config.json')
        self.assertEqual(saved['token'], 'fixture-secret-token')
        with patch('task_relay.bridge.Telegram.call', side_effect=AssertionError('Rechecked')):
            self.assertEqual(self.request('POST', 'api/telegram', {'token': ''})[0], 200)
        self.assertEqual(credentials.private_json(self.paths.data / 'config.json'), saved)
        self.assertFalse(self.paths.state.exists())
        self.assertNotIn(b'fixture-secret-token', self.request('GET', 'api/status')[1])

    def test_origin_host_and_path_guard_reject_unwanted_mutation(self):
        data = {'path': str(self.project)}
        self.assertEqual(self.request('POST', 'api/project', data, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('POST', 'api/project', data, {'Host': 'other.example'})[0], 403)
        self.assertEqual(self.request('GET', '../api/status')[0], 404)
        self.assertFalse(self.paths.data.exists())

    def test_expired_pairing_link_renews_without_replacing_reference(self):
        with patch.dict(os.environ, {'RELAY_FIXTURE_TOKEN': 'fixture-token'}):
            credentials.save(self.paths.data / 'config.json', {
                'token_ref': {'source': 'environment', 'name': 'RELAY_FIXTURE_TOKEN'},
                'username': 'fixture_bot', 'pair_code': 'old', 'pair_expires': 0,
                'other_setting': 'retained'})
            with patch('task_relay.bridge.Telegram.call', side_effect=AssertionError('Unexpected Telegram call')):
                code, raw, _ = self.request('POST', 'api/telegram', {'token': ''})
        self.assertEqual(code, 200, raw)
        saved = credentials.private_json(self.paths.data / 'config.json')
        self.assertNotIn('token', saved)
        self.assertEqual(saved['token_ref']['name'], 'RELAY_FIXTURE_TOKEN')
        self.assertEqual(saved['other_setting'], 'retained')
        self.assertNotEqual(saved['pair_code'], 'old')

    def test_unsupported_host_exposes_status_without_setup_mutation(self):
        with patch.object(launcher, 'HOST', Host('win32')):
            code, raw, _ = self.request('GET', 'api/status')
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(raw)['platform'], 'win32')
            self.assertEqual(self.request('POST', 'api/project', {'path': str(self.project)})[0], 400)
        self.assertFalse(self.paths.data.exists())


if __name__ == '__main__':
    unittest.main()
