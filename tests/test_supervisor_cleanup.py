"""Controlled process fixtures: cleanup failures retain receipts without replay."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from orchestrator import supervisor
from orchestrator.contracts import digest
from orchestrator.workers import CodexFactory
from tests import test_orchestrator as fixtures


class SupervisorTests(unittest.TestCase):
    def run_failure(self, platform='darwin', spawn_error=False, close_error=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'host_runtime.py').write_bytes(b'fixture')
            support={}
            if platform=='win32':
                (root/'host_windows.py').write_bytes(b'windows fixture')
                support={'host_windows.py':hashlib.sha256(b'windows fixture').hexdigest()}
            spec=dict(token='exact-token',host_support_sha256=hashlib.sha256(b'fixture').hexdigest(),
                      host_support_files=support,registered_command=['fixture'],workspace=folder,
                      limits=dict(seconds=0,tool_calls=1))
            (root/'launch.json').write_text(json.dumps(spec));(root/'prompt.txt').write_text('Exact prompt')
            proc=Mock(pid=12345,returncode=0)
            proc.poll.return_value=0 if close_error else None
            host=Mock(platform=platform)
            host.process_identity.return_value={'fixture':True}
            host.spawn.return_value=proc
            if spawn_error:host.spawn.side_effect=OSError('spawn failed')
            elif close_error:proc.close.side_effect=PermissionError('close denied')
            else:host.stop_tree.side_effect=PermissionError('termination denied')
            with patch.object(supervisor,'HOST',host),patch('sys.argv',['supervisor',folder,'exact-token']):
                supervisor.main()
            receipt=json.loads((root/'done.json').read_text())
            inspected=CodexFactory(executable='unused').inspect(dict(id='exact-token',control=folder))
            if spawn_error:
                self.assertEqual(inspected['status'],'finished');host.stop_tree.assert_not_called()
            else:
                self.assertEqual(inspected['status'],'uncertain')
                self.assertEqual(receipt['child_pid'],12345)
                self.assertIn('denied',receipt['cleanup_error'])
                self.assertEqual(host.stop_tree.call_count,0 if close_error else 1)
            self.assertEqual(receipt['token'],'exact-token')
            self.assertEqual(receipt['usage'],[])
            return receipt

    def test_permission_failure_writes_uncertain_receipt_without_second_stop(self):
        self.assertEqual(self.run_failure()['stop_reason'],'time_limit')

    def test_windows_close_failure_cannot_claim_completion(self):
        self.run_failure(platform='win32',close_error=True)

    def test_spawn_failure_with_no_child_keeps_normal_failure_receipt(self):
        self.run_failure(spawn_error=True)


class RuntimeTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown

    def test_cleanup_receipt_survives_restart_without_new_dispatch(self):
        self.rt.create(fixtures.plan());self.rt.tick('demo')
        attempt=self.rt.task('demo','produce')['latest']
        receipt=dict(status='uncertain',reason='Worker cleanup could not be confirmed',
                     child_pid=12345,cleanup_error='PermissionError: denied',stop_reason='time_limit')
        self.factory.sessions[attempt]['status']=receipt
        self.rt.tick('demo')
        self.rt.db.close();self.rt=fixtures.Runtime(self.root/'runtime',self.factory)
        self.rt.tick('demo');self.rt.tick('demo')
        row=self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(attempt,)).fetchone()
        self.assertEqual(row['state'],'uncertain')
        saved=json.loads(row['receipt'])
        self.assertEqual({k:saved[k] for k in receipt},receipt)
        self.assertEqual(saved['connector_receipt']['raw_sha256'],digest(receipt))
        self.assertFalse(saved['connector_receipt']['acceptance'])
        self.assertEqual(self.factory.calls,[attempt])

    def test_cancellation_retains_cleanup_receipt_and_never_replays(self):
        self.rt.create(fixtures.plan());self.rt.tick('demo')
        attempt=self.rt.task('demo','produce')['latest'];self.rt.request_cancel('demo')
        receipt=dict(status='uncertain',reason='Termination denied',child_pid=12345)
        self.factory.sessions[attempt]['status']=receipt
        with patch.object(self.factory,'cancel',return_value={'status':'cancellation_requested'}):
            self.rt.tick('demo');self.rt.tick('demo')
        row=self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(attempt,)).fetchone()
        saved=json.loads(row['receipt'])
        self.assertEqual({k:saved[k] for k in receipt},receipt)
        self.assertEqual(saved['connector_receipt']['raw_sha256'],digest(receipt))
        self.assertFalse(saved['connector_receipt']['acceptance'])
        self.assertEqual(row['state'],'cancelling')
        self.assertEqual(self.factory.calls,[attempt])
