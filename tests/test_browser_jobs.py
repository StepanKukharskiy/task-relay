import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from task_relay.browser_jobs import Journal,conversation_url,execute

URL='https://www.perplexity.ai/search/11111111-2222-3333-4444-555555555555'
OTHER='https://www.perplexity.ai/search/66666666-2222-3333-4444-555555555555'


class Driver:
    def __init__(self,url=None):
        self.sent=[];self.opens=[];self.error=None;self.ready=True;self.after_send=None
        self.state={'url':url or 'https://www.perplexity.ai/','text':'History','queries':0,'answers':0,'ready':True}
    def open(self,url):self.opens.append(url)
    def snapshot(self):return copy.deepcopy(self.state)
    def check_ready(self,state):
        if not self.ready:raise ValueError('Sign in first')
    def submit(self,prompt,baseline):
        self.sent.append(prompt)
        self.state.update(url=URL,text=self.state['text']+'\n'+prompt+'\nAnswer',queries=self.state['queries']+1,answers=self.state['answers']+1)
        if self.after_send:self.after_send()
        if self.error:raise self.error
    def pause(self):raise ValueError('No matching completion')


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite'
        self.db=sqlite3.connect(self.path);self.journal=Journal(self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_new_and_continued_turn_keep_url_exact_prompt_and_receipts(self):
        driver=Driver();prompt=' Exact request with\nnewlines '
        self.journal.prepare('first',prompt)
        driver.after_send=lambda:self.assertEqual(self.journal.get('first')['status'],'submitting')
        result=execute(self.journal,'first',driver)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['url'],URL)
        self.assertEqual(driver.sent,[prompt]);self.assertEqual(result['prompt'],prompt)
        self.journal.prepare('second','Continue',URL);driver.after_send=None
        result=execute(self.journal,'second',driver)
        self.assertEqual(result['status'],'completed');self.assertEqual(driver.opens,[None,URL])
        self.assertIn(prompt,result['result']);self.assertIn('Continue',result['result'])
    def test_completed_receipt_is_idempotent_and_identity_cannot_change(self):
        driver=Driver();self.journal.prepare('once','hello');execute(self.journal,'once',driver)
        self.journal.prepare('once','hello');execute(self.journal,'once',driver)
        self.assertEqual(driver.sent,['hello']);self.assertEqual(len(driver.opens),1)
        with self.assertRaises(ValueError):self.journal.prepare('once','changed')
        with self.assertRaises(ValueError):self.journal.prepare('once','hello',URL)
    def test_restart_after_accepted_enter_reconciles_without_resubmission(self):
        driver=Driver();driver.error=TimeoutError('Reply was lost')
        self.journal.prepare('uncertain','hello')
        self.assertEqual(execute(self.journal,'uncertain',driver)['status'],'uncertain')
        self.db.close();self.db=sqlite3.connect(self.path);self.journal=Journal(self.db)
        with self.assertRaises(ValueError):execute(self.journal,'uncertain',driver)
        with self.assertRaises(ValueError):execute(self.journal,'uncertain',driver,reconcile=True)
        result=execute(self.journal,'uncertain',driver,reconcile=True,url=URL)
        self.assertEqual(result['status'],'completed');self.assertEqual(driver.sent,['hello'])
    def test_preflight_failure_can_be_explicitly_retried_without_resending(self):
        driver=Driver();driver.ready=False;self.journal.prepare('login','hello')
        self.assertEqual(execute(self.journal,'login',driver)['status'],'blocked')
        self.assertEqual(driver.sent,[]);driver.ready=True
        self.assertEqual(execute(self.journal,'login',driver)['status'],'completed')
    def test_changed_conversation_and_extra_turns_are_uncertain(self):
        driver=Driver(URL);self.journal.prepare('changed','hello',URL)
        driver.after_send=lambda:driver.state.update(url=OTHER)
        self.assertEqual(execute(self.journal,'changed',driver)['status'],'uncertain')
        with self.assertRaises(ValueError):self.journal.prepare('another','next',URL)
        with self.assertRaises(ValueError):execute(self.journal,'changed',driver,reconcile=True,url=OTHER)
        driver.state.update(url=URL,queries=2,answers=2)
        self.assertEqual(execute(self.journal,'changed',driver,reconcile=True)['status'],'uncertain')
        self.assertEqual(driver.sent,['hello'])
    def test_missing_or_incomplete_answer_is_not_completion(self):
        driver=Driver();self.journal.prepare('partial','hello')
        driver.after_send=lambda:driver.state.update(answers=0,ready=False)
        self.assertEqual(execute(self.journal,'partial',driver)['status'],'uncertain')
        self.assertEqual(self.journal.get('partial')['url'],URL)
        self.assertIsNone(self.journal.get('partial')['result'])
    def test_claim_race_cannot_reopen_the_receipt(self):
        driver=Driver();self.journal.prepare('race','hello')
        def competing_claim(state):self.journal.claim('race',state)
        driver.check_ready=competing_claim
        self.assertEqual(execute(self.journal,'race',driver)['status'],'submitting')
        self.assertEqual(driver.sent,[])
    def test_invalid_targets_are_rejected_before_browser_use(self):
        for url in ('http://www.perplexity.ai/search/x','https://evil.test/search/x',
                    URL+'?x=1',URL+'#x',URL.replace('www.','user@www.'),
                    'https://www.perplexity.ai/computer/tasks/test'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):self.journal.prepare('invalid','hello',url)
        self.assertEqual(conversation_url(URL),URL)
    def test_journal_transactions_roll_back_claim_and_event_together(self):
        self.journal.prepare('failure','hello')
        self.db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON browser_job_events WHEN new.status='submitting' BEGIN SELECT RAISE(ABORT,'write failed'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.journal.claim('failure',Driver().snapshot())
        self.assertEqual(self.journal.get('failure')['status'],'prepared')
        self.assertIsNone(self.journal.get('failure')['baseline'])


if __name__=='__main__':unittest.main()
