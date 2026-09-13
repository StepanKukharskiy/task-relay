"""Actual channel intake and executor-selection boundary for /browser tasks."""
import json
import unittest
from unittest.mock import patch
from task_relay import browser_requests,orchestrator_chat,gemini
from task_relay.messages_orchestrator import OrchestratorRouter
from orchestrator import executors
from tests import test_providers as fixtures

REQUEST='/browser Find flight information from Saint_Petersburg, Russia to Dubai on November 23 - December 7'


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown;send=fixtures.Tests.send

    def test_telegram_exact_request_queues_without_login_or_sticky_mode(self):
        with patch.object(orchestrator_chat,'provider',return_value=('gemini','fixture-model')):
            ident=self.send(REQUEST)
            row=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()
            self.assertEqual(row['prompt'],REQUEST);self.assertEqual(row['status'],'queued')
            self.assertFalse(self.state.get('orchestrator_mode'))
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0],0)
            self.bridge.process({'update_id':ident,'message':{'message_id':ident,'text':REQUEST,'chat':{'id':123,'type':'private'},'from':{'id':123}}})
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)

    def test_messages_exact_request_and_replay_keep_channel(self):
        router=OrchestratorRouter(self.root/'private/state.sqlite',require_ready=False)
        try:
            with patch.object(orchestrator_chat,'provider',return_value=('gemini','fixture-model')):
                ident=router.submit('browser-guid',REQUEST)
                self.assertEqual(router.submit('browser-guid',REQUEST),ident)
            self.assertEqual(router.state.db.execute('SELECT prompt FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()[0],REQUEST)
            self.assertEqual(router.state.db.execute('SELECT channel FROM relay_request_channels WHERE request_id=?',(ident,)).fetchone()[0],'messages')
        finally:router.close()

    def test_explicit_request_cannot_fall_back_to_another_executor(self):
        for action in ({'kind':'route_task','task_id':'unrelated'}, {'kind':'plan_production','executor':'gemini-agent'}, {'kind':'collect_references'}):
            with self.assertRaisesRegex(ValueError,'browser production plan'):
                orchestrator_chat.interpret(json.dumps({'answer':'Proposed','action':action}),{'browser_request':True})
        self.assertIsNone(orchestrator_chat.interpret(json.dumps({'answer':'Which dates?','action':None}),{'browser_request':True})['action'])

    def test_setup_commands_are_not_execution_requests(self):
        for text in ('/browser','/browser status','/browser CONNECT','/browser cancel'):
            self.assertFalse(browser_requests.is_request(text))
        self.assertTrue(browser_requests.is_request(REQUEST))
        self.assertTrue(browser_requests.is_request('/browser@relaybot Find flights'))

    def test_metadata_refresh_never_generates_content(self):
        with patch.object(executors,'configured',return_value=({}, {'type':'gemini-agent','model':'fixture-model'})),patch.object(executors,'available',side_effect=[ValueError('stale'),None]),patch.object(executors,'probe') as probe:
            browser_requests.refresh_connection();probe.assert_called_once_with()

    def test_flight_request_reaches_reviewed_browser_plan_and_start(self):
        from task_relay import production_planning as planning
        from tests.test_general_browser import browser_graph
        from tests.test_gemini_executor import CONFIG,BACKEND
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                    research_ids=[],artifact_ids=[],planning_only=False,executor='gemini-browser')
        with patch.object(orchestrator_chat,'provider',return_value=('gemini','fixture-model')),patch.object(executors,'configured',return_value=(CONFIG,BACKEND)),patch.object(executors,'available'),patch.object(gemini,'read_config',return_value=CONFIG):
            ident=self.send(REQUEST)
            orchestrator_chat.Worker(self.state,lambda *_:json.dumps({'answer':'Preparing the flight search scope','action':action})).tick()
            row=self.state.db.execute('SELECT * FROM production_plans WHERE request_id=?',(ident,)).fetchone()
            self.assertIsNotNone(row,dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()))
            self.assertEqual(row['request'],REQUEST)
            self.assertIn('host_clock',json.loads(row['context']))
            proposed={'decision':'ready','message':'Search only, no booking','plan':{'brief':'Flight information','tasks':browser_graph()['tasks']}}
            planning.Worker(self.state,lambda *_:(json.dumps(proposed),{})).tick()
            row=self.state.db.execute('SELECT * FROM production_plans WHERE request_id=?',(ident,)).fetchone()
            self.assertEqual(row['status'],'ready',row['error'])
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
            with self.state.db:
                self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
                planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE request_id=?',(ident,)).fetchone()[0],'started')


if __name__=='__main__':unittest.main()
