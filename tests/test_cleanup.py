from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from task_relay import cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'relay'
        self.root.mkdir()
        self.paths = SimpleNamespace(install=self.root, data=self.root / 'private', state=self.root / 'private/state.sqlite')

    def write(self, name, data=b'fixture'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_only_listed_regenerable_files_are_removed(self):
        cache = self.write('task_relay/__pycache__/module.pyc')
        build = self.write('build/lib/module.py')
        protected = [self.write(p) for p in ('task_relay/module.py', 'dist/release.whl',
                     'projects/__pycache__/artifact.pyc', 'private/orchestrator/__pycache__/artifact.pyc',
                     'outputs/__pycache__/evidence.pyc', 'task_relay/__pycache__/guide.md')]
        manifest, _ = cleanup.plan(self.paths, builds=True)
        added = self.write('task_relay/__pycache__/new.pyc')
        result = cleanup.apply(manifest, self.paths)
        self.assertEqual(result['removed'], 2)
        self.assertFalse(cache.exists())
        self.assertFalse(build.exists())
        self.assertTrue(all(p.exists() for p in [*protected, added]))
        self.assertEqual(cleanup.apply(manifest, self.paths)['removed'], 0)

    def test_changed_file_or_symlink_is_skipped(self):
        changed = self.write('__pycache__/changed.pyc')
        swapped = self.write('__pycache__/swapped.pyc')
        source = self.write('important.py')
        manifest, _ = cleanup.plan(self.paths)
        changed.write_bytes(b'new-version')
        swapped.unlink()
        swapped.symlink_to(source)
        result = cleanup.apply(manifest, self.paths)
        self.assertEqual(result['removed'], 0)
        self.assertEqual(result['skipped'], 2)
        self.assertEqual(source.read_bytes(), b'fixture')
        self.assertEqual(changed.read_bytes(), b'new-version')

    def test_builds_are_opt_in_and_external_symlink_is_not_followed(self):
        build = self.write('build/generated.py')
        outside = Path(self.tmp.name).resolve() / 'outside/__pycache__'
        outside.mkdir(parents=True)
        external = outside / 'a.pyc'
        external.write_bytes(b'outside')
        (self.root / 'linked').symlink_to(outside.parent, target_is_directory=True)
        manifest, report = cleanup.plan(self.paths)
        self.assertEqual(report['files'], [])
        cleanup.apply(manifest, self.paths)
        self.assertTrue(external.exists())
        self.assertTrue(build.exists())

    def test_only_verified_duplicate_retirements_are_removed(self):
        from tests.test_messages_storage import MigrationTests
        fixture = MigrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        evidence = fixture.migrate()
        data = fixture.root.resolve()
        install = data / 'installation'
        install.mkdir()
        paths = SimpleNamespace(install=install, data=data, state=data / 'state.sqlite')
        unique = data / 'backups/unique.sqlite'
        unique.write_bytes(b'unique recovery evidence')
        manifest, report = cleanup.plan(paths)
        self.assertEqual(len(report['files']), 2)
        self.assertEqual(cleanup.apply(manifest, paths)['removed'], 2)
        self.assertTrue(unique.exists())
        self.assertTrue(all(Path(entry['backup']).exists() for entry in evidence['sources']))
        self.assertTrue(paths.state.exists())
        fixture.migrate()  # Retrying consolidation does not require redundant raw copies.


if __name__ == '__main__':
    unittest.main()
