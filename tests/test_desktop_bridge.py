"""Packaged-window request framing and local-data isolation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.env = {**os.environ,
                    'TASK_RELAY_DATA_DIR': str(self.root / 'data'),
                    'TASK_RELAY_WORKSPACE_DIR': str(self.root / 'workspaces'),
                    'TASK_RELAY_GENERATED_DIR': str(self.root / 'generated')}

    def request(self, action, value):
        result = subprocess.run([sys.executable, '-m', 'task_relay.desktop_bridge', action],
                                input=json.dumps(value), text=True, capture_output=True,
                                env=self.env, timeout=10)
        return result, json.loads(result.stdout)

    def test_status_is_read_only_and_uses_json_frame(self):
        process, frame = self.request('status', {})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(frame['ok'])
        self.assertIn('doctor', frame['value'])
        self.assertFalse((self.root / 'data').exists())

    def test_companion_startup_does_not_initialize_or_return_a_workspace(self):
        process, frame = self.request('companion-status', {})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('setup', frame['value'])
        self.assertEqual(frame['value']['conversation'], {'url': None})
        self.assertNotIn('tasks', frame['value'])
        self.assertNotIn('storage', frame['value'])
        self.assertFalse((self.root / 'data').exists())

    def test_project_action_reaches_saved_setup_and_rejects_unknown_operation(self):
        project = self.root / 'Sample project'
        project.mkdir()
        process, frame = self.request('project', {'path': str(project)})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(frame['value']['project'], str(project))
        saved = json.loads((self.root / 'data' / 'onboarding.json').read_text())
        self.assertEqual(saved['project'], str(project))
        process, frame = self.request('shell', {'command': 'echo unsafe'})
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(frame['error'], 'Unknown setup action.')

    def test_cleanup_preview_skips_file_changed_before_apply(self):
        cache = self.root / 'data' / 'claude-venv' / 'lib' / '__pycache__' / 'fixture.pyc'
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b'old cache')
        process, frame = self.request('cleanup-preview', {})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(frame['value']['files'], 1)
        self.assertEqual(frame['value']['bytes'], len(b'old cache'))
        cache.write_bytes(b'changed cache')
        process, applied = self.request('cleanup-apply', {'manifest': frame['value']['manifest']})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(applied['value']['removed'], 0)
        self.assertEqual(applied['value']['skipped'], 1)
        self.assertTrue(cache.is_file())

    def test_browser_switch_saves_choice_and_open_requires_enabled(self):
        process, frame = self.request('browser-configure', {'enabled': False})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('off', frame['value']['message'])
        saved = json.loads((self.root/'data/browser-use.json').read_text())
        self.assertFalse(saved['enabled'])
        _, frame = self.request('companion-status', {})
        self.assertFalse(frame['value']['browser']['enabled'])
        _, frame = self.request('browser-open', {})
        self.assertFalse(frame['ok'])
        self.assertIn('Turn Browser use on', frame['error'])

    def test_model_default_round_trip_through_native_bridge(self):
        import sqlite3
        from task_relay import credentials
        data = self.root/'data'
        data.mkdir()
        with sqlite3.connect(data/'state.sqlite') as db:
            db.execute('CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT)')
        credentials.save(data/'gemini.json', {'api_key':'fixture-only', 'models':{'image':'gemini-image-fixture'}})
        process, frame = self.request('model-default', {'revision':0,'capability':'image','provider':'gemini','model':'gemini-image-fixture'})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(frame['ok'], frame)
        _, frame = self.request('companion-status', {})
        self.assertEqual(frame['value']['model_defaults']['choices']['image'], {'provider':'gemini','model':'gemini-image-fixture'})
        self.assertNotIn('fixture-only', json.dumps(frame))
        _, frame = self.request('model-default', {'revision':0,'capability':'image','provider':'gemini','model':'gemini-image-fixture'})
        self.assertFalse(frame['ok'])
        self.assertIn('changed', frame['error'])


if __name__ == '__main__':
    unittest.main()
