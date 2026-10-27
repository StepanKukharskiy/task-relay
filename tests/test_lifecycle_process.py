"""The reference correction/partial graph across actual controller processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from task_relay import runtime_process

ROOT=Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def test_common_launcher_restart_then_corrections_and_partial_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            controller=root/'controller.py'
            controller.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom tests.lifecycle_controller import main\nsys.argv.append('+repr(str(root))+')\nraise SystemExit(main())\n')
            launcher=root/'launch.py'
            launcher.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom task_relay.controller_launch import run\nraise SystemExit(run('+repr(str(root))+','+repr(sys.executable)+','+repr(str(controller))+',"lifecycle"))\n')
            try:
                command=runtime_process.command(sys.executable,launcher)
                r=subprocess.run(command,env=runtime_process.environment(),capture_output=True,text=True,timeout=90)
                (root/'stdout.log').write_text(r.stdout);(root/'stderr.log').write_text(r.stderr)
                self.assertEqual(r.returncode,0,r.stderr)
                final=json.loads((root/'final.json').read_text())
                self.assertEqual(final['status'],'uncertain');self.assertFalse(final['complete'])
                self.assertEqual(len(final['dispatches']),len(set(final['dispatches'])))
                labels={v['task']:v['review_status'] for v in final['delivery']['candidates']}
                self.assertEqual(labels,{'v1':'requires_attention','v2':'requires_attention','v3':'reviewed','slow':'unreviewed'})
                journal=[json.loads(v) for v in (root/'launcher-journal.jsonl').read_text().splitlines()]
                self.assertEqual([v['returncode'] for v in journal if v['event']=='controller_exit'],[75,0])
                before=(root/'final.json').read_bytes()
                replay=subprocess.run(command,env=runtime_process.environment(),capture_output=True,text=True,timeout=10)
                self.assertNotEqual(replay.returncode,0)
                self.assertEqual((root/'final.json').read_bytes(),before)
            finally:
                target=os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE')
                if target:shutil.copytree(root,Path(target)/self.id())


if __name__=='__main__':unittest.main()
