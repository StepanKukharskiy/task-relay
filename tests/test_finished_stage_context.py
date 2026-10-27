"""Finished-file stages use their frozen inputs despite large unrelated history."""
import json
import unittest
from unittest.mock import patch
from orchestrator.storage import transaction
from task_relay import production_planning as planning,pipelines,routing_inputs
from tests import test_delivery_completion as fixtures


class Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.Tests();self.f.setUp();self.addCleanup(self.f.tearDown)

    def history(self,purpose='Unrelated previous output'):
        return [dict(id='old-output',run='other-run',task='old',attempt='old-attempt',
                     attempt_state='completed',path='old.txt',sha256='a'*64,bytes=42,purpose=purpose)]

    def test_large_history_cannot_overflow_frozen_delivery_stage_context(self):
        f=self.f;p=f.create();pipelines.tick(f.state)
        step=f.step(p,'outline');job=dict(f.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(step['request_id'],)).fetchone())
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                    research_ids=[],reference_ids=[],artifact_ids=[],planning_only=False,
                    step_capabilities=[],deliverables={'outline':'Exact outline output'},research_mode='none')
        with patch.object(routing_inputs,'artifact_catalog',return_value=self.history('x'*500000)),transaction(f.state.db):
            planning.enqueue(f.state,job,action,{})
        row=f.state.db.execute('SELECT * FROM production_plans WHERE request_id=?',(job['id'],)).fetchone()
        payload=json.loads(row['context'])
        self.assertEqual(payload['available_sources'],[])
        self.assertLess(len(row['context']),planning.MAX_CONTEXT)
        self.assertTrue(payload['sources'])
        for source in payload['sources']:planning.verify_artifact(f.rt,source)
        self.assertEqual(f.factory.calls,[])

    def test_standalone_history_selection_remains_available(self):
        from tests.test_production_planning import Tests as Standalone
        f=Standalone();f.setUp();self.addCleanup(f.tearDown)
        with patch.object(routing_inputs,'artifact_catalog',return_value=self.history()):
            row=f.queue(99)
        payload=json.loads(row['context']);self.assertEqual(payload['available_sources'][0]['artifact'],'old-output')
