"""Run the common failure matrix against native, browser and legacy adapters."""
import json
import copy
import hashlib
from pathlib import Path
from unittest.mock import patch
from orchestrator.runtime import Runtime
from orchestrator.continuations import ADAPTER_GAPS
from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery
from tests import test_continuation_controller as common
from tests import test_photo_projection as native
from tests import test_public_photo_recovery as browser
from tests import test_review_budget_recovery as budget


class Tests(common.Tests):
    KINDS=('registered_input_preflight','public_photo_setup','saved_review_budget')

    def stopped(self,kind):
        if kind=='registered_input_preflight':
            helper=native.Tests();self.addCleanup(helper.doCleanups)
            fixture,p,s,parent,_=helper.stopped_graph()
            return fixture.state,fixture.rt,parent,p,s,'parent','produce'
        fixture=browser.Tests() if kind=='public_photo_setup' else budget.Tests()
        fixture.setUp();self.addCleanup(fixture.tearDown)
        if kind=='public_photo_setup':
            p,s,parent,tid=fixture.prepare()
            return fixture.state,fixture.rt,parent,p,s,'photos',tid
        p,s,producer,parent=fixture.stopped()
        return fixture.state,fixture.rt,parent,p,s,'parent','review'

    def test_every_migrated_adapter_has_the_common_failure_matrix(self):
        # Worker startup and definitive provider-schema rejection have their own
        # request/tool/changed-journal matrices in their focused suites.
        self.assertEqual(set(ADAPTER_GAPS),set(self.KINDS)|set(common.Tests.KINDS)|{'worker_startup','provider_schema'})

    def test_native_continuation_then_review_budget_continuation_composes_in_one_run(self):
        helper=native.Tests();self.addCleanup(helper.doCleanups)
        fixture,p,s,first,_=helper.stopped_graph();rt=fixture.rt;state=fixture.state
        with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,'parent'))
        rt=Runtime(rt.root,fixture.factory,connection=state.db);rt.tick('parent')
        candidate=rt.task('parent','produce')['latest'];self.assertNotEqual(candidate,first)
        frozen=fixture.factory.sessions[candidate]['frozen']
        raw,manifest=native.product_photos.build(frozen,lambda path:(Path(frozen['workspace'])/path).read_bytes(),
            fetch=lambda *args:(native.photo(),'image/jpeg','https://images.example/verified.jpg'))
        fixture.factory.finish(candidate);(Path(frozen['workspace'])/'photos.zip').write_bytes(raw)
        fixture.factory.sessions[candidate]['status']['operation']=dict(outcome='completed',validation=manifest,output_sha256=hashlib.sha256(raw).hexdigest())
        rt.tick('parent');review=rt.task('parent','review')['latest'];self.assertIsNotNone(review)
        review_session=fixture.factory.sessions[review]
        (review_session['workspace']/'review.md').write_text('Unaccepted controlled review draft')
        review_session['status']=dict(status='finished',token=review,exit_code=-15,reason='tool_limit',tool_calls=25,
            external_outcome='no_pending_response',pending_requests=[])
        rt.tick('parent')
        with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,'parent'))
        rt=Runtime(rt.root,fixture.factory,connection=state.db);rt.tick('parent')
        final_review=rt.task('parent','review')['latest'];self.assertNotEqual(final_review,review)
        self.assertEqual(fixture.factory.sessions[final_review]['frozen']['review_target'],candidate)
        fixture.factory.finish(final_review,decision='accept')
        self.assertEqual(rt.tick('parent')['status'],'completed')
        self.assertEqual(rt.task('parent','produce')['attempts'],2)
        self.assertEqual(state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        receipts=[json.loads(r[0]) for r in state.db.execute("SELECT data FROM production_events WHERE kind='continuation_committed' ORDER BY id")]
        self.assertEqual([r['kind'] for r in receipts],['registered_input_preflight','saved_review_budget'])
        self.assertEqual([r['allocation']['cycle'] for r in receipts],[1,2])

    def test_grouped_browser_recovery_is_atomic_and_dispatches_each_parent_once(self):
        fixture=browser.Tests();fixture.setUp();self.addCleanup(fixture.tearDown)
        p,s,parent,tid=fixture.prepare();rt=fixture.rt;state=fixture.state
        second=copy.deepcopy(rt.spec(rt.task('photos',tid)));second['id']='second-browser'
        rt.add_future('photos',second);rt.tick('photos')
        second_parent=rt.task('photos',second['id'])['latest'];self.assertIsNotNone(second_parent)
        fixture.factory.sessions[second_parent]['status']=copy.deepcopy(fixture.factory.sessions[parent]['status'])
        rt.tick('photos');tasks={name:rt.task('photos',name) for name in (tid,second['id'])}
        calls=list(fixture.factory.calls);original=Runtime.event;seen=[]
        def fail_second(runtime,run,task,attempt,kind,data):
            if kind=='continuation_committed':
                seen.append(attempt)
                if len(seen)==2:raise OSError('Injected second continuation failure')
            return original(runtime,run,task,attempt,kind,data)
        with self.assertRaisesRegex(OSError,'second continuation'),patch.object(Runtime,'event',fail_second),transaction(state.db):
            recovery.begin(state,p,s,'photos')
        self.assertEqual({name:rt.task('photos',name) for name in tasks},tasks)
        self.assertEqual(state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)
        self.assertEqual(state.db.execute("SELECT count(*) FROM production_events WHERE kind='continuation_committed'").fetchone()[0],0)
        self.assertEqual(fixture.factory.calls,calls)
        with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,'photos'))
        restarted=Runtime(rt.root,fixture.factory,connection=state.db);restarted.tick('photos');restarted.tick('photos')
        self.assertEqual(len(fixture.factory.calls),len(calls)+2)
        self.assertEqual([restarted.task('photos',name)['attempts'] for name in tasks],[2,2])
        receipts=[json.loads(r[0]) for r in state.db.execute("SELECT data FROM production_events WHERE kind='continuation_committed'")]
        self.assertEqual({r['parent'] for r in receipts},{parent,second_parent})
        self.assertEqual(len({c['allocation']['cycle'] for c in receipts}),1)

    def test_limit_changes_are_explicit_in_the_committed_allocation_receipt(self):
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                state,rt,parent,p,s,run,tid=self.stopped(kind)
                before=rt.spec(rt.task(run,tid))['limits']
                with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,run))
                after=rt.spec(rt.task(run,tid))['limits']
                receipt=json.loads(state.db.execute("SELECT data FROM production_events WHERE kind='continuation_committed'").fetchone()[0])
                self.assertEqual(receipt['invocation_limits_before'],before)
                self.assertEqual(receipt['invocation_limits_after'],after)
                self.assertEqual(receipt['allocation']['cycle'],1)
                self.assertLessEqual(after['seconds'],recovery.DELIVERY_POLICY['seconds'])
                self.assertLessEqual(after['tool_calls'],recovery.DELIVERY_POLICY['tool_calls'])
                if kind=='registered_input_preflight':self.assertEqual(before,after)
                elif kind=='public_photo_setup':self.assertLess(after['seconds'],before['seconds'])
                else:self.assertGreater(after['tool_calls'],before['tool_calls'])
