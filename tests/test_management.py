"""Local management contracts; controlled fixtures, no native/network dispatch."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from task_relay import management, management_macos as mac, app_updates as updates
from task_relay.relay_paths import Paths
from tests.test_app_updates import release_fixture
from tests import test_update_retained_replies as retained_fixtures


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.paths = Paths(self.root/'code', self.root/'data', self.root/'projects', self.root/'generated')

    def call(self, argv):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = management.main(argv)
        response = json.loads(stream.getvalue())
        self.assertEqual(response['protocol'], 1)
        self.assertEqual(response['ok'], code == 0)
        return code, response

    def test_discovery_is_read_only_and_never_installs_skill(self):
        with patch.object(management, 'paths', return_value=self.paths), patch.object(mac, 'discover', return_value=[]):
            code, reply = self.call(['discover'])
        self.assertEqual(code, 0)
        self.assertEqual(reply['result']['paths']['data'], str(self.paths.data))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_malformed_saved_binding_never_falls_back_to_other_data(self):
        from task_relay import desktop_binding
        saved = self.root/'binding.json'; saved.write_text('{invalid')
        env = {k:v for k,v in os.environ.items() if not k.startswith('TASK_RELAY_')}
        with patch.dict(os.environ, env, clear=True), patch.object(desktop_binding, 'FILE', saved):
            code, reply = self.call(['discover'])
        self.assertEqual(code, 2)
        self.assertEqual(reply['error']['code'], 'JSONDecodeError')
        self.assertEqual(list(self.root.iterdir()), [saved])

    def test_explicit_binding_precedes_saved_binding(self):
        from task_relay import desktop_binding
        saved = self.root/'binding.json'; saved.write_text('{invalid')
        with patch.dict(os.environ, self.paths.environment()), patch.object(desktop_binding, 'FILE', saved):
            self.assertEqual(management.paths().data, self.paths.data)

    def test_explicit_project_override_survives_a_saved_data_binding(self):
        from task_relay import desktop_binding
        self.paths.data.mkdir(); self.paths.state.touch()
        saved = self.root/'binding.json'; saved.write_text(json.dumps(self.paths.environment()))
        env = {k:v for k,v in os.environ.items() if not k.startswith('TASK_RELAY_')}
        env['TASK_RELAY_WORKSPACE_DIR'] = str(self.root/'chosen-projects')
        with patch.dict(os.environ, env, clear=True), patch.object(desktop_binding, 'FILE', saved):
            actual = management.paths()
        self.assertEqual(actual.data, self.paths.data)
        self.assertEqual(actual.workspaces, self.root/'chosen-projects')

    @unittest.skipIf(os.name == 'nt', 'POSIX links')
    def test_dangling_binding_does_not_select_default_database(self):
        from task_relay import desktop_binding
        saved = self.root/'binding.json'; saved.symlink_to(self.root/'missing')
        env = {k:v for k,v in os.environ.items() if not k.startswith('TASK_RELAY_')}
        with patch.dict(os.environ, env, clear=True), patch.object(desktop_binding, 'FILE', saved):
            code, _ = self.call(['discover'])
        self.assertEqual(code, 2)

    def test_source_diagnostics_keep_the_selected_binding_without_app_mutations(self):
        with patch.object(management, 'paths', return_value=self.paths), patch.object(mac, 'current_app', return_value=None), patch('task_relay.diagnostics.inspect', return_value={'ok':True}) as inspect:
            code, reply = self.call(['diagnose'])
        self.assertEqual(code, 0); inspect.assert_called_once_with(self.paths)
        self.assertFalse(reply['result']['app_updates_supported'])

    def test_skill_copy_is_explicit_idempotent_and_preserves_edits(self):
        target = self.root/'skills/relay-manage'
        code, reply = self.call(['skill-install', '--destination', str(target)])
        self.assertEqual(code, 0); self.assertTrue(reply['result']['changed'])
        original = (target/'SKILL.md').read_bytes()
        code, reply = self.call(['skill-install', '--destination', str(target)])
        self.assertEqual(code, 0); self.assertFalse(reply['result']['changed'])
        (target/'SKILL.md').write_bytes(original+b'\nPersonal change\n')
        code, reply = self.call(['skill-install', '--destination', str(target)])
        self.assertEqual(code, 2)
        self.assertTrue((target/'SKILL.md').read_bytes().endswith(b'Personal change\n'))

    @unittest.skipIf(os.name == 'nt', 'POSIX links')
    def test_skill_copy_refuses_linked_parent_without_writing(self):
        actual = self.root/'actual'; actual.mkdir()
        alias = self.root/'linked'; alias.symlink_to(actual, target_is_directory=True)
        code, _ = self.call(['skill-install', '--destination', str(alias/'relay-manage')])
        self.assertEqual(code, 2); self.assertEqual(list(actual.iterdir()), [])

    def test_argument_errors_and_internal_failures_are_json_without_traceback(self):
        code, _ = self.call(['update-install'])
        self.assertEqual(code, 2)
        with patch.object(management, 'execute', side_effect=RuntimeError('private exception secret')):
            code, reply = self.call(['discover'])
        self.assertEqual(code, 2); self.assertNotIn('secret', json.dumps(reply))

    def updater(self):
        host = Mock(); host.support.return_value = dict(supported=True, installed='0.13.321', arch='arm64')
        host.worker_alive.return_value = False; host.spawn_worker.return_value.pid = 123
        release, manifest = release_fixture()
        fetch = Mock(side_effect=lambda url, limit: [release] if url == updates.API else manifest)
        updater = updates.Updater(host, self.root/'updates', fetcher=fetch)
        manager = Mock(); manager.updater = updater
        return manager, host, fetch

    def test_cli_composes_exact_candidate_install_and_recovery_without_replay(self):
        manager, host, fetch = self.updater()
        with patch.object(management, 'paths', return_value=self.paths), patch.object(mac, 'Manager', return_value=manager), patch.object(management.HOST, 'platform', 'darwin'):
            self.call(['update-status']); fetch.assert_not_called(); host.spawn_worker.assert_not_called()
            _, reply = self.call(['update-check', '--beta']); ident = reply['result']['candidate']['id']
            code, _ = self.call(['update-download', '--candidate', 'wrong']); self.assertEqual(code, 2)
            _, reply = self.call(['update-download', '--candidate', ident]); attempt = reply['result']['attempt']['id']
            record = updates.read(manager.updater.receipt); record['phase'] = 'ready'; manager.updater.save(record)
            self.assertEqual(self.call(['update-install', '--attempt', attempt])[0], 0)
            self.assertEqual(self.call(['update-install', '--attempt', attempt])[0], 2)
            self.assertEqual(host.spawn_worker.call_count, 2)
            host.worker_alive.return_value = True
            self.assertEqual(self.call(['update-recover', '--attempt', attempt])[0], 2)
            self.assertEqual(host.spawn_worker.call_count, 2)
            host.worker_alive.return_value = False
            self.assertEqual(self.call(['update-recover', '--attempt', attempt])[0], 0)
            self.assertEqual(host.spawn_worker.call_count, 3)
            self.assertEqual(host.spawn_worker.call_args.args[1], 'recover')
            self.assertTrue(updates.read(manager.updater.receipt)['approved'])

    def fake_app(self):
        app = self.root/'Task Relay.app'; (app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(CFBundleIdentifier='com.taskrelay.desktop', CFBundleShortVersionString='0.13.322')))
        package = app/mac.RUNTIME/'app'; package.mkdir(parents=True)
        return app, package

    def test_discovery_reports_older_app_without_claiming_management_available(self):
        app, package = self.fake_app()
        result = mac.describe(app)
        self.assertFalse(result['management_available']); self.assertIsNone(result['command'])
        (package.parent/'relay').write_text('fixture')
        (package.parent/'relay').chmod(0o755)
        self.assertTrue(mac.describe(app)['management_available'])
        self.assertEqual(mac.current_app(package), app)

    def test_retained_helper_is_bound_to_current_attempt_app_and_data(self):
        app, package = self.fake_app(); root = self.root/'updates'; root.mkdir()
        ident = 'a'*32; folder = root/ident; folder.mkdir()
        record = dict(id=ident, folder=str(folder), installed=str(app), bindings=self.paths.environment())
        updates.write(root/'attempt.json', record)
        with patch.object(mac.MacUpdater, 'update_folder', return_value=root):
            manager = mac.Manager(self.paths, app, package=folder/'worker/app')
            self.assertFalse(manager.installed_runtime)
            with self.assertRaisesRegex(updates.UpdateError, 'recovery only'):
                manager.require_installed_runtime()
            for wrong in (root/('b'*32)/'worker/app', package.parent/'other'):
                with self.assertRaisesRegex(updates.UpdateError, 'does not own'):
                    mac.Manager(self.paths, app, package=wrong)
            other = Paths(self.paths.install, self.root/'other', self.paths.workspaces, self.paths.generated)
            with self.assertRaisesRegex(updates.UpdateError, 'does not own'):
                mac.Manager(other, app, package=folder/'worker/app')
            # Helper recovery survives missing app Contents; validation/recovery
            # of previous code is still the updater's responsibility.
            shutil.rmtree(app/'Contents')
            self.assertFalse(mac.Manager(self.paths, app, package=folder/'worker/app').installed_runtime)

    def test_receipts_exclude_private_payloads_and_reject_traversal(self):
        app, package = self.fake_app(); root = self.root/'updates'
        with patch.object(mac.MacUpdater, 'update_folder', return_value=root):
            manager = mac.Manager(self.paths, package=package)
        ident = 'a'*32; folder = root/ident; (folder/'worker').mkdir(parents=True)
        (folder/'worker/relay').write_text('fixture')
        record = dict(id=ident, folder=str(folder), installed=str(app), bindings=self.paths.environment(),
                      phase='interrupted', error='UNEXPORTED_PAYLOAD', candidate={'secret':'UNEXPORTED_PAYLOAD'}, version='0.13.322')
        updates.write(root/'attempt.json', record); updates.write(folder/'receipt.json', record)
        result = manager.receipts(ident)
        self.assertNotIn('UNEXPORTED_PAYLOAD', json.dumps(result))
        self.assertIn('recovery_command', result['items'][0])
        self.assertIn('TASK_RELAY_DATA_DIR='+str(self.paths.data), result['items'][0]['recovery_command'])
        with self.assertRaises(ValueError): manager.receipts('../outside')
        self.assertEqual(updates.read(folder/'receipt.json'), record)

    def test_receipt_listing_is_bounded_but_old_exact_attempts_remain_readable(self):
        app, package = self.fake_app(); root = self.root/'updates'
        with patch.object(mac.MacUpdater, 'update_folder', return_value=root):
            manager = mac.Manager(self.paths, package=package)
        for index in range(51):
            ident = format(index, '032x'); folder = root/ident; folder.mkdir(parents=True)
            updates.write(folder/'receipt.json', dict(id=ident, folder=str(folder), installed=str(app), phase='failed'))
            os.utime(folder, (1000+index, 1000+index))
        result = manager.receipts()
        self.assertEqual(len(result['items']), 50); self.assertTrue(result['more'])
        self.assertNotIn('0'*32, [item['id'] for item in result['items']])
        self.assertEqual(manager.receipts('0'*32)['items'][0]['id'], '0'*32)
        self.assertFalse(manager.receipts('0'*32)['items'][0]['management_helper_available'])

    @unittest.skipIf(os.name == 'nt', 'POSIX app launcher')
    def test_launcher_uses_bundled_runtime_from_arbitrary_working_directory(self):
        runtime = self.root/'runtime with spaces'; (runtime/'python/bin').mkdir(parents=True)
        (runtime/'python/bin/python3').symlink_to(sys.executable)
        source = Path(__file__).resolve().parents[1]
        (runtime/'app').symlink_to(source, target_is_directory=True)
        launcher = runtime/'relay'; shutil.copy2(source/'desktop/scripts/relay', launcher); launcher.chmod(0o755)
        cwd = self.root/'elsewhere'; cwd.mkdir(); (cwd/'task_relay.py').write_text("raise RuntimeError('wrong import')")
        result = subprocess.run([str(launcher), 'manage', 'skill'], cwd=cwd, capture_output=True, text=True, timeout=20,
                                env={**os.environ, 'PYTHONPATH':str(cwd)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)['result']['path']).resolve(), management.SKILL.resolve())
        self.assertFalse((cwd/'__pycache__').exists())


class RetainedManagementTests(unittest.TestCase):
    setUp = retained_fixtures.Tests.setUp
    queue = retained_fixtures.Tests.queue
    retained = retained_fixtures.Tests.retained
    original = retained_fixtures.Tests.original

    def test_readonly_management_admission_keeps_real_delivery_holds_and_no_replay(self):
        self.retained(); before = self.original()
        host = mac.MacUpdater(installed=self.paths.install/'Task Relay.app', paths=self.paths)
        manager = mac.Manager.__new__(mac.Manager); manager.host = host
        manager.updater = updates.Updater(host=host, root=self.paths.data/'updates')
        host.services = lambda: []
        with patch.object(mac, 'signer', return_value='fixture'), patch('task_relay.diagnostics.inspect', return_value={'ok':True}):
            result = manager.diagnose()
        self.assertTrue(result['update_admission']['allowed'])
        self.assertFalse(manager.updater.root.exists())
        self.bridge.flush(); self.router.tick(self.pilot); self.pilot.deliver()
        self.assertEqual(before, self.original())
        self.assertEqual(self.telegram.sent, []); self.assertEqual(self.transport.sent, [])


if __name__ == '__main__': unittest.main()
