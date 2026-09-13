"""Source updating must preserve companion code, services and recovery receipts."""
from contextlib import redirect_stderr
from dataclasses import replace
import io
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from task_relay import host_updates, releases, updates
from task_relay.host import Host
from task_relay.relay_paths import Paths


class Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        install = self.root / 'Task Relay.app/Contents/Resources/resources/runtime/app'
        install.mkdir(parents=True)
        self.paths = Paths(install, self.root / 'data', self.root / 'projects', self.root / 'generated')
        self.addCleanup(patch.stopall)
        patch.object(host_updates, 'HOST', Host('darwin')).start()
        patch.object(Path, 'home', return_value=self.root).start()

    def test_mutating_cli_commands_refuse_before_fetch_or_saved_state(self):
        for args in (['apply', '--version', '0.13.0'], ['plan', '--version', '0.13.0'],
                     ['rollback'], ['recover']):
            with self.subTest(command=args[0]), patch.object(updates, 'PATHS', self.paths), \
                    patch.object(updates.sys, 'argv', ['update', *args]), \
                    patch.object(releases, 'fetch') as fetch, patch.object(updates, 'load') as load, \
                    redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit):
                    updates.main()
                self.assertIn('source updater cannot update Task Relay.app', error.getvalue())
                fetch.assert_not_called()
                load.assert_not_called()
            self.assertFalse(self.paths.data.exists())
            self.assertFalse((self.root / 'data-releases').exists())

    def test_direct_entry_points_preserve_history_and_interrupted_receipt(self):
        self.paths.data.mkdir()
        history = self.paths.data / 'history.txt'
        history.write_text('Exact original request and selected artifact version 2')
        receipt = self.paths.data / 'updates/activation.json'
        receipt.parent.mkdir()
        receipt.write_text('{"phase":"starting","nonce":"fixture-uncertain"}')
        before = {p.relative_to(self.paths.data): p.read_bytes()
                  for p in self.paths.data.rglob('*') if p.is_file()}
        downloader, service = Mock(), Mock()
        operations = (lambda: updates.prepare({}, self.paths, downloader),
                      lambda: updates.migration_plan({}, self.paths),
                      lambda: updates.activate({}, self.paths, service),
                      lambda: updates.recover(self.paths))
        for operation in operations:
            with self.assertRaisesRegex(ValueError, 'source updater cannot update Task Relay.app'):
                operation()
        downloader.assert_not_called()
        service.assert_not_called()
        self.assertEqual(before, {p.relative_to(self.paths.data): p.read_bytes()
                                 for p in self.paths.data.rglob('*') if p.is_file()})

    def test_alias_and_bundled_python_cannot_be_selected_as_source_target(self):
        alias = self.root / 'runtime-alias'
        alias.symlink_to(self.paths.install, target_is_directory=True)
        for install, python in ((alias, '/fixture/python'),
                                (self.root / 'source', self.paths.install.parent / 'python/bin/python3')):
            with self.subTest(install=install), self.assertRaisesRegex(ValueError, 'app bundle'):
                updates.verify_target({'install': str(install), 'python': str(python)})

    def test_source_checkout_cannot_take_over_matching_companion_service(self):
        paths = replace(self.paths, install=self.root / 'source')
        spec = {'Label': host_updates.LABEL, 'TaskRelayDesktopOwner': 'task-relay-desktop-v1',
                'WorkingDirectory': str(paths.install),
                'ProgramArguments': ['/fixture/python', str(paths.install / 'bridge.py'), 'run'],
                'EnvironmentVariables': paths.environment()}
        service = host_updates.Service(paths, paths.install)
        service.path.parent.mkdir(parents=True)
        raw = plistlib.dumps(spec)
        service.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'companion owns'):
            updates.prepare({}, paths, Mock())
        # Even a matching legacy argv must not override the explicit owner.
        with self.assertRaisesRegex(ValueError, 'companion owns'):
            service.capture()
        self.assertEqual(service.path.read_bytes(), raw)
        self.assertFalse(paths.data.exists())

    def test_app_start_does_not_redirect_to_a_prior_source_release(self):
        from task_relay import relay_paths
        with patch.object(updates, 'PATHS', self.paths), patch.object(relay_paths, 'CHECKOUT', False), \
                patch.object(updates, 'load') as load, patch.object(updates.os, 'execve') as execute:
            updates.redirect(['telegram', 'run'])
            load.assert_not_called()
            execute.assert_not_called()

    def test_metadata_checks_remain_available_and_notices_distinguish_source(self):
        release = {'version': '0.13.0', 'url': releases.WEB + 'tag/v0.13.0'}
        with patch.object(updates, 'PATHS', self.paths), \
                patch.object(updates.sys, 'argv', ['update', 'check']), \
                patch.object(releases, 'Store') as store, patch.object(releases, 'cached', return_value={}), \
                patch('sys.stdout', new_callable=io.StringIO):
            updates.main()
            store.return_value.check.assert_called_once_with(force=True)
        with patch.object(releases, 'PATHS', self.paths):
            self.assertNotIn('update apply', releases.release_notice(release))
            self.assertIn('source package', releases.release_notice(release))
        with patch.object(releases, 'PATHS', replace(self.paths, install=self.root / 'source')):
            self.assertIn('update apply --version 0.13.0', releases.release_notice(release))


if __name__ == '__main__':
    unittest.main()
