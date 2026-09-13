"""CLI launches reuse the selected companion data without touching a service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Tests(unittest.TestCase):
    def test_selected_data_is_shared_and_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();data=root/'selected';data.mkdir();(data/'state.sqlite').write_bytes(b'fixture')
            binding=root/'binding.json';binding.write_text(json.dumps({
                'TASK_RELAY_DATA_DIR':str(data),'TASK_RELAY_WORKSPACE_DIR':str(root/'workspaces'),
                'TASK_RELAY_GENERATED_DIR':str(root/'generated')}))
            env={k:v for k,v in os.environ.items() if not k.startswith('TASK_RELAY_')}
            script="from pathlib import Path; import sys; from task_relay import desktop_binding; desktop_binding.FILE=Path(sys.argv[1]); from task_relay.cli import main; main(['paths','--field','data'])"
            def run():return subprocess.check_output([sys.executable,'-B','-c',script,str(binding)],env=env,text=True).strip()
            self.assertEqual(run(),str(data))
            env['TASK_RELAY_DATA_DIR']=str(root/'explicit')
            self.assertEqual(run(),str(root/'explicit'))
            self.assertEqual((data/'state.sqlite').read_bytes(),b'fixture')
