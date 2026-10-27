"""Offline amendment→photo projection and bounded owner recovery contracts."""
import copy,hashlib,io,json,os,shutil,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from orchestrator import working_context as ctx,product_photos,sourcing_slides,document_compose,pptx_document
from orchestrator import operation_contracts as c,job_owner
from orchestrator.gemini_worker import Files
from tests.test_universal_interfaces import Harness,CONFIGURATIONS
from tests.test_image_sources import photo
from tests import test_owner_context_retention as context_fixture
from tests.lifecycle_fixture import Lifecycle
from tests.test_owner_intents import worker
from tests.test_operation_session import Script


class PhotoLifecycle(unittest.TestCase):
    def fixture(self,config):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        h=Harness(tmp.name,config);self.addCleanup(h.db.close)
        page=h.pack['entries'][0]['pages'][0]
        page['images']=[dict(url='https://images.example/product.jpg',basis='observed-product-jsonld')]
        h.inputs[1]=h.input('sources.json',h.pack)
        store,base=h.produce('baseline');binding=h.input('catalog.json',base)
        f=dict(inputs=h.inputs+[binding],limits=dict(seconds=1800,output_bytes=100000000),execution=dict(capability='images.products',parameters=dict(inventory_path='subjects.json',catalog_path='catalog.json',source_pack_path='sources.json',count_policy='target')))
        calls=[]
        def fetch(url,*args):calls.append(url);return photo(),'image/jpeg',url
        raw,manifest=product_photos.build(f,lambda p:(h.root/p).read_bytes(),fetch=fetch)
        pb=h.input('photos.zip',{});(h.root/'photos.zip').write_bytes(raw);pb.update(media_type='application/zip',sha256=hashlib.sha256(raw).hexdigest())
        return h,store,base,pb,raw,manifest,calls

    def test_amend_twice_review_rebind_compose_and_pptx_preserve_pixels_and_gaps(self):
        for schema,config in CONFIGURATIONS.items():
            with self.subTest(schema=schema):
                h,store,base,pb,raw,manifest,calls=self.fixture(config)
                old=(h.root/'baseline.json').read_bytes();source=(h.root/'sources.json').read_bytes()
                for n in (1,2):
                    prior=json.loads((h.root/'baseline.json').read_text())['records'][0]
                    revised=copy.deepcopy(prior);revised['options'][0]['comparison']='Limited comparison, not acceptance; corrected finding '+str(n)
                    revised['gap']='Target 3, retained 1 provisional, gap 2; no purchasing approval.'
                    store.amend(dict(request_key='fix'+str(n),revision=store.progress()['revision'],expected_record_sha256=c.digest(prior),record=revised),{})
                    files=Files(store.frozen);store.export(files,complete=True);store.verify_export(files.read_bytes)
                    current=json.loads(files.read_bytes('baseline.json'));h.review('review'+str(n),current)
                    binding=h.input('current.json',current)
                    frozen=dict(inputs=h.inputs+[binding,pb],execution=dict(capability='collection.slides',parameters=dict(inventory_path='subjects.json',catalog_path='current.json',source_pack_path='sources.json',image_path=None,photos_path='photos.zip',title=schema,layout='readable')))
                    text,proof=sourcing_slides.build(frozen,lambda p:(h.root/p).read_bytes());doc=json.loads(text)
                    self.assertNotEqual(current['items'][0]['options'][0]['option_id'],base['items'][0]['options'][0]['option_id'])
                    self.assertEqual(proof['missing_photos'],[]);self.assertEqual(len(proof['photo_rebindings']),1)
                    section=h.input('section.json',doc)
                    compose=dict(inputs=[section,pb],execution=dict(capability='document.compose',parameters=dict(document_paths=['section.json'],image_paths=[],image_titles=[],title='Partial comparison')))
                    combined,_=document_compose.build(compose,lambda p:(h.root/p).read_bytes())
                    data,_=pptx_document.create(json.loads(combined),{},100000000,bundles={'photos.zip':raw})
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        pixels=[z.read(p) for p in z.namelist() if p.startswith('ppt/media/')]
                    self.assertIn(photo(),pixels);self.assertIn('gap 2',combined)
                    self.assertIn('not acceptance',combined)
                self.assertEqual(calls,['https://images.example/product.jpg'])
                self.assertEqual((h.root/'sources.json').read_bytes(),source)
                self.assertEqual((h.root/'photos.zip').read_bytes(),raw)
                self.assertNotEqual((h.root/'baseline.json').read_bytes(),old)
                target=os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE')
                if target:
                    h.db.commit();dest=Path(target)/(self.id()+'-'+schema);shutil.copytree(h.root,dest)
                    (dest/'composed.json').write_text(combined);(dest/'candidate.pptx').write_bytes(data)

    def test_foreign_variants_changed_pages_and_ambiguous_receipts_do_not_rebind(self):
        h,_,base,_,_,manifest,_=self.fixture(CONFIGURATIONS['plants'])
        option=copy.deepcopy(base['items'][0]['options'][0]);option['option_id']='new-version'
        def resolve(m,p=h.pack,o=option):return product_photos.retained_photo(o,base['parameters'],m,p)[0]
        self.assertIsNotNone(resolve(manifest))
        for key,value in [('source_url','https://public.example/foreign'),('observed_url','https://public.example/foreign'),('action_id','source-page:'+'f'*64),('download_url','https://images.example/decoy.jpg')]:
            changed=copy.deepcopy(manifest);changed['subjects'][0][key]=value;self.assertIsNone(resolve(changed),key)
        duplicate=copy.deepcopy(manifest);other=copy.deepcopy(duplicate['subjects'][0]);other['id']='different-id-same-bytes';duplicate['subjects'].append(other)
        self.assertIsNone(resolve(duplicate))
        changed=copy.deepcopy(h.pack);changed['entries'][0]['pages'][0]['sha256']='e'*64;self.assertIsNone(resolve(manifest,changed))
        changed=copy.deepcopy(h.pack);changed['entries'][0]['pages'][0]['products']=[{'name':'one'},{'name':'two'}];self.assertIsNone(resolve(manifest,changed))
        variant=copy.deepcopy(option);variant['product_url']+='?variant=other';self.assertIsNone(resolve(manifest,o=variant))
        commons=copy.deepcopy(manifest);commons['subjects'][0].pop('action_id');commons['subjects'][0]['catalog_subject_binding']={'option_id':'old','identity_policy':'subject'};self.assertIsNone(resolve(commons))


