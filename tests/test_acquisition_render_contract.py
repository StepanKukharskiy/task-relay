"""Synthetic retained pages, adaptive image reads and exact revision assets."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from orchestrator import source_fallback as source,layout_contract as layout,pptx_document,contracts
from tests.test_evidence_workload import pack,page

class Acquisition(unittest.TestCase):
    def test_follow_captured_product_link_within_same_read_bound_and_restart_without_replay(self):
        initial=pack([dict(query='chair',target_ids=['A'],pages=[],grounding=[dict(url='https://shop.example/list',title='Chairs')])])
        calls=[]
        def read(url,*_):
            calls.append(url);p=page(url,'Captured page')
            if url.endswith('/list'):p['links']=['https://shop.example/products/chair']
            else:p.update(title='Chair',images=[dict(url='https://shop.example/chair.jpg',basis='observed-img-element')])
            return p
        with tempfile.TemporaryDirectory() as root:
            raw,validation=source.collect(initial,[],2,root,read)
            out=json.loads(raw);self.assertEqual(len(calls),2)
            self.assertTrue(calls[-1].endswith('/products/chair'))
            self.assertEqual(validation['image_reference_coverage'],{'target:A':1})
            self.assertTrue(source.extends(initial,out))
            self.assertEqual(source.collect(initial,[],2,root,lambda *_:self.fail('No replay'))[0],raw)
            self.assertEqual(out['entries'][0],initial['entries'][0])

    def test_image_gaps_prioritized_without_treating_captures_as_suitability(self):
        a=page('https://a.example/one','A');a.update(images=[dict(url='https://a.example/one.png')])
        p=pack([dict(query='a',target_ids=['A'],pages=[a],grounding=[dict(url='https://a.example/two')]),
                dict(query='b',target_ids=['B'],pages=[page('https://b.example/one','B')],grounding=[dict(url='https://b.example/two')])])
        self.assertEqual(source.candidates(p,[])[0]['target_ids'],['B'])
        self.assertEqual(source.image_coverage(p),{'target:A':1,'target:B':0})

    def test_uncertain_adaptive_read_is_never_repeated(self):
        from orchestrator.runtime_outcomes import UncertainOperation
        p=pack([dict(query='x',pages=[],grounding=[dict(url='https://x.example/list')])])
        def read(url,*_):raise UncertainOperation('Missing receipt')
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(UncertainOperation):source.collect(p,[],2,root,read)
            with self.assertRaises(UncertainOperation):source.collect(p,[],2,root,lambda *_:self.fail('No replay'))

    def test_responsive_images_are_literal_observations_only(self):
        from task_relay.orchestrator_web import PageText
        p=PageText('https://shop.example/product')
        p.feed('<picture><source srcset="/a.webp 1x, /b.webp 2x"><img data-srcset="/c.jpg 640w" src="data:bad"></picture>')
        self.assertEqual([x['url'] for x in p.images],['https://shop.example/a.webp','https://shop.example/b.webp','https://shop.example/c.jpg'])

class Revision(unittest.TestCase):
    def test_saved_expanded_pages_survive_amendment_and_asset_aliases(self):
        from tests.test_image_sources import photo
        images={'old.jpg':photo()}
        base=dict(version=2,title='Original',style='clean_minimal_v1',slides=[
            dict(layout='text',content=dict(title='Wrong',body='Saved body'),notes='Original note'),
            dict(layout='image_grid',content=dict(title='Retained',items=[dict(image='old.jpg',label='Photo',caption='Unknown price',credit='Synthetic')],per_page=1,fit='contain'),notes='Exact pixels')])
        base=pptx_document.expand(base);base['asset_sha256']={'old.jpg':hashlib.sha256(photo()).hexdigest()}
        raw=json.dumps(base).encode();sha=hashlib.sha256(raw).hexdigest()
        params=dict(renderer='pptx.create',title='Corrected',style='clean_minimal_v1',max_records=40)
        f=dict(inputs=[dict(path='base.json',sha256=sha,media_type='application/json'),dict(path='new.jpg',sha256=hashlib.sha256(photo()).hexdigest(),media_type='image/jpeg')],
               operation_contract=dict(parameters=params),work_tools=dict(intent=dict(mode='revise',baseline='base.json')))
        ctx=layout.context(f,lambda p:raw if p=='base.json' else photo())
        store=SimpleNamespace(context=lambda:ctx,contract=dict(parameters=params))
        records=layout.initial_records(store);self.assertEqual(len(records),3)
        before=copy.deepcopy(records)
        records[0]=dict(kind='page',slot=1,layout='text',content=dict(title='Fixed',body='Corrected body; price unknown'),notes='Review finding addressed')
        result=layout.projection(store,records)
        self.assertEqual(result['slides'][1],ctx['baseline']['slides'][1])
        self.assertEqual(result['asset_sha256'],{'new.jpg':hashlib.sha256(photo()).hexdigest()})
        self.assertTrue(layout.complete(store,records));self.assertEqual(before[1],records[1])
        self.assertEqual(json.loads(raw),base)
        bad=copy.deepcopy(records);bad[1]['content']['page']=3
        with self.assertRaises(ValueError):layout.projection(store,bad)
        with self.assertRaisesRegex(ValueError,'version changed'):layout.context(f,lambda p:b'changed')
        self.assertEqual(layout.initial_records(SimpleNamespace(context=lambda:{})),[])

