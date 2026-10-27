"""Observed HTML metadata, conservative identity and native photo handoffs."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch
from PIL import Image
from task_relay.orchestrator_web import PageText
from orchestrator import page_identity, product_photos, image_sources, web_sources
from tests import test_typed_room_chain as room
from tests.test_image_sources import photo

class Tests(unittest.TestCase):
    def alias_page(self):
        parser=PageText('https://store.example/product/lamp')
        parser.feed('<script type="application/ld+json">'+json.dumps({'@graph':[
            {'@type':'Product','name':'Dome Lamp &#045; Store','sku':'LAMP-1','image':'/lamp.jpg','offers':{'url':'https://store.example/product/lamp'}},
            {'@type':'Product','name':'Dome Lamp','sku':'LAMP-1','url':'https://store.example/product/lamp'}]})+'</script>')
        return dict(url='https://store.example/product/lamp',sha256='a'*64,products=parser.products,images=parser.images)

    def test_same_explicit_identity_retains_images_through_discovery_and_download(self):
        from orchestrator import discovery_evidence,browser_images
        page=self.alias_page()
        self.assertEqual([i['url'] for i in product_photos.candidate_images(page,'Dome Lamp')],['https://store.example/lamp.jpg'])
        pack=dict(entries=[dict(query='dome lamp',target_ids=['S1'],pages=[page],grounding=[])])
        manifest,_,_=discovery_evidence.manifest(pack,40)
        calls=[]
        def fetch(url,*args):calls.append(url);return photo(),'image/jpeg',url
        raw,_=browser_images.fetch_bundle(manifest,fetch=fetch)
        _,_,saved=image_sources.unpack(raw)
        self.assertEqual(saved['coverage'],dict(found=1,missing=0,total=1))
        self.assertEqual(calls,['https://store.example/lamp.jpg'])
        self.assertEqual(saved['subjects'][0]['source_url'],page['url'])

    def test_shared_name_or_page_without_identity_does_not_alias(self):
        import copy
        original=self.alias_page()
        for change in ({'sku':'OTHER'},{'sku':''},{'productID':'P2'}):
            page=copy.deepcopy(original)
            # Parser walks @graph in reverse; selected short title is first.
            page['products'][0].update(change)
            if 'productID' in change:page['products'][1]['productID']='P1'
            self.assertEqual(product_photos.candidate_images(page,'Dome Lamp'),[])
        page=copy.deepcopy(original)
        page['products'].append(dict(name='Dome Lamp - Store',sku='UNRELATED'))
        self.assertEqual(product_photos.candidate_images(page,'Dome Lamp'),[])

    def test_shared_identifier_cannot_hide_variant_or_product_url_conflicts(self):
        import copy
        for key,a,b in [('color','green','red'),('size','small','large'),('material','wood','metal'),
                ('url','https://store.example/product/lamp?variant=one','https://store.example/product/lamp?variant=two')]:
            page=copy.deepcopy(self.alias_page());page['products'][0][key]=a;page['products'][1][key]=b
            self.assertEqual(product_photos.candidate_images(page,'Dome Lamp'),[])

    def test_registered_slide_review_capacity_matches_actual_projection_and_respects_scope(self):
        from orchestrator import sourcing_slides
        from task_relay import presentation_planning
        fixture=room.Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        task=fixture.assembler_fixture(5);task['id']='spec'
        read=lambda p:(fixture.root/p).read_bytes()
        raw,_=sourcing_slides.build(task,read);cost=sourcing_slides.review_workload(task,read)
        self.assertEqual(cost['slides'],len(json.loads(raw)['slides']))
        sources=[];texts=[]
        for item in task['inputs']:
            if item.get('media_type')!='application/json':continue
            data=read(item['path']);sources.append(dict(artifact=item['artifact'],bytes=len(data),sha256=hashlib.sha256(data).hexdigest()));texts.append(dict(artifact=item['artifact'],text=data.decode()))
        scope=dict(planner_budget_binding_version=2,sources=sources,source_texts=texts,options=dict(limits=dict(tool_calls=60,seconds=1800)))
        review=dict(id='review',review_of='spec',limits=dict(tool_calls=2,seconds=60));plan=dict(tasks=[task,review]);receipts=presentation_planning.budgets(plan,scope)
        self.assertEqual(review['limits']['tool_calls'],cost['slides']+6);self.assertTrue(receipts)
        plan['tasks'].append(dict(id='render',review_correction=dict(producer='spec',kind='sourcing_layout')))
        presentation_planning.budgets(plan,scope)
        task['execution']['parameters']['layout']='readable'
        corrected,_=sourcing_slides.build(task,read)
        self.assertEqual(review['limits']['tool_calls'],len(json.loads(corrected)['slides'])+6)
        self.assertEqual(review['limits']['seconds'],90+45*len(json.loads(corrected)['slides']))
        scope['options']['limits']['tool_calls']=2
        with self.assertRaisesRegex(ValueError,'frozen'):presentation_planning.budgets(plan,scope)
        texts[0]['text']='{}';review['limits']=dict(tool_calls=2,seconds=60)
        self.assertEqual(presentation_planning.budgets(plan,scope),[])

    def test_literal_product_metadata_is_retained_without_executing_scripts(self):
        parser=PageText('https://store.example/p/chair')
        parser.feed('<script>alert("untrusted")</script><meta property="og:image" content="/cover.jpg"><script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'Product','name':'Green chair','image':'/chair.avif','offers':{'price':'129','priceCurrency':'USD','availability':'https://schema.org/InStock'}}]})+'</script><p>Was $199. Current $129</p>')
        self.assertEqual(parser.products[0]['offers'][0]['price'],'129')
        self.assertEqual(parser.images[-1],dict(url='https://store.example/chair.avif',basis='observed-product-jsonld',product_names=['Green chair']))
        self.assertNotIn('alert',''.join(parser.parts))
        parser.feed('<script type="application/ld+json">{broken}</script>')
        self.assertEqual(len(parser.products),1)

    def test_multi_entity_capture_binds_images_to_literal_names_not_page_order(self):
        parser=PageText('https://store.example/catalog')
        products=[{'@type':'Product','name':name,'image':image} for name,image in [('Gray felt basket','/gray.jpg'),('Round, rattan basket','/round.jpg')]]
        parser.feed('<script type="application/ld+json">'+json.dumps({'@graph':products})+'</script>')
        page=dict(products=parser.products,images=parser.images)
        self.assertEqual([i['url'] for i in product_photos.candidate_images(page,'Round rattan basket\n')],['https://store.example/round.jpg'])
        self.assertEqual(product_photos.candidate_images(page,'Unknown basket'),[])
        legacy={**page,'images':[{k:v for k,v in i.items() if k!='product_names'} for i in parser.images]}
        self.assertEqual(product_photos.candidate_images(legacy,'Round rattan basket'),[])

    def test_tracking_association_preserves_variant_and_unknown_parameters(self):
        bare='https://store.example/p/chair?size=large'
        self.assertEqual(page_identity.association(bare+'&TCID=ad',bare)['basis'],'recorded-urls-tracking-only')
        self.assertIsNone(page_identity.association(bare,bare.replace('large','small')))
        self.assertIsNone(page_identity.association(bare,bare+'&unknown=1'))

    def test_prepared_category_followup_retains_literal_metadata_and_parent_capture(self):
        class Session:
            calls=[]
            def __init__(self,*_):pass
            def search(self,q):return dict(queries=[q],retrieved_at=1,sources=[dict(url='https://store.example/chairs')])
            def fetch(self,url,*_,**kwargs):
                self.calls.append(url)
                return dict(url=url,requested_url=url,title='Observed page',text='USD 129',retrieved_at=2,sha256='a'*64,content_type='text/html',total_characters=7,next_offset=None,
                    links=['https://store.example/products/chair'] if url.endswith('chairs') else [],products=[] if url.endswith('chairs') else [dict(name='Green chair')],images=[dict(url='https://store.example/chair.jpg',basis='observed-product-jsonld')])
        import tempfile
        spec=dict(path='queries.json',sha256='b'*64,data=dict(version=1,targets=[dict(id='F1',queries=['green chairs US'],required_options=3)]))
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.Session',Session):
            raw,_=web_sources.collect(['green chairs US'],['store.example'],'test',root,dict(models=dict(text='test')),prepared_spec=spec)
        pages=json.loads(raw)['entries'][0]['pages']
        self.assertEqual(Session.calls,['https://store.example/chairs','https://store.example/products/chair'])
        self.assertEqual(pages[1]['observed_link_from']['sha256'],'a'*64)
        self.assertEqual(pages[1]['products'][0]['name'],'Green chair')
        self.assertEqual(pages[1]['images'][0]['basis'],'observed-product-jsonld')

    def test_catalog_photo_connector_retains_exact_source_versions(self):
        fixture=room.Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        # Add metadata before authoring so the typed catalog freezes that pack.
        fixture.pack['entries'][0]['pages'][0]['images']=[dict(url='https://images.example/chair.jpg',basis='observed-product-jsonld')]
        fixture.pack['entries'][0]['pages'][0]['sha256']='a'*64
        fixture.inputs[1]=fixture.input('sources.json',fixture.pack)
        task=fixture.assembler_fixture(1)
        task.update(assignment_id='photo-test',limits=dict(seconds=30,output_bytes=5000000))
        task['execution']=dict(capability='images.products',version=1,parameters=dict(inventory_path='inventory.json',catalog_path='catalog.json',source_pack_path='sources.json',count_policy='target'))
        raw,m=product_photos.build(task,lambda p:(fixture.root/p).read_bytes(),fetch=lambda *args:(photo(),'image/jpeg','https://images.example/chair.jpg'))
        _,_,manifest=image_sources.unpack(raw)
        self.assertEqual(manifest['coverage'],dict(found=1,missing=0,total=1))
        self.assertEqual(manifest['source_catalog_sha256'],hashlib.sha256((fixture.root/'catalog.json').read_bytes()).hexdigest())
        self.assertEqual(manifest['subjects'][0]['id'],json.loads((fixture.root/'catalog.json').read_text())['items'][0]['options'][0]['option_id'])

    def test_static_avif_preserves_observed_bytes_and_decoded_pixels(self):
        from orchestrator import browser_images
        from tests.test_webp_photo_conversion import manifest
        b=io.BytesIO();Image.new('RGB',(140,120),(120,20,90)).save(b,format='AVIF');original=b.getvalue()
        raw,m=browser_images.fetch_bundle(manifest(),fetch=lambda *args:(original,'image/avif','https://example.com/chair.avif'))
        images,_,saved=image_sources.unpack(raw)
        subject=saved['subjects'][0]
        self.assertEqual(subject['source_original']['sha256'],hashlib.sha256(original).hexdigest())
        with Image.open(io.BytesIO(original)) as before,Image.open(io.BytesIO(images[subject['path']])) as after:
            self.assertEqual(before.convert('RGBA').tobytes(),after.convert('RGBA').tobytes())
