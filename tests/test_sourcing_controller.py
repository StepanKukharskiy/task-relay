"""Synthetic exact-version composition, coverage and stop/restart boundaries."""
import copy,json,unittest
from unittest.mock import patch
from orchestrator import operation_contracts as c,sourcing_contract as sourcing,sourcing_merge,source_coverage
from tests import test_sourcing_records as fixture

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    input=fixture.Tests.input
    assignment=fixture.Tests.assignment
    save=fixture.Tests.save
    item=fixture.Tests.item
    option=fixture.Tests.option

    def merged(self,count=1):
        f=self.assignment('whole');p=f['operation_contract']['parameters'];ctx=sourcing.context(f,lambda path:(self.root/path).read_bytes())
        catalogs=[];reviews=[]
        for index,item in enumerate(ctx['inventory']):
            cp={**p,'record_range':[index,index+1]};part={**ctx,'inventory':{item:ctx['inventory'][item]}}
            doc=sourcing.options_document([self.item(item,count if index==0 else 0)],cp,part)
            path='parts/'+str(index)+'.json';ref=self.input(path,doc);f['inputs'].append(ref);catalogs.append(path)
            verdict=[dict(item=i['id'],item_sha256=c.digest(i),verdict='supported',reason='Supported supplied fields; explicit coverage gap is advisory.') for i in doc['items']]
            rd=sourcing.review_document(verdict,dict(inventory_path='inventory.json',source_pack_path='sources.json',catalog_path=path,max_records=2,summary_path='review.md',record_range=[index,index+1]),dict(items={i['id']:i for i in doc['items']},catalog_sha256=ref['sha256']))
            rpath='parts/'+str(index)+'-review.json';f['inputs'].append(self.input(rpath,rd));reviews.append(rpath)
        f['execution']=dict(capability='sourcing.merge',version=1,parameters=dict(inventory_path='inventory.json',source_pack_path='sources.json',max_records=2,options_per_item=3,count_policy='target',catalog_paths=catalogs,review_paths=reviews))
        raw,md,proof=sourcing_merge.build(f,lambda path:(self.root/path).read_bytes())
        return f,json.loads(raw),proof

    def test_zero_one_five_options_merge_without_invented_slots_and_changed_versions_are_held(self):
        for count in (0,1,5):
            with self.subTest(count=count):
                f,doc,proof=self.merged(count)
                self.assertTrue(doc['complete']);self.assertEqual(len(doc['items'][0]['options']),count)
                self.assertFalse(proof['acceptance']);self.assertEqual(len(proof['partitions']),2)
        target=self.root/f['execution']['parameters']['review_paths'][0]
        target.write_bytes(target.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'changed'):sourcing_merge.build(f,lambda path:(self.root/path).read_bytes())

    def test_unsupported_review_cannot_be_joined_as_supported(self):
        f,_,_=self.merged();path=f['execution']['parameters']['review_paths'][0]
        data=json.loads((self.root/path).read_text());data['records'][0]['verdict']='unsupported'
        f['inputs']=[i for i in f['inputs'] if i['path']!=path]+[self.input(path,data)]
        with self.assertRaisesRegex(ValueError,'Unsupported'):sourcing_merge.build(f,lambda path:(self.root/path).read_bytes())

    def test_coverage_uses_reviewed_priced_us_products_and_only_uncovered_subjects(self):
        _,catalog,_=self.merged(5)
        pack=copy.deepcopy(self.pack);pack['query_specification']=dict(data=dict(version=1,targets=[dict(id=i['id'],queries=[i['label']+' buying options'],required_options=3) for i in self.inventory['items']]))
        spec,states=source_coverage.specification(catalog,pack)
        self.assertEqual([t['id'] for t in spec['targets']],['item-b'])
        self.assertEqual(states[0]['supported_options'],5)
        self.assertIn('Pendant',spec['targets'][0]['queries'][0])
        for o in catalog['items'][0]['options']:o['fields']['us_context']=dict(status='unknown',reason='US purchase support absent')
        spec,_=source_coverage.specification(catalog,pack)
        self.assertEqual([t['id'] for t in spec['targets']],['item-a','item-b'])

    def test_coverage_diversifies_failed_publishers_without_expanding_allowlist(self):
        _,catalog,_=self.merged(0)
        pack=copy.deepcopy(self.pack)
        pack['query_specification']=dict(data=dict(version=1,targets=[dict(id=i['id'],queries=[i['label']+' below USD 200'],required_options=3) for i in self.inventory['items']]))
        pack['domains']=[]
        pack['entries']=[dict(query='initial',target_ids=['item-a'],retrievals=[dict(publisher='failed.example',outcome='failed')])]
        spec,_=source_coverage.specification(catalog,pack)
        self.assertIn('below USD 200 -site:failed.example',spec['targets'][0]['queries'][0])
        pack['domains']=['failed.example']
        spec,_=source_coverage.specification(catalog,pack)
        self.assertNotIn('-site:',spec['targets'][0]['queries'][0])

    def test_target_policy_changes_prospective_review_only_and_preserves_price_defects(self):
        from task_relay.sourcing_review_policy import bind
        producer=dict(id='p',criteria=['Three alternatives per item with correct prices'],instruction='Author')
        reviewer=dict(id='r',review_of='p',criteria=copy.deepcopy(producer['criteria']),instruction='Review')
        plan=dict(tasks=[producer,reviewer]);before=copy.deepcopy(plan)
        self.assertEqual(bind(plan,dict(connector_companions_version=1,sourcing_count_policy='required')),[])
        self.assertEqual(plan,before)
        receipts=bind(plan,dict(connector_companions_version=1,sourcing_count_policy='target'))
        self.assertEqual(producer['criteria'],reviewer['criteria']);self.assertEqual(len(receipts),2)
        self.assertIn('captured price',reviewer['criteria'][0]);self.assertIn('advisory',reviewer['criteria'][0])
