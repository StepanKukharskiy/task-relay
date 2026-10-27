"""An explicit top-up continuation retains the rejected plan and exact scope."""
import json
import unittest
from orchestrator.storage import transaction
from task_relay import pipelines, production_planning
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

    def test_top_up_continuation_preserves_prior_work_and_deduplicates(self):
        pipeline,old=self.rejected_planning_fixture(402)
        failed_call=dict(self.state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(old['id'],)).fetchone())
        pipelines.tick(self.state);pipelines.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        with transaction(self.state.db):
            pipelines.control(self.state,pipeline['id'],'retry_planning',request='done')
        current=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(self.step(pipeline,'model')['target'],)).fetchone()
        for key in ('context','context_hash','options','request','provider','model'):
            self.assertEqual(current[key],old[key])
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old['id'],)).fetchone()),dict(old))
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(old['id'],)).fetchone()),failed_call)
        self.assertEqual(current['calls'],0);self.assertEqual(current['status'],'queued')
        self.assertEqual(self.step(pipeline,'finish')['status'],'pending')
        receipt=json.loads(self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='planning_retry_requested'").fetchone()[0])
        self.assertEqual(receipt['request'],'done')
        with transaction(self.state.db),self.assertRaises(ValueError):
            pipelines.control(self.state,pipeline['id'],'retry_planning',request='done')
        self.assertEqual(len(self.factory.calls),0)

    def test_uncertainty_other_http_errors_and_retained_response_do_not_retry(self):
        pipeline,old=self.rejected_planning_fixture(402)
        cases=[('uncertain',old['error'],None),('blocked','Gemini request failed (500)',None),
               ('blocked',old['error'],'{"decision":"ready"}'),('blocked','Connection timed out',None)]
        for status,error,response in cases:
            with self.subTest(status=status,error=error,response=response):
                self.state.db.execute('UPDATE production_plans SET status=?,error=? WHERE id=?',(status,error,old['id']))
                self.state.db.execute('UPDATE production_plan_calls SET error=?,response=? WHERE plan_id=?',(error,response,old['id']))
                row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old['id'],)).fetchone()
                self.assertFalse(production_planning.rate_limited_plan(self.state,row))


if __name__=='__main__':unittest.main()
