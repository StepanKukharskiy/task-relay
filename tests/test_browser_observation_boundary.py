"""Driver-return evidence is distinct from post-action page capture, no live browser."""
import sqlite3,unittest
from task_relay.general_browser import Session
from task_relay.browser_journal import UncertainAction
from tests.test_general_browser import Driver,policy

class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.driver=Driver();self.session=Session(self.db,'job',policy(),self.driver)
        self.page=self.session.call('open','browser_open',{'url':'https://example.test/work'})
    def tearDown(self):self.db.close()
    def test_returned_click_capture_failure_is_not_replayed_and_needs_fresh_read(self):
        original=self.driver.snapshot
        def capture(tab):
            if self.driver.actions:raise RuntimeError('Execution context destroyed during capture')
            return original(tab)
        self.driver.snapshot=capture
        args=dict(tab=self.page['tab'],observation=self.page['observation'],ref='1',purpose='Requested fixture')
        value=self.session.call('click','browser_click',args)
        self.assertTrue(value['driver_action_returned']);self.assertTrue(value['observation_unavailable'])
        self.assertEqual(value['remote_outcome'],'not_independently_verified');self.assertNotIn('observation',value)
        self.assertFalse(self.session.journal.pending('fixture'))
        self.assertEqual(self.session.call('click','browser_click',args),value);self.assertEqual(len(self.driver.actions),1)
        with self.assertRaisesRegex(ValueError,'stale'):self.session.call('different','browser_click',args)
        self.driver.snapshot=original
        fresh=self.session.call('read','browser_read',{'tab':self.page['tab']})
        self.assertNotEqual(fresh['observation'],self.page['observation'])
        kinds=[x[0] for x in self.db.execute("select kind from general_browser_events where action='click'")]
        self.assertEqual(kinds,['intent','driver_returned','observed'])
    def test_driver_exception_remains_uncertain_without_return_marker(self):
        self.driver.fail=True
        with self.assertRaises(UncertainAction):self.session.call('click','browser_click',dict(tab=self.page['tab'],observation=self.page['observation'],ref='1',purpose='Requested fixture'))
        self.assertTrue(self.session.journal.pending('fixture'))
        self.assertEqual(self.db.execute("select count(*) from general_browser_events where action='click' and kind='driver_returned'").fetchone()[0],0)
    def test_returned_navigation_with_failed_capture_records_no_verified_page(self):
        self.driver.snapshot=lambda tab:(_ for _ in ()).throw(RuntimeError('Capture failed'))
        args=dict(tab=self.page['tab'],url='https://example.test/next')
        result=self.session.call('navigate','browser_navigate',args)
        self.assertTrue(result['driver_action_returned']);self.assertNotIn('url',result)
        self.assertEqual(len(self.driver.actions),1)
        self.assertEqual(self.session.call('navigate','browser_navigate',args),result)
        self.assertEqual(len(self.driver.actions),1)
    def test_failed_read_without_action_does_not_gain_return_evidence(self):
        self.driver.snapshot=lambda tab:(_ for _ in ()).throw(RuntimeError('Capture failed'))
        with self.assertRaises(UncertainAction):self.session.call('read','browser_read',{'tab':self.page['tab']})
        self.assertEqual(self.db.execute("select count(*) from general_browser_events where action='read' and kind='driver_returned'").fetchone()[0],0)
