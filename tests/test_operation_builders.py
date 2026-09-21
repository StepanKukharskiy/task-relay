"""Typed operation compilation with tiny fixtures; no model execution/providers."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import contracts as c, execution, host_code
from task_relay import operation_builders as builders, planning_contract
from task_relay import production_planning as planning
from tests import test_production_planning as fixtures


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        del self.fail
        app=dict(available=True,blocker=None,evidence='Controlled fixture',version='fixture',interpreter='CPython',executable='/fixture/python',library_runtime={'version':'fixture'})
        from orchestrator import rhino3dm_script
        mock=patch.object(rhino3dm_script,'discover',return_value=app)
        mock.start();self.addCleanup(mock.stop)
        mock=patch('task_relay.host_evidence.application_signature',return_value={'fixture':True})
        mock.start();self.addCleanup(mock.stop)
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    start=fixtures.Tests.start
    click=fixtures.Tests.click

    def setup_plan(self,mode='create',seconds=600):
        self.queue(action=self.action(step_capabilities=[builders.CAPABILITY],task_seconds=seconds),
                   text='Execute the selected reciprocal pavilion script and independently review its model.')
        row=self.row();payload=json.loads(row['context'])
        checks=dict(version=1,mode=mode,file_version=8,expected_units='Meters',
                    expected_object_count=None,required_objects=[],preserve_objects=[],expected_dimensions={})
        root=self.rt.root/'inputs';root.mkdir()
        self.ids={}
        for name,body in [('model.py','# Controlled fixture; never executed.\n'),('checks.json',json.dumps(checks)),
                          ('source.3dm','not a real model'),('asset.json','{"reference":true}')]:
            file=root/name;file.write_text(body)
            aid=self.rt.register(file,'Selected fixture',path='selected/'+name)
            self.ids[name]=aid
            source=planning.source_entry(self.rt,aid,'selected/'+name,'Selected fixture','Exact selected input')
            payload['sources'].append(source)
            if name in ('model.py','checks.json'):
                payload['required_artifacts'].append(aid)
                payload['source_texts'].append(dict(artifact=aid,text=body))
        payload['operation_builder']=builders.freeze(payload)
        self.assertIsNotNone(payload['operation_builder'])
        payload['response_contract']=planning_contract.contract(payload['options'],payload['operation_builder'])
        self.save_context(payload)
        value=self.response();value['plan']=dict(operation=builders.CAPABILITY,
                   inputs=dict(script=self.ids['model.py'],checks=self.ids['checks.json']))
        if mode=='edit':value['plan']['inputs']['scene']=self.ids['source.3dm']
        return self.row(),value

    def save_context(self,payload):
        with self.state.db:
            self.state.db.execute('UPDATE production_plans SET context=?,context_hash=?,options=? WHERE id=?',
                (c.encoded(payload),c.digest(payload),c.encoded(payload['options']),self.row()['id']))

    def test_create_compiles_registry_constants_review_and_gate(self):
        row,value=self.setup_plan(seconds=300);original=copy.deepcopy(value)
        canonical,plan=planning.validate_result(json.dumps(value),row)
        host,review=plan['tasks'];spec=execution.REGISTRY[builders.CAPABILITY]
        self.assertEqual(value,original)
        self.assertEqual(host['execution']['version'],spec['version'])
        self.assertEqual(host['execution']['parameters']['scene_sha256'],None)
        self.assertEqual(host['execution']['parameters']['script_sha256'],self.rt.artifact(self.ids['model.py'])['sha256'])
        self.assertEqual({o['path']:o['media_type'] for o in host['outputs']},spec['outputs'])
        self.assertEqual(set(host['selection_outputs']),set(spec['outputs']))
        self.assertEqual(host['criteria'],spec['criteria'])
        self.assertEqual(host['limits']['seconds'],300)
        self.assertEqual(host['max_attempts'],1)
        self.assertEqual(review['review_of'],host['id'])
        self.assertEqual({i['output'] for i in review['inputs'] if 'output' in i},set(spec['outputs']))
        self.assertEqual(plan['origin']['operation_builder']['request'],original['plan'])
        self.assertIn('tasks',canonical['plan'])
        self.assertEqual(self.factory.calls,[])

    def test_invented_structure_unknown_artifacts_and_missing_slots_are_rejected(self):
        row,value=self.setup_plan()
        for field in ('tasks','execution','worker','permissions','criteria','version','limits','script_sha256'):
            injected=copy.deepcopy(value);injected['plan'][field]={}
            with self.subTest(field=field),self.assertRaises(builders.ContractError) as error:
                planning.validate_result(json.dumps(injected),row)
            self.assertEqual(error.exception.field,'$.plan.'+field)
        for slot in ('script','checks'):
            bad=copy.deepcopy(value);del bad['plan']['inputs'][slot]
            with self.assertRaises(builders.ContractError) as error:planning.validate_result(json.dumps(bad),row)
            self.assertEqual(error.exception.code,'missing_input')
            bad['plan']['inputs'][slot]='invented-artifact'
            with self.assertRaises(builders.ContractError):planning.validate_result(json.dumps(bad),row)
        canonical,_=planning.validate_result(json.dumps(value),row)
        with self.assertRaises(builders.ContractError):planning.validate_result(json.dumps(canonical),row)

    def test_edit_requires_scene_and_preserves_its_hash(self):
        row,value=self.setup_plan('edit');bad=copy.deepcopy(value);del bad['plan']['inputs']['scene']
        with self.assertRaisesRegex(builders.ContractError,'Select a captured .3dm'):planning.validate_result(json.dumps(bad),row)
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual(plan['tasks'][0]['execution']['parameters']['scene_sha256'],self.rt.artifact(self.ids['source.3dm'])['sha256'])

    def test_create_rejects_scene_and_duplicate_slots(self):
        row,value=self.setup_plan();value['plan']['inputs']['scene']=self.ids['source.3dm']
        with self.assertRaisesRegex(builders.ContractError,'Create checks'):planning.validate_result(json.dumps(value),row)
        del value['plan']['inputs']['scene'];value['plan']['inputs']['assets']=[self.ids['model.py']]
        with self.assertRaisesRegex(builders.ContractError,'only one input slot'):planning.validate_result(json.dumps(value),row)

    def test_assets_keep_alias_and_do_not_become_checks(self):
        row,value=self.setup_plan();value['plan']['inputs']['assets']=[self.ids['asset.json']]
        _,plan=planning.validate_result(json.dumps(value),row)
        item=next(i for i in plan['tasks'][0]['inputs'] if i.get('artifact')==self.ids['asset.json'])
        self.assertEqual(item['path'],'selected/asset.json');self.assertEqual(item['media_type'],'application/octet-stream')

    def test_frozen_registry_drift_cannot_silently_rebind(self):
        row,value=self.setup_plan()
        with patch.dict(execution.REGISTRY[builders.CAPABILITY],version=999),self.assertRaisesRegex(builders.ContractError,'contract changed'):
            planning.validate_result(json.dumps(value),row)

    def test_preparation_and_mixed_scopes_keep_generic_contract(self):
        row,value=self.setup_plan();payload=json.loads(row['context'])
        payload['source_texts']=[];self.assertIsNone(builders.freeze(payload))
        payload=json.loads(row['context']);payload['options']['step_capabilities'].append('rhino3dm.create')
        self.assertIsNone(builders.freeze(payload))

    def test_bounded_correction_has_field_receipt_and_preserves_raw_response(self):
        row,value=self.setup_plan();bad=copy.deepcopy(value);bad['plan']['permissions']='unrestricted_host'
        requests=[]
        def generate(row,payload):
            requests.append(copy.deepcopy(payload))
            return json.dumps(bad if len(requests)==1 else value),{'controlled':True}
        worker=planning.Worker(self.state,generate);worker.tick();worker.tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        detail=requests[1]['structural_correction']['detail']
        self.assertEqual(detail['field'],'$.plan.permissions')
        self.assertEqual(requests[0]['response_contract'],requests[1]['response_contract'])
        calls=self.state.db.execute('SELECT response FROM production_plan_calls ORDER BY number').fetchall()
        self.assertEqual([json.loads(x[0]) for x in calls],[bad,value])
        self.assertIn('tasks',json.loads(row['result'])['plan'])
        self.assertEqual(json.loads(row['plan'])['origin']['operation_builder']['request'],value['plan'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_enqueue_freezes_typed_slots_from_selected_artifacts(self):
        self.setup_plan()
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='needs_input' WHERE id='plan-1'")
        row=self.queue(2,self.action(step_capabilities=[builders.CAPABILITY],parent_id='plan-1',
            deliverables={'pavilion':'Standalone pavilion model'}))
        payload=json.loads(row['context']);policy=payload['operation_builder']
        self.assertEqual(policy['slots']['script'],[self.ids['model.py']])
        self.assertEqual(policy['slots']['checks'],[self.ids['checks.json']])
        value=self.response();value['plan']=dict(operation=builders.CAPABILITY,
            inputs=dict(script=self.ids['model.py'],checks=self.ids['checks.json']),deliverables={'pavilion':'model'})
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual(plan['deliverables']['pavilion']['output'],'delivery/candidate.3dm')
        self.assertIn(builders.INSTRUCTIONS,payload['planner_instructions'])

    def test_two_invalid_details_stop_without_execution(self):
        _,value=self.setup_plan();value['plan']['tools']=['shell']
        worker=planning.Worker(self.state,lambda *_:(json.dumps(value),{}))
        worker.tick();worker.tick();worker.tick()
        self.assertEqual(self.row()['status'],'blocked');self.assertEqual(self.row()['calls'],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_unresolved_input_does_not_build_an_execution(self):
        row,_=self.setup_plan()
        for decision in ('needs_input','blocked'):
            value=dict(decision=decision,message='Select the intended script.',plan=None)
            result,plan=planning.validate_result(json.dumps(value),row)
            self.assertEqual(result,value);self.assertIsNone(plan)

    def test_trusted_recovery_accepts_canonical_contract_but_still_checks_hashes(self):
        row,value=self.setup_plan();result,_=planning.validate_result(json.dumps(value),row)
        values=dict(row);values.update(parent_id='prior-fixture',status='ready')
        _,plan=planning.validate_recovery_result(result,values)
        self.assertEqual(plan['tasks'][0]['execution'],result['plan']['tasks'][0]['execution'])
        result['plan']['tasks'][0]['execution']['parameters']['script_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'hash differs|input type differs'):
            planning.validate_recovery_result(result,values)

    def test_builder_cannot_relabel_required_source_geometry_as_procedural(self):
        row,value=self.setup_plan('edit');payload=json.loads(row['context'])
        payload['required_artifacts'].append(self.ids['source.3dm'])
        self.save_context(payload)
        with self.assertRaisesRegex(ValueError,'source|procedural'):
            planning.validate_result(json.dumps(value),self.row())

    def test_text_only_worker_cannot_replace_binary_reviewer(self):
        from orchestrator import worker_capabilities
        from tests.test_gemini_executor import BACKEND
        row,value=self.setup_plan();payload=json.loads(row['context']);options=payload['options']
        options.update(backend=BACKEND,executor_locked=True,worker_catalog=[worker_capabilities.entry(BACKEND)])
        self.save_context(payload)
        with self.assertRaisesRegex(ValueError,'No eligible worker'):
            planning.validate_result(json.dumps(value),self.row())

    def test_source_mutation_rolls_back_start(self):
        from pathlib import Path
        from orchestrator.storage import transaction
        _,value=self.setup_plan()
        planning.Worker(self.state,lambda *_:(json.dumps(value),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        with self.state.db:
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
        blob=Path(self.rt.artifact(self.ids['model.py'])['blob']);blob.chmod(0o600)
        blob.write_text('# Changed after proposal')
        with self.assertRaisesRegex(ValueError,'changed'),transaction(self.state.db):
            planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_review_correction_returns_to_preparation_without_execution_schema(self):
        from pathlib import Path
        from orchestrator.storage import transaction
        from task_relay import production_control as pc, production_review_corrections as corrections
        _,value=self.setup_plan()
        planning.Worker(self.state,lambda *_:(json.dumps(value),{})).tick()
        row=self.row()
        with self.state.db:
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
        with transaction(self.state.db):planning.apply(self.state,row['token'],'start')
        production=pc.Worker(self.state,lambda _:self.rt);production.tick()
        attempt=self.rt.task('production-1','execute_model')['latest']
        self.factory.finish(attempt)
        self.factory.sessions[attempt]['status'].update(operation={'outcome':'completed'})
        production.tick()
        attempt=self.rt.task('production-1','review_model')['latest'];self.factory.finish(attempt,decision='revise')
        path=self.factory.sessions[attempt]['workspace']/'.relay/result.json';report=json.loads(path.read_text())
        report.update(summary='Fixture pavilion needs correction.',instruction='Correct the member spacing; preserve intended dimensions.')
        path.write_text(json.dumps(report));production.tick()
        calls=len(self.factory.calls);before=dict(self.row())
        with transaction(self.state.db):ident=corrections.propose(self.state,'production-1')
        corrected=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        self.assertEqual(corrected['status'],'ready')
        payload=json.loads(corrected['context']);plan=json.loads(corrected['plan'])
        self.assertNotIn('operation_builder',payload)
        self.assertEqual(payload['response_contract'],planning_contract.contract(payload['options']))
        self.assertTrue(all(not t.get('execution') for t in plan['tasks']))
        self.assertIn(builders.CAPABILITY,plan['deferred_operations'])
        self.assertEqual(len(self.factory.calls),calls)
        self.assertEqual(dict(self.row()),before)

    def test_start_requires_delivered_exact_code_and_is_idempotent(self):
        _,value=self.setup_plan()
        planning.Worker(self.state,lambda *_:(json.dumps(value),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.click(row['token'])
        self.assertEqual(self.row()['status'],'ready')
        with self.state.db:
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
        self.start(row);self.click(row['token'])
        self.assertEqual(self.row()['status'],'started',self.row()['error'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])
        task=self.rt.task('production-1','execute_model')
        self.assertIsNotNone(host_code.approved(self.rt,'production-1','execute_model',self.rt.spec(task)))


if __name__=='__main__':unittest.main()
