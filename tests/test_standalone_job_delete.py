"""Standalone result ownership, shared history and interrupted cleanup."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay.bridge import State
from task_relay import job_ownership
from task_relay.desktop_library import workflows
from task_relay.job_delete import JobDeleteError, delete, preview, recover_pending
from task_relay.shared_history_delete import (
    SharedHistoryDeleteError, available as available_history,
    forget as forget_history, preview as preview_history)
from task_relay.relay_paths import Paths
from task_relay.desktop_bridge import _dispatch


class StandaloneDeleteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root/'app', root/'data', root/'workspaces', root/'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        with transaction(self.state.db):
            self.state.db.execute('''INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,calls,created,run,token,expires)
                VALUES ('plan-one',2,'telegram','Exact standalone request','{}','{}','hash','fixture','fixture','started',0,1,'run-one','token',1)''')
            self.state.db.execute("INSERT INTO production_runs VALUES ('run-one','{}','completed')")
            self.state.db.execute("INSERT INTO production_tasks (run,id,assignment,status,attempts) VALUES ('run-one','task','assignment','completed',1)")
            self.state.db.execute("INSERT INTO production_attempts (id,run,task,assignment,state,frozen,session) VALUES ('attempt','run-one','task','assignment','completed','{}','{}')")
            self.state.db.execute("INSERT INTO production_artifacts (id,run,task,attempt,path,blob,sha256,bytes,purpose,source) VALUES ('artifact','run-one','task','attempt','report.txt','blob','hash',1,'delivery','{}')")
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,status,created) VALUES (2,'Exact standalone request','fixture','fixture','answered',1)")
            self.state.db.execute("INSERT INTO incoming VALUES (2,'handled',NULL)")
            self.state.db.execute("INSERT INTO orchestrator_messages VALUES (1,3,'run-one')")
            self.state.db.execute("INSERT INTO relay_request_channels VALUES (2,'telegram')")
            self.state.db.execute("INSERT INTO outbox(id,text,sent) VALUES ('production:run-one:files-ready','Delivered',1)")
            self.state.db.execute("INSERT INTO outbox_parts(event_id,part,text,sent) VALUES ('production:run-one:files-ready',1,'Delivered',1)")
            job_ownership.record_standalone(self.state.db, 'plan-one', 'run-one', 'telegram')
        self.pid = job_ownership.standalone_id('plan-one')
        self.folder = self.paths.generated/'workflows'/self.pid
        (self.folder/'.relay').mkdir(parents=True)
        (self.folder/'.relay'/'job.sqlite').write_bytes(b'private view')
        (self.folder/'01-results').mkdir()
        (self.folder/'01-results'/'report.txt').write_text('Native copy')
        (self.folder/'.relay-workflow.json').write_text(json.dumps({'workflow':self.pid}))

    def test_deletes_exact_job_and_retains_shared_conversation_and_native_file(self):
        listed = workflows('runs', paths=self.paths)['items']
        self.assertEqual(listed[0]['job_id'], self.pid)
        self.assertTrue(listed[0]['job_view'].endswith('/.relay/job.sqlite'))
        review = preview(self.pid, self.paths)
        self.assertEqual(review['blockers'], [])
        self.assertTrue(review['shared_history_preserved'])
        self.assertEqual(review['runs'], ['run-one'])
        self.assertEqual(delete(self.pid, review['digest'], self.paths)['status'], 'complete')
        for table in ('relay_standalone_jobs','production_plans','production_runs',
                      'production_tasks','production_attempts','production_artifacts'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        for table in ('orchestrator_chats','orchestrator_messages','relay_request_channels',
                      'outbox','outbox_parts'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 1)
        self.assertFalse((self.folder/'.relay').exists())
        self.assertTrue((self.folder/'01-results'/'report.txt').exists())

    def test_separate_history_action_forgets_only_sent_local_text(self):
        review = preview(self.pid, self.paths)
        self.assertEqual(delete(self.pid, review['digest'], self.paths)['status'], 'complete')
        self.assertEqual(available_history(self.paths),
                         [{'id':self.pid,'events':1,'channel':'telegram'}])
        history = preview_history(self.pid, self.paths)
        self.assertEqual(history['blockers'], [])
        self.assertEqual((history['events'],history['parts']), (1,1))
        self.assertEqual(forget_history(self.pid,history['digest'],self.paths)['status'],'complete')
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox').fetchone()[0], '')
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox_parts').fetchone()[0], '')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],
                         0)
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=2').fetchone()[0],
                         'handled')
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox_parts').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT focus FROM orchestrator_messages').fetchone()[0],
                         'run-one')
        self.assertEqual(forget_history(self.pid,history['digest'],self.paths)['status'],'complete')
        self.assertEqual(available_history(self.paths),[])

    def test_history_action_is_atomic_if_request_cleanup_fails(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        history = preview_history(self.pid,self.paths)
        with transaction(self.state.db):
            self.state.db.execute('''CREATE TRIGGER history_failure BEFORE DELETE ON orchestrator_chats
                BEGIN SELECT RAISE(ABORT,'interrupted'); END''')
        with self.assertRaisesRegex(Exception,'interrupted'):
            forget_history(self.pid,history['digest'],self.paths)
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox').fetchone()[0],
                         'Delivered')
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox_parts').fetchone()[0],
                         'Delivered')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],
                         1)
        self.assertIsNone(self.state.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='relay_shared_history_receipts'").fetchone())

    def test_bridge_history_actions_use_reviewed_runtime_contract(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        with patch('task_relay.shared_history_delete.available',
                   side_effect=lambda: available_history(self.paths)), \
             patch('task_relay.shared_history_delete.preview',
                   side_effect=lambda ident: preview_history(ident,self.paths)), \
             patch('task_relay.shared_history_delete.forget',
                   side_effect=lambda ident,digest: forget_history(ident,digest,self.paths)):
            self.assertEqual(len(_dispatch('shared-history-list',{})['items']),1)
            history = _dispatch('shared-history-preview',{'id':self.pid})
            self.assertEqual(history['blockers'],[])
            self.assertEqual(_dispatch('shared-history-forget',
                                       {'id':self.pid,'digest':history['digest']})['status'],
                             'complete')

    def test_history_action_blocks_changed_pending_and_shared_delivery(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        history = preview_history(self.pid,self.paths)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE outbox_parts SET text='Changed'")
        with self.assertRaisesRegex(SharedHistoryDeleteError,'changed'):
            forget_history(self.pid,history['digest'],self.paths)
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox_parts SET sent=0')
        self.assertIn('A retained delivery part is pending.',
                      preview_history(self.pid,self.paths)['blockers'])
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox_parts SET sent=1')
            self.state.db.execute('CREATE TABLE other_delivery(event_id TEXT)')
            self.state.db.execute("INSERT INTO other_delivery VALUES ('production:run-one:files-ready')")
        self.assertIn('Another Relay record references a retained delivery.',
                      preview_history(self.pid,self.paths)['blockers'])

    def test_legacy_deletion_does_not_guess_shared_history_from_event_prefix(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        with transaction(self.state.db):
            self.state.db.execute('UPDATE relay_delete_receipts SET shared_history=NULL WHERE id=?',
                                  (self.pid,))
        with self.assertRaisesRegex(SharedHistoryDeleteError,'older deletion'):
            preview_history(self.pid,self.paths)
        self.assertEqual(available_history(self.paths),[])
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox').fetchone()[0],
                         'Delivered')

    def test_history_refuses_missing_request_deduplication(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        with transaction(self.state.db):
            self.state.db.execute('DELETE FROM incoming WHERE id=2')
        history = preview_history(self.pid,self.paths)
        self.assertIn('A retained request lacks a completed deduplication record.',
                      history['blockers'])
        with self.assertRaisesRegex(SharedHistoryDeleteError,'blocked'):
            forget_history(self.pid,history['digest'],self.paths)

    def test_history_refuses_task_routed_or_unbound_request(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE incoming SET thread_id='another-task' WHERE id=2")
        self.assertIn('A retained request lacks a completed deduplication record.',
                      preview_history(self.pid,self.paths)['blockers'])
        with transaction(self.state.db):
            self.state.db.execute('UPDATE incoming SET thread_id=NULL WHERE id=2')
            self.state.db.execute('DELETE FROM relay_request_channels WHERE request_id=2')
        self.assertIn('A retained request belongs to another channel.',
                      preview_history(self.pid,self.paths)['blockers'])

    def test_history_refuses_late_request_delivery(self):
        review = preview(self.pid,self.paths)
        self.assertEqual(delete(self.pid,review['digest'],self.paths)['status'],'complete')
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO outbox(id,text,sent) VALUES ('orchestrator:2:late','Late',1)")
        self.assertIn('A conversation request has an unrecorded delivery.',
                      preview_history(self.pid,self.paths)['blockers'])

    def test_pending_shared_delivery_and_other_job_dependency_block(self):
        with transaction(self.state.db):
            self.state.db.execute("UPDATE outbox_parts SET sent=0 WHERE event_id='production:run-one:files-ready'")
        review = preview(self.pid, self.paths)
        self.assertIn('A shared channel delivery part is still pending.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(self.pid, review['digest'], self.paths)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE outbox_parts SET sent=1 WHERE event_id='production:run-one:files-ready'")
            self.state.db.execute('''INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,calls,created,token,expires)
                VALUES ('outside',3,'telegram','Reuse','{}',?,'hash','fixture','fixture','started',0,2,'outside',1)''',
                (json.dumps({'sources':[{'artifact':'artifact'}]}),))
        review = preview(self.pid, self.paths)
        self.assertIn('Another plan uses an output artifact from this job.', review['blockers'])

    def test_cleanup_interruption_retries_without_database_deletion_replay(self):
        review = preview(self.pid, self.paths)
        with patch('task_relay.job_delete.shutil.rmtree', side_effect=OSError('interrupted')):
            self.assertEqual(delete(self.pid, review['digest'], self.paths)['status'], 'cleanup_pending')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_standalone_jobs').fetchone()[0], 0)
        self.assertEqual(recover_pending(self.paths)[0]['status'], 'complete')
        self.assertEqual(delete(self.pid, review['digest'], self.paths)['status'], 'complete')

    def test_changed_root_request_blocks_deletion(self):
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET request='Changed' WHERE id='plan-one'")
        review = preview(self.pid, self.paths)
        self.assertIn('The standalone root request or channel changed.', review['blockers'])

    def test_unrelated_run_cannot_be_claimed_by_existing_root(self):
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO production_runs VALUES ('other-run','{}','completed')")
            with self.assertRaisesRegex(ValueError, 'different plan ancestry'):
                job_ownership.record_standalone(self.state.db, 'plan-one', 'other-run', 'telegram')
        owner = self.state.db.execute('SELECT last_run FROM relay_standalone_jobs WHERE id=?',
                                      (self.pid,)).fetchone()
        self.assertEqual(owner['last_run'], 'run-one')

    def test_historical_selected_result_gets_explicit_verified_backfill(self):
        (self.folder/'.relay'/'job.sqlite').unlink()  # Older result exports lack this projection.
        with transaction(self.state.db):
            self.state.db.execute('DELETE FROM relay_standalone_jobs WHERE id=?', (self.pid,))
            self.state.db.execute("INSERT INTO production_decisions VALUES ('decision','run-one','task','artifact','Selection','Exact selected version',1)")
        listed = workflows('runs', paths=self.paths)['items'][0]
        self.assertEqual(listed['job_id'], self.pid)
        self.assertTrue(listed['registration_needed'])
        self.assertIsNone(listed['job_view'])
        self.assertEqual(job_ownership.backfill_standalone('run-one', self.paths), self.pid)
        self.assertFalse(workflows('runs', paths=self.paths)['items'][0]['registration_needed'])
        self.assertEqual(preview(self.pid, self.paths)['blockers'], [])

    def test_unsent_historical_result_cannot_be_registered(self):
        with transaction(self.state.db):
            self.state.db.execute('DELETE FROM relay_standalone_jobs WHERE id=?', (self.pid,))
            self.state.db.execute("INSERT INTO production_decisions VALUES ('decision','run-one','task','artifact','Selection','Exact selected version',1)")
            self.state.db.execute("UPDATE outbox SET sent=0 WHERE id='production:run-one:files-ready'")
        self.assertNotIn('job_id', workflows('runs', paths=self.paths)['items'][0])
        with self.assertRaisesRegex(ValueError, 'No exact selected'):
            job_ownership.backfill_standalone('run-one', self.paths)

    def test_external_plan_selected_artifact_and_run_block_deletion(self):
        with transaction(self.state.db):
            self.state.db.execute('''INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,calls,created,token,expires)
                VALUES ('outside',3,'telegram','Continue from this result',?,'{}','hash','fixture','fixture','ready',0,2,'outside',1)''',
                (json.dumps({'artifact_ids':['artifact'], 'previous_run':'run-one'}),))
        review = preview(self.pid, self.paths)
        self.assertIn('Another plan selects an output artifact from this job.', review['blockers'])
        self.assertIn('Another plan continues this job’s run.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(self.pid, review['digest'], self.paths)
