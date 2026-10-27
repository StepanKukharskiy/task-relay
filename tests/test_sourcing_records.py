"""Small text fixtures for typed sourcing, versioned review and native handoff."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from orchestrator import operation_contracts as contracts, operation_records as records, storage
from orchestrator import sourcing_contract as sourcing, report_builder
from orchestrator.gemini_worker import Files, execute, definitions
from task_relay import sourcing_planning

BACKEND={'type':'gemini-agent','model':'gemini-3.7-flash'}
CONFIG={'api_key':'synthetic-key','models':{'text':BACKEND['model']}}

def response(name,args):
    return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'functionCall':{'name':name,'args':args}}]}}]}

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();(self.root/'.relay').mkdir()
        self.db=sqlite3.connect(self.root/'state.sqlite',isolation_level=None);self.addCleanup(self.db.close)
        storage.initialize(self.db)
        self.text='Walnut desk\nUSD Price $349.99\nWidth 120 cm\nShips to United States\nOrder online'
        self.pack={'version':1,'entries':[{'pages':[{'url':f'https://example.com/products/desk-{n}','text':self.text}]}
                                         for n in range(5)]}
        self.inventory={'items':[{'id':'item-a','label':'Walnut desk'},{'id':'item-b','label':'Pendant'}]}
        self.inputs=[self.input('inventory.json',self.inventory),self.input('sources.json',self.pack)]
        self.frozen=self.assignment('producer')
        self.save(self.frozen);self.files=Files(self.frozen);self.store=records.Store(self.frozen,self.db)
        self.context=self.store.sourcing_context()

    def input(self,path,data):
        raw=(contracts.encoded(data)+'\n').encode();target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        return dict(artifact=hashlib.sha256(path.encode()).hexdigest(),path=path,purpose='Synthetic bound source',
                    authority='Fixture evidence only',sha256=hashlib.sha256(raw).hexdigest())

    def assignment(self,ident,review=False):
        p=dict(inventory_path='inventory.json',source_pack_path='sources.json',max_records=len(self.inventory['items']),summary_path='delivery/'+ident+'.md')
        if review:p['catalog_path']='catalog.json'
        else:p.update(options_per_item=3,count_policy='target')
        f=dict(assignment_id=ident,workspace=str(self.root),operation_store=str(self.root/'state.sqlite'),
               backend=BACKEND.copy(),inputs=copy.deepcopy(self.inputs),outputs=[dict(path='delivery/'+ident+'.json',purpose='Code projection'),dict(path=p['summary_path'],purpose='Code projection')],
               operation_contract=dict(id='sourcing.review' if review else 'sourcing.options',version=1,parameters=p,output='delivery/'+ident+'.json'),
               criteria=['Preserve source-supported item records.'],instruction='Synthetic sourcing only',tools=['files'],
               limits=dict(seconds=600,tool_calls=24,provider_requests=24,response_tokens=4096,output_bytes=200000))
        if review:f['review_of']='producer'
        f['report_contract']=report_builder.freeze(f)
        return f

    def save(self,f):
        self.db.execute('INSERT OR REPLACE INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (f['assignment_id'],'run',f['assignment_id'],'assignment','running',None,contracts.encoded(f),'{}',None,None))

    def option(self,n=0):
        fields={k:dict(status='unknown',reason='Not established') for k in sourcing.FIELDS}
        for field,quote in [('name_variant','Walnut desk'),('price','USD Price $349.99'),('dimensions','Width 120 cm'),('us_context','Ships to United States'),('order_terms','Order online')]:
            start=self.text.index(quote);fields[field]=dict(status='observed',start=start,end=start+len(quote))
        return dict(observation=f'page-{n}-0',fields=fields,comparison='Matches inventory material; exact product identity uncertain.')

    def item(self,ident='item-a',count=1):
        return dict(item=ident,options=[self.option(n) for n in range(count)],gap='Missing alternatives' if count<3 else '')

    def submit(self,value,key='first',revision=0,store=None,context=None):
        return (store or self.store).submit(dict(request_key=key,revision=revision,records=[value]),context or self.context)

    def complete_catalog(self,count=1):
        self.submit(self.item(count=count));self.submit(self.item('item-b',0),'second',1)
        self.store.export(self.files,complete=True)
        return json.loads(self.files.read_bytes('delivery/producer.json'))

    def reviewer(self,catalog):
        f=self.assignment('reviewer',True);f['inputs'].append(self.input('catalog.json',catalog))
        f['report_contract']=report_builder.freeze(f);self.save(f)
        return f,records.Store(f,self.db)

    def test_interruption_reopen_and_failed_projection_keep_committed_fragments(self):
        receipt=self.submit(self.item())
        with patch('task_relay.filesystem.FILES.write',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.store.export(self.files)
        reopened=records.Store(self.frozen)
        self.assertEqual(reopened.progress()['remaining'],1)
        self.assertEqual(reopened.progress()['next_items'][0]['item'],'item-b')
        self.assertEqual(self.submit(self.item()),receipt)
        self.submit(self.item('item-b',0),'second',1,store=reopened)
        reopened.export(self.files,complete=True);reopened.verify_export(self.files.read_bytes)
        doc=json.loads(self.files.read_bytes('delivery/producer.json'))
        self.assertEqual(doc['items'][0]['options'][0]['fields']['price']['amount'],'349.99')
        self.assertIn('USD Price $349.99',self.files.read_bytes('delivery/producer.md').decode())

    def test_zero_one_five_options_project_with_explicit_target_shortfalls(self):
        for count in (0,1,5):
            with self.subTest(count=count):
                ctx=self.context;item=self.item(count=count)
                sourcing.options_record(item,self.frozen['operation_contract']['parameters'],ctx)
                doc=sourcing.options_document([item,self.item('item-b',0)],self.frozen['operation_contract']['parameters'],ctx)
                sourcing.validate_result(doc,{'decision':'delivered'})
                self.assertEqual(len(doc['items'][0]['options']),count)
                self.assertEqual(doc['items'][0]['shortfall'],max(0,3-count))
                from task_relay.delivery_completion import coverage_slots
                cov=coverage_slots(self.inventory,doc,3,'target')
                self.assertFalse(cov['missing'])

    def test_foreign_items_authored_prices_and_invalid_spans_are_atomic(self):
        bads=[self.item('foreign'),self.item(),self.item()]
        bads[1]['options'][0]['fields']['price']['amount']='999.99'
        bads[2]['options'][0]['fields']['price']['end']=9999
        for bad in bads:
            with self.assertRaises(ValueError):self.submit(bad)
        self.assertEqual(self.store.progress()['committed'],0)
        self.assertEqual(self.db.execute('select count(*) from operation_submissions').fetchone()[0],0)

    def test_duplicate_page_variants_cannot_pad_alternatives(self):
        changed=copy.deepcopy(self.pack);changed['entries'][1]['pages'][0]['url']='https://example.com/products/desk-0?finish=other'
        self.inputs[1]=self.input('sources.json',changed);self.frozen['inputs']=self.inputs;self.save(self.frozen)
        with self.assertRaisesRegex(ValueError,'Duplicate product'):self.store=records.Store(self.frozen,self.db);self.submit(self.item(count=2),context=self.store.sourcing_context())

    def test_amendment_preserves_history_and_rejects_stale_guards(self):
        self.submit(self.item());changed=self.item();changed['options'][0]['comparison']='Corrected comparison'
        args=dict(request_key='repair',revision=1,expected_record_sha256=contracts.digest(self.item()),record=changed)
        receipt=self.store.amend(args,self.context)
        self.assertEqual(self.store.amend(args,self.context),receipt)
        old=json.loads(self.db.execute('select value from operation_record_versions').fetchone()[0])
        self.assertEqual(old,self.item())
        with self.assertRaisesRegex(ValueError,'Stale'):self.store.amend(dict(args,request_key='again'),self.context)
        self.assertEqual(self.store.progress()['revision'],2)
        self.db.execute("update production_attempts set state='blocked' where id='producer'")
        self.assertEqual(self.store.amend(args,self.context),receipt)
        with self.assertRaisesRegex(ValueError,'stopped'):self.store.amend(dict(args,request_key='new',revision=2),self.context)

    def test_fragment_errors_identify_nested_shape_before_atomic_correction_and_restart(self):
        bad=self.item();bad['options'][0]['comparison']={'visual_fit':'Fits'}
        with self.assertRaisesRegex(ValueError,r'records\[0\].options\[0\].comparison: expected string'):
            self.submit(bad)
        bad['options'][0]['comparison']='x'*601
        with self.assertRaisesRegex(ValueError,'601 characters; maximum 600'):self.submit(bad)
        bad=self.item();del bad['options'][0]['fields']['price']['status']
        with self.assertRaisesRegex(ValueError,r'fields.price: missing status'):self.submit(bad)
        self.assertEqual(self.store.progress()['committed'],0)
        self.assertEqual(self.db.execute('select count(*) from operation_submissions').fetchone()[0],0)
        original=self.item();receipt=self.submit(original)
        reopened=records.Store(self.frozen)
        self.assertEqual(self.submit(original,store=reopened),receipt)
        changed=copy.deepcopy(original);changed['options'][0]['comparison']={'bad':'shape'}
        args=dict(request_key='repair',revision=1,expected_record_sha256=contracts.digest(original),record=changed)
        with self.assertRaisesRegex(ValueError,r'record.options\[0\].comparison: expected string'):
            reopened.amend(args,self.context)
        self.assertEqual(reopened.progress()['revision'],1)
        changed['options'][0]['comparison']='Corrected comparison after restart'
        amended=reopened.amend(args,self.context)
        self.assertEqual(amended['revision'],2)
        self.assertEqual(json.loads(self.db.execute('select value from operation_record_versions').fetchone()[0]),original)
        self.submit(self.item('item-b',0),'second',2,store=reopened)
        reopened.export(self.files,complete=True);reopened.verify_export(self.files.read_bytes)

    def test_review_checkpoints_survive_reopen_but_cannot_accept_uncertainty(self):
        catalog=self.complete_catalog();f,store=self.reviewer(catalog);ctx=store.sourcing_context()
        item=catalog['items'][0]
        r=dict(item=item['id'],item_sha256=contracts.digest(item),verdict='supported',reason='Captured fields match declared variant; saved evidence only.')
        self.submit(r,'review-a',0,store,ctx)
        reopened=records.Store(f)
        next_item=reopened.progress()['next_items'][0]
        self.assertEqual(next_item['item'],'item-b')
        r2=dict(item=next_item['item'],item_sha256=next_item['item_sha256'],verdict='uncertain',reason='No source-supported alternative found.')
        self.submit(r2,'review-b',1,reopened,ctx)
        reopened.export(Files(f),complete=True)
        with self.assertRaisesRegex(ValueError,'cannot be accepted'):reopened.verify_result({'decision':'accept'})
        reopened.verify_result({'decision':'revise'})

    def test_review_version_guard_and_projection_tampering(self):
        catalog=self.complete_catalog();f,review=self.reviewer(catalog);ctx=review.sourcing_context()
        old=catalog['items'][0];r=dict(item=old['id'],item_sha256='0'*64,verdict='supported',reason='Wrong version')
        with self.assertRaisesRegex(ValueError,'different item version'):self.submit(r,'wrong',0,review,ctx)
        forged=copy.deepcopy(ctx);forged['items'][r['item']]={'invented':'version'}
        r['item_sha256']=contracts.digest(forged['items'][r['item']])
        with self.assertRaisesRegex(ValueError,'different item version'):self.submit(r,'forged',0,review,forged)
        catalog['items'][0]['options'][0]['fields']['price']['amount']='999.99'
        f['inputs'][-1]=self.input('catalog.json',catalog);self.save(f)
        with self.assertRaisesRegex(ValueError,'differs'):records.Store(f,self.db).sourcing_context()

    def test_generic_writes_cannot_replace_either_code_projection(self):
        for path in ('delivery/producer.json','delivery/producer.md'):
            with self.assertRaisesRegex(ValueError,'owned'):self.files.call('file_write',dict(path=path,text='Invented'))

    def test_preflight_rejects_insufficient_budget_without_expanding_it(self):
        small=copy.deepcopy(self.frozen);small['limits']['provider_requests']=3
        with self.assertRaisesRegex(ValueError,'needs 4'):sourcing.preflight(small,self.context)
        self.assertEqual(small['limits']['provider_requests'],3)

    def test_target_can_deliver_gaps_without_reading_every_available_page(self):
        small=copy.deepcopy(self.frozen);small['limits']['provider_requests']=4
        sourcing.preflight(small,self.context)
        self.assertEqual(small['limits']['provider_requests'],4)
        small['operation_contract']['parameters']['count_policy']='required'
        with self.assertRaisesRegex(ValueError,'needs 9'):sourcing.preflight(small,self.context)

    def test_malformed_json_source_is_a_contract_error_not_an_unhandled_crash(self):
        bad=copy.deepcopy(self.pack);bad['entries']=[None]
        self.frozen['inputs'][1]=self.input('sources.json',bad);self.save(self.frozen)
        with self.assertRaisesRegex(ValueError,'source-pack entry'):records.Store(self.frozen,self.db).sourcing_context()

    def test_thirteen_item_catalog_and_review_progress_within_frozen_request_budget(self):
        self.inventory={'items':[dict(id='item-'+str(n),label='Synthetic desk') for n in range(13)]}
        self.inputs[0]=self.input('inventory.json',self.inventory)
        self.frozen=self.assignment('producer');self.save(self.frozen);self.store=records.Store(self.frozen,self.db)
        ctx=self.store.sourcing_context();sourcing.preflight(self.frozen,ctx)
        for n,item in enumerate(self.inventory['items']):self.submit(self.item(item['id'],3),'item-'+str(n),n,self.store,ctx)
        files=Files(self.frozen);self.store.export(files,complete=True)
        catalog=json.loads(files.read_bytes('delivery/producer.json'));f,review=self.reviewer(catalog)
        for n,item in enumerate(catalog['items']):
            unit=review.progress()['next_items'][0]
            self.assertEqual(unit['item'],item['id'])
            self.submit(dict(item=item['id'],item_sha256=unit['item_sha256'],verdict='supported',reason='Synthetic evidence interpretation'),
                        'judgment-'+str(n),n,review,review.sourcing_context())
        review.export(Files(f),complete=True);review.verify_result({'decision':'accept'})
        self.assertEqual(review.progress()['remaining'],0)
        self.assertEqual(len(catalog['items']),13)
        self.assertEqual(sum(len(i['options']) for i in catalog['items']),39)

    def test_source_index_groups_exact_versions_without_merging_equal_text_at_different_urls(self):
        pack=copy.deepcopy(self.pack);pack['entries'].append(copy.deepcopy(pack['entries'][0]))
        self.frozen['inputs'][1]=self.input('sources.json',pack);self.save(self.frozen)
        progress=records.Store(self.frozen,self.db).progress()['observations']
        self.assertEqual(progress[-1]['duplicate_of'],'page-0-0')
        self.assertIsNone(progress[1]['duplicate_of'])

    def test_selectable_spans_use_exact_offsets_and_leave_price_meaning_for_review(self):
        ctx=copy.deepcopy(self.context);ctx['observations']['page-0-0']['text']='Previous $499.00\nCurrent $349.99\nWidth 120 cm'
        view=sourcing.source_read(ctx,dict(observation='page-0-0',offset=3,limit=12000))
        self.assertEqual([s['text'] for s in view['price_spans']],['$499.00','$349.99'])
        for span in view['price_spans']+view['text_spans']:
            self.assertEqual(ctx['observations']['page-0-0']['text'][span['start']:span['end']],span['text'])
        self.assertNotIn('selected_price',view)

    def test_budget_reserves_remaining_fragment_calls_and_finish_before_repeated_reads(self):
        from orchestrator import executors
        self.frozen['limits'].update(tool_calls=5,provider_requests=8);self.save(self.frozen)
        report=dict(summary='Synthetic reserved completion',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Exact spans and disclosed gaps')})
        model=Mock();model.request.side_effect=[response('sourcing_source_read',dict(observation='page-0-0',offset=0,limit=12000)),response('sourcing_source_read',dict(observation='page-1-0',offset=0,limit=12000)),response('operation_submit',dict(request_key='a',revision=0,records_json=json.dumps([self.item()]))),response('operation_submit',dict(request_key='b',revision=1,records_json=json.dumps([self.item('item-b',0)]))),response('finish',report)]
        control=self.root/'reserved-control';control.mkdir();(control/'launch.json').write_text(contracts.encoded({'credential_fingerprint':executors.fingerprint(CONFIG,BACKEND)}))
        with patch('orchestrator.gemini_worker.emit'):
            result=execute(self.frozen,control,client=model,config_reader=lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered')
        wire=model.request.call_args_list[2].args[1]['tools'][0]['functionDeclarations']
        self.assertEqual({t['name'] for t in wire},{'operation_submit','finish'})
        self.assertEqual(records.Store(self.frozen,self.db).progress()['remaining'],0)

    def test_api_worker_submits_fragments_and_code_exports_without_whole_file_writes(self):
        from orchestrator import executors
        report=dict(summary='Synthetic records saved',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Code-extracted saved spans and explicit gaps')})
        model=Mock();model.request.side_effect=[response('operation_submit',dict(request_key='a',revision=0,records=[self.item()])),
            response('operation_submit',dict(request_key='b',revision=1,records=[self.item('item-b',0)])),response('finish',report)]
        launch={'credential_fingerprint':executors.fingerprint(CONFIG,BACKEND)};control=self.root/'control';control.mkdir()
        (control/'launch.json').write_text(contracts.encoded(launch))
        with patch('orchestrator.gemini_worker.emit'):
            result=execute(self.frozen,control,client=model,config_reader=lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered')
        self.store.verify_export(lambda p:(self.root/p).read_bytes())
        first=model.request.call_args_list[0].args[1]
        declarations=first['tools'][0]['functionDeclarations']
        self.assertFalse(any(t['name'].startswith('file_') for t in declarations))
        self.assertIn('sourcing_source_read',{t['name'] for t in declarations})
        self.assertNotIn(self.text,json.dumps(first))
        calls=[json.loads(p.read_text())['name'] for p in sorted(control.glob('tool-*.json'))]
        self.assertEqual(calls,['operation_submit','operation_submit','finish'])
        self.assertEqual(self.store.progress()['committed'],2)

    def test_script_entry_namespace_builds_tools_reads_evidence_and_finishes(self):
        import runpy,sys
        import orchestrator.gemini_worker as module
        from orchestrator import executors
        report=dict(summary='Synthetic script-entry records saved',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Bound source spans and explicit gaps')})
        model=Mock();model.request.side_effect=[response('sourcing_source_read',dict(observation='page-0-0',offset=0,limit=12000)),response('operation_submit',dict(request_key='a',revision=0,records_json=json.dumps([self.item()]))),response('operation_submit',dict(request_key='b',revision=1,records_json=json.dumps([self.item('item-b',0)]))),response('finish',report)]
        control=self.root/'script-control';control.mkdir();(control/'launch.json').write_text(contracts.encoded({'credential_fingerprint':executors.fingerprint(CONFIG,BACKEND)}))
        self.frozen['runtime_sources']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(module.__file__).parent.glob('*.py')}
        self.save(self.frozen);(self.root/'.relay/ASSIGNMENT.json').write_text(contracts.encoded(self.frozen))
        with patch.object(sys,'argv',[module.__file__,str(control),str(self.root)]),patch('task_relay.gemini.Client',return_value=model),patch.object(executors,'configured_worker',return_value=(CONFIG,BACKEND)):
            namespace=runpy.run_path(module.__file__,run_name='__main__')
        self.assertEqual(namespace['__package__'],'')
        result=json.loads((self.root/'.relay/result.json').read_text())
        self.assertEqual(result['decision'],'delivered')
        tool=json.loads((control/'tool-01-00.json').read_text())
        self.assertEqual(tool['result']['text'],self.text)
        records.Store(self.frozen,self.db).verify_export(lambda p:(self.root/p).read_bytes())
        self.assertEqual(model.request.call_count,4)

    def test_gemini_fragment_transport_is_shallow_without_changing_local_contract(self):
        from orchestrator.gemini_worker import definitions,gemini_declarations,gemini_record_arguments
        shared=definitions(self.frozen);original=copy.deepcopy(shared)
        wire={t['name']:t for t in gemini_declarations(shared)}
        for name,field in (('operation_submit','records'),('operation_amend','record')):
            schema=wire[name]['parameters'];self.assertNotIn(field,schema['properties'])
            self.assertEqual(schema['properties'][field+'_json']['type'],'string')
            self.assertIn('JSON-encoded',schema['properties'][field+'_json']['description'])
        self.assertEqual(shared,original)
        for invalid in ('not json','{}'):
            with self.assertRaises(ValueError):gemini_record_arguments('operation_submit',dict(records_json=invalid))
        with self.assertRaises(ValueError):gemini_record_arguments('operation_submit',dict(records_json='[]',records=[]))
        invalid=self.item();invalid['options'][0]['fields']['price']['end']=len(self.text)+10
        args=gemini_record_arguments('operation_submit',dict(request_key='invalid-span',revision=0,records_json=json.dumps([invalid])))
        with self.assertRaises(ValueError):self.store.submit(args,self.store.sourcing_context())
        self.assertEqual(self.store.progress()['committed'],0)

    def test_planner_binds_contracts_and_handoff_requires_record_operation(self):
        plan={'tasks':[dict(id='p',inputs=copy.deepcopy(self.inputs),outputs=copy.deepcopy(self.frozen['outputs']),
                           tools=['files'],criteria=['Keep data'],limits=self.frozen['limits'].copy(),
                           sourcing=dict(version=1,inventory={'source':self.inputs[0]['artifact']},source_pack={'source':self.inputs[1]['artifact']},
                                         options_per_item=3,count_policy='target',max_records=2)),
                       dict(id='r',review_of='p',inputs=copy.deepcopy(self.inputs)+[dict(from_task='p',output='delivery/producer.json',path='upstream/catalog.json')],
                            outputs=[dict(path='delivery/review.json'),dict(path='delivery/review.md')],tools=['files'],criteria=['Semantic review'],limits=self.frozen['limits'].copy())]}
        sourcing_planning.bind(plan)
        self.assertEqual(plan['tasks'][1]['operation_contract']['id'],'sourcing.review')
        from orchestrator.handoff_contracts import bind_stage,ContractError
        plan['deliverables']={'catalog':{'task':'p','output':'delivery/producer.json'}}
        stage={'handoff':{'inputs':[],'outputs':{'catalog':dict(media_type='application/json',content_contract=dict(id='sourcing.options',version=1))}}}
        bind_stage(stage,plan)
        del plan['tasks'][0]['operation_contract']
        with self.assertRaisesRegex(ContractError,'registered record'):bind_stage(stage,plan)

    def test_new_reviewer_connector_supplies_only_the_missing_typed_projection(self):
        def plan():
            return {'tasks':[dict(id='p',inputs=copy.deepcopy(self.inputs),outputs=copy.deepcopy(self.frozen['outputs']),tools=['files'],criteria=['Keep data'],limits=self.frozen['limits'].copy(),sourcing=dict(version=1,inventory={'source':self.inputs[0]['artifact']},source_pack={'source':self.inputs[1]['artifact']},options_per_item=3,count_policy='target',max_records=2)),dict(id='r',review_of='p',inputs=copy.deepcopy(self.inputs)+[dict(from_task='p',output='delivery/producer.json',path='upstream/catalog.json')],outputs=[dict(path='delivery/review.md',purpose='Selected summary')],tools=['files'],criteria=['Semantic review'],limits=self.frozen['limits'].copy())]}
        value=plan();before=copy.deepcopy(value)
        sourcing_planning.bind(value,2)
        review=value['tasks'][1]
        self.assertEqual(review['operation_contract']['output'],'delivery/review.json')
        self.assertEqual(review['outputs'][0],before['tasks'][1]['outputs'][0])
        self.assertEqual(review['limits'],before['tasks'][1]['limits'])
        self.assertEqual(review['operation_contract']['parameters']['max_records'],2)
        from orchestrator.sourcing_contract import validate_assignment
        validate_assignment(review)
        with self.assertRaisesRegex(ValueError,'exactly one JSON'):sourcing_planning.bind(plan(),1)
        bad=plan();bad['tasks'][1]['inputs'].append(dict(path='delivery/review.json',artifact='existing'))
        with self.assertRaisesRegex(ValueError,'conflicts'):sourcing_planning.bind(bad,2)

    def test_legacy_planner_form_does_not_gain_new_sourcing_authority(self):
        from task_relay.planning_contract import contract
        old=contract({})['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']
        new=contract({'sourcing_records_version':1})['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']
        self.assertNotIn('sourcing',old);self.assertIn('sourcing',new)

    def native_pair(self,verdict='supported',provenance=True):
        from orchestrator.runtime import Runtime
        from tests.test_orchestrator import FakeFactory
        factory=FakeFactory();rt=Runtime(self.root/('runtime-'+verdict),factory);self.addCleanup(rt.db.close)
        sources=[]
        for i in self.inputs:
            aid=rt.register(self.root/i['path'],'Synthetic sourcing source')
            sources.append({**i,'artifact':aid})
        if provenance:
            native=rt.artifact(sources[1]['artifact'])
            fetched=sum(len(e['pages']) for e in self.pack['entries'])
            receipt=dict(status='finished',operation=dict(output_sha256=native['sha256'],validation=dict(fetched=fetched)))
            rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',('saved-read','original','sources','original','completed',None,
                          contracts.encoded(dict(execution=dict(capability='web.sources'))),'{}',contracts.encoded(receipt),None))
            rt.db.execute('UPDATE production_artifacts SET attempt=? WHERE id=?',('saved-read',native['id']))
        producer=self.assignment('producer');reviewer=self.assignment('reviewer',True)
        for t in (producer,reviewer):
            for k in ('assignment_id','workspace','operation_store','backend','report_contract'):t.pop(k,None)
            t.update(id='reviewer' if t.get('review_of') else 'producer',role='reviewer' if t.get('review_of') else 'producer',
                     objective='Typed sourcing fixture',max_attempts=1,inputs=copy.deepcopy(sources),dependencies=['producer'] if t.get('review_of') else [])
        reviewer['inputs'].append(dict(from_task='producer',output='delivery/producer.json',path='catalog.json',purpose='Exact candidate',authority='Unaccepted candidate'))
        reviewer['inputs'].append(dict(from_task='producer',output='delivery/producer.md',path='schedule.md',purpose='Exact candidate summary',authority='Unaccepted candidate'))
        reviewer['criteria']=producer['criteria']+[sourcing.SEMANTIC_CRITERION]
        rt.create(dict(id='typed-demo',brief='Synthetic native record chain',backend=BACKEND.copy(),tasks=[producer,reviewer]))
        rt.tick('typed-demo')
        if not provenance:return rt,factory
        def finish(tid,values,decision):
            aid=rt.task('typed-demo',tid)['latest'];session=factory.sessions[aid];f=session['frozen']
            store=records.Store(f,rt.db);ctx=store.sourcing_context();files=Files(f)
            for n,value in enumerate(values):store.submit(dict(request_key='record-'+str(n),revision=n,records=[value]),ctx)
            store.export(files,complete=True)
            report=dict(summary='Synthetic checkpoint completion',decision=decision,instruction='',findings=[],
                        checks={'c'+str(n):dict(passed=True,evidence='Exact code projection and semantic item checks') for n in range(1,len(f['criteria'])+1)})
            (Path(f['workspace'])/'.relay/result.json').write_text(contracts.encoded(report))
            session['status']=dict(status='finished',exit_code=0,reason=None,usage=[dict(input_tokens=10,output_tokens=5)])
            rt.tick('typed-demo')
        finish('producer',[self.item(count=1 if fetched else 0),self.item('item-b',0)],'delivered')
        aid=rt.task('typed-demo','reviewer')['latest'];f=factory.sessions[aid]['frozen']
        ctx=records.Store(f,rt.db).sourcing_context()
        judgments=[dict(item=k,item_sha256=contracts.digest(v),verdict=verdict,reason='Synthetic independent judgment with disclosed gaps') for k,v in ctx['items'].items()]
        finish('reviewer',judgments,'accept')
        return rt,factory

    def test_native_dispatch_delivery_uses_committed_catalog_and_independent_checkpoints(self):
        rt,factory=self.native_pair()
        self.assertEqual(rt.tick('typed-demo')['status'],'completed')
        self.assertEqual(len(factory.calls),2)
        self.assertEqual(rt.task('typed-demo','producer')['status'],'completed')
        self.assertIsNotNone(rt.output('typed-demo','producer','delivery/producer.json'))

    def test_native_supervisor_rejects_accept_that_contradicts_saved_review(self):
        rt,factory=self.native_pair('uncertain')
        self.assertEqual(rt.task('typed-demo','reviewer')['status'],'blocked')
        self.assertEqual(rt.task('typed-demo','producer')['status'],'awaiting_review')
        self.assertEqual(len(factory.calls),2)
        row=rt.db.execute('select error from production_attempts where id=?',(rt.task('typed-demo','reviewer')['latest'],)).fetchone()
        self.assertIn('cannot be accepted',row[0])

    def test_native_preflight_rejects_authored_source_pack_before_spending_attempt(self):
        rt,factory=self.native_pair(provenance=False)
        self.assertEqual(rt.task('typed-demo','producer')['attempts'],0)
        self.assertEqual(factory.calls,[])
        self.assertEqual(rt.task('typed-demo','producer')['status'],'blocked')

    def test_completed_empty_native_pack_delivers_honest_target_gaps(self):
        self.pack={'version':1,'entries':[{'pages':[]}]}
        self.inputs[1]=self.input('sources.json',self.pack)
        rt,factory=self.native_pair()
        self.assertEqual(rt.status('typed-demo')['status'],'completed')
        self.assertEqual(len(factory.calls),2)

class PlannerTests(unittest.TestCase):
    from tests.test_production_planning import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    request=Fixture.request
    action=Fixture.action
    queue=Fixture.queue
    row=Fixture.row

    def test_actual_planner_admission_compiles_explicit_intent_to_both_contracts(self):
        from orchestrator import executors
        from task_relay import production_planning as planning
        with patch.object(executors,'configured',return_value=(CONFIG,BACKEND)),patch.object(executors,'available'):
            row=dict(self.queue(action=self.action(executor='gemini-agent'),text='Prepare a catalog from supplied evidence; disclose gaps.'))
        payload=json.loads(row['context']);options=json.loads(row['options']);sources=[]
        for name,data in [('inventory.json',{'items':[{'id':'a'}]}),('sources.json',{'version':1,'entries':[]})]:
            file=self.rt.root/name;file.write_text(contracts.encoded(data));aid=self.rt.register(file,'Fixture source')
            artifact=self.rt.artifact(aid)
            source=dict(artifact=aid,path=name,purpose='Sourcing fixture',authority='Evidence',sha256=artifact['sha256'],bytes=artifact['bytes'],media_type='application/json')
            sources.append(source)
        payload['sources'].extend(sources)
        row['context']=contracts.encoded(payload);row['options']=contracts.encoded(options)
        selected=[{k:s[k] for k in ('artifact','path','purpose','authority','media_type')} for s in sources]
        limits=dict(seconds=600,tool_calls=24,provider_requests=24,response_tokens=4096,output_bytes=200000)
        p=dict(id='author',role='producer',objective='Produce catalog',instruction='Submit source-bound records and gaps',
               inputs=selected,outputs=[dict(path='delivery/catalog.json',purpose='Catalog'),dict(path='delivery/schedule.md',purpose='Schedule')],
               dependencies=[],criteria=['Keep all inventory items'],limits=limits.copy(),max_attempts=1,
               sourcing=dict(version=1,inventory={'source':sources[0]['artifact']},source_pack={'source':sources[1]['artifact']},options_per_item=3,count_policy='target',max_records=1))
        r=dict(id='review',role='reviewer',objective='Independently review captured records',instruction='Judge meaning and retain uncertainty',
               inputs=selected+[dict(from_task='author',output=o['path'],path='upstream/'+o['path'],purpose=o['purpose'],authority='Unaccepted output') for o in p['outputs']],
               outputs=[dict(path='delivery/review.json',purpose='Item verdicts'),dict(path='delivery/review.md',purpose='Review')],dependencies=['author'],review_of='author',
               criteria=['Check captured semantics'],limits=limits.copy(),max_attempts=1)
        value=dict(decision='ready',message='Typed catalog and independent review',plan=dict(brief='Source records',tasks=[p,r]),input_basis=dict(mode='new',artifacts=[]))
        _,compiled=planning.validate_result(contracts.encoded(value),row)
        self.assertEqual([t['operation_contract']['id'] for t in compiled['tasks']],['sourcing.options','sourcing.review'])
        self.assertEqual([t['tools'] for t in compiled['tasks']],[['files'],['files']])
        self.assertEqual(self.factory.calls,[])

if __name__=='__main__':unittest.main()
