"""The macOS double-click entry point finds its folder and preserves errors."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Finder entry point')
class SetupCommandTests(unittest.TestCase):
    def run_fixture(self, installer):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = Path(__file__).resolve().parents[1] / 'Setup.command'
            shutil.copy2(source, root / 'Setup.command')
            (root / 'install.sh').write_text(installer)
            result = subprocess.run(['/bin/zsh', str(root / 'Setup.command')], cwd='/',
                                    input='\n', text=True, capture_output=True, timeout=10)
            return result, root

    def test_double_click_entry_finds_extracted_folder(self):
        result, root = self.run_fixture('pwd\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(root), result.stdout)
        self.assertIn('Your installation and saved settings remain here.', result.stdout)

    def test_install_error_stays_visible_for_retry(self):
        result, _ = self.run_fixture("echo 'fixture install error' >&2\nexit 7\n")
        self.assertEqual(result.returncode, 7)
        self.assertIn('fixture install error', result.stderr)
        self.assertIn('open Setup.command again to retry', result.stdout)


if __name__ == '__main__':
    unittest.main()
