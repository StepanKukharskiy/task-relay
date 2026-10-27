"""Literal evidence to image display projection; controlled public image bytes."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from orchestrator import product_photos,image_sources,operation_contracts as c
from task_relay.completion_recovery import registered_preflight_gap
from tests.test_universal_interfaces import Harness,CONFIGURATIONS
from tests.test_image_sources import photo

class Tests(unittest.TestCase):
    def prepare(self,config,*,ambiguous=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        h=Harness(temp.name,config);self.addCleanup(h.db.close)
        identity=config['identity'];literal=identity+': Linen\n\tSectional\u00a0 Brand'
        for entry in h.pack['entries']:
            page=entry['pages'][0];line=next(x for x in page['text'].splitlines() if x.startswith(identity+':'))
            page['text']=page['text'].replace(line,literal);page['sha256']=hashlib.sha256(page['text'].encode()).hexdigest()
            page['images']=[dict(url='https://images.example/verified.jpg',basis='observed-product-jsonld')]
            if ambiguous:page['products']=[dict(name='Unrelated object'),dict(name=literal)]
        h.inputs[1]=h.input('sources.json',h.pack);fragment=h.fragment
        def multiline(subject):
            result=fragment(subject)
            for option in result['options']:option['fields'][identity]['end']=option['fields'][identity]['start']+len(literal)
            return result
        h.fragment=multiline;_,catalog=h.produce('producer')
        binding=h.input('catalog.json',catalog)
        f=dict(assignment_id='photos',workspace=str(h.root),inputs=h.inputs+[binding],outputs=[dict(path='photos.zip')],limits=dict(seconds=600,output_bytes=5000000),
            execution=dict(capability='images.catalog',parameters=dict(inventory_path='subjects.json',catalog_path='catalog.json',source_pack_path='sources.json',count_policy='target',source_adapters=['observed-pages'],image_identity='page')),
            runtime_sources={'product_photos.py':'0'*64})
        return h,f,literal

    def test_lost_multi_entity_binding_is_missing_without_downloading_a_decoy(self):
        for name,config in CONFIGURATIONS.items():
            with self.subTest(schema=name):
                h,f,_=self.prepare(config,ambiguous=True)
                def forbidden(*_):self.fail('Ambiguous page image must not be downloaded')
                _,manifest=product_photos.build(f,lambda p:(h.root/p).read_bytes(),fetch=forbidden)
                self.assertEqual(manifest['coverage'],dict(found=0,missing=1,total=1))
                f['execution']['parameters']['count_policy']='required'
                with self.assertRaisesRegex(ValueError,'Required product photo coverage'):
                    product_photos.build(f,lambda p:(h.root/p).read_bytes(),fetch=forbidden)

    def test_multiline_identity_reaches_image_bundle_without_changing_evidence(self):
        for name,config in CONFIGURATIONS.items():
            with self.subTest(schema=name):
                h,f,literal=self.prepare(config);before=(h.root/'catalog.json').read_bytes();calls=[]
                def fetch(url,*_):calls.append(url);return photo(),'image/jpeg',url
                raw,manifest=product_photos.build(f,lambda p:(h.root/p).read_bytes(),fetch=fetch)
                self.assertEqual(len(calls),1);self.assertEqual(manifest['coverage']['found'],1)
                self.assertEqual(manifest['subjects'][0]['query'],' '.join(literal.split()))
                self.assertEqual((h.root/'catalog.json').read_bytes(),before)
                self.assertEqual(manifest['source_catalog_sha256'],hashlib.sha256(before).hexdigest())
                self.assertEqual(len(image_sources.unpack(raw)[0]),1)

    def test_registered_preflight_requires_exact_initial_intent_and_no_transport(self):
        from types import SimpleNamespace
        h,f,_=self.prepare(CONFIGURATIONS['furniture']);read=lambda p:(h.root/p).read_bytes()
        sha,_,subjects,_=product_photos.prepare(f,read,legacy=True);first=subjects[0]['id']
        binding=c.digest(dict(subjects=subjects,adapters=[dict(id='observed-pages',version=1)],policy=dict(catalog_sha256=sha,image_identity='page')))
        event=dict(kind='collection-checkpoint',status='requested',state=dict(version=1,binding=binding,pending=dict(subject=first,adapter='observed-pages',version=1),units={first:{}}))
        control=h.root/'workers/photos';control.mkdir(parents=True);journal=control/'image-requests.jsonl';journal.write_text(c.encoded(event)+'\n')
        artifacts={i['artifact']:dict(sha256=i['sha256'],blob=str(h.root/i['path'])) for i in f['inputs']}
        rt=SimpleNamespace(root=h.root,artifact=lambda aid:artifacts[aid]);attempt=dict(id='photos',task='photos',frozen=c.encoded(f))
        receipt=dict(status='finished',exit_code=1,operation=dict(outcome='failed'),pending_requests=[])
        proof=registered_preflight_gap(rt,attempt,receipt);self.assertIsNotNone(proof)
        self.assertEqual(proof['proof']['execution'],'not_started')
        journal.write_text(c.encoded(event)+'\n'+c.encoded(dict(kind='image',status='requested'))+'\n')
        self.assertIsNone(registered_preflight_gap(rt,attempt,receipt))
        journal.write_text(c.encoded(event)+'\n');(h.root/'photos.zip').write_bytes(b'unaccounted output')
        self.assertIsNone(registered_preflight_gap(rt,attempt,receipt))

    def stopped_graph(self,*,rejected=False):
        from tests.test_completion_recovery import Tests as Fixture
        from tests.test_orchestrator import pair
        from orchestrator import execution
        from orchestrator.storage import transaction
        from task_relay import completion_recovery as recovery
        f=Fixture();f.setUp();self.addCleanup(f.tearDown);p,s=f.prepare()
        h,photo_spec,_=self.prepare(CONFIGURATIONS['furniture'],ambiguous=rejected)
        graph=pair(max_attempts=1);graph['id']='parent';producer,review=graph['tasks']
        producer.update(execution={**photo_spec['execution'],'version':1},inputs=[{**i,'artifact':f.rt.register(h.root/i['path'],'Bound synthetic source')} for i in photo_spec['inputs']],outputs=[dict(path='photos.zip',purpose='Photo bundle',media_type='application/zip')],criteria=execution.REGISTRY['images.catalog']['criteria'],limits=dict(seconds=600,tool_calls=1,output_bytes=5000000))
        review.update(criteria=producer['criteria'],limits=dict(seconds=600,tool_calls=24,output_bytes=1000000),inputs=[dict(from_task='produce',output='photos.zip',path='photos.zip',media_type='application/zip',purpose='Inspect bundle',authority='Unaccepted')])
        f.rt.create(graph);f.rt.tick('parent');aid=f.rt.task('parent','produce')['latest'];frozen=f.factory.sessions[aid]['frozen']
        frozen['runtime_sources']['product_photos.py']='0'*64
        f.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen,sort_keys=True,separators=(',',':')),aid));f.state.db.commit()
        read=lambda path:(Path(frozen['workspace'])/path).read_bytes()
        if rejected:
            from unittest.mock import patch
            with patch.object(product_photos,'candidate_images',side_effect=lambda page,literal:page['images']):
                raw,manifest=product_photos.build(frozen,read,fetch=lambda *args:(photo(),'image/jpeg','https://images.example/verified.jpg'))
            f.factory.finish(aid);(Path(frozen['workspace'])/'photos.zip').write_bytes(raw)
            f.factory.sessions[aid]['status']['operation']=dict(outcome='completed',validation=manifest)
            f.rt.tick('parent');f.rt.tick('parent');rid=f.rt.task('parent','review')['latest'];self.assertIsNotNone(rid)
            f.factory.finish(rid,decision='revise');path=f.factory.sessions[rid]['workspace']/'.relay/result.json'
            report=json.loads(path.read_text());report['findings']=[dict(category='integrity',code='incorrect_identity',message='Wrong subject image',evidence='Observed category image')];path.write_text(json.dumps(report));f.rt.tick('parent')
            with transaction(f.state.db):f.state.db.execute('UPDATE completion_recovery_grants SET policy=?',(c.encoded(recovery.DELIVERY_POLICY),))
            return f,p,s,aid,None
        sha,_,subjects,_=product_photos.prepare(frozen,read,legacy=True);first=subjects[0]['id'];binding=c.digest(dict(subjects=subjects,adapters=[dict(id='observed-pages',version=1)],policy=dict(catalog_sha256=sha,image_identity='page')))
        event=dict(kind='collection-checkpoint',status='requested',state=dict(version=1,binding=binding,pending=dict(subject=first,adapter='observed-pages',version=1),units={first:{}}))
        control=f.rt.root/'workers'/aid;control.mkdir(parents=True,exist_ok=True);(control/'image-requests.jsonl').write_text(c.encoded(event)+'\n')
        f.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,operation=dict(outcome='failed'),pending_requests=[])
        f.rt.tick('parent')
        with transaction(f.state.db):f.state.db.execute('UPDATE completion_recovery_grants SET policy=?',(c.encoded(recovery.DELIVERY_POLICY),))
        return f,p,s,aid,control

    def test_native_preflight_continues_original_graph_without_planner_and_rechecks_journal(self):
        from orchestrator.storage import transaction
        from task_relay import completion_recovery as recovery
        f,p,s,aid,control=self.stopped_graph();before=dict(f.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone());calls=list(f.factory.calls)
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        self.assertEqual(f.factory.calls,calls);self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        f.rt.tick('parent');new=f.rt.task('parent','produce')['latest'];self.assertNotEqual(new,aid,[dict(r) for r in f.state.db.execute("SELECT kind,data FROM production_events WHERE run='parent' ORDER BY id DESC LIMIT 2")])
        self.assertEqual(f.rt.task('parent','produce')['attempts'],2)
        self.assertEqual(before,dict(f.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()))
        self.assertEqual(f.factory.sessions[new]['frozen']['execution'],json.loads(before['frozen'])['execution'])

    def test_native_preflight_changed_transport_journal_holds_before_dispatch(self):
        from orchestrator.storage import transaction
        from task_relay import completion_recovery as recovery
        f,p,s,aid,control=self.stopped_graph()
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        with (control/'image-requests.jsonl').open('a') as stream:stream.write('{"kind":"image","status":"requested"}\n')
        calls=list(f.factory.calls);f.rt.tick('parent')
        self.assertEqual(f.factory.calls,calls);self.assertEqual(f.rt.task('parent','produce')['status'],'blocked')

    def test_changed_registered_selection_uses_existing_cycle_and_requires_fresh_review(self):
        from orchestrator.storage import transaction
        from task_relay import completion_recovery as recovery
        f,p,s,aid,_=self.stopped_graph(rejected=True);before=recovery.snapshot(f.state,'parent',photo_recovery=True);calls=list(f.factory.calls)
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        target=f.step(p,'outline')['target'];self.assertTrue(target.startswith('registered-revision-'));self.assertEqual(f.factory.calls,calls)
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(recovery.snapshot(f.state,'parent',photo_recovery=True),before)
        f.rt.tick(target);new=f.rt.task(target,'produce')['latest'];self.assertIsNotNone(new)
        frozen=f.factory.sessions[new]['frozen'];raw,manifest=product_photos.build(frozen,lambda path:(Path(frozen['workspace'])/path).read_bytes(),fetch=lambda *_:self.fail('No ambiguous download'))
        self.assertEqual(manifest['coverage']['missing'],1)
        f.factory.finish(new);(Path(frozen['workspace'])/'photos.zip').write_bytes(raw);f.factory.sessions[new]['status']['operation']=dict(outcome='completed',validation=manifest)
        f.rt.tick(target);f.rt.tick(target);review=f.rt.task(target,'review')['latest'];self.assertIsNotNone(review)
        self.assertEqual(f.factory.sessions[review]['frozen']['review_target'],new)
        f.factory.finish(review,decision='accept');self.assertEqual(f.rt.tick(target)['status'],'completed')

    def test_registered_revision_preserves_blocked_planner_and_holds_changed_inputs(self):
        from orchestrator.storage import transaction
        from task_relay import completion_recovery as recovery
        from tests import test_production_planning as planning_fixtures
        from unittest.mock import patch
        f,p,s,aid,_=self.stopped_graph(rejected=True)
        parent=planning_fixtures.Tests.queue(f,99)
        with transaction(f.state.db):f.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        # Simulate the former controller sending this valid local correction to planning.
        with patch('task_relay.registered_revision.proof',return_value=None),transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        step=f.step(p,'outline');plan=f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(step['target'],)).fetchone();self.assertIsNotNone(plan)
        with transaction(f.state.db):
            f.state.db.execute("UPDATE production_plans SET status='blocked',calls=1,result=? WHERE id=?",(json.dumps(dict(decision='blocked',message='Cannot change old native behavior',plan=None)),plan['id']))
            f.state.db.execute('INSERT INTO production_plan_calls(plan_id,number,request,response,usage,error,created) VALUES (?,1,?,?,?,?,1)',(plan['id'],'{}',json.dumps(dict(decision='blocked',plan=None,message='No capability')),'{}',None))
            f.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],));f.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='outline'",(p['id'],))
        calls=[dict(r) for r in f.state.db.execute('SELECT * FROM production_plan_calls')];factory=list(f.factory.calls)
        recovery.reconcile_stranded_local_revision(f.state);target=f.step(p,'outline')['target'];self.assertTrue(target.startswith('registered-revision-'),target)
        self.assertEqual(factory,f.factory.calls);self.assertEqual(calls,[dict(r) for r in f.state.db.execute('SELECT * FROM production_plan_calls')]);self.assertEqual(f.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
        frozen=json.loads(f.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(aid,)).fetchone()[0]);blob=Path(f.rt.artifact(frozen['inputs'][0]['artifact'])['blob']);blob.chmod(0o600);blob.write_bytes(b'changed')
        f.rt.tick(target);self.assertEqual(factory,f.factory.calls);self.assertEqual(f.rt.task(target,'produce')['status'],'blocked')
