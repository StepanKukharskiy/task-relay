"""New worker amendment/export → real native admission/composition → partial files.

Only capture/process observations and model replies are fixtures. No network or
native GUI. Runtime, owner compiler, record workers, reviews and exports are real.
"""
import copy,hashlib,io,json,os,shutil,tempfile,unittest,zipfile
from pathlib import Path
from orchestrator import job_owner,operation_contracts as c,sourcing_contract,step_runner
from orchestrator.runtime import Runtime
from tests import test_owner_intents as owner
from tests import lifecycle_fixture as life
from tests.test_universal_interfaces import Harness,CONFIGURATIONS
from tests.test_image_sources import photo
from task_relay.external_evidence import recorded_sources

class Fixtures:
    source=owner.Tests.source;session=owner.Tests.session;invoke=owner.Tests.invoke;run_worker=owner.Tests.run_worker
    def setUp(self):
        from task_relay.bridge import State
        from task_relay import production_control
        from tests.test_orchestrator import FakeFactory
        self.home_tmp=tempfile.TemporaryDirectory();self.addCleanup(self.home_tmp.cleanup)
        self.home=Path(self.home_tmp.name).resolve();self.state=State(self.home/'state.sqlite')
        self.root=production_control.root(self.state);self.factory=FakeFactory()
        self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        self.addCleanup(self.state.db.close);self.addCleanup(lambda:self.rt.close())
        self.grant=life.grant();self.grant['operations']=['images.products','collection.slides','document.compose','pptx.create','pptx.render']
        self.grant['deliverables']={'deck':'application/vnd.openxmlformats-officedocument.presentationml.presentation','pdf':'application/pdf'}
        from orchestrator import worker_capabilities
        # Binary reviewer is admitted but never executed: its inspection stops uncertain.
        self.grant['workers'].append(worker_capabilities.entry(dict(type='gemini-code',model='fixture',runtime='a'*64)))
        self.initial=copy.deepcopy(self.grant)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.h=Harness(self.tmp.name,CONFIGURATIONS[self.schema]);self.addCleanup(self.h.db.close)
        page=self.h.pack['entries'][0]['pages'][0];page['images']=[dict(url='https://images.example/product.jpg',basis='observed-product-jsonld')]
        # Deliberately noncanonical native bytes, as in the live capture adapter.
        self.inv=self.source(json.dumps(self.h.inventory),'inventory.json','application/json')
        self.pack=self.capture(json.dumps(self.h.pack,indent=2),'original')
        fresh=copy.deepcopy(self.h.pack);fresh['entries'][0]['pages'][0]['url']='https://public.example/additional'
        self.extra=self.capture(json.dumps(fresh,indent=3),'additional')
        self.params=dict(options_per_item=3,count_policy='target',max_records=1,field_definitions=self.h.config['fields'],identity_field=self.h.config['identity'])
        job_owner.create(self.rt,'job','Correct the recorded claim, retain sources/photos, target 3; partial delivery authorized.',life.BACKEND,[self.inv,self.pack,self.extra],self.grant,concurrency=3);self.rt.tick('job')
    def tearDown(self):
        target=os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE')
        if target:
            self.rt.db.commit();self.rt.db.execute('PRAGMA wal_checkpoint(PASSIVE)');shutil.copytree(self.home,Path(target)/self.id())
    def capture(self,text,name):
        ref=self.source(text,name+'.json','application/json');a=self.rt.artifact(ref['artifact'])
        # Controlled upstream native receipt only; no invented downstream completion.
        frozen=dict(execution=dict(capability='web.sources'))
        receipt=dict(status='finished',pending_requests=[],operation=dict(output_sha256=a['sha256'],validation=dict(fetched=1)))
        with self.rt.transaction():
            self.rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',(name,'prior',name,name,'completed',None,json.dumps(frozen),'{}',json.dumps(receipt),None))
            self.rt.db.execute('UPDATE production_artifacts SET attempt=?,path=? WHERE id=?',(name,'delivery/source-pack.json',a['id']))
        return ref
    def submit(self,key,tasks):
        result,_=self.invoke([('job_delegate',dict(request_id=key,tasks=tasks))]);self.assertEqual(result['outcome'],'yielded');self.rt.tick('job')
    def content(self,ident,source,baseline=None):
        refs=[self.inv,source]+([baseline] if baseline else [])
        task=dict(id=ident,objective='Correct the claim, retain exact source identity and gaps. Version IDs may change.',inputs=[{'artifact':i['artifact'] if 'artifact' in i else i['id']} for i in refs],content=dict(family='collection.options',sources=dict(inventory_path={'artifact':self.inv['artifact']},source_pack_path={'artifact':source['artifact']}),parameters=copy.deepcopy(self.params)))
        if baseline:task['content']['baseline']={'artifact':baseline['id']}
        return task
    def artifact(self,task,path='outputs/result.json'):
        a=dict(self.rt.output('job',task,path));return dict(a,artifact=a['id'])
    def review(self,ident):
        rid=next(t['id'] for t in self.rt.status('job')['tasks'] if t['id'].startswith(ident+'_review'))
        f=self.factory.sessions[self.rt.task('job',rid)['latest']]['frozen']
        ctx=sourcing_contract.context(f,lambda p:(Path(f['workspace'])/p).read_bytes())
        judgments=[dict(item=k,item_sha256=c.digest(v),verdict='supported',reason='Scripted independent check of exact corrected record, saved sources and explicit gap') for k,v in ctx['items'].items()]
        self.run_worker(rid,lambda f:[('file_read',dict(path=f['operation_contract']['parameters']['catalog_path'],offset=0,limit=24000))]+[('operation_submit',dict(request_key='review'+str(n),revision=n,records=[v])) for n,v in enumerate(judgments)],decision='accept')
        self.assertEqual(self.rt.task('job',ident)['status'],'completed')
        self.assertEqual(f['review_target'],self.artifact(ident)['attempt'])
    def initial_catalog(self):
        self.submit('initial',[self.content('initial',self.pack)])
        fragment=self.h.fragment(self.h.inventory['items'][0]);self.run_worker('initial',lambda f:[('operation_submit',dict(request_key='one',revision=0,records=[fragment]))]);self.review('initial')
        return self.artifact('initial'),fragment
    def repair(self,ident,base,fragment,source,blocked=False):
        task=self.content(ident,source,base)
        # Actual correction compiler needs the exact ancestor pack even with new captures.
        old=json.loads(Path(base['blob']).read_text());digest=old['source_versions']['source_pack_sha256']
        parent=next(dict(a) for a in self.rt.db.execute('select * from production_artifacts where sha256=?',(digest,)))
        task['inputs'].append({'artifact':parent['id']})
        self.submit(ident,[task]);f=self.factory.sessions[self.rt.task('job',ident)['latest']]['frozen']
        self.assertIn('content-version hash',f['instruction'])
        self.run_worker(ident,lambda f:[('operation_amend',dict(request_key='correct',revision=0,expected_record_sha256=c.digest(old['records'][0]),record=fragment))],decision='blocked' if blocked else 'delivered')
        catalog=self.artifact(ident);pack=self.artifact(ident,'delivery/retained-sources.json')
        v=json.loads(Path(catalog['blob']).read_text());self.assertEqual(v['source_versions']['source_pack_sha256'],pack['sha256'])
        self.assertNotEqual(v['items'][0]['options'][0]['option_id'],old['items'][0]['options'][0]['option_id'])
        if not blocked:self.review(ident)
        return catalog,pack
    def native(self,ident):
        self.rt.tick('job');session=self.factory.sessions[self.rt.task('job',ident)['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
        result=step_runner.execute(session['frozen'],control);self.assertEqual(result['outcome'],'completed')
        session['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');return result
    def complete_path(self,append):
        from orchestrator import product_photos
        base,fragment=self.initial_catalog();before=Path(base['blob']).read_bytes()
        from unittest.mock import patch
        self.submit('photos',[dict(id='photos',objective='Retain observed product image',operation='images.products',parameters=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path={'artifact':base['id']},source_pack_path={'artifact':self.pack['artifact']},count_policy='target'))])
        with patch('orchestrator.image_sources.download',return_value=(photo(),'image/jpeg','https://images.example/product.jpg')):self.native('photos')
        photos=self.artifact('photos','outputs/result.zip')['id']
        source=self.pack
        if append:source=self.extra
        revised=copy.deepcopy(fragment);revised['options'][0]['comparison']='Corrected limitation, not purchasing approval.';revised['gap']='Target 3; retained 1; gap 2.'
        if 'price' in revised['options'][0]['fields']:revised['options'][0]['fields']['price']=dict(status='unknown',reason='No selected-variant price established; range requires selection.')
        corrected,pack=self.repair('repair',base,revised,source)
        if not append:self.assertEqual(Path(pack['blob']).read_bytes(),Path(self.rt.artifact(self.pack['artifact'])['blob']).read_bytes())
        self.assertTrue(recorded_sources(self.rt,[pack],allow_empty=True))
        # Restore real runtime then create another worker from the corrected export.
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        revised2=copy.deepcopy(revised);revised2['options'][0]['comparison']+=' Second substantive qualification.'
        final,retained=self.repair('repair_again',corrected,revised2,dict(artifact=pack['id']))
        self.assertTrue(recorded_sources(self.rt,[retained],allow_empty=True))
        self.assertEqual(Path(base['blob']).read_bytes(),before)
        params=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path={'artifact':final['id']},source_pack_path={'artifact':retained['id']},photos_path={'artifact':photos},image_path=None,title='Partial evidence',layout='readable')
        self.submit('slides',[dict(id='slides',objective='Project corrected exact records and preserved images',operation='collection.slides',parameters=params)])
        self.native('slides');slides=self.artifact('slides')
        spec=json.loads(Path(slides['blob']).read_text());self.assertIn('gap 2',json.dumps(spec));self.assertIn('exact-retained-page-image',json.dumps(spec))
        self.submit('compose',[dict(id='compose',objective='Compose corrected slides',operation='document.compose',parameters=dict(document_paths=[{'artifact':slides['id']}],image_paths=[],image_titles=[],title='Partial evidence'),inputs=[{'artifact':photos}])])
        self.native('compose');composed=self.artifact('compose')
        # Explicit reviewer keeps final review pending; partial must label it honestly.
        self.submit('deck',[dict(id='deck',objective='Build exact corrected presentation',operation='pptx.create',data={'artifact':composed['id']},inputs=[{'artifact':photos}]),dict(id='deck_review',objective='Independently review final deck',review_of='deck')])
        self.native('deck');deck=self.artifact('deck','outputs/result.pptx')
        with zipfile.ZipFile(io.BytesIO(Path(deck['blob']).read_bytes())) as z:self.assertIn(photo(),[z.read(p) for p in z.namelist() if p.startswith('ppt/media/')])
        self.finish_delivery(deck)

    def finish_delivery(self,deck):
        # Controlled unknown process outcome, never acceptance; existing runtime projects partial.
        inspection=next(t for t in self.rt.status('job')['tasks'] if t.get('latest') and self.factory.sessions[t['latest']]['frozen'].get('execution',{}).get('capability')=='pptx.render');aid=inspection['latest'];self.factory.sessions[aid]['status']=dict(status='uncertain',reason='Controlled missing review receipt')
        self.rt.tick('job');status=self.rt.status('job');self.assertEqual(status['status'],'uncertain')
        delivery=status['delivery'];self.assertFalse(delivery['complete']);self.assertFalse(delivery['user_acceptance'])
        candidate=next(x for x in delivery['candidates'] if x['artifact']==deck['id']);self.assertNotEqual(candidate['review_status'],'reviewed')
        self.assertIn('pdf',delivery['missing_formats'])
        self.assertEqual(job_owner.original(self.rt,'job')['job_owner']['task_limits'],life.LIMITS)
        self.assertEqual(self.grant,self.initial);self.assertEqual(len(self.factory.calls),len(set(self.factory.calls)))
        for session in self.factory.sessions.values():
            for k,v in session['frozen']['limits'].items():self.assertLessEqual(v,life.LIMITS[k])
        from task_relay import result_handoff
        calls=list(self.factory.calls);folder=result_handoff.sync(self.state,'job')
        marker=json.loads((folder/'.relay-workflow.json').read_text())
        self.assertEqual((folder/marker['paths'][deck['id']]).read_bytes(),Path(deck['blob']).read_bytes())
        self.assertIn(candidate['review_status'],result_handoff.saved_text(self.state,'job'))
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        self.rt.tick('job');self.assertEqual(self.rt.status('job')['delivery'],delivery);self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        (self.root/'partial-projection.json').write_text(json.dumps(delivery,indent=2))

