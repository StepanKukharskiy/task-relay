"""Desktop planner request identity, local review and exact Start boundary."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from orchestrator import executors
from task_relay.bridge import State
from task_relay.desktop_plans import DesktopPlanError, create, decide, detail, list_plans, prepare, process_requests
from task_relay.production_planning import Worker
from task_relay.relay_paths import Paths
from task_relay import relay_channels
from tests.test_orchestrator import pair


class DesktopPlansTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.paths = Paths(root / 'app', root / 'data', root / 'workspaces', root / 'generated')
        self.project = root / 'project'
        self.project.mkdir()
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        with self.state.db:
            self.state.put('health:desktop-plans', {'interface_version': 1, 'last_success': time.time()})
            self.state.put('production-planner-policy', {'backend': pair()['backend']})

    def request(self, request_id=None):
        return create('Write a source-grounded brief.', 'No rendering.', str(self.project), None,
                      request_id or str(uuid.uuid4()), self.paths)

    def test_duplicate_request_is_one_planning_job_and_channel_is_desktop(self):
        request_id = str(uuid.uuid4())
        first = self.request(request_id)
        second = self.request(request_id)
        self.assertEqual(first['plan_id'], second['plan_id'])
        with self.assertRaises(DesktopPlanError):
            create('Different brief', '', str(self.project), None, request_id, self.paths)
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()['status'],
                         'accepted', self.state.db.execute('SELECT result FROM desktop_plan_requests').fetchone()[0])
        row = self.state.db.execute('SELECT * FROM production_plans').fetchone()
        self.assertEqual(row['channel'], 'desktop')
        self.assertEqual(row['status'], 'queued')
        self.assertTrue(json.loads(row['options'])['planning_only'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0], 1)
        self.assertEqual(list_plans(self.paths)['plans'][0]['request_status'], 'accepted')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_failed_admission_rolls_back_partial_database_work_and_keeps_receipt(self):
        self.request()
        def fail(state, *_):
            state.db.execute("INSERT INTO relay_event_channels VALUES ('partial-desktop-plan','desktop')")
            raise ValueError('Configured executor unavailable')
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch('task_relay.production_planning.enqueue', side_effect=fail)):
            process_requests(self.state)
        row = self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()
        self.assertEqual(row['status'], 'rejected')
        self.assertIn('executor unavailable', row['result'])
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM relay_event_channels WHERE event_id='partial-desktop-plan'").fetchone())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0], 0)

    def test_missing_input_question_is_visible_for_revision(self):
        self.request()
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        answer = {'decision': 'needs_input', 'message': 'Which source version should be revised?', 'plan': None}
        Worker(self.state, lambda *_: (json.dumps(answer), {'total_tokens': 1})).tick()
        ident = self.state.db.execute('SELECT id FROM production_plans').fetchone()[0]
        view = detail(ident, self.paths)
        self.assertEqual(view['project'], str(self.project))
        self.assertEqual(view['status'], 'needs_input')
        self.assertEqual(view['preview'], answer['message'])
        self.assertIsNone(view['review_digest'])
        create('Use version 2 of the saved brief.', '', str(self.project), ident,
               str(uuid.uuid4()), self.paths)
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        revised = self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?', (ident,)).fetchone()
        self.assertIsNotNone(revised)
        self.assertIn('Write a source-grounded brief.', revised['request'])
        self.assertIn('Use version 2 of the saved brief.', revised['request'])
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?', (ident,)).fetchone()[0], 'superseded')

    def test_exact_review_required_before_desktop_start(self):
        self.request()
        with (patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')),
              patch.object(executors, 'available')):
            process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()['status'],
                         'accepted', self.state.db.execute('SELECT result FROM desktop_plan_requests').fetchone()[0])
        proposal = pair(gate='User selects the brief', max_attempts=1)
        for task in proposal['tasks']:
            task['tools'] = ['files', 'shell']
            task['limits'] = {'seconds': 600, 'tool_calls': 60, 'output_bytes': 100000000}
        answer = {'decision': 'ready', 'message': 'One brief and independent review.',
                  'input_basis': {'mode': 'new', 'artifacts': []},
                  'plan': {key: proposal[key] for key in ('brief', 'tasks')}}
        Worker(self.state, lambda *_: (json.dumps(answer), {'total_tokens': 1})).tick()
        ident = self.state.db.execute('SELECT id FROM production_plans').fetchone()[0]
        first = detail(ident, self.paths)
        self.assertEqual(first['status'], 'ready')
        self.assertTrue(first['planning_only'])
        self.assertTrue(first['documents'])
        with self.assertRaisesRegex(DesktopPlanError, 'Pair Telegram'):
            decide(ident, 'start', first['review_digest'], self.paths)
        with self.state.db:
            self.state.put('user_id', 7)
            self.state.put('chat_id', 7)
        with self.assertRaisesRegex(ValueError, 'no execution authorization'):
            decide(ident, 'start', first['review_digest'], self.paths)
        with self.assertRaisesRegex(DesktopPlanError, 'Restart|changed|ready'):
            decide(ident, 'start', 'incorrect', self.paths)
        prepared = prepare(ident, self.paths)
        self.assertFalse(prepared['planning_only'])
        self.assertNotEqual(first['review_digest'], prepared['review_digest'])
        with self.assertRaisesRegex(DesktopPlanError, 'changed'):
            decide(ident, 'start', first['review_digest'], self.paths)
        result = decide(ident, 'start', prepared['review_digest'], self.paths)
        self.assertEqual(result['status'], 'started')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans').fetchone()[0], 'started')
        event = self.state.db.execute("SELECT id FROM outbox WHERE id LIKE 'production:%:planner-started'").fetchone()[0]
        self.assertEqual(relay_channels.event_channel(self.state, event), 'telegram')


if __name__ == '__main__':
    unittest.main()
