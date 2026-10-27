"""Confirmed navigation cleanup preserves reads and keeps submissions uncertain."""
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch
from task_relay.general_browser import PlaywrightDriver,Session,NavigationUnavailable
from task_relay.browser_journal import UncertainAction
from tests.test_general_browser import Driver,policy

class NavigationTimeout(Exception):pass
class Page:
    def __init__(self,confirm=True,fail=False):self.closed=False;self.confirm=confirm;self.fail=fail
    def close(self):
        if self.fail:raise OSError('close failed')
        self.closed=self.confirm
    def is_closed(self):return self.closed

class Tests(unittest.TestCase):
    def adapter(self,page):
        driver=PlaywrightDriver.__new__(PlaywrightDriver)
        driver.pages={'tab':page};driver.navigation_blocks={};driver.redirects={}
        driver.goto=lambda p,u:(_ for _ in ()).throw(NavigationTimeout('navigation timed out'))
        return driver
    def test_adapter_requires_confirmed_owned_tab_closure(self):
        for page in [Page(),Page(confirm=False),Page(fail=True)]:
            driver=self.adapter(page)
            with patch.dict(sys.modules,{'playwright.sync_api':types.SimpleNamespace(TimeoutError=NavigationTimeout)}):
                if page.confirm and not page.fail:
                    with self.assertRaises(NavigationUnavailable):driver.navigate('tab','https://example.test/product')
                    self.assertEqual(driver.pages,{})
                else:
                    with self.assertRaises((RuntimeError,OSError)):driver.navigate('tab','https://example.test/product')
                    self.assertIn('tab',driver.pages)
    def test_session_can_try_alternative_without_replaying_timeout(self):
        db=sqlite3.connect(':memory:');driver=Driver();session=Session(db,'job',policy(max_tabs=1),driver)
        try:
            page=session.call('open','browser_open',{'url':'https://example.test/one'})
            args={'tab':page['tab'],'url':'https://example.test/slow'}
            with patch.object(driver,'navigate',side_effect=NavigationUnavailable(args['url'],'timed out')) as navigate:
                result=session.call('slow','browser_navigate',args)
                self.assertEqual(result['outcome'],'unavailable')
                self.assertTrue(result['tab_closed']);self.assertNotIn('observation',result)
                self.assertFalse(session.journal.pending('fixture'))
                self.assertEqual(session.call('slow','browser_navigate',args),result)
                navigate.assert_called_once()
            with self.assertRaisesRegex(ValueError,'detached'):session.call('old-tab','browser_read',{'tab':page['tab']})
            alternative=session.call('alternative','browser_open',{'url':'https://example.test/other'})
            self.assertEqual(alternative['url'],'https://example.test/other')
            from orchestrator.browser_review_inputs import capture_pack
            pack=capture_pack(db,{'assignment_id':'job','browser':policy(max_tabs=1)})
            self.assertEqual(pack['actions'][1]['result']['outcome'],'unavailable')
        finally:db.close()
    def test_unknown_navigation_and_submission_stay_uncertain(self):
        for operation in ['navigate','click']:
            db=sqlite3.connect(':memory:');driver=Driver();session=Session(db,'job',policy(),driver)
            try:
                page=session.call('open','browser_open',{'url':'https://example.test/one'})
                args={'tab':page['tab'],'url':'https://example.test/slow'} if operation=='navigate' else dict(tab=page['tab'],observation=page['observation'],ref='1',purpose='requested submission')
                method='navigate' if operation=='navigate' else 'act'
                error=OSError('driver outcome lost') if operation=='navigate' else NavigationUnavailable('https://example.test/slow','redirect timed out')
                with patch.object(driver,method,side_effect=error) as call:
                    with self.assertRaises(UncertainAction):session.call('action','browser_'+operation,args)
                    with self.assertRaises(UncertainAction):session.call('action','browser_'+operation,args)
                    call.assert_called_once()
                self.assertTrue(session.journal.pending('fixture'))
            finally:db.close()
