"""Real subprocess lifecycle with a deterministic local fake CLI, no model calls."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from orchestrator.runtime import Runtime
from orchestrator.workers import CodexFactory
from tests.test_orchestrator import plan, task


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        cli = self.root / 'fake-codex'
        cli.write_text('#!' + sys.executable + '''
import json,sys,time
from pathlib import Path
args=sys.argv
ws=Path(args[args.index('-C')+1])
a=json.loads((ws/'.relay/ASSIGNMENT.json').read_text())
print(json.dumps({'type':'thread.started','thread_id':'fixture-session'}),flush=True)
if a['instruction']=='wait': time.sleep(20)
if a['instruction']=='progress':
    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':30,'output_tokens':5}}),flush=True)
    print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':'private fixture command'}}),flush=True)
    time.sleep(3)
if a['instruction']=='tools':
    for i in range(4): print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)
    time.sleep(20)
for out in a['outputs']:
    p=ws/out['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_text('real child output')
result={'assignment_id':a['assignment_id'],'summary':'Done','decision':'delivered','instruction':'',
        'checks':[{'criterion':i,'passed':True,'evidence':'fixture'} for i in range(1,len(a['criteria'])+1)]}
Path(args[args.index('-o')+1]).write_text(json.dumps(result))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':17,'output_tokens':9}}),flush=True)
''')
        cli.chmod(0o700); self.cli = cli; self.factory = CodexFactory(cli)
        self.rt = Runtime(self.root / 'runtime', self.factory)

    def tearDown(self):
        for control in (self.root / 'runtime/workers').glob('*'):
            if not (control / 'done.json').exists():
                self.factory.cancel({'id':control.name,'control':str(control)})
        for child in self.factory.children:
            child.wait(timeout=10)
        self.rt.db.close(); self.temp.cleanup()

    def until(self, predicate, seconds=10):
        stop = time.monotonic() + seconds
        while time.monotonic() < stop:
            status = self.rt.tick('demo')
            if predicate(status):
                return status
            time.sleep(.05)
        self.fail('Worker did not settle')

    def test_factory_creates_session_collects_files_and_usage_after_scheduler_restart(self):
        self.rt.create(plan()); self.rt.tick('demo')
        aid = self.rt.task('demo', 'produce')['latest']
        self.rt.db.close(); self.rt = Runtime(self.root / 'runtime', CodexFactory(self.cli))
        status = self.until(lambda s: s['status'] == 'completed')
        receipt = json.loads(status['attempts'][0]['receipt'])
        self.assertEqual(receipt['thread_id'], 'fixture-session')
        self.assertEqual(receipt['usage'], [{'input_tokens':17,'output_tokens':9}])
        self.assertEqual(len(status['attempts']), 1)
        self.factory.inspect({'id':aid,'control':str(self.root/'runtime/workers'/aid)})

    def test_cancel_is_confirmed_by_process_owner(self):
        t = task(); t['instruction'] = 'wait'; self.rt.create(plan([t])); self.rt.tick('demo')
        self.until(lambda s: s['tasks'][0]['status']=='running')
        self.rt.cancel('demo')
        self.until(lambda s: s['tasks'][0]['status']=='cancelled')
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='output_delivered'").fetchone()[0], 0)

    def test_wall_clock_limit_kills_child(self):
        t = task(limits={'seconds':1}); t['instruction']='wait'
        self.rt.create(plan([t])); self.rt.tick('demo')
        result=self.until(lambda s: s['status']=='blocked')
        self.assertEqual(json.loads(result['attempts'][0]['receipt'])['reason'], 'time_limit')

    def test_tool_limit_kills_child(self):
        t=task(limits={'tool_calls':1});t['instruction']='tools'
        self.rt.create(plan([t])); self.rt.tick('demo')
        result=self.until(lambda s:s['status']=='blocked')
        self.assertEqual(json.loads(result['attempts'][0]['receipt'])['reason'], 'tool_limit')

    def test_progress_snapshot_reports_usage_without_copying_command_content(self):
        t=task();t['instruction']='progress';self.rt.create(plan([t]));self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest']
        progress=self.root/'runtime/workers'/aid/'progress.json'
        self.until(lambda _:progress.exists() and json.loads(progress.read_text()).get('tool_calls')==1)
        value=json.loads(progress.read_text())
        self.assertEqual(value['token'],aid)
        self.assertEqual(value['usage'],[{'input_tokens':30,'output_tokens':5}])
        self.assertEqual(value['activity'],'running_command')
        self.assertNotIn('private fixture command',progress.read_text())
        self.until(lambda s:s['status']=='completed')

    def test_progress_write_failure_does_not_fail_worker(self):
        t=task();t['instruction']='progress';self.rt.create(plan([t]));self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest']
        progress=self.root/'runtime/workers'/aid/'progress.json'
        if progress.exists():progress.unlink()
        progress.mkdir()
        result=self.until(lambda s:s['status']=='completed')
        receipt=json.loads(result['attempts'][0]['receipt'])
        self.assertIsNone(receipt['reason'])
        self.assertEqual(receipt['exit_code'],0)


if __name__ == '__main__':
    unittest.main()
