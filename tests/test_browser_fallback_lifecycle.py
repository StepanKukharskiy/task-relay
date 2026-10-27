"""Offline owner handoffs using real compiler, scheduler, collectors and journals.

Only provider decisions and host observations are scripted. No browser or API.
"""
import json,os,shutil,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from orchestrator import step_runner,contracts as c
from orchestrator.runtime import Runtime
from orchestrator.owner_compilation import label
from orchestrator.runtime_outcomes import UncertainOperation
from task_relay import source_native_browser as host
from tests import test_owner_intents as owner
from tests.test_native_source_browser import Helper,binding,pack,URL


def retain_evidence(test):
    """Opt-in offline qualification export; ordinary unit tests stay temporary."""
    destination=os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE')
    if destination:
        if hasattr(test,'rt'):test.rt.close()
        shutil.copytree(test.root,Path(destination)/test.id())


class Tests(unittest.TestCase):
    create=owner.Tests.create
    source=owner.Tests.source
    invoke=owner.Tests.invoke
    session=owner.Tests.session
    run_worker=owner.Tests.run_worker
    tearDown=retain_evidence

    def setUp(self):
        owner.Tests.setUp(self);self.grant.pop('delegation_version')
        self.grant['operations']=['web.sources.rendered','web.sources.native']
        self.grant['owner_turns']=10
        self.calls=[]
        for target,value in [('task_relay.orchestrator_web.public_addresses',['8.8.8.8']),
                             ('task_relay.source_native_browser.discover',binding()),
                             ('task_relay.source_native_browser.verified',None)]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)

    def execute_operation(self,ident,renderer,*,native=False):
        self.rt.tick('job');state=self.factory.sessions[self.rt.task('job',ident)['latest']]
        control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        with patch('task_relay.source_native_browser.render' if native else 'task_relay.source_browser.render',side_effect=renderer),patch('task_relay.source_browser.read_http',side_effect=renderer):
            result=step_runner.execute(state['frozen'],control)
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');return result,control

    def begin(self):
        source=pack();source['entries'].append(dict(query='other valid source',target_ids=['B'],pages=[],retrievals=[dict(url=URL+'/valid',outcome='failed')]))
        ref=self.source(json.dumps(source),'sources.json','application/json')
        self.create(inputs=[ref]);self.rt.tick('job')
        result,script=self.invoke([('job_delegate',dict(request_id='isolated',tasks=[owner.native('isolated','web.sources.rendered',[dict(artifact=ref['artifact'])],dict(domains=['catalog.example'],max_pages=2))]))])
        self.assertEqual(result['outcome'],'yielded');self.assertEqual(len(script.requests),1)
        def isolated(url,*_):
            self.calls.append(('isolated',url))
            return dict(url=url,text='Existing useful evidence' if url.endswith('/valid') else 'Access Denied',sha256='a'*64,
                        content_type='text/html',capture_method='isolated-rendered-dom',
                        retrieval_status='captured' if url.endswith('/valid') else 'blocked',retrieval_reason='HTTP 403')
        self.execute_operation('isolated',isolated)
        artifact=self.rt.output('job','isolated','delivery/source-pack.json')
        return artifact,json.loads(Path(artifact['blob']).read_text())

    def native_intent(self,artifact):
        return owner.native('native','web.sources.native',[dict(artifact=artifact['id'])],
                            dict(domains=['catalog.example'],max_pages=1,browser=host.TRANSPORT,max_observations=2))

    def test_owner_fallback_retains_valid_evidence_restart_and_exact_final_review(self):
        artifact,prior=self.begin();original=Path(artifact['blob']).read_bytes()
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        result,script=self.invoke([('job_catalog',dict(operations=['web.sources.native'])),
            ('job_delegate',dict(request_id='native-fallback',tasks=[self.native_intent(artifact),
                owner.worker('report',[dict(task='native',output='source-pack')])]))])
        self.assertEqual(result['outcome'],'yielded');self.assertEqual(len(script.requests),2)
        real=host.render
        def native(url,domains,root,**kwargs):
            self.calls.append(('native',url))
            return real(url,domains,root,**kwargs,helper=Helper(root),lease_context=nullcontext,wait=lambda _:None)
        _,control=self.execute_operation('native',native,native=True)
        combined=self.rt.output('job','native','delivery/source-pack.json')
        doc=json.loads(Path(combined['blob']).read_text())
        self.assertEqual(doc['entries'][:len(prior['entries'])],prior['entries'])
        self.assertEqual(Path(artifact['blob']).read_bytes(),original)
        self.assertEqual(self.calls,[('isolated',URL),('isolated',URL+'/valid'),('native',URL)])
        self.assertEqual(len(doc['rendered_fallback']['reads']),3)
        self.assertEqual(json.loads((control/'render-1/native-receipts.json').read_text())['actions'][-1]['state'],'completed')
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        frozen,_=self.run_worker('report',lambda f:[('file_read',dict(path=f['inputs'][0]['path'],offset=0,limit=10000)),
            ('file_write',dict(path=f['outputs'][0]['path'],text='The failed read and earlier successful evidence remain available. Native observations supply the missing dimensions.'))])
        self.assertEqual(frozen['inputs'][0]['sha256'],combined['sha256'])
        judge,_=self.run_worker(label('report','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=10000)) for i in f['inputs']]+
            [('file_write',dict(path=f['outputs'][0]['path'],text='Reviewed exact report against retained original and native evidence.'))],decision='accept')
        self.assertTrue(any(i['sha256']==combined['sha256'] for i in judge['inputs']))
        report=self.rt.output('job','report','outputs/result.txt')
        self.invoke([('job_complete',dict(deliverables_json=c.encoded(dict(report=report['id'])),summary='Reviewed synthetic fallback report'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed')
        self.assertEqual(self.rt.task('job','native')['attempts'],1)

    def test_missing_native_grant_cannot_escalate_after_confirmed_denial(self):
        self.grant['operations']=['web.sources.rendered']
        artifact,_=self.begin();s=self.session()
        with self.assertRaisesRegex(ValueError,'outside this job grant'):
            s.delegate(dict(request_id='ungranted',tasks=[self.native_intent(artifact)]))
        self.assertEqual([t['id'] for t in self.rt.status('job')['tasks']],['owner','isolated'])
        self.assertFalse(any(kind=='native' for kind,_ in self.calls))

    def test_uncertain_first_read_has_no_source_output_or_downstream_dispatch(self):
        ref=self.source(json.dumps(pack()),'sources.json','application/json')
        self.create(inputs=[ref]);self.rt.tick('job')
        s=self.session();s.delegate(dict(request_id='chain',tasks=[
            owner.native('isolated','web.sources.rendered',[dict(artifact=ref['artifact'])],dict(domains=[],max_pages=1)),
            owner.native('native','web.sources.native',[dict(task='isolated',output='source-pack')],dict(domains=[],max_pages=1,browser=host.TRANSPORT,max_observations=2))]))
        with self.assertRaises(UncertainOperation):self.execute_operation('isolated',lambda *_:(_ for _ in ()).throw(UncertainOperation('lost response')))
        state=self.factory.sessions[self.rt.task('job','isolated')['latest']]
        state['status']=dict(status='uncertain',external_outcome='unknown',pending_requests=['render-1'])
        self.rt.close();self.rt=Runtime(self.root,self.factory);self.rt.tick('job')
        self.assertIsNone(self.rt.task('job','native')['latest'])
        self.assertEqual(self.rt.task('job','isolated')['attempts'],1)
        self.assertFalse(any(x.get('execution',{}).get('capability')=='web.sources.native' for x in [s['frozen'] for s in self.factory.sessions.values()]))

    def test_registered_cancel_is_confirmed_without_output_or_browser(self):
        artifact,_=self.begin();self.session().delegate(dict(request_id='native',tasks=[self.native_intent(artifact)]))
        self.rt.tick('job');state=self.factory.sessions[self.rt.task('job','native')['latest']]
        control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        (control/'cancel.json').write_text('{}')
        with patch.object(host,'render') as dispatch:
            receipt=step_runner.execute(state['frozen'],control)
            dispatch.assert_not_called()
        self.assertEqual((receipt['outcome'],receipt['effect']),('failed','confirmed'))
        self.assertFalse((Path(state['frozen']['workspace'])/'delivery/source-pack.json').exists())
        from orchestrator.operation_lifecycle import terminal
        self.assertEqual(terminal(state['frozen'],control)['outcome'],'failed')

    def test_native_capacity_shortfall_is_rejected_atomically(self):
        self.grant['task_limits']['seconds']=160
        artifact,_=self.begin();s=self.session();before=len(self.factory.calls)
        intent=self.native_intent(artifact);intent['parameters']['max_observations']=6
        with self.assertRaisesRegex(ValueError,'budget|seconds|observation'):
            s.delegate(dict(request_id='insufficient',tasks=[intent]))
        self.assertEqual([t['id'] for t in self.rt.status('job')['tasks']],['owner','isolated'])
        self.assertEqual(len(self.factory.calls),before)


class StopTests(unittest.TestCase):
    from tests.test_native_source_browser import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=retain_evidence

    def test_cancelled_collection_never_starts_a_read(self):
        from orchestrator.source_fallback import collect
        (self.root/'cancel.json').write_text('{}')
        calls=[]
        with self.assertRaisesRegex(ValueError,'cancelled'):
            collect(pack(),[],1,self.root,lambda *a:calls.append(a))
        self.assertEqual(calls,[])

    def test_parent_cancellation_after_receipt_stops_native_and_remaining_pages(self):
        from orchestrator.source_fallback import collect
        source=pack();source['entries'][0]['retrievals'].append(dict(url=URL+'/second',outcome='failed'))
        calls=[]
        def render(url,domains,root):
            helper=Helper(root);original=helper.call
            def call(request):
                calls.append(request);result=original(request)
                (self.root/'cancel.json').write_text('{}')
                return result
            helper.call=call
            return host.render(url,domains,root,binding=binding(),max_observations=4,
                helper=helper,lease_context=nullcontext,wait=lambda _:None,cancel_control=self.root)
        with self.assertRaisesRegex(ValueError,'cancelled'):collect(source,[],2,self.root,render,read_policy=binding())
        self.assertEqual(len(calls),1)
        record=json.loads((self.root/'render-1/native-receipts.json').read_text())
        self.assertEqual(record['assignment']['state'],'cancelled')
        self.assertEqual(record['actions'][0]['state'],'completed')
        self.assertTrue((self.root/'render-1/native-call-1.response.json').exists())
        self.assertFalse((self.root/'render-2').exists())
        (self.root/'cancel.json').unlink()
        with self.assertRaisesRegex(ValueError,'cancelled'):collect(source,[],2,self.root,render,read_policy=binding())
        self.assertEqual(len(calls),1)

    def test_foreground_loss_retains_raw_failure_and_never_replays(self):
        from task_relay.host_computer import NativeSessionError
        helper=Helper(self.root);original=helper.call
        def call(request):
            if helper.calls:raise NativeSessionError('foreground_lost')
            return original(request)
        helper.call=call
        for _ in range(2):
            with self.assertRaises(UncertainOperation):
                host.render(URL,[],self.root,binding=binding(),max_observations=4,
                    helper=helper,lease_context=nullcontext,wait=lambda _:None)
        self.assertEqual(len(helper.calls),1)
        self.assertIn('foreground_lost',(self.root/'native-call-2.error.json').read_text())
        self.assertFalse((self.root/'render-outcome.json').exists())

    def test_cancel_never_masks_uncertain_read(self):
        from orchestrator.source_fallback import collect
        def lost(*_):
            (self.root/'cancel.json').write_text('{}')
            raise UncertainOperation('Unacknowledged native action')
        with self.assertRaises(UncertainOperation):collect(pack(),[],1,self.root,lost)
        with self.assertRaises(UncertainOperation):collect(pack(),[],1,self.root,lambda *_:self.fail('No replay'))
        self.assertFalse((self.root/'fallback-stop.json').exists())

    def test_owner_takeover_stops_entire_collection_not_only_current_page(self):
        from orchestrator.source_fallback import collect
        for kind in ('takeover','pause','stop'):
            with self.subTest(kind=kind):
                control=self.root/kind;control.mkdir();calls=[]
                source=pack();source['entries'][0]['retrievals'].append(dict(url=URL+'/second',outcome='failed'))
                def render(url,domains,root):
                    helper=Helper(root);original=helper.call
                    def call(request):
                        calls.append(request);result=original(request)
                        (root/'computer-owner-event.json').write_text(json.dumps(dict(kind=kind)))
                        return result
                    helper.call=call
                    return host.render(url,domains,root,binding=binding(),max_observations=2,
                        helper=helper,lease_context=nullcontext,wait=lambda _:None,cancel_control=control)
                with self.assertRaisesRegex(ValueError,'cancelled'):collect(source,[],2,control,render,read_policy=binding())
                self.assertEqual(len(calls),1)
                self.assertFalse((control/'render-2').exists())
                with self.assertRaisesRegex(ValueError,'cancelled'):collect(source,[],2,control,render,read_policy=binding())
                self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
