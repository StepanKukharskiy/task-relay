import json
from pathlib import Path
import unittest
from task_relay import result_handoff as handoff, production_control as pc, relay_channels
from tests import test_production_control as fixtures


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        self.state.media_dir=self.state.media_dir.resolve()
    tearDown=fixtures.Tests.tearDown
    finish_stage=fixtures.Tests.finish_stage
    click=fixtures.Tests.click
    stage_card=fixtures.Tests.stage_card
    message=fixtures.Tests.message
    worker=fixtures.Tests.worker

    def select(self):
        self.finish_stage()
        aid=self.rt.status('demo')['artifacts'][0]['id']
        # Select the producer, never its source or independent review.
        aid=next(a['id'] for a in self.rt.status('demo')['artifacts'] if a['task']=='produce')
        self.rt.select('demo','produce',aid,'creative selection','Exact fixture selection')
        return aid

    def test_completed_selection_exports_once_and_hands_off_without_dispatch(self):
        aid=self.select();calls=len(self.factory.calls)
        handoff.tick(self.state);handoff.tick(self.state)
        rows=self.state.db.execute("SELECT text FROM outbox WHERE id='production:demo:files-ready'").fetchall()
        self.assertEqual(len(rows),1)
        self.assertIn('Completed — your selected results are ready.',rows[0][0])
        path=next(line for line in rows[0][0].splitlines() if line.startswith('/') and '/selected/' in line)
        self.assertEqual(Path(path).read_bytes(),Path(self.rt.artifact(aid)['blob']).read_bytes())
        self.assertEqual(len(self.factory.calls),calls)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)

    def test_no_acceptance_or_completion_inferred_before_selection(self):
        self.finish_stage();handoff.tick(self.state)
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM outbox WHERE id='production:demo:files-ready'").fetchone())

    def test_newer_delivered_handoffs_do_not_starve_older_completed_result(self):
        self.select()
        decision=dict(self.state.db.execute('SELECT * FROM production_decisions LIMIT 1').fetchone())
        with self.state.db:
            for n in range(20):
                run='newer-'+str(n)
                old=self.state.db.execute("SELECT plan FROM production_runs WHERE id='demo'").fetchone()[0]
                plan=json.loads(old);plan['id']=run
                self.state.db.execute('INSERT INTO production_runs VALUES (?,?,?)',(run,json.dumps(plan),'completed'))
                self.state.db.execute('INSERT INTO production_decisions VALUES (?,?,?,?,?,?,?)',
                    (run,run,decision['task'],decision['artifact'],'Selection','Fixture',decision['created']+n+1))
                self.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)',('production:'+run+':files-ready','Already handed off'))
        handoff.tick(self.state)
        self.assertIsNotNone(self.state.db.execute("SELECT 1 FROM outbox WHERE id='production:demo:files-ready'").fetchone())

    def test_modified_export_preserved_and_exact_registered_file_exposed(self):
        aid=self.select();root=handoff.sync(self.state,'demo')
        old=json.loads((root/'.relay-workflow.json').read_text());path=root/old['paths'][aid]
        path.write_text('My local edits')
        self.assertNotIn(str(path),handoff.saved_text(self.state,'demo'))
        # A fresh signature is not necessary: export must detect changed bytes.
        handoff.sync(self.state,'demo')
        self.assertEqual(path.read_text(),'My local edits')
        self.assertIn('-registered',handoff.saved_text(self.state,'demo'))

    def test_wrong_channel_and_uncommitted_export_rejected(self):
        self.select()
        with self.assertRaisesRegex(ValueError,'channel'):handoff.sync(relay_channels.ScopedState(self.state,'messages'),'demo')
        with self.rt.transaction(),self.assertRaisesRegex(ValueError,'commit'):handoff.sync(self.state,'demo')

    def test_existing_install_does_not_send_historical_completion_messages(self):
        self.select()
        self.state.db.execute('DROP TABLE result_handoff_epoch')
        handoff.initialize(self.state.db);self.state.db.commit()
        handoff.tick(self.state)
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM outbox WHERE id='production:demo:files-ready'").fetchone())

    def test_plan_recovery_ancestry_keeps_stable_folder_and_registered_inputs(self):
        self.select()
        with self.state.db:
            for n,parent,run in [(1,None,None),(2,'plan-1','demo')]:
                self.state.db.execute("""INSERT INTO production_plans
                    (id,request_id,parent_id,channel,request,options,context,context_hash,provider,model,status,token,expires,run,created)
                    VALUES (?,?,?,'telegram','Exact original request','{}','{}','hash','test','test','started',?,0,?,0)""",
                    ('plan-'+str(n),100+n,parent,'token-'+str(n),run))
        root=handoff.sync(self.state,'demo')
        self.assertEqual((root/'request.txt').read_text(),'Exact original request')
        manifest=json.loads((root/'manifest.json').read_text())
        self.assertEqual(manifest['stages'][0]['plans'],['plan-1','plan-2'])
        self.assertEqual(handoff.ancestry(self.state,'demo')[0],'plan-1')
        self.assertEqual(len(manifest['artifacts']),len(self.rt.status('demo')['artifacts']))
