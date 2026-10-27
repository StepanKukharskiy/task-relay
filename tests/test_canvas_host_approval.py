"""Exact native script confirmation through existing canvas admission, offline."""
import copy
import json
import sqlite3
import unittest
import uuid
from unittest.mock import patch
from task_relay import desktop_node_runs as runs, desktop_node_drafts as drafts, desktop_node_files as files
from orchestrator import host_code
from orchestrator.runtime import Runtime
from tests import test_canvas_node_run as canvas, test_blender_edit as blender
from tests.test_orchestrator import FakeFactory


class HostApproval(unittest.TestCase):
    def setUp(self):
        self.fixture=canvas.Canvas();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root.resolve();self.paths=self.fixture.paths
        for mock in (patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender')),
                     patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/blender'}),
                     patch.object(files,'PATHS',self.paths),patch.object(files,'_database',runs._database)):
            mock.start();self.addCleanup(mock.stop)
        with sqlite3.connect(self.paths.state) as db:
            db.row_factory=sqlite3.Row;rt=Runtime(self.root/'orchestrator',connection=db)
            op=blender.inputs(rt,self.root)
            with rt.transaction():
                self.selected=[files.select_artifact(rt,i['artifact']) for i in op['inputs']]
        bindings={key:{'artifact':item['artifact']} for key,item in zip(('scene_sha256','script_sha256','checks_sha256'),self.selected)}
        bindings['permissions']={'value':'unrestricted_host'}
        workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[dict(schema_version=3,id='native',operation='blender.run_python',objective='Edit saved roof',inputs=bindings)])
        saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Native fixture',workflow=workflow))
        self.request=dict(self.fixture.request,id=saved['id'],revision=saved['revision'])

    def command(self):
        checked=runs.preview(self.request)
        return dict(**self.request,fingerprint=checked['fingerprint'],allow_paid=False,approve_host_code=runs.host_choices(checked['host_reviews']))

    def counts(self):
        with sqlite3.connect(self.paths.state) as db:
            return tuple(db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('production_runs','production_attempts'))

    def test_exact_preview_requires_explicit_approval_and_never_dispatches(self):
        before=self.counts();p=runs.preview(self.request)
        self.assertEqual(before,self.counts());self.assertEqual(p['paid_nodes'],[])
        self.assertEqual(p['deferred_host_nodes'],[])
        documents=p['host_reviews'][0]['documents']
        self.assertEqual(len(documents),2)
        self.assertIn('bpy.data.objects',documents[0]['text'])
        self.assertEqual(documents[0]['sha256'],self.selected[1]['sha256'])
        command=self.command();command.pop('approve_host_code')
        with self.assertRaisesRegex(ValueError,'approve the exact host'):runs.start(command)
        self.assertEqual(before,self.counts())

    def test_admission_restart_dispatch_and_replay_use_same_exact_receipt(self):
        command=self.command();receipt=runs.start(command)
        self.assertEqual(self.counts(),(1,0));self.assertTrue(runs.start(command)['reused'])
        with sqlite3.connect(self.paths.state) as db:
            db.row_factory=sqlite3.Row;factory=FakeFactory();rt=Runtime(self.root/'orchestrator',factory,connection=db)
            task=rt.task(receipt['run'],'native');spec=rt.spec(task)
            approval=host_code.approved(rt,receipt['run'],'native',spec)
            self.assertEqual(approval['decision']['binding_digest'],command['approve_host_code'][0]['digest'])
            rt.tick(receipt['run']);attempt=rt.task(receipt['run'],'native')['latest']
            self.assertIsNotNone(attempt);host_code.verify_frozen(factory.sessions[attempt]['frozen'])
            self.assertEqual(len(factory.calls),1)
            rt.tick(receipt['run']);self.assertEqual(len(factory.calls),1)
            self.assertEqual(db.execute("SELECT count(*) FROM production_events WHERE kind='host_code_authorized'").fetchone()[0],1)

    def test_changed_application_or_script_cannot_reuse_preview(self):
        command=self.command()
        with patch('task_relay.host_evidence.application_signature',return_value={'path':'/changed/blender'}):
            with self.assertRaisesRegex(ValueError,'changed'):runs.start(command)
        from pathlib import Path
        with sqlite3.connect(self.paths.state) as db:
            blob=db.execute('SELECT blob FROM production_artifacts WHERE id=?',(self.selected[1]['artifact'],)).fetchone()[0]
        Path(blob).chmod(0o600);Path(blob).write_text('print("changed")')
        with self.assertRaisesRegex(ValueError,'changed'):runs.start(command)
        self.assertEqual(self.counts(),(0,0))

    def test_failure_rolls_back_approval_with_admission(self):
        command=self.command()
        with patch('task_relay.relay_channels.bind',side_effect=ValueError('interrupted')):
            with self.assertRaisesRegex(ValueError,'interrupted'):runs.start(command)
        self.assertEqual(self.counts(),(0,0))
        with sqlite3.connect(self.paths.state) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM production_events WHERE kind='host_code_authorized'").fetchone()[0],0)

    def test_changed_binding_during_admission_rolls_back(self):
        command=self.command();original=host_code.authorize
        def changed(*args,**kwargs):
            with patch('task_relay.host_evidence.application_signature',return_value={'path':'/changed/blender'}):return original(*args,**kwargs)
        with patch.object(host_code,'authorize',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed'):runs.start(command)
        self.assertEqual(self.counts(),(0,0))

    def test_future_code_has_no_blanket_authorization(self):
        checked=runs.preview(self.request);plan=copy.deepcopy(checked['plan'])
        item=plan['tasks'][0]['inputs'][1];item.pop('artifact');item.update(from_task='future',output='script.py')
        reviews,deferred=runs.host_reviews(None,plan)
        self.assertEqual(reviews,[]);self.assertEqual(deferred,['native'])

    def test_same_canvas_new_version_rechecks_approval_and_keeps_prior_assignment(self):
        first=runs.start(self.command())
        with sqlite3.connect(self.paths.state) as db:
            db.row_factory=sqlite3.Row;rt=Runtime(self.root/'orchestrator',connection=db)
            rt.cancel(first['run'])
            original=[tuple(r) for r in db.execute('SELECT * FROM production_assignments WHERE run=?',(first['run'],))]
        record=runs.read_canvas({'run':first['run']})
        request=dict(canvas=first['run'],revision=record['revision'],scope='native',values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(request)
        command=dict(**request,fingerprint=checked['fingerprint'],allow_paid=False)
        with self.assertRaisesRegex(ValueError,'approve the exact host'):runs.start(command)
        command['approve_host_code']=runs.host_choices(checked['host_reviews'])
        next_run=runs.start(command);self.assertEqual(next_run['canvas_run'],first['run'])
        with sqlite3.connect(self.paths.state) as db:
            self.assertEqual(original,[tuple(r) for r in db.execute('SELECT * FROM production_assignments WHERE run=?',(first['run'],))])
            self.assertEqual(db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
