"""Failed children, idle waits and typed native handoffs; no paid requests."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import contracts as c,execution,executors,job_owner
from tests import test_job_owner_loop as fixture
from tests.test_operation_adapters import assignment

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    create=fixture.Tests.create
    invoke=fixture.Tests.invoke
    batch=fixture.Tests.batch
    delegate=fixture.Tests.delegate

    def session(self):
        aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        owner=job_owner.Session(s['frozen'],s['session']['control'],job_owner.files(s['frozen'],s['session']['control']))
        self.addCleanup(owner.rt.close);return owner

    def fail_child(self):
        self.delegate(self.batch());self.rt.tick('job')
        aid=self.rt.task('job','v1')['latest']
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,operation=dict(outcome='failed',reason='Input is not a registered contract'),external_outcome='no_pending_response')
        self.rt.tick('job');return aid

    def test_failed_child_reason_reaches_owner_and_idle_wait_can_correct_same_invocation(self):
        self.create();self.rt.tick('job');failed=self.fail_child()
        owner=self.session();self.assertIn('registered contract',owner.snapshot()['tasks'][0]['failure']['reason'])
        before=self.rt.task('job','owner')['attempts']
        result,script=self.invoke([('job_wait',{}),('job_delegate',dict(request_id='correction',batch_json=c.encoded(self.batch('fixed'))))])
        error=script.requests[1]['contents'][-1]['parts'][0]['functionResponse']['response']['error']
        self.assertIn('No pending child work',error);self.assertEqual(result['outcome'],'yielded')
        self.assertEqual(self.rt.task('job','owner')['attempts'],before)
        self.assertEqual(self.rt.task('job','v1')['latest'],failed)
        self.assertEqual(self.rt.task('job','fixed')['attempts'],0)

    def test_repeated_idle_wait_cannot_buy_another_invocation(self):
        self.create();self.rt.tick('job');self.fail_child();aid=self.rt.task('job','owner')['latest']
        with patch.object(executors,'request_limit',return_value=2):
            with self.assertRaisesRegex(ValueError,'no automatic wake'):
                self.invoke([('job_wait',{}),('job_wait',{})])
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,reason='No pending work',external_outcome='no_pending_response')
        self.rt.tick('job');calls=len(self.factory.calls)
        self.rt.close();from orchestrator.runtime import Runtime
        self.rt=Runtime(self.root,self.factory)
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(len(self.factory.calls),calls);self.assertEqual(self.rt.status('job')['status'],'blocked')

    def test_waitable_states_exclude_terminal_and_unrunnable_dependents(self):
        self.create();self.rt.tick('job');self.delegate(self.batch());self.rt.tick('job')
        owner=self.session();self.assertEqual(owner.call('job_wait',{}),{'waiting':True})
        with self.rt.transaction():self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE id='v1'")
        with self.assertRaisesRegex(ValueError,'No pending child work'):owner.call('job_wait',{})
        for state in ('launching','running','cancelling','uncertain','awaiting_user'):
            with self.rt.transaction():self.rt.db.execute('UPDATE production_tasks SET status=? WHERE id=?',(state,'v1'))
            self.assertEqual(owner.call('job_wait',{}),{'waiting':True})

    def photo_task(self,inputs):
        return assignment('images.products',dict(inventory_path='inventory.json',catalog_path='catalog.json',source_pack_path='sources.json',count_policy='target'),inputs,ident='photos')

    def sources(self):
        refs=[]
        for name in ('inventory','catalog','sources'):
            p=self.root/(name+'.json');p.write_text('{"items":[]}')
            refs.append(dict(artifact=self.rt.register(p,'Untyped fixture'),path=p.name,purpose='Exact source',authority='Data',media_type='application/json'))
        return refs

    def test_wrong_typed_input_rolls_back_entire_owner_batch_before_dispatch(self):
        refs=self.sources();self.grant['operations']=['images.products'];self.create(inputs=refs);self.rt.tick('job')
        owner=self.session();task=self.photo_task(refs);task['outputs'][0]['path']='photos.zip'
        before=len(self.factory.calls)
        with self.assertRaisesRegex(ValueError,'catalog.json.*sealed registered options'):
            owner.delegate(dict(request_id='bad-types',batch_json=c.encoded([self.batch()[0],task])))
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(len(self.factory.calls),before)

    def test_ordinary_scheduler_rejects_wrong_bound_bytes_without_spending_attempt(self):
        from tests.test_mixed_execution import operation
        from tests.test_orchestrator import plan
        refs=self.sources();task=self.photo_task(refs);task.update(limits=dict(seconds=600,tool_calls=1,output_bytes=45000000),max_attempts=1,tools=[]);task['outputs'][0]['path']='photos.zip'
        self.rt.create(plan([task]))
        with patch('orchestrator.execution.available'):
            self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','photos')['status'],'blocked');self.assertEqual(self.rt.task('demo','photos')['attempts'],0)
        self.assertEqual(self.factory.calls,[])

    def test_all_registered_typed_consumers_reject_arbitrary_json_and_future_bytes_defer(self):
        for name in ('images.products','images.catalog','sourcing.slides','collection.slides','sourcing.merge','records.merge'):
            adapter=execution.adapter(name)
            for parameter,roles in adapter.content_ports:
                task=dict(inputs=[dict(path='data.json',media_type='application/json')],execution=dict(parameters={p:('data.json' if not p.endswith('paths') else ['data.json']) for p,_ in adapter.content_ports}))
                with self.subTest(operation=name),self.assertRaisesRegex(ValueError,'sealed registered'):
                    adapter.validate_content(task,lambda _:b'{"items":[]}')
                adapter.validate_content(task,lambda _:None)

    def test_future_output_is_checked_before_consumer_attempt_after_restart(self):
        from tests.test_orchestrator import plan,task as worker
        from orchestrator.runtime import Runtime
        refs=self.sources();producer=worker('author')
        producer['outputs']=[dict(path='catalog.json',purpose='Candidate JSON',media_type='application/json')]
        refs[1]=dict(from_task='author',output='catalog.json',path='catalog.json',purpose='Candidate',authority='Unaccepted',media_type='application/json')
        consumer=self.photo_task(refs);consumer.update(dependencies=['author'],limits=dict(seconds=600,tool_calls=1,output_bytes=45000000),max_attempts=1,tools=[]);consumer['outputs'][0]['path']='photos.zip'
        self.rt.create(plan([producer,consumer]));self.rt.tick('demo');aid=self.rt.task('demo','author')['latest']
        self.factory.finish(aid)
        (Path(self.factory.sessions[aid]['frozen']['workspace'])/'catalog.json').write_text('{"items":[]}')
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        with patch('orchestrator.execution.available'):self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','author')['status'],'completed')
        self.assertEqual(self.rt.task('demo','photos')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','photos')['attempts'],0)
        self.assertEqual(len(self.factory.calls),1)

    def test_valid_sealed_contract_passes_without_conversion_or_semantic_acceptance(self):
        from orchestrator import sourcing_contract as sourcing
        p=dict(inventory_path='inventory.json',source_pack_path='sources.json',max_records=1,summary_path='catalog.md',options_per_item=3,count_policy='target')
        data=sourcing.options_document([dict(item='sample',options=[],gap='No verified options')],p,
            dict(inventory={'sample':{}},source_versions={},observations={}))
        raw=c.encoded(data).encode();task=self.photo_task([dict(path='catalog.json',media_type='application/json')])
        adapter=execution.adapter('images.products');adapter.validate_content(task,lambda _:raw)
        self.assertEqual(raw,c.encoded(data).encode())
        for mutation in ('unsealed','wrong-role','wrong-version'):
            bad=copy.deepcopy(data)
            if mutation=='unsealed':bad['complete']=False
            elif mutation=='wrong-role':bad['contract']['id']='sourcing.review'
            else:bad['contract']['version']=999
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):adapter.validate_content(task,lambda _:c.encoded(bad).encode())
