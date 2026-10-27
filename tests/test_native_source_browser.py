import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import contextmanager,nullcontext
from unittest.mock import patch
from task_relay import source_native_browser as host
from orchestrator.source_fallback import collect
from orchestrator.runtime_outcomes import UncertainOperation
from tests.test_computer_use import Helper as Observation,TARGET

URL='https://catalog.example/item'

class Helper:
    identity=Observation.identity
    def __init__(self,root,fail=None,cleanup=False):self.root,self.fail,self.cleanup=root,fail,cleanup;self.calls=[]
    def require_ready(self):pass
    @contextmanager
    def session(self):
        yield self
        if self.cleanup:raise PermissionError('Synthetic cleanup failure')
    def call(self,request):
        with sqlite3.connect(self.root/'native-state.sqlite') as db:
            assert db.execute("SELECT count(*) FROM relay_computer_actions WHERE state='claimed'").fetchone()[0]==1
        self.calls.append(copy.deepcopy(request))
        if self.fail==len(self.calls):raise TimeoutError('Lost native response')
        result=Observation().call(request['observation_request'])
        result['text']='Observation '+str(len(self.calls))+': synthetic catalog dimensions 89 x 41.5 x 33'
        return dict(protocol=result['protocol'],ok=True,token='new-token-'+str(len(self.calls)),observation=result,
            window_created=request['operation']=='launch',foreground_acquired=request['operation']=='launch',action_executed=True)


def binding():return dict(transport=host.TRANSPORT,policy=host.POLICY,helper='/synthetic/helper.app',identity=Helper.identity)

