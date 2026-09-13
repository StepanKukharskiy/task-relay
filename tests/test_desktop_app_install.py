"""Small bundle fixtures: permission-path continuity and failed-update recovery."""
import importlib.util
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('app_install', Path(__file__).resolve().parents[1] / 'desktop/scripts/app_install.py')
install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install)


def fake_run(args):
    args = list(map(str, args))
    if args[0] == 'codesign':
        return
    if args[1] == '-c':
        app, archive = map(Path, args[-2:])
        with zipfile.ZipFile(archive, 'w') as output:
            for path in sorted(app.rglob('*')):
                output.write(path, str(path.relative_to(app.parent)))
    elif args[1] == '-x':
        with zipfile.ZipFile(args[-2]) as archive:
            archive.extractall(args[-1])
    else:
        shutil.copytree(args[1], args[2])


class AppInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installed = self.bundle('Task Relay.app', 'before')
        self.candidate = self.bundle('candidate.app', 'after')
        self.holding = self.root / '.holding'
        self.addCleanup(patch.stopall)
        patch.object(install, 'run', side_effect=fake_run).start()

    def bundle(self, name, content):
        app = self.root / name
        (app / 'Contents/MacOS').mkdir(parents=True)
        (app / 'Contents/MacOS/task-relay-desktop').write_text(content)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.taskrelay.desktop'}))
        return app

    def test_update_preserves_root_and_retains_prelaunch_rollback(self):
        inode = self.installed.stat().st_ino
        before = install.bundle_digest(self.installed)
        install.replace_contents(self.installed, self.candidate, self.holding)
        self.assertEqual(inode, self.installed.stat().st_ino)
        self.assertEqual(install.bundle_digest(self.candidate), install.bundle_digest(self.installed))
        install.restore_contents(self.installed, self.holding)
        self.assertEqual(before, install.bundle_digest(self.installed))
        self.assertEqual(inode, self.installed.stat().st_ino)

    def test_failed_installed_signature_restores_original(self):
        before = install.bundle_digest(self.installed)
        with patch.object(install, 'verify', side_effect=[None, ValueError('bad signature'), None]):
            with self.assertRaisesRegex(ValueError, 'bad signature'):
                install.replace_contents(self.installed, self.candidate, self.holding)
        self.assertEqual(before, install.bundle_digest(self.installed))

    def test_interruption_between_moves_is_recoverable(self):
        before = install.bundle_digest(self.installed)
        rename = Path.rename
        def interrupted(path, destination):
            if path.name == 'candidate-contents':
                raise KeyboardInterrupt()
            return rename(path, destination)
        with patch.object(Path, 'rename', interrupted):
            with self.assertRaises(KeyboardInterrupt):
                install.replace_contents(self.installed, self.candidate, self.holding)
        self.assertEqual(before, install.bundle_digest(self.installed))

    def test_linked_candidate_preserves_installed(self):
        before = install.bundle_digest(self.installed)
        (self.candidate / 'Contents/link').symlink_to(self.installed)
        with self.assertRaisesRegex(ValueError, 'Linked'):
            install.replace_contents(self.installed, self.candidate, self.holding)
        self.assertEqual(before, install.bundle_digest(self.installed))

    def test_archive_roundtrip_before_retirement(self):
        receipt = install.archive_bundle(self.installed, self.root / 'recovery/app.zip')
        self.assertTrue(self.installed.exists())
        install.retire_archived_bundle(self.installed, receipt)
        self.assertFalse(self.installed.exists())
        self.assertTrue(Path(receipt['archive']).is_file())

    def test_changed_archive_cannot_authorize_deletion(self):
        receipt = install.archive_bundle(self.installed, self.root / 'app.zip')
        Path(receipt['archive']).write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            install.retire_archived_bundle(self.installed, receipt)
        self.assertTrue(self.installed.exists())

    def test_archive_cannot_overwrite_recovery(self):
        archive = self.root / 'app.zip'
        archive.write_text('previous receipt')
        with self.assertRaisesRegex(ValueError, 'overwritten'):
            install.archive_bundle(self.installed, archive)
        self.assertEqual('previous receipt', archive.read_text())

    def test_failed_archive_verification_preserves_app_and_destination(self):
        archive = self.root / 'app.zip'
        with patch.object(install, 'verify', side_effect=[None, ValueError('bad archived signature')]):
            with self.assertRaisesRegex(ValueError, 'bad archived'):
                install.archive_bundle(self.installed, archive)
        self.assertTrue(self.installed.exists())
        self.assertFalse(archive.exists())
