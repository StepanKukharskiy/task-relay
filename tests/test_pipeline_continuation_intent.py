"""Ordinary continuation intent must not require a model to select recovery mechanics.

These are controlled intake regressions, not live-model delivery qualification.
"""
import json
import unittest
from orchestrator.storage import transaction
from task_relay import pipelines
from task_relay.relay_channels import ScopedState
from tests import test_pipelines as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    stage=fixture.Tests.stage
    create=fixture.Tests.create
    step=fixture.Tests.step
    answer=fixture.Tests.answer
    rejected_planning_fixture=fixture.Tests.rejected_planning_fixture

    def continue_request(self,p,verb='continue',ident=904):
        self.request(dict(kind='pipeline_control',pipeline_id=p['id'],verb=verb),
                     'Billing restored. Continue the saved work with the same provider.',ident)
        result=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()
        self.assertEqual(result['status'],'answered',result['answer'])

    def test_resume_from_ordinary_intake_recovers_confirmed_billing_rejection(self):
        p,old=self.rejected_planning_fixture(402)
        before=dict(old)
        self.continue_request(p,'resume')
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(self.step(p,'model')['target'],)).fetchone()
        self.assertNotEqual(successor['id'],old['id'])
        for key in ('context','context_hash','options','request','provider','model'):
            self.assertEqual(successor[key],old[key])
        self.assertEqual(successor['status'],'queued')
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old['id'],)).fetchone()),before)
        self.assertEqual(self.factory.calls,[])
        self.continue_request(p,ident=905)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)

    def test_same_intent_resumes_paused_work_without_creating_recovery_authority(self):
        p=self.create();pipelines.tick(self.state)
        before=dict(self.step(p,'outline'))
        with transaction(self.state.db):pipelines.control(self.state,p['id'],'pause')
        self.continue_request(p)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'active')
        self.assertEqual(dict(self.step(p,'outline')),before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_extensions').fetchone()[0],0)

    def test_current_receipts_override_stale_model_state_and_unknown_outcome_stays_held(self):
        p,old=self.rejected_planning_fixture(402)
        snap={'pipelines':pipelines.catalog(self.state)}
        with transaction(self.state.db):self.state.db.execute("UPDATE production_plans SET status='uncertain' WHERE id=?",(old['id'],))
        with self.assertRaises(ValueError),transaction(self.state.db):
            pipelines.dispatch(self.state,dict(prompt='Continue after billing restoration.'),
                               dict(kind='pipeline_control',pipeline_id=p['id'],verb='continue'),snap)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'blocked')
        self.assertEqual(self.factory.calls,[])

    def test_continuation_requires_original_channel_and_transaction(self):
        p,old=self.rejected_planning_fixture(402)
        with self.assertRaises(ValueError):pipelines.control(self.state,p['id'],'continue',request='Continue')
        with self.assertRaises(ValueError),transaction(self.state.db):
            pipelines.control(ScopedState(self.state,'messages'),p['id'],'continue',request='Continue')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_rollback_preserves_blocked_plan_and_no_external_dispatch(self):
        p,old=self.rejected_planning_fixture(402)
        with self.assertRaisesRegex(RuntimeError,'rollback'),transaction(self.state.db):
            pipelines.control(self.state,p['id'],'continue',request='Continue')
            raise RuntimeError('rollback')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old['id'],)).fetchone()),dict(old))
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'blocked')
        self.assertEqual(self.factory.calls,[])
