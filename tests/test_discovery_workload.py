"""Shared ceiling preservation and discovery pixels, with synthetic evidence."""
import copy,json,unittest
import hashlib,io,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch
from tests.test_record_transfer_compiler import Admission

class Workload(Admission):
    def test_declared_ceiling_survives_resolved_workload_and_no_empty_partitions(self):
        refs,task=self.content(11)
        task['content']['parameters']['max_records']=40
        self.grant['operations']=['records.merge'];self.grant['task_limits'].update(tool_calls=100,provider_requests=24)
        self.create(inputs=refs);self.rt.tick('job')
        self.session().delegate(dict(request_id='ceiling',tasks=[task]))
        chunks=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id'].startswith('collect_batch_') and not self.rt.spec(t).get('review_of')]
        self.assertEqual(len(chunks),2)
        for chunk in chunks:self.assertEqual(chunk['operation_contract']['parameters']['max_records'],40)
        self.assertEqual([c['operation_contract']['parameters']['record_range'] for c in chunks],[[0,10],[10,11]])

class Discovery(unittest.TestCase):
    def test_search_lead_and_listing_pixels_precede_catalog_without_buying_facts(self):
        from orchestrator import discovery_evidence as d,product_photos as photos,sourcing_contract as s
        from tests.test_universal_interfaces import Harness,CONFIGURATIONS
        from tests.test_image_sources import photo
        with tempfile.TemporaryDirectory() as root:
            h=Harness(root,CONFIGURATIONS['furniture']);self.addCleanup(h.db.close)
            listing=dict(url='https://shop.example/list',text='Collection',title='Collection',sha256='a'*64,
                products=[dict(name='Chair A',url='https://shop.example/a')],
                images=[dict(url='https://shop.example/a.jpg',basis='observed-product-jsonld',product_names=['Chair A'])])
            pack=dict(version=1,entries=[dict(query='chair',target_ids=['S0'],pages=[listing],grounding=[dict(title='Uncaptured Chair B',url='https://shop.example/b')])])
            inputs=[h.input('subjects.json',h.inventory),h.input('pool.json',pack)]
            f=dict(assignment_id='discovery',inputs=inputs,execution=dict(capability='images.products',parameters=dict(inventory_path='subjects.json',catalog_path=None,source_pack_path='pool.json',count_policy='target')),limits=dict(seconds=600,output_bytes=100000000))
            raw,manifest=photos.build(f,lambda p:(Path(root)/p).read_bytes(),fetch=lambda *a:(photo(),'image/jpeg','https://shop.example/a.jpg'))
            self.assertEqual(manifest['coverage'],dict(found=1,missing=1,total=2));self.assertIsNone(manifest['source_catalog_sha256'])
            a=manifest['discovery_pool']['leads'][0];self.assertEqual(a['discovery']['basis'],'captured-entity')
            b=manifest['discovery_pool']['leads'][1];self.assertEqual(b['discovery']['basis'],'search-title')
            assignment=h.assignment('select');assignment['inputs']=inputs;params=assignment['operation_contract']['parameters'];params.update(source_pack_path='pool.json',selection_policy='visual')
            ctx=s.context(assignment,lambda p:(Path(root)/p).read_bytes())
            def fragment(lead):return dict(item='S0',gap='Not selected yet',options=[dict(observation=lead['observation'],fields=dict(name=dict(status='observed',start=0,end=len(lead['text'])),price=dict(status='unknown',reason='Unverified'),dimensions=dict(status='unknown',reason='Unverified')),comparison='Visual lead only',selection=dict(status='provisional',design_id='a',reason='Inspect pixels',photo_sha256='',reference_sha256=''))])
            value=fragment(a);s.options_record(value,params,ctx);catalog=s.options_document([value],params,ctx)
            selected,binding=photos.retained_photo(catalog['items'][0]['options'][0],params,manifest,pack)
            self.assertEqual(selected['sha256'],hashlib.sha256(photo()).hexdigest());self.assertEqual(binding['source_page_sha256'],'a'*64)
            s.options_record(fragment(b),params,ctx)
            bad=fragment(b);bad['options'][0]['fields']['dimensions']=dict(status='observed',start=0,end=3)
            with self.assertRaisesRegex(ValueError,'buying details'):s.options_record(bad,params,ctx)
            wrong=copy.deepcopy(pack);wrong['entries'][0]['pages'][0]['sha256']='b'*64
            self.assertEqual(photos.retained_photo(catalog['items'][0]['options'][0],params,manifest,wrong),(None,None))
            self.assertEqual(len(d.observations(pack)),2)

    def test_pool_round_robin_and_no_product_url_or_image_invention(self):
        from orchestrator.discovery_evidence import pool,observations
        entries=[]
        for n in range(3):entries.append(dict(query='q'+str(n),target_ids=['s'+str(n)],pages=[],grounding=[dict(title='Lead '+str(j),url=f'https://example.org/{n}/{j}') for j in range(20)]))
        leads,coverage=pool(dict(entries=entries),6)
        self.assertEqual([l['target_ids'] for l in leads],[['s0'],['s1'],['s2']]*2)
        self.assertTrue(all(not l['images'] for l in leads));self.assertEqual(coverage['remaining_distinct_urls'],54)
        page=dict(url='https://example.org/category',text='Category',products=[dict(name='A'),dict(name='B')],images=[dict(url='https://example.org/ambiguous.jpg')])
        self.assertEqual(observations(dict(entries=[dict(pages=[page])])),[])
