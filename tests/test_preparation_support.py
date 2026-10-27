import copy
import json
import unittest
from unittest.mock import patch
from orchestrator import browser_images,execution
from task_relay import preparation_support as support,production_planning
from tests.test_orchestrator import Tests as RuntimeTests,pair
from tests.test_mixed_execution import operation
from tests import test_pipelines,test_production_planning


class CheckerTests(unittest.TestCase):
    def test_frozen_local_checker_agrees_with_production_without_executor_or_network(self):
        namespace={};exec(browser_images.validator_source(),namespace)
        value=dict(schema=browser_images.SCHEMA,job='fixture',subjects=[dict(id='chair',label='Chair',query='Chair')],candidates=[])
        for mutation in ('valid','extra','private','missing_provenance'):
            candidate=copy.deepcopy(value)
            if mutation=='extra':candidate['guessed_field']=1
            if mutation in ('private','missing_provenance'):
                candidate['candidates']=[dict(subject='chair',download_url='https://example.com/chair.jpg',source_url='https://example.com/chair',observed_url='https://example.com/chair',observation='page-hash',action_id='recorded-page',title='Chair')]
                if mutation=='private':candidate['candidates'][0]['download_url']='https://127.0.0.1/chair.jpg'
                else:candidate['candidates'][0]['observation']=''
            for checker in (browser_images.validate_manifest,namespace['validate_manifest']):
                if mutation=='valid':self.assertEqual(checker(candidate),candidate)
                else:
                    with self.assertRaises(ValueError):checker(candidate)
        self.assertEqual(support.documents('images.fetch',{'version':999}),{})

    def test_helpers_reach_preparer_and_its_review_only(self):
        plan=dict(tasks=[dict(id='prepare'),dict(id='review',review_of='prepare'),dict(id='unrelated'),
             dict(id='fetch',execution={'capability':'images.fetch'},inputs=[{'from_task':'prepare','output':'manifest.json'}])])
        sources=[dict(artifact='request',request_context=True),dict(artifact='schema',operation_support='images.fetch'),dict(artifact='other',operation_support='pptx.create')]
        scope=dict(assignment_input_policy_version=1,sources=sources);ids=[s['artifact'] for s in sources]
        for task in plan['tasks']:
            expected=['request','schema'] if task['id'] in ('prepare','review') else ['request']
            self.assertEqual(production_planning.assignment_required_artifacts(task,plan,scope,ids),expected)


class RecoveryTests(unittest.TestCase):
    setUp=RuntimeTests.setUp
    tearDown=RuntimeTests.tearDown

    def failed(self):
        graph=pair();producer,review=graph['tasks'];producer['outputs'][0].update(path='manifest.json',media_type='application/json')
        review['inputs'][0].update(output='manifest.json',media_type='application/json')
        fetch=operation('fetch','images.fetch',[dict(from_task='produce',output='manifest.json',path='manifest.json',purpose='Prepared data',authority='Unaccepted input',media_type='application/json')],['produce','review'])
        fetch['outputs']=[dict(path='photos.zip',purpose='Photos',media_type='application/zip')]
        graph['tasks'].append(fetch);self.rt.create(graph);self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid,decision='blocked');self.rt.tick('demo')
        spec=copy.deepcopy(execution.REGISTRY['images.fetch']);spec['id']='images.fetch'
        return aid,dict(delivery_completion_policy_version=1,graph_operations=[spec])

    def test_exact_failed_attempt_and_draft_are_preserved_then_only_remaining_attempt_runs(self):
        aid,scope=self.failed();old=self.rt.spec(self.rt.task('demo','produce'));artifacts=[dict(a) for a in self.rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(aid,))]
        with self.rt.transaction():receipt=support.repair(self.rt,'demo',scope)
        self.assertTrue(receipt);self.assertEqual(self.rt.task('demo','produce')['attempts'],1)
        spec=self.rt.spec(self.rt.task('demo','produce'))
        for key in ('criteria','limits','max_attempts'):self.assertEqual(spec[key],old[key])
        self.assertEqual([dict(a) for a in self.rt.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(aid,))],artifacts)
        self.assertEqual(len([i for i in spec['inputs'] if i['path'].startswith('operation-support/')]),2)
        with self.rt.transaction():self.assertIsNone(support.repair(self.rt,'demo',scope))
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','produce')['attempts'],2);self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(self.rt.task('demo','fetch')['attempts'],0)

    def test_paused_unknown_or_exhausted_work_is_never_requeued(self):
        aid,scope=self.failed()
        for variation in ('paused','unknown','exhausted'):
            with self.rt.transaction():
                if variation=='paused':self.rt.db.execute("UPDATE production_runs SET status='paused' WHERE id='demo'")
                elif variation=='unknown':self.rt.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run='demo' AND id='fetch'")
                else:self.rt.db.execute("UPDATE production_tasks SET attempts=2 WHERE run='demo' AND id='produce'")
                self.assertIsNone(support.repair(self.rt,'demo',scope))
                self.rt.db.execute("UPDATE production_runs SET status='active' WHERE id='demo'");self.rt.db.execute("UPDATE production_tasks SET status='queued' WHERE run='demo' AND id='fetch'")
        self.assertEqual(len(self.factory.calls),1)


