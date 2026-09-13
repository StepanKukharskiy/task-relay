from contextlib import contextmanager
import sqlite3
import unittest
from unittest.mock import Mock,patch

from tests import test_providers as fixtures
from task_relay import browser_sites as sites,browser_setup,providers,browser_requests,relay_channels
from task_relay.host_browser_accounts import local_endpoint
from task_relay.general_browser import Session
from task_relay.browser_journal import UncertainAction
from tests.test_general_browser import Driver,policy

SITE='https://example.test'


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    send=fixtures.Tests.send

    def command(self,arg,source=None,channel='telegram'):
        self.uid+=1
        return browser_setup.command(self.state,'sites '+arg,source or str(self.uid),channel)

    def running(self,channel='telegram'):
        self.command('add '+SITE)
        self.command('login '+SITE,channel=channel)
        job=self.state.db.execute('SELECT job FROM browser_site_logins').fetchone()[0]
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?",(job,))
        return job

    def driver(self,url=SITE):
        page=Mock();page.url=url
        @contextmanager
        def factory(*_):yield page
        return page,factory

    def test_sites_controls_bypass_task_model_routing_and_preserve_receipts(self):
        self.assertFalse(browser_requests.is_request('/browser sites add '+SITE))
        self.assertTrue(browser_requests.is_request('/browser research example.test'))
        self.send('/browser sites add '+SITE,user=999)
        self.assertFalse(sites.catalog(self.state.db))
        self.send('/browser sites add '+SITE)
        self.assertEqual(sites.catalog(self.state.db)[0]['status'],'needs_verification')
        self.command('login '+SITE,'same');self.command('login '+SITE,'same')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_site_logins').fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,'identity'):self.command('remove '+SITE,'same')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)

    def test_new_sites_cannot_borrow_an_approved_session(self):
        self.command('add '+SITE)
        access=sites.Access(self.root/'private')
        for site in (SITE,'https://other.test','https://sub.example.test'):
            with self.assertRaises(sites.VerificationRequired):access.check(site)
        self.assertEqual(len(sites.catalog(self.state.db)),1)

    def test_manual_confirmation_reuses_site_but_does_not_claim_independent_auth(self):
        job=self.running('messages');page,factory=self.driver()
        page.wait_for_timeout.side_effect=lambda _:self.command('done '+SITE,channel='messages')
        with patch('task_relay.host_browser_accounts.login_required',return_value=False):sites.run_login(self.state,job,factory)
        sites.Access(self.root/'private').check(SITE+'/work')
        self.assertEqual(sites.catalog(self.state.db)[0]['status'],'confirmed_by_user')
        row=self.state.db.execute('SELECT text FROM outbox WHERE id=?',('browser-setup:'+job+':finished',)).fetchone()
        self.assertIn('confirmed by you',row[0])
        self.assertEqual(relay_channels.event_channel(self.state,'browser-setup:'+job+':finished'),'messages')
        page.fill.assert_not_called()

    def test_no_confirmation_before_open_and_challenge_never_counts_as_sign_in(self):
        job=self.running();page,factory=self.driver()
        with self.assertRaisesRegex(ValueError,'No open'):self.command('done '+SITE)
        page.wait_for_timeout.side_effect=lambda _:self.command('done '+SITE)
        with patch('task_relay.host_browser_accounts.login_required',return_value=True):sites.run_login(self.state,job,factory)
        self.assertEqual(sites.catalog(self.state.db)[0]['status'],'needs_verification')
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs WHERE id=?',(job,)).fetchone()[0],'failed')

    def test_different_site_after_sign_in_needs_manual_verification(self):
        job=self.running();page,factory=self.driver('https://different.test')
        page.wait_for_timeout.side_effect=lambda _:self.command('done '+SITE)
        sites.run_login(self.state,job,factory)
        self.assertEqual(sites.catalog(self.state.db)[0]['status'],'needs_verification')
        self.assertEqual(len(sites.catalog(self.state.db)),1)

    def test_cancel_and_restart_cannot_accept_late_confirmation(self):
        job=self.running();page,factory=self.driver()
        page.wait_for_timeout.side_effect=lambda _:browser_setup.command(self.state,'cancel','cancel')
        sites.run_login(self.state,job,factory)
        with self.assertRaises(ValueError):self.command('done '+SITE)
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs WHERE id=?',(job,)).fetchone()[0],'cancelled')
        self.command('login '+SITE)
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE status='queued'")
        providers.Worker(self.state)
        self.assertFalse(self.state.db.execute("SELECT 1 FROM provider_jobs WHERE status='running'").fetchone())
        self.assertEqual(sites.catalog(self.state.db)[0]['status'],'needs_verification')

    def test_remove_or_connection_change_revokes_existing_access_object(self):
        self.command('add '+SITE)
        with self.state.db:self.state.db.execute("UPDATE browser_sites SET status='confirmed_by_user'")
        access=sites.Access(self.root/'private');access.check(SITE)
        self.command('remove '+SITE)
        with self.assertRaises(sites.VerificationRequired):access.check(SITE)
        self.command('add '+SITE)
        with self.state.db:self.state.db.execute("UPDATE browser_sites SET status='confirmed_by_user'")
        sites.set_source(self.state.db,None)
        with self.assertRaises(sites.VerificationRequired):access.check(SITE)
        self.assertEqual(sites.catalog(self.state.db)[0]['status'],'needs_verification')

    def test_setup_job_and_outbox_are_atomic_and_spawn_follows_commit(self):
        self.command('add '+SITE)
        with patch.object(browser_setup,'notice',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):self.command('login '+SITE,'rollback')
        self.assertFalse(self.state.db.execute('SELECT 1 FROM browser_site_logins').fetchone())
        self.command('login '+SITE)
        process=Mock();process.poll.return_value=None
        def spawn(cmd,**kwargs):
            self.assertFalse(self.state.db.in_transaction)
            self.assertIn('task_relay.browser_setup',cmd)
            return process
        with patch.object(providers.HOST,'browser_python',return_value='/example/python'),patch.object(providers.HOST,'spawn',side_effect=spawn):providers.Worker(self.state).tick()

    def test_endpoint_and_site_validation_rejects_credential_or_remote_urls(self):
        for url in ('https://example.test?q=secret','https://user:pass@example.test','http://example.test','https://*.test'):
            with self.assertRaises(ValueError):sites.website(url)
        for url in ('http://example.test:9222','http://127.0.0.1:9222/path','http://user:pass@127.0.0.1:9222','http://127.0.0.1:9222?secret'):
            with self.assertRaises(ValueError):local_endpoint(url)
        self.assertEqual(local_endpoint('http://127.0.0.1:9222'),'http://127.0.0.1:9222')

    def test_verification_on_read_is_blocked_but_after_submit_stays_uncertain(self):
        driver=Driver();session=Session(self.state.db,'verify-test',policy(),driver)
        with patch.object(driver,'snapshot',side_effect=sites.VerificationRequired('Manual verification required')):
            result=session.call('open','browser_open',{'url':SITE})
        self.assertEqual(result['outcome'],'manual_verification_required')
        self.assertFalse(session.journal.pending('fixture'))
        page=session.call('read','browser_read',{'tab':result['tab']})
        args=dict(tab=page['tab'],observation=page['observation'],ref='1',purpose='Requested submission')
        with patch.object(driver,'act',side_effect=sites.VerificationRequired('Manual verification required')):
            with self.assertRaises(UncertainAction):session.call('submit','browser_click',args)
        self.assertEqual(session.journal.pending('fixture')[0]['id'],'submit')


if __name__=='__main__':unittest.main()
