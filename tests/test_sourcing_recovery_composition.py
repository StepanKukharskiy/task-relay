"""Text-only evidence composition and version-bound catalog recovery."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from orchestrator import operation_contracts as contracts,operation_records as records,sourcing_contract as sourcing,executors
from orchestrator.gemini_worker import Files
from task_relay import sourcing_recovery,preparation_reviews
from tests import test_sourcing_records


class RecordTests(unittest.TestCase):
    setUp=test_sourcing_records.Tests.setUp
    input=test_sourcing_records.Tests.input
    assignment=test_sourcing_records.Tests.assignment
    save=test_sourcing_records.Tests.save
    option=test_sourcing_records.Tests.option
    item=test_sourcing_records.Tests.item
    submit=test_sourcing_records.Tests.submit
    complete_catalog=test_sourcing_records.Tests.complete_catalog
    def prepare(self):
        baseline=self.complete_catalog()
        fresh=copy.deepcopy(self.pack);fresh['entries']=fresh['entries'][:1]
        fresh['entries'][0]['pages'][0]['url']='https://example.com/products/new-desk'
        f=self.assignment('recovery')
        f['inputs']+= [self.input('baseline.json',baseline),self.input('fresh.json',fresh)]
        p=f['operation_contract']['parameters'];p.update(source_pack_path='fresh.json',base_source_pack_path='sources.json',base_catalog_path='baseline.json',source_pack_output='delivery/combined.json')
        f['outputs'].append(dict(path='delivery/combined.json',purpose='Code-composed evidence'))
        self.save(f);return baseline,f,records.Store(f,self.db)

    def test_preserves_prior_options_indices_and_prices_then_exports_reviewed_evidence(self):
        baseline,f,store=self.prepare();ctx=store.sourcing_context()
        new=self.option();new['observation']='page-5-0'
        item=dict(item='item-a',options=[new],gap='Target shortfall disclosed')
        args=dict(request_key='add',revision=0,records=[item])
        receipt=store.submit(args,None)
        self.assertEqual(store.submit(args,None),receipt)
        store.submit(dict(request_key='empty',revision=1,records=[self.item('item-b',0)]),None)
        files=Files(f);store.export(files,complete=True);store.verify_export(files.read_bytes)
        catalog=json.loads(files.read_bytes('delivery/recovery.json'));pack=json.loads(files.read_bytes('delivery/combined.json'))
        self.assertEqual(pack['entries'][:5],self.pack['entries'])
        self.assertEqual(len(pack['entries']),6)
        self.assertEqual(catalog['items'][0]['options'][0],baseline['items'][0]['options'][0])
        self.assertEqual(len(catalog['items'][0]['options']),2)
        self.assertEqual(catalog['source_versions']['source_pack_sha256'],hashlib.sha256(files.read_bytes('delivery/combined.json')).hexdigest())
        self.assertIn('delivery/combined.json',store.owned_outputs())
        # Review consumes the exported composition, independently of raw inputs.
        review=self.assignment('composition-review',True);review['inputs']=[self.input('inventory.json',self.inventory),self.input('composed.json',pack),self.input('catalog.json',catalog)]
        review['operation_contract']['parameters']['source_pack_path']='composed.json'
        review_ctx=sourcing.context(review,lambda p:(self.root/p).read_bytes())
        self.assertEqual(review_ctx['source_versions'],catalog['source_versions'])
        self.assertEqual(len(review_ctx['items']),2)

    def test_omitted_or_duplicate_baseline_option_cannot_erase_supported_evidence(self):
        baseline,f,store=self.prepare()
        store.submit(dict(request_key='empty-addition',revision=0,records=[self.item(count=0)]),None)
        item=store.document(store._state(self.db)[1])['items'][0]
        self.assertEqual(item['options'],baseline['items'][0]['options'])
        record=self.item(count=1);record['options'][0]['comparison']='Attempted replacement'
        before=store.progress()
        with self.assertRaisesRegex(ValueError,'Existing option differs'):
            store.amend(dict(request_key='duplicate',revision=1,expected_record_sha256=contracts.digest(store._state(self.db)[1][0]),record=record),None)
        self.assertEqual(store.progress(),before)
        self.assertEqual(store.document(store._state(self.db)[1])['items'][0]['options'],baseline['items'][0]['options'])

    def test_changed_baseline_is_rejected_before_fragments_are_committed(self):
        _,f,store=self.prepare();(self.root/'baseline.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):store.submit(dict(request_key='first',revision=0,records=[self.item()]),None)
        self.assertEqual(store._state(self.db)[1],[])

    def test_explicit_prospective_amend_can_remove_wrong_candidate_without_erasing_history(self):
        baseline,f,store=self.prepare();f['operation_contract']['parameters']['allow_baseline_amend']=True
        self.save(f);store=records.Store(f,self.db)
        self.assertEqual(store.progress()['committed'],2)
        old=store._state(self.db)[1][0];self.assertEqual(len(old['options']),1)
        replacement=self.item(count=0);replacement['gap']='Candidate removed because the selected variant is unsupported; needs independent review.'
        store.amend(dict(request_key='correct',revision=0,expected_record_sha256=contracts.digest(old),record=replacement),None)
        self.assertEqual(store.document(store._state(self.db)[1])['items'][0]['options'],[])
        preserved=json.loads(self.db.execute('SELECT value FROM operation_record_versions WHERE attempt=?',('recovery',)).fetchone()[0])
        self.assertEqual(preserved,old)
        self.assertEqual(json.loads((self.root/'baseline.json').read_text()),baseline)

    def test_export_allowance_is_contract_owned_and_plain_workers_stay_bounded(self):
        _,f,_=self.prepare()
        self.assertEqual(executors.limits_for(f['backend'],f)['output_bytes'],4000000)
        plain=copy.deepcopy(f);plain.pop('operation_contract')
        self.assertEqual(executors.limits_for(f['backend'],plain)['output_bytes'],200000)
        self.assertEqual(executors.limits_for(self.frozen['backend'],self.frozen)['output_bytes'],200000)


class CompilerTests(unittest.TestCase):
    def fixture(self):
        inv=dict(artifact='inventory',sha256='a'*64,content_contract=dict(id='sourcing.inventory',version=1))
        source=dict(artifact='base-source',sha256='b'*64,bytes=100,path='base.json',purpose='Evidence',authority='Evidence',media_type='application/json')
        cat=dict(artifact='catalog',sha256='c'*64,bytes=100,path='catalog.json',purpose='Sealed catalog',authority='Evidence',media_type='application/json')
        p=dict(inventory_path='inventory.json',source_pack_path='base.json',max_records=2,summary_path='schedule.md',options_per_item=3,count_policy='target')
        catalog=dict(contract=dict(id='sourcing.options',version=1),parameters=p,source_versions=dict(inventory_sha256='a'*64,source_pack_sha256='b'*64),records=[],items=[],complete=True)
        documents={'base-source':dict(version=1,entries=[]),'catalog':catalog}
        scope=dict(connector_companions_version=1,sourcing_count_policy='target',completion_recovery=dict(gaps=[dict(kind='consumer_coverage')]),
            pipeline_step=dict(handoff=dict(outputs={'catalog':dict(content_contract=dict(id='sourcing.options',version=1))})),
            input_ports={'upstream.items':inv},sources=[source,cat],options=dict(limits=dict(output_bytes=10000000)))
        search=dict(id='search',execution=dict(capability='web.sources.prepared'),outputs=[dict(path='pack.json')],limits=dict(output_bytes=2000000))
        author=dict(id='author',inputs=[dict(artifact='inventory',path='inventory.json'),{k:source[k] for k in ('artifact','path','purpose','authority','media_type')},dict(from_task='search',output='pack.json',path='new.json')],outputs=[dict(path='options.json'),dict(path='schedule.md')],limits=dict(output_bytes=200000),instruction='Author')
        review=dict(id='review',review_of='author',inputs=[],dependencies=['author'])
        plan=dict(tasks=[search,author,review]);coverage={'catalog':dict(task='author',output='options.json'),'evidence':dict(task='search',output='pack.json')}
        return plan,scope,coverage,{s['artifact']:s for s in [source,cat]},documents

    def test_compiles_ports_and_exact_sealed_baseline_without_new_tasks_or_calls(self):
        plan,scope,coverage,known,documents=self.fixture()
        receipts=sourcing_recovery.bind(plan,scope,coverage,known,lambda s:documents[s['artifact']])
        author=plan['tasks'][1]
        self.assertEqual(author['sourcing']['count_policy'],'target')
        self.assertEqual(author['sourcing_composition']['base_catalog_path'],'catalog.json')
        self.assertEqual(coverage['evidence'],dict(task='author',output='pack.json'))
        self.assertEqual(len(plan['tasks']),3)
        self.assertGreater(author['limits']['output_bytes'],2000000)
        self.assertEqual(receipts[0]['provider_calls'],0)

    def test_ambiguity_or_frozen_output_budget_cannot_be_silently_bypassed(self):
        for kind in ('unsealed','count-policy','budget'):
            plan,scope,coverage,known,documents=self.fixture()
            if kind=='unsealed':documents['catalog']['complete']=False
            if kind=='count-policy':scope['sourcing_count_policy']='required'
            if kind=='budget':scope['options']['limits']['output_bytes']=200000
            with self.subTest(kind=kind),self.assertRaises(ValueError):sourcing_recovery.bind(plan,scope,coverage,known,lambda s:documents[s['artifact']])

    def test_review_receipt_becomes_dependency_and_never_a_query_argument(self):
        query=dict(id='query',outputs=[dict(path='query.json')])
        review=dict(id='review',review_of='query',outputs=[dict(path='review.md')])
        argument=dict(from_task='query',output='query.json',media_type='application/json')
        receipt=dict(from_task='review',output='review.md',media_type='text/markdown')
        search=dict(id='search',execution=dict(capability='web.sources.prepared'),inputs=[argument,receipt],dependencies=['query'])
        scope=dict(connector_companions_version=1,graph_operations=[dict(id='web.sources.prepared',min_inputs=1,max_inputs=1,input_types=['application/json'])])
        self.assertEqual(len(preparation_reviews.bind_arguments(dict(tasks=[query,review,search]),scope)),1)
        self.assertEqual(search['inputs'],[argument]);self.assertIn('review',search['dependencies'])
        self.assertEqual(preparation_reviews.bind_arguments(dict(tasks=[query,review,search]),scope),[])
