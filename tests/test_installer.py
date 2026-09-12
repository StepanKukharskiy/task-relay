"""Installer retries must not overwrite unrelated environments or perform upgrades."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import install


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.target = Path(temp.name).resolve() / 'environment'

    def test_foreign_environment_and_changed_source_are_preserved(self):
        self.target.mkdir()
        sentinel = self.target / 'keep.txt'
        sentinel.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'not owned'):
            install.install(self.target)
        receipt = self.target / '.task-relay-install.json'
        receipt.write_text(json.dumps(dict(source=str(install.ROOT), sha256='old', status='ready')))
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            install.install(self.target)
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.assertEqual(json.loads(receipt.read_text())['sha256'], 'old')

    def test_interrupted_pip_retries_same_source_and_ready_install_skips_pip(self):
        def create(target):
            (target / 'bin').mkdir(exist_ok=True)
            (target / 'bin/task-relay').write_text('fixture')
        with patch.object(install.venv.EnvBuilder, 'create', side_effect=create), patch.object(install.subprocess, 'run') as run:
            run.side_effect = subprocess.CalledProcessError(1, ['pip'])
            with self.assertRaises(subprocess.CalledProcessError):
                install.install(self.target)
            self.assertEqual(json.loads((self.target / '.task-relay-install.json').read_text())['status'], 'installing')
            run.side_effect = None
            install.install(self.target)
            run.reset_mock()
            install.install(self.target)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][-1], '--version')


if __name__ == '__main__':
    unittest.main()
