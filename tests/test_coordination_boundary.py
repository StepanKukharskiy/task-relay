"""Controlled shared-boundary lifecycles; no providers, network or native apps."""
import copy,hashlib,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator import job_owner,sourcing_contract,operation_records,operation_session,evidence_context,artifact_files,record_tool
from orchestrator.runtime import Runtime
from tests import test_owner_parallel_progress as parallel,test_sourcing_records as records
from tests.test_browser_fallback_lifecycle import retain_evidence


class Scheduling(unittest.TestCase):
    tearDown=retain_evidence
    create=parallel.Tests.create
    finish=parallel.Tests.finish
    ref=parallel.Tests.ref
    invoke=parallel.Tests.invoke
    delegate=parallel.Tests.delegate
    batch=parallel.Tests.batch
    def setUp(self):
        parallel.Tests.setUp(self)
        self.grant['coordination_version']=1

    def test_admitted_chain_runs_through_restart_without_owner_poll_then_final_decision(self):
        self.create()
        first=self.batch('first');next_tasks=self.batch('next',[self.ref('first')]);next_tasks[0]['dependencies']=['first']
        self.delegate(first+next_tasks+self.batch('slow'));self.rt.tick('job')
        self.finish('first');self.finish('first_review','accept')
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertIn(self.rt.task('job','next')['status'],('running','launching'))
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.finish('next');self.finish('next_review','accept')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertEqual(self.rt.task('job','slow')['status'],'running')
        self.invoke([('job_wait',{})]);self.rt.tick('job')
        self.finish('slow');self.finish('slow_review','accept')
        artifact=self.rt.output('job','next','report.txt')
        self.invoke([('job_complete',dict(deliverables_json=json.dumps({'report':artifact['id']}),summary='Independent exact review completed'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed')
        self.assertEqual(len(self.factory.calls),len(set(self.factory.calls)))
        self.assertTrue(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='owner_progress_deferred'").fetchone())

    def test_failure_still_requires_decision_and_never_replays(self):
        self.create();chain=self.batch('next',[self.ref('first')]);chain[0]['dependencies']=['first']
        self.delegate(self.batch('first')+chain+self.batch('slow'));self.rt.tick('job')
        aid=self.rt.task('job','first')['latest']
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,external_outcome='no_pending_response',reason='Confirmed failure')
        self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertIsNone(self.rt.task('job','next')['latest'])
        self.assertEqual(self.factory.calls.count(aid),1)

    def test_uncertainty_retains_existing_stop_boundary(self):
        self.create();self.delegate(self.batch('first')+self.batch('slow'));self.rt.tick('job')
        aid=self.rt.task('job','first')['latest']
        self.factory.sessions[aid]['status']=dict(status='uncertain',reason='Unknown effect')
        self.rt.tick('job');self.finish('slow')
        self.assertEqual(self.rt.status('job')['status'],'uncertain')
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertEqual(self.factory.calls.count(aid),1)


class Observations(unittest.TestCase):
    tearDown=retain_evidence
    setUp=records.Tests.setUp
    input=records.Tests.input
    assignment=records.Tests.assignment
    save=records.Tests.save
    option=records.Tests.option
    item=records.Tests.item
    submit=records.Tests.submit
    complete_catalog=records.Tests.complete_catalog

    def test_lookup_survives_completion_and_restart(self):
        baseline=self.complete_catalog();old=(self.root/'delivery/producer.json').read_bytes()
        reopened=operation_records.Store(self.frozen,self.db)
        self.assertEqual(reopened.progress()['remaining'],0)
        ctx=reopened.sourcing_context()
        args=dict(observation='',query='Width 120 cm',offset=0,limit=2)
        result=sourcing_contract.source_find(ctx,args)
        self.assertEqual(result['total'],5);self.assertEqual(result['next_offset'],2)
        for match in result['matches']:
            text=ctx['observations'][match['observation']]['text']
            self.assertEqual(text[match['start']:match['end']],'Width 120 cm')
        listed=sourcing_contract.source_find(ctx,dict(observation='',query='',offset=0,limit=40))
        self.assertEqual(len(listed['matches']),5)
        self.assertEqual((self.root/'delivery/producer.json').read_bytes(),old)
        self.assertFalse('acceptance' in result)

    def test_unicode_repeated_literals_and_invalid_lookup_cannot_mutate_records(self):
        ctx=copy.deepcopy(self.context);ctx['observations']['page-0-0']['text']='é🪑 desk; é🪑 desk'
        result=sourcing_contract.source_find(ctx,dict(observation='page-0-0',query='é🪑',offset=1,limit=1))
        self.assertEqual(result['total'],2);self.assertEqual(result['matches'][0]['start'],9)
        self.assertIsNone(result['next_offset'])
        with self.assertRaisesRegex(ValueError,'Unknown observation'):
            sourcing_contract.source_find(ctx,dict(observation='not-an-id',query='desk',offset=0,limit=1))
        self.assertEqual(self.store.progress()['committed'],0)

    def test_shared_loop_uses_lookup_without_extra_assignment(self):
        from orchestrator.gemini_worker import execute
        from tests.test_operation_session import Script
        from orchestrator.workers import atomic
        from orchestrator import executors
        control=self.root/'control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(records.CONFIG,self.frozen['backend'])))
        script=Script([('source_find',dict(observation='',query='Width 120 cm',offset=0,limit=2)),
            ('operation_submit',dict(request_key='a',revision=0,records=[self.item()])),
            ('operation_submit',dict(request_key='b',revision=1,records=[self.item('item-b',0)])),
            ('finish',dict(report_json=json.dumps(dict(summary='Bound records',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Exact retained evidence')}))))])
        with patch('orchestrator.gemini_worker.emit'):
            result=execute(self.frozen,control,script,lambda:(records.CONFIG,self.frozen['backend']))
        self.assertEqual(result['decision'],'delivered')
        receipt=json.loads(next(control.glob('tool-01-*.json')).read_text())
        self.assertEqual(receipt['result']['total'],5)
        self.assertEqual(len(script.requests),4)

    def test_review_session_keeps_binary_receipts_separate_from_literal_intervals(self):
        from orchestrator import artifact_roles
        catalog=self.complete_catalog()
        f=self.assignment('mixed-review',True);f['id']='mixed-review';f.pop('report_contract')
        f['inputs'].append(self.input('catalog.json',catalog))
        for item in f['inputs']+f['outputs']:item['media_type']='application/json' if item['path'].endswith('.json') else 'text/markdown'
        binary=b'BLENDER\xff\x00exact fixture';path=self.root/'model.blend';path.write_bytes(binary)
        f['inputs'].append(dict(path='model.blend',artifact='model',media_type='application/x-blender',sha256=hashlib.sha256(binary).hexdigest(),purpose='Inherited candidate',authority='No acceptance'))
        # Use the real registered role binder, never a synthetic permissive reader.
        artifact_roles.bind(f,None,[]);self.save(f)
        (self.root/'mixed').mkdir()
        files=artifact_files.files(f,self.root/'mixed')
        session=operation_session.Session(files,self.root/'mixed',None)
        remaining=session.view()['remaining']
        self.assertNotIn('model.blend',{v['path'] for v in remaining})
        self.assertEqual(files.call('artifact_inspect',dict(path='model.blend'))['semantic_acceptance'],False)
        files.observe('inventory.json',0,2,files.read_bytes('inventory.json'));session.received()
        receipt=session.save();checkpoint=json.loads(Path(receipt['path']).read_text())
        fresh=artifact_files.files(f,self.root/'mixed');restored=operation_session.Session(fresh,self.root/'mixed',None)
        restored.restore(checkpoint)
        self.assertEqual(fresh.observed['inventory.json'],[(0,2)])
        checkpoint['observed']['model.blend']=[[0,1]]
        with self.assertRaisesRegex(ValueError,'Binary evidence'):restored.restore(checkpoint)

    def test_lookup_uses_all_native_provider_transports_offline(self):
        from orchestrator.agent_loop import execute
        from orchestrator import executors
        from orchestrator.workers import atomic
        for provider in ('openai','openrouter','qwen'):
            with self.subTest(provider=provider):
                f=self.assignment(provider);f['backend']=dict(type=provider+'-agent',model='fixture-model');self.save(f)
                (self.root/'.relay/result.json').unlink(missing_ok=True)
                control=self.root/provider;control.mkdir();config={'api_key':'fixture-only'}
                atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,f['backend'])))
                steps=iter([('source_find',dict(observation='',query='Width 120 cm',offset=0,limit=2)),
                    ('operation_submit',dict(request_key='a',revision=0,records=[self.item()])),
                    ('operation_submit',dict(request_key='b',revision=1,records=[self.item('item-b',0)])),
                    ('finish',dict(report_json=json.dumps(dict(summary='Bound records',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Exact retained evidence')}))))])
                calls=[]
                def request(endpoint,payload,**kwargs):
                    calls.append(payload)
                    try:name,args=next(steps)
                    except StopIteration:raise AssertionError([json.loads(p.read_text()) for p in control.glob('tool-*.json')])
                    ident=str(len(calls))
                    if name=='finish':args=json.loads(args['report_json'])
                    if provider=='openai':return dict(status='completed',output=[dict(type='function_call',call_id=ident,name=name,arguments=json.dumps(args))])
                    return dict(choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content=None,tool_calls=[dict(id=ident,type='function',function=dict(name=name,arguments=json.dumps(args)))]))])
                result=execute(f,control,SimpleNamespace(request=request),lambda:(config,f['backend']))
                self.assertEqual(result['decision'],'delivered');self.assertEqual(len(calls),4)
                receipt=json.loads(next(control.glob('tool-01-*.json')).read_text())
                self.assertEqual(receipt['result']['total'],5)

    def test_codex_dynamic_tool_gate_corrects_bad_lookup_in_same_assignment(self):
        import sys
        from orchestrator.agent_loop import execute
        from orchestrator import executors
        from orchestrator.codex_transport import Client
        from orchestrator.workers import atomic
        from tests.test_codex_executor import BACKEND,CONFIG
        f=self.assignment('codex');f['backend']=BACKEND.copy();self.save(f)
        control=self.root/'codex-control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        steps=[('source_find',dict(observation='missing',query='desk',offset=0,limit=1)),
            ('source_find',dict(observation='',query='Width 120 cm',offset=0,limit=2)),
            ('operation_submit',dict(request_key='a',revision=0,records=[self.item()])),
            ('operation_submit',dict(request_key='b',revision=1,records=[self.item('item-b',0)])),
            ('finish',dict(summary='Bound records',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Exact retained evidence')}))]
        script=control/'script.json';atomic(script,steps)
        command=[sys.executable,'-B',str(Path(__file__).with_name('codex_protocol_fixture.py')),str(script)]
        with Client(CONFIG,BACKEND,control,20,command=command) as client:
            result=execute(f,control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered')
        receipts=[json.loads(p.read_text()) for p in sorted(control.glob('tool-*.json'))]
        self.assertIn('Unknown observation',receipts[0]['result']['error'])
        self.assertEqual(receipts[1]['result']['total'],5)
        self.assertEqual(len(receipts),5)
        self.assertEqual(len(list(control.glob('api-*.request.json'))),5)


class Composition(unittest.TestCase):
    def test_descendant_prefix_retains_ids_counters_and_never_duplicates_captures(self):
        base=dict(version=1,entries=[dict(pages=[dict(url='https://example.com/a',text='Original')])])
        fresh=copy.deepcopy(base);fresh['entries'].append(dict(pages=[dict(url='https://example.com/b',text='Additional')]))
        fresh['rendered_fallback']=dict(reads=[dict(url='https://example.com/b',outcome='captured')])
        result=sourcing_contract.compose_sources(base,fresh,'a'*64,'b'*64)
        self.assertEqual(result,fresh);self.assertEqual(len(result['entries']),2)
        self.assertIsNot(result,fresh)


class CompiledRecovery(unittest.TestCase):
    from tests.test_owner_intents import Tests as Fixture
    setUp=Fixture.setUp
    create=Fixture.create
    source=Fixture.source
    session=Fixture.session
    invoke=Fixture.invoke
    run_worker=Fixture.run_worker
    tearDown=retain_evidence

    def test_owner_admission_composes_baseline_then_worker_reopens_preserving_records(self):
        from orchestrator import operation_contracts as contracts
        helper=records.Tests();helper.setUp();self.addCleanup(helper.doCleanups)
        baseline=helper.complete_catalog()
        baseline['contract']['id']='collection.options'
        semantic=dict(options_per_item=3,count_policy='target',max_records=2,
            field_definitions={name:'price' if name=='price' else 'text' for name in sourcing_contract.FIELDS},identity_field='name_variant')
        baseline['parameters'].update(semantic)
        # Inputs retain exact source bytes, including the serialized newline.
        inventory=self.source((helper.root/'inventory.json').read_text(),'inventory.json','application/json')
        old=self.source((helper.root/'sources.json').read_text(),'base.json','application/json')
        catalog=self.source(contracts.encoded(baseline)+'\n','catalog.json','application/json')
        fresh=copy.deepcopy(helper.pack);fresh['entries']=fresh['entries'][:1]
        fresh['entries'][0]['pages'][0]['url']='https://example.com/new'
        new=self.source(contracts.encoded(fresh)+'\n','fresh.json','application/json')
        # Controlled upstream capture receipts, matching the compiler fixture's
        # source authority. No assertion of live fetching is made by this test.
        for name,ref in [('old-capture',old),('new-capture',new)]:
            a=self.rt.artifact(ref['artifact'])
            receipt=dict(status='finished',operation=dict(output_sha256=a['sha256'],validation=dict(fetched=1)))
            self.rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                (name,'prior','sources','prior','completed',None,json.dumps(dict(execution=dict(capability='web.sources'))),'{}',json.dumps(receipt),None))
            self.rt.db.execute('UPDATE production_artifacts SET attempt=?,path=? WHERE id=?',(name,'delivery/source-pack.json',a['id']))
        self.grant.pop('delegation_version');self.grant.update(coordination_version=1,owner_progress_version=1)
        self.grant['task_limits'].update(tool_calls=30,provider_requests=24,output_bytes=3000000)
        self.create(inputs=[inventory,old,catalog,new]);self.rt.tick('job')
        task=dict(id='repair',objective='Add evidence to the existing catalog; keep valid options',
            inputs=[dict(artifact=old['artifact']),dict(artifact=catalog['artifact'])],
            content=dict(family='collection.options',sources=dict(inventory_path=dict(artifact=inventory['artifact']),source_pack_path=dict(artifact=new['artifact'])),parameters=semantic))
        self.invoke([('job_delegate',dict(request_id='recover',tasks=[task]))]);self.rt.tick('job')
        spec=self.rt.spec(self.rt.task('job','repair'));params=spec['operation_contract']['parameters']
        self.assertIn('base_catalog_path',params)
        self.assertEqual(spec['limits']['output_bytes'],3000000)
        def steps(f):
            return [('source_find',dict(observation='',query='Walnut desk',offset=0,limit=40))]
        f,_=self.run_worker('repair',steps)
        result=self.rt.output('job','repair',f['operation_contract']['output'])
        value=json.loads(Path(result['blob']).read_text())
        self.assertEqual(value['items'][0]['options'],baseline['items'][0]['options'])
        evidence=self.rt.output('job','repair',params['source_pack_output'])
        pack=json.loads(Path(evidence['blob']).read_text())
        self.assertEqual(pack['entries'][:5],helper.pack['entries']);self.assertEqual(len(pack['entries']),6)
        reviews=[t for t in self.rt.status('job')['tasks'] if t['id']!='owner' and self.rt.spec(self.rt.task('job',t['id'])).get('review_of')=='repair']
        self.assertEqual(len(reviews),1)
        reviewer=self.factory.sessions[self.rt.task('job',reviews[0]['id'])['latest']]['frozen']
        context=sourcing_contract.context(reviewer,lambda p:(Path(reviewer['workspace'])/p).read_bytes())
        self.assertEqual(context['source_versions']['source_pack_sha256'],evidence['sha256'])
        self.assertEqual(len(context['items']),2)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.assertEqual(self.rt.output('job','repair',params['source_pack_output'])['sha256'],evidence['sha256'])


class RetainedConsumer(unittest.TestCase):
    from tests.test_source_recovery_policy import Handoff as Fixture
    setUp=Fixture.setUp
    source=Fixture.source
    session=Fixture.session
    invoke=Fixture.invoke
    run_worker=Fixture.run_worker
    execute_operation=Fixture.execute_operation
    begin=Fixture.begin
    tearDown=retain_evidence
    def create(self,inputs):
        from tests.test_owner_intents import Tests
        self.inventory=self.source(json.dumps(dict(items=[dict(id='part',label='Part')])),'inventory.json','application/json')
        return Tests.create(self,inputs=[*inputs,self.inventory])

    def test_consumer_uses_committed_descendant_of_blocked_worker_after_restart(self):
        from orchestrator import owner_intents
        self.grant.update(coordination_version=1,owner_progress_version=1)
        original,richer=self.begin(inline=True)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        task=dict(id='consume',objective='Use retained observations',content=dict(family='collection.options',
            sources=dict(inventory_path=dict(artifact=self.inventory['artifact']),source_pack_path=dict(artifact=original['artifact'])),
            parameters=dict(field_definitions={'name':'text'},identity_field='name',max_records=1,options_per_item=1,count_policy='target')))
        bound=owner_intents.compile(self.session(),dict(request_id='consume',tasks=[task]))[0]
        self.assertEqual(bound['records']['inputs']['source_pack_path'],dict(source=richer['id']))
        self.assertEqual(self.rt.task('job','read')['status'],'blocked')
        before=self.rt.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0]
        # A second independent consumer does not receive another browser dispatch.
        task['id']='consume-again'
        owner_intents.compile(self.session(),dict(request_id='consume-again',tasks=[task]))
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],before)


if __name__=='__main__':unittest.main()
