"""Bounded native outcomes and inspection compilation; no browser/provider calls."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from task_relay import computer_contract as contract
from task_relay.host_computer import NativeSessionError
from tests.test_native_source_browser import Tests as NativeBase,Helper,URL
from tests import test_owner_compilation as fixture,test_owner_intents as intents
from orchestrator import execution,step_runner
from orchestrator.runtime import Runtime
from orchestrator.operation_adapters import Adapter,object_schema
from orchestrator.owner_compilation import label

class Native(NativeBase):
    # The base fixtures are reused, but inherited tests are qualified separately.
    def test_same_origin_redirect_preserves_requested_and_observed_url(self):
        helper=Helper(self.root);original=helper.call
        def reply(request):
            value=original(request);value['observation']['url']=URL+'/canonical';return value
        with patch.object(helper,'call',side_effect=reply):value=self.read(helper)
        self.assertEqual(value['requested_url'],URL);self.assertEqual(value['url'],URL+'/canonical')
        self.assertEqual(helper.calls[1]['observation_request']['expected_url'],URL+'/canonical')
        self.assertEqual(self.read(),value) # restart is read-only

    def test_confirmed_destination_rejection_is_saved_without_replay(self):
        helper=Helper(self.root)
        def reject(request):
            helper.calls.append(request)
            from tests.test_computer_use import TARGET
            raise NativeSessionError('unexpected_navigation_destination',dict(protocol=contract.PROTOCOL,ok=False,error='unexpected_navigation_destination',navigation_failure=dict(version=1,terminal=True,operation='launch',requested_url=URL,observed_url='https://outside.example/challenge',target=TARGET,action_executed=True)))
        with patch.object(helper,'call',side_effect=reject):
            with self.assertRaisesRegex(ValueError,'confirmed failure'):self.read(helper)
        state=json.loads((self.root/'native-receipts.json').read_text())
        self.assertEqual(state['actions'][0]['state'],'failed');self.assertIsNotNone(state['actions'][0]['receipt'])
        with self.assertRaisesRegex(ValueError,'confirmed failure'):self.read(helper)
        self.assertEqual(len(helper.calls),1)
        receipt=json.loads(state['actions'][0]['receipt']);(Path(receipt['folder'])/'rejection.json').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'changed'):self.read(helper)

    def test_policy_rejects_cross_origin_credentials_and_implicit_expansion(self):
        for actual,policy in [('https://else.example/item','same-origin-observed-v1'),('https://user@catalog.example/item','same-origin-observed-v1'),(URL+'/canonical',None),('https://catalog.example:8443/item','same-origin-observed-v1')]:
            with self.subTest(actual=actual),self.assertRaises(ValueError):contract.navigation_url(URL,actual,policy)

    def test_uncorrelated_rejection_stays_uncertain(self):
        helper=Helper(self.root)
        def reject(request):raise NativeSessionError('unexpected_navigation_destination',{'navigation_failure':{'terminal':True}})
        from orchestrator.runtime_outcomes import UncertainOperation
        with patch.object(helper,'call',side_effect=reject),self.assertRaises(UncertainOperation):self.read(helper)
        self.assertFalse((self.root/'render-outcome.json').exists())

def inspect_fixture(ctx):
    from orchestrator.operation_execution import Result
    return Result('Inspected exact synthetic bytes: '+(ctx.workspace/ctx.frozen['inputs'][0]['path']).read_text(),None,{},None)

class Review(unittest.TestCase):
    from tests.test_browser_fallback_lifecycle import retain_evidence as tearDown
    create=fixture.Tests.create;source=fixture.Tests.source;session=fixture.Tests.session;invoke=fixture.Tests.invoke;run_worker=fixture.Tests.run_worker
    def setUp(self):
        fixture.Tests.setUp(self)
        runtime=patch('task_relay.code_runtime.available',return_value={'tools':{}});runtime.start();self.addCleanup(runtime.stop)
        self.grant.update(review_inspection_version=1,execution_review_version=1,review_snapshot_version=1,max_tasks=20,owner_turns=10)
        from orchestrator import worker_capabilities
        self.grant['workers'].append(worker_capabilities.entry(dict(type='gemini-code',model='fixture',runtime='a'*64)))
        self.grant['operations']=['fixture.build','fixture.inspect'];self.grant['deliverables']={'result':'application/x-fixture'}
        self.grant['task_limits'].update(tool_calls=24,provider_requests=24)
        base=copy.deepcopy(execution.REGISTRY['text.bundle'])
        build={**base,'outputs':{'delivery/candidate.txt':'application/x-fixture'},'output_type':None}
        inspect={**base,'input_types':['application/x-fixture'],'outputs':{'delivery/inspection.txt':'text/plain'},'output_type':None,'review_evidence':True}
        adapter=Adapter(object_schema({}),handler='orchestrator.operation_execution:text_bundle',handoffs=dict(version=1,default='declared-context-or-native-file',ports=[]),worker_tool=True)
        for target,values in [(execution.REGISTRY,{'fixture.build':build,'fixture.inspect':inspect}),(execution.ADAPTERS,{'fixture.build':adapter,'fixture.inspect':__import__('dataclasses').replace(adapter,handler='tests.test_navigation_inspection:inspect_fixture')})]:
            p=patch.dict(target,values);p.start();self.addCleanup(p.stop)

    def execute_native(self,name):
        self.rt.tick('job');row=self.rt.task('job',name);state=self.factory.sessions[row['latest']];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        step_runner.execute(state['frozen'],control)
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job')

    def graph(self,inline):
        ref=self.source('Small synthetic opaque document.');self.create(inputs=[ref]);self.rt.tick('job')
        producer=dict(id='build',objective='Preserve fixture',inputs=[dict(artifact=ref['artifact'])])
        if inline:producer['work']=dict(operation='fixture.build',mode='execute',parameters={})
        else:producer.update(operation='fixture.build',parameters={})
        result=self.session().delegate(dict(request_id='first',tasks=[producer,dict(id='judge',objective='Inspect exact candidate',review_of='build')]))
        specs=[self.rt.spec(t) for t in self.rt.db.execute('select * from production_tasks where run=?',('job',))]
        readers=[t for t in specs if t.get('execution',{}).get('capability')=='fixture.inspect'];self.assertEqual(len(readers),1);reader=readers[0]['id']
        if inline:
            with patch('orchestrator.worker_tools.execute_local',side_effect=lambda sub,folder,*a,**kw:step_runner.execute(sub,folder)):
                self.run_worker('build',lambda f:[('work_run',dict(step='build',request_key='one'))])
        else:self.execute_native('build')
        self.assertIsNone(self.rt.task('job','judge')['latest'])
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.execute_native(reader)
        f,_=self.run_worker('judge',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        self.assertTrue(any(i['from_task']==reader for i in f['inputs'] if 'from_task' in i))
        artifact=self.rt.output('job','build','outputs/work-build/candidate.txt' if inline else 'delivery/candidate.txt')
        self.session().delegate(dict(request_id='again',tasks=[dict(id='second-review',objective='Review retained exact candidate',review_of='build',inputs=[dict(artifact=artifact['id'])])]))
        self.run_worker('second-review',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        receipt=self.session().complete(dict(deliverables_json=json.dumps({'result':artifact['id']}),summary='Exact reviewed fixture'))
        self.assertEqual(receipt['deliverables']['result']['artifact'],artifact['id'])
        count=self.rt.db.execute("select count(*) from production_tasks where run='job' and id like 'inspection_%'").fetchone()[0];self.assertEqual(count,1)

    def test_standalone_review_waits_for_inspection_restart_and_reuses(self):self.graph(False)
    def test_inline_review_waits_for_inspection_restart_and_reuses(self):self.graph(True)

    def test_missing_reader_stops_before_any_worker_dispatch(self):
        self.grant['operations']=['fixture.build']
        ref=self.source();self.create(inputs=[ref]);self.rt.tick('job');before=len(self.factory.calls)
        from orchestrator.runtime_outcomes import Hold
        with self.assertRaises(Hold):self.session().delegate(dict(request_id='missing',tasks=[intents.native('build','fixture.build',[dict(artifact=ref['artifact'])]),dict(id='judge',objective='Inspect',review_of='build')]))
        self.assertEqual(len(self.factory.calls),before)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)

    def test_required_inspection_counts_against_existing_capacity(self):
        self.grant['max_tasks']=2
        ref=self.source();self.create(inputs=[ref]);self.rt.tick('job')
        with self.assertRaisesRegex(ValueError,'capacity|slots'):
            self.session().delegate(dict(request_id='capacity',tasks=[intents.native('build','fixture.build',[dict(artifact=ref['artifact'])]),dict(id='judge',objective='Inspect',review_of='build')]))
        self.assertEqual(len(self.rt.status('job')['tasks']),1)

    def test_registered_native_formats_choose_structured_inspection(self):
        from orchestrator.review_inspection import bind
        for media,cap in [('application/x-blender','blender.inspect'),('application/vnd.rhino','rhino.inspect')]:
            with self.subTest(media=media):
                ref=self.source('Opaque synthetic fixture',cap+'.txt',media)
                tasks=[dict(id='judge',review_of='candidate',instruction='Review',inputs=[ref],dependencies=[],outputs=[])]
                grant=dict(review_inspection_version=1,operations=['blender.inspect','rhino.inspect','rhino.render'])
                rows=bind(tasks,grant,self.rt,'job')
                self.assertEqual(rows[0]['operation'],cap)
                self.assertIn(rows[0]['inspection'],tasks[0]['dependencies'])
