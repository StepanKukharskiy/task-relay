"""Broad synthetic pool, observed pixels, visual shortlist and correction lifecycle.

Scripted judgments and six tiny fixture photos test contracts, not visual quality.
No network, live providers, native apps, generated media or paid APIs.
"""
import copy,hashlib,json,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from orchestrator import job_owner
from tests import test_complete_correction_path as complete
from tests import test_correction_handoff_lifecycle as chain
from tests.test_image_sources import photo


class VisualPath(complete.Complete):
    def run_steps(self,ident,steps,decision='delivered'):
        def observed(f):return [('image_view',dict(path=i['path'],members=[])) for i in f['inputs'] if i.get('media_type')=='image/png']+steps(f)
        return super().run_steps(ident,observed,decision)

    def setUp(self):
        create=job_owner.create
        def with_reference(rt,run,request,backend,inputs,*a,**kw):
            path=self.home/'reference.png';Image.new('RGB',(4,4),(30,50,90)).save(path)
            aid=rt.register(path,'Synthetic reference pixels')
            self.reference=dict(artifact=aid,path='prior/reference.png',media_type='image/png',purpose='Original visual benchmark',authority='Synthetic original')
            self.reference_hash=hashlib.sha256(path.read_bytes()).hexdigest()
            return create(rt,run,request,backend,[*inputs,self.reference],*a,**kw)
        with patch.object(job_owner,'create',side_effect=with_reference):super().setUp()
        self.params['selection_policy']='visual'

    def capture(self,text,name):
        pack=json.loads(text);entry=pack['entries'][0];pack['entries']=[]
        for n in range(6):
            e=copy.deepcopy(entry);p=e['pages'][0]
            p['url']+='-design-'+str(n);p['text']=p['text'].replace('S0 '+self.h.config['identity']+' 0','S0 '+self.h.config['identity']+' '+str(n))
            p['sha256']=hashlib.sha256(p['text'].encode()).hexdigest();pack['entries'].append(e)
        return super().capture(json.dumps(pack,indent=2),name)

    def content(self,ident,source,baseline=None):
        task=super().content(ident,source,baseline)
        task['inputs'].append({'artifact':self.reference['artifact']})
        if hasattr(self,'photos'):task['inputs'].append({'artifact':self.photos['id']})
        return task

    def run_worker(self,ident,steps,decision='delivered'):
        def observed(f):
            actions=[]
            for i in f['inputs']:
                if i.get('media_type')=='image/png':actions.append(('image_view',dict(path=i['path'],members=[])))
                if hasattr(self,'photos') and i.get('artifact')==self.photos['id']:
                    with zipfile.ZipFile(Path(f['workspace'])/i['path']) as z:members=[p for p in z.namelist() if p.startswith('images/')]
                    for n in range(0,len(members),4):actions.append(('image_view',dict(path=i['path'],members=members[n:n+4])))
            return actions+steps(f)
        return super().run_worker(ident,observed,decision)

    def initial_catalog(self):
        self.submit('initial',[self.content('initial',self.pack)])
        fragment=self.h.fragment(self.h.inventory['items'][0]);fragment['gap']='No visual assessment yet; buying details unknown.'
        for n,o in enumerate(fragment['options']):
            o['fields']={k:v if k==self.h.config['identity'] else dict(status='unknown',reason='Not verified; visual selection remains possible') for k,v in o['fields'].items()}
            o['selection']=dict(status='provisional',design_id='design-'+str(n),reason='Candidate lead awaiting visual comparison',photo_sha256='',reference_sha256='')
        self.run_worker('initial',lambda f:[('operation_submit',dict(request_key='pool',revision=0,records=[fragment]))]);self.review('initial')
        base=self.artifact('initial');doc=json.loads(Path(base['blob']).read_text())
        self.assertEqual(len(doc['items'][0]['options']),6);self.assertEqual(doc['items'][0]['shortfall'],3)
        return base,fragment

    def test_broad_pool_unknown_buying_three_visual_designs_restart_correct_review_partial(self):
        base,fragment=self.initial_catalog();before=Path(base['blob']).read_bytes()
        self.submit('photos',[dict(id='photos',objective='Retain broad pool images',operation='images.products',parameters=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path={'artifact':base['id']},source_pack_path={'artifact':self.pack['artifact']},count_policy='target'))])
        with patch('orchestrator.image_sources.download',return_value=(photo(),'image/jpeg','https://images.example/product.jpg')):self.native('photos')
        self.photos=self.artifact('photos','outputs/result.zip')
        with zipfile.ZipFile(self.photos['blob']) as z:manifest=json.loads(z.read('manifest.json'))
        self.assertEqual(manifest['coverage']['found'],6)
        revised=copy.deepcopy(fragment)
        for n,o in enumerate(revised['options']):
            o['selection']=dict(status='visually_suitable' if n<4 else 'provisional' if n==4 else 'excluded',
                design_id='design-'+str(n if n!=3 else 0),reason='Scripted assessment of exact candidate and benchmark pixels',
                photo_sha256=manifest['subjects'][n]['sha256'],reference_sha256=self.reference_hash)
        revised['gap']='Historical narrative says six options; typed count must override this stale prose.'
        corrected,pack=self.repair('repair',base,revised,self.pack)
        doc=json.loads(Path(corrected['blob']).read_text());self.assertEqual(doc['items'][0]['coverage'],dict(suitable=3,provisional=1,excluded=1,unavailable=0,shortfall=0))
        from orchestrator.runtime import Runtime
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        revised2=copy.deepcopy(revised);revised2['options'][0]['comparison']='Stale photo missing assertion retained only as historical editorial input.'
        final,retained=self.repair('repair_again',corrected,revised2,pack)
        self.assertEqual(Path(base['blob']).read_bytes(),before)
        self.submit('slides',[dict(id='slides',objective='Compose three visually suitable designs',operation='collection.slides',parameters=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path={'artifact':final['id']},source_pack_path={'artifact':retained['id']},photos_path={'artifact':self.photos['id']},image_path=None,title='Visual shortlist',layout='readable'))]);self.native('slides')
        slides=self.artifact('slides');spec=json.loads(Path(slides['blob']).read_text())
        self.assertIn('exact-retained-page-image',json.dumps(spec))
        from orchestrator.sourcing_slides import displayed_items
        self.assertEqual(len(displayed_items(json.loads(Path(final['blob']).read_text()))[0]['options']),3)
        self.submit('compose',[dict(id='compose',objective='Compose shortlist',operation='document.compose',parameters=dict(document_paths=[{'artifact':slides['id']}],image_paths=[],image_titles=[],title='Visual shortlist'),inputs=[{'artifact':self.photos['id']}])]);self.native('compose')
        self.submit('deck',[dict(id='deck',objective='Build shortlist',operation='pptx.create',data={'artifact':self.artifact('compose')['id']},inputs=[{'artifact':self.photos['id']}]),dict(id='deck_review',objective='Independently review all shortlist pages',review_of='deck')]);self.native('deck')
        deck=self.artifact('deck','outputs/result.pptx')
        with zipfile.ZipFile(deck['blob']) as z:self.assertIn(photo(),[z.read(p) for p in z.namelist() if p.startswith('ppt/media/')])
        self.finish_delivery(deck)
