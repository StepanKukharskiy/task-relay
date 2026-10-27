"""Frozen uploads remain selectable without a worker attempt or new model call."""
import json
import unittest
from task_relay import pipelines as pipe, routing_inputs, relay_channels
from tests import test_pipelines as fixtures

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    create=fixtures.Tests.create
    request=fixtures.Tests.request
    stage=fixtures.Tests.stage
    step=fixtures.Tests.step
    def test_registered_upload_is_selectable_and_saved_interpretation_recovers(self):
        p=self.create(stages=[self.stage(route='production'),self.stage('finish')]);pipe.tick(self.state)
        step=self.step(p,'outline');jid=step['request_id']
        path=self.state.media_dir.parent/'exact.txt';path.write_text('Exact supplied source')
        aid=self.rt.register(path,'Human supplied source',run=p['id'],path='request-uploads/exact.txt')
        source=pipe.artifact_source(self.state,aid)
        self.state.db.execute('UPDATE relay_pipeline_requests SET inputs=? WHERE request_id=?',(json.dumps(dict(prior_results=[],sources=[source],handoffs=[])),jid))
        self.state.db.execute("UPDATE relay_pipelines SET channel='desktop' WHERE id=?",(p['id'],))
        self.state.db.execute('INSERT OR REPLACE INTO relay_request_channels VALUES (?,?)',(jid,'desktop'))
        p=self.state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()
        scoped=relay_channels.ScopedState(self.state,'desktop')
        # Exercise the shared-state native dispatch path, not just recovery.
        frozen=routing_inputs.freeze_artifacts(self.state,dict(id=jid,focus=p['id']),[aid])
        self.assertEqual(frozen[0]['sha256'],source['sha256'])
        self.assertEqual(frozen[0]['artifact_id'],aid)
        catalog=routing_inputs.artifact_catalog(scoped)
        found=next(a for a in catalog if a['id']==aid)
        self.assertIsNone(found['attempt_state'])
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],artifact_ids=[aid],planning_only=False,research_mode='none',step_capabilities=[],deliverables={'outline':'Model paraphrase of the frozen output'})
        raw=json.dumps(dict(answer='Prepare inventory',action=action))
        self.state.db.execute("UPDATE orchestrator_chats SET status='failed',response=? WHERE id=?",(raw,jid))
        self.state.db.execute('INSERT INTO orchestrator_chat_errors VALUES (?,?,?,?,?)',(jid,'interpretation','ValueError','Artifact omitted from catalog',1))
        self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=?",(p['id'],))
        self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
        self.state.db.execute("UPDATE orchestrator_chats SET status='uncertain' WHERE id=?",(jid,))
        self.assertIsNone(pipe.setup_failure(scoped,self.step(p,'outline')))
        self.state.db.execute("UPDATE orchestrator_chats SET status='failed' WHERE id=?",(jid,))
        self.state.db.commit()
        with self.state.db:
            self.state.db.execute("BEGIN IMMEDIATE")
            pipe.recover_stage_setup(scoped,p,self.step(p,'outline'),'Fix and continue')
        restored=self.step(p,'outline');self.assertEqual(restored['status'],'running')
        self.assertNotEqual(restored['request_id'],jid)
        old=self.state.db.execute('SELECT status,response FROM orchestrator_chats WHERE id=?',(jid,)).fetchone()
        self.assertEqual(tuple(old),('failed',raw))
        row=self.state.db.execute('SELECT context FROM production_plans WHERE id=?',(restored['target'],)).fetchone()
        sources=json.loads(row[0])['sources'];self.assertTrue(any(s['sha256']==source['sha256'] for s in sources))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_unretained_upload_is_not_added_to_catalog(self):
        path=self.state.media_dir.parent/'unselected.txt';path.write_text('Unselected')
        aid=self.rt.register(path,'Not selected',run='unrelated',path='unselected.txt')
        self.assertNotIn(aid,{a['id'] for a in routing_inputs.artifact_catalog(self.state)})
