"""Same failure boundaries for record and review continuations; no live I/O."""
import json
import unittest
from unittest.mock import patch
from orchestrator import contracts as c
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery
from tests import test_operation_session as reviews, test_record_completion_continuation as records
from tests.test_orchestrator import task as task_spec


class Tests(unittest.TestCase):
    KINDS=('record_checkpoint','local_review_session')
    def test_rejection_after_last_review_does_not_spend_an_unreviewable_producer_attempt(self):
        helper=reviews.Tests();self.addCleanup(helper.doCleanups)
        f,p,s,producer,parent,_=helper.stopped(max_attempts=2)
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        f.rt.tick('parent');review=f.rt.task('parent','review')['latest']
        rejected=dict(summary='Correction needed',decision='revise',instruction='Correct candidate text',findings=[],
            checks={'c1':dict(passed=False,evidence='Candidate requires the requested correction')})
        helper.run_worker(f,review,reviews.Script([('finish',dict(report_json=c.encoded(rejected)))]))
        calls=list(f.factory.calls);f.rt.tick('parent')
        self.assertEqual(f.factory.calls,calls)
        self.assertEqual(f.rt.task('parent','produce')['latest'],producer)
        self.assertEqual(f.rt.task('parent','produce')['attempts'],1)
        event=f.state.db.execute("SELECT data FROM production_events WHERE kind='revision_limit'").fetchone()
        self.assertEqual(json.loads(event[0])['code'],'review_capacity_exhausted')

    def test_yield_restart_rejection_correction_and_downstream_delivery_use_current_version(self):
        helper=reviews.Tests();self.addCleanup(helper.doCleanups)
        f,p,s,producer,parent,_=helper.stopped(max_attempts=3)
        f.rt.add_future('parent',task_spec('downstream',dependencies=['produce','review'],tools=['files'],
            limits=dict(seconds=600,tool_calls=3,provider_requests=3,output_bytes=200000),
            inputs=[dict(from_task='produce',output='output.txt',path='accepted.txt',purpose='Reviewed source',authority='Exact reviewed candidate')]))
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        f.rt=Runtime(f.rt.root,f.factory,connection=f.state.db);f.rt.tick('parent')
        review=f.rt.task('parent','review')['latest']
        rejected=dict(summary='Candidate requires correction',decision='revise',instruction='Replace with corrected text',findings=[],
            checks={'c1':dict(passed=False,evidence='The candidate text needs the specified correction')})
        result,_=helper.run_worker(f,review,reviews.Script([('finish',dict(report_json=c.encoded(rejected)))]))
        self.assertEqual(result['decision'],'revise');f.rt.tick('parent')
        self.assertIsNone(f.rt.task('parent','downstream')['latest'])
        corrected=f.rt.task('parent','produce')['latest'];self.assertNotEqual(corrected,producer)
        delivered=dict(summary='Wrote corrected candidate',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Corrected text written')})
        helper.run_worker(f,corrected,reviews.Script([('file_write',dict(path='output.txt',text='Corrected exact candidate.')),('finish',dict(report_json=c.encoded(delivered)))]))
        f.rt.tick('parent');new_review=f.rt.task('parent','review')['latest']
        self.assertNotEqual(new_review,review,dict(f.rt.task('parent','review')))
        frozen=f.factory.sessions[new_review]['frozen'];self.assertEqual(frozen['review_target'],corrected)
        self.assertNotIn('review_checkpoint',frozen)
        helper.run_worker(f,new_review,reviews.Script([reviews.final('Corrected exact candidate inspected.')]))
        f.rt.tick('parent');downstream=f.rt.task('parent','downstream')['latest'];self.assertIsNotNone(downstream)
        bound=f.factory.sessions[downstream]['frozen']['inputs'][0]
        self.assertEqual(bound['artifact'],f.rt.output('parent','produce','output.txt')['id'])
        helper.run_worker(f,downstream,reviews.Script([('file_write',dict(path='output.txt',text='Final result from corrected candidate.')),('finish',dict(report_json=c.encoded(delivered)))]))
        self.assertEqual(f.rt.tick('parent')['status'],'completed')
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(f.state.db.execute("SELECT count(*) FROM production_events WHERE kind='continuation_committed'").fetchone()[0],1)

    def stopped(self,kind):
        if kind=='record_checkpoint':
            fixture=records.Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
            rt,parent,p,s=fixture.native()
            return fixture.state,rt,parent,p,s,'native','producer'
        helper=reviews.Tests();self.addCleanup(helper.doCleanups)
        fixture,p,s,producer,parent,_=helper.stopped()
        return fixture.state,fixture.rt,parent,p,s,'parent','review'

    def test_both_adapters_commit_once_then_restart_without_dispatch_inside_transaction(self):
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                state,rt,parent,p,s,run,tid=self.stopped(kind)
                old=dict(state.db.execute('SELECT * FROM production_attempts WHERE id=?',(parent,)).fetchone())
                calls=list(rt.factory.calls)
                with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,run))
                self.assertEqual(rt.factory.calls,calls)
                self.assertFalse(rt.continue_attempt(run,tid,parent,kind=kind))
                self.assertEqual(state.db.execute("SELECT count(*) FROM production_events WHERE kind='continuation_committed'").fetchone()[0],1)
                restarted=Runtime(rt.root,rt.factory,connection=state.db);restarted.tick(run);restarted.tick(run)
                self.assertEqual(len(rt.factory.calls),len(calls)+1)
                self.assertEqual(old,dict(state.db.execute('SELECT * FROM production_attempts WHERE id=?',(parent,)).fetchone()))
                self.assertEqual(restarted.task(run,tid)['attempts'],2)

    def test_failed_commit_rolls_back_assignment_allocation_and_queue_for_both_adapters(self):
        original=Runtime.event
        def fail(runtime,run,task,attempt,kind,data):
            if kind=='continuation_committed':raise OSError('Injected recovery commit failure')
            return original(runtime,run,task,attempt,kind,data)
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                state,rt,parent,p,s,run,tid=self.stopped(kind)
                before=rt.task(run,tid);assignments=state.db.execute('SELECT count(*) FROM production_assignments').fetchone()[0]
                with self.assertRaisesRegex(OSError,'Injected'),patch.object(Runtime,'event',fail),transaction(state.db):
                    recovery.begin(state,p,s,run)
                self.assertEqual(rt.task(run,tid),before)
                self.assertEqual(state.db.execute('SELECT count(*) FROM production_assignments').fetchone()[0],assignments)
                self.assertEqual(state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)
                with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,run))
                self.assertEqual(rt.task(run,tid)['status'],'queued')

    def test_changed_grant_or_receipt_after_commit_blocks_both_before_new_attempt(self):
        for kind in self.KINDS:
            for change in ('grant','receipt'):
                with self.subTest(kind=kind,change=change):
                    state,rt,parent,p,s,run,tid=self.stopped(kind)
                    with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,run))
                    committed=json.loads(state.db.execute("SELECT data FROM production_events WHERE kind='continuation_committed' ORDER BY id DESC LIMIT 1").fetchone()[0])
                    calls=list(rt.factory.calls)
                    with transaction(state.db):
                        if change=='grant':state.db.execute('DELETE FROM completion_recovery_grants WHERE pipeline=?',(p['id'],))
                        else:
                            receipt=json.loads(state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(parent,)).fetchone()[0])
                            receipt.update(external_outcome='unknown',pending_requests=['unresolved-intent'])
                            state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded(receipt),parent))
                    rt.tick(run)
                    if change=='grant' and committed['allocation'] is None:
                        # A separately revocable recovery grant does not own
                        # an unchanged attempt authorized by the original task.
                        self.assertEqual(len(rt.factory.calls),len(calls)+1)
                        self.assertEqual(rt.task(run,tid)['attempts'],2)
                        continue
                    self.assertEqual(rt.factory.calls,calls)
                    self.assertEqual(rt.task(run,tid)['attempts'],1)
                    self.assertEqual(rt.task(run,tid)['status'],'blocked')
                    event=state.db.execute("SELECT data FROM production_events WHERE kind='continuation_preflight_blocked'").fetchone()
                    self.assertIsNotNone(event);self.assertFalse(json.loads(event[0])['dispatched'])


if __name__=='__main__':unittest.main()
