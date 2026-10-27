"""Real compiler/record/render handoffs; scripted pages, pixels and judgments only."""
import copy,json,zipfile
from pathlib import Path
from unittest.mock import patch
from orchestrator import job_owner,operation_contracts as c
from orchestrator.operation_records import Store
from orchestrator.runtime import Runtime
from tests.test_discovery_failed_lifecycle import DiscoveryFailed
from tests.test_visual_selection_lifecycle import VisualPath
from tests.test_correction_handoff_lifecycle import Fixtures
from tests.test_image_sources import photo

class AcquisitionRender(DiscoveryFailed):
    def capture(self,text,name):
        import hashlib
        source=json.loads(text);source.update(version=1,kind='public_source_candidates');p=source['entries'][0]['pages'][0]
        p.update(title='Synthetic listing',text='Synthetic listing; buying details not captured.',products=[],images=[])
        for n in range(6):p['products'].append(dict(name='Design '+str(n),url='https://public.example/design-'+str(n)))
        p['sha256']=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
        source['entries']=[source['entries'][0]]
        source['entries'][0]['grounding']=[dict(url='https://public.example/listing',title='Listing')]
        return Fixtures.capture(self,json.dumps(source),name)

    def setUp(self):
        create=job_owner.create
        def qualified(rt,run,request,backend,inputs,grant,**kw):
            grant['operations'].append('web.sources.rendered')
            return create(rt,run,request,backend,inputs,grant,**kw)
        with patch.object(job_owner,'create',side_effect=qualified):super().setUp()
        self.initial=copy.deepcopy(self.grant)

    def initial_catalog(self):
        if hasattr(self,'inventory_preflight'):self.inventory_preflight()
        source=json.loads(Path(self.rt.artifact(self.pack['artifact'])['blob']).read_text())
        # Remove fixture pixels before acquisition. Observed listing names and
        # product links survive; the permitted reader must actually be dispatched.
        raw_page=source['entries'][0]['pages'][0]
        raw_page['images']=[]
        source['entries'][0]['grounding']=[dict(url='https://public.example/listing',title='Listing')]
        empty=self.pack
        self.submit('acquire',[dict(id='acquire',objective='Acquire candidate pixels from retained literal links',
            operation='web.sources.rendered',data={'artifact':empty['artifact']},parameters=dict(domains=[],max_pages=2))])
        calls=[]
        def rendered(url,*_):
            calls.append(url);p=copy.deepcopy(raw_page);p.update(url=url,requested_url=url,capture_method='isolated-rendered-dom')
            if url.endswith('/listing'):
                p['products']=[];p['links']=['https://public.example/products/pool']
            else:
                p['images']=[dict(url='https://images.example/product.jpg',basis='observed-product-jsonld',product_names=['Design '+str(n)]) for n in range(6)]
            return p
        with patch('task_relay.source_browser.render',side_effect=rendered),patch('task_relay.source_browser.read_http',side_effect=rendered):self.native('acquire')
        acquired=self.artifact('acquire','delivery/source-pack.json')
        self.assertEqual(len(calls),2)
        captured=json.loads(Path(acquired['blob']).read_text());self.assertEqual(captured['entries'][:1],source['entries'])
        self.pack={'artifact':acquired['id']}
        self.submit('pool',[dict(id='pool',objective='Retain acquired discovery pixels before catalog',operation='images.products',parameters=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path=None,source_pack_path=self.pack,count_policy='target'))])
        with patch('orchestrator.image_sources.download',return_value=(photo(),'image/jpeg','https://images.example/product.jpg')):self.native('pool')
        self.photos=self.artifact('pool','outputs/result.zip')
        from orchestrator.discovery_evidence import observations
        leads={v['result']['text']:v['id'] for v in observations(captured) if v['result']['images']}
        self.assertEqual(len(leads),6)
        def fragment(subject):
            return dict(item=subject['id'],gap='Explicit target gap',options=[dict(observation=leads['Design '+str(n)],fields={k:dict(status='observed',start=0,end=len('Design '+str(n))) if k==self.h.config['identity'] else dict(status='unknown',reason='Unverified buying detail') for k in self.h.config['fields']},comparison='Synthetic visual lead') for n in range(6)] if subject['id']==self.h.inventory['items'][0]['id'] else [])
        self.h.fragment=fragment
        return VisualPath.initial_catalog(self)

    def artifact(self,task,path='outputs/result.json'):
        if task=='final_compose' and getattr(self,'corrected_document',None):return self.corrected_document
        return super().artifact(task,path)

    def native(self,ident):
        from orchestrator import step_runner
        self.rt.tick('job');session=self.factory.sessions[self.rt.task('job',ident)['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
        result=step_runner.execute(session['frozen'],control);self.assertEqual(result['outcome'],'completed')
        session['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[],operation=result)
        self.rt.tick('job')
        if ident!='final_compose':return result
        # This point is AFTER actual independent rejection in Complete's path.
        baseline=super().artifact('final_compose');original=Path(baseline['blob']).read_bytes()
        prior=self.artifact('deck','outputs/result.pptx')
        inputs=[{'artifact':self.photos['id']},{'artifact':prior['id']}]
        def delegate(name,base):
            self.submit(name,[dict(id=name,objective='Correct saved sections, preserve all unaffected pages and pixels',inputs=inputs,
                work=dict(operation='pptx.create',mode='revise',baseline={'artifact':base['id']},parameters={},content_parameters=dict(max_records=40)))])
        delegate('section_checkpoint',baseline)
        f=self.factory.sessions[self.rt.task('job','section_checkpoint')['latest']]['frozen']
        store=Store(f);self.assertEqual(store.progress()['revision'],0)
        with store.connection(write=False) as db:_,records=store._state(db)
        replacement=dict(kind='page',slot=1,layout='text',content=dict(title='Preserved correction',body='Unknown buying details remain disclosed; ten subjects have explicit target gaps.'),notes='Scripted independent finding addressed')
        self.run_steps('section_checkpoint',lambda f:[('operation_amend',dict(request_key='saved',revision=0,expected_record_sha256=c.digest(records[0]),record=replacement))],decision='blocked')
        checkpoint=super().artifact('section_checkpoint','outputs/work-content.json')
        self.assertEqual(self.rt.task('job','section_checkpoint')['status'],'blocked')
        from orchestrator.document_authoring import check_inputs
        consumer=dict(id='check_checkpoint',execution=dict(capability='pptx.create'),inputs=[dict(artifact=checkpoint['id'],media_type='application/json')])
        check_inputs([consumer],self.session())
        pending=Path(self.factory.sessions[checkpoint['attempt']]['session']['control'])/'work-operations'/'pending-proof'
        pending.mkdir(parents=True);(pending/'intent.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'unresolved operation'):check_inputs([consumer],self.session())
        (pending/'intent.json').unlink();pending.rmdir()
        # A confirmed checkpoint is reusable; an uncertain attempt is not.
        with self.rt.transaction():self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(checkpoint['attempt'],))
        with self.assertRaisesRegex(ValueError,'uncertain'):check_inputs([consumer],self.session())
        with self.rt.transaction():self.rt.db.execute("UPDATE production_attempts SET state='blocked' WHERE id=?",(checkpoint['attempt'],))
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        delegate('section_continue',checkpoint)
        f=self.factory.sessions[self.rt.task('job','section_continue')['latest']]['frozen']
        store=Store(f);self.assertEqual(store.progress()['revision'],0)
        with store.connection(write=False) as db:_,records=store._state(db)
        seeded=store.document(records);self.assertIn('Preserved correction',json.dumps(seeded))
        self.assertEqual(seeded['slides'][1:],json.loads(Path(checkpoint['blob']).read_text())['slides'][1:])
        replacement['content']['body']+=' Fresh continuation completes the remaining correction.'
        count=len(seeded['slides'])
        actions=[('operation_amend',dict(request_key='remaining',revision=0,expected_record_sha256=c.digest(records[0]),record=replacement)),
            ('work_run',dict(step='build',request_key='build')),('work_run',dict(step='inspect',request_key='inspect'))]
        actions += [('image_view',dict(path='outputs/work-inspect/slide-previews.zip',members=[f'slide-{n:03d}.png' for n in range(start,min(start+4,count+1))])) for start in range(1,count+1,4)]
        with patch('task_relay.presentation_host.invoke',side_effect=self.fake_renderer):self.run_steps('section_continue',lambda f:actions)
        self.corrected_document=super().artifact('section_continue','outputs/work-content.json')
        self.assertIn('Fresh continuation',Path(self.corrected_document['blob']).read_text())
        self.assertEqual(Path(baseline['blob']).read_bytes(),original)
        reviewer=next(t['id'] for t in self.rt.status('job')['tasks'] if self.rt.spec(t).get('review_of')=='section_continue')
        def inspect(f):
            actions=[]
            for item in f['inputs']:
                if item.get('media_type')=='application/zip':
                    with zipfile.ZipFile(Path(f['workspace'])/item['path']) as z:members=[p for p in z.namelist() if p.endswith(('.png','.jpg','.jpeg'))]
                    actions += [('image_view',dict(path=item['path'],members=members[n:n+8])) for n in range(0,len(members),8)]
            return actions
        self.run_steps(reviewer,inspect,decision='accept')
        self.assertEqual(self.rt.task('job','section_continue')['status'],'completed')
        # Full independent re-review is subsequently executed by the inherited
        # final_deck/final_review path on this exact typed corrected projection.
        return result

    def test_acquisition_failed_saved_section_restart_render_rereview_partial(self):
        self.test_discovery_deferred_inventory_failed_corrections_full_path()

class Plants(AcquisitionRender):schema='plants'
class Components(AcquisitionRender):schema='components'
