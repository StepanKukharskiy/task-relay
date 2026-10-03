"""Permanent job deletion is exact, atomic, and recoverable."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay.bridge import State
from task_relay.job_delete import JobDeleteError, delete, pending, preview, recover, recover_pending
from task_relay.relay_paths import Paths


PID = 'job-' + 'a' * 24
OTHER = 'job-' + 'b' * 24


class JobDeleteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root/'app', root/'data', root/'workspaces', root/'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)

    def pipeline(self, pid=PID, status='completed', request=1, target=None):
        with self.state.db:
            self.state.db.execute('''INSERT INTO relay_pipelines
                (id,request_id,request,title,spec,channel,provider,model,status,created)
                VALUES (?,?,?,?,?,?,?,?,?,1)''',
                (pid,request,'Exact request','Parts catalog','{}','desktop','fixture','fixture',status))
            if target:
                self.state.db.execute('''INSERT INTO relay_pipeline_steps
                    (pipeline,position,id,status,target_kind,target,sources)
                    VALUES (?,0,'translate','completed','plan_production',?,'[]')''', (pid,target))

    def production(self):
        with self.state.db:
            self.state.db.execute('''INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,calls,created,run,token,expires)
                VALUES ('plan-1',2,'desktop','Exact stage','{}','{}','hash','fixture','fixture','started',0,1,'run-1','token',1)''')
            self.state.db.execute("INSERT INTO production_runs VALUES ('run-1','{}','active')")
            self.state.db.execute("INSERT INTO production_tasks (run,id,assignment,status,attempts) VALUES ('run-1','task','assignment','completed',1)")
            self.state.db.execute("INSERT INTO production_attempts (id,run,task,assignment,state,frozen,session) VALUES ('attempt','run-1','task','assignment','completed','{}','{}')")
            self.state.db.execute("INSERT INTO production_artifacts (id,run,task,attempt,path,blob,sha256,bytes,purpose,source) VALUES ('artifact','run-1','task','attempt','native.xlsx','blob','hash',1,'delivery','{}')")

    def test_deletes_owned_graph_and_private_view_keeps_native_files(self):
        self.pipeline(target='plan-1')
        self.production()
        folder = self.paths.generated/'workflows'/PID
        (folder/'.relay').mkdir(parents=True)
        (folder/'.relay'/'job.sqlite').write_bytes(b'private')
        (folder/'01-results').mkdir()
        (folder/'01-results'/'native.xlsx').write_bytes(b'native')
        (folder/'.relay-workflow.json').write_text(json.dumps({'workflow':PID}))
        review = preview(PID, self.paths)
        self.assertEqual(review['blockers'], [])
        self.assertEqual(review['runs'], ['run-1'])
        self.assertEqual(delete(PID, review['digest'], self.paths)['status'], 'complete')
        for table in ('relay_pipelines','relay_pipeline_steps','production_plans','production_runs',
                      'production_tasks','production_attempts','production_artifacts'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        self.assertFalse((folder/'.relay').exists())
        self.assertTrue((folder/'01-results'/'native.xlsx').exists())
        self.assertEqual(delete(PID, review['digest'], self.paths)['status'], 'complete')

    def test_deletes_owned_operation_checkpoints_but_keeps_foreign_attempt(self):
        from orchestrator.operation_records import initialize
        initialize(self.state.db)
        self.pipeline(target='plan-1');self.production()
        with self.state.db:
            self.state.db.execute('INSERT INTO research_campaign_receipts VALUES (?,?,?,?,?)',(PID,'batch','run','{}','[]'))
            self.state.db.execute('INSERT INTO research_campaign_receipts VALUES (?,?,?,?,?)',('foreign','batch','other','{}','[]'))
            for attempt in ('attempt','foreign'):
                self.state.db.execute('INSERT INTO operation_record_sets VALUES (?,?,1)',(attempt,'binding'))
                self.state.db.execute('INSERT INTO operation_records VALUES (?,?,0,?)',(attempt,'claim','{}'))
                self.state.db.execute('INSERT INTO operation_submissions VALUES (?,?,?,?)',(attempt,'key','hash','{}'))
        review=preview(PID,self.paths)
        self.assertEqual(delete(PID,review['digest'],self.paths)['status'],'complete')
        for table in ('operation_record_sets','operation_records','operation_submissions'):
            self.assertEqual([r[0] for r in self.state.db.execute('SELECT attempt FROM '+table)],['foreign'])
        self.assertEqual([r[0] for r in self.state.db.execute('SELECT pipeline FROM research_campaign_receipts')],['foreign'])

    def test_active_and_shared_work_block_without_mutation(self):
        self.pipeline(status='active', target='plan-1')
        self.production()
        review = preview(PID, self.paths)
        self.assertTrue(review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)
        with self.state.db:
            self.state.db.execute("UPDATE relay_pipelines SET status='completed' WHERE id=?", (PID,))
        self.pipeline(OTHER, request=3, target='plan-1')
        review = preview(PID, self.paths)
        self.assertIn('Another pipeline uses this plan or run.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0], 2)

    def test_native_links_are_owned_and_shared_links_block_deletion(self):
        self.pipeline(target='plan-1')
        self.production()
        with self.state.db:
            self.state.db.execute('''INSERT INTO relay_native_links VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('native-1', PID, 'plant', 'selection', 'artifact', 'hash', '{}',
                 'artifact', 'hash', '{}', 'fixture', 'reviewed', 'reviewer', '', 1))
            self.state.db.execute('''INSERT INTO relay_native_coverage VALUES (?,?,?,?,?)''',
                                  (PID, 'artifact', '{}', 'incomplete', 'fixture'))
        review = preview(PID, self.paths)
        self.assertEqual(review['blockers'], [])
        self.pipeline(OTHER, request=3)
        with self.state.db:
            self.state.db.execute('''INSERT INTO relay_native_links VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('native-other', OTHER, 'plant', 'selection', 'artifact', 'hash', '{}',
                 'artifact', 'hash', '{}', 'fixture', 'reviewed', 'reviewer', '', 1))
        blocked = preview(PID, self.paths)
        self.assertIn('Another job has a reviewed link to this job’s artifact.', blocked['blockers'])
        with self.assertRaises(JobDeleteError):
            delete(PID, blocked['digest'], self.paths)
        with self.state.db:
            self.state.db.execute("DELETE FROM relay_native_links WHERE job=?", (OTHER,))
            self.state.db.execute("DELETE FROM relay_pipelines WHERE id=?", (OTHER,))
        fresh = preview(PID, self.paths)
        self.assertEqual(fresh['blockers'], [])
        self.assertEqual(delete(PID, fresh['digest'], self.paths)['status'], 'complete')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_native_links').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_native_coverage').fetchone()[0], 0)

    def test_change_handoff_is_owned_and_cross_job_baseline_blocks_delete(self):
        self.pipeline(target='plan-1')
        self.production()
        values = ('handoff-own', PID, 'request-1', 'Exact change',
                  'native_subject_withdrawal', 'artifact', '{}', 'digest', '{}',
                  'fixture-user', 1)
        with self.state.db:
            self.state.db.execute('INSERT INTO relay_impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)', values)
        owned = preview(PID, self.paths)
        self.assertEqual(owned['blockers'], [])
        self.assertEqual(owned['counts']['relay_impact_handoffs'], 1)
        self.pipeline(OTHER, request=3)
        with self.state.db:
            self.state.db.execute('INSERT INTO relay_impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('handoff-other', OTHER, 'request-2', 'Another change',
                 'native_subject_withdrawal', 'artifact', '{}', 'digest', '{}',
                 'fixture-user', 1))
        blocked = preview(PID, self.paths)
        self.assertIn('Another job has a reviewed link to this job’s artifact.', blocked['blockers'])
        with self.assertRaises(JobDeleteError):
            delete(PID, blocked['digest'], self.paths)
        with self.state.db:
            self.state.db.execute("DELETE FROM relay_impact_handoffs WHERE job=?", (OTHER,))
            self.state.db.execute("DELETE FROM relay_pipelines WHERE id=?", (OTHER,))
        fresh = preview(PID, self.paths)
        self.assertEqual(fresh['blockers'], [])
        self.assertEqual(delete(PID, fresh['digest'], self.paths)['status'], 'complete')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_impact_handoffs').fetchone()[0], 0)

    def test_cross_job_xlsx_handoff_source_blocks_delete(self):
        self.pipeline(target='plan-1')
        self.production()
        self.pipeline(OTHER, request=3)
        inputs = json.dumps({'old_source': 'artifact', 'replacement_source': 'other-source',
                             'baseline_artifact': 'other-catalog'})
        with self.state.db:
            self.state.db.execute('INSERT INTO relay_impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('xlsx-other', OTHER, 'request-2', 'Exact XLSX change',
                 'xlsx_fact_change', 'other-catalog', inputs, 'digest', '{}', 'fixture-user', 1))
        blocked = preview(PID, self.paths)
        self.assertIn('Another job has a reviewed link to this job’s artifact.', blocked['blockers'])
        with self.assertRaises(JobDeleteError):
            delete(PID, blocked['digest'], self.paths)

    def test_changed_graph_rejects_stale_confirmation(self):
        self.pipeline()
        review = preview(PID, self.paths)
        with self.state.db:
            self.state.db.execute('UPDATE relay_pipelines SET title=? WHERE id=?', ('Changed',PID))
        with self.assertRaisesRegex(JobDeleteError, 'changed'):
            delete(PID, review['digest'], self.paths)
        self.assertIsNotNone(self.state.db.execute('SELECT id FROM relay_pipelines WHERE id=?',(PID,)).fetchone())

    def test_cleanup_failure_leaves_receipt_and_retry(self):
        self.pipeline()
        folder = self.paths.generated/'workflows'/PID
        (folder/'.relay').mkdir(parents=True)
        (folder/'.relay'/'job.sqlite').write_bytes(b'private')
        (folder/'.relay-workflow.json').write_text(json.dumps({'workflow':PID}))
        review = preview(PID, self.paths)
        with patch('task_relay.job_delete.shutil.rmtree', side_effect=OSError('interrupted')):
            self.assertEqual(delete(PID, review['digest'], self.paths)['status'], 'cleanup_pending')
        self.assertEqual(pending(self.paths)[0]['id'], PID)
        self.assertIsNone(self.state.db.execute('SELECT id FROM relay_pipelines WHERE id=?',(PID,)).fetchone())
        self.assertEqual(recover_pending(self.paths)[0]['status'], 'complete')
        self.assertFalse((folder/'.relay').exists())
        self.assertEqual(pending(self.paths), [])

    def test_export_lock_defers_cleanup_until_retry(self):
        from task_relay.host import HOST
        self.pipeline()
        folder = self.paths.generated/'workflows'/PID
        (folder/'.relay').mkdir(parents=True)
        (folder/'.relay'/'job.sqlite').write_bytes(b'private')
        (folder/'.relay-workflow.json').write_text(json.dumps({'workflow':PID}))
        review = preview(PID, self.paths)
        lock = folder.parent/('.'+PID+'.lock')
        with lock.open('a') as stream:
            HOST.lock(stream)
            result = delete(PID, review['digest'], self.paths)
            self.assertEqual(result['status'], 'cleanup_pending')
            self.assertTrue((folder/'.relay'/'job.sqlite').exists())
        self.assertEqual(recover_pending(self.paths)[0]['status'], 'complete')
        self.assertFalse((folder/'.relay').exists())

    def test_downstream_plan_using_output_blocks_deletion(self):
        self.pipeline(target='plan-1')
        self.production()
        with self.state.db:
            self.state.db.execute('''INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,calls,token,expires,created)
                VALUES ('outside',3,'desktop','Reuse artifact','{}',?,'hash','fixture','fixture','started',0,'outside',1,1)''',
                (json.dumps({'sources':[{'artifact':'artifact'}]}),))
        review = preview(PID, self.paths)
        self.assertIn('Another plan uses an output artifact from this job.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)

    def test_other_pipeline_using_output_blocks_deletion(self):
        self.pipeline(target='plan-1')
        self.production()
        self.pipeline(OTHER, request=3)
        with self.state.db:
            self.state.db.execute('''INSERT INTO relay_pipeline_steps
                (pipeline,position,id,status,sources) VALUES (?,0,'reuse','completed',?)''',
                (OTHER,json.dumps([{'artifact':'artifact'}])))
        review = preview(PID, self.paths)
        self.assertIn('Another pipeline cites an output artifact from this job.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)

    def media(self):
        self.pipeline()
        traces = self.paths.data / 'gemini-runs'
        results = self.paths.data / 'results'
        traces.mkdir(exist_ok=True)
        results.mkdir(exist_ok=True)
        (traces / 'media-job.input.json').write_text('{"input":true}')
        (traces / 'media-job.json').write_text('{"response":true}')
        (results / 'media-job.md').write_text('Rendered')
        with self.state.db:
            self.state.db.execute('''INSERT INTO relay_pipeline_steps
                (pipeline,position,id,request_id,status,target_kind,target,sources)
                VALUES (?,0,'image',1,'completed','generate_image','media-job','[]')''',(PID,))
            self.state.db.execute('''INSERT INTO backend_jobs
                (id,thread_id,update_id,prompt,status,created_at,cancel,result_path)
                VALUES ('media-job','gemini:agent-task',-99,'Render','completed',1,0,?)''',
                (str(results / 'media-job.md'),))
            self.state.db.execute("INSERT INTO watched VALUES ('gemini:agent-task','',0,'Image','idle',1)")
            self.state.db.execute("INSERT INTO backend_tasks VALUES ('gemini:agent-task','gemini','session','/tmp','model',1)")
            self.state.db.execute("INSERT INTO incoming VALUES (-99,'completed','gemini:agent-task')")
            self.state.db.execute("INSERT INTO orchestrator_image_requests VALUES (1,'gemini:agent-task','media-job','[]')")
            self.state.db.execute("INSERT INTO relay_pipeline_task_links VALUES (?,?,?,?,?,?,?,1)",
                                  (PID,'image',1,'media-job','gemini:agent-task','separate_conversation','dispatch'))
            self.state.db.execute("INSERT INTO gemini_runs(job_id,capability,model,stage,response_path,options_json) VALUES ('media-job','image','model','complete',?,'{}')",
                                  (str(traces / 'media-job.json'),))
            self.state.db.execute("INSERT INTO gemini_history VALUES ('media-job','gemini:agent-task','image',?,?,1)",
                                  (str(traces / 'media-job.input.json'), str(traces / 'media-job.json')))
            self.state.db.execute("INSERT INTO capability_dispatches VALUES (1,'image','gemini','media-job','done','gemini:agent-task',1)")
            self.state.db.execute("INSERT INTO artifacts(id,thread_id,job_id,role,path,filename,mime,sha256,size,created_at) VALUES ('input','gemini:agent-task',NULL,'input','input.png','input.png','image/png','hash',1,1)")
            self.state.db.execute("INSERT INTO artifacts(id,thread_id,job_id,role,path,filename,mime,sha256,size,created_at) VALUES ('output','gemini:agent-task','media-job','output','output.png','output.png','image/png','hash',1,1)")
            self.state.db.execute("INSERT INTO outbox(id,thread_id,text,sent) VALUES ('backend:media-job:result','gemini:agent-task','Done',1)")
            self.state.db.execute("INSERT INTO media_outbox(id,event_id,thread_id,path,filename,kind,caption,status) VALUES ('attachment','backend:media-job:result','gemini:agent-task','output.png','output.png','original','','sent')")
            self.state.db.execute("INSERT INTO messages VALUES (1,10,'gemini:agent-task')")
            self.state.db.execute("INSERT INTO messages VALUES (1,11,'unrelated-task')")
            self.state.db.execute("INSERT INTO outbox(id,thread_id,text,sent) VALUES ('unrelated','unrelated-task','Keep',1)")
            self.state.db.execute("INSERT INTO kv VALUES ('gemini-reply-capability:gemini:agent-task','\"image\"')")
            self.state.db.execute("INSERT INTO kv VALUES ('image-artifact-inputs:1','[]')")

    def test_media_stage_without_link_blocks_deletion(self):
        self.media()
        with self.state.db:
            self.state.db.execute('DELETE FROM relay_pipeline_task_links')
        review = preview(PID, self.paths)
        self.assertIn('A media stage has no verified agent task ownership link.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)

    def test_deletes_exclusive_media_task_and_keeps_shared_channel_history(self):
        self.media()
        review = preview(PID, self.paths)
        self.assertEqual(review['blockers'], [])
        self.assertEqual(review['media_tasks'], ['gemini:agent-task'])
        self.assertEqual(delete(PID, review['digest'], self.paths)['status'], 'complete')
        for table in ('backend_jobs','backend_tasks','watched','incoming','gemini_runs',
                      'gemini_history','artifacts','orchestrator_image_requests',
                      'relay_pipeline_task_links','capability_dispatches','media_outbox'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)
        self.assertEqual([r[0] for r in self.state.db.execute('SELECT id FROM outbox')], ['unrelated'])
        self.assertEqual([r[0] for r in self.state.db.execute('SELECT thread_id FROM messages')], ['unrelated-task'])
        self.assertFalse((self.paths.data / 'gemini-runs' / 'media-job.json').exists())
        self.assertFalse((self.paths.data / 'gemini-runs' / 'media-job.input.json').exists())
        self.assertFalse((self.paths.data / 'results' / 'media-job.md').exists())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM kv').fetchone()[0], 0)

    def test_shared_media_task_or_pending_delivery_blocks_without_mutation(self):
        self.media()
        with self.state.db:
            self.state.db.execute("INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES ('second-job','gemini:agent-task',-100,'Again','completed',2)")
        review = preview(PID, self.paths)
        self.assertIn('A media task has another backend job or turn.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)
        with self.state.db:
            self.state.db.execute("DELETE FROM backend_jobs WHERE id='second-job'")
            self.state.db.execute("UPDATE outbox SET sent=0 WHERE id='backend:media-job:result'")
        review = preview(PID, self.paths)
        self.assertIn('An outbound message is still pending.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM backend_jobs WHERE id='media-job'").fetchone()[0], 1)

    def test_media_trace_change_rejects_stale_confirmation(self):
        self.media()
        review = preview(PID, self.paths)
        (self.paths.data / 'gemini-runs' / 'media-job.json').write_text('changed')
        with self.assertRaisesRegex(JobDeleteError, 'changed'):
            delete(PID, review['digest'], self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)

    def test_media_trace_cleanup_retries_from_committed_receipt(self):
        self.media()
        review = preview(PID, self.paths)
        with patch('task_relay.job_delete._cleanup_private_files', side_effect=OSError('interrupted')):
            self.assertEqual(delete(PID, review['digest'], self.paths)['status'], 'cleanup_pending')
        self.assertTrue((self.paths.data / 'gemini-runs' / 'media-job.json').exists())
        self.assertEqual(recover_pending(self.paths)[0]['status'], 'complete')
        self.assertFalse((self.paths.data / 'gemini-runs' / 'media-job.json').exists())

    def test_database_failure_rolls_back_every_owned_row(self):
        self.pipeline(target='plan-1')
        self.production()
        review = preview(PID, self.paths)
        with self.state.db:
            self.state.db.execute('''CREATE TRIGGER prevent_job_delete BEFORE DELETE ON production_runs
                BEGIN SELECT RAISE(ABORT, 'injected failure'); END''')
        with self.assertRaises(Exception): delete(PID, review['digest'], self.paths)
        for table in ('relay_pipelines','relay_pipeline_steps','production_plans','production_runs'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0], 1)
        self.assertEqual(pending(self.paths), [])

    def test_missing_stage_target_blocks_ambiguous_old_history(self):
        self.pipeline(target='plan-1')
        review = preview(PID, self.paths)
        self.assertIn('production_plans has a missing ownership record.', review['blockers'])
        with self.assertRaises(JobDeleteError): delete(PID, review['digest'], self.paths)


if __name__ == '__main__': unittest.main()
