"""Existing browser adapter → registered node → exact model inputs. Offline only."""
import copy,json,sqlite3,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import contextmanager
from orchestrator import perplexity_search as op,operation_definition,node_spec
from orchestrator.operation_execution import Context
from orchestrator.runtime_outcomes import UncertainOperation
from task_relay import perplexity_browser as browser,managed_browser
from tests.test_browser_jobs import Driver,URL

class PageDriver(Driver):
    def sources(self,job):
        return dict(sources=[dict(url='https://example.org/plant',title='Plant source',relationship='observed_on_answer_page',verified=False)],observed_links=1,inspected_links=1,truncated=False)

@contextmanager
def page(_):yield object()

class Operation(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.workspace=self.root/'workspace';self.workspace.mkdir();(self.workspace/'.relay').mkdir()
        self.control=self.root/'control'
        self.frozen=dict(workspace=str(self.workspace),assignment_id='one-search',execution=dict(capability='perplexity.search',version=1,parameters={'query':'Plants along the western Colorado River'}),limits={'seconds':600,'output_bytes':2000000})
        self.ctx=Context(self.frozen,self.control,self.workspace,{},[])
        self.driver=PageDriver()
        for p in (patch.object(op,'PATHS',SimpleNamespace(data=self.root/'data')),patch.object(op,'available'),patch.object(managed_browser,'page',page),patch.object(browser,'PerplexityPage',return_value=self.driver)):
            p.start();self.addCleanup(p.stop)
    def test_success_retains_exact_question_answer_links_and_unknown_usage(self):
        result=op.execute(self.ctx)
        self.assertEqual(self.driver.sent,[self.frozen['execution']['parameters']['query']])
        self.assertEqual(result.receipt['outcome'],'completed');self.assertIsNone(result.receipt['usage'])
        sources=json.loads((self.workspace/'outputs/sources.json').read_text())
        self.assertEqual(sources['conversation_url'],URL);self.assertEqual(sources['sources'][0]['url'],'https://example.org/plant')
        self.assertFalse(sources['sources'][0]['verified'])
        self.assertIn(self.driver.state['text'],(self.workspace/'outputs/answer.md').read_text())
        with self.assertRaises(UncertainOperation):op.execute(self.ctx)
        self.assertEqual(len(self.driver.sent),1)
    def test_click_timeout_is_uncertain_and_never_replayed(self):
        self.driver.error=TimeoutError('Click may have reached the site')
        for _ in range(2):
            with self.assertRaises(UncertainOperation):op.execute(self.ctx)
        self.assertEqual(len(self.driver.sent),1)
        observation={};op.inspect(self.control,observation,{})
        self.assertEqual(observation['external_outcome'],'unknown')
        self.assertFalse((self.workspace/'outputs/answer.md').exists())
    def test_login_or_profile_lock_stops_before_submission(self):
        self.driver.ready=False
        with self.assertRaisesRegex(ValueError,'Sign in'):op.execute(self.ctx)
        self.assertEqual(self.driver.sent,[])
        self.assertEqual(json.loads((self.control/'operation.json').read_text())['effect'],'none')
        self.driver.ready=True
        with browser.profile_lock(self.root/'data'):
            with self.assertRaises(BlockingIOError):op.execute(self.ctx)
        self.assertEqual(self.driver.sent,[])
    def test_source_capture_failure_preserves_answer_receipt_without_repeat(self):
        self.driver.sources=lambda _:(_ for _ in ()).throw(ValueError('Page changed'))
        result=op.execute(self.ctx)
        self.assertEqual(result.receipt['outcome'],'completed')
        sources=json.loads((self.workspace/'outputs/sources.json').read_text())
        self.assertEqual(sources['sources'],[])
        self.assertIsNone(sources['observed_links'])
        self.assertEqual(sources['source_collection'],dict(status='unavailable',error='Page changed',error_type='ValueError'))
        answer=(self.workspace/'outputs/answer.md').read_text()
        self.assertIn('Source-link collection failed',answer)
        self.assertIn(self.driver.state['text'],answer)
        self.assertIn('No search was resubmitted',answer)
        self.assertEqual(json.loads((self.control/'browser-sources.json').read_text())['source_collection'],sources['source_collection'])
        self.assertEqual(json.loads((self.control/'browser-result.json').read_text())['status'],'completed')
        with self.assertRaises(UncertainOperation):op.execute(self.ctx)
        self.assertEqual(len(self.driver.sent),1)

    def test_output_limit_failure_is_not_hidden_by_optional_source_capture(self):
        self.driver.sources=lambda _:(_ for _ in ()).throw(TimeoutError('Source read timed out'))
        self.frozen['limits']['output_bytes']=1
        with self.assertRaisesRegex(ValueError,'exceed'):op.execute(self.ctx)
        self.assertFalse((self.workspace/'outputs/answer.md').exists())
        self.assertEqual(json.loads((self.control/'browser-result.json').read_text())['status'],'completed')
        self.assertEqual(json.loads((self.control/'browser-sources.json').read_text())['source_collection']['error_type'],'TimeoutError')
        with self.assertRaises(UncertainOperation):op.execute(self.ctx)
        self.assertEqual(len(self.driver.sent),1)

class Interfaces(unittest.TestCase):
    def test_named_ports_setup_and_saved_graph(self):
        definition=operation_definition.definition('perplexity.search')
        self.assertEqual(set(definition['inputs']['properties']),{'query'})
        self.assertEqual(set(definition['outputs']),{'answer','sources'})
        node=dict(schema_version=3,id='research',objective='Research plants',operation='perplexity.search',inputs={'query':{'value':'Western Colorado River plants'}})
        saved=node_spec.capture(node);self.assertEqual(node_spec.check_capture(json.loads(json.dumps(saved))),node)
        node['inputs']['api_key']={'value':'not permitted'}
        with self.assertRaises(ValueError):node_spec.validate(node)
    def test_setup_is_configuration_only_and_does_not_start_browser(self):
        from task_relay import desktop_node_setup as setup
        state=dict(enabled=True,available=True,manual_sign_in=False,error=None)
        with patch.object(managed_browser,'status',return_value=state),patch.object(managed_browser,'page') as launch:
            result=setup.snapshot();launch.assert_not_called()
        self.assertEqual(result['browser']['session'],'not_checked')
        self.assertEqual(result['operations']['perplexity.search']['connection'],'managed_browser')
        self.assertFalse(result['operations']['perplexity.search']['worker'])
    def test_disabled_and_manual_setup_block_admission_without_opening_browser(self):
        for state in (dict(enabled=False,manual_sign_in=False),dict(enabled=True,manual_sign_in=True)):
            with patch.object(op,'setup',return_value=dict(**state,available=True,error=None)),patch.object(managed_browser,'page') as launch:
                with self.assertRaises(ValueError):op.available({}, {})
                launch.assert_not_called()

class Capture(unittest.TestCase):
    def test_only_literal_external_links_and_changed_page_rejection(self):
        class Link:
            def __init__(self,url):self.url=url
            def get_attribute(self,_):return self.url
            def inner_text(self,**_):return 'Observed title'
        class Anchors:
            def count(self):return 5
            def nth(self,i):return Link(['https://example.org/plant','https://example.org/plant','javascript:bad','/settings','https://user:secret@example.org'][i])
        class Main:
            def locator(self,_):return Anchors()
        driver=browser.PerplexityPage(SimpleNamespace(get_by_role=lambda _:Main()))
        snap=dict(url=URL,text='Question and answer',ready=True,queries=1,answers=1)
        driver.snapshot=lambda:copy.deepcopy(snap)
        result=driver.sources(dict(url=URL,result=snap['text']))
        self.assertEqual([s['url'] for s in result['sources']],['https://example.org/plant'])
        self.assertFalse(result['sources'][0]['verified'])
        with self.assertRaisesRegex(ValueError,'changed'):driver.sources(dict(url=URL,result='Different answer'))
        snapshots=iter([copy.deepcopy(snap),dict(snap,text=snap['text']+' Changed suggestion')])
        driver.snapshot=lambda:next(snapshots)
        with self.assertRaisesRegex(ValueError,'changed during'):driver.sources(dict(url=URL,result=snap['text']))

class Composed(unittest.TestCase):
    def test_canvas_run_passes_both_exact_outputs_to_model_without_paid_or_messenger_dispatch(self):
        self.check_composed(False)

    def test_source_failure_still_delivers_answer_and_disclosure_to_next_node(self):
        self.check_composed(True)

    def check_composed(self,source_failure):
        from tests.test_same_canvas_rerun import SameCanvas
        from tests.test_mixed_execution import LocalRegistered,Client
        from orchestrator.adapters import ExecutionFactory
        from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts
        f=SameCanvas();f.setUp();self.addCleanup(f.doCleanups)
        class OfflineFactory(ExecutionFactory):
            def available(self,backend):return None
            def create(self,control,workspace,frozen,backend):
                return (self.registered if frozen.get('execution') else self.agents).create(control,workspace,frozen,backend)
        ops=LocalRegistered(Client());f.rt.factory=OfflineFactory(f.factory,ops)
        model=copy.deepcopy(f.saved['workflow']['tasks'][0]);model['id']='plant_list'
        model['inputs']={name:dict(task='research',output=name) for name in ('answer','sources')}
        model['input_definitions']={name:dict(type='artifact',label=name,required=True,media_type=media) for name,media in [('answer','text/markdown'),('sources','application/json')]}
        research=dict(schema_version=3,id='research',objective='Research plants',operation='perplexity.search',inputs={'query':{'value':'Plants along the western Colorado River'}})
        graph=dict(schema_version=1,kind='workflow',inputs={},tasks=[research,model])
        saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Perplexity test',workflow=graph))
        request=dict(id=saved['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
        driver=PageDriver()
        if source_failure:driver.sources=lambda _:(_ for _ in ()).throw(ValueError('Perplexity answer changed during source capture'))
        with patch.object(op,'available'),patch.object(op,'PATHS',f.paths),patch.object(managed_browser,'page',page),patch.object(browser,'PerplexityPage',return_value=driver):
            checked=runs.preview(request);self.assertEqual(checked['paid_nodes'],[])
            result=runs.start(dict(**request,fingerprint=checked['fingerprint'],allow_paid=False));run=result['run']
            for _ in range(5):f.rt.tick(run)
        self.assertEqual(f.rt.task(run,'research')['status'],'completed')
        aid=f.rt.task(run,'plant_list')['latest'];self.assertIsNotNone(aid)
        frozen=f.factory.sessions[aid]['frozen']
        self.assertEqual({i['media_type'] for i in frozen['inputs']},{'text/markdown','application/json'})
        for i in frozen['inputs']:
            original=f.rt.output(run,'research','outputs/'+('answer.md' if i['media_type']=='text/markdown' else 'sources.json'))
            self.assertEqual(i['sha256'],original['sha256'])
            if source_failure:
                content=Path(original['blob']).read_text()
                if i['media_type']=='text/markdown':self.assertIn('Source-link collection failed',content)
                else:self.assertEqual(json.loads(content)['source_collection']['status'],'unavailable')
        if source_failure:
            self.assertEqual(f.rt.task(run,'research')['status'],'completed')
            self.assertEqual(len(driver.sent),1)
        f.factory.finish(aid);f.rt.tick(run)
        self.assertEqual(f.rt.status(run)['status'],'completed')
        self.assertEqual(len(driver.sent),1);self.assertEqual(len(ops.calls),1)
        from orchestrator.execution import ADAPTERS
        self.assertEqual(ADAPTERS['perplexity.search'].max_attempts,1)
