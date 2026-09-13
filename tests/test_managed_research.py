"""Channel routing and crash recovery for the app-managed Chrome worker."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay import browser_research as research, credentials, managed_research, providers
from task_relay.bridge import State
from task_relay.browser_jobs import Journal
from tests.test_browser_jobs import Driver, URL


class ResearchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name).resolve()/'data'
        self.state = State(self.data/'state.sqlite')
        self.addCleanup(self.state.db.close)
        research.initialize(self.state.db)
        credentials.save(self.data/'browser-use.json', {'version': 1, 'enabled': True})

    def queued(self, source='fixture'):
        return research.enqueue(self.state, source, '/perplexity exact question\nwith a second line', 'messages')

    def run_job(self, receipt, driver):
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?", (receipt,))
        @contextmanager
        def factory(root):yield driver
        managed_research.run(self.state, receipt, factory)

    def test_orchestrator_routes_natural_request_without_model_browser_checks(self):
        import json
        from task_relay import orchestrator_chat as chat, capabilities, browser_requests
        request = 'use browser and search perplexity for fixture contractors\nKeep this exact scope.'
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,created) VALUES (1,?,'fixture','fixture',0)", (request,))
            self.state.db.execute("INSERT INTO relay_request_channels VALUES (1,'messages')")
        action = {'kind': 'browser_research', 'site': 'perplexity', 'query': 'Find fixture contractors. Keep this exact scope.'}
        snap = {'capabilities': {'operations': [research.catalog(self.state)]}}
        def generator(job, payload):
            self.assertEqual(payload['user_message'], request)
            return json.dumps({'answer': 'Research requested.', 'action': action})
        with patch.object(chat, 'snapshot', return_value=snap), patch.object(browser_requests, 'refresh_connection', side_effect=AssertionError('Wrong browser route')):
            chat.Worker(self.state, generator).tick()
        job = self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertEqual(job['status'], 'answered', job['answer'])
        receipt = self.state.db.execute('SELECT receipt_id FROM capability_dispatches WHERE job_id=1').fetchone()[0]
        self.assertEqual(Journal(self.state.db).get(receipt)['prompt'], action['query'])
        self.assertEqual(self.state.db.execute('SELECT request FROM browser_research_requests WHERE id=?',(receipt,)).fetchone()[0],request)
        self.assertIn(action['query'],job['answer'])
        with transaction(self.state.db):capabilities.dispatch(self.state, job, action, snap)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError,'different action'):
            with transaction(self.state.db):capabilities.dispatch(self.state, job, {**action,'query':'Changed scope'}, snap)
        driver = Driver();self.run_job(receipt, driver)
        self.assertEqual(driver.sent, [action['query']])
        from task_relay.relay_channels import pending
        self.assertEqual(len(pending(self.state, 'telegram')), 0)
        self.assertEqual(len(pending(self.state, 'messages')), 2)

    def test_orchestrator_dispatch_rolls_back_receipt_and_queue_together(self):
        from task_relay import capabilities
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with transaction(self.state.db):
                capabilities.dispatch(self.state, {'id': 2, 'prompt': 'Research fixture in Perplexity'},
                                      {'kind': 'browser_research', 'site': 'perplexity', 'query': 'Research fixture.'}, {})
                raise RuntimeError('rollback')
        for table in ('capability_dispatches', 'browser_jobs', 'provider_jobs', 'browser_research_requests', 'outbox'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)

    def test_orchestrator_rechecks_setting_and_does_not_fall_back(self):
        from task_relay import capabilities
        action = {'kind': 'browser_research', 'site': 'perplexity', 'query': 'Find fixture contractors. Keep this exact scope.'}
        for saved, reason in (({'enabled': False}, 'Browser use is off'),
                              ({'enabled': True, 'manual_sign_in': True}, 'Done signing in')):
            credentials.save(self.data/'browser-use.json', {'version': 1, **saved})
            with self.assertRaisesRegex(capabilities.CapabilityError, reason):
                with transaction(self.state.db):
                    capabilities.dispatch(self.state, {'id': 2, 'prompt': 'Research fixture in Perplexity'}, action, {})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0], 0)
        with self.assertRaises(ValueError):research.validate_action({**action, 'prompt': 'rewritten'})
        with self.assertRaises(ValueError):research.validate_action({**action, 'site': 'other'})

    def test_research_query_validation_never_falls_back_to_copying_original(self):
        import json
        from task_relay import orchestrator_chat as chat
        base={'kind':'browser_research','site':'perplexity'}
        for action in (base, *({**base,'query':q} for q in (None,42,'','   ','x'*12001)),
                       {**base,'query':'Find fixture contractors.','extra':True}):
            with self.subTest(action=repr(action)[:100]), self.assertRaises(ValueError):
                chat.interpret(json.dumps({'answer':'Research','action':action}),{})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0],0)

    def test_frozen_query_keeps_scope_and_cannot_be_changed_on_duplicate_input(self):
        from task_relay import capabilities
        original='Use Perplexity to compare fixture suppliers in Bergen for 2025; exclude wholesalers. Return a table.'
        query='Compare fixture suppliers in Bergen for 2025, excluding wholesalers. Return a table.'
        action={'kind':'browser_research','site':'perplexity','query':query}
        with transaction(self.state.db):
            capabilities.dispatch(self.state,{'id':8,'prompt':original},action,{})
        row=self.state.db.execute('SELECT r.*,j.prompt AS query FROM browser_research_requests r JOIN browser_jobs j ON j.id=r.id').fetchone()
        self.assertEqual(row['request'],original);self.assertEqual(row['query'],query)
        with self.assertRaises(ValueError):
            research.enqueue(self.state,'orchestrator:8',original,exact_prompt='Find any suppliers.')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0],1)
        self.assertEqual(Journal(self.state.db).get(row['id'])['prompt'],query)

    def test_generated_query_cannot_silently_select_a_conversation_target(self):
        query=URL+' Compare the cited suppliers.'
        receipt=research.enqueue(self.state,'query-url','Research these suppliers',exact_prompt=query)
        job=Journal(self.state.db).get(receipt)
        self.assertIsNone(job['target']);self.assertEqual(job['prompt'],query)

    def test_browser_catalog_reports_configuration_without_verifying_login(self):
        from task_relay import host_managed_chrome
        from task_relay.relay_channels import ScopedState
        self.queued()
        with patch.object(host_managed_chrome, 'chrome_path', return_value=Path('/fixture/Chrome')):
            info = research.catalog(ScopedState(self.state, 'messages'))
            self.assertTrue(info['available'])
            self.assertEqual(len(info['recent_requests']), 1)
            self.assertEqual(research.catalog(ScopedState(self.state, 'telegram'))['recent_requests'], [])
        with patch.object(host_managed_chrome, 'chrome_path', return_value=None):
            self.assertFalse(research.catalog(self.state)['available'])

    def test_app_setting_routes_chat_without_extension_and_delivers_once(self):
        receipt = self.queued()
        self.assertIsNone(research.run_next(self.state, Driver()))  # extension cannot take it
        driver = Driver()
        self.run_job(receipt, driver)
        self.assertEqual(driver.sent, ['exact question\nwith a second line'])
        self.assertEqual(self.queued(), receipt)
        managed_research.run(self.state, receipt, lambda _: self.fail('Duplicate browser opened'))
        row = self.state.db.execute('SELECT channel FROM relay_event_channels WHERE event_id=?', ('perplexity-research:'+receipt+':completed',)).fetchone()
        self.assertEqual(row[0], 'messages')
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'completed')

    def test_enqueue_rollback_includes_provider_dispatch(self):
        with self.assertRaises(RuntimeError):
            with transaction(self.state.db):
                self.queued()
                raise RuntimeError('fixture rollback')
        for table in ('browser_jobs', 'browser_research_requests', 'browser_research_transport', 'provider_jobs', 'outbox'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)

    def test_multiple_research_requests_keep_separate_receipts_and_queue_limit(self):
        receipts = [self.queued(str(i)) for i in range(5)]
        self.assertEqual(len(set(receipts)), 5)
        with self.assertRaisesRegex(ValueError, 'Five'):self.queued('sixth')
        driver = Driver()
        self.run_job(receipts[0], driver)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM provider_jobs WHERE status='queued'").fetchone()[0], 4)
        self.assertEqual(len(driver.sent), 1)

    def test_connection_setup_still_allows_only_one_pending_job_per_provider(self):
        import sqlite3
        # Upgrade a pre-browser-settings database without dropping its jobs.
        self.state.db.executescript('''DROP INDEX one_provider_setup_v2;
            CREATE UNIQUE INDEX one_provider_setup ON provider_jobs(provider) WHERE status IN ('queued','running');''')
        with self.state.db:
            self.state.db.execute("INSERT INTO provider_jobs VALUES ('first','gemini','connect','queued',0)")
        providers.initialize(self.state.db)
        self.queued('first research');self.queued('second research')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.state.db:self.state.db.execute("INSERT INTO provider_jobs VALUES ('second','gemini','connect','queued',0)")

    def test_scheduler_dispatch_commits_before_start_and_reaches_research_entry(self):
        import sqlite3
        from unittest.mock import Mock
        from task_relay.browser_setup import run_login
        receipt = self.queued()
        process = Mock();process.poll.return_value = None
        def spawn(command, **kwargs):
            with sqlite3.connect(self.data/'state.sqlite') as db:
                self.assertEqual(db.execute('SELECT status FROM provider_jobs WHERE id=?', (receipt,)).fetchone()[0], 'running')
            self.assertEqual(command[1:], ['-m','task_relay.browser_setup',str(self.data/'state.sqlite'),receipt])
            return process
        worker = providers.Worker(self.state, popen=spawn)
        with patch.object(providers.HOST, 'browser_python', return_value='/fixture/python'):
            worker.tick()
        driver = Driver()
        @contextmanager
        def factory(root):yield driver
        run_login(self.state, receipt, factory)
        process.poll.return_value = 0
        worker.tick()
        self.assertEqual(len(driver.sent), 1)
        self.assertIsNone(worker.active)

    def test_disabled_before_execution_never_opens_browser(self):
        receipt = self.queued()
        credentials.save(self.data/'browser-use.json', {'version': 1, 'enabled': False})
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?", (receipt,))
        managed_research.run(self.state, receipt, lambda _: self.fail('Disabled browser opened'))
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'blocked')
        with self.assertRaisesRegex(ValueError, 'off'):self.queued('another')

    def test_manual_sign_in_keeps_queued_research_pending_and_blocks_new_intake(self):
        from unittest.mock import Mock
        receipt = self.queued()
        credentials.save(self.data/'browser-use.json', {'version':1, 'enabled':True, 'manual_sign_in':True})
        spawn = Mock()
        providers.Worker(self.state, popen=spawn).tick()
        spawn.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs WHERE id=?',(receipt,)).fetchone()[0], 'queued')
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'prepared')
        with self.assertRaisesRegex(ValueError, 'Done signing in'):self.queued('another')

    def test_uncertain_submit_requires_observation_and_retains_single_intent(self):
        receipt = self.queued()
        driver = Driver();driver.error = ValueError('Connection lost after submit')
        self.run_job(receipt, driver)
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'uncertain')
        with self.assertRaises(ValueError):research.requeue(self.state, receipt)
        research.requeue(self.state, receipt, inspect=True, url=URL)
        driver.error = None
        self.run_job(receipt, driver)
        self.assertEqual(len(driver.sent), 1)
        self.assertEqual(Journal(self.state.db).get(receipt)['status'], 'completed')

    def test_scheduler_restart_finalizes_uncertainty_in_original_channel(self):
        receipt = self.queued()
        journal = Journal(self.state.db)
        journal.claim(receipt, Driver().snapshot())
        with self.state.db:
            self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?", (receipt,))
            self.state.db.execute("UPDATE browser_research_requests SET state='running' WHERE id=?", (receipt,))
        research.recover(self.state)  # extension recovery cannot mutate Chrome jobs
        self.assertEqual(journal.get(receipt)['status'], 'submitting')
        providers.Worker(self.state)
        self.assertEqual(journal.get(receipt)['status'], 'uncertain')
        self.assertIsNone(research.run_next(self.state, Driver()))

    def test_completion_before_scheduler_exit_is_recovered_without_resend(self):
        receipt = self.queued()
        journal = Journal(self.state.db)
        journal.update(receipt, 'completed', url=URL, result='saved answer')
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?", (receipt,))
        providers.Worker(self.state)
        managed_research.interrupted(self.state, receipt, 'second recovery')
        self.assertEqual(journal.get(receipt)['result'], 'saved answer')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox WHERE id=?', ('perplexity-research:'+receipt+':completed',)).fetchone()[0], 1)


if __name__ == '__main__':unittest.main()
