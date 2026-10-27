"""Delivery intent survives stage recovery and requires a reviewed final artifact."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay import delivery_completion as delivery, completion_recovery as recovery
from task_relay import pipelines as pipe, production_planning as planning, production_control as pc
from tests import test_pipelines as fixtures


class Tests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    request = fixtures.Tests.request
    stage = fixtures.Tests.stage
    step = fixtures.Tests.step
    answer = fixtures.Tests.answer
    response = fixtures.Tests.response

    def action(self, planned=False):
        return dict(kind='plan_pipeline', contract_version=1, title='Final delivery',
                    planning_only=planned, completion=dict(version=1, stage='finish', output='finish'),
                    stages=[self.stage(route='production'), self.stage('finish', route='production')])

    def create(self, planned=False, action=None):
        self.request(action or self.action(planned), 'Deliver the finished reviewed file without intermediate choices.', 1)
        p = self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertIsNotNone(p)
        # Desktop workflow Start is automatic; fixtures do not send Telegram notices.
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET channel='desktop' WHERE id=?",(p['id'],))
        return self.state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()

    def complete_stage(self, p, stage_id, body=None, completion_expected=True):
        pipe.tick(self.state)
        action = dict(kind='plan_production', template='custom', project=None,
                      reference_pack_id=None, research_ids=[], artifact_ids=[], planning_only=False,
                      research_mode='none', step_capabilities=[], deliverables={stage_id: 'Exact '+stage_id+' output'})
        stage = self.step(p, stage_id)
        if stage['target_kind']!='plan_production':
            self.answer(action)
            stage = self.step(p, stage_id)
        response = self.response()
        context=json.loads(self.state.db.execute('SELECT context FROM production_plans WHERE id=?',(stage['target'],)).fetchone()[0])
        for task in response['plan']['tasks']:
            task.setdefault('inputs',[]).extend(dict(artifact=source['artifact'],path='evidence/'+source['artifact']+'.json',purpose=source['purpose'],authority='Exact upstream workflow version') for source in context['sources'] if not source.get('request_context') and not any(i.get('artifact')==source['artifact'] for i in task.get('inputs',[])))
        media=json.loads(p['spec'])['stages'][stage['position']]['handoff']['outputs'][stage_id]['media_type']
        output={'application/json':'output.json','application/zip':'output.zip'}.get(media,'output.txt')
        response['plan']['tasks'][0]['outputs'][0].update(path=output,media_type=media)
        response['plan']['tasks'][1]['inputs'][0].update(output=output,media_type=media)
        response['deliverable_map'] = {stage_id: dict(task='produce', output=output)}
        for task in response['plan']['tasks']:
            task.pop('user_gate', None)
            if context.get('completion_recovery'):
                task.setdefault('limits',{}).update(seconds=600,tool_calls=24,provider_requests=24)
        planning.Worker(self.state, lambda *_: (json.dumps(response), {})).tick()
        row = self.state.db.execute('SELECT * FROM production_plans WHERE id=?', (stage['target'],)).fetchone()
        self.assertEqual(row['status'], 'ready', row['error'])
        pipe.tick(self.state)
        row = self.state.db.execute('SELECT * FROM production_plans WHERE id=?', (stage['target'],)).fetchone()
        self.assertEqual(row['status'],'started',self.step(p,stage_id)['error'])
        worker = pc.Worker(self.state, lambda _: self.rt)
        worker.tick()
        producer = self.rt.task(row['run'], 'produce')['latest']
        self.factory.finish(producer)
        if body is not None:
            target=self.factory.sessions[producer]['workspace']/output
            if isinstance(body,bytes):target.write_bytes(body)
            else:target.write_text(json.dumps(body))
        worker.tick()
        reviewer = self.rt.task(row['run'], 'review')['latest']
        self.factory.finish(reviewer, decision='accept'); worker.tick(); pipe.tick(self.state)
        if completion_expected:self.assertEqual(self.step(p, stage_id)['status'], 'completed')
        return row['run'], producer, reviewer

    def test_coverage_artifact_identity_can_be_read_without_database_mutation(self):
        p=self.create();self.complete_stage(p,'outline')
        source=json.loads(self.step(p,'outline')['sources'])[0]
        self.state.db.execute('PRAGMA query_only=ON')
        try:self.assertEqual(pipe.artifact_source(self.state,source['artifact']),source)
        finally:self.state.db.execute('PRAGMA query_only=OFF')

    def test_initial_request_grants_bounded_per_stage_recovery_without_another_prompt(self):
        p = self.create()
        grant = self.state.db.execute('SELECT * FROM completion_recovery_grants WHERE pipeline=?', (p['id'],)).fetchone()
        self.assertEqual(grant['request'], p['request'])
        self.assertEqual(json.loads(grant['policy']), recovery.DELIVERY_POLICY)
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(len(delivery.ledger(self.state, p['id'])['remaining']), 2)

    def test_planning_only_never_grants_or_dispatches_until_resume(self):
        p = self.create(planned=True)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_grants').fetchone()[0], 0)
        pipe.tick(self.state); self.assertEqual(self.factory.calls, [])
        with transaction(self.state.db):
            pipe.control(__import__('task_relay.relay_channels',fromlist=['ScopedState']).ScopedState(self.state,'desktop'), p['id'], 'resume', request='Start the saved workflow')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_grants').fetchone()[0], 1)

    def test_final_binding_and_current_independent_review_complete_without_selection(self):
        p = self.create()
        self.complete_stage(p, 'outline')
        self.complete_stage(p, 'finish')
        pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?', (p['id'],)).fetchone()[0], 'completed')
        self.assertEqual(delivery.ledger(self.state, p['id'])['remaining'], [])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0], 0)

    def test_stale_final_review_cannot_become_workflow_success(self):
        p = self.create(); self.complete_stage(p, 'outline')
        _, _, reviewer = self.complete_stage(p, 'finish')
        with transaction(self.state.db):
            frozen = json.loads(self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?', (reviewer,)).fetchone()[0])
            frozen['review_target'] = 'stale-version'
            self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?', (json.dumps(frozen), reviewer))
        with self.assertRaisesRegex(ValueError, 'independent review'):
            delivery.check_final(self.state, p)
        pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?', (p['id'],)).fetchone()[0], 'blocked')

    def test_delivery_contract_rejects_choices_and_intermediate_report_as_final(self):
        for field in ('choice', 'wrong_stage', 'missing_output', 'conversation'):
            action = copy.deepcopy(self.action())
            if field == 'choice': action['stages'][0]['gate'] = 'selection'
            elif field == 'wrong_stage': action['completion']['stage'] = 'outline'
            elif field == 'missing_output': action['completion']['output'] = 'absent'
            else: action['stages'][-1]['route'] = 'conversation'
            with self.subTest(field=field), self.assertRaises(ValueError):
                delivery.validate(action)

    def test_catalog_photo_connector_is_an_explicit_delivery_photo_producer(self):
        action=self.action();photo=self.stage('photos',route='production')
        photo['capabilities']=['images.products'];photo['handoff']['outputs']['photos']['media_type']='application/zip'
        action['stages'].insert(1,photo)
        action['stages'][-1]['handoff']['inputs']=[dict(stage='photos',deliverable='photos',consumer='context',media_type='application/zip')]
        action['completion']['photos']=dict(stage='photos',output='photos',count_policy='target')
        delivery.validate(action)
        photo['capabilities']=[]
        with self.assertRaises(ValueError):delivery.validate(action)

    def test_recovery_allowance_is_local_to_the_stage_and_transactional(self):
        p = self.create()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='production_run',target='parent' WHERE pipeline=? AND id='finish'", (p['id'],))
            for cycle in range(1, 5):
                self.state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',
                                      (p['id'], 'outline', 'old-'+str(cycle), cycle, cycle+100, '{}'))
        stage = self.step(p, 'finish')
        baseline = dict(run='parent', artifacts=[], tasks=[], attempts=[], gaps=[dict(kind='producer_gaps')],
                        plan=dict(tasks=[], deliverables={}))
        with patch.object(recovery, 'snapshot', return_value=baseline):
            with self.assertRaisesRegex(ValueError, 'rollback'), transaction(self.state.db):
                self.assertTrue(recovery.begin(self.state, p, stage, 'parent'))
                raise ValueError('rollback')
            self.assertIsNone(self.state.db.execute("SELECT * FROM completion_recoveries WHERE parent='parent'").fetchone())
            with transaction(self.state.db):
                self.assertTrue(recovery.begin(self.state, p, stage, 'parent'))
        row = self.state.db.execute("SELECT cycle FROM completion_recoveries WHERE parent='parent'").fetchone()
        self.assertEqual(row['cycle'], 1)
        self.assertEqual(self.factory.calls, [])

    def test_short_catalog_automatically_queues_only_missing_coverage(self):
        action=self.action()
        inventory=action['stages'][0]
        inventory['handoff']['outputs']['outline']['media_type']='application/json'
        catalog=self.stage('catalog',route='production')
        catalog['handoff']['outputs']['catalog']['media_type']='application/json'
        catalog['handoff']['inputs']=[dict(stage='outline',deliverable='outline',media_type='application/json',consumer='context')]
        action['stages'].insert(1,catalog)
        action['stages'][-1]['handoff']['inputs']=[dict(stage=s,deliverable=o,media_type='application/json',consumer='context') for s,o in [('outline','outline'),('catalog','catalog')]]
        action['completion']['coverage']=dict(inventory=dict(stage='outline',output='outline'),catalog=dict(stage='catalog',output='catalog'),options_per_item=3)
        p=self.create(action=action)
        self.complete_stage(p,'outline',body={'items':[{'id':'F01'}]})
        run,producer,reviewer=self.complete_stage(p,'catalog',body={'items':[{'id':'F01','options':[{'product_url':'https://store.example/one'}]}]},completion_expected=False)
        self.assertEqual(self.rt.task(run,'produce')['status'],'completed')
        self.assertEqual(self.rt.task(run,'review')['status'],'completed')
        step=self.step(p,'catalog')
        self.assertEqual(step['status'],'running')
        self.assertEqual(step['target_kind'],'plan_production')
        recovery_row=self.state.db.execute('SELECT * FROM completion_recoveries WHERE parent=?',(run,)).fetchone()
        self.assertIsNotNone(recovery_row)
        baseline=json.loads(recovery_row['baseline'])
        self.assertEqual(baseline['gaps'][0]['kind'],'delivery_coverage')
        self.assertEqual(baseline['gaps'][0]['missing'],[dict(item='F01',option=2),dict(item='F01',option=3)])
        self.assertEqual(self.step(p,'finish')['status'],'pending')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_missing_alternatives_produce_exact_work_slots_without_dropping_inventory(self):
        inventory={'items':[{'id':'F01'},{'id':'L01'}]}
        catalog={'items':[{'id':'F01','options':[{'product_url':'https://store.example/products/sofa'}]}]}
        result=delivery.coverage_slots(inventory,catalog,3)
        self.assertEqual(result['missing'],[{'item':'F01','option':2},{'item':'F01','option':3},
                                          {'item':'L01','option':1},{'item':'L01','option':2},{'item':'L01','option':3}])
        self.assertEqual(result['required_items'],2)
        self.assertIn('does not verify',result['semantic_evidence'])

    def test_duplicate_item_or_query_variants_cannot_pad_coverage(self):
        inventory={'items':[{'id':'F01'}]}
        for catalog in [
            {'items':[{'id':'F01','options':[]},{'id':'F01','options':[]}]},
            {'items':[{'id':'unrequested','options':[]}]},
            {'items':[{'id':'F01','options':[{'product_url':'https://store.example/product?color=black'},
                                           {'product_url':'https://store.example/product?color=white'}]}]},
            {'items':[{'id':'F01','options':[{'product_url':'https://user:secret@store.example/product'}]}]},
        ]:
            with self.subTest(catalog=catalog),self.assertRaises(ValueError):
                delivery.coverage_slots(inventory,catalog,3)

    def test_target_count_carries_zero_one_and_five_options_without_padding_or_dropping(self):
        inventory=dict(items=[dict(id='F01')])
        for count in (0,1,5):
            options=[dict(product_url='https://store.example/product-'+str(i)) for i in range(count)]
            result=delivery.coverage_slots(inventory,dict(items=[dict(id='F01',options=options)]),3,'target')
            self.assertEqual(len(result['slots']),count)
            self.assertEqual(result['missing'],[])
            self.assertEqual(len(result['shortfall']),max(0,3-count))
            self.assertEqual(result['unresolved_items'],['F01'] if count==0 else [])


class FrozenWorkerTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    stage=fixtures.Tests.stage
    step=fixtures.Tests.step
    action=Tests.action
    create=Tests.create

    def test_only_initial_frozen_worker_models_can_avoid_another_start(self):
        p=self.create()
        from tests.test_orchestrator import pair
        plan=pair(max_attempts=1)
        for t in plan['tasks']:t['limits']=dict(seconds=600,tool_calls=24)
        backend=dict(type='gemini-agent',model='frozen-model')
        plan['tasks'][0]['worker']=dict(version=1,executor='gemini-agent',requires=['files.text'],backend=backend)
        from orchestrator.executors import validate
        plan['tasks'][0]['tools']=validate(backend)
        with transaction(self.state.db):
            event=self.state.db.execute("SELECT id,detail FROM relay_pipeline_events WHERE pipeline=? AND kind='created'",(p['id'],)).fetchone()
            grant=json.loads(event['detail']);grant['automatic_worker_backends']=[plan['backend'],backend]
            self.state.db.execute('UPDATE relay_pipeline_events SET detail=? WHERE id=?',(json.dumps(grant),event['id']))
        row=dict(plan=json.dumps(plan),context=json.dumps(dict(delivery_completion_policy_version=1)))
        self.assertTrue(pipe.check_plan(self.state,p,self.step(p,'outline'),row))
        plan['tasks'][0]['worker']['backend']['model']='later-model';row['plan']=json.dumps(plan)
        self.assertFalse(pipe.check_plan(self.state,p,self.step(p,'outline'),row))
        plan['tasks'][0]['worker']['backend']['model']='frozen-model';row['plan']=json.dumps(plan);row['context']='{}'
        self.assertFalse(pipe.check_plan(self.state,p,self.step(p,'outline'),row))
