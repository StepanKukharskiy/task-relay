"""Controlled service switch, changed-review rejection and interrupted recovery."""
from contextlib import closing
import json
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from task_relay.desktop_handoff import Handoff
from task_relay.desktop_macos import DesktopServiceError
from task_relay.host import Host
from task_relay.relay_paths import Paths


class FixtureHost(Host):
    def __init__(self, case):
        super().__init__('darwin')
        self.case = case
        self.loaded = {}
        self.commands = []
        self.fail_candidate = False
        self.hold_loaded = False

    def launchctl(self, args, **_):
        self.commands.append(list(args))
        operation = args[0]
        if operation == 'bootstrap':
            spec = plistlib.loads(Path(args[2]).read_bytes())
            label = spec['Label']
            candidate = bool(spec.get('TaskRelayDesktopOwner'))
            if self.loaded.get(label):
                raise AssertionError('Two service owners attempted to load')
            code = 1 if candidate and self.fail_candidate else 0
            if not code:
                self.loaded[label] = True
                self.case.heartbeat(label)
        else:
            label = args[1].split('/')[-1]
            if operation == 'print':
                code = 0 if self.loaded.get(label) else 1
            elif operation == 'bootout':
                if not self.hold_loaded:
                    self.loaded[label] = False
                code = 0
            else:
                raise AssertionError(args)
        return type('Result', (), {'returncode': code})()


class HandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / 'Task Relay.app/Contents/Resources/resources/runtime'
        self.paths = Paths(self.runtime / 'app', self.root / 'data', self.root / 'work', self.root / 'generated')
        for name in ('python/bin/python3', 'app/bridge.py', '../../../MacOS/task-relay-desktop'):
            path = self.runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture runtime')
            path.chmod(0o700)
        self.paths.data.mkdir()
        with closing(sqlite3.connect(self.paths.state)) as db:
            db.executescript('CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE backend_jobs(status TEXT);'
                             'CREATE TABLE messages_settings(key TEXT PRIMARY KEY,value TEXT);'
                             'CREATE TABLE messages_delivery(id TEXT,status TEXT);')
            db.execute('INSERT INTO messages_settings VALUES (?,?)', ('chat', json.dumps({'id': 1})))
            db.execute('INSERT INTO messages_delivery VALUES (?,?)', ('kept', 'uncertain'))
            db.commit()
        self.now = 1000.
        self.host = FixtureHost(self)
        self.handoff = Handoff(self.runtime, self.paths, self.host, self.root, lambda: self.now, self.tick)
        self.enterContext(patch('task_relay.bridge.read_config', return_value={'token': 'fixture'}))
        self.enterContext(patch('task_relay.desktop_binding.FILE', self.root / 'binding.json'))
        self.enterContext(patch('task_relay.desktop_messages.shutil.which', return_value='/fixture/imsg'))

    def tick(self, seconds):
        self.now += seconds

    def heartbeat(self, label):
        self.now += .1
        if label.endswith('.messages'):
            self.paths.messages.mkdir(exist_ok=True)
            (self.paths.messages / 'health.json').write_text(json.dumps({'updated_at': self.now, 'status': 'running', 'pid': 42}))
        else:
            with closing(sqlite3.connect(self.paths.state)) as db:
                db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', ('health:poll', json.dumps({'last_success': self.now})))
                db.commit()

    def old_service(self, channel='relay', loaded=True):
        service = self.handoff.services[channel]
        arguments = ['/source/python', '/source/bridge.py', 'run'] if channel == 'relay' else ['/source/Messages Relay.app/Contents/MacOS/MessagesRelay']
        spec = {'Label': service._spec()['Label'], 'ProgramArguments': arguments,
                'EnvironmentVariables': self.paths.environment(), 'RunAtLoad': True}
        service.path.parent.mkdir(parents=True, exist_ok=True)
        raw = plistlib.dumps(spec)
        service.path.write_bytes(raw)
        self.host.loaded[spec['Label']] = loaded
        return service, raw

    def test_owned_messages_status_identifies_bundled_permission_target(self):
        from task_relay.desktop_messages import MessagesService
        service=MessagesService(self.runtime,self.paths,self.host,self.root,lambda:self.now,self.tick)
        service.path.parent.mkdir(parents=True,exist_ok=True)
        service.path.write_bytes(plistlib.dumps(service._spec()))
        self.paths.messages.mkdir(parents=True,exist_ok=True)
        (self.paths.messages/'health.json').write_text(json.dumps({'status':'needs_attention','updated_at':self.now,'detail':'Full Disk Access denied'}))
        self.host.loaded['com.personal.taskrelay.messages']=True
        state=service.status()
        self.assertTrue(state['managed']);self.assertFalse(state['healthy'])
        self.assertEqual(state['permission_app'],str(self.root/'Task Relay.app'))
        self.assertIn('Full Disk Access denied',state['detail'])

    def test_readonly_inspection_creates_nothing(self):
        self.assertEqual(self.handoff.inspect(), {'items': []})
        self.assertFalse(self.handoff.folder.exists())

    def test_connected_messages_still_shows_held_delivery_warning(self):
        from task_relay.desktop_messages import MessagesService
        service=MessagesService(self.runtime,self.paths,self.host,self.root,lambda:self.now,self.tick)
        service.path.parent.mkdir(parents=True,exist_ok=True)
        service.path.write_bytes(plistlib.dumps(service._spec()))
        self.paths.messages.mkdir(parents=True,exist_ok=True)
        warning='An earlier reply remains held for review. New messages can receive replies.'
        (self.paths.messages/'health.json').write_text(json.dumps({'status':'running','updated_at':self.now,'detail':warning}))
        self.host.loaded['com.personal.taskrelay.messages']=True
        state=service.status()
        self.assertTrue(state['healthy'])
        self.assertIn(warning,state['detail'])

    def test_handoff_starts_when_launchd_cannot_open_protected_data_logs(self):
        original = self.host.launchctl

        def restricted_launchctl(args, **kwargs):
            if args[0] == 'bootstrap':
                spec = plistlib.loads(Path(args[2]).read_bytes())
                if spec.get('TaskRelayDesktopOwner'):
                    for key in ('StandardOutPath', 'StandardErrorPath'):
                        log = Path(spec[key])
                        if log.is_relative_to(self.paths.data):
                            return type('Result', (), {'returncode': 1})()
                        # Simulate launchd opening its logs before starting the app.
                        with log.open('a') as stream:
                            stream.write('fixture startup\n')
            return original(args, **kwargs)

        with patch.object(self.host, 'launchctl', side_effect=restricted_launchctl):
            for channel in ('relay', 'messages'):
                service, _ = self.old_service(channel)
                plan = self.handoff.prepare(channel)
                self.assertEqual(self.handoff.apply(plan['id'], plan['digest'])['phase'], 'complete')
                self.assertTrue(service.status()['healthy'])

    def test_exact_switch_and_explicit_rollback_keep_history_and_pairing(self):
        service, prior = self.old_service()
        plan = self.handoff.prepare('relay')
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertNotIn('bootout', [a[0] for a in self.host.commands])
        result = self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(result['phase'], 'complete')
        self.assertEqual(service._owner()[0], 'desktop')
        restored = self.handoff.restore(plan['id'])
        self.assertEqual(restored['phase'], 'restored')
        self.assertEqual(service.path.read_bytes(), prior)
        with closing(sqlite3.connect(self.paths.state)) as db:
            self.assertEqual(db.execute('SELECT status FROM messages_delivery').fetchone()[0], 'uncertain')
            self.assertEqual(db.execute('SELECT count(*) FROM messages_settings').fetchone()[0], 1)

    def test_bound_existing_installation_can_start_only_after_exact_handoff(self):
        service, _ = self.old_service()
        (self.root / 'binding.json').write_text('{}')
        plan = self.handoff.prepare('relay')
        self.assertEqual(self.handoff.apply(plan['id'], plan['digest'])['phase'], 'complete')
        self.assertTrue(service.status()['healthy'])

    def test_failed_candidate_restores_prior_owner_and_is_not_reapplied(self):
        service, prior = self.old_service()
        plan = self.handoff.prepare('relay')
        self.host.fail_candidate = True
        with self.assertRaisesRegex(DesktopServiceError, 'prior definition was restored'):
            self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertTrue(service._loaded())
        count = len(self.host.commands)
        with self.assertRaisesRegex(DesktopServiceError, 'already attempted'):
            self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(len(self.host.commands), count)

    def test_changed_service_or_runtime_rejects_before_stopping(self):
        for changed in ('definition', 'runtime'):
            with self.subTest(changed=changed):
                service, _ = self.old_service()
                plan = self.handoff.prepare('relay')
                if changed == 'definition':
                    service.path.write_bytes(plistlib.dumps({'Label': 'different'}))
                else:
                    (self.runtime / 'app/bridge.py').write_text('new version')
                count = len([x for x in self.host.commands if x[0] == 'bootout'])
                with self.assertRaises(DesktopServiceError):
                    self.handoff.apply(plan['id'], plan['digest'])
                self.assertEqual(len([x for x in self.host.commands if x[0] == 'bootout']), count)

    def test_inflight_work_blocks_switch_without_stopping(self):
        service, prior = self.old_service()
        plan = self.handoff.prepare('relay')
        with closing(sqlite3.connect(self.paths.state)) as db:
            db.execute("INSERT INTO backend_jobs VALUES ('running')")
            db.commit()
        with self.assertRaisesRegex(DesktopServiceError, 'in-flight'):
            self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertNotIn('bootout', [a[0] for a in self.host.commands])

    def test_tampered_candidate_receipt_cannot_replace_a_service(self):
        import base64
        service, prior = self.old_service()
        plan = self.handoff.prepare('relay')
        path = self.handoff._file(plan['id'])
        record = json.loads(path.read_text())
        record['target'] = base64.b64encode(plistlib.dumps({'ProgramArguments': ['/different/program']})).decode()
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(DesktopServiceError, 'receipt is unavailable'):
            self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertNotIn('bootout', [a[0] for a in self.host.commands])

    def test_interrupted_switch_requires_explicit_restoration(self):
        service, prior = self.old_service()
        plan = self.handoff.prepare('relay')
        record = self.handoff._load(plan['id'])
        self.handoff._save(record, 'switching', 'Fixture interruption after old service stopped.')
        self.host.loaded[service._spec()['Label']] = False
        with self.assertRaisesRegex(DesktopServiceError, 'already attempted'):
            self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(self.handoff.inspect()['items'][0]['phase'], 'switching')
        self.assertFalse(service._loaded())
        self.handoff.restore(plan['id'])
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertTrue(service._loaded())

    def test_failed_shutdown_never_replaces_the_loaded_definition(self):
        service, prior = self.old_service()
        plan = self.handoff.prepare('relay')
        self.host.hold_loaded = True
        with self.assertRaisesRegex(DesktopServiceError, 'uncertain'):
            self.handoff.apply(plan['id'], plan['digest'])
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertEqual(self.handoff.inspect()['items'][0]['phase'], 'uncertain')
        self.assertFalse(any(args[0] == 'bootstrap' for args in self.host.commands))

    def test_messages_handoff_uses_one_hidden_helper_and_preserves_pairing(self):
        service, prior = self.old_service('messages')
        plan = self.handoff.prepare('messages')
        self.handoff.apply(plan['id'], plan['digest'])
        spec = plistlib.loads(service.path.read_bytes())
        self.assertEqual(spec['EnvironmentVariables']['TASK_RELAY_COMPANION'], '1')
        self.assertTrue(service.status()['healthy'])
        self.handoff.restore(plan['id'])
        self.assertEqual(service.path.read_bytes(), prior)

    def test_stopped_service_stays_stopped_after_handoff_and_restore(self):
        service, prior = self.old_service(loaded=False)
        plan = self.handoff.prepare('relay')
        self.handoff.apply(plan['id'], plan['digest'])
        self.assertFalse(service._loaded())
        self.handoff.restore(plan['id'])
        self.assertFalse(service._loaded())
        self.assertEqual(service.path.read_bytes(), prior)
        self.assertFalse(any(args[0] == 'bootstrap' for args in self.host.commands))

    def test_another_installation_cannot_be_adopted(self):
        service, _ = self.old_service()
        spec = plistlib.loads(service.path.read_bytes())
        spec['EnvironmentVariables']['TASK_RELAY_DATA_DIR'] = '/another/install'
        service.path.write_bytes(plistlib.dumps(spec))
        with self.assertRaisesRegex(DesktopServiceError, 'does not match'):
            self.handoff.prepare('relay')


if __name__ == '__main__':
    unittest.main()
