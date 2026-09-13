"""General browser authority/recovery with small text fixtures and no network."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts as c
from orchestrator.browser_contract import origin,validate
from task_relay.browser_journal import Journal,UncertainAction
from task_relay.general_browser import Session,profile_lock,NavigationBlocked
from tests.test_gemini_executor import graph


def policy(**changes):
    return {**dict(profile='fixture',origins=['https://example.test'],interaction_scope='Submit the requested fixture text once',
                max_tabs=3,max_actions=20,uploads=[],downloads=[]),**changes}


def browser_graph():
    value=graph();value['backend']['type']='gemini-browser'
    for task in value['tasks']:
        task.update(tools=['files','browser'],browser=policy(interaction_scope='' if task.get('review_of') else 'Submit the requested fixture text once'))
    return value


class Driver:
    def __init__(self):self.pages={};self.actions=[];self.fail=False;self.before=None
    def open(self,tab,url):
        self.pages[tab]={'url':url,'title':'Fixture','text':'Ready',
                        'controls':[{'tag':'INPUT','type':'text','autocomplete':'','value_present':False},
                                    {'tag':'BUTTON','type':'','label':'Submit','value_present':False}]}
    def snapshot(self,tab):return copy.deepcopy(self.pages[tab]),[0,1]
    def navigate(self,tab,url):self.actions.append(('navigate',tab,url));self.pages[tab]['url']=url
    def close(self,tab):del self.pages[tab]
    def wait(self,tab,seconds):pass
    def act(self,tab,element,operation,args,files):
        if self.before:self.before()
        self.actions.append((operation,tab,element))
        if operation=='fill':self.pages[tab]['controls'][element]['value_present']=True
        if self.fail:raise OSError('Lost page response after action')
        self.pages[tab]['text']='Submitted' if operation=='click' else 'Edited'


class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.driver=Driver()
        self.session=Session(self.db,'job',policy(),self.driver)
        self.page=self.session.call('open','browser_open',{'url':'https://example.test/work'})
    def tearDown(self):self.db.close()
    def target(self,page=None,**extra):
        page=page or self.page
        return dict(tab=page['tab'],observation=page['observation'],ref='1',purpose='Submit requested fixture',**extra)

    def test_completed_duplicate_returns_exact_receipt_even_after_detach(self):
        args=self.target();result=self.session.call('submit','browser_click',args)
        reopened=Session(self.db,'job',policy(),Driver())
        self.assertEqual(reopened.call('submit','browser_click',args),result)
        self.assertEqual(len(self.driver.actions),1)
        with self.assertRaisesRegex(ValueError,'identity'):
            reopened.call('submit','browser_click',{**args,'purpose':'changed'})

    def test_lost_result_blocks_new_id_and_survives_reopen_until_operator_resolution(self):
        self.driver.fail=True
        with self.assertRaises(UncertainAction):self.session.call('submit','browser_click',self.target())
        reopened=Session(self.db,'next-job',policy(),Driver())
        page=reopened.call('open','browser_open',{'url':'https://example.test/work'})
        with self.assertRaises(UncertainAction):reopened.call('resubmit','browser_click',self.target(page))
        self.assertEqual(len(self.driver.actions),1);self.assertEqual(len(reopened.driver.actions),0)
        reopened.journal.resolve('fixture','job','submit','occurred','Inspected the saved remote result')
        with self.assertRaises(UncertainAction):self.session.call('submit','browser_click',self.target())
        self.assertFalse(reopened.journal.pending('fixture'))
        self.assertEqual(self.db.execute("SELECT count(*) FROM general_browser_events WHERE kind='operator_resolution'").fetchone()[0],1)

    def test_external_dispatch_observes_committed_intent_and_nested_transaction_refused(self):
        def committed():
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(self.session.journal.pending('fixture')[0]['status'],'intent')
        self.driver.before=committed
        self.session.call('submit','browser_click',self.target())
        page=self.session.call('read','browser_read',{'tab':self.page['tab']})
        self.db.execute('BEGIN IMMEDIATE')
        with self.assertRaisesRegex(ValueError,'commit'):self.session.call('nested','browser_click',self.target(page))
        self.db.rollback();self.assertEqual(len(self.driver.actions),1)

    def test_stale_observation_cannot_click_replacement_page(self):
        self.driver.pages[self.page['tab']]['text']='Changed'
        with self.assertRaisesRegex(ValueError,'changed'):self.session.call('click','browser_click',self.target())
        self.assertEqual(self.driver.actions,[])
        self.assertIsNone(self.db.execute("SELECT 1 FROM general_browser_actions WHERE id='click'").fetchone())

    def test_tabs_have_stable_identity_and_closed_tabs_are_never_retargeted(self):
        other=self.session.call('second','browser_open',{'url':'https://example.test/other'})
        self.session.call('close','browser_close',{'tab':self.page['tab']})
        with self.assertRaisesRegex(ValueError,'detached'):self.session.call('click','browser_click',self.target())
        self.assertEqual(set(self.driver.pages),{other['tab']})

    def test_out_of_scope_origins_passwords_drafts_and_file_transfers_are_rejected(self):
        for url in ('https://elsewhere.test','file:///etc/passwd','https://user:pass@example.test','http://example.test','https://example.test@elsewhere.test'):
            with self.assertRaises(ValueError):self.session.call('outside','browser_open',{'url':url})
        controls=self.driver.pages[self.page['tab']]['controls']
        for index,descriptor in enumerate(({'type':'password'},{'autocomplete':'one-time-code'},{'value_present':True})):
            controls[0].update(type='text',autocomplete='',value_present=False);controls[0].update(descriptor)
            page=self.session.call('read-'+str(index),'browser_read',{'tab':self.page['tab']})
            args={**self.target(page),'ref':'0','text':'secret'}
            with self.assertRaises(ValueError):self.session.call('fill','browser_fill',args)
        with self.assertRaisesRegex(ValueError,'grant'):
            self.session.call('upload','browser_upload',{**self.target(page),'path':'undeclared.txt'})
        self.assertFalse(self.driver.actions)

    def test_read_only_scope_allows_navigation_but_not_form_submission(self):
        self.session.policy['interaction_scope']=''
        with self.assertRaisesRegex(ValueError,'reading'):self.session.call('submit','browser_click',self.target())
        self.driver.pages[self.page['tab']]['controls'][1]={'tag':'A','href':'https://example.test/next'}
        page=self.session.call('read','browser_read',{'tab':self.page['tab']})
        self.session.call('follow','browser_click',self.target(page))
        self.assertEqual(self.driver.actions[0][0],'navigate')

    def test_scope_block_on_navigation_returns_receipt_and_allows_other_page_without_replay(self):
        args={'tab':self.page['tab'],'url':'https://example.test/redirect'}
        detail={'url':'https://consent.example.test','requested_url':args['url'],'reason':'outside permitted website origins'}
        with patch.object(self.driver,'navigate',side_effect=NavigationBlocked(detail)) as navigate:
            result=self.session.call('redirect','browser_navigate',args)
            self.assertEqual(result['outcome'],'blocked');self.assertEqual(result['blocked_navigation'],detail)
            self.assertEqual(self.session.call('redirect','browser_navigate',args),result)
            navigate.assert_called_once();self.assertFalse(self.session.journal.pending('fixture'))
        page=self.session.call('alternative','browser_navigate',{**args,'url':'https://example.test/other'})
        self.assertEqual(page['url'],'https://example.test/other')

    def test_scope_block_after_submission_still_preserves_uncertainty(self):
        detail={'url':'https://elsewhere.test','requested_url':'https://example.test/submit','reason':'outside permitted website origins'}
        with patch.object(self.driver,'act',side_effect=NavigationBlocked(detail)) as act:
            with self.assertRaises(UncertainAction):self.session.call('submit','browser_click',self.target())
            with self.assertRaises(UncertainAction):self.session.call('submit','browser_click',self.target())
            act.assert_called_once()
        self.assertEqual(self.session.journal.pending('fixture')[0]['id'],'submit')

    def test_action_limit_cancel_and_crash_intents_prevent_extra_work(self):
        self.session.policy['max_actions']=1
        with self.assertRaisesRegex(ValueError,'limit'):self.session.call('read','browser_read',{'tab':self.page['tab']})
        self.session.cancelled=lambda:True
        with self.assertRaisesRegex(ValueError,'Cancelled'):self.session.call('cancel','browser_open',{'url':'https://example.test'})
        self.session.journal.claim('fixture','lost-job','lost','browser_click',{},20,True)
        self.assertEqual(Journal(self.db).pending('fixture')[0]['status'],'intent')

    def test_contract_binds_transfers_and_prevents_repeating_browser_review(self):
        c.plan(browser_graph())
        for change in ('review_scope','grant','retry','backend'):
            p=browser_graph()
            if change=='review_scope':p['tasks'][1]['browser']['interaction_scope']='Send again'
            elif change=='grant':p['tasks'][0]['browser']['uploads']=['secret.txt']
            elif change=='retry':p['tasks'][0]['max_attempts']=2
            else:p['backend']['type']='gemini-agent'
            with self.assertRaises(ValueError):c.plan(p)
        for origins in (['https://example.test/'],['https://*.test'],['file:///tmp'],[]):
            with self.assertRaises(ValueError):validate(policy(origins=origins))
        self.assertEqual(origin('http://127.0.0.1:123/work'),'http://127.0.0.1:123')

    def test_profile_has_single_owner_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            with profile_lock(folder,'fixture'):
                with self.assertRaises(OSError):
                    with profile_lock(folder,'fixture'):self.fail('Two profile owners')
            root=Path(folder)/'browser-general'/'other';root.symlink_to(Path(folder)/'browser-general'/'fixture',target_is_directory=True)
            with self.assertRaises(ValueError):
                with profile_lock(folder,'other'):self.fail('Symlink profile')

    def test_case_alias_cannot_bypass_profile_uncertainty(self):
        self.driver.fail=True
        with self.assertRaises(UncertainAction):self.session.call('submit','browser_click',self.target())
        with self.assertRaisesRegex(ValueError,'lowercase'):Session(self.db,'next',policy(profile='Fixture'),Driver())
        self.assertEqual(len(self.driver.actions),1)

    def test_scheduler_serializes_same_profile_across_jobs(self):
        from orchestrator.runtime import Runtime
        from tests.test_orchestrator import FakeFactory
        with tempfile.TemporaryDirectory() as folder:
            factory=FakeFactory();runtime=Runtime(Path(folder)/'runtime',factory)
            try:
                first=browser_graph();first['tasks']=first['tasks'][:1]
                second=copy.deepcopy(first);second['id']='second'
                runtime.create(first);runtime.create(second);runtime.tick('demo');runtime.tick('second')
                self.assertEqual(len(factory.calls),1)
                factory.finish(factory.calls[0]);runtime.tick('demo');runtime.tick('second')
                self.assertEqual(len(factory.calls),2)
            finally:runtime.db.close()


if __name__=='__main__':unittest.main()
