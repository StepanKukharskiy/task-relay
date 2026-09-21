"""The same policy holds for models, images, documents and local code workers."""
import json
import unittest
from orchestrator import contracts, outcomes
from tests import test_orchestrator as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown

    def finish(self,tid,findings=None,decision='delivered',missing=None):
        aid=self.rt.task('demo',tid)['latest'];self.factory.finish(aid,decision=decision,missing=missing)
        path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
        value=json.loads(path.read_text());value['findings']=findings or [];path.write_text(json.dumps(value))
        self.rt.tick('demo');return aid

    def graph(self):
        plan=fixture.pair(gate=None)
        plan['tasks'].append(fixture.task('next',dependencies=['produce','review'],inputs=[dict(from_task='produce',output='output.txt',path='source.txt',purpose='Exact source',authority='Selected output')]))
        self.rt.create(plan);self.rt.tick('demo')

    def test_quality_from_producer_survives_ai_acceptance_and_holds_downstream_for_exact_user_choice(self):
        self.graph()
        findings=[outcomes.quality('layout','Slide image is cropped awkwardly','output.txt: saved layout preview')]
        aid=self.finish('produce',findings)
        self.finish('review',decision='accept')
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.assertEqual(self.rt.task('demo','next')['attempts'],0)
        task=self.rt.task('demo','produce');artifact=self.rt.output('demo','produce','output.txt')
        with self.assertRaises(ValueError):self.rt.select('demo','produce',artifact['id'],'old purpose','accept')
        self.rt.select('demo','produce',artifact['id'],self.rt.decision_purpose(task),'I inspected the preview and accept as-is')
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','next')['attempts'],1)
        event=json.loads(self.rt.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='user_selected'",(aid,)).fetchone()[0])
        self.assertEqual(event['quality_review']['findings'],findings)

    def test_reviewer_quality_revision_asks_user_instead_of_spending_correction_attempt(self):
        self.graph();self.finish('produce')
        self.finish('review',[outcomes.quality('shape','Model proportions differ','Measured candidate vs reference')],decision='revise')
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],1)
        self.assertEqual(self.rt.task('demo','review')['status'],'completed')
        self.assertEqual(len(self.factory.calls),2)

    def test_quality_never_overrides_missing_files_or_runtime_failure(self):
        self.graph()
        self.finish('produce',[outcomes.quality('appearance','Looks unusual','Candidate preview')],missing='output.txt')
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','next')['attempts'],0)
        self.assertIsNone(self.rt.quality_review(self.rt.task('demo','produce')))

    def test_execution_findings_block_even_when_worker_claims_delivery(self):
        self.graph()
        self.finish('produce',[dict(category='execution',code='python_error',message='Script crashed',evidence='Traceback in saved log')])
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)

    def test_uncertainty_never_becomes_quality_acceptance(self):
        self.graph()
        self.finish('produce',[dict(category='uncertainty',code='lost_connection',message='Submission outcome unknown',evidence='Connection lost before receipt')])
        self.assertEqual(self.rt.task('demo','produce')['status'],'uncertain')
        self.assertEqual(self.rt.task('demo','next')['attempts'],0)

    def test_every_category_uses_same_policy_and_malformed_findings_fail_closed(self):
        for category,want in [('quality','user_review'),('execution','block'),('integrity','block'),('authorization','block'),('uncertainty','reconcile')]:
            finding=dict(category=category,code='test',message='Observed issue',evidence='Saved report')
            self.assertEqual(outcomes.disposition([finding]),want)
        self.assertEqual(outcomes.disposition([]),'continue')
        for bad in ([{'category':'quality'}],None,[dict(category='invented',code='x',message='x',evidence='x')]):
            with self.assertRaises(ValueError):outcomes.disposition(bad)


if __name__=='__main__':unittest.main()
