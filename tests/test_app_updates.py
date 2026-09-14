"""Controlled app update fixtures; no native app, service or network execution."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from task_relay import app_updates as updates, app_bundle
from task_relay.app_updates_macos import MacUpdater, extract
from task_relay.relay_paths import Paths


def release_fixture():
    manifest = dict(protocol=1, version='0.14.0', platform='macos', arch='arm64', channel='beta',
                    asset='Task-Relay-0.14.0-macos-arm64.zip', bytes=99, sha256='a'*64,
                    signer_sha256='b'*64, data_policy='unchanged')
    url = updates.DOWNLOADS + 'v0.14.0/'
    release = dict(tag_name='v0.14.0', draft=False, prerelease=True, assets=[
        dict(name=manifest['asset'], size=99, digest='sha256:' + 'a'*64, browser_download_url=url+manifest['asset']),
        dict(name='app-update-macos-arm64.json', browser_download_url=url+'app-update-macos-arm64.json')])
    return release, manifest


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = Mock()
        self.host.support.return_value = dict(supported=True, installed='0.13.0', arch='arm64')
        self.host.worker_alive.return_value = False
        self.host.spawn_worker.return_value.pid = 123
        self.release, self.manifest = release_fixture()
        self.fetch = Mock(side_effect=lambda url, limit: [self.release] if url == updates.API else self.manifest)
        self.updater = updates.Updater(self.host, self.root, fetcher=self.fetch)

    def ready(self):
        self.updater.check(True)
        self.updater.download(self.updater.status()['candidate']['id'])
        record = updates.read(self.updater.receipt)
        record['phase'] = 'ready'; updates.write(self.updater.receipt, record)
        return record

    def test_wheels_and_dmg_do_not_become_app_updates(self):
        self.release['assets'] = self.release['assets'][:1]
        self.assertIsNone(self.updater.check(True)['candidate'])
        self.host.spawn_worker.assert_not_called()

    def test_beta_is_opt_in_and_downgrades_are_ignored(self):
        self.assertIsNone(self.updater.check(False)['candidate'])
        self.assertEqual(self.updater.check(True)['candidate']['version'], '0.14.0')
        self.host.support.return_value['installed'] = '0.15.0'
        self.assertIsNone(self.updater.check(True)['candidate'])

    def test_status_is_local_and_read_only(self):
        self.assertEqual(self.updater.status()['attempt'], {})
        self.assertFalse(self.updater.cache.exists())
        self.fetch.assert_not_called()

    def test_asset_digest_url_and_channel_mismatch_are_rejected(self):
        for field, value in [('sha256','c'*64), ('channel','stable'), ('data_policy','migrate')]:
            with self.subTest(field=field):
                manifest = {**self.manifest, field:value}
                with self.assertRaises(updates.UpdateError):
                    updates.candidate(self.release,manifest,'arm64','0.13.0',True)
        self.release['assets'][0]['browser_download_url'] = 'https://example.org/other.zip'
        with self.assertRaises(updates.UpdateError): self.updater.check(True)

    def test_approval_is_exact_and_double_install_never_replays(self):
        record = self.ready()
        with self.assertRaises(updates.UpdateError): self.updater.install('another-attempt')
        self.updater.install(record['id'])
        with self.assertRaises(updates.UpdateError): self.updater.install(record['id'])
        self.assertEqual(self.host.spawn_worker.call_count, 2)  # one download, one install
        self.assertEqual(updates.read(self.updater.receipt)['phase'], 'launching')

    def test_busy_work_preserves_ready_download_and_app(self):
        record = self.ready()
        self.host.preflight.side_effect = updates.UpdateError('Work is running')
        with self.assertRaisesRegex(updates.UpdateError,'running'): self.updater.install(record['id'])
        self.assertEqual(updates.read(self.updater.receipt)['phase'], 'ready')
        self.assertEqual(self.host.spawn_worker.call_count, 1)

    def test_changed_candidate_and_signer_preserve_app(self):
        record = self.ready()
        self.host.validate_prepared.side_effect = updates.UpdateError('Signing identity changed')
        with self.assertRaises(updates.UpdateError): self.updater.install(record['id'])
        self.assertEqual(updates.read(self.updater.receipt)['phase'], 'ready')
        self.host.preflight.assert_not_called()

    def test_lost_worker_exposes_receipt_without_restarting(self):
        record = self.ready(); record.update(phase='launching', approved=1)
        updates.write(self.updater.receipt,record)
        self.assertEqual(self.updater.status()['attempt']['phase'],'interrupted')
        self.assertEqual(self.host.spawn_worker.call_count,1)
        self.updater.recover(record['id'])
        self.assertEqual(self.host.spawn_worker.call_args.args[1], 'recover')

    def test_discard_prepared_download_allows_new_check(self):
        record = self.ready()
        self.updater.recover(record['id'])
        self.assertEqual(self.updater.status()['attempt']['phase'],'failed')
        self.host.recover.assert_not_called()

    def test_download_spawn_failure_is_journaled(self):
        self.updater.check(True)
        self.host.spawn_worker.side_effect = OSError('No interpreter')
        with self.assertRaises(OSError): self.updater.download(self.updater.status()['candidate']['id'])
        self.assertEqual(updates.read(self.updater.receipt)['phase'], 'failed')

    def test_link_traversal_duplicates_and_devices_are_not_extracted(self):
        for name, mode in [('Task Relay.app/../escape',stat.S_IFREG), ('/outside',stat.S_IFREG),
                           ('Task Relay.app/link',stat.S_IFLNK), ('Task Relay.app/device',stat.S_IFCHR)]:
            with self.subTest(name=name):
                archive = self.root / 'bad.zip'
                with zipfile.ZipFile(archive,'w') as stream:
                    info=zipfile.ZipInfo(name); info.external_attr=(mode | 0o644)<<16
                    stream.writestr(info,'text')
                with self.assertRaises(updates.UpdateError): extract(archive,self.root/'extracted')
                self.assertFalse((self.root/'extracted').exists())

    def test_checksum_failure_never_extracts_or_stops_services(self):
        record=self.ready(); record.update(candidate=self.updater.status()['candidate'])
        adapter=MacUpdater(installed=self.root/'Task Relay.app')
        response=io.BytesIO(b'corrupt'); response.url='https://github.com/asset'
        with patch('task_relay.app_updates_macos.signer',return_value='b'*64), patch('urllib.request.urlopen',return_value=response), patch('task_relay.app_updates_macos.extract') as unpack:
            with self.assertRaisesRegex(updates.UpdateError,'checksum'): adapter.prepare(record,lambda:None)
            unpack.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);data=self.root/'data';data.mkdir()
        self.paths=Paths(self.root/'runtime',data,self.root/'work',self.root/'generated')
        self.adapter=MacUpdater(installed=self.root/'Task Relay.app',paths=self.paths)
        self.record=dict(id='test',folder=str(self.root),candidate_app=str(self.root/'candidate'),services=[],installed_digest='old')
        for method in ('validate_prepared','preflight','stop_owners','compatible','start_owners','reopen','recover'):
            setattr(self.adapter,method,Mock())
        self.adapter.data_locks=ExitStackMock
        self.adapter.services=lambda:[]

    def test_running_browser_or_sending_message_prevents_replacement(self):
        for table,status in [('browser_jobs','running'),('messages_delivery','sending'),('orchestrator_chats','processing')]:
            with self.subTest(table=table):
                self.paths.state.unlink(missing_ok=True)
                with closing(sqlite3.connect(self.paths.state)) as db:
                    db.execute('CREATE TABLE '+table+'(status TEXT)');db.execute('INSERT INTO '+table+' VALUES (?)',(status,));db.commit()
                with self.assertRaisesRegex(updates.UpdateError,'work'): self.adapter.idle()

    def test_failed_prelaunch_replacement_attempts_code_recovery(self):
        with patch.object(app_bundle,'replace_contents',side_effect=ValueError('bad signature')):
            with self.assertRaisesRegex(ValueError,'signature'): self.adapter.install(self.record,lambda:None)
        self.adapter.recover.assert_called_once()
        self.adapter.start_owners.assert_not_called()

    def test_failure_after_restart_does_not_blindly_roll_back(self):
        def fail(record,save):
            record['restart_intent']=1
            raise updates.UpdateError('No new heartbeat')
        self.adapter.start_owners.side_effect=fail
        with patch.object(app_bundle,'replace_contents'):
            with self.assertRaisesRegex(updates.UpdateError,'heartbeat'): self.adapter.install(self.record,lambda:None)
        self.adapter.recover.assert_not_called()
        self.adapter.reopen.assert_not_called()

    def test_success_restarts_before_marking_complete(self):
        phases=[]
        with patch.object(app_bundle,'replace_contents'):
            self.adapter.install(self.record,lambda:phases.append(self.record['phase']))
        self.assertEqual(phases[-1],'complete')
        self.adapter.start_owners.assert_called_once()
        self.adapter.reopen.assert_called_once()


class ExitStackMock:
    def __enter__(self):return self
    def __exit__(self,*args):return False

class NativeRecoveryFixtures(unittest.TestCase):
    def test_interrupted_replacement_restores_code_without_restoring_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); data=root/'data';data.mkdir()
            paths=Paths(root/'runtime',data,root/'work',root/'generated')
            app=root/'Task Relay.app'; (app/'Contents').mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.taskrelay.desktop'}))
            (app/'Contents/payload').write_text('previous code')
            before=app_bundle.bundle_digest(app);inode=app.stat().st_ino
            holding=root/'holding';holding.mkdir()
            (app/'Contents').rename(holding/'previous-contents')
            with closing(sqlite3.connect(paths.state)) as db:
                db.execute('CREATE TABLE history(value TEXT)');db.execute("INSERT INTO history VALUES ('newer retained record')");db.commit()
            record=dict(id='test',folder=str(root),installed=str(app),installed_inode=inode,
                        installed_digest=before,bindings=paths.environment(),services=[],holding=str(holding))
            adapter=MacUpdater(installed=app,paths=paths)
            adapter.services=lambda:[]
            adapter.stop_owners=Mock();adapter.start_owners=Mock();adapter.reopen=Mock();adapter.compatible=Mock()
            def copy(args,**kwargs):
                if str(args[0]).endswith('ditto'): shutil.copytree(args[1],args[2])
            with patch('task_relay.app_updates_macos.run',side_effect=copy), patch.object(app_bundle,'verify'):
                adapter.recover(record,lambda:None)
            self.assertEqual(record['phase'],'rolled_back')
            self.assertEqual(app_bundle.bundle_digest(app),before)
            self.assertEqual(app.stat().st_ino,inode)
            with closing(sqlite3.connect(paths.state)) as db:
                self.assertEqual(db.execute('SELECT value FROM history').fetchone()[0],'newer retained record')

    def test_stale_telegram_heartbeat_is_not_readiness(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();paths=Paths(root/'app',root,root/'work',root/'out')
            now=time.time()
            with closing(sqlite3.connect(paths.state)) as db:
                db.execute('CREATE TABLE kv(key TEXT,value TEXT)')
                for key in ('poll','scan','production','orchestrator-chat'):
                    db.execute('INSERT INTO kv VALUES (?,?)',('health:'+key,json.dumps({'last_success':now-10 if key=='scan' else now})))
                db.commit()
            adapter=MacUpdater(installed=root/'Task Relay.app',paths=paths)
            self.assertFalse(adapter.telegram_ready(now-1))
            with closing(sqlite3.connect(paths.state)) as db:
                db.execute("UPDATE kv SET value=? WHERE key='health:scan'",(json.dumps({'last_success':now}),));db.commit()
            self.assertTrue(adapter.telegram_ready(now-1))

    def test_packaged_zip_roundtrip_preserves_bundle_identity(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('package_update',Path(__file__).resolve().parents[1]/'desktop/scripts/package-update.py')
        package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();app=root/'Task Relay.app';(app/'Contents/MacOS').mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.taskrelay.desktop','CFBundleShortVersionString':'0.14.0'}))
            binary=app/'Contents/MacOS/task-relay-desktop';binary.write_text('controlled fixture');binary.chmod(0o755)
            (app/'Contents/private-folder').mkdir(mode=0o700)
            before=app_bundle.bundle_digest(app)
            with patch.object(package,'signer',return_value='b'*64), patch.object(package,'run',return_value=Mock(stdout=b'arm64\n')), \
                    patch.object(package, 'check_packaged'):
                manifest=package.package(app,root/'output','beta')
            restored=extract(root/'output'/manifest['asset'],root/'restored')
            self.assertEqual(app_bundle.bundle_digest(restored),before)
            self.assertEqual(updates.digest(root/'output'/manifest['asset']),manifest['sha256'])
            with patch.object(package, 'signer', return_value='b'*64), \
                    patch.object(package, 'check_packaged', side_effect=ValueError('Missing PDF reader')):
                with self.assertRaisesRegex(ValueError, 'Missing PDF reader'):
                    package.package(app, root/'broken-output', 'beta')
            self.assertFalse((root/'broken-output').exists())

class CompatibilityProbeTests(unittest.TestCase):
    def test_probe_preserves_signed_source_and_live_rows(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();data=root/'data';data.mkdir()
            paths=Paths(root/'current',data,root/'work',root/'out')
            app=root/'Candidate.app';runtime=app/'Contents/Resources/resources/runtime'
            python=runtime/'python/bin/python3';python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
            package=runtime/'app/task_relay';package.mkdir(parents=True)
            (package/'__init__.py').write_text('')
            bridge=package/'bridge.py'
            bridge.write_text('import sqlite3\nclass State:\n def __init__(self,path): self.db=sqlite3.connect(path)\n')
            with closing(sqlite3.connect(paths.state)) as db:
                db.execute('CREATE TABLE history(value TEXT)');db.execute("INSERT INTO history VALUES ('retained')");db.commit()
            adapter=MacUpdater(installed=root/'Installed.app',paths=paths)
            adapter.compatible(app,root/'probe')
            self.assertFalse(list(package.rglob('__pycache__')))
            bridge.write_text('import sqlite3\nclass State:\n def __init__(self,path):\n  self.db=sqlite3.connect(path)\n  self.db.execute("UPDATE history SET value=\\\'changed\\\'")\n  self.db.commit()\n')
            with self.assertRaisesRegex(updates.UpdateError,'changes saved data'):
                adapter.compatible(app,root/'incompatible-probe')
            with closing(sqlite3.connect(paths.state)) as db:
                self.assertEqual(db.execute('SELECT value FROM history').fetchone()[0],'retained')
            self.assertFalse(list(package.rglob('__pycache__')))

class CurrentSchemaTests(unittest.TestCase):
    def test_real_empty_state_is_idle_but_pending_reply_blocks_update(self):
        from task_relay.bridge import State
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();paths=Paths(root/'app',root/'data',root/'work',root/'out')
            state=State(paths.state)
            try:
                adapter=MacUpdater(installed=root/'Task Relay.app',paths=paths)
                adapter.idle()
                with state.db:
                    state.db.execute("INSERT INTO outbox_parts(event_id,part,text) VALUES ('fixture-reply',0,'fixture')")
                with self.assertRaisesRegex(updates.UpdateError,'pending replies'): adapter.idle()
                with state.db: state.db.execute('UPDATE outbox_parts SET sent=1')
                adapter.idle()
            finally: state.db.close()
