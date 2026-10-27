"""Normal desktop intake → typed stages → real local PPTX, with fake providers.

No upstream stage is marked complete by this harness. Every saved stage goes
through its planner, production controller, version-bound outputs and review.
Semantic/vision responses are deterministic seams, not live-quality evidence.
"""
import copy,hashlib,io,json,time,unittest,uuid,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from orchestrator import contracts as c,operation_records as records,operation_contracts,sourcing_contract,execution
from orchestrator.adapters import ExecutionFactory
from orchestrator.gemini_worker import Files
from orchestrator.step_runner import execute
from orchestrator.workers import atomic
from task_relay import desktop_plans,orchestrator_chat,pipelines,production_planning as planning,production_control as pc
from task_relay.relay_paths import Paths
from task_relay.workflow_usage import report as workflow_usage
from tests import test_delivery_completion as fixture
from tests.test_mixed_execution import LocalRegistered,Client
from tests.test_sourcing_records import BACKEND,CONFIG

TEXT='Walnut desk\nUSD Price $349.99\nWidth 120 cm\nShips to United States\nOrder online'

class SourceSession:
    queries=[]
    def __init__(self,receipt,*_):self.root=Path(receipt).with_suffix('')
    def search(self,query):
        self.queries.append(query)
        self.root.mkdir(parents=True,exist_ok=True)
        atomic(self.root/'search-0.json',dict(status='responded',response=dict(usageMetadata=dict(promptTokenCount=7,candidatesTokenCount=3,totalTokenCount=10))))
        return dict(queries=[query],retrieved_at=1,sources=[dict(url='https://store.example/products/desk')])
    def fetch(self,url,*_,**__):
        return dict(url=url,requested_url=url,title='Synthetic desk',text=TEXT,sha256='a'*64,retrieved_at=1,
                    content_type='text/html',total_characters=len(TEXT),next_offset=None,images=[],products=[],links=[])

