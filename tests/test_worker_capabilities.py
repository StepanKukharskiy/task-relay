"""Controlled worker composition, provider isolation and durable dispatch tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import contracts, executors, worker_capabilities as workers
from orchestrator.runtime import Runtime
from task_relay import production_activity, pipelines
from tests.test_orchestrator import FakeFactory, pair, task
from tests import test_production_planning as fixtures
from task_relay import production_planning as planning

CODEX = pair()['backend']
GEMINI = {'type':'gemini-agent', 'model':'test-gemini'}
BROWSER = {'type':'openai-browser', 'model':'test-browser'}
CATALOG = [workers.entry(b) for b in (CODEX,GEMINI,BROWSER)]


def compose(t, requires=None, executor=None):
    t['worker']={'requires':requires or ['files.text']}
    if executor:t['worker']['executor']=executor
    workers.resolve(t,CATALOG,CODEX)
    return t


class CompositionTests(unittest.TestCase):
    def test_arbitrary_roles_and_registered_requirements(self):
        for role in ('Climate researcher','Invoice analyst','Card adaptation author'):
            t=task();t['role']=role
            compose(t,executor='gemini-agent')
            self.assertEqual(t['role'],role)
            self.assertEqual(t['worker']['backend'],GEMINI)
            self.assertEqual(t['tools'],['files'])
        self.assertEqual(compose(task(),['code.execute'])['worker']['backend'],CODEX)

    def test_missing_capability_never_fabricates_a_worker(self):
        for requires in (['media.compose'],['install.plugin'],[],['files.text','files.text']):
            with self.subTest(requires=requires), self.assertRaises(ValueError):compose(task(),requires or ['invalid'])
        with self.assertRaisesRegex(ValueError,'No eligible'):
            compose(task(),['code.execute'],executor='gemini-agent')
        with self.assertRaisesRegex(ValueError,'outside the frozen'):
            compose(task(),executor='new-provider')

    def test_binary_inputs_and_outputs_require_file_code_adapter(self):
        for field in ('inputs','outputs'):
            t=task();t[field]=[{'path':'model.3dm','purpose':'Exact model'}]
            with self.assertRaisesRegex(ValueError,'No eligible'):compose(t,executor='gemini-agent')
            self.assertEqual(compose(t)['worker']['backend'],CODEX)

    def test_browser_is_never_selected_as_a_text_fallback(self):
        t=task();t['worker']={'requires':['files.text']}
        with self.assertRaisesRegex(ValueError,'No eligible'):
            workers.resolve(t,[workers.entry(BROWSER)],BROWSER)
        with self.assertRaisesRegex(ValueError,'browser contract'):
            compose(task(),['browser.use'])

    def test_browser_binding_retains_exact_scope(self):
        scope=dict(profile='fixture',origins=['https://example.com'],interaction_scope='',
                   max_tabs=1,max_actions=2,uploads=[],downloads=[])
        t=task(browser=copy.deepcopy(scope),limits=executors.GEMINI_LIMITS.copy(),max_attempts=1)
        compose(t,['files.text','browser.use'])
        checked=contracts.assignment(t)
        self.assertEqual(checked['worker']['backend'],BROWSER)
        self.assertEqual(checked['browser'],scope)
        self.assertEqual(checked['max_attempts'],1)

    def test_frozen_validator_requires_code_capability(self):
        t=task(inputs=[{'path':'operation-support/rhino.run_python/validate.py','purpose':'Execute local checks'}])
        t['worker']={'requires':['files.text']}
        workers.resolve(t,CATALOG,GEMINI)
        self.assertEqual(t['worker']['backend'],CODEX)
        t.pop('tools')
        with self.assertRaisesRegex(ValueError,'No eligible'):compose(t,executor='gemini-agent')

    def test_binding_cannot_inject_backend_or_change_tools(self):
        t=task();t['worker']={'requires':['files.text'],'backend':GEMINI}
        with self.assertRaisesRegex(ValueError,'injection'):workers.resolve(t,CATALOG,CODEX)
        t=task(tools=['files','shell'])
        with self.assertRaisesRegex(ValueError,'conflict'):compose(t,executor='gemini-agent')
        t=compose(task(),executor='gemini-agent');t['worker']['backend']=CODEX
        with self.assertRaisesRegex(ValueError,'match'):workers.validate(t)

    def test_per_worker_limits_and_registered_operations_remain_enforced(self):
        p=pair(max_attempts=1)
        compose(p['tasks'][0],executor='gemini-agent')
        with self.assertRaisesRegex(ValueError,'bounded executor'):contracts.plan(p)
        p['tasks'][0]['limits']=executors.GEMINI_LIMITS.copy()
        self.assertEqual(contracts.plan(p)['tasks'][0]['worker']['backend'],GEMINI)
        p['tasks'][0]['execution']={'capability':'invented'}
        with self.assertRaisesRegex(ValueError,'Registered operations'):workers.validate(p['tasks'][0])

    def test_queued_activity_uses_task_model(self):
        t=compose(task(),executor='gemini-agent')
        activity=production_activity.snapshot(Path('/unused'),None,t,CODEX)
        self.assertEqual(activity['executor'],'gemini-agent')
        self.assertEqual(activity['model'],'test-gemini')
        self.assertEqual(activity['usage']['tokens'],{})

    def test_capture_locks_explicit_provider_without_catalog_discovery(self):
        with patch.object(executors,'catalog') as catalog:
            self.assertEqual(workers.capture(None,GEMINI,locked=True),[workers.entry(GEMINI)])
        catalog.assert_not_called()

    def test_restart_and_disconnect_keep_approved_worker_and_exact_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            factory=FakeFactory();rt=Runtime(Path(directory),factory)
            p=pair(max_attempts=1)
            compose(p['tasks'][0],executor='gemini-agent')
            p['tasks'][0]['limits']=executors.GEMINI_LIMITS.copy()
            compose(p['tasks'][1],['code.execute'])
            rt.create(p);rt.tick('demo')
            first=rt.task('demo','produce')['latest'];factory.finish(first)
            rt.db.close();rt=Runtime(Path(directory),factory)
            rt.tick('demo')
            review=rt.task('demo','review')['latest']
            self.assertEqual(factory.sessions[first]['frozen']['backend'],GEMINI)
            self.assertEqual(factory.sessions[review]['frozen']['backend'],CODEX)
            self.assertEqual(factory.sessions[review]['frozen']['inputs'][0]['artifact'],rt.output('demo','produce','output.txt')['id'])
            self.assertEqual(factory.calls.count(first),1)
            rt.db.close()
        with tempfile.TemporaryDirectory() as directory:
            factory=FakeFactory();factory.available=lambda backend: (_ for _ in ()).throw(ValueError('Disconnected '+backend['type']))
            rt=Runtime(Path(directory),factory);rt.create(p);rt.tick('demo');rt.tick('demo')
            self.assertEqual(rt.task('demo','produce')['status'],'blocked')
            self.assertEqual(factory.calls,[])
            self.assertEqual(rt.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
            rt.db.close()


class PlanningTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    click=fixtures.Tests.click
    start=fixtures.Tests.start

    def dynamic(self):
        r=self.response()
        for t in r['plan']['tasks']:
            t.pop('tools');t['worker']={'requires':['files.text'],'executor':'gemini-agent'}
            t['limits']=executors.GEMINI_LIMITS.copy()
        return r

    def test_plan_freezes_catalog_and_shows_models_before_approval(self):
        with patch.object(workers,'capture',return_value=copy.deepcopy(CATALOG)):
            self.queue()
        planning.Worker(self.state,lambda *_:(json.dumps(self.dynamic()),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        plan=json.loads(row['plan'])
        self.assertEqual(plan['tasks'][0]['worker']['backend'],GEMINI)
        self.assertIn('test-gemini',planning.preview(row))
        self.assertIn('External transfer',planning.preview(row))
        with patch.object(executors,'available',side_effect=ValueError('Disconnected')):
            self.start(row)
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        with patch.object(executors,'available') as available:
            self.start(row)
            self.assertTrue(all(call.args==(GEMINI,) for call in available.call_args_list))
        self.assertEqual(self.row()['status'],'started')

    def test_python_plan_discloses_runtime_and_blocks_changed_runtime_at_start(self):
        backend={'type':'qwen-code','model':'fixture-qwen','runtime':'a'*64}
        catalog=[workers.entry(CODEX),workers.entry(backend)]
        with patch.object(workers,'capture',return_value=catalog):self.queue()
        response=self.dynamic()
        for task in response['plan']['tasks']:
            task['worker']={'requires':['files.text','code.execute'],'executor':'qwen-code'}
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        frozen=json.loads(row['plan'])['tasks'][0]
        self.assertEqual(frozen['tools'],['files','python'])
        self.assertEqual(frozen['worker']['backend'],backend)
        self.assertIn('Native Python code',planning.preview(row))
        self.assertIn('code logs',planning.preview(row))
        with patch.object(executors,'available',side_effect=ValueError('Native runtime changed')):self.start(row)
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_legacy_catalog_cannot_gain_dynamic_permissions(self):
        self.queue();row=dict(self.row());options=json.loads(row['options']);options.pop('worker_catalog',None)
        row['options']=json.dumps(options)
        with self.assertRaisesRegex(ValueError,'no dynamic worker catalog'):
            planning.validate_result(json.dumps(self.dynamic()),row)

    def test_clarification_retains_catalog_despite_new_configuration(self):
        with patch.object(workers,'capture',return_value=copy.deepcopy(CATALOG)):
            self.queue()
        planning.Worker(self.state,lambda *_:(json.dumps({'decision':'needs_input','message':'Which file?','plan':None}),{})).tick()
        with patch.object(workers,'capture',side_effect=AssertionError('Must retain old catalog')):
            row=self.queue(ident=2,action=self.action(parent_id='plan-1'),text='Use the supplied file.')
        self.assertEqual(json.loads(row['options'])['worker_catalog'],CATALOG)

    def test_explicit_scope_cannot_expand_through_a_worker_choice(self):
        with patch.object(executors,'catalog',return_value=[dict(id='gemini-agent',available=True,backend=GEMINI)]),patch.object(executors,'available'):
            row=self.queue(action=self.action(executor='gemini-agent'))
        r=self.dynamic();r['plan']['tasks'][0]['worker']={'requires':['code.execute'],'executor':'codex-cli'}
        with self.assertRaisesRegex(ValueError,'outside the frozen'):
            planning.validate_result(json.dumps(r),row)

    def test_pipeline_requires_approval_for_a_different_worker_backend(self):
        p=contracts.plan(pair(max_attempts=1))
        workflow={'id':'fixture','spec':json.dumps({'stages':[{'capabilities':[]}]})}
        step={'position':0}
        self.assertTrue(pipelines.check_plan(self.state,workflow,step,{'plan':json.dumps(p)}))
        p['tasks'][0].pop('tools');compose(p['tasks'][0],executor='gemini-agent')
        p['tasks'][0]['limits']=executors.GEMINI_LIMITS.copy();p['tasks'][0]['limits']['seconds']=600
        self.assertFalse(pipelines.check_plan(self.state,workflow,step,{'plan':json.dumps(p)}))


if __name__=='__main__':unittest.main()