class ControllerTests(unittest.TestCase):
    setUp=test_pipelines.Tests.setUp
    tearDown=test_pipelines.Tests.tearDown
    request=test_pipelines.Tests.request
    stage=test_pipelines.Tests.stage
    create=test_pipelines.Tests.create
    step=test_pipelines.Tests.step
    queue=test_production_planning.Tests.queue
    action=test_production_planning.Tests.action
    row=test_production_planning.Tests.row

    def blocked(self):
        p=self.create([self.stage('photos',route='production',caps=['images.fetch']),self.stage('finish')])
        original=self.queue(17,self.action(step_capabilities=['images.fetch']))
        graph=pair();producer,review=graph['tasks'];producer['outputs'][0].update(path='manifest.json',media_type='application/json')
        review['inputs'][0].update(output='manifest.json',media_type='application/json')
        fetch=operation('fetch','images.fetch',[dict(from_task='produce',output='manifest.json',path='manifest.json',purpose='Prepared data',authority='Unaccepted input',media_type='application/json')],['produce','review'])
        fetch['outputs']=[dict(path='photos.zip',purpose='Photos',media_type='application/zip')];graph['tasks'].append(fetch)
        self.rt.create(graph);self.rt.tick('demo');aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid,decision='blocked');self.rt.tick('demo')
        scope=json.loads(original['context']);scope['delivery_completion_policy_version']=1;scope['pipeline_step']=json.loads(p['spec'])['stages'][0]
        options=json.loads(original['options']);options['job_request_id']=17
        from orchestrator.contracts import encoded,digest
        frozen=json.loads(self.state.db.execute("SELECT plan FROM production_runs WHERE id='demo'").fetchone()[0])
        with self.state.db:
            self.state.db.execute("UPDATE production_plans SET status='started',context=?,context_hash=?,options=?,plan=?,plan_hash=?,run='demo' WHERE id=?",(encoded(scope),digest(scope),encoded(options),encoded(frozen),digest(frozen),original['id']))
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='plan_production',target=? WHERE pipeline=? AND id='photos'",(original['id'],p['id']))
            self.state.db.execute('INSERT INTO relay_pipeline_requests VALUES (?,?,?,?)',(17,p['id'],'photos','{}'))
            self.state.db.execute('INSERT INTO completion_recovery_grants VALUES (?,?,?)',(p['id'],'Finish with internal corrections','{}'))
            event=self.state.db.execute("SELECT id,detail FROM relay_pipeline_events WHERE pipeline=? AND kind='created'",(p['id'],)).fetchone();detail=json.loads(event['detail']);detail['automatic_task_attempts']=2
            self.state.db.execute('UPDATE relay_pipeline_events SET detail=? WHERE id=?',(encoded(detail),event['id']))
        return p,original,aid

    def test_controller_restores_only_same_stage_under_grant_and_dispatches_after_commit(self):
        p,original,aid=self.blocked()
        support.reconcile(self.state)
        self.assertEqual(self.step(p,'photos')['status'],'running')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],1);self.assertEqual(len(self.factory.calls),1)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?',(original['id'],)).fetchone()[0],'started')
        proof=self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND kind='preparation_support_recovered'",(p['id'],)).fetchone()
        self.assertFalse(json.loads(proof[0])['proof']['attempts_reset'])
        self.assertTrue(self.state.get('production-enabled:demo'))
        self.rt.tick('demo');self.assertEqual(len(self.factory.calls),2)

    def test_human_control_intervention_prevents_automatic_repair(self):
        p,original,aid=self.blocked();self.state.put('production-control-epoch:demo',1);self.state.db.commit()
        support.reconcile(self.state)
        self.assertEqual(self.step(p,'photos')['status'],'blocked');self.assertEqual(len(self.factory.calls),1)

    def test_unexecuted_recovery_remains_saved_while_original_remaining_attempt_resumes(self):
        p,original,aid=self.blocked()
        from orchestrator.contracts import encoded,digest
        values=dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(original['id'],)).fetchone())
        scope=json.loads(values['context']);scope['completion_recovery']={'parent':'demo'}
        values.update(id='blocked-recovery',request_id=18,status='blocked',run=None,token='synthetic-recovery-token',context=encoded(scope),context_hash=digest(scope),result='{"decision":"blocked","message":"Missing contract","plan":null}')
        with self.state.db:
            self.state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
            self.state.db.execute("UPDATE relay_pipeline_steps SET target='blocked-recovery' WHERE pipeline=? AND id='photos'",(p['id'],))
        support.reconcile(self.state)
        self.assertEqual(self.step(p,'photos')['target'],original['id'])
        retained=self.state.db.execute("SELECT * FROM production_plans WHERE id='blocked-recovery'").fetchone()
        self.assertEqual(dict(retained),values)
        self.assertEqual(self.rt.task('demo','produce')['attempts'],1);self.assertEqual(len(self.factory.calls),1)


if __name__=='__main__':unittest.main()
