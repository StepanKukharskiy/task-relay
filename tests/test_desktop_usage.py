"""Desktop usage keeps missing measurements and incomplete storage scans honest."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import time
import unittest

from task_relay.desktop_usage import _storage, breakdown, summary
from task_relay.relay_paths import Paths
from task_relay import usage_tracker


class DesktopUsageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root / 'app', root / 'data', root / 'workspaces', root / 'generated')
        self.paths.data.mkdir()
        self.paths.workspaces.mkdir()
        self.paths.generated.mkdir()

    def test_recorded_tokens_and_storage_exclude_symlink_targets(self):
        with closing(sqlite3.connect(self.paths.state)) as db:
            with db:
                usage_tracker.initialize(db)
                db.execute('CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                db.execute("INSERT INTO kv VALUES ('usage_tracking_enabled','true')")
                usage_tracker.record(db, 'measured', 'relay_api', 'gemini', 'fixture', None, None,
                                     time.time(), {'input_tokens': 20, 'output_tokens': 5})
                usage_tracker.record(db, 'unknown', 'relay_api', 'openrouter', 'fixture', None, None,
                                     time.time(), {})
                usage_tracker.record(db, 'planner', 'relay_planner', 'gemini', 'fixture', None, None,
                                     time.time(), {'input_tokens': 7, 'output_tokens': 3})
                usage_tracker.record(db, 'local', 'local_codex', 'codex', 'fixture', None, None,
                                     time.time(), {'input_tokens': 100, 'output_tokens': 10})
        (self.paths.workspaces / 'note.txt').write_text('local work')
        external = self.paths.install / 'outside.bin'
        external.parent.mkdir()
        external.write_bytes(b'x' * 4_000_000)
        (self.paths.generated / 'outside-link').symlink_to(external)
        (self.paths.data.parent / 'source_inventory.json').write_text('{}')
        (self.paths.data.parent / 'pyproject.toml').write_text('')
        (self.paths.data.parent / 'task_relay').mkdir()

        result = summary(self.paths)
        self.assertEqual(result['tokens']['total'], 145)
        self.assertEqual(result['tokens']['input'], 127)
        self.assertEqual(result['tokens']['output'], 18)
        self.assertEqual(result['tokens']['unmeasured'], 1)
        self.assertEqual(result['tokens']['relay_total'], 35)
        self.assertEqual(result['tokens']['relay_api_total'], 25)
        self.assertEqual(result['tokens']['relay_unmeasured'], 1)
        self.assertTrue(result['tokens']['indexing_enabled'])
        self.assertTrue(result['storage']['complete'])
        self.assertLess(result['storage']['bytes'], external.stat().st_size)
        self.assertTrue(result['source_folder']['complete'])
        self.assertGreater(result['source_folder']['bytes'], result['storage']['bytes'])
        categories = breakdown(self.paths)
        self.assertTrue(categories['complete'])
        self.assertEqual(sum(item['bytes'] for item in categories['categories']), result['source_folder']['bytes'])

    def test_missing_ledger_and_budgeted_scan_are_not_presented_as_zero_or_exact(self):
        (self.paths.data / 'one.txt').write_text('a')
        (self.paths.data / 'two.txt').write_text('b')
        self.assertIsNone(summary(self.paths)['tokens']['total'])
        self.assertIsNone(summary(self.paths)['source_folder'])
        scan = _storage(self.paths, max_entries=1)
        self.assertFalse(scan['complete'])
        self.assertTrue(any(not folder['complete'] for folder in scan['folders']))
        self.assertFalse(breakdown(self.paths, max_entries=1)['complete'])


if __name__ == '__main__':
    unittest.main()
