"""Signing must preserve an established identity and never fall back to ad hoc."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('sign_app', Path(__file__).resolve().parents[1] / 'desktop/scripts/sign-app.py')
signing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(signing)


class SigningTests(unittest.TestCase):
    def test_unconfigured_build_fails_without_commands_or_identity_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = Path(directory) / 'identity'
            with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['sign', '--identity-dir', str(identity)]), patch.object(signing, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'No ad hoc fallback'):
                    signing.main()
            run.assert_not_called()
            self.assertFalse(identity.exists())

    def test_rebuild_reuses_certificate_and_preserves_other_keychains(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / 'Task Relay.app'
            (app / 'Contents/MacOS').mkdir(parents=True)
            (app / 'Contents/MacOS/task-relay-desktop').write_text('small fixture')
            identity = root / 'identity'
            identity.mkdir()
            settings = identity / 'identity.json'
            settings.write_text(json.dumps({'identity': 'A' * 40, 'password': 'test-only'}))
            before = settings.read_bytes()
            def result(args, **kwargs):
                output = '"/example/existing.keychain-db"\n' if args[1] == 'list-keychains' and '-s' not in args else ''
                return subprocess.CompletedProcess(args, 0, output, '')
            with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['sign', str(app), '--identity-dir', str(identity)]), patch.object(signing, 'keychain'), patch.object(signing, 'run', side_effect=result) as run:
                signing.main()
            calls = [item.args[0] for item in run.call_args_list]
            self.assertIn(['/usr/bin/security', 'list-keychains', '-d', 'user', '-s', '/example/existing.keychain-db', str(identity / 'signing.keychain-db')], calls)
            sign = next(args for args in calls if '--sign' in args)
            self.assertEqual('A' * 40, sign[sign.index('--sign') + 1])
            self.assertEqual(before, settings.read_bytes())
            self.assertFalse(any('add-trusted-cert' in args for args in calls))

    def test_missing_private_key_cannot_trigger_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / 'identity.json'
            settings.write_text(json.dumps({'identity': 'A' * 40, 'password': 'test-only'}))
            with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['sign', '--init-local', '--identity-dir', str(root)]), patch.object(signing, 'keychain', side_effect=RuntimeError('missing keychain')), patch.object(signing, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'missing keychain'):
                    signing.main()
            run.assert_not_called()
            self.assertEqual('A' * 40, json.loads(settings.read_text())['identity'])
