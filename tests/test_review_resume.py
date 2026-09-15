import json
import unittest

from tests import test_production_selections as fixture
from tests.test_orchestrator import pair
from task_relay import production_control as pc
from task_relay import production_selections as selections
from task_relay import production_lifecycle as lifecycle
from task_relay import capabilities


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    worker=fixture.Tests.worker
    choose=fixture.Tests.choose

    def waiting(self):
        value=pair(gate='Review prepared data');value['id']='resume-test'
        downstream=pair(gate='Review final output')['tasks']
        downstream[0].update(id='finish',dependencies=['produce','review'],inputs=[dict(
            from_task='produce',output='output.txt',path='input.txt',purpose='Prepared data',authority='Reviewed candidate')])
        downstream[1].update(id='finish-review',review_of='finish',dependencies=['finish'])
        downstream[1]['inputs'][0]['from_task']='finish'
        value['tasks'].extend(downstream);self.rt.create(value)
        with self.state.db:pc.start(self.state,'resume-test',pc.inspect(self.state,'resume-test')[0]['revision'])
        worker=self.worker();worker.tick()
        self.factory.finish(self.rt.task('resume-test','produce')['latest']);worker.tick()
        self.factory.finish(self.rt.task('resume-test','review')['latest'],decision='accept');worker.tick()
        self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute("SELECT * FROM production_selection_cards WHERE run='resume-test'").fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        return worker,card,mid

    def legacy(self):
        worker,card,mid=self.waiting()
        with self.state.db:
            self.state.put('production-review-grant:resume-test',False)
            plan=self.state.db.execute("SELECT plan FROM production_runs WHERE id='resume-test'").fetchone()[0]
            self.state.db.execute('''INSERT INTO production_plans(id,request_id,channel,request,options,context,
                context_hash,provider,model,status,plan,token,expires,run,created)
                VALUES ('old-plan',912,'telegram','Original approved work','{}','{}','fixture','gemini','fixture',
                'started',?,'old-token',9999999999,'resume-test',1)''',(plan,))
        self.choose(card,mid)
        return worker

    def test_selection_resumes_only_remaining_tasks_once(self):
        worker,card,mid=self.waiting()
        self.assertFalse(self.state.get('production-enabled:resume-test'))
        self.choose(card,mid);self.choose(card,mid)
        self.assertTrue(self.state.get('production-enabled:resume-test'))
        self.assertEqual(len(self.factory.calls),2)  # no external dispatch in selection transaction
        worker.tick();worker.tick()
        self.assertEqual(len(self.factory.calls),3)
        self.assertEqual(self.rt.task('resume-test','produce')['attempts'],1)
        self.assertEqual(self.rt.task('resume-test','finish')['attempts'],1)

    def test_cancel_or_changed_authorization_never_resumes(self):
        worker,card,mid=self.waiting()
        with self.state.db:self.state.put('production-control-epoch:resume-test',1)
        self.choose(card,mid);worker.tick()
        self.assertFalse(self.state.get('production-enabled:resume-test'))
        self.assertEqual(len(self.factory.calls),2)
        self.assertIsNone(pc.review_resume_digest(self.state,'resume-test',legacy=True))

    def test_legacy_resume_needs_explicit_action_and_unchanged_started_plan(self):
        worker=self.legacy()
        self.assertFalse(self.state.get('production-enabled:resume-test'))
        self.assertIsNotNone(pc.review_resume_digest(self.state,'resume-test',legacy=True))
        buttons=lifecycle.controls(self.state,'production:resume-test:status','resume-test')
        self.assertTrue(any(b['text']=='Resume remaining work' for row in buttons for b in row))
        action={'kind':'resume_production','workflow':'resume-test'}
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            first=capabilities.dispatch(self.state,{'id':933,'prompt':'Run the remaining step.'},action,{})
            self.assertEqual(first,capabilities.dispatch(self.state,{'id':933,'prompt':'Run the remaining step.'},action,{}))
        worker.tick();self.assertEqual(len(self.factory.calls),3)
        self.assertEqual(self.rt.task('resume-test','produce')['attempts'],1)

    def test_legacy_plan_change_blocks_recovery(self):
        self.legacy()
        with self.state.db:
            self.state.db.execute("UPDATE production_plans SET plan='{}' WHERE id='old-plan'")
        self.assertIsNone(pc.review_resume_digest(self.state,'resume-test',legacy=True))
        with self.state.db,self.assertRaises(ValueError):pc.resume_review(self.state,'resume-test',legacy=True)


if __name__=='__main__':unittest.main()
