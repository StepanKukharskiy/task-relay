"""Exact media-stage ownership and shared-history boundaries."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from orchestrator.storage import transaction
from task_relay.bridge import State
from task_relay import job_ownership, job_sqlite, workflow_files
from task_relay.job_delete import preview
from task_relay.relay_paths import Paths


PID = 'pipe-' + 'a' * 24
JOB = 'b' * 32
OTHER_JOB = 'c' * 32
TASK = 'gemini:' + 'd' * 32


class MediaOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root/'install', root/'data', root/'workspaces', root/'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        db = self.state.db
        with transaction(db):
            db.execute('''INSERT INTO relay_pipelines
                (id,request_id,request,title,spec,channel,provider,model,status,created)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (PID, 1, 'Make an image', 'Media job', json.dumps({'stages':[{'id':'image'}]}),
                 'telegram', 'fixture', 'fixture', 'completed', 1))
            db.execute('''INSERT INTO relay_pipeline_steps
                (pipeline,position,id,status,request_id,target_kind,target,sources)
                VALUES (?,0,'image','completed',2,'generate_image',?,'[]')''', (PID, JOB))
            db.execute("INSERT INTO relay_pipeline_requests VALUES (2,?,'image','{}')", (PID,))
            db.execute('''INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,status,created)
                VALUES (2,'Exact media prompt',?,'fixture','fixture','answered',1)''', (PID,))
            db.execute('''INSERT INTO backend_tasks VALUES (?,?,?,?,?,0)''',
                       (TASK, 'gemini', 'session', str(root), 'image-model'))
            db.execute("INSERT INTO watched(id,title,status) VALUES (?,'Separate task','idle')", (TASK,))
            db.execute('''INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at)
                VALUES (?,?,3,'Exact media prompt','completed',1)''', (JOB, TASK))
            db.execute('''INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at)
                VALUES (?,?,4,'Unrelated later turn','completed',2)''', (OTHER_JOB, TASK))
            db.execute("INSERT INTO incoming VALUES (3,'completed',?)", (TASK,))
            db.execute("INSERT INTO incoming VALUES (4,'completed',?)", (TASK,))
            db.execute('''INSERT INTO orchestrator_image_requests VALUES (2,?,?,'[]')''',
                       (TASK, JOB))
            db.execute('''INSERT INTO gemini_runs(job_id,capability,model,response_path,options_json)
                VALUES (?,'image','image-model','response',?)''',
                (JOB, json.dumps({'references':[]})))
            db.execute('''INSERT INTO outbox(id,thread_id,text,sent)
                VALUES (?,?,?,1)''', (f'backend:{JOB}:result', TASK, 'Finished'))
            db.execute('''INSERT INTO outbox(id,thread_id,text,sent)
                VALUES (?,?,?,1)''', (f'backend:{OTHER_JOB}:result', TASK, 'Unrelated'))
            db.execute('''INSERT INTO outbox_parts(event_id,part,text,sent) VALUES (?,?,?,?)''',
                       (f'backend:{JOB}:result', 1, 'Finished', 1))
            db.execute('''INSERT INTO media_outbox(id,event_id,thread_id,path,filename,kind,status)
                VALUES (?,?,?,?,?,'original','sent')''',
                ('media-receipt', f'backend:{JOB}:result', TASK, 'image.png', 'image.png'))
            db.execute("INSERT INTO messages VALUES (1,10,?)", (TASK,))

    def process(self):
        return workflow_files.job_state_for_pipeline(self.state, PID)['process']

    def test_verified_legacy_link_projects_exact_stage_without_absorbing_task_history(self):
        before = self.process()
        self.assertIn('missing_media_task_link', {g['kind'] for g in before['gaps']})
        with transaction(self.state.db):
            links = job_ownership.backfill_verified_media_links(self.state.db, PID)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['origin'], 'verified_legacy')
        self.assertEqual(links[0]['task_scope'], 'separate_conversation')
        deletion = preview(PID, self.paths)
        self.assertEqual(deletion['counts']['relay_pipeline_task_links'], 1)
        self.assertIn('A media task has another backend job or turn.',
                      deletion['blockers'])
        self.assertNotIn('A media stage has no verified agent task ownership link.',
                         deletion['blockers'])
        after = self.process()
        self.assertNotIn('missing_media_task_link', {g['kind'] for g in after['gaps']})
        self.assertTrue(after['complete'], after['gaps'])
        self.assertEqual(next(r['scope'] for r in after['records'] if r['source_table']=='backend_tasks'),
                         'separate_task_reference')
        self.assertEqual({r['source_id'] for r in after['records'] if r['source_table']=='backend_jobs'}, {JOB})
        self.assertIn(f'backend:{JOB}:result',
                      {r['source_id'] for r in after['records'] if r['source_table']=='outbox'})
        self.assertNotIn(f'backend:{OTHER_JOB}:result',
                         {r['source_id'] for r in after['records'] if r['source_table']=='outbox'})
        self.assertNotIn('messages', {r['source_table'] for r in after['records']})
        self.assertEqual(next(c['state'] for c in after['coverage'] if c['category']=='channel_history'),
                         'external')
        report = workflow_files._snapshot(self.state, PID)
        report['snapshot'] = 'fixture-snapshot'
        view_path = self.paths.data/'job-view.sqlite'
        view_path.write_bytes(job_sqlite.projection_bytes(report))
        with sqlite3.connect(view_path) as view:
            self.assertEqual(view.execute('''SELECT scope FROM process_records
                WHERE source_table='backend_tasks' ''').fetchone()[0], 'separate_task_reference')
            self.assertEqual(view.execute('''SELECT count(*) FROM process_records
                WHERE source_table='outbox' AND scope='exact_delivery_receipt' ''').fetchone()[0], 1)

    def test_mismatched_backend_chain_cannot_be_recorded(self):
        with transaction(self.state.db):
            self.state.db.execute('''UPDATE orchestrator_image_requests SET task_id='different'
                WHERE job_id=2''')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            with transaction(self.state.db):
                job_ownership.backfill_verified_media_links(self.state.db, PID)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_task_links').fetchone()[0], 0)

    def test_changed_stage_retains_link_and_marks_ownership_ambiguous(self):
        with transaction(self.state.db):
            job_ownership.backfill_verified_media_links(self.state.db, PID)
            self.state.db.execute('''UPDATE relay_pipeline_steps SET target_kind='browser_research'
                WHERE pipeline=? AND id='image' ''', (PID,))
        process = self.process()
        self.assertIn('orphan_media_task_link', {gap['kind'] for gap in process['gaps']})
        self.assertFalse(process['complete'])
        self.assertIn('An agent task link has no matching media stage target.',
                      preview(PID, self.paths)['blockers'])


if __name__ == '__main__':
    unittest.main()
