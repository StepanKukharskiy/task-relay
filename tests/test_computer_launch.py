"""Managed startup uses committed intents, exact scopes and no replay."""
import copy
import json
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from orchestrator.computer_contract import resolve,validate
from task_relay import computer_contract as native, computer_sessions as journal, computer_target
from tests import test_computer_worker as worker_fixture
from tests.test_computer_sessions import SessionHelper
from tests.test_computer_use import TARGET


def runtime():
    value={'mode':'new-window','helper':'/synthetic/Relay.app','identity':SessionHelper.identity}
    return {**value,'selection':native.digest(value)}


def managed():
    return resolve({'selection':runtime()['selection'],'url':'https://example.com/one',
                    'allowed_urls':['https://example.com/one','https://example.com/two'],'max_seconds':120},runtime())


class LaunchHelper(SessionHelper):
    def call(self,request):
        if request['operation']!='launch':return super().call(request)
        actual=copy.deepcopy(request)
        actual['observation_request']['target']=TARGET
        result=super().call(actual)
        result.update(window_created=True,foreground_acquired=True,action_executed=True)
        return result


class Tests(unittest.TestCase):
    setUp=worker_fixture.Tests.setUp
    tearDown=worker_fixture.Tests.tearDown
    prepare=worker_fixture.Tests.prepare
    execute=worker_fixture.Tests.execute
    def test_unicode_urls_are_encoded_before_freezing_without_changing_query_meaning(self):
        from urllib.parse import urlsplit,parse_qsl
        raw='https://x.com/search?q=менеджер%20ozon&literal=%252F&tag=a+b&tag=a%20b'
        request={'selection':runtime()['selection'],'url':raw,'allowed_urls':[raw],'max_seconds':120}
        before=copy.deepcopy(request)
        selected=resolve(request,runtime());wire=selected['spec']['url']
        self.assertTrue(wire.isascii());self.assertIn('%D0%BC',wire)
        self.assertIn('literal=%252F&tag=a+b&tag=a%20b',wire)
        self.assertEqual(parse_qsl(urlsplit(raw).query),parse_qsl(urlsplit(wire).query))
        self.assertEqual(selected['spec']['allowed_urls'],[wire])
        self.assertEqual(request,before)
        self.assertEqual(resolve({**request,'url':wire,'allowed_urls':[wire]},runtime()),selected)

    def test_url_encoding_cannot_expand_or_merge_a_proposed_scope(self):
        raw='https://example.com/каталог?q=%2F'
        encoded='https://example.com/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3?q=%2F'
        request={'selection':runtime()['selection'],'url':raw,'allowed_urls':[encoded],'max_seconds':120}
        with self.assertRaisesRegex(ValueError,'Initial URL'):resolve(request,runtime())
        with self.assertRaisesRegex(ValueError,'distinct'):
            resolve({**request,'allowed_urls':[raw,encoded]},runtime())
        with self.assertRaisesRegex(ValueError,'ASCII'):
            resolve({**request,'url':'https://пример.рф/','allowed_urls':['https://пример.рф/']},runtime())

    def test_launch_binds_returned_target_and_preserves_frozen_scope(self):
        db=self.prepare();self.frozen['computer']=managed();helper=LaunchHelper(db)
        self.assertEqual(self.execute(db,helper)['decision'],'delivered')
        actions=list(db.execute('SELECT * FROM relay_computer_actions ORDER BY ordinal'))
        self.assertEqual([json.loads(a['request'])['operation'] for a in actions],['launch','navigate','scroll'])
        self.assertEqual(json.loads(actions[0]['request'])['observation_request']['target'],native.NEW_WINDOW)
        self.assertEqual(json.loads(actions[1]['request'])['observation_request']['target'],TARGET)
        row=journal.get(db,actions[0]['assignment'])
        self.assertEqual(json.loads(row['spec'])['target'],native.NEW_WINDOW)
        for a in actions:journal._verify_receipt(a['receipt'])
        before=len(helper.calls)
        with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        self.assertEqual(len(helper.calls),before)

    def test_lost_launch_receipt_never_reopens_or_calls_provider(self):
        db=self.prepare();self.frozen['computer']=managed()
        def lost(request,count):raise TimeoutError('Created window but response lost')
        helper=LaunchHelper(db,lost)
        with self.assertRaisesRegex(ValueError,'uncertain'):self.execute(db,helper)
        self.assertEqual(len(helper.calls),1);self.assertEqual(len(self.model.calls),0)
        row=db.execute('SELECT * FROM relay_computer_actions').fetchone()
        self.assertEqual(row['state'],'uncertain')
        with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        with self.assertRaisesRegex(ValueError,'Reconcile and stop'):
            journal.resume(db,row['assignment'],current_url='https://example.com/one',actor='test',note='resume')
        journal.resume(db,row['assignment'],current_url='https://example.com/one',actor='test',note='reconcile unknown launch',abandon=True)
        self.assertEqual(len(helper.calls),1)

    def test_cancel_before_launch_has_no_window_or_model_effect(self):
        db=self.prepare();self.frozen['computer']=managed();helper=LaunchHelper(db)
        (self.control/'cancel.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Cancelled'):self.execute(db,helper)
        self.assertEqual(helper.calls,[]);self.assertEqual(self.model.calls,[])

    def test_permission_failure_precedes_window_intent_and_provider(self):
        db=self.prepare();self.frozen['computer']=managed()
        class Denied(LaunchHelper):
            def require_ready(self):raise ValueError('Safari helper needs accessibility')
        helper=Denied(db)
        with self.assertRaisesRegex(ValueError,'needs accessibility'):self.execute(db,helper)
        self.assertEqual(helper.calls,[]);self.assertEqual(self.model.calls,[])
        self.assertEqual(db.execute('SELECT count(*) FROM relay_computer_actions').fetchone()[0],0)

    def test_takeover_after_launch_never_reclaims_focus(self):
        db=self.prepare();self.frozen['computer']=managed();helper=LaunchHelper(db)
        with self.assertRaisesRegex(ValueError,'stopped'):self.execute(db,helper,'takeover')
        self.assertEqual([r['operation'] for r in helper.calls],['launch'])
        self.assertEqual(db.execute('SELECT state FROM relay_computer_assignments').fetchone()[0],'cancelled')

    def test_missing_creation_proof_is_uncertain_before_model(self):
        db=self.prepare();self.frozen['computer']=managed()
        class Bad(LaunchHelper):
            def call(self,request):
                result=super().call(request);result.pop('window_created');return result
        with self.assertRaisesRegex(ValueError,'uncertain'):self.execute(db,Bad(db))
        self.assertEqual(self.model.calls,[])

    def test_declared_scope_rejects_invalid_urls_and_duration(self):
        for change in ({'url':'https://outside.example/'},{'allowed_urls':['http://example.com/one']},{'max_seconds':301},{'selection':'invented'},{'helper':'/evil.app'}):
            request={'selection':runtime()['selection'],'url':'https://example.com/one','allowed_urls':['https://example.com/one'],'max_seconds':120,**change}
            with self.assertRaises(ValueError):resolve(request,runtime())

    def test_changed_runtime_cannot_launch_frozen_plan(self):
        frozen=managed();different={**runtime(),'helper':'/other.app'}
        with patch.object(computer_target,'runtime',return_value=different):
            with self.assertRaisesRegex(ValueError,'changed'):computer_target.verify_policy(frozen)
        with patch.object(computer_target,'runtime',return_value=runtime()):computer_target.verify_policy(frozen)


