"""Small offline graphs: real controller/tool loop, scripted text, no providers."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import job_owner,contracts as c
from orchestrator.runtime import Runtime
from tests import test_job_owner_loop as fixture

class Tests(unittest.TestCase):
    invoke=fixture.Tests.invoke
    delegate=fixture.Tests.delegate
    batch=fixture.Tests.batch
    finish_children=fixture.Tests.finish_children
    test_committed_delegation_crash_retains_progress=fixture.Tests.test_committed_delegation_survives_crash_before_normal_checkpoint
    def setUp(self):
        fixture.Tests.setUp(self)
        self.grant.update(owner_progress_version=1,max_tasks=20,owner_turns=8)
    def create(self,concurrency=3):
        job_owner.create(self.rt,'job','Parallel branches then exact reviewed final text.',fixture.BACKEND,[],self.grant,concurrency=concurrency)
        self.rt.tick('job')
    def start(self):
        self.create();self.delegate(self.batch('fast')+self.batch('slow'));self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['status'],'waiting')
    def finish(self,tid,decision='delivered'):
        self.factory.finish(self.rt.task('job',tid)['latest'],decision=decision);self.rt.tick('job')
        plan=job_owner.original(self.rt,'job')
        active=self.rt.db.execute("SELECT count(*) FROM production_attempts WHERE state IN ('launching','running','cancelling','uncertain')").fetchone()[0]
        self.assertLessEqual(active,plan['concurrency'])
    def accepted_fast(self):
        self.finish('fast');self.assertEqual(self.rt.task('job','owner')['status'],'waiting')
        self.finish('fast_review','accept')
    def ref(self,tid):
        return dict(from_task=tid,output='report.txt',path=tid+'.txt',purpose='Exact prerequisite',authority='Candidate requires review',media_type='text/plain')
    def test_completed_branch_feeds_downstream_before_other_review_then_join_and_delivery(self):
        self.start();slow=self.rt.task('job','slow')['latest'];self.accepted_fast()
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertEqual(self.rt.task('job','slow')['latest'],slow)
        next_batch=self.batch('next',[self.ref('fast')]);next_batch[0]['dependencies']=['fast']
        join=self.batch('joined',[self.ref('next'),self.ref('slow')]);join[0]['dependencies']=['next','slow']
        self.delegate(next_batch+join,key='downstream');self.rt.tick('job')
        self.assertIsNotNone(self.rt.task('job','next')['latest'])
        self.assertIsNone(self.rt.task('job','joined')['latest'])
        self.assertEqual(self.rt.task('job','slow')['status'],'running')
        # Both the scheduler and the waiting owner's consumed progress survive restart.
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.finish('next');self.finish('next_review','accept')
        self.invoke([('job_wait',{})]);self.rt.tick('job')
        attempts=self.rt.task('job','owner')['attempts'];calls=list(self.factory.calls)
        for _ in range(4):self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],attempts);self.assertEqual(self.factory.calls,calls)
        self.finish('slow');self.assertIsNone(self.rt.task('job','joined')['latest'])
        self.finish('slow_review','accept')
        self.assertIsNotNone(self.rt.task('job','joined')['latest'])
        self.invoke([('job_wait',{})]);self.rt.tick('job')
        self.finish('joined');self.finish('joined_review','accept')
        artifact=self.rt.output('job','joined','report.txt')
        result,_=self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':artifact['id']}),summary='Exact reviewed joined result'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed')
        self.assertEqual(len(self.factory.calls),len(set(self.factory.calls)))
    def test_child_finishing_during_owner_invocation_is_not_lost_at_wait(self):
        from tests.test_operation_session import Script
        self.create(concurrency=4)
        self.delegate(self.batch('fast')+self.batch('slow')+self.batch('third'));self.rt.tick('job')
        self.accepted_fast();self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        request=Script.request
        def during_request(client,*args,**kwargs):
            # This transition occurs after the owner's snapshot was supplied.
            self.finish('slow');self.finish('slow_review','accept')
            return request(client,*args,**kwargs)
        with patch.object(Script,'request',new=during_request):self.invoke([('job_wait',{})])
        # Restart after checkpoint, before the controller collects the owner.
        self.rt.close();self.rt=Runtime(self.root,self.factory);self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],3)
        self.assertEqual(self.rt.task('job','third')['status'],'running')
        self.invoke([('job_wait',{})]);self.rt.tick('job')
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],3)
        self.assertEqual(self.rt.task('job','owner')['status'],'waiting')
    def test_confirmed_failure_wakes_owner_without_replaying_the_slow_branch(self):
        self.start();slow=self.rt.task('job','slow')['latest'];aid=self.rt.task('job','fast')['latest']
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,external_outcome='no_pending_response',reason='Confirmed fixture failure')
        self.rt.tick('job')
        self.assertEqual(self.rt.task('job','fast')['status'],'blocked')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.delegate(self.batch('repair'),key='repair');self.rt.tick('job')
        self.assertIsNotNone(self.rt.task('job','repair')['latest'])
        self.assertEqual(self.factory.calls.count(slow),1)
        self.assertEqual(self.rt.task('job','slow')['status'],'running')
    def test_no_progress_and_full_concurrency_do_not_dispatch_duplicate_owner(self):
        self.start();calls=list(self.factory.calls)
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(calls,self.factory.calls)
        self.accepted_fast();owner=self.rt.task('job','owner')['latest']
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(self.factory.calls.count(owner),1)
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
    def test_simultaneous_branch_results_coalesce_into_one_owner_invocation(self):
        self.start();self.finish('fast');self.finish('slow')
        for tid in ('fast_review','slow_review'):
            self.factory.finish(self.rt.task('job',tid)['latest'],decision='accept')
        self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        owner=self.rt.task('job','owner')['latest']
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['latest'],owner)
        self.assertEqual(self.factory.calls.count(owner),1)

    def test_last_owner_turn_is_reserved_until_all_children_settle(self):
        self.grant['owner_turns']=2;self.start();self.accepted_fast()
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertEqual(self.rt.task('job','owner')['status'],'waiting')
        self.finish('slow');self.finish('slow_review','accept')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
    def test_legacy_grant_still_waits_for_whole_batch(self):
        self.grant.pop('owner_progress_version');self.start();self.accepted_fast()
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.finish('slow');self.finish('slow_review','accept')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
    def test_unknown_effect_blocks_wake_and_replacement_even_with_completed_sibling(self):
        self.start();aid=self.rt.task('job','slow')['latest'];self.factory.sessions[aid]['status']=dict(status='uncertain',reason='Missing provider outcome')
        self.rt.tick('job');calls=list(self.factory.calls);self.finish('fast')
        self.assertIsNotNone(self.rt.output('job','fast','report.txt'))
        self.assertIsNone(self.rt.task('job','fast_review')['latest'])
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertEqual(self.rt.status('job')['status'],'uncertain');self.assertEqual(self.factory.calls.count(aid),1)
