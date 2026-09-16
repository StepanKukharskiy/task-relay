"""Controlled backup cleanup race; no signing or installed application changes."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from task_relay import app_bundle as bundle


class Tests(unittest.TestCase):
    def test_verified_archive_survives_scratch_cleanup_race(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);app=root/'Task Relay.app';app.mkdir();(app/'fixture.txt').write_text('exact app bytes')
            def run(args):
                if '-c' in args:Path(args[-1]).write_bytes(b'controlled archive transport')
                else:shutil.copytree(app,Path(args[-1])/app.name)
            def cleanup(path,ignore_errors=False,**kwargs):
                self.assertTrue(ignore_errors)
                (Path(path)/'.DS_Store').write_bytes(b'Finder metadata')
            with patch.object(bundle,'run',side_effect=run),patch.object(bundle,'verify'),patch.object(tempfile.TemporaryDirectory,'_rmtree',side_effect=cleanup):
                result=bundle.archive_bundle(app,root/'backup.zip')
            self.assertEqual((root/'backup.zip').read_bytes(),b'controlled archive transport')
            self.assertEqual(result['bundle_sha256'],bundle.bundle_digest(app))
            self.assertTrue((Path(result['temporary_cleanup_pending'])/'.DS_Store').is_file())

    def test_failed_verification_still_prevents_publishing_backup(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);app=root/'Task Relay.app';app.mkdir()
            with patch.object(bundle,'verify',side_effect=ValueError('Signature invalid')),self.assertRaisesRegex(ValueError,'Signature invalid'):
                bundle.archive_bundle(app,root/'backup.zip')
            self.assertFalse((root/'backup.zip').exists())
