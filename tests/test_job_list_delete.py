"""Recoverable Jobs-list deletion, no providers or filesystem purge."""
import json
import unittest
from unittest.mock import patch
from tests.test_desktop_workspace import WorkspaceTests
from task_relay import desktop_workspace as workspace,desktop_node_drafts as drafts

class JobListDelete(unittest.TestCase):
    def setUp(self):
        self.fixture=WorkspaceTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.paths=self.fixture.paths;self.db=self.fixture.state.db
    def change(self,kind='run',ident='demo',deleted=True):
        return workspace.job_visibility(dict(kind=kind,id=ident,deleted=deleted),self.paths)
    def test_delete_restore_and_repeat_preserve_every_execution_row(self):
        with self.db:self.db.execute("UPDATE production_runs SET status='cancelled' WHERE id='demo'")
        before={t:self.db.execute('SELECT * FROM '+t).fetchall() for t in ['production_runs','production_tasks','production_assignments','production_events']}
        self.change();self.change()
        self.assertNotIn('demo',[i['id'] for i in workspace.jobs(paths=self.paths)['items']])
        row=next(i for i in workspace.jobs(paths=self.paths,include_archived=True)['items'] if i['id']=='demo')
        self.assertTrue(row['archived'])
        self.change(deleted=False)
        self.assertIn('demo',[i['id'] for i in workspace.jobs(paths=self.paths)['items']])
        for t,rows in before.items():self.assertEqual(rows,self.db.execute('SELECT * FROM '+t).fetchall())
    def test_blocked_job_without_active_workers_can_be_deleted(self):
        with self.db:self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='demo'")
        self.change()
        self.assertNotIn('demo',[i['id'] for i in workspace.jobs(paths=self.paths)['items']])
    def test_active_and_unknown_jobs_cannot_be_hidden(self):
        with self.assertRaisesRegex(ValueError,'not finished'):self.change()
        with self.assertRaisesRegex(ValueError,'unavailable'):self.change(ident='missing')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM desktop_job_archives').fetchone()[0],0)
    def test_unresolved_worker_cannot_be_hidden_even_if_run_cancelled(self):
        self.fixture.rt.tick('demo')
        with self.db:self.db.execute("UPDATE production_runs SET status='cancelled' WHERE id='demo'")
        with self.assertRaisesRegex(ValueError,'active or.*uncertain'):self.change()
    def test_pending_canvas_version_prevents_hiding_parent(self):
        from tests.test_orchestrator import pair
        plan=pair();plan['id']='child'
        self.fixture.rt.create(plan)
        with self.db:
            self.db.execute("UPDATE production_runs SET status='cancelled' WHERE id='demo'")
            self.fixture.rt.event('child',None,None,'canvas_node_version',dict(run='demo',task='produce'))
        with patch.object(workspace,'jobs',return_value=dict(items=[dict(kind='run',id='demo',run='demo',status='completed')],next_offset=None)):
            with self.assertRaisesRegex(ValueError,'active or uncertain'):self.change()
    def test_saved_draft_is_retained_exactly_and_restorable(self):
        with patch.object(drafts,'PATHS',self.paths):
            graph=dict(schema_version=1,kind='workflow',inputs={},tasks=[dict(schema_version=3,id='read',operation='web.fetch',objective='Read page',inputs={'url':{'value':'https://example.org'}})])
            saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Empty canvas',workflow=graph))
            path=self.paths.data/'node-drafts'/(saved['id']+'.json');raw=path.read_bytes()
            self.change('draft',saved['id'])
            self.assertEqual(drafts.dispatch('node-drafts',{})['items'],[])
            self.assertTrue(drafts.dispatch('node-drafts',{'include_archived':True})['items'][0]['archived'])
            self.assertEqual(path.read_bytes(),raw)
            self.change('draft',saved['id'],False)
            self.assertEqual(drafts.dispatch('node-drafts',{})['items'][0]['id'],saved['id'])
    def test_invalid_envelope_has_no_effect(self):
        for value in ({'kind':'run','id':'demo','deleted':1},{'kind':'unknown','id':'demo','deleted':True},{'kind':'draft','id':'../state.sqlite','deleted':True}):
            with self.assertRaises(ValueError):workspace.job_visibility(value,self.paths)
