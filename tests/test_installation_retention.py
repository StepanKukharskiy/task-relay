"""Small recovery fixtures: no installed app, services, or live database access."""
import gzip
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from task_relay import installation_retention as retention


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / 'data'; self.data.mkdir()
        self.live = self.data / 'state.sqlite'; self.live.write_bytes(b'untouched live data')
        self.old = self.install('old', 1)
        self.new = self.install('new', 2)
        self.policy = self.data / 'installation-retention.json'
        self.policy.write_text(json.dumps({'version': 1, 'keep': 1, 'roots': [str(self.root)],
                                           'receipts': [str(self.old)]}))

    def install(self, name, stamp, phase='complete'):
        folder = self.root / name; folder.mkdir()
        db = folder / ('state-before-' + name + '.sqlite')
        with closing(sqlite3.connect(db)) as conn:
            with conn:
                conn.execute('CREATE TABLE evidence(value TEXT)')
                conn.execute('INSERT INTO evidence VALUES (?)', (name,))
        app = folder / 'previous-app.zip'
        with zipfile.ZipFile(app, 'w') as z:
            z.writestr('Task Relay.app/Contents/fixture', name)
        record = {'phase': phase, 'started_at': stamp, 'completed_at': stamp + .1,
                  'database_backup': str(db), 'app_backup': str(app),
                  'database_backup_sha256': retention._hash(db),
                  'archive': {'archive_sha256': retention._hash(app)}}
        receipt = folder / 'install-receipt.json'
        receipt.write_text(json.dumps(record))
        return receipt

    def payload(self, receipt, key):
        return Path(json.loads(receipt.read_text())[key])

    def test_success_preserves_live_receipts_and_only_new_pair(self):
        originals = {p: p.read_bytes() for p in (self.old, self.new)}
        result = retention.maintain(self.data, self.new, prune=True)
        self.assertEqual(result['status'], 'complete')
        for key in ('database_backup', 'app_backup'):
            self.assertFalse(self.payload(self.old, key).exists())
            self.assertTrue(self.payload(self.new, key).exists())
        self.assertEqual(self.live.read_bytes(), b'untouched live data')
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        self.assertEqual(retention.maintain(self.data, self.new, prune=True)['removed'], [])

    def test_registration_of_failed_install_does_not_retire_recovery(self):
        failed = self.install('failed', 3, 'needs_inspection')
        retention.maintain(self.data, failed)
        with self.assertRaisesRegex(ValueError, 'not complete'):
            retention.maintain(self.data, failed, prune=True)
        self.assertTrue(self.payload(self.old, 'app_backup').exists())
        self.assertEqual(retention.maintain(self.data, self.new, prune=True)['status'],
                         'preserved_newer_installation')

    def test_later_success_retires_registered_failed_install(self):
        failed = self.install('failed', 3, 'needs_inspection')
        retention.maintain(self.data, failed)
        latest = self.install('latest', 4, 'installed_messages_permission_required')
        result = retention.maintain(self.data, latest, prune=True)
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(self.payload(failed, 'database_backup').exists())
        self.assertTrue(failed.exists())

    def test_invalid_new_backup_keeps_every_old_file(self):
        self.payload(self.new, 'app_backup').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            retention.maintain(self.data, self.new, prune=True)
        self.assertTrue(self.payload(self.old, 'database_backup').exists())
        self.assertTrue(self.payload(self.old, 'app_backup').exists())

    def test_matching_receipt_hash_does_not_hide_invalid_zip(self):
        app = self.payload(self.new, 'app_backup'); app.write_bytes(b'not a zip')
        d = json.loads(self.new.read_text()); d['archive']['archive_sha256'] = retention._hash(app)
        self.new.write_text(json.dumps(d))
        with self.assertRaises(zipfile.BadZipFile):
            retention.maintain(self.data, self.new, prune=True)
        self.assertTrue(self.payload(self.old, 'database_backup').exists())

    def test_changed_old_pair_is_preserved(self):
        self.payload(self.old, 'database_backup').write_bytes(b'new unknown bytes')
        result = retention.maintain(self.data, self.new, prune=True)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(self.payload(self.old, 'app_backup').exists())

    def test_compressed_old_snapshot_checked_against_receipt(self):
        db = self.payload(self.old, 'database_backup')
        archived = Path(str(db) + '.gz')
        with gzip.open(archived, 'wb') as z:
            z.write(db.read_bytes())
        db.unlink()
        result = retention.maintain(self.data, self.new, prune=True)
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(archived.exists())

    def test_symlink_cannot_delete_unrelated_data(self):
        db = self.payload(self.old, 'database_backup'); db.unlink(); db.symlink_to(self.live)
        result = retention.maintain(self.data, self.new, prune=True)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.live.read_bytes(), b'untouched live data')
        self.assertTrue(self.payload(self.old, 'app_backup').exists())

    def test_nonempty_wal_preserves_old_pair(self):
        wal = Path(str(self.payload(self.old, 'database_backup')) + '-wal')
        wal.write_bytes(b'pending')
        result = retention.maintain(self.data, self.new, prune=True)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(self.payload(self.old, 'database_backup').exists())

    def test_interrupted_removal_resumes_without_losing_new_pair(self):
        app = self.payload(self.old, 'app_backup'); unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path == app:
                raise OSError('controlled interruption')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupt):
            first = retention.maintain(self.data, self.new, prune=True)
        self.assertEqual(first['status'], 'partial')
        self.assertTrue(app.exists())
        self.assertEqual(retention.maintain(self.data, self.new, prune=True)['status'], 'complete')
        self.assertTrue(self.payload(self.new, 'database_backup').exists())

    def test_disabled_policy_never_removes_files(self):
        self.policy.unlink()
        self.assertEqual(retention.maintain(self.data, self.new, prune=True)['status'], 'disabled')
        self.assertTrue(self.payload(self.old, 'database_backup').exists())

    def test_installer_reports_cleanup_failure_without_failed_installation(self):
        from tests.test_desktop_local_install import local
        with patch.object(retention, 'maintain', side_effect=OSError('controlled failure')):
            result = local.maintain_backups(self.data, self.new, prune=True)
        self.assertEqual(result['status'], 'preserved')
        self.assertTrue(self.payload(self.new, 'database_backup').exists())