class Native(LocalRegistered):
    def submit(self,session):
        control=Path(session['control']);self.calls.append(session['id'])
        with (control/'supervisor.claim').open('x') as stream:stream.write('controlled')
        launch=json.loads((control/'launch.json').read_text());f=json.loads((Path(launch['workspace'])/'.relay/ASSIGNMENT.json').read_text())
        try:details=execute(f,control,lambda _:self.client,lambda:CONFIG);code=0
        except Exception as exc:details=dict(error=str(exc));code=1
        atomic(control/'done.json',dict(token=session['id'],exit_code=code,reason=details.get('error'),usage=[details.get('usage',{})],tool_calls=0))
        return dict(submitted=True,fixture=True)

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    stage=fixture.Tests.stage
    step=fixture.Tests.step
    checkpoint_stop=False
    room_count=1

    def test_code_partitioned_room_reaches_delivery_with_exact_source_versions(self):
        self.room_count=12
        self.test_normal_desktop_chain_delivers_partial_pptx_with_current_composed_versions()

    def test_early_checkpoint_and_runtime_restart_still_deliver_without_new_prompt(self):
        self.checkpoint_stop=True
        self.test_normal_desktop_chain_delivers_partial_pptx_with_current_composed_versions()

    def author(self,ident,inputs,outputs,requires=None):
        return dict(id=ident,role='agent',objective='Controlled '+ident,instruction='Use the exact selected synthetic evidence',
            worker=dict(executor='gemini-agent',requires=requires or ['files.text']),inputs=inputs,outputs=outputs,
            dependencies=list(dict.fromkeys(i['from_task'] for i in inputs if 'from_task' in i)),
            criteria=['Preserve supported facts and explicitly disclosed gaps.'],limits=dict(seconds=600,tool_calls=24,provider_requests=24,response_tokens=4096,output_bytes=200000),max_attempts=2)

    def edge(self,task,output,path=None,mime='application/json'):
        return dict(from_task=task,output=output,path=path or 'upstream/'+task+'/'+output,purpose='Exact synthetic upstream output',authority='Unaccepted candidate',media_type=mime)

    def output(self,path,mime='application/json'):
        return dict(path=path,purpose='Controlled source-backed output',media_type=mime)

    def review(self,producer,extra=None):
        r=self.author(producer['id']+'_review',copy.deepcopy(producer['inputs'])+[self.edge(producer['id'],o['path'],mime=o['media_type']) for o in producer['outputs']],
            [self.output('review.md','text/markdown')],requires=producer.get('worker',{}).get('requires'))
        r.update(role='reviewer',review_of=producer['id'],criteria=copy.deepcopy(producer['criteria']))
        if extra:r['inputs'].extend(extra)
        return r

    def operation(self,ident,cap,params,inputs):
        spec=execution.REGISTRY[cap]
        path='deck.pptx' if cap=='pptx.create' else 'photos.zip' if cap=='images.products' else 'slides.json' if cap=='sourcing.slides' else 'delivery/source-pack.json'
        return dict(id=ident,role='procedure',objective='Controlled '+cap,instruction='Run exact registered operation',
            execution=dict(capability=cap,version=1,parameters=params),inputs=inputs,outputs=[self.output(path,spec['output_type'])],
            dependencies=list(dict.fromkeys(i['from_task'] for i in inputs if 'from_task' in i)),criteria=copy.deepcopy(spec['criteria']),
            limits=dict(seconds=min(600,spec['seconds']),tool_calls=1,output_bytes=spec['output_bytes']),max_attempts=1)

    def proposal(self,row,_context=None):
        ctx=json.loads(row['context']);stage=ctx['pipeline_step']['id'];sources=ctx['sources']
        image=next(s for s in sources if s.get('media_type')=='image/png')
        png={k:image[k] for k in ('artifact','path','purpose','authority','media_type')};png['visual_reference']=True
        if stage=='inventory':
            author=self.author('inventory',[png],[self.output('inventory.json'),self.output('inventory.md','text/markdown')],['files.text','images.view'])
            author['sourcing']=dict(version=2,kind='inventory',image=dict(source=png['artifact']),max_records=self.room_count)
            tasks=[author,self.review(author)];mapping=dict(inventory=dict(task='inventory',output='inventory.json'))
        elif stage=='catalog':
            inv=next(s for s in sources if s.get('workflow_artifact') and s['media_type']=='application/json')
            source={k:inv[k] for k in ('artifact','path','purpose','authority','media_type')}
            queries=self.author('queries',[source],[self.output('queries.json')]);qr=self.review(queries)
            search=self.operation('search','web.sources.prepared',dict(domains=['store.example'],model=CONFIG['models']['text']),[self.edge('queries','queries.json')]);search['dependencies'].append(qr['id']);sr=self.review(search)
            catalog=self.author('catalog',[source,self.edge('search','delivery/source-pack.json')],[self.output('catalog.json'),self.output('catalog.md','text/markdown')]);catalog['dependencies'].append(sr['id'])
            catalog['sourcing']=dict(version=1,inventory=dict(source=inv['artifact']),source_pack=dict(producer='search',output='delivery/source-pack.json'),max_records=self.room_count,options_per_item=3,count_policy='target')
            cr=self.review(catalog)
            inputs=[source,self.edge('catalog','catalog.json'),self.edge('search','delivery/source-pack.json')]
            photo=self.operation('photos','images.products',dict(inventory_path=source['path'],catalog_path=inputs[1]['path'],source_pack_path=inputs[2]['path'],count_policy='target'),inputs);photo['dependencies'].append(cr['id']);pr=self.review(photo)
            pr['worker']=dict(executor='codex-cli',requires=['files.binary','code.execute'])
            tasks=[queries,qr,search,sr,catalog,cr,photo,pr]
            mapping=dict(catalog=dict(task='catalog',output='catalog.json'),sources=dict(task='search',output='delivery/source-pack.json'),photos=dict(task='photos',output='photos.zip'))
        else:
            selected={}
            for handoff in ctx['handoff_sources']:
                port=ctx['input_ports'][handoff['stage']+'.'+handoff['deliverable']]
                s=next(s for s in sources if s['artifact']==port['artifact'])
                key=handoff['deliverable']
                selected[key]={k:s[k] for k in ('artifact','path','purpose','authority','media_type')}
            inputs=list(selected.values())+[{k:v for k,v in png.items() if k!='visual_reference'}]
            spec=self.operation('spec','sourcing.slides',dict(inventory_path=selected['inventory']['path'],catalog_path=selected['catalog']['path'],source_pack_path=selected['sources']['path'],image_path=png['path'],photos_path=selected['photos']['path'],title='Synthetic room sourcing',layout='standard'),inputs);sp=self.review(spec)
            sp['worker']=dict(executor='codex-cli',requires=['files.binary','code.execute','images.view'])
            # Presentation JSON paths reference the exact aliases selected above.
            deck=self.operation('deck','pptx.create',{},[self.edge('spec','slides.json')]+[i for i in inputs if i['media_type'] in ('image/png','application/zip')]);deck['dependencies'].append(sp['id']);dr=self.review(deck)
            dr['worker']=dict(executor='codex-cli',requires=['files.binary','code.execute','images.view'])
            tasks=[spec,sp,deck,dr];mapping=dict(finish=dict(task='deck',output='deck.pptx'))
        return c.encoded(dict(decision='ready',message='Controlled full chain',geometry_basis=dict(mode='procedural',artifacts=[],checks=[]),input_basis=dict(mode='new',artifacts=[]),plan=dict(brief='Controlled image to sourcing PPTX',tasks=tasks),deliverable_map=mapping)),dict(input_tokens=10,output_tokens=5)

    def complete_agent(self,aid):
        session=self.factory.sessions[aid];f=session['frozen'];ws=session['workspace'];contract=f.get('operation_contract',{}).get('id')
        if contract:
            store=records.Store(f,self.state.db);progress=store.progress()
            if contract=='sourcing.inventory':
                if progress['committed']==0:
                    for slot in range(1,self.room_count+1):
                        store.submit(dict(request_key='item-'+str(slot),revision=store.progress()['revision'],records=[dict(kind='item',slot=slot,label='Walnut desk',category='furniture',bbox=[.1,.1,.8,.8],confidence='medium',notes='Controlled visual response')]),None)
                    if self.checkpoint_stop:
                        store.export(Files(f));self._yielded=aid
                        (ws/'.relay/result.json').write_text(c.encoded(dict(summary='Saved one visual checkpoint',decision='blocked',instruction='Continue by sealing the observed inventory',
                            findings=[dict(category='execution',code='checkpoint_yield',message='Controlled local yield',evidence='One durable record; no pending external response')],checks={key:None for key in f['report_contract']['schema']['properties']['checks']['properties']})))
                        session['status']=dict(status='finished',exit_code=0,reason=None,api_requests=2,tool_calls=2,external_outcome='no_pending_response',pending_requests=[],usage=[dict(input_tokens=100)])
                        return
                store.submit(dict(request_key='end',revision=store.progress()['revision'],records=[dict(kind='end',count=self.room_count,notes='Controlled inventory')]),None)
            elif contract=='sourcing.options':
                ctx=store.sourcing_context();observation=next(iter(ctx['observations']))
                fields={k:dict(status='unknown',reason='Not established') for k in sourcing_contract.FIELDS}
                for key,quote in [('name_variant','Walnut desk'),('price','USD Price $349.99'),('dimensions','Width 120 cm'),('us_context','Ships to United States'),('order_terms','Order online')]:
                    start=ctx['observations'][observation]['text'].index(quote);fields[key]=dict(status='observed',start=start,end=start+len(quote))
                for item in ctx['inventory']:
                    store.submit(dict(request_key=item,revision=store.progress()['revision'],records=[dict(item=item,options=[dict(observation=observation,fields=fields,comparison='Controlled correspondence judgment')],gap='Only one verified synthetic option found')]),None)
            else:
                for item_id,item in store.sourcing_context()['items'].items():
                    store.submit(dict(request_key=item_id,revision=store.progress()['revision'],records=[dict(item=item_id,item_sha256=operation_contracts.digest(item),verdict='supported',reason='Accurate included facts and explicit advisory gap')]),None)
            store.export(Files(f),complete=True)
            data={o['path']:(ws/o['path']).read_bytes() for o in f['outputs']}
            self.factory.finish(aid,decision='accept' if f.get('review_of') else 'delivered')
            for path,raw in data.items():(ws/path).write_bytes(raw)
        else:
            self.factory.finish(aid,decision='accept' if f.get('review_of') else 'delivered')
            if f['id']=='queries':(ws/'queries.json').write_text(json.dumps(dict(version=1,targets=[dict(id='VIS-'+str(n).zfill(3),queries=['walnut desk US '+str(n)],required_options=3) for n in range(1,self.room_count+1)])))
        if f.get('final_quality'):
            from orchestrator.final_quality import DIMENSIONS
            result_path=ws/'.relay/result.json';result=json.loads(result_path.read_text())
            for number,binding in f['final_quality']['checks'].items():
                refs=[dict(path=p,location='Synthetic exact candidate and inspection companion') for p in
                    dict.fromkeys([binding['candidate'],*binding['inspection_inputs'],*[i['path'] for i in f['inputs'] if i.get('visual_reference')]])]
                evidence={d:dict(verdict='satisfied',reason='Scripted semantic judgment; structural integration only',inspected=refs) for d in DIMENSIONS}
                next(check for check in result['checks'] if check['criterion']==int(number))['evidence']=json.dumps(evidence)
            result_path.write_text(c.encoded(result));self._final_quality_seen=True
        session['status'].update(external_outcome='no_pending_response',pending_requests=[])

    def test_normal_desktop_chain_delivers_partial_pptx_with_current_composed_versions(self):
        from orchestrator import worker_capabilities
        from task_relay import gemini
        workers=[worker_capabilities.entry(self.state.get('production-planner-policy')['backend']),worker_capabilities.entry(BACKEND)]+getattr(self,'additional_workers',[])
        from task_relay import orchestrator_context
        # Only transports/semantic responses are fake; admission, compiler,
        # scheduler, native assembly and delivery are the real implementations.
        paths=Paths(Path(self.tmp.name)/'app',self.state.media_dir.parent,Path(self.tmp.name)/'projects',Path(self.tmp.name)/'generated')
        out=io.BytesIO();Image.new('RGB',(20,20),(90,110,130)).save(out,format='PNG');photo=Path(self.tmp.name)/'room.png';photo.write_bytes(out.getvalue())
        inv=self.stage('inventory',route='production');inv['research_mode']='none';inv['handoff']['outputs']['inventory']['media_type']='application/json'
        cat=self.stage('catalog',route='production',caps=['web.sources','images.products']);cat['research_mode']='sources';cat['deliverables']=dict(catalog='Reviewed catalog',sources='Exact catalog source pack',photos='Reviewed available product photos');cat['handoff']=dict(inputs=[dict(stage='inventory',deliverable='inventory',media_type='application/json',consumer='context')],outputs={k:dict(media_type='application/zip' if k=='photos' else 'application/json') for k in cat['deliverables']})
        final=self.stage('finish',route='production',caps=['pptx.create']);final['research_mode']='none';final['handoff']['outputs']['finish']['media_type']=execution.REGISTRY['pptx.create']['output_type'];final['handoff']['inputs']=[dict(stage=s,deliverable=d,media_type=m,consumer='context') for s,d,m in [('inventory','inventory','application/json'),('catalog','catalog','application/json'),('catalog','sources','application/json'),('catalog','photos','application/zip')]]
        action=dict(kind='plan_pipeline',contract_version=1,title='Synthetic full sourcing',planning_only=False,stages=[inv,cat,final],completion=dict(version=1,stage='finish',output='finish',coverage=dict(inventory=dict(stage='inventory',output='inventory'),catalog=dict(stage='catalog',output='catalog'),options_per_item=3,count_policy='target'),photos=dict(stage='catalog',output='photos',count_policy='target')))
        native=Native(Client());self.rt.factory=ExecutionFactory(getattr(self,'cli_factory',self.factory),native,self.factory)
        def render(url,*_):return SourceSession(Path(self.tmp.name)/'render').fetch(url)
        with patch.object(gemini,'read_config',return_value=CONFIG),patch.object(worker_capabilities,'capture',return_value=workers),patch('orchestrator.executors.available'),patch('orchestrator.executors.catalog',return_value=[dict(w,available=True) for w in workers]),patch('task_relay.orchestrator_web.Session',SourceSession),patch('task_relay.source_browser.render',side_effect=render),patch.object(execution,'available'):
            with self.state.db:self.state.put('health:desktop-plans',dict(interface_version=1,orchestrator_entry_version=1,last_success=time.time()))
            desktop_plans.create('Source this exact room image and deliver a PPTX without intermediate approvals. Best available alternatives and photo gaps are allowed.','',None,None,str(uuid.uuid4()),paths,files=[str(photo)],entry_mode='conversation',research_mode='sources')
            photo.write_bytes(b'Changed external source after the exact upload was recorded')
            desktop_plans.process_requests(self.state)
            from tests.intake_fixtures import work,outcome
            requested=outcome('finish',format='.pptx',checks=['nonempty']);requested['description']=final['deliverables']['finish']
            orchestrator_chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Saved full workflow',action=action,request_contract=work([requested])))).tick()
            p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone();self.assertIsNotNone(p)
            self.assertEqual(p['channel'],'desktop')
            worker=pc.Worker(self.state,lambda _:self.rt)
            for _ in range(100):
                if getattr(self,'cli_factory',None):time.sleep(.05)
                pipelines.tick(self.state)
                planning.Worker(self.state,self.proposal).tick()
                worker.tick()
                for aid,session in list(self.factory.sessions.items()):
                    if session['status']['status']=='running':self.complete_agent(aid)
                if getattr(self,'_yielded',None) and not getattr(self,'_restarted',False):
                    from orchestrator.runtime import Runtime
                    self.rt=Runtime(self.rt.root,self.rt.factory,connection=self.state.db)
                    worker=pc.Worker(self.state,lambda _:self.rt);self._restarted=True
                current=self.state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()
                if current['status'] in ('completed','blocked'):break
            self.assertEqual(current['status'],'completed',dict(plans=[dict(r) for r in self.state.db.execute('SELECT id,status,error FROM production_plans')],steps=[dict(s) for s in self.state.db.execute('SELECT id,status,error FROM relay_pipeline_steps')],events=[dict(e) for e in self.state.db.execute("SELECT task,kind,data FROM production_events WHERE kind LIKE '%block%' OR kind LIKE '%fail%'")],attempts=[dict(a) for a in self.state.db.execute("SELECT task,state,error,receipt FROM production_attempts WHERE state!='completed'")]))
            result=json.loads(self.step(p,'finish')['result']);artifact=self.rt.artifact(result['deliverables']['finish']['artifact'])
            with zipfile.ZipFile(artifact['blob']) as archive:
                text=''.join(archive.read(n).decode() for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml'))
                self.assertIn('349.99',text);self.assertIn('VIS-001',text)
            catalog=json.loads(self.step(p,'catalog')['result'])['deliverables']
            data=json.loads(Path(self.rt.artifact(catalog['catalog']['artifact'])['blob']).read_text())
            self.assertEqual(data['source_versions']['source_pack_sha256'],catalog['sources']['sha256'])
            self.assertEqual(len(data['items'][0]['options']),1)
            self.assertEqual(len(data['items']),self.room_count)
            if self.room_count>10:
                joins=self.state.db.execute("SELECT spec FROM production_assignments WHERE spec LIKE '%sourcing.merge%'").fetchall()
                self.assertTrue(any(json.loads(r[0]).get('execution',{}).get('capability')=='sourcing.merge' for r in joins))
            self.assertGreater(len(SourceSession.queries),1)
            measured=workflow_usage(self.state,p['id'])
            self.assertGreater(measured['totals']['input_tokens']['reported'],0)
            self.assertIsNotNone(measured['finished_at']);self.assertGreater(measured['elapsed_seconds'],0)
            native_reads=[r for r in measured['records'] if r['provider']=='gemini' and r['kind']=='worker' and r['counts']['input_tokens']==7]
            self.assertEqual(len(native_reads),2*self.room_count)
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
            self.assertTrue(self._final_quality_seen)
            if self.checkpoint_stop:
                self.assertTrue(self._restarted)
                attempts=self.state.db.execute("SELECT state FROM production_attempts WHERE task='inventory'").fetchall()
                self.assertEqual([a['state'] for a in attempts],['blocked','completed'])
