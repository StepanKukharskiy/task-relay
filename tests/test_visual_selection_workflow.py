"""Offline discovery/selection/projection and immutable inspection regressions."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import sourcing_contract as sourcing,visual_selection as selection,web_sources
from tests import test_sourcing_records as records
from tests import test_prepared_research as research
from tests import test_review_dependency_lifecycle as binary
from tests import test_owner_intents as owner
from orchestrator import step_runner,job_owner

def judgment(status='visually_suitable',design='design-a'):
    return dict(status=status,design_id=design,reason='Scripted visual match; purchasing fields unknown.',
                photo_sha256='a'*64 if status=='visually_suitable' else '',reference_sha256='b'*64 if status=='visually_suitable' else '')

class Selection(unittest.TestCase):
    setUp=records.Tests.setUp
    input=records.Tests.input
    assignment=records.Tests.assignment
    save=records.Tests.save
    option=records.Tests.option
    item=records.Tests.item

    def test_three_visual_designs_unknown_buying_fields_duplicate_and_provisional_separate(self):
        params={**self.frozen['operation_contract']['parameters'],'selection_policy':'visual'}
        item=self.item(count=5)
        for n,o in enumerate(item['options']):
            o['fields']={k:v if k=='name_variant' else dict(status='unknown',reason='Not yet verified') for k,v in o['fields'].items()}
            o['selection']=judgment('provisional' if n==4 else 'visually_suitable','design-'+str(n if n<3 else 0))
        item['options'][4]['selection']['design_id']='lead'
        sourcing.options_record(item,params,self.context)
        doc=sourcing.options_document([item],params,self.context);v=doc['items'][0]
        self.assertEqual(v['coverage'],dict(suitable=3,provisional=1,excluded=0,unavailable=0,shortfall=0))
        from orchestrator.sourcing_slides import displayed_items,option_blocks
        self.assertEqual(len(displayed_items(doc)[0]['options']),3)
        self.assertNotIn('exact product identity uncertain',str(option_blocks(v['options'][0],params,[],set())))
        item['options'][2]['selection']=judgment('excluded','design-2')
        item['gap']='One visual alternative still missing.'
        amended=sourcing.options_document([item],params,self.context)['items'][0]
        self.assertEqual(amended['shortfall'],1);self.assertEqual(amended['coverage']['excluded'],1)
        self.assertNotEqual(amended['options'][2]['option_id'],v['options'][2]['option_id'])
        legacy=self.item(count=5);old=sourcing.options_document([legacy],self.frozen['operation_contract']['parameters'],self.context)
        self.assertNotIn('coverage',old['items'][0])

    def test_missing_pixels_conflicting_design_and_unsupported_status_fail(self):
        v=judgment();v['photo_sha256']=''
        with self.assertRaises(ValueError):selection.validate(v)
        with self.assertRaises(ValueError):selection.counts([dict(selection=judgment()),dict(selection=judgment('excluded'))],3)
        with self.assertRaises(ValueError):selection.validate(dict(judgment(),status='buy-now'))

    def test_unobserved_visual_claim_cannot_finish(self):
        from orchestrator.operation_records import Store
        f=copy.deepcopy(self.frozen);f['operation_contract']['parameters']['selection_policy']='visual';self.save(f)
        item=self.item();item['options'][0]['selection']=judgment()
        doc=sourcing.options_document([item],f['operation_contract']['parameters'],self.context)
        with self.assertRaisesRegex(ValueError,'observation journal'):selection.verify_observations(Store(f,self.db),doc)

    def test_visual_policy_composes_three_registered_field_schemas(self):
        from tests.test_universal_interfaces import Harness,CONFIGURATIONS
        from orchestrator.sourcing_slides import displayed_items
        for name,configuration in CONFIGURATIONS.items():
            with self.subTest(schema=name),tempfile.TemporaryDirectory() as folder:
                h=Harness(folder,configuration,options=4)
                try:
                    f=h.assignment('select');p=f['operation_contract']['parameters'];p['selection_policy']='visual'
                    ctx=sourcing.context(f,lambda path:(Path(folder)/path).read_bytes())
                    fragment=h.fragment(h.inventory['items'][0])
                    for n,o in enumerate(fragment['options']):
                        o['selection']=judgment(design='design-'+str(n if n<3 else 0))
                        for field in o['fields']:
                            if field!=configuration['identity']:o['fields'][field]=dict(status='unknown',reason='Unverified buying detail')
                    sourcing.options_record(fragment,p,ctx);d=sourcing.options_document([fragment],p,ctx)
                    self.assertEqual(d['items'][0]['coverage']['suitable'],3)
                    self.assertEqual(len(displayed_items(d)[0]['options']),3)
                finally:h.db.close()

    def test_reviewed_partition_merge_preserves_visual_policy_and_rejects_mixing(self):
        from tests.test_universal_interfaces import Harness,CONFIGURATIONS
        from orchestrator import sourcing_merge,operation_contracts as c
        for name,config in CONFIGURATIONS.items():
            with self.subTest(schema=name),tempfile.TemporaryDirectory() as root:
                h=Harness(root,config,count=2,options=4)
                try:
                    assignment=h.assignment;fragment=h.fragment
                    def visual_assignment(*a,**kw):
                        f=assignment(*a,**kw)
                        if f['operation_contract']['id']=='collection.options':
                            f['operation_contract']['parameters']['selection_policy']='visual'
                            h.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(c.encoded(f),f['assignment_id']));h.db.commit()
                        return f
                    def visual_fragment(subject):
                        value=fragment(subject)
                        for n,o in enumerate(value['options']):o['selection']=judgment(design='design-'+str(n if n<3 else 0))
                        return value
                    h.assignment=visual_assignment;h.fragment=visual_fragment
                    catalogs=[];reviews=[];inputs=copy.deepcopy(h.inputs)
                    for n,bounds in enumerate(([0,1],[1,2])):
                        _,cat=h.produce('p'+str(n),bounds);review=h.review('r'+str(n),cat,bounds)
                        for paths,prefix,value in ((catalogs,'cat',cat),(reviews,'review',review)):
                            path=prefix+str(n)+'.json';paths.append(path);inputs.append(h.input(path,value))
                    params=dict(inventory_path='subjects.json',source_pack_path='sources.json',max_records=2,options_per_item=3,count_policy='target',field_definitions=config['fields'],identity_field=config['identity'],catalog_paths=catalogs,review_paths=reviews)
                    frozen=dict(inputs=inputs,execution=dict(capability='records.merge',version=1,parameters=params))
                    read=lambda p:(Path(root)/p).read_bytes()
                    raw,_,_=sourcing_merge.build(frozen,read);doc=json.loads(raw)
                    self.assertEqual(doc['parameters']['selection_policy'],'visual')
                    self.assertEqual([i['coverage']['suitable'] for i in doc['items']],[3,3])
                    mixed=json.loads(read('cat1.json'));mixed['parameters'].pop('selection_policy')
                    replacement=h.input('cat1.json',mixed);frozen['inputs']=[replacement if i['path']=='cat1.json' else i for i in frozen['inputs']]
                    with self.assertRaisesRegex(ValueError,'policy'):sourcing_merge.build(frozen,read)
                finally:h.db.close()

class Discovery(unittest.TestCase):
    def test_uncertain_search_stops_without_fetch_or_replay(self):
        from orchestrator.runtime_outcomes import Hold
        events=[]
        class Session(research.Session):
            def search(self,q):
                events.append(('search',q))
                if q.startswith('B'):raise Hold('external_uncertain','Unknown submitted search outcome')
                return super().search(q)
            def fetch(self,*a,**kw):events.append(('read',a[0]));return super().fetch(*a,**kw)
        spec=dict(version=1,targets=[dict(id=k,queries=[k+' broad'],required_options=3) for k in ('A','B','C')])
        with tempfile.TemporaryDirectory() as tmp,patch.object(web_sources.orchestrator_web,'public_url',side_effect=lambda u:u):
            with self.assertRaisesRegex(Hold,'Unknown submitted'):
                web_sources.collect(['A broad','B broad','C broad'],[],research.CONFIG['models']['text'],tmp,research.CONFIG,prepared_spec=dict(path='q',sha256='a'*64,data=spec),session_factory=Session)
        self.assertEqual(events,[('search','A broad'),('search','B broad')])

    def test_inventory_searches_precede_reads_pool_retained_without_more_budget(self):
        events=[]
        class Session(research.Session):
            def search(self,q):events.append(('search',q));return super().search(q)
            def fetch(self,*a,**kw):events.append(('read',a[0]));return super().fetch(*a,**kw)
        spec=dict(version=1,targets=[dict(id='A',queries=['A broad'],required_options=3),dict(id='B',queries=['B broad'],required_options=3)])
        with tempfile.TemporaryDirectory() as tmp,patch.object(web_sources.orchestrator_web,'public_url',side_effect=lambda u:u):
            raw,_=web_sources.collect(['A broad','B broad'],[],research.CONFIG['models']['text'],tmp,research.CONFIG,prepared_spec=dict(path='q',sha256='a'*64,data=spec),session_factory=Session)
        pack=json.loads(raw);self.assertEqual([e[0] for e in events[:2]],['search','search'])
        self.assertEqual(len(pack['candidate_pool']),2)
        self.assertTrue(all(len(p['links'])>=3 for p in pack['candidate_pool']))
        self.assertLessEqual(pack['read_budget']['submitted_reads']+2,80)
        self.assertEqual(sum(e[0]=='search' for e in events),2)

class StandaloneInspection(binary.ReviewDependency):
    # Select only this method in the release gate; inherited inline paths remain
    # covered by their original group.
    def native(self,ident):
        self.rt.tick('job');s=self.factory.sessions[self.rt.task('job',ident)['latest']]
        Path(s['session']['control']).mkdir(parents=True,exist_ok=True)
        result=step_runner.execute(s['frozen'],Path(s['session']['control']))
        self.assertEqual(result['outcome'],'completed')
        s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job')

    def test_rejected_standalone_inspection_then_two_fresh_reviews_without_replay(self):
        self.delegate('prep',[owner.worker('prep',[{'artifact':self.evidence['artifact']}]),dict(id='prep_review',objective='Review fixture',review_of='prep')])
        self.run_steps('prep',lambda f:self.reads(f)+[('file_write',dict(path=f['outputs'][0]['path'],text='Original fixture'))])
        self.run_steps('prep_review',self.reads,'accept');data=self.rt.output('job','prep','outputs/result.txt')
        self.delegate('first',[dict(id='first',objective='Standalone opaque candidate',operation='fixture.build',inputs=[{'artifact':data['id']}]),dict(id='inspect',objective='Standalone exact observation',operation='fixture.inspect',inputs=[dict(task='first',output='candidate')]),dict(id='inspect_review',objective='Reject semantic quality while preserving completed inspection',review_of='inspect')]);self.native('first')
        first=self.rt.output('job','first','delivery/candidate.txt')
        self.native('inspect')
        self.run_steps('inspect_review',self.reads,'revise')
        state=self.rt.task('job','inspect')['status'];self.assertNotEqual(state,'completed')
        calls=list(self.factory.calls)
        self.restart();second=self.make('v2','Corrected first defect',first);f=self.judge('v2','revise')
        self.assertNotIn('inspect',f['dependencies'])
        self.assertTrue(any(i.get('artifact')==self.rt.output('job','inspect','delivery/preview.png')['id'] for i in f['inputs']))
        third=self.make('v3','Second corrected defect',second);self.judge('v3','accept')
        self.assertEqual(self.rt.task('job','inspect')['status'],state)
        self.assertEqual(len([s for s in self.factory.sessions.values() if s['frozen'].get('execution',{}).get('capability')=='fixture.inspect' and any(i.get('artifact')==first['id'] for i in s['frozen']['inputs'])]),1)
        from orchestrator.review_inspection import bind
        task=self.inspection_task(first);row=self.rt.db.execute("select * from production_attempts where task='inspect'").fetchone();frozen=json.loads(row['frozen']);control=Path(json.loads(row['session'])['control'])
        original=(control/'operation-materialized.json').read_bytes()
        saved=dict(row);grant=job_owner.original(self.rt,'job')['job_owner']
        for status,receipt in [('uncertain',json.loads(saved['receipt'])),('completed',dict(status='finished',pending_requests=['unknown']))]:
            with self.rt.transaction():self.rt.db.execute('UPDATE production_attempts SET state=?,receipt=? WHERE id=?',(status,json.dumps(receipt),saved['id']))
            with self.subTest(status=status),self.assertRaisesRegex(ValueError,'conclusive'):bind([self.inspection_task(first)],grant,self.rt,'job')
        with self.rt.transaction():self.rt.db.execute('UPDATE production_attempts SET state=?,receipt=? WHERE id=?',(saved['state'],saved['receipt'],saved['id']))
        try:
            (control/'operation-materialized.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'invalid'):bind([task],job_owner.original(self.rt,'job')['job_owner'],self.rt,'job')
        finally:(control/'operation-materialized.json').write_bytes(original)