class ContextPaging(unittest.TestCase):
    group=context_fixture.ContextTests.group
    def test_exact_large_read_is_paged_for_all_transports_and_survives_restart(self):
        for provider in ('gemini','openai','openrouter','codex'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as root:
                view=ctx.WorkingView(Path(root),semantic=True)
                initial={'role':'user','parts':[{'text':'Exact scope'}]} if provider=='gemini' else {'role':'user','content':'Exact scope'}
                value={'artifacts':'escaped "\\ Ω '*14000,'operations':{'text.bundle':{'required':'exact'}}}
                chunk=self.group(provider,'job_catalog',{'operations':['text.bundle']},value,0);before=copy.deepcopy(chunk)
                projected=view.project([initial]+chunk,provider,version=2)
                self.assertLessEqual(ctx.size(projected),ctx.MAX_TEXT_BYTES);self.assertEqual(chunk,before)
                calls,results=ctx.exchanges(projected[1:]);self.assertEqual(calls,ctx.exchanges(chunk)[0])
                ref=results[0] if isinstance(results[0],dict) else json.loads(results[0])
                self.assertEqual(ref['representation'],'relay.tool-result-pages.v1')
                view=ctx.WorkingView(Path(root),semantic=True);parts=[];offset=0
                while offset is not None:
                    page=view.read({'context':ref['context'],'offset':offset});parts.append(page['text']);offset=page['next_offset']
                self.assertEqual(json.loads(''.join(parts)),value)
                section=next(f for f in ref['fields'] if f['field']=='operations')
                exact=view.read({'context':ref['context'],'offset':section['offset']})['text'][:section['characters']]
                self.assertEqual(json.loads(exact),value['operations'])
                self.assertEqual(json.loads((view.folder/(ref['raw_exchange']+'.json')).read_text()),chunk)
                (view.folder/(ref['context']+'.json')).write_text('{}')
                with self.assertRaisesRegex(ValueError,'changed'):view.read({'context':ref['context'],'offset':0})

    def test_no_effect_receipt_replay_or_paging_without_reader(self):
        with tempfile.TemporaryDirectory() as root:
            view=ctx.WorkingView(Path(root));initial=dict(role='user',content='Exact scope')
            for name,history in [('job_delegate',True),('job_complete',True),('job_history',True),('job_catalog',False)]:
                with self.subTest(tool=name):
                    chunk=self.group('codex',name,{},dict(evidence='x'*150000),1)
                    with self.assertRaisesRegex(ValueError,'Latest tool exchange exceeds'):view.project([initial]+chunk,'codex',version=2,history_available=history)
            with self.assertRaisesRegex(ValueError,'Required job state'):view.project([dict(role='user',content='x'*150000)],'codex',version=2)


class OwnerLifecycle(Lifecycle,unittest.TestCase):
    def test_large_catalog_then_correction_restart_review_and_partial_delivery(self):
        original=job_owner.Session._call;seen=[]
        original_request=Script.request
        def read_saved(script,endpoint,payload,**kwargs):
            last=payload['contents'][-1].get('parts',[{}])[0].get('functionResponse',{}).get('response',{})
            if isinstance(last,dict) and last.get('representation')=='relay.tool-result-pages.v1':
                script.requests.append(copy.deepcopy(payload))
                field=next(f for f in last['fields'] if f['field']!='large_saved_catalog')
                return dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(functionCall=dict(name='job_history',args=dict(context=last['context'],offset=field['offset'])))]))])
            return original_request(script,endpoint,payload,**kwargs)
        def large(session,name,args):
            value=original(session,name,args)
            if name=='job_catalog':value={**value,'large_saved_catalog':'"\\'*70000};seen.append(value)
            return value
        # Same real worker loop after the tool executes; only transport/model are scripted.
        with patch.object(job_owner.Session,'_call',large),patch.object(Script,'request',read_saved):
            result,script=self.invoke([('job_catalog',{}),('job_delegate',dict(request_id='initial',tasks=self.pair('v1',[{'artifact':self.evidence['artifact']},{'artifact':self.other['artifact']}])) )])
        self.assertEqual(result['outcome'],'yielded');self.assertEqual(len(seen),1)
        response=script.requests[1]['contents'][-1]['parts'][0]['functionResponse']['response']
        self.assertEqual(response['representation'],'relay.tool-result-pages.v1')
        restored=script.requests[2]['contents'][-1]['parts'][0]['functionResponse']
        self.assertEqual(restored['name'],'job_history');self.assertIn('text',restored['response'])
        self.rt.tick('job');self.work('v1','Price: 99. No gap disclosed.',collect=False)
        final=self.corrected(resume=True)
        self.delegate('uncertain',[worker('unknown')]);aid=self.rt.task('job','unknown')['latest']
        self.factory.sessions[aid]['status']=dict(status='uncertain',reason='No correlated receipt')
        self.rt.tick('job');self.export_partial(final)
        self.assertEqual(len(seen),1);self.invariants()
