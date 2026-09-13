"""A source service can be viewed only after an explicit desktop connection."""
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from task_relay import desktop_binding


class DesktopBindingTests(unittest.TestCase):
    def test_connect_and_disconnect_preserve_service_and_history(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        data = home / 'source-data'
        data.mkdir()
        (data / 'state.sqlite').write_bytes(b'fixture')
        paths = {'TASK_RELAY_DATA_DIR': str(data),
                 'TASK_RELAY_WORKSPACE_DIR': str(home / 'workspaces'),
                 'TASK_RELAY_GENERATED_DIR': str(home / 'generated')}
        service = home / 'Library/LaunchAgents/com.personal.codex-telegram.plist'
        service.parent.mkdir(parents=True)
        original = plistlib.dumps({'Label': desktop_binding.LABEL, 'EnvironmentVariables': paths})
        service.write_bytes(original)
        saved = home / 'Library/Application Support/Task Relay Desktop/binding.json'
        with patch.object(desktop_binding.Path, 'home', return_value=home), patch.object(desktop_binding, 'FILE', saved):
            desktop_binding.connect()
            self.assertEqual(json.loads(saved.read_text()),
                             {key: str(Path(value).resolve()) for key, value in paths.items()})
            desktop_binding.disconnect()
        self.assertFalse(saved.exists())
        self.assertEqual(service.read_bytes(), original)
        self.assertTrue((data / 'state.sqlite').exists())


if __name__ == '__main__':
    unittest.main()
