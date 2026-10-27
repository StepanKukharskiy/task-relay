"""Deferred inventory, discovery pixels, failed corrections and exact re-review."""
import copy,hashlib,json,zipfile
from pathlib import Path
from unittest.mock import patch
from tests.test_failed_compiled_lifecycle import FailedCompiled
from tests.test_visual_selection_lifecycle import VisualPath
from tests.test_correction_handoff_lifecycle import Fixtures
from tests.test_image_sources import photo
from tests.test_owner_intents import worker

class DiscoveryFailed(FailedCompiled):
    def setUp(self):
        from tests import test_correction_handoff_lifecycle as chain
        harness=chain.Harness
        def subjects(*a,**kw):
            h=harness(*a,**kw)
            ids={i['id']:f'SUB-{n+1:03d}' for n,i in enumerate(h.inventory['items'])}
            for i in h.inventory['items']:i['id']=ids[i['id']]
            for e in h.pack['entries']:e['target_ids']=[ids[x] for x in e['target_ids']]
            return h
        with patch.object(chain,'Harness',side_effect=subjects):super().setUp()
        self.params['max_records']=40

    def capture(self,text,name):
        pack=json.loads(text);page=pack['entries'][0]['pages'][0]
        page.update(title='Synthetic listing',text='Synthetic listing; buying details not captured.',products=[],images=[])
        for n in range(6):
            title='Design '+str(n);page['products'].append(dict(name=title,url='https://public.example/design-'+str(n)))
            page['images'].append(dict(url='https://images.example/product.jpg',basis='observed-product-jsonld',product_names=[title]))
        page['sha256']=hashlib.sha256(json.dumps(page,sort_keys=True).encode()).hexdigest()
        pack['entries']=[pack['entries'][0]]
        return Fixtures.capture(self,json.dumps(pack,indent=2),name)

    def initial_catalog(self):
        # Actual registered image operation, before ANY catalog or selection.
        self.submit('pool',[dict(id='pool',objective='Inspect discovery images before catalog',operation='images.products',parameters=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path=None,source_pack_path={'artifact':self.pack['artifact']},count_policy='target'))])
        with patch('orchestrator.image_sources.download',return_value=(photo(),'image/jpeg','https://images.example/product.jpg')):self.native('pool')
        self.photos=self.artifact('pool','outputs/result.zip')
        with zipfile.ZipFile(self.photos['blob']) as z:m=json.loads(z.read('manifest.json'))
        self.assertEqual(m['coverage']['found'],6);self.assertIsNone(m['source_catalog_sha256'])
        def fragment(subject):
            return dict(item=subject['id'],gap='Explicit target gap',options=[dict(observation='lead-0-0-'+str(n),fields={k:dict(status='observed',start=0,end=len('Design '+str(n))) if k==self.h.config['identity'] else dict(status='unknown',reason='Unverified buying detail') for k in self.h.config['fields']},comparison='Synthetic visual lead') for n in range(6)] if subject['id']==self.h.inventory['items'][0]['id'] else [])
        self.h.fragment=fragment
        base,value=super().initial_catalog()
        self.assertEqual(json.loads(Path(base['blob']).read_text())['parameters']['max_records'],40)
        return base,value

    def submit(self,key,tasks):
        if key!='initial':return super().submit(key,tasks)
        original=self.rt.artifact(self.inv['artifact']);raw=Path(original['blob']).read_text()
        copy_task=dict(id='deferred_inventory',objective='Extract exact synthetic subject inventory',content=dict(family='collection.subjects',sources=dict(source_path={'artifact':self.inv['artifact']}),parameters=dict(max_records=11,fields=[])))
        tasks[0]['content']['sources']['inventory_path']=dict(task='deferred_inventory',output='result')
        super().submit(key,[copy_task,*tasks])
        records=[dict(kind='item',slot=n+1,label=i['label'],attributes={},quote=i['label'],bbox=None,notes='Synthetic source') for n,i in enumerate(self.h.inventory['items'])]+[dict(kind='end',count=11,notes='Complete synthetic inventory')]
        VisualPath.run_worker(self,'deferred_inventory',lambda f:[('operation_submit',dict(request_key='subject'+str(n),revision=n,records=[v])) for n,v in enumerate(records)])
        rid=next(t['id'] for t in self.rt.status('job')['tasks'] if self.rt.spec(t).get('review_of')=='deferred_inventory')
        VisualPath.run_worker(self,rid,lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs'] if i.get('media_type')=='application/json']+[('file_write',dict(path=f['outputs'][0]['path'],text='Exact synthetic inventory compared; supported.'))],decision='accept')
        a=self.artifact('deferred_inventory');observed=json.loads(Path(a['blob']).read_text())
        self.assertEqual([i['id'] for i in observed['items']],[i['id'] for i in self.h.inventory['items']]);self.h.inventory=observed
        self.inv=dict(artifact=a['id'])

    def run_worker(self,ident,steps,decision='delivered'):
        if ident!='initial':return super().run_worker(ident,steps,decision)
        chunks=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id'].startswith('initial_batch_') and not self.rt.spec(t).get('review_of')]
        self.assertEqual(len(chunks),4) # Deferred inventory retains its declared bound.
        for chunk in chunks:
            bounds=chunk['operation_contract']['parameters']['record_range']
            self.assertEqual(chunk['operation_contract']['parameters']['max_records'],40)
            def actions(f):
                calls=steps(f) if bounds[0]==0 else []
                for n in range(max(1,bounds[0]),min(11,bounds[1])):calls.append(('operation_submit',dict(request_key='gap'+str(n),revision=len(calls),records=[dict(item=self.h.inventory['items'][n]['id'],options=[],gap='Honest target shortfall')])) )
                return calls
            VisualPath.run_worker(self,chunk['id'],actions,decision);VisualPath.review(self,chunk['id'])
        self.native(ident)

    def test_discovery_deferred_inventory_failed_corrections_full_path(self):
        self.test_failed_corrections_full_compiler_to_rereview_partial()
        final=json.loads(Path(self.artifact('final_repair')['blob']).read_text())
        self.assertEqual(final['parameters']['max_records'],40)
        self.assertEqual([i['coverage']['suitable'] for i in final['items']],[3]+[0]*10)

class Plants(DiscoveryFailed):schema='plants'
class Components(DiscoveryFailed):schema='components'
