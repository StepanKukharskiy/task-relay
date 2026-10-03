"""Standalone Desktop history deletion: reviewed identity, atomicity and recovery."""
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from tests import test_shared_orchestrator as fixture
from task_relay import conversation_delete as delete, desktop_plans, desktop_workspace, orchestrator_chat as chat, desktop_bridge


class DeleteTests(unittest.TestCase):
    setUp=fixture.SharedTests.setUp
    create_conversation=fixture.SharedTests.create_conversation

    def record(self):
        self.original=self.paths.data/'input.txt';self.original.write_text('A frozen input.')
        receipt=self.create_conversation(files=[str(self.original)])
        self.request_id=receipt['request_id']
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        with patch.object(chat,'snapshot',return_value={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}), patch.object(chat.gemini,'DATA',self.paths.data):
            chat.Worker(self.state,generator=lambda *_:json.dumps(fixture.REPLY)).tick()
        self.ident=str(self.state.db.execute('SELECT id FROM orchestrator_chats').fetchone()[0])
        self.event='orchestrator:'+self.ident
        with self.state.db:
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(self.event,))
            self.state.db.execute('INSERT INTO outbox_parts(event_id,part,text,sent) VALUES (?,?,?,1)',(self.event,1,'Saved delivered text.'))
        self.trace=self.paths.data/'orchestrator-reads'/(hashlib.sha256(self.ident.encode()).hexdigest()+'.json')
        self.trace.parent.mkdir(exist_ok=True);self.trace.write_text('Private fixture trace.')
        self.review=delete.preview(self.ident,self.paths)
        self.assertEqual(self.review['blockers'],[],self.review['blockers'])
        return self.review

    def test_delete_clears_local_text_keeps_frozen_files_and_prevents_receipt_replay(self):
        review=self.record();view=desktop_workspace.chat_detail(self.ident,self.paths)
        self.assertTrue(view['can_delete']);frozen=Path(view['files'][0])
        done=delete.delete(self.ident,review['digest'],self.paths);self.assertEqual(done['status'],'complete')
        self.assertFalse(self.trace.exists());self.assertTrue(frozen.is_file());self.assertTrue(self.original.is_file())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        row=self.state.db.execute('SELECT * FROM desktop_plan_requests').fetchone()
        self.assertEqual(row['status'],'deleted');self.assertEqual(row['prompt'],'')
        delivery=self.state.db.execute('SELECT * FROM outbox WHERE id=?',(self.event,)).fetchone()
        self.assertEqual(delivery['sent'],1);self.assertEqual(delivery['text'],'')
        self.assertEqual(self.state.db.execute('SELECT text,sent FROM outbox_parts').fetchone()[:],('',1))
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['items'],[])
        self.assertIsNone(self.state.get('orchestrator-presentation:'+self.ident))
        again=self.create_conversation(self.request_id,files=[str(self.original)])
        self.assertEqual(again['status'],'deleted')
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'different exact content'):
            desktop_plans.create('A changed request.','',None,None,self.request_id,self.paths,files=[str(self.original)],entry_mode='conversation')
        self.assertEqual(delete.delete(self.ident,review['digest'],self.paths),done)
        with self.assertRaisesRegex(delete.ConversationDeleteError,'stale'):
            delete.delete(self.ident,'0'*64,self.paths)

    def test_changed_preview_does_not_delete_or_clean_traces(self):
        review=self.record()
        with self.state.db:self.state.db.execute('UPDATE orchestrator_chats SET answer=? WHERE id=?',('A changed answer.',int(self.ident)))
        with self.assertRaisesRegex(delete.ConversationDeleteError,'changed'):
            delete.delete(self.ident,review['digest'],self.paths)
        self.assertTrue(self.trace.is_file());self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_conversation_deletions').fetchone()[0],0)

    def test_active_delivery_and_cross_job_dependencies_block_before_mutation(self):
        self.record()
        for status in ('queued','sending','uncertain','guides_pending'):
            with self.state.db:self.state.db.execute('UPDATE orchestrator_chats SET status=? WHERE id=?',(status,int(self.ident)))
            review=delete.preview(self.ident,self.paths);self.assertTrue(review['blockers'])
            with self.assertRaisesRegex(delete.ConversationDeleteError,'blocked'):delete.delete(self.ident,review['digest'],self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE orchestrator_chats SET status='answered'")
            self.state.db.execute('UPDATE outbox_parts SET sent=0')
        self.assertTrue(delete.preview(self.ident,self.paths)['blockers'])
        with self.state.db:
            self.state.db.execute('UPDATE outbox_parts SET sent=1')
            self.state.db.execute('CREATE TABLE future_owner(id TEXT PRIMARY KEY,source_request_id INTEGER)')
            self.state.db.execute('INSERT INTO future_owner VALUES (?,?)',('other-job',int(self.ident)))
        review=delete.preview(self.ident,self.paths);self.assertIn('Another Relay record references this conversation.',review['blockers'])
        with self.assertRaisesRegex(delete.ConversationDeleteError,'blocked'):delete.delete(self.ident,review['digest'],self.paths)
        self.assertTrue(self.trace.is_file())

    def test_other_channel_and_proposed_work_use_original_controls(self):
        self.record()
        with self.state.db:self.state.db.execute("UPDATE relay_request_channels SET channel='telegram'")
        self.assertTrue(delete.preview(self.ident,self.paths)['blockers'])
        with self.state.db:
            self.state.db.execute("UPDATE relay_request_channels SET channel='desktop'")
            value={**fixture.REPLY,'action':{'kind':'plan_production'}}
            self.state.db.execute('UPDATE orchestrator_chats SET response=?',(json.dumps(value),))
        self.assertTrue(delete.preview(self.ident,self.paths)['blockers'])
        with self.assertRaises(delete.ConversationDeleteError):delete.preview('1',self.paths)

    def test_database_failure_rolls_back_text_and_tombstone_before_cleanup(self):
        review=self.record()
        self.state.db.execute("CREATE TRIGGER deny_clear BEFORE UPDATE OF text ON outbox BEGIN SELECT RAISE(ABORT,'Controlled rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):delete.delete(self.ident,review['digest'],self.paths)
        self.assertTrue(self.trace.is_file());self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT status FROM desktop_plan_requests').fetchone()[0],'accepted')
        self.assertIsNotNone(self.state.get('orchestrator-presentation:'+self.ident))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_conversation_deletions').fetchone()[0],0)

    def test_cleanup_failure_is_recoverable_without_restoring_or_replaying_requests(self):
        review=self.record()
        with patch.object(Path,'unlink',side_effect=OSError('Controlled cleanup interruption')):
            done=delete.delete(self.ident,review['digest'],self.paths)
        self.assertEqual(done['status'],'cleanup_pending');self.assertTrue(self.trace.exists())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['conversation_delete_pending'][0]['id'],self.ident)
        self.assertEqual(delete.recover(self.ident,self.paths)['status'],'complete');self.assertFalse(self.trace.exists())
        self.assertEqual(delete.pending(self.paths),[]);self.assertEqual(delete.recover(self.ident,self.paths)['status'],'complete')

    def test_changed_trace_remains_intact_during_recovery(self):
        review=self.record();original=self.trace.read_bytes();recover=delete.recover
        def change_then_recover(*args):self.trace.write_text('Changed trace.');return recover(*args)
        with patch.object(delete,'recover',side_effect=change_then_recover):done=delete.delete(self.ident,review['digest'],self.paths)
        self.assertEqual(done['status'],'cleanup_pending');self.assertEqual(self.trace.read_text(),'Changed trace.')
        self.trace.write_bytes(original);self.assertEqual(delete.recover(self.ident,self.paths)['status'],'complete')

    def test_native_bridge_has_all_delete_routes_and_preview_stays_read_only(self):
        self.record();before=dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone())
        delete.preview(self.ident,self.paths);self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()),before)
        rust=(Path(__file__).resolve().parents[1]/'desktop/src-tauri/src/lib.rs').read_text().split('fn bridge_command',1)[0]
        for action,method in (('conversation-delete-preview','preview'),('conversation-delete','delete'),('conversation-delete-recover','recover')):
            self.assertIn('"'+action+'"',rust)
            with patch.object(delete,method,return_value={'controlled':True}) as call:
                self.assertEqual(desktop_bridge._dispatch(action,{'id':self.ident,'digest':self.review['digest']}),{'controlled':True})
                call.assert_called_once()

    def test_linked_trace_blocks_review_and_retains_cleanup_receipt(self):
        review=self.record();original=self.trace.read_bytes();recover=delete.recover
        outside=self.paths.data/'other-record.txt';outside.write_bytes(original)
        self.trace.unlink();self.trace.symlink_to(outside)
        with self.assertRaisesRegex(delete.ConversationDeleteError,'linked'):
            delete.preview(self.ident,self.paths)
        self.trace.unlink();self.trace.write_bytes(original)
        def link_then_recover(*args):
            self.trace.unlink();self.trace.symlink_to(outside);return recover(*args)
        with patch.object(delete,'recover',side_effect=link_then_recover):
            done=delete.delete(self.ident,review['digest'],self.paths)
        self.assertEqual(done['status'],'cleanup_pending');self.assertTrue(self.trace.is_symlink())
        self.assertEqual(outside.read_bytes(),original)
        self.trace.unlink();self.trace.write_bytes(original)
        self.assertEqual(delete.recover(self.ident,self.paths)['status'],'complete')
        self.assertTrue(outside.is_file())

    def test_nested_option_source_blocks_deletion_without_losing_its_receipt(self):
        self.record()
        with self.state.db:
            self.state.db.execute('INSERT INTO conversation_followups VALUES (?,?,?,?,?,?,?)',
                ('nested-selection',-999,0,'fixture','research',1,int(self.ident)))
        review=delete.preview(self.ident,self.paths)
        self.assertIn('Another Relay record references this conversation.',review['blockers'])
        with self.assertRaisesRegex(delete.ConversationDeleteError,'blocked'):
            delete.delete(self.ident,review['digest'],self.paths)
        self.assertTrue(self.trace.exists())
        self.assertEqual(self.state.db.execute('SELECT request_id FROM conversation_followups').fetchone()[0],'nested-selection')

    def test_followup_uuid_ownership_blocks_standalone_history_deletion(self):
        self.record()
        with self.state.db:
            self.state.db.execute('INSERT INTO conversation_followups VALUES (?,?,?,?,?,?,?)',
                (self.request_id,-999,0,'fixture','research',1,-999))
        review=delete.preview(self.ident,self.paths)
        self.assertIn('Another Relay record references this conversation.',review['blockers'])
        with self.assertRaisesRegex(delete.ConversationDeleteError,'blocked'):
            delete.delete(self.ident,review['digest'],self.paths)
        self.assertTrue(self.trace.exists())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)
