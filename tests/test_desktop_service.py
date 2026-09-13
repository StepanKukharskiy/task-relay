"""Controlled ownership and failed-start recovery for the packaged macOS service."""
import json
from contextlib import closing
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from task_relay.desktop_macos import DesktopService, DesktopServiceError, LABEL
from task_relay.relay_paths import Paths


class FakeHost:
    def __init__(self):
        self.loaded = False
        self.fail_bootstrap = False
        self.commands = []

    def require_macos(self, _):
        pass

    def launchctl(self, args, **_):
        self.commands.append(args[0])
        if args[0] == 'print':
            code = 0 if self.loaded else 1
        elif args[0] == 'bootstrap':
            code = 1 if self.fail_bootstrap else 0
            if code == 0:
                self.loaded = True
        elif args[0] == 'bootout':
            self.loaded = False
            code = 0
        else:
            raise AssertionError(args)
        return type('Result', (), {'returncode': code})()


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / 'runtime'
        python = self.runtime / 'python/bin/python3'
        python.parent.mkdir(parents=True)
        python.write_text('fixture')
        python.chmod(0o700)
        bridge = self.runtime / 'app/bridge.py'
        bridge.parent.mkdir(parents=True)
        bridge.write_text('fixture')
        self.paths = Paths(self.runtime / 'app', self.root / 'data',
                           self.root / 'workspaces', self.root / 'generated')
        binding = patch('task_relay.desktop_binding.FILE', self.root / 'no-binding.json')
        binding.start()
        self.addCleanup(binding.stop)
        self.host = FakeHost()
        self.now = 1000.0

    def service(self, sleep=None):
        return DesktopService(self.runtime, self.paths, self.host, self.root,
                              clock=lambda: self.now, sleep=sleep or self.tick)

    def tick(self, seconds):
        self.now += seconds

    def heartbeat(self):
        self.paths.data.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.paths.state)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',
                       ('health:poll', json.dumps({'last_success': self.now})))
            db.commit()

    def test_shutdown_waits_for_launchd_to_finish(self):
        service=DesktopService(sleep=lambda _:None)
        with patch.object(service,'_loaded',side_effect=[True,True,False]):
            self.assertTrue(service._wait_unloaded())

    def test_start_waits_for_fresh_poll_and_stop_preserves_definition(self):
        def ready(seconds):
            self.tick(seconds)
            self.heartbeat()
        with patch('task_relay.bridge.read_config', return_value={'token': 'fixture'}):
            result = self.service(ready).start(timeout=2)
        self.assertTrue(result['healthy'])
        self.assertEqual(result['owner'], 'desktop')
        self.assertEqual(plistlib.loads(self.service().path.read_bytes())['ProgramArguments'][0],
                         str(self.runtime / 'python/bin/python3'))
        stopped = self.service().stop()
        self.assertFalse(stopped['loaded'])
        self.assertTrue(self.service().path.exists())
        records = [json.loads(line) for line in
                   (self.paths.data / 'desktop-service-receipts.jsonl').read_text().splitlines()]
        self.assertEqual([r['phase'] for r in records], ['intent', 'ready', 'intent', 'stopped'])
        self.assertEqual(records[0]['id'], records[1]['id'])

    def test_source_service_is_preserved_without_bootstrap_or_stop(self):
        path = self.service().path
        path.parent.mkdir(parents=True)
        source = plistlib.dumps({'Label': LABEL, 'ProgramArguments': ['/source/python', '/source/bridge.py', 'run']})
        path.write_bytes(source)
        self.host.loaded = True
        self.assertEqual(self.service().status()['owner'], 'other')
        with patch('task_relay.bridge.read_config', return_value={'token': 'fixture'}):
            with self.assertRaises(DesktopServiceError):
                self.service().start()
        with self.assertRaises(DesktopServiceError):
            self.service().stop()
        self.assertEqual(path.read_bytes(), source)
        self.assertNotIn('bootstrap', self.host.commands)
        self.assertNotIn('bootout', self.host.commands)

    def test_connected_source_service_reports_its_own_health(self):
        path = self.service().path
        path.parent.mkdir(parents=True)
        path.write_bytes(plistlib.dumps({'Label': LABEL,
            'EnvironmentVariables': {'TASK_RELAY_DATA_DIR': str(self.paths.data)}}))
        self.host.loaded = True
        self.heartbeat()
        status = self.service().status()
        self.assertEqual(status['owner'], 'other')
        self.assertTrue(status['healthy'])
        self.assertIn('Existing source service', status['detail'])

    def test_failed_start_reverses_only_new_owned_definition(self):
        self.host.fail_bootstrap = True
        with patch('task_relay.bridge.read_config', return_value={'token': 'fixture'}):
            with self.assertRaises(DesktopServiceError):
                self.service().start()
        self.assertFalse(self.service().path.exists())
        self.assertFalse(self.host.loaded)
        records = [json.loads(line) for line in
                   (self.paths.data / 'desktop-service-receipts.jsonl').read_text().splitlines()]
        self.assertEqual([r['phase'] for r in records], ['intent', 'failed'])

    def test_stale_poll_stops_attempt_and_keeps_data(self):
        self.heartbeat()  # A prior service heartbeat cannot satisfy this start.
        self.now += 30
        with patch('task_relay.bridge.read_config', return_value={'token': 'fixture'}):
            with self.assertRaises(DesktopServiceError):
                self.service().start(timeout=.5)
        self.assertFalse(self.host.loaded)
        self.assertFalse(self.service().path.exists())
        self.assertTrue(self.paths.state.exists())

    def test_source_data_binding_cannot_be_started_as_a_new_desktop_service(self):
        binding = self.root / 'binding.json'
        binding.write_text('{}')
        with patch('task_relay.desktop_binding.FILE', binding):
            with self.assertRaises(DesktopServiceError):
                self.service().start()
        self.assertFalse(self.service().path.exists())
        self.assertNotIn('bootstrap', self.host.commands)


if __name__ == '__main__':
    unittest.main()