from task_relay import production_planning as planning
from orchestrator import worker_capabilities,executors

class PlanningTests(unittest.TestCase):
    setUp=worker_fixture.PlanningTests.setUp
    tearDown=worker_fixture.PlanningTests.tearDown
    request=worker_fixture.PlanningTests.request
    action=worker_fixture.PlanningTests.action
    queue=worker_fixture.PlanningTests.queue
    row=worker_fixture.PlanningTests.row
    response=worker_fixture.PlanningTests.response
    def test_planner_can_create_window_without_selected_target(self):
        backend={'type':'gemini-computer','model':'fixture-model'}
        catalog=[worker_capabilities.entry(b) for b in (backend,{'type':'gemini-agent','model':'fixture-model'})]
        with patch.object(worker_capabilities,'capture',return_value=catalog),patch.object(computer_target,'runtime',return_value=runtime()):self.queue()
        response=self.response()
        for task in response['plan']['tasks']:
            task.pop('tools');task['worker']={'requires':['files.text']};task['limits']=executors.GEMINI_LIMITS.copy()
        task=response['plan']['tasks'][0]
        task['computer']={'selection':runtime()['selection'],'url':'https://example.com/one','allowed_urls':['https://example.com/one'],'max_seconds':120}
        task['worker']['requires'].append('computer.use')
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        planned=json.loads(row['plan'])['tasks'][0]
        self.assertEqual(planned['computer']['spec']['target'],native.NEW_WINDOW)
        self.assertEqual(planned['limits']['seconds'],120)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
