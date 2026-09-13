from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from task_relay import perplexity_browser as browser
from task_relay.host import Host,UnsupportedHost


class Tests(unittest.TestCase):
    def test_profile_is_private_separate_and_exclusively_locked(self):
        with tempfile.TemporaryDirectory() as folder:
            with browser.profile_lock(folder) as root:
                self.assertEqual(root.name,'browser-perplexity')
                self.assertEqual(root.stat().st_mode&0o777,0o700)
                with self.assertRaises(BlockingIOError):
                    with browser.profile_lock(folder):pass
            with browser.profile_lock(folder):pass
    def test_profile_symlink_and_unqualified_platform_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'elsewhere').mkdir();(root/'browser-perplexity').symlink_to(root/'elsewhere',target_is_directory=True)
            with self.assertRaises(ValueError):
                with browser.profile_lock(root):pass
            with patch.object(browser,'HOST',Host('win32')):
                with self.assertRaises(UnsupportedHost):
                    with browser.profile_lock(root):pass
    def test_browser_cli_is_lazy_and_help_needs_no_browser(self):
        from task_relay.cli import COMMANDS
        self.assertEqual(COMMANDS['browser'],'task_relay.perplexity_browser')
        with self.assertRaises(SystemExit) as result:browser.main(['--help'])
        self.assertEqual(result.exception.code,0)


if __name__=='__main__':unittest.main()
