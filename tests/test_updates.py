"""Release switching and recovery use small SQLite fixtures and controlled services."""
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from task_relay import bridge, credentials, releases, updates, update_gate
from task_relay.relay_paths import Paths

ROOT = Path(__file__).resolve().parents[1]


class FakeService:
    def __init__(self, paths):
        self.paths = paths
        self.raw = b'old definition'
        self.starts = 0
        self.fail_starts = 0

    def capture(self):
        return dict(raw=base64.b64encode(self.raw).decode(), active=True, platform='fixture')

    def candidate(self, prior, target):
        return ('definition ' + target['install']).encode()

    def verify(self, prior, candidate):
        if self.raw not in (base64.b64decode(prior['raw']), candidate):
            raise ValueError('Service changed')

    def stop(self, prior):
        pass

    def write(self, raw):
        self.raw = raw

    def start(self, prior):
        self.starts += 1
        if self.fail_starts:
            self.fail_starts -= 1
            raise ValueError('fixture start failure')
        record = updates.load(updates.activation_path(self.paths))
        credentials.save(self.paths.data / 'updates/ready.json',
                         dict(nonce=record['nonce'], pid=os.getpid(), install=record['target']['install']))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.paths = Paths(ROOT, self.root / 'data', self.root / 'projects', self.root / 'generated')
        self.state = bridge.State(self.paths.state)
        self.addCleanup(self.state.db.close)
        with self.state.db:
            self.state.put('original-request', {'text': 'Preserve exactly this instruction'})
        self.service = FakeService(self.paths)
        # A separate real Python runtime tree, with the existing storage implementation.
        candidate = self.root / 'candidate'
        for package in ('task_relay', 'orchestrator'):
            shutil.copytree(ROOT / package, candidate / package, ignore=shutil.ignore_patterns('__pycache__', 'assets'))
        self.target = dict(updates.current(self.paths), install=str(candidate), version='0.12.1', code_hash=updates.code_hash(candidate))
        self.factory = lambda paths, install: self.service

    def activate(self, target=None):
        return updates.activate(target or self.target, self.paths, self.factory)

    def test_success_and_rollback_preserve_newer_history(self):
        result = self.activate()
        self.assertEqual(result['phase'], 'active')
        self.assertTrue(Path(result['backup']).is_file())
        with self.state.db:
            self.state.put('new-decision', {'artifact': 'fixture-version-2', 'accepted': True})
        rolled = self.activate(result['previous'])
        self.assertEqual(rolled['target']['install'], str(ROOT))
        self.assertEqual(self.state.get('new-decision')['artifact'], 'fixture-version-2')
        self.assertEqual(self.state.get('original-request')['text'], 'Preserve exactly this instruction')

    def test_unfinished_and_uncertain_work_prevents_switch(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO incoming(id,status) VALUES (1,'uncertain')")
        before = updates.content(self.state.db)
        with self.assertRaisesRegex(ValueError, 'Unfinished or uncertain'):
            self.activate()
        self.assertEqual(self.service.raw, b'old definition')
        self.assertEqual(updates.content(self.state.db), before)
        self.assertIsNone(updates.load(updates.activation_path(self.paths)))
        self.assertEqual(self.service.starts, 0)

    def test_finished_receipts_and_unused_buttons_do_not_block_or_become_accepted(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO provider_key_sessions VALUES ('fixture-key-prompt','openai',NULL,'waiting',0)")
            self.state.db.execute("INSERT INTO workflow_dispatches VALUES ('fixture-marker','fixture-workflow','fixture-task','Exact old request','submitted',0)")
            self.state.db.execute("INSERT INTO incoming_files(update_id,thread_id,file_id,filename,status) VALUES (42,'fixture-task','fixture-file','note.txt','attached')")
            self.state.db.execute("INSERT INTO production_control_cards(token,event_id,run,verb,epoch,digest,status) VALUES ('fixture-token','fixture-event','fixture-run','pause',0,'fixture-digest','pending')")
        before = updates.content(self.state.db)
        self.activate()
        self.assertEqual(updates.content(self.state.db), before)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_control_cards').fetchone()[0], 'pending')

    def test_linked_workflow_between_dispatches_blocks_until_stopped(self):
        with self.state.db:
            self.state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)', ('fixture-linked', json.dumps({'status':'active','phase':'execute_ready'})))
        with self.assertRaisesRegex(ValueError, 'workflows'):
            self.activate()
        self.assertEqual(self.service.starts, 0)
        with self.state.db:
            self.state.db.execute('UPDATE workflows SET data=?', (json.dumps({'status':'stopped','phase':'execute_ready'}),))
        self.activate()

    def test_pending_delivery_blocks_until_every_part_is_confirmed(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO outbox(id,text) VALUES ('fixture-event','Exact result')")
            self.state.db.execute("INSERT INTO outbox_parts(event_id,part,text) VALUES ('fixture-event',0,'Exact result')")
        with self.assertRaisesRegex(ValueError, 'outbox'):
            self.activate()
        self.assertEqual(self.service.starts, 0)
        with self.state.db:
            self.state.db.execute('UPDATE outbox SET sent=1')
        with self.assertRaisesRegex(ValueError, 'outbox_parts'):
            self.activate()
        with self.state.db:
            self.state.db.execute('UPDATE outbox_parts SET sent=1')
        self.activate()

    def test_work_arriving_during_stop_is_caught_by_second_check(self):
        def late_arrival(prior):
            with self.state.db:
                self.state.db.execute("INSERT OR IGNORE INTO incoming(id,status) VALUES (99,'queued')")
        with patch.object(self.service, 'stop', side_effect=late_arrival):
            with self.assertRaisesRegex(ValueError, 'Unfinished or uncertain'):
                self.activate()
        self.assertEqual(self.service.raw, b'old definition')
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=99').fetchone()[0], 'queued')

    def test_schema_change_is_detected_on_copy_and_original_is_untouched(self):
        module = Path(self.target['install']) / 'task_relay/bridge.py'
        module.write_text('import sqlite3\nclass State:\n def __init__(self,p):\n  self.db=sqlite3.connect(p)\n  self.db.execute("CREATE TABLE incompatible_schema(x)")\n  self.db.commit()\n')
        self.target['code_hash'] = updates.code_hash(self.target['install'])
        before = updates.content(self.state.db)
        with self.assertRaisesRegex(ValueError, 'changes stored data/schema'):
            self.activate()
        self.assertEqual(before, updates.content(self.state.db))
        self.assertEqual(self.service.raw, b'old definition')

    def test_failed_start_restores_service_without_reverting_data(self):
        self.service.fail_starts = 1
        with self.assertRaisesRegex(ValueError, 'fixture start failure'):
            self.activate()
        self.assertEqual(self.service.raw, b'old definition')
        self.assertEqual(self.service.starts, 2)
        self.assertIsNotNone(self.state.get('original-request'))
        record = updates.load(updates.activation_path(self.paths))
        self.assertEqual(record['phase'], 'active')
        self.assertEqual(record['previous']['install'], str(ROOT))

    def test_incomplete_recovery_has_explicit_receipt_and_can_be_recovered(self):
        self.service.fail_starts = 2
        with self.assertRaisesRegex(RuntimeError, 'recovery are incomplete'):
            self.activate()
        self.assertEqual(updates.load(updates.activation_path(self.paths))['phase'], 'recovery_required')
        with patch.object(updates, 'Service', self.factory):
            result = updates.recover(self.paths)
        self.assertEqual(result['phase'], 'active')
        self.assertEqual(result['target']['install'], str(ROOT))
        self.assertEqual(self.service.raw, b'old definition')

    def test_lost_commit_ack_does_not_roll_back_an_enabled_release(self):
        save = credentials.save
        def lost_ack(path, value):
            save(path, value)
            if path == updates.activation_path(self.paths) and value.get('phase') == 'active':
                raise KeyboardInterrupt
        with patch.object(credentials, 'save', side_effect=lost_ack):
            with self.assertRaisesRegex(RuntimeError, 'commit may have completed'):
                self.activate()
        self.assertEqual(self.service.starts, 1)
        self.assertEqual(updates.load(updates.activation_path(self.paths))['phase'], 'active')
        self.assertEqual(updates.load(updates.activation_path(self.paths))['target']['install'], self.target['install'])

    def test_changed_retained_code_refuses_rollback(self):
        result = self.activate()
        changed = Path(self.target['install']) / 'task_relay/fixture_change.py'
        changed.write_text('changed = True\n')
        with self.assertRaisesRegex(ValueError, 'files changed'):
            self.activate(result['previous'])
        self.assertEqual(updates.load(updates.activation_path(self.paths))['target']['install'], self.target['install'])

    def test_messages_deployment_is_preserved(self):
        (self.paths.data / 'messages-pilot').mkdir()
        with self.assertRaisesRegex(ValueError, 'Telegram-only'):
            self.activate()
        self.assertFalse(updates.activation_path(self.paths).exists())
        self.assertEqual(self.service.starts, 0)

    def test_existing_foreground_process_blocks_switch(self):
        # Fail immediately in this controlled check rather than waiting for a real service timeout.
        original = updates.lock
        def immediate(path, timeout=0):
            return original(path, timeout=0)
        with original(self.paths.data / 'bridge.lock'):
            with patch.object(updates, 'lock', immediate):
                with self.assertRaisesRegex(ValueError, 'another relay process'):
                    self.activate()
        self.assertEqual(self.service.raw, b'old definition')

    def test_startup_gate_waits_for_commit_before_returning(self):
        record = dict(phase='starting', nonce='fixture-nonce', target={'install': str(ROOT)})
        credentials.save(updates.activation_path(self.paths), record)
        done = []
        worker = threading.Thread(target=lambda: (update_gate.startup(self.paths, timeout=3), done.append(True)))
        worker.start()
        self.addCleanup(worker.join, 4)
        deadline = time.monotonic() + 2
        while not (self.paths.data / 'updates/ready.json').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(done)
        record['phase'] = 'active'
        credentials.save(updates.activation_path(self.paths), record)
        worker.join(2)
        self.assertEqual(done, [True])

    def test_stale_ready_receipt_is_not_acceptance(self):
        credentials.save(self.paths.data / 'updates/ready.json', dict(nonce='old', pid=os.getpid(), install=str(ROOT)))
        with self.assertRaisesRegex(ValueError, 'did not report'):
            updates.wait_ready(dict(nonce='new', target={'install': str(ROOT)}), self.paths, timeout=.01)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        import zipfile
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.paths = Paths(ROOT, self.root / 'data', self.root / 'projects', self.root / 'generated')
        self.wheel = self.root / 'task_relay-0.12.1-py3-none-any.whl'
        with zipfile.ZipFile(self.wheel, 'w') as archive:
            archive.writestr('task_relay-0.12.1.dist-info/METADATA', 'Name: task-relay\nVersion: 0.12.1\n')
            archive.writestr('task_relay/__init__.py', '')
        self.release = dict(version='0.12.1', filename=self.wheel.name,
                            sha256=updates.hashlib.sha256(self.wheel.read_bytes()).hexdigest(), size=self.wheel.stat().st_size)

    def test_bad_digest_and_unsupported_wheel_paths_never_install(self):
        import zipfile
        with patch.object(updates.venv.EnvBuilder, 'create') as create:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                updates.prepare(dict(self.release, sha256='b' * 64), self.paths,
                                downloader=lambda r,p: shutil.copyfile(self.wheel, p))
            with zipfile.ZipFile(self.wheel, 'a') as archive:
                archive.writestr('startup.pth', 'unapproved fixture path')
            self.release['sha256'] = updates.hashlib.sha256(self.wheel.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'installation paths'):
                updates.prepare(self.release, self.paths, downloader=lambda r,p: shutil.copyfile(self.wheel,p))
            create.assert_not_called()

    def test_interrupted_preparation_retries_owned_environment(self):
        import subprocess
        def create(path):
            (path / 'bin').mkdir(parents=True, exist_ok=True)
            (path / 'bin/python').write_text('fixture interpreter')
        reply = subprocess.CompletedProcess([], 0, stdout=json.dumps(dict(version='0.12.1', protocol=1, install=str(ROOT))))
        with patch.object(updates.venv.EnvBuilder, 'create', side_effect=create), patch.object(updates.subprocess, 'run') as run:
            run.side_effect = subprocess.CalledProcessError(1, ['fixture-pip'])
            with self.assertRaises(subprocess.CalledProcessError):
                updates.prepare(self.release, self.paths, downloader=lambda r,p: shutil.copyfile(self.wheel,p))
            run.side_effect = None
            run.return_value = reply
            target = updates.prepare(self.release, self.paths, downloader=lambda r,p: shutil.copyfile(self.wheel,p))
            run.reset_mock()
            self.assertEqual(updates.prepare(self.release, self.paths), target)
            run.assert_not_called()

    def test_windows_refuses_before_download_or_state_creation(self):
        from task_relay.host import Host
        with patch.object(updates, 'HOST', Host('win32')), patch.object(updates, 'PATHS', self.paths), patch.object(updates.sys, 'argv', ['update', 'apply', '--version', '0.13.0']), patch.object(releases, 'fetch') as fetch:
            with self.assertRaises(SystemExit):
                updates.main()
            fetch.assert_not_called()
        self.assertFalse(self.paths.data.exists())


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name).resolve() / 'data'
        self.store = releases.Store(self.data)
        self.addCleanup(self.store.close)
        self.release = dict(version='0.13.0', url=releases.WEB + 'tag/v0.13.0')

    def test_daily_check_survives_restart_and_failure_is_throttled(self):
        calls = []
        def fetch():
            calls.append(True)
            return self.release
        self.store.check(fetcher=fetch, now=100000)
        reopened = releases.Store(self.data)
        try:
            reopened.check(fetcher=fetch, now=100001)
            self.assertEqual(len(calls), 1)
            def broken():
                calls.append(True)
                raise OSError('fixture offline')
            self.assertEqual(reopened.check(fetcher=broken, now=200000), self.release)
            reopened.check(fetcher=broken, now=200001)
            self.assertEqual(len(calls), 2)
            self.assertIn('failed', releases.cached(self.data)['error'])
        finally:
            reopened.close()

    def test_notice_lost_ack_is_not_retried_after_restart(self):
        calls = []
        class Telegram:
            def call(self, method, **kwargs):
                calls.append(method)
                raise OSError('fixture acknowledgement lost')
        self.store.notify(self.release, Telegram(), 42)
        second = releases.Store(self.data)
        try:
            second.notify(self.release, Telegram(), 42)
            self.assertEqual(calls, ['sendMessage'])
            self.assertEqual(second.db.execute('SELECT status FROM notices').fetchone()[0], 'uncertain')
        finally:
            second.close()

    def test_confirmed_notice_is_once_per_version_and_not_for_current_version(self):
        from unittest.mock import Mock
        telegram = Mock()
        telegram.call.return_value = {'message_id': 99}
        self.store.notify(self.release, telegram, 42)
        self.store.notify(self.release, telegram, 42)
        self.store.notify(dict(self.release, version=releases.VERSION), telegram, 42)
        self.assertEqual(telegram.call.call_count, 1)
        self.assertEqual(self.store.db.execute('SELECT status,message_id FROM notices').fetchone(), ('sent', 99))

    def test_opt_out_does_not_check_or_send(self):
        from unittest.mock import Mock
        with patch.object(releases, 'preferences', return_value={'notifications': False}), patch.object(releases, 'Store') as store:
            releases.tick(Mock(), Mock())
            store.assert_not_called()

    def test_worker_honors_its_own_data_preference(self):
        from unittest.mock import Mock
        credentials.save(self.data / 'update-preferences.json', {'notifications': False})
        state = Mock()
        state.media_dir = self.data / 'media'
        state.get.return_value = 42
        with patch.object(releases, 'Store') as store:
            releases.tick(state, Mock())
            store.assert_not_called()

    def test_stable_versions_compare_numerically_and_reject_prereleases(self):
        self.assertGreater(releases.version('0.12.10'), releases.version('0.12.9'))
        for value in ('v0.12.0', '0.12.0-rc1', '00.12.0', '../latest'):
            with self.assertRaises(ValueError):
                releases.version(value)

    def test_metadata_requires_official_wheel_and_digest(self):
        from unittest.mock import MagicMock
        row = dict(tag_name='v0.13.0', draft=False, prerelease=False, assets=[dict(
            name='task_relay-0.13.0-py3-none-any.whl', state='uploaded', size=100,
            browser_download_url=releases.WEB + 'download/v0.13.0/task_relay-0.13.0-py3-none-any.whl', digest='sha256:' + 'a' * 64)])
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.side_effect = lambda limit: json.dumps(row).encode()
        with patch.object(releases.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(releases.fetch('0.13.0')['sha256'], 'a' * 64)
            row['assets'][0]['browser_download_url'] = 'https://example.invalid/untrusted.whl'
            with self.assertRaisesRegex(ValueError, 'URL or SHA-256'):
                releases.fetch('0.13.0')


if __name__ == '__main__':
    unittest.main()
