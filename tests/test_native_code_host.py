"""Opt-in fixed native sandbox probes. No provider, browser or native app work."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from task_relay import native_code_host as host,code_runtime


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('TASK_RELAY_TEST_NATIVE_CODE')=='1',
                     'Requires explicit native macOS sandbox qualification')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='relay-test-é ');self.addCleanup(self.temporary.cleanup)
        self.folder=Path(self.temporary.name).resolve();(self.folder/'inputs').mkdir()
        (self.folder/'outside.txt').write_text('outside fixture')
        (self.folder/'inputs/source.txt').write_text('exact source')
        self.runtime=host.identity()

    def test_qualification_checks_formats_and_boundaries_without_live_settings(self):
        with patch.object(code_runtime,'path',return_value=self.folder/'settings.json'):
            status=code_runtime.configure(True)
            self.assertTrue(status['enabled']);self.assertEqual(code_runtime.available()['runtime'],self.runtime)
            if os.environ.get('TASK_RELAY_REQUIRE_DOCUMENTS')=='1':
                for name in ('docx','pptx','pypdf','reportlab','openpyxl','PIL'):
                    self.assertTrue(status['tools'][name]['available'],name)
                    self.assertIn(status['tools'][name]['checked'],('save/reopen','save'))
            print('Verified native tool report: '+json.dumps(status['tools'],sort_keys=True))
            code_runtime.configure(False)
            with self.assertRaises(ValueError):code_runtime.available()

    def test_filesystem_environment_and_subprocess_denials(self):
        code='''import json,os,pathlib,subprocess
root=pathlib.Path(os.environ['RELAY_OUTPUTS']);inputs=pathlib.Path(os.environ['RELAY_INPUTS'])
assert inputs.joinpath('source.txt').read_text()=='exact source'
assert 'TASK_RELAY_TEST_SECRET' not in os.environ
checks={}
for name,path in [('source',inputs/'source.txt'),('outside',inputs.parent/'outside.txt')]:
    try:path.write_text('changed');checks[name]=False
    except PermissionError:checks[name]=True
try:subprocess.run(['/usr/bin/true']);checks['spawn']=False
except PermissionError:checks['spawn']=True
(root/'result.json').write_text(json.dumps(checks))
'''
        with patch.dict(os.environ,{'TASK_RELAY_TEST_SECRET':'fixture-secret'}):
            result=host.run(self.runtime,self.folder,code,5,1000000)
        self.assertEqual(result['returncode'],0,result['log'])
        self.assertEqual(json.loads((self.folder/'outputs/result.json').read_text()),{'source':True,'outside':True,'spawn':True})
        self.assertEqual((self.folder/'outside.txt').read_text(),'outside fixture')
        self.assertEqual((self.folder/'inputs/source.txt').read_text(),'exact source')

    def assert_stopped(self,pid):
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_parent_sigkill_closes_lifetime_pipe_and_reaps_code_child(self):
        code="import os,pathlib,time\npathlib.Path(os.environ['RELAY_OUTPUTS']).joinpath('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)"
        parent_code='from task_relay import native_code_host as h\nfrom pathlib import Path\nh.run(h.identity(),Path('+repr(str(self.folder))+'),'+repr(code)+',60,1000000)'
        parent=subprocess.Popen([sys.executable,'-B','-c',parent_code],cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            marker=self.folder/'outputs/child.pid';deadline=time.monotonic()+10
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(marker.exists());pid=int(marker.read_text())
            parent.kill();parent.wait(timeout=5)
            outcome=self.folder/'guard-outcome.json';deadline=time.monotonic()+5
            while not outcome.exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(outcome.exists());self.assertIn('owner exited',json.loads(outcome.read_text())['error'])
            self.assert_stopped(pid)
        finally:
            if parent.poll() is None:parent.kill()
            parent.wait(timeout=5)

    def test_cancel_terminates_the_owned_child(self):
        code="import os,pathlib,time\npathlib.Path(os.environ['RELAY_OUTPUTS']).joinpath('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)"
        marker=self.folder/'outputs/child.pid'
        with self.assertRaisesRegex(ValueError,'cancelled'):host.run(self.runtime,self.folder,code,60,1000000,marker.exists)
        self.assert_stopped(int(marker.read_text()))

    def test_wall_clock_deadline_stops_sleeping_code(self):
        start=time.monotonic()
        with self.assertRaisesRegex(ValueError,'time limit'):host.run(self.runtime,self.folder,'import time;time.sleep(60)',1,1000000)
        self.assertLess(time.monotonic()-start,8)

    def test_substituted_log_cannot_read_host_file(self):
        code="import os,pathlib\nroot=pathlib.Path(os.environ['RELAY_OUTPUTS'])\n(root/'runtime.log').unlink()\n(root/'runtime.log').symlink_to(root.parent/'outside.txt')"
        with self.assertRaises((ValueError,OSError)):host.run(self.runtime,self.folder,code,5,1000000)
        self.assertEqual((self.folder/'outside.txt').read_text(),'outside fixture')

    def test_exact_binary_delivery_and_independent_review_handoff(self):
        from orchestrator.code_worker import CodeFiles
        import hashlib
        with patch.object(code_runtime,'path',return_value=self.folder/'settings.json'):
            code_runtime.configure(True);backend={'type':'qwen-code','model':'fixture','runtime':code_runtime.available()['id']}
            workspace=self.folder/'work';workspace.mkdir();control=self.folder/'control';control.mkdir()
            raw=b'amount\n3\n4\n';(workspace/'source.csv').write_bytes(raw)
            assignment={'assignment_id':'producer','workspace':str(workspace),'backend':backend,
                'limits':{'seconds':30,'output_bytes':1000000},
                'inputs':[{'path':'source.csv','sha256':hashlib.sha256(raw).hexdigest()}],
                'outputs':[{'path':'result.xlsx'}]}
            producer=CodeFiles(assignment,control)
            result=producer.run({'seconds':10,'code':'''from __future__ import annotations
import csv,os,pathlib,openpyxl
source=pathlib.Path(os.environ['RELAY_INPUTS'])/'source.csv'
total=sum(int(r['amount']) for r in csv.DictReader(source.open()))
book=openpyxl.Workbook();book.active['A1']=total
book.save(pathlib.Path(os.environ['RELAY_OUTPUTS'])/'result.xlsx')'''})
            self.assertEqual(result['returncode'],0,result['log'])
            binary=(workspace/'result.xlsx').read_bytes();review_control=self.folder/'review-control';review_control.mkdir()
            review={**assignment,'assignment_id':'reviewer','inputs':[{'path':'result.xlsx','sha256':hashlib.sha256(binary).hexdigest()}],
                    'outputs':[{'path':'review.json'}]}
            reviewer=CodeFiles(review,review_control)
            result=reviewer.run({'seconds':10,'code':'''import os,json,pathlib,openpyxl
book=openpyxl.load_workbook(pathlib.Path(os.environ['RELAY_INPUTS'])/'result.xlsx')
assert book.active['A1'].value==7
(pathlib.Path(os.environ['RELAY_OUTPUTS'])/'review.json').write_text(json.dumps({'total':7,'verified':True}))'''})
            self.assertEqual(result['returncode'],0,result['log'])
            self.assertEqual(json.loads((workspace/'review.json').read_text()),{'total':7,'verified':True})
            self.assertEqual((workspace/'source.csv').read_bytes(),raw)
            self.assertEqual((workspace/'result.xlsx').read_bytes(),binary)


if __name__=='__main__':unittest.main()
