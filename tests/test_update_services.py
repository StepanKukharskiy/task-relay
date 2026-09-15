"""Controlled native service definition checks; no real service is dispatched here."""
import base64
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from task_relay import host_updates, host_linux
from task_relay.host import Host
from task_relay.relay_paths import Paths


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.paths = Paths(self.root / 'old-code', self.root / 'data', self.root / 'projects', self.root / 'generated')
        self.paths.data.mkdir()
        self.target = dict(python=str(self.root / 'new/bin/python'), install=str(self.root / 'new-code'))

    def test_macos_owned_definition_preserves_environment_and_rejects_edits(self):
        host = Host('darwin')
        with patch.object(host_updates, 'HOST', host), patch.object(host, 'launchctl', return_value=subprocess.CompletedProcess([], 0)), patch.object(Path, 'home', return_value=self.root):
            service = host_updates.Service(self.paths, self.paths.install)
            spec = dict(Label=host_updates.LABEL, WorkingDirectory=str(self.paths.install),
                        ProgramArguments=['/fixture/python', str(self.paths.install / 'bridge.py'), 'run'],
                        EnvironmentVariables={**self.paths.environment(), 'FIXTURE_BINDING': 'retained'}, KeepAlive=True)
            host_linux.write(service.path, plistlib.dumps(spec))
            prior = service.capture()
            candidate = service.candidate(prior, self.target)
            new = plistlib.loads(candidate)
            self.assertEqual(new['EnvironmentVariables'], spec['EnvironmentVariables'])
            self.assertEqual(new['ProgramArguments'][0], self.target['python'])
            self.assertEqual(new['ProgramArguments'][1:], ['-m', 'task_relay.bridge', 'run'])
            self.assertEqual(plistlib.loads(base64.b64decode(prior['raw'])), spec)
            service.write(candidate)
            service.verify(prior, candidate)
            # A subsequent update recognizes the canonical definition too.
            next_service = host_updates.Service(self.paths, self.target['install'])
            self.assertEqual(base64.b64decode(next_service.capture()['raw']), candidate)
            new['WorkingDirectory'] = '/fixture/edited'
            host_linux.write(service.path, plistlib.dumps(new))
            with self.assertRaisesRegex(ValueError, 'changed'):
                service.verify(prior, candidate)

    def test_macos_custom_launcher_is_not_replaced(self):
        with patch.object(host_updates, 'HOST', Host('darwin')), patch.object(Path, 'home', return_value=self.root):
            service = host_updates.Service(self.paths, self.paths.install)
            raw = plistlib.dumps(dict(Label=host_updates.LABEL, WorkingDirectory=str(self.paths.install),
                                     ProgramArguments=['/fixture/custom'], EnvironmentVariables=self.paths.environment()))
            host_linux.write(service.path, raw)
            with self.assertRaisesRegex(ValueError, 'custom launcher'):
                service.capture()
            self.assertEqual(service.read(), raw)

    def test_linux_definition_switch_keeps_path_bindings_and_detects_local_edits(self):
        path = self.root / 'user/task-relay-telegram.service'
        raw = host_linux.definition(self.paths.install, self.paths, '/fixture/python')
        host_linux.write(path, raw)
        with patch.object(host_updates, 'HOST', Host('linux')), patch.object(host_linux, 'unit_path', return_value=path), patch.object(host_linux, 'manager', return_value='fixture-systemctl'), patch.object(host_linux, 'command', return_value=subprocess.CompletedProcess([], 0)):
            service = host_updates.Service(self.paths, self.paths.install)
            prior = service.capture()
            candidate = service.candidate(prior, self.target)
            host_linux.check_owner(candidate, self.target['install'], ValueError, self.paths)
            service.write(candidate)
            service.verify(prior, candidate)
            host_linux.write(path, candidate + b'# edited\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                service.verify(prior, candidate)


if __name__ == '__main__':
    unittest.main()
