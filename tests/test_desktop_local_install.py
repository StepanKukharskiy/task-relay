"""Local update preparation retains bindings and refuses stale/active installs."""
import importlib.util
import json
from pathlib import Path
import plistlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'desktop/scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    SPEC = importlib.util.spec_from_file_location('install_local', SCRIPTS / 'install-local.py')
    local = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(local)


class LocalInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installed = self.root / 'Task Relay.app'
        self.candidate = self.root / 'Candidate.app'
        for app in (self.installed, self.candidate):
            (app / 'Contents').mkdir(parents=True)
            (app / 'Contents/fixture').write_text(app.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        with sqlite3.connect(self.data / 'state.sqlite') as db:
            db.execute('CREATE TABLE production_attempts(state TEXT)')
        runtime = self.installed / 'Contents/Resources/resources/runtime'
        env = {'TASK_RELAY_DATA_DIR': str(self.data), 'TASK_RELAY_GENERATED_DIR': str(self.root / 'generated'), 'TASK_RELAY_WORKSPACE_DIR': str(self.root / 'projects')}
        self.plists = [self.root / (label + '.plist') for label in local.LABELS]
        owners = ['task-relay-desktop-v1', 'task-relay-companion-messages-v1']
        commands = [[str(runtime / 'python/bin/python3'), str(runtime / 'app/bridge.py'), 'run'], [str(runtime / 'helpers/Messages Relay.app/Contents/MacOS/MessagesRelay')]]
        for i, path in enumerate(self.plists):
            path.write_bytes(plistlib.dumps({'Label': local.LABELS[i], 'TaskRelayDesktopOwner': owners[i], 'EnvironmentVariables': env, 'ProgramArguments': commands[i]}))
        self.before = [p.read_bytes() for p in self.plists]
        self.recovery = self.root / 'recovery'
        self.addCleanup(patch.stopall)
        patch.object(local, 'PLISTS', self.plists).start()

    def prepare(self):
        with patch('sys.argv', ['install', '--prepare', str(self.recovery), '--candidate', str(self.candidate), '--installed', str(self.installed)]):
            local.main()

    def test_preparation_records_main_app_migration_without_mutating_services(self):
        self.prepare()
        manifest = json.loads((self.recovery / 'install-manifest.json').read_text())
        spec = manifest['updated_messages_spec']
        self.assertEqual([str(self.installed / 'Contents/MacOS/task-relay-desktop'), '--messages-service'], spec['ProgramArguments'])
        self.assertEqual(str(self.data), spec['EnvironmentVariables']['TASK_RELAY_DATA_DIR'])
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_active_attempt_prevents_update_preparation(self):
        with sqlite3.connect(self.data / 'state.sqlite') as db:
            db.execute("INSERT INTO production_attempts VALUES ('running')")
        with self.assertRaisesRegex(RuntimeError, 'Active or queued'):
            self.prepare()
        self.assertFalse(self.recovery.exists())
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])

    def test_changed_candidate_cannot_stop_services(self):
        self.prepare()
        (self.candidate / 'Contents/fixture').write_text('changed')
        with patch('sys.argv', ['install', '--apply', str(self.recovery / 'install-manifest.json')]), patch.object(local, 'run') as run:
            with self.assertRaisesRegex(AssertionError, 'Candidate changed'):
                local.main()
        run.assert_not_called()
        self.assertEqual(self.before, [p.read_bytes() for p in self.plists])
