"""Trusted owner admission through the real scheduler with scripted workers."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory, plan, task


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'runtime';self.factory=FakeFactory()
        self.rt=Runtime(self.root,self.factory)
        self.addCleanup(lambda:self.rt.db.close())
        self.rt.create(plan([task('initial')]))

    def batch(self):
        def input(ident):return dict(from_task=ident,output='output.txt',path=ident+'.txt',purpose='Exact delegate result',authority='Candidate evidence')
        return [task('a'),task('b'),task('integrate',dependencies=['a','b'],inputs=[input('a'),input('b')]),
                task('review',review_of='integrate',dependencies=['integrate'],inputs=[input('integrate')])]

    def finish(self,ident,decision='delivered'):
        attempt=self.rt.task('demo',ident)['latest']
        self.factory.finish(attempt,decision=decision)
        return self.rt.tick('demo')

    def test_owner_delegates_integrates_and_reviews_through_one_scheduler(self):
        self.rt.tick('demo');self.finish('initial')
        original=self.rt.task('demo','initial')['assignment']
        before=len(self.factory.calls)
        receipt=self.rt.add_futures('demo',self.batch(),request_id='owner-turn-2')
        self.assertEqual(len(self.factory.calls),before)
        self.assertEqual(len(receipt['assignments']),4)
        self.rt.tick('demo')
        self.assertEqual(len(self.factory.calls),before+2)
        self.finish('b');self.assertIsNone(self.rt.task('demo','integrate')['latest'])
        self.finish('a')
        frozen=self.factory.sessions[self.rt.task('demo','integrate')['latest']]['frozen']
        self.assertEqual(frozen['brief'],'A small workflow')
        for item in frozen['inputs']:
            exact=self.rt.output('demo',item['from_task'],item['output'])
            self.assertEqual(item['artifact'],exact['id'])
            self.assertEqual(item['sha256'],exact['sha256'])
        self.finish('integrate')
        self.assertEqual(self.rt.task('demo','integrate')['status'],'awaiting_review')
        result=self.finish('review','accept')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.rt.task('demo','initial')['assignment'],original)
        self.assertEqual(len(self.factory.calls),5)

    def test_restart_repeated_request_does_not_duplicate_workers(self):
        batch=self.batch();receipt=self.rt.add_futures('demo',batch,request_id='owner-turn-2')
        self.rt.tick('demo');calls=list(self.factory.calls)
        self.rt.db.close();self.rt=Runtime(self.root,self.factory)
        self.assertEqual(self.rt.add_futures('demo',batch,request_id='owner-turn-2'),receipt)
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0],5)
        batch[0]['instruction']='Different work'
        with self.assertRaisesRegex(ValueError,'different batch'):
            self.rt.add_futures('demo',batch,request_id='owner-turn-2')

    def test_invalid_or_interrupted_batch_is_atomic(self):
        batch=self.batch();batch[-1]['dependencies']=['missing']
        with self.assertRaises(ValueError):self.rt.add_futures('demo',batch,request_id='bad')
        event=self.rt.event
        def fail(run,tid,attempt,kind,data):
            if kind=='future_tasks_added':raise RuntimeError('interrupted commit')
            return event(run,tid,attempt,kind,data)
        with patch.object(self.rt,'event',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'interrupted commit'):
                self.rt.add_futures('demo',self.batch(),request_id='retry')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0],1)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_assignments').fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])
        self.rt.add_futures('demo',self.batch(),request_id='retry')

    def test_uncertain_delegate_is_not_replayed_and_independent_work_continues(self):
        self.rt.tick('demo');self.finish('initial')
        self.rt.add_futures('demo',self.batch(),request_id='parallel')
        self.rt.tick('demo');aid=self.rt.task('demo','a')['latest']
        self.factory.sessions[aid]['status']={'status':'uncertain','reason':'No confirmed provider response'}
        self.finish('b');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','b')['status'],'completed')
        self.assertEqual(self.rt.task('demo','a')['status'],'uncertain')
        self.assertIsNone(self.rt.task('demo','integrate')['latest'])
        self.assertEqual(self.factory.calls.count(aid),1)

    def test_late_review_or_paused_owner_rejects_whole_batch(self):
        self.rt.tick('demo')
        batch=[task('new'),task('late',review_of='initial',dependencies=['initial'],
            inputs=[dict(from_task='initial',output='output.txt',path='candidate.txt',purpose='Candidate',authority='Candidate')])]
        with self.assertRaisesRegex(ValueError,'before its producer starts'):
            self.rt.add_futures('demo',batch)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0],1)
        self.rt.pause('demo')
        with self.assertRaisesRegex(ValueError,'active workflow'):self.rt.add_futures('demo',self.batch())
