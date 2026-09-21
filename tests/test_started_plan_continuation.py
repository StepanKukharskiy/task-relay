"""Started planning records resolve to their exact blocked production, not new plans."""
import copy
import json
import unittest
from unittest.mock import Mock
from task_relay import production_planning as planning, orchestrator_chat as chat
from tests import test_rhino_launch_recovery as native


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
            research_ids=[],reference_ids=[],planning_only=False,parent_id='plan-old',previous_run='prep',
            step_capabilities=['rhino.run_python'],deliverables={'model':'Editable model'})
        options={k:v for k,v in self.action.items() if k not in ('parent_id','reference_ids')}
        self.snap=dict(production_plans=[dict(id='plan-old',status='started',run='run-current',options=options)],
            production_runs=[dict(name='run-current',status='blocked'),dict(name='prep',status='completed')],
            capabilities={'graph_operations':[dict(id='rhino.run_python',available=True)]})

    def test_exact_saved_run_wins_over_old_preparation_reference(self):
        request='Continue my landscape model'
        self.assertEqual(planning.started_plan_continuation(self.action,self.snap,request),
            dict(kind='continue_production',workflow='run-current',items=None,direction=request))
        self.assertEqual(self.action['previous_run'],'prep')
        with self.assertRaises(planning.StartedPlanningRequest):
            chat.interpret(json.dumps({'answer':'Plan','action':self.action}),self.snap)

    def test_new_scope_and_source_choices_are_never_silently_discarded(self):
        cases=[{'deliverables':{'new':'Different output'}},{'step_capabilities':[]},{'planning_only':True},
               {'previous_run':'another-project'},{'task_seconds':1800}, {'starter_workflow':'new'},
               {'artifact_ids':['new']},{'reference_ids':['upload']},{'research_ids':[99]},
               {'project':'/new'},{'executor':'another-model'},{'surprise':True}]
        for change in cases:
            with self.subTest(change=change):
                try:result=planning.started_plan_continuation({**self.action,**change},self.snap,'Continue')
                except ValueError:continue
                self.assertIsNone(result)

    def test_unknown_ambiguous_active_uncertain_and_stage_requests_are_not_rebound(self):
        for status in ('active','uncertain','completed','awaiting_user'):
            snap=copy.deepcopy(self.snap);snap['production_runs'][0]['status']=status
            self.assertIsNone(planning.started_plan_continuation(self.action,snap,'Continue'))
        for status in ('ready','blocked','needs_input','discarded'):
            snap=copy.deepcopy(self.snap);snap['production_plans'][0]['status']=status
            self.assertIsNone(planning.started_plan_continuation(self.action,snap,'Continue'))
        for change in ({'production_plans':[]},{'production_runs':[]},{'pipeline_step':{'id':'stage'}},
                       {'production_plans':self.snap['production_plans']*2}):
            self.assertIsNone(planning.started_plan_continuation(self.action,{**self.snap,**change},'Continue'))


class WorkerTests(unittest.TestCase):
    setUp=native.Tests.setUp
    tearDown=native.Tests.tearDown
    request=native.Tests.request
    action=native.Tests.action
    queue=native.Tests.queue
    row=native.Tests.row
    response=native.Tests.response
    setup_plan=native.Tests.setup_plan
    delivered=native.Tests.delivered
    stopped=native.Tests.stopped

    def test_message_reaches_recovery_without_new_provider_plan_or_execution(self):
        run=self.stopped();parent=self.row();options=json.loads(parent['options'])
        action=self.action(parent_id=parent['id'],step_capabilities=options['step_capabilities'])
        original='Continue my landscape model'
        raw=json.dumps({'answer':'An execution plan is ready.', 'action':action})
        attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        self.bridge.process({'update_id':99,'message':{'text':original,'chat':{'id':7,'type':'private'},'from':{'id':7}}})
        generator=Mock(return_value=raw);worker=chat.Worker(self.state,generator);worker.tick();worker.tick()
        row=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=99').fetchone()
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertIn('Native execution recovery ready',row['answer'])
        self.assertEqual(row['response'],raw);self.assertEqual(row['prompt'],original)
        routing=self.state.get('orchestrator-continuation-routing:99')
        self.assertEqual(routing['normalized_action']['workflow'],run)
        self.assertEqual(routing['normalized_action']['direction'],original)
        self.assertEqual(routing['original_action'],action)
        self.assertEqual(generator.call_count,1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(attempts,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')])
        fresh=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(parent['id'],)).fetchone()
        self.assertEqual(fresh['status'],'ready');self.assertIsNone(fresh['run']);self.assertEqual(fresh['calls'],0)
        self.assertEqual(len(self.factory.calls),1)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?',(parent['id'],)).fetchone()[0],'started')

    def test_changed_execution_during_interpretation_does_not_create_a_successor(self):
        run=self.stopped();parent=self.row();options=json.loads(parent['options'])
        action=self.action(parent_id=parent['id'],step_capabilities=options['step_capabilities'])
        self.bridge.process({'update_id':99,'message':{'text':'Continue','chat':{'id':7,'type':'private'},'from':{'id':7}}})
        def respond(*args):
            with self.state.db:
                self.state.put('production-enabled:'+run,'concurrent-user-change')
            return json.dumps({'answer':'Plan', 'action':action})
        chat.Worker(self.state,respond).tick()
        row=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=99').fetchone()
        self.assertEqual(row['status'],'failed')
        self.assertIn('changed while interpreting',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertIsNone(self.state.get('orchestrator-continuation-routing:99'))