class Furniture(Fixtures,unittest.TestCase):
    schema='furniture'
    def test_new_worker_unknown_price_retained_native_bytes_review_compose_and_partial(self):self.complete_path(False)

class Components(Fixtures,unittest.TestCase):
    schema='components'
    def test_appended_sources_two_new_workers_restart_review_compose_and_partial(self):self.complete_path(True)

class Provenance(Fixtures,unittest.TestCase):
    schema='plants'
    def test_blocked_export_ancestry_is_not_acceptance_and_uncertainty_or_forgery_fails(self):
        base,fragment=self.initial_catalog();source=self.extra;changed=copy.deepcopy(fragment);changed['options'][0]['comparison']='Changed claim, semantic review still required.'
        cat,pack=self.repair('blocked',base,changed,source,blocked=True)
        self.assertEqual(self.rt.task('job','blocked')['status'],'blocked');self.assertTrue(recorded_sources(self.rt,[pack],allow_empty=True))
        row=self.rt.db.execute('select state,receipt from production_attempts where id=?',(pack['attempt'],)).fetchone()
        self.rt.db.execute("update production_attempts set state='uncertain' where id=?",(pack['attempt'],));self.assertFalse(recorded_sources(self.rt,[pack],allow_empty=True))
        self.rt.db.execute('update production_attempts set state=?,receipt=? where id=?',(row['state'],json.dumps(dict(status='finished',pending_requests=['unknown'])),pack['attempt']));self.assertFalse(recorded_sources(self.rt,[pack],allow_empty=True))
        self.rt.db.execute('update production_attempts set receipt=? where id=?',(row['receipt'],pack['attempt']))
        forged=self.source(Path(pack['blob']).read_text()+' ','forged.json','application/json');a=dict(self.rt.artifact(forged['artifact']),artifact=forged['artifact']);self.assertFalse(recorded_sources(self.rt,[a],allow_empty=True))

    def test_exact_legacy_serialization_retains_ancestry_without_acceptance(self):
        from unittest.mock import patch
        base,fragment=self.initial_catalog();changed=copy.deepcopy(fragment)
        changed['options'][0]['comparison']='Legacy collected correction, still rejected.'
        current=sourcing_contract.context
        def legacy(*args,**kwargs):
            ctx=current(*args,**kwargs)
            if 'composed_source_pack' in ctx:
                raw=(c.encoded(json.loads(ctx['composed_source_pack']))+'\n').encode()
                ctx={**ctx,'composed_source_pack':raw,'source_versions':{**ctx['source_versions'],'source_pack_sha256':hashlib.sha256(raw).hexdigest()}}
            return ctx
        # Reproduce only the old serializer; all record/admission/receipt checks run.
        with patch.object(sourcing_contract,'context',side_effect=legacy):
            catalog,pack=self.repair('legacy',base,changed,self.pack,blocked=True)
        self.assertNotEqual(pack['sha256'],self.rt.artifact(self.pack['artifact'])['sha256'])
        self.assertTrue(recorded_sources(self.rt,[pack],allow_empty=True))
        self.assertEqual(self.rt.task('job','legacy')['status'],'blocked')
        self.submit('project_legacy',[dict(id='project_legacy',objective='Project exact corrected records, without acceptance',operation='collection.slides',parameters=dict(inventory_path={'artifact':self.inv['artifact']},source_pack_path={'artifact':pack['id']},catalog_path={'artifact':catalog['id']},photos_path=None,image_path=None,title='Partial records',layout='readable'))])
        self.native('project_legacy')
        self.assertEqual(self.rt.task('job','legacy')['status'],'blocked')
