"""Real package entry points with private fixture paths; no provider submissions."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackageEntrypoints(unittest.TestCase):
    def test_module_children_ignore_unrelated_bare_modules_and_keep_data_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            data = root / 'data'
            env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
                   'TASK_RELAY_DATA_DIR': str(data),
                   'TASK_RELAY_WORKSPACE_DIR': str(root / 'projects'),
                   'TASK_RELAY_GENERATED_DIR': str(root / 'generated')}
            # A different working directory can contain unrelated modules with the
            # old names. Canonical imports must not execute those files.
            for name in ('bridge', 'gemini', 'backends', 'providers', 'api_providers', 'file_tools', 'relay_paths'):
                (root / (name + '.py')).write_text("raise RuntimeError('Unrelated bare module imported')\n")
            for module in ('provider_runner', 'gemini_runner', 'api_runner'):
                with self.subTest(module=module):
                    result = subprocess.run([sys.executable, '-B', '-m', 'task_relay.' + module,
                                             str(data / 'state.sqlite'), 'absent-fixture', str(os.getpid())],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            check = subprocess.run([sys.executable, '-B', '-c',
                "from task_relay.bridge import State; from task_relay.relay_paths import PATHS; "
                "s=State(PATHS.state); assert s.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0]==0; "
                "assert s.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0]==0; s.db.close()"],
                cwd=root, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            bridge = subprocess.run([sys.executable, '-B', '-m', 'task_relay.desktop_bridge', 'unknown-fixture-action'],
                                    input='{}', cwd=root, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(bridge.returncode, 1, bridge.stdout + bridge.stderr)
            self.assertEqual(json.loads(bridge.stdout), {'ok': False, 'error': 'Unknown setup action.'})
            self.assertTrue((data / 'state.sqlite').is_file())
            self.assertFalse((root / 'private').exists())


if __name__ == '__main__':
    unittest.main()
