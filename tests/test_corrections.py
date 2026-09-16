"""Local correction scheduling with tiny text artifacts and scripted receipts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import contracts as c,corrections,execution
from orchestrator.runtime import Runtime
from task_relay.production_control import runtime_digest
from tests.test_orchestrator import FakeFactory,pair,task
from tests.test_mixed_execution import operation


def graph():
    p=pair();author,review=p['tasks']
    author['outputs']=[dict(path='slides.json',purpose='Slide data',media_type='application/json')]
    review['inputs'][0].update(output='slides.json',media_type='application/json')
    deck=operation('deck','pptx.create',[dict(from_task='produce',output='slides.json',path='slides.json',
        purpose='Reviewed data',authority='Unaccepted data',media_type='application/json')],['produce','review'],user_gate='Select deck')
    deck['outputs']=[dict(path='deck.pptx',purpose='Deck',media_type=execution.REGISTRY['pptx.create']['output_type'])]
    final=task('final',review_of='deck',dependencies=['deck'],max_attempts=2,
        inputs=[dict(from_task='deck',output='deck.pptx',path='candidate.pptx',purpose='Inspect deck',authority='Unaccepted candidate',media_type=deck['outputs'][0]['media_type'])])
    final['criteria']=deck['criteria'];final['outputs']=[dict(path='review.md',purpose='Review')]
    p['tasks'] += [deck,final];corrections.compile(p['tasks']);return p


class Tests(unittest.TestCase):
    def setUp(self):
        availability=patch.object(execution,'available');availability.start();self.addCleanup(availability.stop)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.factory=FakeFactory();self.rt=Runtime(Path(temp.name)/'runtime',self.factory);self.addCleanup(self.rt.close)
        self.rt.create(graph());self.digest=runtime_digest(self.rt,'demo');self.rt.tick('demo')

    def finish(self,tid,decision='delivered',failure=False):
        a=self.rt.task('demo',tid)['latest'];self.assertIsNotNone(a)
        self.factory.finish(a,decision=decision)
        if tid=='deck':
            self.factory.sessions[a]['status']['operation']={'outcome':'failed' if failure else 'completed','reason':'Invalid slide data' if failure else None}
            if failure:self.factory.sessions[a]['status'].update(exit_code=1,reason='Invalid slide data')
        self.rt.tick('demo');return a

    def to_deck(self):
        self.finish('produce');self.finish('review','accept')

    def test_two_review_boundaries_correct_exact_versions_and_reach_user_gate(self):
        original=self.finish('produce');first_spec_review=self.finish('review','revise')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],2)
        current=self.factory.sessions[self.rt.task('demo','produce')['latest']]['frozen']
        self.assertEqual({self.rt.artifact(i['artifact'])['attempt'] for i in current['inputs'] if i.get('previous_delivery')},
                         {original,first_spec_review})
        revised=self.finish('produce');self.finish('review','accept')
        first_deck=self.finish('deck')
        before=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(first_deck,)).fetchone())
        first_review=self.finish('final','revise')
        current=self.rt.task('demo','produce');self.assertEqual(current['attempts'],3)
        spec=self.factory.sessions[current['latest']]['frozen']
        artifacts=[self.rt.artifact(i['artifact']) for i in spec['inputs'] if i.get('previous_delivery')]
        self.assertEqual({a['attempt'] for a in artifacts},{revised,first_review})
        self.assertEqual(runtime_digest(self.rt,'demo'),self.digest)
        self.finish('produce');self.finish('review','accept');self.finish('deck');self.finish('final','accept')
        self.assertEqual(self.rt.status('demo')['status'],'awaiting_user')
        self.assertEqual(self.rt.task('demo','deck')['attempts'],2)
        self.assertEqual(dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(first_deck,)).fetchone()),before)
        self.assertNotEqual(original,revised)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_confirmed_local_failure_corrects_then_stops_at_budget(self):
        self.to_deck();self.finish('deck',failure=True)
        self.assertIn(self.rt.task('demo','produce')['status'],('launching','running'))
        self.finish('produce');self.finish('review','accept');self.finish('deck',failure=True)
        self.assertEqual(self.rt.task('demo','deck')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','deck')['attempts'],2)
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','produce')['attempts'],2)

    def test_third_preparation_attempt_is_reserved_for_built_deck(self):
        self.finish('produce');self.finish('review','revise')
        self.finish('produce');self.finish('review','revise')
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],2)
        self.assertEqual(self.rt.task('demo','deck')['attempts'],0)

    def test_uncertain_operation_cannot_trigger_correction(self):
        self.to_deck();a=self.rt.task('demo','deck')['latest']
        self.factory.sessions[a]['status']={'status':'uncertain','reason':'No terminal receipt'}
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','deck')['status'],'uncertain')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],1)

    def test_api_and_host_operations_cannot_receive_policy(self):
        for capability in ('gemini.text','images.collect','rhino.run_python'):
            candidate=copy.deepcopy(graph()['tasks'][2]);candidate['execution']['capability']=capability
            with self.assertRaises(ValueError):c.assignment(candidate)

    def test_frozen_one_attempt_operation_remains_one_attempt(self):
        candidate=graph();deck=candidate['tasks'][2]
        deck.pop('review_correction');deck['max_attempts']=1
        fresh=Runtime(self.rt.root.parent/'legacy',FakeFactory());self.addCleanup(fresh.close)
        fresh.create(candidate);fresh.tick('demo')
        for tid,decision in [('produce','delivered'),('review','accept'),('deck','delivered'),('final','revise')]:
            a=fresh.task('demo',tid)['latest'];fresh.factory.finish(a,decision=decision);fresh.tick('demo')
        self.assertEqual(fresh.task('demo','deck')['status'],'blocked')
        self.assertEqual(fresh.task('demo','deck')['attempts'],1)
