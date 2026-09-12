"""Explicit provider choice survives planning and requires current eligibility."""
import json
import unittest
from unittest.mock import patch

from orchestrator import executors
import production_planning as planning
from tests import test_production_planning as fixtures
from tests.test_gemini_executor import CONFIG,BACKEND


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    click=fixtures.Tests.click
    start=fixtures.Tests.start

    def text_response(self):
        r=self.response()
        for t in r['plan']['tasks']:t.update(tools=['files'],limits=executors.GEMINI_LIMITS.copy())
        return r

    def test_explicit_executor_card_and_atomic_approval(self):
        with patch.object(executors,'configured',return_value=(CONFIG,BACKEND)),patch.object(executors,'available'):
            row=self.queue(action=self.action(executor='gemini-agent'))
            planning.Worker(self.state,lambda *_:(json.dumps(self.text_response()),{})).tick()
            row=self.row();self.assertEqual(row['status'],'ready',row['error'])
            self.assertEqual(json.loads(row['plan'])['backend'],BACKEND)
            self.assertIn('External transfer',planning.preview(row));self.assertIn('File tools only',planning.preview(row))
            with patch.object(executors,'available',side_effect=ValueError('Disconnected')):self.start(row)
            self.assertEqual(self.row()['status'],'ready')
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
            self.start(row);self.assertEqual(self.row()['status'],'started')
            self.assertEqual(json.loads(self.state.db.execute('SELECT plan FROM production_runs').fetchone()[0])['backend'],BACKEND)

    def test_clarification_keeps_selected_provider_despite_policy(self):
        with patch.object(executors,'configured',return_value=(CONFIG,BACKEND)),patch.object(executors,'available'):
            self.queue(action=self.action(executor='gemini-agent'))
            planning.Worker(self.state,lambda *_:(json.dumps(dict(decision='needs_input',message='Which title?',plan=None)),{})).tick()
            row=self.queue(ident=2,action=self.action(parent_id='plan-1'),text='Use title X.')
            self.assertEqual(json.loads(row['options'])['backend'],BACKEND)
            bad=self.text_response();bad['plan']['tasks'][0]['tools']=['files','shell']
            with self.assertRaisesRegex(ValueError,'provider'):
                planning.validate_result(json.dumps(bad),row)

    def test_next_stage_keeps_provider_when_default_policy_differs(self):
        from tests.test_production_stages import Tests as stages
        with patch.object(executors,'configured',return_value=(CONFIG,BACKEND)),patch.object(executors,'available'):
            self.queue(action=self.action(executor='gemini-agent'))
            planning.Worker(self.state,lambda *_:(json.dumps(self.text_response()),{})).tick()
            self.start(self.row());stages.finish(self,'production-1')
            row=self.queue(ident=2,action=self.action(previous_run='production-1'))
            self.assertEqual(json.loads(row['options'])['backend'],BACKEND)

    def test_unavailable_explicit_executor_never_falls_back(self):
        with self.assertRaisesRegex(ValueError,'unavailable'):
            planning.validate_action(self.action(executor='gemini-agent'),{'capabilities':{'graph_executors':[{'id':'gemini-agent','available':False}]}})


if __name__=='__main__':unittest.main()
