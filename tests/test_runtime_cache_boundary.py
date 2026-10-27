"""Real controller/restart/supervisor processes, with local scripted text only."""
import json,os,py_compile,shlex,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from task_relay import runtime_snapshot as snapshots,runtime_process
ROOT=Path(__file__).resolve().parents[1]
PYTHON=os.environ.get('TASK_RELAY_TEST_PINNED_PYTHON',sys.executable)

class Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.source=self.root/'source';self.source.mkdir();(self.source/'probe.py').write_text("VALUE='source'\n")
    def tearDown(self):
        target=os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE')
        if target:shutil.copytree(self.root,Path(target)/self.id())
    def cache(self,root,body="VALUE='poison'\n"):
        evil=self.root/'evil.py';evil.write_text(body)
        cache=root/'__pycache__'/('probe.'+sys.implementation.cache_tag+'.pyc');cache.parent.mkdir(exist_ok=True)
        py_compile.compile(str(evil),cfile=str(cache),invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        evil.unlink();return cache
    def test_new_and_poisoned_derived_caches_neither_change_identity_nor_execute(self):
        self.cache(self.source);receipt=snapshots.capture(self.source,self.root/'pin');root=Path(receipt['root'])
        self.assertFalse(list(root.rglob('*.pyc')))
        cache=self.cache(root);snapshots.verify(receipt)
        # Control proves this is executable poison for an ordinary interpreter.
        code='import sys;sys.path.insert(0,'+repr(str(root))+');import probe;print(probe.VALUE)'
        control=subprocess.run([PYTHON,'-I','-c',code],capture_output=True,text=True,check=True)
        self.assertEqual(control.stdout.strip(),'poison')
        for isolated in (False,True):
            result=subprocess.run(runtime_process.command(PYTHON,'-c',code,isolated=isolated),env=runtime_process.environment(),capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout.strip(),'source')
        cache.write_bytes(b'changed cache');snapshots.verify(receipt)
        cache.unlink();snapshots.verify(receipt)
    def test_source_sourceless_bytecode_unknown_files_and_cache_links_stay_pinned(self):
        receipt=snapshots.capture(self.source,self.root/'pin');root=Path(receipt['root']);cache=root/'__pycache__';cache.mkdir()
        for name in ('orphan.cpython-312.pyc','unknown.txt'):
            p=cache/name;p.write_text('added')
            with self.assertRaisesRegex(ValueError,'files changed'):snapshots.verify(receipt)
            p.unlink()
        p=cache/('probe.'+sys.implementation.cache_tag+'.pyc');p.symlink_to(root/'probe.py')
        with self.assertRaisesRegex(ValueError,'files changed'):snapshots.verify(receipt)
        p.unlink();p=root/'probe.py';p.chmod(0o600);p.write_text('changed source')
        with self.assertRaisesRegex(ValueError,'files changed'):snapshots.verify(receipt)
    def test_legacy_manifest_keeps_its_original_strict_policy(self):
        receipt=snapshots.capture(self.source,self.root/'pin');root=Path(receipt['root']);manifest=root.parent/'manifest.json'
        manifest.write_text(json.dumps(dict(version=1,files=snapshots.inventory(root))))
        receipt=dict(version=1,root=str(root),manifest_sha256=snapshots.sha(manifest))
        snapshots.verify(receipt);self.cache(root)
        with self.assertRaisesRegex(ValueError,'files changed'):snapshots.verify(receipt)
    def test_actual_launcher_controller_supervisor_worker_and_restart_preserve_delivery(self):
        receipt=snapshots.capture(self.source,self.root/'pin');(self.root/'snapshot.json').write_text(json.dumps(receipt))
        worker=self.root/'worker.py'
        worker.write_text('''import sys,json,time,wave
from pathlib import Path
assert sys.dont_write_bytecode and sys.pycache_prefix=='''+repr(os.path.abspath(os.devnull))+'''
ws=Path(sys.argv[sys.argv.index('-C')+1]);a=json.loads((ws/'.relay/ASSIGNMENT.json').read_text())
time.sleep(.3)
(ws/'output.txt').write_text('retained text from source-only worker')
result=dict(assignment_id=a['assignment_id'],summary='Controlled text',decision='delivered',instruction='',checks=[dict(criterion=1,passed=True,evidence='Scripted local text fixture')])
Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(result))
print(json.dumps(dict(type='turn.completed',usage=dict(input_tokens=1,output_tokens=1))))
''')
        cli=self.root/'fixture-cli';cli.write_text('#!/bin/sh\nexec '+shlex.quote(PYTHON)+' '+shlex.quote(str(worker))+' "$@"\n');cli.chmod(0o700)
        controller=self.root/'controller.py'
        controller.write_text('''import sys,json,time,os,wave
from pathlib import Path
sys.path.insert(0,'''+repr(str(ROOT))+''')
from task_relay import runtime_process,runtime_snapshot
from orchestrator.runtime import Runtime
from orchestrator.workers import CodexFactory,atomic
from tests.test_orchestrator import plan
runtime_process.require_source_only()
root=Path(__file__).resolve().parent
runtime_snapshot.verify(json.loads((root/'snapshot.json').read_text()))
actual=os.environ.get('TASK_RELAY_TEST_RUNTIME_IDENTITY')
if actual:
 from task_relay.native_code_host import verify
 verify(json.loads(Path(actual).read_text()))
rt=Runtime(root/'runtime',CodexFactory(root/'fixture-cli'))
if not (root/'restart-committed.json').exists():
 rt.create(plan());rt.tick('demo')
 # Simulate a derived cache emitted by a separate importer before restart.
 pin=Path(json.loads((root/'snapshot.json').read_text())['root']);cache=pin/'__pycache__';cache.mkdir(exist_ok=True)
 (cache/('probe.'+sys.implementation.cache_tag+'.pyc')).write_bytes(b'incidental cache')
 atomic(root/'restart-committed.json',dict(run='demo'))
 rt.close();raise SystemExit(75)
for _ in range(150):
 status=rt.tick('demo')
 if status['status']!='active':break
 time.sleep(.05)
atomic(root/'final.json',status)
rt.close()
assert status['status']=='completed',status
''')
        launch=self.root/'launch.py';launch.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom task_relay.controller_launch import run\nraise SystemExit(run('+repr(str(self.root))+','+repr(PYTHON)+','+repr(str(controller))+',"demo"))\n')
        # Intentionally no -B on the outer entry: the shared launcher owns it.
        env=dict(os.environ);env.pop('PYTHONDONTWRITEBYTECODE',None);env.pop('PYTHONPYCACHEPREFIX',None)
        result=subprocess.run([PYTHON,str(launch)],env=env,capture_output=True,text=True,timeout=45)
        (self.root/'launch.stdout').write_text(result.stdout);(self.root/'launch.stderr').write_text(result.stderr)
        self.assertEqual(result.returncode,0,result.stderr)
        status=json.loads((self.root/'final.json').read_text());self.assertEqual(len(status['attempts']),1)
        controls=list((self.root/'runtime/workers').glob('*'));self.assertEqual(len(controls),1)
        self.assertEqual(json.loads((controls[0]/'done.json').read_text())['exit_code'],0)
        events=[json.loads(s) for s in (self.root/'launcher-journal.jsonl').read_text().splitlines()]
        self.assertEqual([x['returncode'] for x in events if x['event']=='controller_exit'],[75,0])
        replay=subprocess.run([PYTHON,str(launch)],env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(replay.returncode,0)
        self.assertEqual(len(list((self.root/'runtime/workers').glob('*'))),1)
    def test_uncommitted_stop_never_grants_restart(self):
        from task_relay.controller_launch import run
        controller=self.root/'controller.py';controller.write_text('raise SystemExit(75)')
        with self.assertRaisesRegex(ValueError,'Missing committed'):run(self.root,PYTHON,controller,'demo')
        events=[json.loads(s) for s in (self.root/'launcher-journal.jsonl').read_text().splitlines()]
        self.assertEqual(sum(e['event']=='controller_launch' for e in events),1)

if __name__=='__main__':unittest.main()
