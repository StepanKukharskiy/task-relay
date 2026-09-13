from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from tests import test_providers as fixtures
from task_relay import browser_setup,providers,relay_channels
from task_relay.messages_orchestrator import OrchestratorRouter
from task_relay.perplexity_browser import HOME_URL


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    send=fixtures.Tests.send
    click=fixtures.Tests.click
    def jobs(self):return self.state.db.execute("SELECT * FROM provider_jobs WHERE provider='perplexity'").fetchall()
    def running(self,channel='telegram'):
        browser_setup.command(self.state,'connect','test-start',channel)
        job=self.jobs()[0]['id']
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?",(job,))
        return job
    def driver(self,ready=True):
        driver=Mock();driver.page.url=HOME_URL
        if not ready:driver.check_ready.side_effect=ValueError('not signed in')
        @contextmanager
        def factory(_):yield driver
        return driver,factory
    def test_telegram_menu_and_command_deduplicate_without_worker_or_credentials(self):
        self.send('/providers');self.click('Perplexity browser')
        old=self.click('Open Perplexity sign-in',user=999)
        self.assertEqual(len(self.jobs()),0)
        token=self.click('Open Perplexity sign-in');self.click('Open Perplexity sign-in',data=token)
        self.send('/browser connect')
        self.assertEqual(len(self.jobs()),1)
        self.assertEqual(self.jobs()[0]['status'],'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_key_sessions').fetchone()[0],0)
    def test_messages_request_and_progress_keep_their_delivery_channel(self):
        router=OrchestratorRouter(self.root/'private/state.sqlite',require_ready=False)
        try:
            router.browser_setup('same-guid','connect');router.browser_setup('same-guid','connect')
            job=self.jobs()[0]['id']
            with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?",(job,))
            browser_setup.progress(self.state,job,'waiting','Browser waiting')
            browser_setup.finish(self.state,job,True,'Connected')
            events=self.state.db.execute("SELECT id FROM outbox WHERE id LIKE 'browser-setup:%'").fetchall()
            self.assertEqual(len(events),3)
            self.assertTrue(all(relay_channels.event_channel(self.state,r['id'])=='messages' for r in events))
            self.assertEqual(len(self.jobs()),1)
        finally:router.close()
    def test_verified_sign_in_finishes_without_input_or_prompt_submission(self):
        job=self.running();driver,factory=self.driver()
        with patch('builtins.input',side_effect=AssertionError('No terminal input')):
            browser_setup.run_login(self.state,job,factory)
        self.assertEqual(self.jobs()[0]['status'],'completed')
        driver.submit.assert_not_called()
        self.assertIn('sign-in was verified',browser_setup.status(self.state))
    def test_cancel_closes_wait_without_success_and_preserves_new_setup(self):
        job=self.running();driver,factory=self.driver(False)
        driver.pause.side_effect=lambda:browser_setup.command(self.state,'cancel','cancel')
        browser_setup.run_login(self.state,job,factory)
        self.assertEqual(self.jobs()[0]['status'],'cancelled')
        browser_setup.finish(self.state,job,True,'Late success')
        self.assertEqual(self.jobs()[0]['status'],'cancelled')
        browser_setup.command(self.state,'connect','next')
        self.assertEqual(len(self.jobs()),2)
    def test_identity_provider_page_is_never_inspected(self):
        job=self.running();driver,factory=self.driver();driver.page.url='https://accounts.example.test/login'
        driver.pause.side_effect=lambda:browser_setup.command(self.state,'cancel','cancel')
        browser_setup.run_login(self.state,job,factory)
        driver.snapshot.assert_not_called();driver.check_ready.assert_not_called()
    def test_restart_marks_interrupted_login_failed_in_original_channel(self):
        job=self.running('messages');providers.Worker(self.state)
        self.assertEqual(self.jobs()[0]['status'],'failed')
        event='browser-setup:'+job+':finished'
        self.assertEqual(relay_channels.event_channel(self.state,event),'messages')
        self.assertIsNone(providers.Worker(self.state).active)
    def test_worker_launch_is_after_commit_and_uses_optional_runtime(self):
        browser_setup.command(self.state,'connect','launch')
        process=Mock();process.poll.return_value=None
        def spawn(cmd,**kw):
            self.assertFalse(self.state.db.in_transaction)
            self.assertEqual(cmd[:3],['/example/python','-m','task_relay.browser_setup'])
            return process
        with patch.object(providers.HOST,'browser_python',return_value='/example/python'),patch.object(providers.HOST,'spawn',side_effect=spawn):
            worker=providers.Worker(self.state);worker.tick()
        self.assertIsNotNone(worker.active)
    def test_queue_and_notice_roll_back_together(self):
        with patch.object(browser_setup,'notice',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):browser_setup.command(self.state,'connect','rollback')
        self.assertEqual(len(self.jobs()),0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_setup_requests').fetchone()[0],0)
    def test_timeout_does_not_claim_connected(self):
        job=self.running();driver,factory=self.driver(False)
        browser_setup.run_login(self.state,job,factory,timeout=0)
        self.assertEqual(self.jobs()[0]['status'],'failed')
        driver.submit.assert_not_called()


if __name__=='__main__':unittest.main()
