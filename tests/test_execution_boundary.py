"""Local-only source drift and process ownership; no model or native application."""
import hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from task_relay import runtime_process
from task_relay.host import HOST,UnsupportedHost
from tests import test_sourcing_records as records
from tests.test_operation_session import Script
from orchestrator.agent_loop import execute
from orchestrator import executors
from orchestrator.workers import atomic

class Boundaries(unittest.TestCase):
    def test_source_barrier_detects_shared_lazy_module_and_escaping_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'task_relay/shared.py';p.parent.mkdir();p.write_text('VALUE=1')
            frozen=dict(runtime_sources={'task_relay/shared.py':hashlib.sha256(p.read_bytes()).hexdigest()})
            runtime_process.verify_sources(frozen,root)
            p.write_text('VALUE=2')
            with self.assertRaisesRegex(ValueError,'Frozen implementation changed'):runtime_process.verify_sources(frozen,root)
            with self.assertRaisesRegex(ValueError,'Invalid frozen source'):runtime_process.verify_sources(dict(runtime_sources={'../outside':'0'*64}),root)

    def test_response_is_preserved_but_no_tool_runs_after_source_drift(self):
        fixture=records.Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        frozen=fixture.frozen;control=fixture.root/'control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(records.CONFIG,frozen['backend'])))
        script=Script([('operation_submit',dict(request_key='never',revision=0,records=[fixture.item()]))])
        with patch.object(runtime_process,'verify_sources',side_effect=[None,ValueError('Frozen implementation changed')]):
            with self.assertRaisesRegex(ValueError,'Frozen implementation changed'):execute(frozen,control,script,lambda:(records.CONFIG,frozen['backend']))
        self.assertEqual(len(script.requests),1)
        self.assertTrue((control/'api-01.response.json').exists())
        self.assertFalse(list(control.glob('tool-*.json')))
        self.assertEqual(fixture.store.progress()['committed'],0)

    def test_only_spawning_process_can_signal_its_owned_group(self):
        proc=Mock(pid=os.getpid())
        with patch('task_relay.host.os.killpg') as signal:
            with self.assertRaises(UnsupportedHost):HOST.signal_tree(proc)
            signal.assert_not_called()

    def test_real_owned_child_timeout_is_reaped_and_group_gone(self):
        proc=HOST.spawn(runtime_process.command(sys.executable,'-c','import time; time.sleep(30)'))
        try:
            HOST.stop_tree(proc,timeout=.1)
            self.assertIsNotNone(proc.poll())
            self.assertFalse(HOST.group_alive(proc.pid))
        finally:
            if proc.poll() is None:HOST.stop_tree(proc,timeout=.1)

    def test_denied_group_probe_requires_positive_absence_evidence(self):
        with patch('task_relay.host.os.killpg',side_effect=PermissionError('denied')):
            with patch('task_relay.host.subprocess.run',return_value=Mock(returncode=0,stdout='10\n20\n',stderr='')):
                self.assertTrue(HOST.group_alive(10));self.assertFalse(HOST.group_alive(30))
            for result in (Mock(returncode=1,stdout='',stderr='denied'),Mock(returncode=0,stdout='unknown',stderr='')):
                with patch('task_relay.host.subprocess.run',return_value=result):
                    with self.assertRaises(PermissionError):HOST.group_alive(30)
