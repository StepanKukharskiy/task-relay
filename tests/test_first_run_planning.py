"""Fresh-state planning with controlled provider metadata; no external calls."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import executors, worker_capabilities
from task_relay import production_planning as planning
from tests import test_production_planning as fixtures
from tests import test_task_routing as routing


GEMINI={'type':'gemini-agent','model':'verified-gemini'}
OPENAI={'type':'openai-agent','model':'verified-openai'}


class Tests(unittest.TestCase):
    tearDown=routing.Tests.tearDown
    request=routing.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response

    def setUp(self):
        routing.Tests.setUp(self)
        del self.fail  # Routing's fake desktop flag shadows unittest.TestCase.fail.
        self.entries=[dict(worker_capabilities.entry(b),available=True) for b in (OPENAI,GEMINI)]
        for mock in (patch.object(executors,'catalog',side_effect=lambda *_:copy.deepcopy(self.entries)),
                     patch.object(executors,'available')):
            mock.start();self.addCleanup(mock.stop)

    def options(self,row):return json.loads(row['options'])

    def test_fresh_request_reaches_ready_plan_with_verified_conversation_provider(self):
        self.assertIsNone(self.state.get('production-planner-policy'))
        row=self.queue(text='Write a short text description of a tensegrity model.')
        self.assertEqual(self.options(row)['backend'],GEMINI)
        self.assertFalse(self.options(row)['executor_locked'])
        self.assertEqual({x['id'] for x in self.options(row)['worker_catalog']},
                         {'gemini-agent','openai-agent'})
        result=self.response()
        for task in result['plan']['tasks']:
            task.pop('tools');task['worker']={'requires':['files.text']}
            task['limits']=executors.GEMINI_LIMITS.copy()
        planning.Worker(self.state,lambda *_:(json.dumps(result),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.assertIn('verified-gemini',planning.preview(row))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)

    def test_unavailable_conversation_worker_uses_another_verified_file_worker(self):
        self.entries[1]['available']=False
        self.assertEqual(self.options(self.queue())['backend'],OPENAI)

    def test_missing_workers_give_setup_steps_and_preserve_request_without_dispatch(self):
        self.entries=[dict(worker_capabilities.entry({'type':'openai-browser','model':'browser-only'}),available=True)]
        self.request(self.action(),'Preserve this exact request.')
        saved=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertEqual(saved['status'],'failed')
        self.assertEqual(saved['prompt'],'Preserve this exact request.')
        self.assertIn('Check worker connection',saved['answer'])
        self.assertNotIn('production-planner-policy',saved['answer'])
        self.assertIsNotNone(saved['response'])
        self.assertIsNone(self.row())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        # A later explicit request can plan after setup; the failed receipt survives.
        before=tuple(saved)
        self.entries=[dict(worker_capabilities.entry(GEMINI),available=True)]
        self.queue(ident=2)
        self.assertEqual(tuple(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()),before)

    def test_explicit_executor_wins_and_locks_catalog(self):
        row=self.queue(action=self.action(executor='openai-agent'))
        self.assertEqual(self.options(row)['backend'],OPENAI)
        self.assertTrue(self.options(row)['executor_locked'])
        self.assertEqual([x['id'] for x in self.options(row)['worker_catalog']],['openai-agent'])

    def test_unavailable_named_executor_is_not_substituted(self):
        self.entries[0]['available']=False
        self.request(self.action(executor='openai-agent'))
        self.assertIsNone(self.row())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_existing_default_is_not_replaced_by_bootstrap(self):
        with self.state.db:self.state.put('production-planner-policy',{'backend':OPENAI})
        self.assertEqual(self.options(self.queue())['backend'],OPENAI)

    def test_stale_default_fails_without_substituting_verified_worker(self):
        with self.state.db:self.state.put('production-planner-policy',{'backend':OPENAI})
        with patch.object(executors,'available',side_effect=ValueError('Selected worker model changed')):
            self.request(self.action())
        self.assertIsNone(self.row())
        self.assertIn('Selected worker model changed',self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=1').fetchone()[0])

    def test_clarification_keeps_frozen_backend_and_model(self):
        original=self.queue()
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='needs_input' WHERE id=?",(original['id'],))
        self.entries=[dict(worker_capabilities.entry(OPENAI),available=True)]
        successor=self.queue(ident=2,action=self.action(parent_id=original['id']),text='Use three struts.')
        self.assertEqual(self.options(successor)['backend'],GEMINI)
        self.assertEqual(self.options(successor)['worker_catalog'],self.options(original)['worker_catalog'])
        self.assertIn('Use three struts.',successor['request'])
