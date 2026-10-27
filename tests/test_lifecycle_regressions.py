"""Previously missed composed lifetime boundaries; no provider work."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orchestrator import supervisor, sourcing_slides, contracts as c
from task_relay import registered_revision
from task_relay.bridge import BackgroundWorkers, State
from tests import test_native_correction_authority as correction_fixture


class Audit(unittest.TestCase):
    def test_standalone_import_path_does_not_change_runtime_identity(self):
        from task_relay import native_code_host
        one=Mock(metadata={'Name':'fixture'},version='1')
        two=Mock(metadata={'Name':'fixture'},version='2')
        with patch('importlib.metadata.distributions',return_value=[one]):first=native_code_host.identity()
        with patch('importlib.metadata.distributions',return_value=[one,one]):duplicate=native_code_host.identity()
        with patch('importlib.metadata.distributions',return_value=[one,two]):changed=native_code_host.identity()
        self.assertEqual(first,duplicate)
        self.assertNotEqual(first,changed)

    def test_finished_child_cannot_hide_tool_budget_violation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'host_runtime.py').write_bytes(b'controlled fixture')
            spec = dict(token='audit', host_support_sha256=hashlib.sha256(b'controlled fixture').hexdigest(),
                        registered_command=['controlled'], workspace=folder,
                        limits=dict(seconds=600, tool_calls=1))
            (root/'launch.json').write_text(json.dumps(spec))
            (root/'prompt.txt').write_text('Controlled fixture')
            child = Mock(pid=12345, returncode=0)
            child.poll.return_value = 0
            host = Mock(platform='darwin')
            host.process_identity.return_value = {'controlled': True}
            def spawn(*args, stdout, **kwargs):
                for i in range(2):
                    stdout.write((json.dumps(dict(type='item.started', item=dict(id=str(i), type='command_execution'))) + '\n').encode())
                stdout.flush()
                return child
            host.spawn.side_effect = spawn
            with patch.object(supervisor, 'HOST', host), patch.object(sys, 'argv', ['supervisor', folder, 'audit']):
                supervisor.main()
            receipt = json.loads((root/'done.json').read_text())
            self.assertEqual(receipt['tool_calls'], 2)
            self.assertEqual(receipt['reason'], 'tool_limit', 'Completed child must retain an observed budget violation')

    def test_correction_admission_does_not_discard_required_capacity(self):
        fixture = correction_fixture.Tests()
        fixture.setUp()
        try:
            run, baseline = fixture.data_revision()
            proof = registered_revision.proof(fixture.rt, baseline)
            plan = copy.deepcopy(baseline['plan'])
            author = next(t for t in plan['tasks'] if t['id'] == proof['producer'])
            data = {
                author['execution']['parameters']['inventory_path']: json.dumps({'items': [{}]*20}).encode(),
                author['execution']['parameters']['catalog_path']: json.dumps({'items': [{'options': [{}], 'gap': ''} for _ in range(20)]}).encode(),
            }
            cost = sourcing_slides.review_workload(author, data.get, correction=True)
            for task in plan['tasks']:
                if not task.get('execution'):
                    task['limits'].update(tool_calls=cost['tool_calls'], seconds=cost['seconds'])
            baseline = {**baseline, 'plan': c.plan(plan)}
            receipt = dict(cycle=1, baseline=c.encoded(baseline))
            try:
                revised = registered_revision.projection_graph(baseline, receipt, proof)
            except ValueError:
                return  # A structured pre-dispatch capacity hold is acceptable.
            final = next(t for t in revised['tasks'] if t['id'] == 'final')
            self.assertGreaterEqual(final['limits']['tool_calls'], cost['tool_calls'],
                                    'An admitted whole-candidate correction cannot discard its declared review workload')
        finally:
            fixture.tearDown()
            fixture.doCleanups()

    def test_constructor_failure_is_inside_worker_supervision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state.sqlite'
            workers = BackgroundWorkers(path, {}, None)
            state = State(path)
            state.db.execute('PRAGMA busy_timeout=0')
            other = sqlite3.connect(path)
            other.execute('BEGIN IMMEDIATE')
            escaped = None
            with patch.object(workers, 'open_state', return_value=state), \
                 patch('task_relay.bridge.log_operation_error') as logged, \
                 patch.object(workers.stop, 'wait', side_effect=lambda *a: workers.stop.set() or True):
                try:
                    workers.work('providers', .5)
                except sqlite3.OperationalError as exc:
                    escaped = str(exc)
                finally:
                    other.rollback()
                    other.close()
            try:
                state.db.execute('SELECT 1')
                closed = False
            except sqlite3.ProgrammingError:
                closed = True
            finally:
                state.db.close()
            self.assertIsNone(escaped, 'Initialization failures must produce supervised failure/retry, not kill the worker')
            self.assertTrue(logged.called)
            self.assertTrue(closed)