def pack():return dict(version=1,kind='public_source_candidates',domains=[],entries=[dict(query='fixture',target_ids=['A'],pages=[],retrievals=[dict(url=URL,outcome='failed')])])

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.dns=patch('task_relay.orchestrator_web.public_addresses',return_value=['8.8.8.8']);self.dns.start();self.addCleanup(self.dns.stop)
    def read(self,helper=None,**changes):
        args=dict(binding=binding(),max_observations=4,helper=helper or Helper(self.root),lease_context=nullcontext,wait=lambda _:None)
        args.update(changes);return host.render(URL,['catalog.example'],self.root,**args)
    def test_exact_observations_committed_before_calls_and_restart_without_browser(self):
        helper=Helper(self.root);value=self.read(helper)
        self.assertEqual([c['operation'] for c in helper.calls],['launch','observe','scroll','scroll'])
        self.assertIn('Observation 1:',value['text']);self.assertIn('Observation 4:',value['text'])
        self.assertEqual(self.read(Helper(self.root,fail=1)),value)
        evidence=next((self.root/'evidence').glob('*/*/page.txt'));evidence.write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):self.read(helper)
        self.assertEqual(len(helper.calls),4)
    def test_missing_receipt_remains_uncertain_and_never_reopens(self):
        helper=Helper(self.root,fail=2)
        with self.assertRaises(UncertainOperation):self.read(helper)
        self.assertFalse((self.root/'render-outcome.json').exists())
        with self.assertRaisesRegex(UncertainOperation,'no replay'):self.read(helper)
        self.assertEqual(len(helper.calls),2)
        record=json.loads((self.root/'native-receipts.json').read_text())
        self.assertEqual(record['actions'][-1]['state'],'uncertain')
        self.assertTrue((self.root/'native-call-1.response.json').exists())
    def test_permission_denial_has_no_window_or_read_intent(self):
        helper=Helper(self.root)
        with patch.object(helper,'require_ready',side_effect=ValueError('Permission unavailable')):
            with self.assertRaisesRegex(ValueError,'Permission'):self.read(helper)
        self.assertFalse((self.root/'render-intent.json').exists());self.assertEqual(helper.calls,[])
    def test_cleanup_failure_keeps_confirmed_capture(self):
        value=self.read(Helper(self.root,cleanup=True))
        self.assertEqual(value['retrieval_status'],'captured');self.assertTrue((self.root/'render-cleanup-error.json').exists())
        self.assertEqual(self.read(),value)
    def test_changed_scope_or_budget_cannot_reuse_capture(self):
        self.read()
        with self.assertRaisesRegex(ValueError,'authority changed'):self.read(max_observations=5)
        changed=binding();changed['policy']='different'
        with self.assertRaisesRegex(ValueError,'authority changed'):self.read(binding=changed)
    def test_confirmed_failed_other_transport_can_be_read_only_under_new_explicit_policy(self):
        original=pack()
        failed=lambda *_:dict(url=URL,sha256='0'*64,retrieval_status='blocked',retrieval_reason='denied')
        first,_=collect(original,[],1,self.root/'isolated',failed);prior=json.loads(first)
        raw,_=collect(prior,[],1,self.root/'same',lambda *_:self.fail('No repeated legacy read'))
        self.assertEqual(len(json.loads(raw)['entries']),2)
        renderer=lambda url,domains,root:host.render(url,domains,root,binding=binding(),max_observations=2,helper=Helper(root),lease_context=nullcontext,wait=lambda _:None)
        result,stats=collect(prior,[],1,self.root/'native',renderer,read_policy=binding())
        self.assertEqual(stats['rendered'],1);self.assertEqual(json.loads(result)['entries'][:2],prior['entries'])
        self.assertEqual(collect(prior,[],1,self.root/'native',lambda *_:self.fail('No restart read'),read_policy=binding()),(result,stats))
        with self.assertRaisesRegex(ValueError,'grant changed'):collect(prior,[],1,self.root/'native',renderer,read_policy={'changed':True})
    def test_registry_grants_and_changed_helper_fail_before_dispatch(self):
        from orchestrator import execution
        from orchestrator.operation_bindings import rendered
        from orchestrator.operation_execution import rendered_sources,Context
        from orchestrator.runtime import file_hash
        from task_relay import host_computer
        params=dict(domains=[],max_pages=1,browser=host.TRANSPORT,max_observations=4)
        spec=execution.REGISTRY['web.sources.native'];adapter=execution.adapter('web.sources.native')
        adapter.validate(dict(execution=dict(parameters=params),limits=dict(seconds=180)),spec)
        with self.assertRaises(ValueError):adapter.validate(dict(execution=dict(parameters=params),limits=dict(seconds=90)),spec)
        frozen=dict(runtime_sources={},execution=dict(capability='web.sources.native',parameters=params))
        with patch.object(host,'discover',return_value=binding()):rendered(frozen)
        for name in ('source_fallback.py','web_sources.py','page_identity.py'):
            frozen['runtime_sources'][name]=file_hash(Path(execution.__file__).with_name(name))
        frozen['runtime_sources']['task_relay/source_native_browser.py']='changed'
        with patch.object(host,'render') as dispatch:
            with self.assertRaisesRegex(ValueError,'changed after dispatch'):rendered_sources(Context(frozen,self.root,self.root,spec,[dict(text=json.dumps(pack()))]))
            dispatch.assert_not_called()
        from orchestrator.producer_binding import compatible_native
        self.assertTrue(compatible_native('web.sources.native',['web.sources.rendered']))
        with patch.object(host_computer,'Observer') as observe:
            observe.return_value.identity={'changed':True}
            with self.assertRaisesRegex(ValueError,'changed after binding'):host.verified(binding())
            observe.return_value.require_ready.assert_not_called()
    def test_native_access_denied_text_is_diagnostic(self):
        from task_relay.source_browser import availability
        self.assertEqual(availability('', 'Access Denied\nDetails',None)[0],'blocked')

    def test_registered_graph_preserves_source_and_holds_lost_native_reply(self):
        from orchestrator import execution,step_runner
        from orchestrator.runtime import Runtime
        from orchestrator.adapters import RegisteredFactory
        from orchestrator.operation_lifecycle import resources
        from orchestrator.workers import atomic
        from tests.test_orchestrator import FakeFactory,pair
        real_render=host.render
        for fail in (None,2):
            with self.subTest(failure=fail):
                root=self.root/str(fail);root.mkdir();control=root/'control';control.mkdir()
                helper=Helper(control/'render-1',fail=fail)
                rt=Runtime(root/'runtime',FakeFactory());self.addCleanup(rt.db.close)
                file=root/'source.json';file.write_text(json.dumps(pack()));aid=rt.register(file,'Synthetic exact source')
                graph=pair(max_attempts=1);task=graph['tasks'][0]
                task.update(execution=dict(capability='web.sources.native',version=1,parameters=dict(domains=['catalog.example'],max_pages=1,browser=host.TRANSPORT,max_observations=2)),
                    inputs=[dict(artifact=aid,path='source.json',purpose='Synthetic candidates',authority='Unaccepted',media_type='application/json')],
                    outputs=[dict(path='delivery/source-pack.json',purpose='Native evidence',media_type='application/json')],
                    criteria=copy.deepcopy(execution.REGISTRY['web.sources.native']['criteria']),limits=dict(seconds=150,tool_calls=1,output_bytes=3000000))
                graph['tasks'][1]['inputs'][0].update(output='delivery/source-pack.json',media_type='application/json')
                graph['tasks'][1]['criteria']=copy.deepcopy(task['criteria'])
                self.assertEqual(resources(task),{'computer-safari'})
                def read(url,domains,path,**kwargs):
                    return real_render(url,domains,path,**kwargs,helper=helper,lease_context=nullcontext,wait=lambda _:None)
                with patch.object(host,'discover',return_value=binding()),patch.object(host,'verified',return_value=helper),patch.object(host,'render',side_effect=read):
                    rt.create(graph);rt.tick('demo')
                    frozen=json.loads(rt.db.execute('SELECT frozen FROM production_attempts').fetchone()[0])
                    if fail:
                        with self.assertRaises(UncertainOperation):step_runner.execute(frozen,control)
                        atomic(control/'done.json',dict(token=frozen['assignment_id'],exit_code=1,reason='fixture lost reply',usage=[]))
                        observed=RegisteredFactory().inspect(dict(id=frozen['assignment_id'],control=str(control),execution=frozen['execution']))
                        self.assertEqual(observed['status'],'uncertain');self.assertIn('render-1',observed['pending_requests'])
                    else:
                        result=step_runner.execute(frozen,control);self.assertEqual(result['outcome'],'completed')
                        value=json.loads((Path(frozen['workspace'])/'delivery/source-pack.json').read_text())
                        self.assertEqual(value['entries'][:1],pack()['entries'])
                        self.assertIn('Observation 2:',value['entries'][-1]['pages'][0]['text'])
                    count=len(helper.calls)
                    with self.assertRaisesRegex(ValueError,'Cannot replay'):step_runner.execute(frozen,control)
                    self.assertEqual(len(helper.calls),count)

if __name__=='__main__':unittest.main()
