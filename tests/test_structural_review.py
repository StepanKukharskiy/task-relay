"""Prospective graph simplification across registered content configurations."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import execution
from task_relay import record_planning
from tests import test_universal_interfaces as fixtures


class Tests(unittest.TestCase):
    def compile(self,*,enabled=True,gate=False,report=False,consumer=False,config=None,semantic=False,max_tasks=30):
        plan=fixtures.Tests().proposal(config or fixtures.CONFIGURATIONS['plants'])
        if gate:plan['tasks'][0]['user_gate']='User chooses the complete catalog'
        if semantic:plan['tasks'][0]['output_contracts']=[dict(path='catalog.json',validation=['Compare the collection as a whole'])]
        if consumer:
            plan['tasks'].append(dict(id='consumer',inputs=[],outputs=[],dependencies=['collect','review']))
        deliverables={'catalog':dict(task='collect',output='catalog.json')}
        if report:deliverables['review']=dict(task='review',output='review.md')
        native=execution.REGISTRY['records.merge']
        scope=dict(connector_companions_version=1,graph_operations=[dict(id='records.merge',available=True,**native)])
        if enabled:scope['structural_review_policy_version']=1
        receipts=record_planning.partition(plan,scope,dict(max_tasks=max_tasks,limits=dict(seconds=600,output_bytes=5000000)),
            {'collect':11,'review':11},deliverables)
        return plan,receipts

    def test_structural_merge_keeps_semantic_delegates_without_another_model_gate(self):
        for name,config in fixtures.CONFIGURATIONS.items():
            with self.subTest(configuration=name):
                # Same policy is independent of fields and business vocabulary.
                plan,receipts=self.compile(consumer=True,config=config)
                tasks={t['id']:t for t in plan['tasks']}
                self.assertNotIn('review',tasks)
                self.assertEqual(tasks['consumer']['dependencies'],['collect'])
                self.assertEqual(sum(bool(t.get('review_of')) for t in tasks.values()),4)
                self.assertEqual(len(tasks['collect']['execution']['parameters']['review_paths']),4)
                self.assertEqual(receipts[-1]['removed_review']['id'],'review')
                self.assertFalse(receipts[-1]['acceptance'])
                record_planning.bind(plan)

    def test_legacy_scope_and_requested_report_keep_the_review(self):
        for kwargs in ({'enabled':False},{'report':True},{'semantic':True}):
            plan,_=self.compile(**kwargs)
            self.assertIn('review',{t['id'] for t in plan['tasks']})

    def test_explicit_user_gate_is_not_removed_by_partitioning(self):
        with self.assertRaisesRegex(ValueError,'explicit human gate'):self.compile(gate=True)

    def test_capacity_counts_actual_workers_without_expanding_the_limit(self):
        plan,_=self.compile(max_tasks=9)
        self.assertEqual(len(plan['tasks']),9)
        for kwargs in ({'max_tasks':8},{'max_tasks':9,'report':True},{'max_tasks':9,'enabled':False}):
            with self.assertRaisesRegex(ValueError,'frozen graph size'):self.compile(**kwargs)

    def test_native_composition_rejects_wrong_review_versions_and_missing_coverage(self):
        from orchestrator import sourcing_merge
        for name,config in fixtures.CONFIGURATIONS.items():
            with self.subTest(configuration=name),tempfile.TemporaryDirectory() as root:
                root=Path(root).resolve()
                h=fixtures.Harness(root,config,count=2);self.addCleanup(h.db.close)
                inputs=copy.deepcopy(h.inputs);catalogs=[];reviews=[]
                for index in range(2):
                    bounds=[index,index+1]
                    _,catalog=h.produce('p'+str(index),bounds)
                    review=h.review('r'+str(index),catalog,bounds)
                    for paths,prefix,value in ((catalogs,'cat',catalog),(reviews,'review',review)):
                        path=prefix+str(index)+'.json';paths.append(path);inputs.append(h.input(path,value))
                parameters=dict(inventory_path='subjects.json',source_pack_path='sources.json',
                    max_records=2,options_per_item=3,count_policy='target',field_definitions=config['fields'],
                    identity_field=config['identity'],catalog_paths=catalogs,review_paths=reviews)
                frozen=dict(inputs=inputs,execution=dict(capability='records.merge',version=1,parameters=parameters))
                read=lambda path:(Path(root)/path).read_bytes()
                raw,_,proof=sourcing_merge.build(frozen,read)
                self.assertEqual(len(json.loads(raw)['items']),2)
                self.assertFalse(proof['acceptance'])
                # The real runtime collects the native receipt and hands the
                # exact output to a delegate without a second model review.
                from orchestrator.runtime import Runtime
                from tests.test_orchestrator import FakeFactory, plan as runtime_plan, task
                factory=FakeFactory();rt=Runtime(Path(root)/'runtime',factory)
                try:
                    bound=[]
                    for item in inputs:
                        aid=rt.register(Path(root)/item['path'],'Synthetic reviewed input')
                        bound.append({**item,'artifact':aid})
                    native=execution.REGISTRY['records.merge']
                    merge=task('merge',execution=frozen['execution'],inputs=bound,max_attempts=1,
                        limits=dict(seconds=120,tool_calls=1,output_bytes=5000000))
                    merge.update(criteria=copy.deepcopy(native['criteria']),outputs=[dict(path=p,purpose='Verified composition',media_type=m) for p,m in native['outputs'].items()])
                    consumer=task('consumer',dependencies=['merge'],inputs=[dict(from_task='merge',
                        output='delivery/catalog.json',path='catalog.json',purpose='Verified records',authority='Reviewed input composition',media_type='application/json')])
                    rt.create(runtime_plan([merge,consumer]));rt.tick('demo')
                    attempt=rt.task('demo','merge')['latest'];session=factory.sessions[attempt]
                    Path(session['session']['control']).mkdir(parents=True,exist_ok=True)
                    work=session['workspace'];details=sourcing_merge.execute(session['frozen'],session['session']['control'],lambda p:(work/p).read_bytes())
                    session['status']=dict(status='finished',exit_code=0,tool_calls=1,operation=details)
                    rt.tick('demo')
                    self.assertEqual(rt.task('demo','merge')['status'],'completed')
                    downstream=factory.sessions[rt.task('demo','consumer')['latest']]['frozen']
                    self.assertEqual(downstream['inputs'][0]['artifact'],rt.output('demo','merge','delivery/catalog.json')['id'])
                    self.assertEqual((Path(downstream['workspace'])/'catalog.json').read_bytes(),raw)
                finally:rt.db.close()
                incomplete=copy.deepcopy(frozen)
                incomplete['execution']['parameters'].update(catalog_paths=catalogs[:1],review_paths=reviews[:1])
                with self.assertRaisesRegex(ValueError,'coverage'):
                    sourcing_merge.build(incomplete,read)
                changed=json.loads(read(reviews[0]));changed['catalog_sha256']='0'*64
                replacement=h.input(reviews[0],changed)
                frozen['inputs']=[replacement if i['path']==reviews[0] else i for i in inputs]
                with self.assertRaisesRegex(ValueError,'different bytes'):
                    sourcing_merge.build(frozen,read)
