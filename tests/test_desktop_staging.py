"""Generated desktop sources must not retain retired files across builds."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('desktop_staging',
    Path(__file__).resolve().parents[1] / 'desktop/scripts/stage-runtime.py')
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)


class Tests(unittest.TestCase):
    def test_restage_removes_retired_source_and_preserves_python(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runtime = root / 'desktop/src-tauri/resources/runtime'
            app = runtime / 'app'
            app.mkdir(parents=True)
            (app / 'retired.py').write_text('retired')
            (app / 'desktop_bridge_entry.py').write_text('retired forwarding entry')
            (runtime / 'python').mkdir()
            (runtime / 'python/keeper').write_text('runtime')
            entry = root / 'task_relay/desktop_bridge.py'
            entry.parent.mkdir()
            entry.write_text('entry')
            inventory = {'files': [{'path': 'task_relay/desktop_bridge.py', 'release': True},
                                   {'path': 'private.txt', 'release': False}]}
            with patch.object(staging, 'ROOT', root), patch.object(staging, 'inventory', return_value=inventory):
                staging.main()
            self.assertEqual({p.name for p in app.iterdir()}, {'task_relay'})
            self.assertEqual((app / 'task_relay/desktop_bridge.py').read_text(), 'entry')
            self.assertEqual((runtime / 'python/keeper').read_text(), 'runtime')

    def test_refuses_symlinked_output_without_deleting_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / 'keeper'
            target.mkdir()
            (target / 'record').write_text('keep')
            app = root / 'desktop/src-tauri/resources/runtime/app'
            app.parent.mkdir(parents=True)
            app.symlink_to(target, target_is_directory=True)
            with patch.object(staging, 'ROOT', root), patch.object(staging, 'inventory', return_value={'files': []}):
                with self.assertRaises(ValueError):
                    staging.main()
            self.assertEqual((target / 'record').read_text(), 'keep')
