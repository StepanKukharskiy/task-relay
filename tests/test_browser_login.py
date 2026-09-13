"""Credential routing/recovery with small fixtures and real in-memory pipes."""
import io
import json
import os
import sqlite3
import time
import unittest
from unittest.mock import Mock,patch
from task_relay import browser_login as login,browser_setup,host_login,providers,orchestrator_chat
from tests import test_providers as fixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    send=fixtures.Tests.send
    click=fixtures.Tests.click

    def start(self):
        self.send('/browser chat')
        row=self.state.db.execute("SELECT * FROM provider_jobs WHERE provider='perplexity' ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual(row['operation'],'browser_chat_login')
        with self.state.db:self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=?",(row['id'],))
        return row['id']

    def prompt(self,job,kind='email'):
        token=login.request_input(self.state,job,kind)
        self.bridge.flush()
        row=self.state.db.execute('SELECT * FROM browser_login_inputs WHERE id=?',(token,)).fetchone()
        self.assertIsNotNone(row['prompt_id'])
        return row

    def pipe(self,job):
        read,write=os.pipe()
        reader,writer=os.fdopen(read,'rb',buffering=0),os.fdopen(write,'wb',buffering=0)
        host_login.register(login.data(self.state),job,writer)
        self.addCleanup(host_login.forget,login.data(self.state),job)
        self.addCleanup(reader.close)
        return host_login.Inbox(reader)

    def test_reply_uses_pipe_once_and_never_reaches_model_or_saved_history(self):
        job=self.start();row=self.prompt(job);inbox=self.pipe(job)
        value='fixture-person@example.test'
        with patch.object(orchestrator_chat,'handle',side_effect=AssertionError('Credential reached model routing')):
            ident=self.send(value,reply=row['prompt_id'])
            envelope=inbox.poll()
            self.assertEqual(envelope,{'challenge':row['id'],'value':value})
            self.send('another-fixture@example.test',reply=row['prompt_id'])
        self.assertIsNone(inbox.poll())
        self.assertNotIn(value,'\n'.join(self.state.db.iterdump()))
        self.assertNotIn(value,str(self.bot.sent))
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=?',(ident,)).fetchone()[0],'handled')
        providers.delete_pending(self.state,self.bot)
        self.assertIn(('deleteMessage',{'chat_id':123,'message_id':ident}),self.bot.calls)

    def test_expired_cancelled_and_orphaned_replies_are_consumed_without_dispatch(self):
        job=self.start();row=self.prompt(job)
        with self.state.db:self.state.db.execute('UPDATE browser_login_inputs SET expires=0')
        with patch.object(host_login,'send') as send,patch.object(orchestrator_chat,'handle',side_effect=AssertionError('Leaked')):
            self.send('fixture-expired',reply=row['prompt_id'])
            browser_setup.command(self.state,'cancel','fixture-cancel')
            self.send('fixture-cancelled',reply=row['prompt_id'])
            self.uid+=1
            self.bridge.process({'update_id':self.uid,'message':{'message_id':self.uid,'text':'fixture-orphan',
                'chat':{'id':123,'type':'private'},'from':{'id':123},
                'reply_to_message':{'message_id':-999,'text':'Perplexity sign-in · https://www.perplexity.ai\nReply'}}})
            send.assert_not_called()
        saved='\n'.join(self.state.db.iterdump())
        for secret in ('fixture-expired','fixture-cancelled','fixture-orphan'):self.assertNotIn(secret,saved)

    def test_unthreaded_input_during_login_is_not_a_task(self):
        job=self.start();self.prompt(job)
        with patch.object(host_login,'send') as send,patch.object(orchestrator_chat,'handle',side_effect=AssertionError('Leaked')):
            self.send('fixture-unthreaded-password')
            send.assert_not_called()
        self.assertNotIn('fixture-unthreaded-password','\n'.join(self.state.db.iterdump()))

    def test_unauthorized_reply_cannot_claim_prompt(self):
        job=self.start();row=self.prompt(job)
        with patch.object(host_login,'send') as send:
            self.send('fixture-unauthorized',user=999,reply=row['prompt_id'])
            send.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs').fetchone()[0],'waiting')

    def test_claim_commits_before_pipe_write_and_lost_delivery_is_not_replayed(self):
        job=self.start();row=self.prompt(job)
        def lost(*args):
            self.assertFalse(self.state.db.in_transaction)
            self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs').fetchone()[0],'claimed')
            raise OSError('fixture-secret-must-not-escape')
        with patch.object(host_login,'send',side_effect=lost) as send:
            self.send('fixture-secret-must-not-escape',reply=row['prompt_id'])
            self.send('fixture-secret-must-not-escape',reply=row['prompt_id'])
            self.assertEqual(send.call_count,1)
        self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs').fetchone()[0],'uncertain')
        self.assertNotIn('fixture-secret-must-not-escape','\n'.join(self.state.db.iterdump()))
        self.assertNotIn('fixture-secret-must-not-escape',str(self.bot.sent))

    def test_transaction_failure_does_not_deliver_and_keeps_prompt_waiting(self):
        job=self.start();row=self.prompt(job)
        self.state.db.execute("CREATE TRIGGER fail_login BEFORE UPDATE ON browser_login_inputs BEGIN SELECT RAISE(ABORT,'fixture write failure'); END")
        with patch.object(host_login,'send') as send:
            with self.assertRaises(sqlite3.IntegrityError):self.send('fixture-value',reply=row['prompt_id'])
            send.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs').fetchone()[0],'waiting')

    def test_restart_expires_prompts_and_retains_uncertain_input_metadata(self):
        job=self.start();row=self.prompt(job)
        with self.state.db:self.state.db.execute("UPDATE browser_login_inputs SET status='submitting'")
        providers.Worker(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs').fetchone()[0],'uncertain')
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs').fetchone()[0],'failed')
        with patch.object(host_login,'send') as send:
            self.send('fixture-after-restart',reply=row['prompt_id'])
            send.assert_not_called()

    def test_email_and_code_complete_with_fresh_challenges_and_no_retained_values(self):
        job=self.start();pipe=self.pipe(job)
        driver=Mock();stages=iter(['email','code','ready']);current=['email'];received=[]
        driver.login_stage.side_effect=lambda:current[0]
        def submit(kind,value,identity):
            self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs ORDER BY created DESC LIMIT 1').fetchone()[0],'submitting')
            received.append((kind,value));current[0]='code' if kind=='email' else 'ready'
        driver.login_submit.side_effect=submit
        def poll():
            self.bridge.flush()
            row=self.state.db.execute('SELECT * FROM browser_login_inputs ORDER BY created DESC LIMIT 1').fetchone()
            self.send('fixture-email@example.test' if row['kind']=='email' else '123456',reply=row['prompt_id'])
            return pipe.poll()
        login.run(self.state,job,driver,Mock(poll=poll),timeout=5)
        self.assertEqual(received,[('email','fixture-email@example.test'),('code','123456')])
        self.assertEqual(self.state.db.execute('SELECT status FROM provider_jobs').fetchone()[0],'completed')
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM browser_login_inputs WHERE status='consumed'").fetchone()[0],2)
        saved='\n'.join(self.state.db.iterdump())
        self.assertNotIn('fixture-email@example.test',saved);self.assertNotIn('123456',saved)
        driver.submit.assert_not_called()

    def test_browser_challenge_requests_no_credential_and_cancel_stops(self):
        job=self.start();driver=Mock();driver.login_stage.return_value='manual'
        driver.pause.side_effect=lambda:browser_setup.command(self.state,'cancel','cancel-challenge')
        inbox=Mock()
        login.run(self.state,job,driver,inbox,timeout=5)
        inbox.poll.assert_not_called();driver.login_submit.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_login_inputs').fetchone()[0],0)

    def test_wrong_challenge_or_cancellation_before_submit_never_fills_browser(self):
        for cancel in (False,True):
            job=self.start();driver=Mock();driver.login_stage.return_value='email'
            def poll():
                token=self.state.db.execute('SELECT id FROM browser_login_inputs WHERE job=?',(job,)).fetchone()[0]
                if cancel:browser_setup.command(self.state,'cancel','cancel-'+job)
                return {'challenge':token if cancel else 'wrong','value':'fixture-never-filled'}
            with self.assertRaises(ValueError):login.run(self.state,job,driver,Mock(poll=poll),timeout=5)
            driver.login_submit.assert_not_called()
            browser_setup.command(self.state,'cancel','finish-'+job)

    def test_messages_chat_mode_is_rejected_without_queue(self):
        with self.assertRaisesRegex(ValueError,'Telegram'):
            browser_setup.command(self.state,'chat','messages-fixture','messages')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0],0)

    def test_worker_pipe_is_registered_after_commit_and_removed_on_exit(self):
        import subprocess
        self.send('/browser chat')
        job=self.state.db.execute('SELECT id FROM provider_jobs').fetchone()[0]
        read,write=os.pipe()
        reader,writer=os.fdopen(read,'rb',buffering=0),os.fdopen(write,'wb',buffering=0)
        self.addCleanup(reader.close)
        self.addCleanup(host_login.forget,login.data(self.state),job)
        process=Mock(stdin=writer);process.poll.return_value=None
        def spawn(command,**kwargs):
            self.assertFalse(self.state.db.in_transaction)
            self.assertEqual(kwargs['stdin'],subprocess.PIPE)
            return process
        with patch.object(providers.HOST,'browser_python',return_value='/fixture/python'),patch.object(providers.HOST,'spawn',side_effect=spawn):
            worker=providers.Worker(self.state);worker.tick()
        row=self.prompt(job)
        self.send('fixture-worker@example.test',reply=row['prompt_id'])
        self.assertEqual(host_login.Inbox(reader).poll()['value'],'fixture-worker@example.test')
        process.poll.return_value=0
        worker.tick()
        self.assertTrue(writer.closed)
        self.assertEqual(self.state.db.execute('SELECT status FROM browser_login_inputs').fetchone()[0],'uncertain')


if __name__=='__main__':unittest.main()
