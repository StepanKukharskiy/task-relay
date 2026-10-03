"""Typed operations on tiny saved observations; no provider or browser calls."""
import copy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock,patch

from orchestrator import operation_contracts as contracts,operation_records as records,storage,research_quality
from orchestrator.gemini_worker import Files,execute
from orchestrator.workers import atomic
from tests import test_research_quality as research_fixture
from tests.test_research_quality import plan
from tests.test_gemini_executor import BACKEND,CONFIG,report
from tests.test_computer_generation_recovery import response


class Tests(unittest.TestCase):
    def setUp(self):
        self.fixture=research_fixture.Tests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.frozen,self.audit=self.fixture.frozen_review();self.root=self.fixture.root.resolve()
        self.frozen['workspace']=str(self.root)
        (self.root/'.relay').mkdir()
        self.frozen['research_audit']['version']=2
        self.frozen['operation_contract']=dict(id='research.audit',version=1,parameters={},output='delivery/research_audit.json')
        self.frozen['backend']=BACKEND.copy()
        self.frozen['operation_store']=str(self.root/'state.sqlite')
        self.db=sqlite3.connect(self.frozen['operation_store'],isolation_level=None);self.addCleanup(self.db.close)
        storage.initialize(self.db);self.save_assignment()
        self.files=Files(self.frozen);self.store=records.Store(self.frozen,self.db)
        self.context=records.audit_context(self.frozen,self.files.read_bytes)

    def save_assignment(self):
        self.db.execute('INSERT OR REPLACE INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
            (self.frozen['assignment_id'],'run','review','assignment','running',None,json.dumps(self.frozen),'{}',None,None))

    def submit(self,values=None,key='batch-1',revision=0):
        return self.store.submit(dict(request_key=key,revision=revision,records=values or self.audit['claims']),self.context)

    def test_reopen_repair_projection_and_idempotent_receipt(self):
        receipt=self.submit()
        with patch('task_relay.filesystem.FILES.write',side_effect=OSError('disk temporarily unavailable')):
            with self.assertRaises(OSError):self.store.export(self.files,complete=True)
        reopened=records.Store(self.frozen)
        self.assertEqual(reopened.progress()['remaining'],0)
        self.assertEqual(self.submit(),receipt)
        reopened.export(self.files,complete=True)
        reopened.verify_export(self.files.read_bytes)
        self.assertEqual(json.loads(self.files.read_bytes('delivery/research_audit.json')),self.audit)
        self.assertEqual(self.db.execute('SELECT count(*) FROM operation_records').fetchone()[0],3)

    def test_stale_conflicting_and_foreign_submissions_are_atomic(self):
        self.submit(self.audit['claims'][:1])
        for values,key,revision in [([self.audit['claims'][1]],'next',0),
                ([dict(self.audit['claims'][0],reason='changed')],'batch-1',0),
                ([dict(self.audit['claims'][1],claim=999)],'foreign',1),
                ([self.audit['claims'][1],dict(self.audit['claims'][2],supports=[{'observation':'foreign','quote':'invented'}])],'mixed',1)]:
            with self.assertRaises(ValueError):self.submit(values,key,revision)
        self.assertEqual(self.store.progress()['committed'],1)
        with self.assertRaisesRegex(ValueError,'completion'):self.store.export(self.files,complete=True)
        self.submit(self.audit['claims'][1:],'next',1)
        self.assertEqual(self.store.progress()['remaining'],0)

    def test_no_generic_overwrite_or_forged_export(self):
        with self.assertRaisesRegex(ValueError,'owned'):self.files.call('file_write',dict(path='delivery/research_audit.json',text='{}'))
        self.submit();self.store.export(self.files,complete=True)
        (self.root/'delivery/research_audit.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'differs'):self.store.verify_export(self.files.read_bytes)
        changed=copy.deepcopy(self.frozen);changed['computer_review']['research']['units'][0]['text']='Different candidate'
        with self.assertRaisesRegex(ValueError,'authoritative'):records.Store(changed,self.db).progress()

    def test_unsupported_commits_but_never_accepts(self):
        self.audit['claims'][1].update(verdict='unsupported',supports=[])
        self.submit();self.store.export(self.files,complete=True)
        from orchestrator.contracts import report as validate
        with self.assertRaisesRegex(ValueError,'Unsupported'):validate(report(self.frozen),self.frozen)

    def test_worker_uses_typed_records_then_generates_review(self):
        from orchestrator import executors
        control=self.root/'control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        model=Mock();model.request.side_effect=[response('operation_submit',dict(request_key='first',revision=0,records=self.audit['claims'])),
            response('finish',dict(report_json=json.dumps(report(self.frozen))))]
        result=execute(self.frozen,control,model,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'accept');self.assertEqual(model.request.call_count,2)
        declaration=next(t for t in model.request.call_args_list[0].args[1]['tools'][0]['functionDeclarations'] if t['name']=='operation_submit')
        self.assertNotIn('parameters',declaration)
        self.assertFalse(declaration['parametersJsonSchema']['additionalProperties'])
        self.assertEqual(declaration['parametersJsonSchema']['properties']['records']['maxItems'],3)
        self.store.verify_export(lambda p:(self.root/p).read_bytes())
        self.assertTrue((self.root/'review.md').is_file())

    def test_malformed_generation_executes_no_partial_records(self):
        from orchestrator import executors
        control=self.root/'control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        broken=response('operation_submit',dict(request_key='discarded',revision=0,records=self.audit['claims']))
        broken['candidates'][0]['finishReason']='MALFORMED_FUNCTION_CALL'
        model=Mock();model.request.side_effect=[broken,response('operation_submit',dict(request_key='valid',revision=0,records=self.audit['claims'])),
            response('finish',dict(report_json=json.dumps(report(self.frozen))))]
        self.assertEqual(execute(self.frozen,control,model,lambda:(CONFIG,BACKEND))['decision'],'accept')
        self.assertEqual([r[0] for r in self.db.execute('SELECT request_key FROM operation_submissions')],['valid'])

    def test_explicit_discovery_and_profile_use_same_framework(self):
        for entity,required in [('person',['manual_work','tools']),('supplier',['product','minimum_order'])]:
            p=plan();producer,reviewer=p['tasks']
            producer.update(instruction='Discover source-linked entities.',objective='Discover candidates',
                research=dict(mode='discovery',parameters=dict(entity_type=entity,required_fields=required,max_records=2)))
            producer['limits'].update(provider_requests=16);reviewer['limits'].update(provider_requests=16)
            research_quality.bind(p,'Discover two entities.',structured=True)
            contracts.validate_assignment(producer);contracts.validate_assignment(reviewer)
            parameters=producer['operation_contract']['parameters']
            value=dict(url='https://example.org/entity',name='Fixture',identity_support=[dict(observation='o1',quote='Fixture')],
                facts=[dict(field=f,status='unknown',text='Not observed in these captures.',supports=[]) for f in required])
            ctx={'sources':{'o1':'Fixture https://example.org/entity'}}
            self.assertEqual(contracts.candidate_record(value,parameters,ctx),value['url'])
            document=dict(contract=dict(id='research.candidates',version=1),parameters=parameters,records=[value])
            contracts.validate_document(json.dumps(document),document['contract'])
            with self.assertRaises(ValueError):contracts.validate_document('{"posts":[]}',document['contract'])
            evidence=json.dumps(document).encode();summary=b'[Limitation] Only saved captures were inspected.\n'
            result=research_quality.candidate(producer['research_delivery'],{'evidence.json':evidence,'summary.md':summary}.__getitem__,
                dict(observations=[dict(observation='o1',text=ctx['sources']['o1'])]))
            self.assertEqual(len(result['units']),4)  # summary, identity, every required fact
        p=plan();p['tasks'][0]['research']={'mode':'profile'};p['tasks'][1]['limits']['provider_requests']=16
        research_quality.bind(p,'Inspect at most five posts.',structured=True)
        self.assertEqual(p['tasks'][0]['research_delivery']['version'],1)
        self.assertEqual(p['tasks'][1]['operation_contract']['id'],'research.audit')

    def test_typed_handoffs_reject_json_kind_mismatch_and_reuse_geometry_validator(self):
        from orchestrator import handoff_contracts as h
        from tests.test_handoff_contracts import stage,edge
        identity=dict(id='research.candidates',version=1)
        stages=[stage('a','production',{'data':dict(media_type='application/json',content_contract=identity)}),
                stage('b','production',{'summary':dict(media_type='text/markdown')},inputs=[dict(**edge('a','data','application/json'),content_contract=identity)])]
        h.compile_workflow(stages,required=True)
        stages[1]['handoff']['inputs'][0]['content_contract']=dict(id='research.audit',version=1)
        with self.assertRaisesRegex(ValueError,'exact content contract'):h.compile_workflow(stages,required=True)
        target=self.root/'typed.json';target.write_text('{"posts":[]}')
        with self.assertRaises(ValueError):h.check_file(target,dict(media_type='application/json',content_contract=identity))
        geometry=dict(version=1,units='Meters',tolerance=.001,layers=[dict(name='main',color=[0,0,0])],
            objects=[dict(name='origin',layer='main',type='point',point=[0,0,0])])
        contracts.validate_document(json.dumps(geometry),dict(id='geometry.specification',version=1))
        geometry['objects'][0]['point']=[float('nan'),0,0]
        with self.assertRaises(ValueError):contracts.validate_document(json.dumps(geometry),dict(id='geometry.specification',version=1))

    def test_supervisor_freezes_store_and_requires_committed_review(self):
        original=research_quality.bind
        def bind(p,request):
            p['tasks'][0]['research']={'mode':'profile'}
            p['tasks'][1]['limits']['provider_requests']=16
            return original(p,request,structured=True)
        fixture=research_fixture.IntegrationTests()
        with patch.object(research_quality,'bind',side_effect=bind):fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.deliver()
        rid=fixture.rt.task('demo','review')['latest']
        self.assertIsNotNone(rid)
        frozen=fixture.factory.sessions[rid]['frozen']
        self.assertEqual(Path(frozen['operation_store']),fixture.rt.root/'state.sqlite')
        store=records.Store(frozen,fixture.rt.db);files=Files(frozen)
        verdict=dict(claim=1,verdict='supported',reason='The observed source reports a supplier catalog issue.',
            supports=[dict(observation=fixture.observation,quote='Synthetic supplier catalog issue.')])
        store.submit(dict(request_key='one',revision=0,records=[verdict]),records.audit_context(frozen,files.read_bytes))
        from orchestrator.gemini_worker import save_review_report
        fixture.factory.finish(rid,decision='accept')
        store.export(files,complete=True);save_review_report(files,frozen,report(frozen))
        fixture.rt.tick('demo')
        self.assertEqual(fixture.rt.task('demo','produce')['status'],'awaiting_user')
        self.assertEqual(len(fixture.factory.calls),2)

    def test_feasibility_and_explicit_contracts_preserve_legacy(self):
        old=plan();research_quality.bind(old,'Inspect at most five posts.')
        self.assertNotIn('operation_contract',old['tasks'][1])
        fresh=plan();fresh['tasks'][0]['research']={'mode':'profile'}
        with self.assertRaisesRegex(ValueError,'16 requests'):research_quality.bind(fresh,'Inspect five posts.',structured=True)
        fresh=plan();fresh['tasks'][0].update(instruction='Read a page.',objective='Save page data.')
        research_quality.bind(fresh,'Read a page.',structured=True)
        self.assertNotIn('research_delivery',fresh['tasks'][0])  # extensions alone do not choose semantics

    def test_candidate_records_checkpoint_with_frozen_job_parameters(self):
        p=plan();producer,review=p['tasks']
        producer.update(instruction='Discover suppliers.',objective='Discover suppliers',
            research=dict(mode='discovery',parameters=dict(entity_type='supplier',required_fields=['product'],max_records=2)))
        for t in p['tasks']:t['limits']['provider_requests']=16
        research_quality.bind(p,'Discover suppliers.',structured=True)
        frozen={**producer,'assignment_id':'candidate-fixture','workspace':str(self.root),
                'operation_store':self.frozen['operation_store']}
        self.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
            ('candidate-fixture','run','produce','candidate-version','running',None,json.dumps(frozen),'{}',None,None))
        store=records.Store(frozen,self.db)
        value=dict(url='https://example.org/supplier',name='Fixture supplier',
            identity_support=[dict(observation='source',quote='Fixture supplier')],
            facts=[dict(field='product',status='unknown',text='Product not observed.',supports=[])])
        context=dict(sources={'source':'Fixture supplier https://example.org/supplier'})
        receipt=store.submit(dict(request_key='candidate-1',revision=0,records=[value]),context)
        self.assertEqual(receipt['committed'],1)
        files=Files({**frozen,'inputs':[]})
        # Files receives the same output grants; only this synthetic fixture has no input files.
        store.export(files,complete=True)
        result=json.loads(files.read_bytes('evidence.json'))
        self.assertEqual(result['parameters']['entity_type'],'supplier')
        self.assertEqual(result['records'][0]['facts'][0]['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'already committed'):
            store.submit(dict(request_key='duplicate-url',revision=1,records=[value]),context)

    def test_builder_carries_explicit_consumer_contract(self):
        from task_relay.workflow_builder import build
        identity=dict(id='research.candidates',version=1)
        action=dict(kind='plan_pipeline',title='Typed fixture',planning_only=True,stage_details=[
            dict(id='discover',instruction='Discover candidate entities.',route='production',gate='none',capabilities=[],
                outputs={'candidates':dict(description='Ledger',format='json',content_contract=identity)},uses=[]),
            dict(id='summarize',instruction='Read the ledger.',route='production',gate='none',capabilities=[],
                outputs={'summary':dict(description='Summary',format='markdown')},
                uses=[dict(stage='discover',output='candidates',consumer='context',content_contract=identity)])])
        result,_=build(action,{'capabilities':{'graph_operations':[]}})
        self.assertEqual(result['stages'][1]['handoff']['inputs'][0]['content_contract'],identity)

    def test_same_contract_validation_and_receipts_across_every_text_provider(self):
        from orchestrator import executors
        from tests.test_api_providers import tool_response
        neutral=contracts.tool(self.frozen['operation_contract'])
        self.assertIn('parameters',neutral);self.assertNotIn('parametersJsonSchema',neutral)
        artifacts=[]
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider):
                f=copy.deepcopy(self.frozen);f['assignment_id']='audit-'+provider
                f['backend']=dict(type=provider+'-agent',model='fixture-model')
                ws=self.root/provider;ws.mkdir();(ws/'.relay').mkdir()
                for item in f['inputs']:
                    target=ws/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes((self.root/item['path']).read_bytes())
                f['workspace']=str(ws)
                self.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (f['assignment_id'],'run','review','version','running',None,json.dumps(f),'{}',None,None))
                control=ws/'control';control.mkdir();config={'api_key':'fixture-only'}
                atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,f['backend'])))
                def reply(name,args,index):
                    if provider=='gemini':
                        return response(name,dict(report_json=json.dumps(args)) if name=='finish' else args)
                    return tool_response(provider,name,args,call_id=str(index))
                good=dict(request_key='same-records',revision=0,records=self.audit['claims'])
                bad=copy.deepcopy(good);bad['records'][0]['supports'][0]['quote']='Fabricated source text'
                model=Mock();model.request.side_effect=[reply('operation_submit',bad,1),
                    reply('operation_submit',good,2),reply('operation_submit',good,3),reply('finish',report(f),4)]
                result=execute(f,control,model,lambda:(config,f['backend']))
                self.assertEqual(result['decision'],'accept');self.assertEqual(model.request.call_count,4)
                first=json.loads((control/'tool-01-00.json').read_text())['result']
                self.assertIn('absent',first['error'])
                receipts=[json.loads((control/('tool-0'+str(i)+'-00.json')).read_text())['result'] for i in (2,3)]
                self.assertEqual(receipts[0],receipts[1])
                self.assertEqual(records.Store(f,self.db).progress()['committed'],3)
                payload=model.request.call_args_list[0].args[1]
                if provider=='gemini':
                    wire=next(t for t in payload['tools'][0]['functionDeclarations'] if t['name']=='operation_submit')
                    schema=wire['parametersJsonSchema'];self.assertNotIn('parameters',wire)
                else:
                    tools=payload['tools'] if provider=='openai' else [t['function'] for t in payload['tools']]
                    wire=next(t for t in tools if t['name']=='operation_submit');schema=wire['parameters']
                    self.assertNotIn('parametersJsonSchema',wire)
                self.assertEqual(schema,neutral['parameters'])
                artifacts.append((ws/f['operation_contract']['output']).read_bytes())
        self.assertTrue(all(a==artifacts[0] for a in artifacts))
