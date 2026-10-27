"""Permanent deletion uses tiny local fake-worker canvases, never providers."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_same_canvas_rerun as canvas_fixture
from task_relay import job_delete,desktop_node_runs as runs,desktop_node_drafts as drafts
from orchestrator import node_spec

class NodeJobDelete(unittest.TestCase):
    def setUp(self):
        self.f=canvas_fixture.SameCanvas();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.paths=self.f.paths;self.db=self.f.state.db
    def preview(self):return job_delete.preview_item(dict(kind='run',id=self.f.run),self.paths)
    def test_composed_delete_all_versions_files_no_replay_and_other_job_preserved(self):
        command,_=self.f.command();child=runs.start(command)['run']
        self.f.rt.tick(child);self.f.factory.finish(self.f.rt.task(child,'second')['latest']);self.f.rt.tick(child)
        before=self.db.execute("SELECT * FROM production_runs WHERE id='demo'").fetchone()
        view=self.preview();self.assertEqual(view['blockers'],[]);self.assertEqual(set(view['runs']),{self.f.run,child})
        self.assertGreater(view['files'],0)
        owned=job_delete._node_graph(self.db,view['id'],self.paths)['_cleanup_files']
        result=job_delete.delete(view['id'],view['digest'],self.paths);self.assertEqual(result['status'],'complete')
        self.assertTrue(all(not Path(v['path']).exists() for v in owned))
        for run in view['runs']:
            self.assertIsNone(self.db.execute('SELECT 1 FROM production_runs WHERE id=?',(run,)).fetchone())
            self.assertIsNone(self.db.execute('SELECT 1 FROM production_events WHERE run=?',(run,)).fetchone())
        self.assertEqual(before,self.db.execute("SELECT * FROM production_runs WHERE id='demo'").fetchone())
        self.assertEqual(job_delete.delete(view['id'],view['digest'],self.paths)['status'],'complete')
        with self.assertRaisesRegex(ValueError,'deleted'):runs.start(command)
        self.assertEqual(self.db.execute('SELECT command FROM desktop_node_runs WHERE run=?',(child,)).fetchone()[0],'{}')
        self.assertEqual(self.db.execute('SELECT files FROM relay_delete_receipts WHERE id=?',(view['id'],)).fetchone()[0],'[]')
    def test_stale_review_does_not_delete(self):
        view=self.preview();self.f.command('Changed saved prompt')
        with self.assertRaisesRegex(ValueError,'changed'):job_delete.delete(view['id'],view['digest'],self.paths)
        self.assertTrue(self.db.execute('SELECT 1 FROM production_runs WHERE id=?',(self.f.run,)).fetchone())
    def test_active_child_and_other_saved_reference_block(self):
        command,_=self.f.command();runs.start(command)
        self.assertTrue(self.preview()['blockers'])
    def test_external_draft_reference_blocks_without_effect(self):
        path=self.paths.data/'node-drafts'/('a'*32+'.json');path.write_text(json.dumps({'title':'Other','source':self.f.run}))
        view=self.preview();self.assertTrue(any('draft' in s for s in view['blockers']))
        with self.assertRaisesRegex(ValueError,'blocked'):job_delete.delete(view['id'],view['digest'],self.paths)
    def test_interrupted_cleanup_can_retry_without_replaying_execution(self):
        view=self.preview()
        with patch.object(job_delete,'_cleanup_private_files',side_effect=OSError('test interruption')):
            self.assertEqual(job_delete.delete(view['id'],view['digest'],self.paths)['status'],'cleanup_pending')
        self.assertEqual(job_delete.recover(view['id'],self.paths)['status'],'complete')
        self.assertIsNone(self.db.execute('SELECT 1 FROM production_runs WHERE id=?',(self.f.run,)).fetchone())
    def test_empty_named_save_reload_list_delete_and_stale_save(self):
        workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[])
        record=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='My empty canvas',workflow=workflow))
        self.assertEqual(drafts.dispatch('node-draft',{'id':record['id']})['title'],'My empty canvas')
        self.assertIn(record['id'],[r['id'] for r in drafts.dispatch('node-drafts',{})['items']])
        self.assertFalse(node_spec.resolve_workflow(workflow)['ready'])
        with self.assertRaises(ValueError):node_spec.resolve_workflow(workflow,values={})
        view=job_delete.preview_item(dict(kind='draft',id=record['id']),self.paths)
        self.assertEqual(view['blockers'],[]);self.assertEqual(view['files'],1)
        self.assertEqual(job_delete.delete(view['id'],view['digest'],self.paths)['status'],'complete')
        with self.assertRaisesRegex(ValueError,'no longer exists'):
            drafts.dispatch('node-draft-save',dict(id=record['id'],revision=None,title=record['title'],workflow=workflow))
    def test_saved_canvas_rename_is_visible_in_jobs(self):
        from task_relay import desktop_workspace
        record=runs.read_canvas({'run':self.f.run})
        runs.save_canvas(dict(run=self.f.run,revision=record['revision'],title='Renamed canvas',workflow=record['workflow']))
        item=next(i for i in desktop_workspace.jobs(paths=self.paths)['items'] if i['id']==self.f.run)
        self.assertEqual(item['title'],'Renamed canvas')
    def test_unresolved_receipt_and_changed_file_block_deletion(self):
        with self.db:self.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps({'pending_requests':['unknown']}),self.f.attempt))
        view=self.preview();self.assertTrue(any('unresolved' in b for b in view['blockers']))
        with self.db:self.db.execute("UPDATE production_attempts SET receipt='{}' WHERE id=?",(self.f.attempt,))
        view=self.preview()
        path=self.paths.data/'node-drafts'/(self.f.saved['id']+'.json')
        path.write_text(path.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'changed'):job_delete.delete(view['id'],view['digest'],self.paths)
    def test_external_saved_output_is_not_removed(self):
        original=self.paths.workspaces/'original.png';original.parent.mkdir(parents=True,exist_ok=True);original.write_bytes(b'original')
        view=self.preview();job_delete.delete(view['id'],view['digest'],self.paths)
        self.assertEqual(original.read_bytes(),b'original')

    def stopped_attempt(self, **receipt):
        saved=dict(status='uncertain',local_terminal=True,external_outcome='unknown',**receipt)
        with self.db:
            self.db.execute("UPDATE production_attempts SET state='uncertain',receipt=? WHERE id=?",(json.dumps(saved),self.f.attempt))
            self.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run=? AND id='second'",(self.f.run,))

    def test_stopped_uncertain_explicit_delete_preserves_tombstone_no_dispatch(self):
        self.stopped_attempt()
        view=self.preview();self.assertEqual(view['blockers'],[])
        self.assertEqual(view['stopped_uncertain_attempts'],[self.f.attempt])
        before=len(self.f.factory.calls)
        with self.assertRaisesRegex(ValueError,'Confirm deletion'):
            job_delete.delete(view['id'],view['digest'],self.paths)
        self.assertEqual(self.db.execute('SELECT state FROM production_attempts WHERE id=?',(self.f.attempt,)).fetchone()[0],'uncertain')
        result=job_delete.delete(view['id'],view['digest'],self.paths,acknowledge_uncertain=True)
        self.assertEqual(result['status'],'complete');self.assertEqual(len(self.f.factory.calls),before)
        self.assertEqual(self.db.execute('SELECT command FROM desktop_node_runs WHERE run=?',(self.f.run,)).fetchone()[0],'{}')
        self.assertEqual(job_delete.delete(view['id'],view['digest'],self.paths)['status'],'complete')

    def test_stop_proof_is_strict_and_remote_pending_cleanup_still_block(self):
        self.stopped_attempt()
        for value in ({},dict(status='uncertain',local_terminal='true'),
                      dict(status='finished',local_terminal=True),
                      dict(status='uncertain',local_terminal=True,pending_requests=['unknown']),
                      dict(status='uncertain',local_terminal=True,cleanup_error='busy'),
                      dict(status='uncertain',local_terminal=True,operation={'remote':{'id':'job'}}),
                      [],None):
            with self.subTest(receipt=value):
                with self.db:self.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(value),self.f.attempt))
                view=self.preview();self.assertTrue(view['blockers'])
                with self.assertRaisesRegex(ValueError,'blocked'):
                    job_delete.delete(view['id'],view['digest'],self.paths,acknowledge_uncertain=True)

    def test_active_child_still_blocks_stopped_old_attempt_and_stale_confirmation(self):
        command,_=self.f.command();child=runs.start(command)['run']
        self.stopped_attempt();self.assertTrue(self.preview()['blockers'])
        self.f.rt.tick(child);self.f.factory.finish(self.f.rt.task(child,'second')['latest']);self.f.rt.tick(child)
        view=self.preview();self.assertEqual(view['blockers'],[])
        from task_relay import desktop_workspace
        item=next(i for i in desktop_workspace.jobs(paths=self.paths)['items'] if i['id']==self.f.run)
        self.assertEqual(item['status'],'completed')
        with self.db:self.db.execute("UPDATE production_attempts SET state='running' WHERE id=?",(self.f.attempt,))
        with self.assertRaisesRegex(ValueError,'changed'):
            job_delete.delete(view['id'],view['digest'],self.paths,acknowledge_uncertain=True)
        self.assertTrue(self.preview()['blockers'])
