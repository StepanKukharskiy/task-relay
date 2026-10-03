"""Guarded task deletion uses small records and exact recovery receipts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay.bridge import State
from task_relay.desktop_tasks import list_tasks
from task_relay.relay_paths import Paths
from task_relay.task_delete import TaskDeleteError, delete, pending, preview, recover_pending
from task_relay.desktop_bridge import _dispatch


TASK = 'gemini:fixture-task'
JOB = 'fixture-job'


class TaskDeleteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.paths = Paths(root/'app',root/'data',root/'workspaces',root/'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        result = self.paths.data/'results'/(JOB+'.md')
        response = self.paths.data/'gemini-runs'/(JOB+'.json')
        request = self.paths.data/'gemini-runs'/(JOB+'.input.json')
        for file,contents in ((result,b'answer'),(response,b'{}'),(request,b'{}')):
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(contents)
        self.files = (result,response,request)
        with self.state.db:
            self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',(TASK,'',0,'Fixture task','idle',1))
            self.state.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,?)',(TASK,'gemini','fixture-task',str(root),'fixture',1))
            self.state.db.execute('''INSERT INTO backend_jobs
                (id,thread_id,update_id,prompt,status,created_at,finished_at,result_path)
                VALUES (?,?,1,'Exact request','completed',1,2,?)''',(JOB,TASK,str(result)))
            self.state.db.execute("INSERT INTO incoming VALUES (1,'completed',?)",(TASK,))
            self.state.db.execute('''INSERT INTO gemini_runs
                (job_id,capability,model,stage,response_path,options_json)
                VALUES (?,'text','fixture','complete',?,'{}')''',(JOB,str(response)))
            self.state.db.execute('''INSERT INTO gemini_history VALUES (?,?,?,?,?,?)''',
                                  (JOB,TASK,'text',str(request),str(response),1))
            self.state.db.execute("INSERT INTO outbox VALUES ('backend:fixture-job:done',?,'Done',1)",(TASK,))
            self.state.db.execute("INSERT INTO messages VALUES (1,2,?)",(TASK,))

    def test_deletes_owned_text_history_and_traces_preserving_external_files(self):
        native = self.paths.workspaces/'native.txt'
        native.parent.mkdir()
        native.write_text('kept')
        review = preview(TASK,self.paths)
        self.assertEqual(review['blockers'],[])
        self.assertEqual(review['turns'],1)
        self.assertEqual(delete(TASK,review['digest'],self.paths)['status'],'complete')
        for table in ('watched','backend_tasks','backend_jobs','incoming','gemini_runs',
                      'gemini_history','outbox','messages'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertTrue(native.is_file())
        self.assertTrue(all(not file.exists() for file in self.files))
        self.assertEqual(delete(TASK,review['digest'],self.paths)['status'],'complete')

    def test_active_shared_and_stale_state_block_without_mutation(self):
        with self.state.db:
            self.state.db.execute("UPDATE watched SET status='running' WHERE id=?",(TASK,))
        review = preview(TASK,self.paths)
        self.assertIn('Task is active or uncertain.',review['blockers'])
        with self.assertRaises(TaskDeleteError): delete(TASK,review['digest'],self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE watched SET status='idle' WHERE id=?",(TASK,))
            self.state.db.execute('''INSERT INTO relay_pipeline_task_links
                (pipeline,step,request_id,backend_job_id,task_id,task_scope,origin,recorded)
                VALUES ('pipe-a','media',2,?,?,'separate_conversation','dispatch',1)''',(JOB,TASK))
        review = preview(TASK,self.paths)
        self.assertTrue(any('Another Relay record' in item for item in review['blockers']))
        with self.assertRaises(TaskDeleteError): delete(TASK,review['digest'],self.paths)
        with self.state.db:
            self.state.db.execute('DELETE FROM relay_pipeline_task_links')
        review = preview(TASK,self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE outbox SET text='Changed'")
        with self.assertRaisesRegex(TaskDeleteError,'changed'):
            delete(TASK,review['digest'],self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)

    def test_cleanup_failure_retries_without_redeleting_database(self):
        review = preview(TASK,self.paths)
        original = Path.unlink
        def fail_once(path, *args, **kwargs):
            if path == self.files[0]: raise OSError('interrupted')
            return original(path,*args,**kwargs)
        with patch('pathlib.Path.unlink', autospec=True, side_effect=fail_once):
            self.assertEqual(delete(TASK,review['digest'],self.paths)['status'],'cleanup_pending')
        self.assertEqual(len(pending(self.paths)),1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)
        self.assertEqual(recover_pending(self.paths)[0]['status'],'complete')
        self.assertTrue(all(not file.exists() for file in self.files))
        self.assertEqual(pending(self.paths),[])

    def test_missing_provider_history_blocks(self):
        with self.state.db:
            self.state.db.execute('DELETE FROM gemini_history')
        review = preview(TASK,self.paths)
        self.assertIn('A completed provider turn has missing history records.',review['blockers'])

    def test_unclassified_private_trace_blocks_complete_deletion(self):
        extra = self.paths.data/'gemini-runs'/(JOB+'.debug.json')
        extra.write_text('private')
        review = preview(TASK,self.paths)
        self.assertIn('A provider turn has an unclassified private trace.',review['blockers'])
        with self.assertRaises(TaskDeleteError): delete(TASK,review['digest'],self.paths)
        self.assertTrue(extra.exists())

    def test_saved_work_offers_delete_only_for_unblocked_task(self):
        self.assertTrue(list_tasks(self.paths)['tasks'][0]['can_delete'])
        with self.state.db:
            self.state.db.execute('''INSERT INTO relay_pipeline_task_links
                (pipeline,step,request_id,backend_job_id,task_id,task_scope,origin,recorded)
                VALUES ('pipe-a','media',2,?,?,'separate_conversation','dispatch',1)''',(JOB,TASK))
        item = list_tasks(self.paths)['tasks'][0]
        self.assertFalse(item['can_delete'])
        self.assertIn('Delete unavailable',item['delete_note'])

    def test_completed_desktop_command_can_be_owned_but_uncertain_one_blocks(self):
        with self.state.db:
            self.state.db.execute('''INSERT INTO desktop_commands
                VALUES ('request',?,'Exact request',1,'accepted',1,'Sent')''',(TASK,))
        self.assertEqual(preview(TASK,self.paths)['blockers'],[])
        with self.state.db:
            self.state.db.execute("UPDATE desktop_commands SET status='uncertain'")
        self.assertIn('A desktop instruction is unfinished or uncertain.',preview(TASK,self.paths)['blockers'])

    def test_desktop_bridge_uses_the_same_reviewed_runtime_contract(self):
        with patch('task_relay.task_delete.preview',side_effect=lambda ident: preview(ident,self.paths)), \
             patch('task_relay.task_delete.delete',side_effect=lambda ident,digest: delete(ident,digest,self.paths)), \
             patch('task_relay.task_delete.pending',side_effect=lambda: pending(self.paths)):
            review = _dispatch('task-delete-preview',{'id':TASK})
            self.assertEqual(review['blockers'],[])
            self.assertEqual(_dispatch('task-delete',{'id':TASK,'digest':review['digest']})['status'],'complete')
            self.assertEqual(_dispatch('task-delete-pending',{})['items'],[])

    def independent_media(self, kind='image'):
        source = self.paths.workspaces/'source.png'
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(b'input pixels')
        with self.state.db:
            self.state.db.execute('UPDATE gemini_runs SET capability=?',(kind,))
            self.state.db.execute('UPDATE gemini_history SET capability=?',(kind,))
            self.state.db.execute('''INSERT INTO orchestrator_chats
                (id,prompt,provider,model,status,created)
                VALUES (2,'Exact image request','gemini','fixture','answered',1)''')
            self.state.db.execute("INSERT INTO incoming VALUES (2,'handled',NULL)")
            self.state.db.execute('INSERT INTO orchestrator_'+kind+'_requests VALUES (2,?,?,?)',
                                  (TASK,JOB,'[2]'))
            self.state.db.execute('''INSERT INTO capability_dispatches VALUES
                (2,?,?,?,?,?,1)''',
                                  (json.dumps({'kind':'generate_'+kind}),
                                   'orchestrator_'+kind+'_requests','2','Queued',TASK))
            self.state.db.execute('INSERT INTO outbox VALUES (?,?,?,1)',(kind+'-request:2',TASK,'Queued'))
            self.state.db.execute('INSERT INTO outbox_parts VALUES (?,0,?,1,NULL)',(kind+'-request:2','Queued'))
            self.state.db.execute("INSERT INTO relay_attachment_batches VALUES ('batch-a',1,1,2)")
            self.state.db.execute("INSERT INTO relay_attachment_members VALUES (2,'batch-a',0)")
            self.state.db.execute('''INSERT INTO production_uploads
                (id,run,file_id,filename,caption,declared_size,status,path,sha256,bytes)
                VALUES (2,'@orchestrator','file','source.png','Exact image request',12,'used',?,'hash',12)''',
                                  (str(source),))
            self.state.db.execute("INSERT INTO kv VALUES ('orchestrator-attachments:2','[2]')")
            self.state.db.execute('INSERT INTO kv VALUES (?,?)',(kind+'-artifact-inputs:2','[]'))
        return source

    def test_independent_media_deletes_request_and_keeps_once_only_batch(self):
        source = self.independent_media()
        review = preview(TASK,self.paths)
        self.assertEqual(review['blockers'],[])
        self.assertEqual(review['media_requests'],[2])
        self.assertEqual(review['retained_attachment_batches'],1)
        self.assertEqual(delete(TASK,review['digest'],self.paths)['status'],'complete')
        for table in ('orchestrator_chats','orchestrator_image_requests','capability_dispatches'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        batch = self.state.db.execute('SELECT request_id FROM relay_attachment_batches').fetchone()
        self.assertEqual(batch[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_uploads').fetchone()[0],1)
        self.assertTrue(source.is_file())
        receipt = self.state.db.execute('SELECT media_requests FROM relay_task_delete_receipts').fetchone()
        self.assertEqual(json.loads(receipt[0]),[2])
        # A late album member must not submit the deleted caption a second time.
        from task_relay import attachment_batches
        late = self.paths.workspaces/'late.png'
        late.write_bytes(b'late pixels')
        with self.state.db:
            self.state.db.execute('''INSERT INTO production_uploads
                (id,run,file_id,filename,caption,declared_size,status,path,sha256,bytes)
                VALUES (3,'@orchestrator','late','late.png','Exact image request',11,'ready',?,'hash',11)''',
                                  (str(late),))
            self.state.db.execute("INSERT INTO relay_attachment_members VALUES (3,'batch-a',1)")
        attachment_batches.finish(self.state,now=100)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)

    def test_changed_or_incomplete_attachment_batch_blocks_media_delete(self):
        self.independent_media()
        review = preview(TASK,self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE relay_attachment_batches SET last_received=2")
        with self.assertRaisesRegex(TaskDeleteError,'changed'):
            delete(TASK,review['digest'],self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE relay_attachment_batches SET notified_count=0")
        self.assertIn('An attachment batch is unfinished or missing its saved uploads.',
                      preview(TASK,self.paths)['blockers'])

    def test_direct_video_uses_the_same_single_owner_guard(self):
        self.independent_media('video')
        review = preview(TASK,self.paths)
        self.assertEqual(review['blockers'],[])
        self.assertEqual(review['media_requests'],[2])
        self.assertEqual(delete(TASK,review['digest'],self.paths)['status'],'complete')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_video_requests').fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
