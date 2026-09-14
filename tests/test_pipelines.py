import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from bridge import State
from task_relay import pipelines as pipe
from task_relay import orchestrator_chat as chat, production_planning as planning
from task_relay import production_control as pc, production_selections as selections
from task_relay import browser_research, relay_channels
from task_relay.browser_jobs import Journal
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from tests import test_production_planning as fixtures


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        del self.fail
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    response=fixtures.Tests.response

    def stage(self,ident='outline',route='conversation',gate='none',caps=None):
        return dict(id=ident,instruction='Produce '+ident+' using the exact prior outputs.',route=route,gate=gate,
                    capabilities=caps or [],deliverables={ident:'Exact '+ident+' output'})

    def create(self,stages=None,planning_only=False):
        action=dict(kind='plan_pipeline',title='A user-defined outcome',planning_only=planning_only,
                    stages=stages or [self.stage(),self.stage('finish')])
        self.request(action,'Read the supplied brief, then create the requested outputs. Preserve source files.',1)
        p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertIsNotNone(p,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=1').fetchone()[0])
        return p

    def step(self,p,ident):
        return self.state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],ident)).fetchone()

    def answer(self,action):
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Bounded result','action':action})).tick()

    def result(self,text='Exact source-backed result.',choices=None):
        return dict(kind='pipeline_result',result=text,choices=choices or [])

    def test_request_extraction_drives_different_stage_orders_without_templates(self):
        p=self.create([self.stage('compare',gate='choice'),self.stage('explain')])
        self.assertIn('Preserve source files.',p['request'])
        self.assertEqual([s['id'] for s in json.loads(p['spec'])['stages']],['compare','explain'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_requests').fetchone()[0],0)
        choices=[dict(id='one',label='One',value='Complete concept one.'),dict(id='two',label='Two',value='Complete concept two.')]
        self.answer(self.result('Two proposed concepts.',choices))
        self.assertEqual(self.step(p,'compare')['status'],'awaiting_choice')
        pipe.tick(self.state);pipe.tick(self.state)
        self.assertIsNone(self.step(p,'explain')['request_id'])
        with transaction(self.state.db):pipe.choose(self.state,p['id'],'compare','two')
        pipe.tick(self.state)
        next_step=self.step(p,'explain');job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(next_step['request_id'],)).fetchone()
        self.assertIn('Complete concept two.',job['prompt']);self.assertIn(p['request'],job['prompt'])
        self.answer(self.result('Chosen concept explanation.'));pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'completed')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_requests').fetchone()[0],2)

    def test_choice_is_channel_owned_and_never_accepted_from_status(self):
        p=self.create([self.stage(gate='choice'),self.stage('finish')])
        self.answer(self.result(choices=[dict(id='a',label='A',value='A exact'),dict(id='b',label='B',value='B exact')]))
        other=relay_channels.ScopedState(self.state,'messages')
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'channel'):pipe.choose(other,p['id'],'outline','a')
        pipe.tick(self.state);self.assertEqual(self.step(p,'outline')['status'],'awaiting_choice')
        with transaction(self.state.db):pipe.choose(self.state,p['id'],'outline','a')
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'no longer'):pipe.choose(self.state,p['id'],'outline','a')

    def test_numeric_leading_stage_id_survives_dispatch_and_continuation(self):
        p=self.create([self.stage('3d_model'),self.stage('2D_summary')])
        self.assertEqual(json.loads(p['spec'])['stages'][0]['id'],'3d_model')
        self.answer(self.result('Source for the next stage.'))
        pipe.tick(self.state)
        s=self.step(p,'2D_summary');ctx=pipe.request_context(self.state,s['request_id'])
        self.assertEqual(ctx['inputs']['prior_results'],[{'id':'3d_model','result':'Source for the next stage.'}])
        self.answer(self.result('Final summary.'));pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'completed')

    def test_concept_result_has_one_delivery_with_selection_controls(self):
        p=self.create([self.stage(gate='choice'),self.stage('finish')])
        self.answer(self.result('Full program and options.',[
            dict(id='a',label='A',value='Option A'),dict(id='b',label='B',value='Option B')]))
        s=self.step(p,'outline')
        self.assertIsNone(self.state.db.execute('SELECT 1 FROM outbox WHERE id=?',('orchestrator:'+str(s['request_id']),)).fetchone())
        key=f'pipeline:{p["id"]}:outline:result'
        from task_relay.workflow_files import location_text
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox WHERE id=?',(key,)).fetchone()[0],
                         'Full program and options.\n\n'+location_text(self.state,p['id']))
        self.assertEqual(len(pipe.controls(self.state,key)['inline_keyboard']),3)

    def test_workflow_time_grant_is_frozen_and_legacy_extension_requires_start(self):
        p=self.create([self.stage('model','production'),self.stage('finish')])
        s=self.step(p,'model');plan={'tasks':[{'max_attempts':1,'limits':{'seconds':1800,'tool_calls':60}}]}
        row={'plan':json.dumps(plan)}
        self.assertTrue(pipe.check_plan(self.state,p,s,row))
        with transaction(self.state.db):
            receipt=self.state.db.execute("SELECT id,detail FROM relay_pipeline_events WHERE pipeline=? AND kind='created'",(p['id'],)).fetchone()
            detail=json.loads(receipt['detail']);del detail['automatic_task_seconds']
            self.state.db.execute('UPDATE relay_pipeline_events SET detail=? WHERE id=?',(json.dumps(detail),receipt['id']))
        self.assertFalse(pipe.check_plan(self.state,p,s,row))
        plan['tasks'][0]['limits']['seconds']=600;row={'plan':json.dumps(plan)}
        self.assertTrue(pipe.check_plan(self.state,p,s,row))

    def prepared_host_plan(self):
        value=self.response();produce,review=value['plan']['tasks']
        produce['outputs']=[dict(path='delivery/model.py',purpose='Exact script'),dict(path='delivery/checks.json',purpose='Exact checks')]
        produce['selection_outputs']=[o['path'] for o in produce['outputs']]
        review['inputs']=[dict(from_task=produce['id'],output=o['path'],path='candidate/'+Path(o['path']).name,purpose=o['purpose'],authority='Unaccepted candidate') for o in produce['outputs']]
        value['deferred_operations']={cap:'Run with the prepared exact-input host execution phase.' for cap in ('rhino.startup','rhino.run_python','rhino.inspect')}
        value['deliverable_map']={'model':{'deferred_operation':'rhino.run_python'}}
        return value

    def continued_preparation(self,host=True):
        from task_relay import production_continuations as cont
        caps=['rhino.startup','rhino.run_python','rhino.inspect'] if host else []
        p=self.create([self.stage('model','production','selection',caps),self.stage('finish')])
        self.answer(dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                         research_ids=[],planning_only=False,step_capabilities=caps,deliverables={'model':'Exact model output'}))
        stage=self.step(p,'model')
        response=self.prepared_host_plan() if host else self.response()
        if not host:response['deliverable_map']={'model':{'task':'produce','output':'output.txt'}}
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        self.bridge.flush(False);pipe.tick(self.state)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.factory.finish(self.rt.task(row['run'],'produce')['latest'],decision='blocked');worker.tick()
        pipe.tick(self.state)
        self.assertEqual(self.step(p,'model')['status'],'blocked')
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,status,created) VALUES (700,'Continue with the saved drafts.',?,'gemini','fixture','answered',100)",(row['run'],))
            cont.enqueue(self.state,{'id':700,'prompt':'Continue with the saved drafts.'},row['run'])
        worker.tick()
        link=self.state.db.execute('SELECT * FROM production_continuations WHERE parent=?',(row['run'],)).fetchone()
        self.assertEqual(link['status'],'registered')
        return p,row,link,worker

    def test_generic_file_continuation_advances_to_next_stage_without_an_extra_request(self):
        p,row,link,worker=self.continued_preparation(host=False);child=link['child']
        pipe.tick(self.state)
        self.factory.finish(self.rt.task(child,'produce')['latest']);worker.tick()
        self.factory.finish(self.rt.task(child,'review')['latest'],decision='accept');worker.tick()
        self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=?',(child,)).fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        self.state.db.close();self.state=State(self.root/'state.sqlite')
        pipe.tick(self.state);pipe.tick(self.state);pipe.tick(self.state)
        next_step=self.step(p,'finish');self.assertIsNotNone(next_step['request_id'])
        ctx=pipe.request_context(self.state,next_step['request_id'])
        self.assertEqual([s['artifact'] for s in ctx['inputs']['sources']],[card['artifact']])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='continuation_attached'").fetchone()[0],1)
        self.assertEqual(len(self.factory.calls),3)

    def test_registered_continuation_rejoins_workflow_and_plans_exact_selected_execution_once(self):
        from task_relay import production_status,production_stages
        p,row,link,worker=self.continued_preparation();child=link['child']
        parent_tasks=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_tasks WHERE run=?',(row['run'],))]
        pipe.tick(self.state)
        self.assertTrue(pipe.owns_run(self.state,child))
        self.assertEqual(self.step(p,'model')['target'],child)
        self.assertEqual(production_stages.planning_origin(self.state,child)['id'],row['id'])
        self.factory.finish(self.rt.task(child,'produce')['latest']);worker.tick()
        self.factory.finish(self.rt.task(child,'review')['latest'],decision='accept');worker.tick()
        pipe.tick(self.state)
        self.assertIsNone(self.state.db.execute('SELECT plan_id FROM production_stage_links WHERE parent=?',(child,)).fetchone())
        self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=?',(child,)).fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        text=production_status.current(self.state,child)[1]
        self.assertIn('Relay will prepare the execution plan',text)
        self.assertNotIn('describe the next stage',text)
        self.assertNotIn('use Plan execution',text)
        pipe.tick(self.state);pipe.tick(self.state)
        stage=self.step(p,'model');self.assertEqual(stage['target_kind'],'plan_production')
        target=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        self.assertEqual(target['status'],'queued',stage['error'])
        self.assertTrue(pipe.owns_run(self.state,child))
        self.assertNotIn('use Plan execution',production_status.current(self.state,child)[1])
        context=json.loads(target['context']);selected={r[0] for r in self.state.db.execute('SELECT artifact FROM production_decisions WHERE run=?',(child,))}
        self.assertEqual(len(selected),2)
        self.assertTrue(selected<={s['artifact'] for s in context['sources']})
        self.assertEqual(context['previous_stage']['run'],child)
        self.assertEqual(context['pipeline_step']['gate'],'selection')
        self.assertEqual(set(json.loads(target['options'])['step_capabilities']),{'rhino.startup','rhino.run_python','rhino.inspect'})
        self.assertIn(row['request'],target['request'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_stage_links WHERE parent=?',(child,)).fetchone()[0],1)
        self.assertEqual(parent_tasks,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_tasks WHERE run=?',(row['run'],))])
        self.assertIsNone(self.step(p,'finish')['request_id'])
        self.assertEqual(len(self.factory.calls),3) # failed producer + continuation producer/reviewer; no host dispatch

    def test_continuation_attachment_is_atomic_and_does_not_resume_paused_cancelled_or_unreceipted_work(self):
        p,row,link,worker=self.continued_preparation()
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with transaction(self.state.db):pipe.attach_continuations(self.state);raise RuntimeError('rollback')
        self.assertEqual(self.step(p,'model')['target'],row['id'])
        for status in ('paused','cancelled'):
            with transaction(self.state.db):self.state.db.execute('UPDATE relay_pipelines SET status=? WHERE id=?',(status,p['id']))
            pipe.tick(self.state);self.assertEqual(self.step(p,'model')['target'],row['id'])
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE production_continuations SET status='queued' WHERE id=?",(link['id'],))
        pipe.tick(self.state);self.assertEqual(self.step(p,'model')['target'],row['id'])
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_continuations SET status='registered' WHERE id=?",(link['id'],))
            self.state.db.execute("UPDATE relay_request_channels SET channel='messages' WHERE request_id=?",(link['id'],))
            self.state.db.execute("INSERT OR IGNORE INTO relay_request_channels VALUES (?,'messages')",(link['id'],))
        pipe.tick(self.state);self.assertEqual(self.step(p,'model')['target'],row['id'])
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_request_channels SET channel='telegram' WHERE request_id=?",(link['id'],))
            self.state.db.execute("DELETE FROM production_events WHERE run=? AND kind='production_continuation_created'",(link['child'],))
        pipe.tick(self.state);self.assertEqual(self.step(p,'model')['target'],row['id'])

    def test_host_group_deferral_and_explicit_saved_plan_recovery_preserve_history(self):
        caps=['rhino.startup','rhino.run_python','rhino.inspect']
        p=self.create([self.stage('model','production','selection',caps),self.stage('finish')])
        self.answer(dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],planning_only=False,step_capabilities=caps,deliverables={'model':'Exact model output'}))
        step=self.step(p,'model');row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(step['target'],)).fetchone()
        value=self.prepared_host_plan();result,plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual(set(plan['deferred_operations']),set(caps))
        partial=copy.deepcopy(value);del partial['deferred_operations']['rhino.startup'];del partial['deferred_operations']['rhino.inspect']
        with self.assertRaises(ValueError) as caught:planning.validate_result(json.dumps(partial),row)
        self.assertIn('rhino.inspect, rhino.startup',str(caught.exception))
        self.assertNotIn('rhino.run_python',str(caught.exception))
        for cap in ('gemini.image','rhino.startup'):
            bad=copy.deepcopy(value);bad['deferred_operations']={cap:'Not a complete exact-input host group.'}
            if cap=='gemini.image':bad['deferred_operations']['rhino.run_python']='Prepare script first.'
            fake=dict(row);options=json.loads(row['options']);options['step_capabilities']=list(bad['deferred_operations']);fake['options']=json.dumps(options)
            with self.assertRaises(ValueError):planning.validate_result(json.dumps(bad),fake)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='blocked',calls=2,error='old validation failure' WHERE id=?",(row['id'],))
            for number,response in enumerate((value,partial),1):
                self.state.db.execute('INSERT INTO production_plan_calls VALUES (?,?,?,?,?,?,?)',(row['id'],number,row['context'],json.dumps(response),'{}','old validation failure',1))
        pipe.tick(self.state)
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_plan_calls')]
        with transaction(self.state.db):pipe.control(self.state,p['id'],'recover_planning')
        successor=self.step(p,'model')['target'];self.assertNotEqual(successor,row['id'])
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_plan_calls')],before)
        self.assertEqual(self.state.db.execute('SELECT status,calls FROM production_plans WHERE id=?',(row['id'],)).fetchone()[:],('blocked',2))
        new=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(successor,)).fetchone()
        self.assertEqual(new['status'],'ready');self.assertEqual(new['calls'],0)
        self.assertEqual(json.loads(new['context'])['recovered_proposal']['call'],1)
        self.assertEqual(json.loads(new['options'])['deliverables'],{'model':'Exact model output'})
        self.assertEqual(len(self.factory.calls),0)
        with transaction(self.state.db),self.assertRaises(ValueError):pipe.control(self.state,p['id'],'recover_planning')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)

    def rejected_planning_fixture(self):
        from task_relay.gemini import ProviderError
        caps=['rhino.startup','rhino.run_python','rhino.inspect']
        p=self.create([self.stage('model','production','selection',caps),self.stage('finish')])
        self.answer(dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],planning_only=False,step_capabilities=caps,deliverables={'model':'Exact model output'}))
        def reject(*_):raise ProviderError(429)
        planning.Worker(self.state,reject).tick()
        pipe.tick(self.state)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(self.step(p,'model')['target'],)).fetchone()
        self.assertEqual(row['status'],'blocked')
        return p,row

    def test_explicit_rate_limit_retry_preserves_frozen_plan_and_failure(self):
        p,old=self.rejected_planning_fixture()
        original=dict(old)
        with transaction(self.state.db):
            pipe.control(self.state,p['id'],'retry_planning',request='Continue my saved project exactly.')
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(self.step(p,'model')['target'],)).fetchone()
        for field in ('request','context','context_hash','options','provider','model','parent_id'):
            self.assertEqual(successor[field],old[field],field)
        self.assertEqual(successor['status'],'queued');self.assertEqual(successor['calls'],0)
        self.assertIsNone(successor['run'])
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old['id'],)).fetchone()),original)
        receipt=json.loads(self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='planning_retry_requested'").fetchone()[0])
        self.assertEqual(receipt['request'],'Continue my saved project exactly.')
        self.assertEqual(self.step(p,'finish')['status'],'pending')
        with transaction(self.state.db),self.assertRaises(ValueError):
            pipe.control(self.state,p['id'],'retry_planning',request='duplicate')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)
        self.assertEqual(len(self.factory.calls),0)

    def test_rate_limit_retry_command_is_deduplicated_without_interpretation(self):
        from types import SimpleNamespace
        p,old=self.rejected_planning_fixture()
        bridge=SimpleNamespace(state=self.state,send=lambda *_:None)
        command='retry-plan '+p['id']
        exact='  /workflow '+command+'  \n'
        chat.workflow_command(bridge,command,903,source_request=exact)
        chat.workflow_command(bridge,command,903)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='planning_retry_requested'").fetchone()[0],1)
        receipt=json.loads(self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='planning_retry_requested'").fetchone()[0])
        self.assertEqual(receipt['request'],exact)

    def test_explicit_continue_action_queues_retry_without_running_workers(self):
        p,old=self.rejected_planning_fixture()
        pipe.tick(self.state);pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.request(dict(kind='pipeline_control',pipeline_id=p['id'],verb='retry_planning'),'Continue my saved house project',904)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=904').fetchone()[0],'answered')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_retry_refuses_uncertain_submission_and_cross_channel(self):
        p,old=self.rejected_planning_fixture()
        from task_relay.relay_channels import ScopedState
        with transaction(self.state.db),self.assertRaises(ValueError):
            pipe.control(ScopedState(self.state,'messages'),p['id'],'retry_planning',request='Continue')
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='uncertain' WHERE id=?",(old['id'],))
        with transaction(self.state.db),self.assertRaises(ValueError):
            pipe.control(self.state,p['id'],'retry_planning',request='Continue')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_old_recovery_error_explains_control_failure_without_rephrasing(self):
        p,old=self.rejected_planning_fixture()
        self.request(dict(kind='pipeline_control',pipeline_id=p['id'],verb='recover_planning'),'Continue',804)
        result=self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=804').fetchone()[0]
        self.assertIn('No saved proposal currently validates',result)
        self.assertNotIn('Could not interpret',result)

    def test_retry_button_is_tied_to_the_rejected_plan(self):
        from types import SimpleNamespace
        p,old=self.rejected_planning_fixture()
        key='pipeline:'+p['id']+':model:blocked'
        button=pipe.controls(self.state,key)['inline_keyboard'][0][0]
        self.assertEqual(button['text'],'Retry planning')
        self.assertLessEqual(len(button['callback_data'].encode()),64)
        replies=[]
        bridge=SimpleNamespace(state=self.state,telegram=SimpleNamespace(call=lambda *a,**k:replies.append(k['text'])))
        q={'data':button['callback_data'],'id':'click','from':{'id':self.state.get('user_id')},
           'message':{'chat':{'id':self.state.get('chat_id'),'type':'private'}}}
        pipe.callback(bridge,{'callback_query':q})
        successor=self.step(p,'model')['target']
        from task_relay.gemini import ProviderError
        def reject(*_):raise ProviderError(429)
        planning.Worker(self.state,reject).tick();pipe.tick(self.state)
        pipe.callback(bridge,{'callback_query':q})
        self.assertIn('stale',replies[-1])
        self.assertEqual(self.step(p,'model')['target'],successor)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],2)

    def test_invalid_pipeline_reports_validation_without_dispatch(self):
        action=dict(kind='plan_pipeline',title='Duplicate stage',planning_only=False,
                    stages=[self.stage('3d_model'),self.stage('3d_model')])
        self.request(action,'Create a model and summary.',1)
        row=self.state.db.execute('SELECT status,response,answer FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertEqual(row['status'],'failed')
        self.assertEqual(json.loads(row['response'])['action'],action)
        self.assertIn('could not validate the proposed workflow',row['answer'])
        self.assertNotIn('invalid response format',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)
        for ident in ('../escape','a:b',' space','a'*51):
            action['stages'][1]['id']=ident
            with self.assertRaises(pipe.PipelineValidationError):pipe.validate(action,{})

    def test_human_feedback_is_processed_before_next_stage(self):
        p=self.create()
        self.answer(self.result())
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (?,?,?,?,?,?)',
                (44,'Pause this workflow',p['id'],'gemini','fixture',100))
        pipe.tick(self.state)
        self.assertIsNone(self.step(p,'finish')['request_id'])
        self.answer(dict(kind='pipeline_control',pipeline_id=p['id'],verb='pause'))
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'paused')
        self.assertIsNone(self.step(p,'finish')['request_id'])

    def test_messages_clarification_retains_workflow_context(self):
        from task_relay.messages_orchestrator import OrchestratorRouter
        p=self.create()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET channel='messages'")
            self.state.db.execute("INSERT OR REPLACE INTO relay_request_channels VALUES (1,'messages')")
        self.answer(None)
        waiting=self.step(p,'outline');self.assertEqual(waiting['status'],'awaiting_input')
        router=OrchestratorRouter(state=self.state,require_ready=False)
        with patch.object(chat,'provider',return_value=('gemini','fixture')):
            ident=router.submit('clarify-workflow','Use the provided local folder.')
        self.assertEqual(self.step(p,'outline')['request_id'],ident)
        self.assertEqual(pipe.request_context(self.state,ident)['original_request'],p['request'])
        self.answer(self.result())
        self.assertEqual(self.step(p,'outline')['status'],'completed')

    def test_complete_research_receipt_advances_once_across_restart(self):
        p=self.create([self.stage('research','browser_research'),self.stage('summarize')])
        with patch.object(browser_research,'managed_enabled',return_value=True):
            self.answer(dict(kind='browser_research',site='perplexity',query='Bounded source question?'))
        s=self.step(p,'research');receipt=s['target'];self.assertEqual(s['status'],'running')
        with transaction(self.state.db):
            Journal(self.state.db).update(receipt,'completed',url='https://www.perplexity.ai/search/11111111-1111-1111-1111-111111111111',result='Exact answer with [citation](https://example.org/source).')
        pipe.tick(self.state)
        self.state.db.close();self.state=State(self.root/'state.sqlite')
        pipe.tick(self.state);pipe.tick(self.state)
        s=self.step(p,'summarize');context=pipe.request_context(self.state,s['request_id'])
        self.assertIn('Exact answer with [citation]',context['inputs']['prior_results'][0]['result'])
        self.assertIn(receipt,context['inputs']['prior_results'][0]['result'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_requests').fetchone()[0],2)

    def test_uncertain_submission_and_interpreter_failure_never_retry(self):
        p=self.create([self.stage('research','browser_research'),self.stage('summarize')])
        with patch.object(browser_research,'managed_enabled',return_value=True):self.answer(dict(kind='browser_research',site='perplexity',query='Q'))
        with transaction(self.state.db):Journal(self.state.db).update(self.step(p,'research')['target'],'uncertain',error='Click outcome unknown')
        for _ in range(3):pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'blocked')
        self.assertIsNone(self.step(p,'summarize')['request_id'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM browser_jobs').fetchone()[0],1)
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'recovery'):pipe.control(self.state,p['id'],'resume')

    def test_pause_and_cancel_block_queued_dispatch_and_resume_is_explicit(self):
        p=self.create();pipe.tick(self.state);s=self.step(p,'outline')
        job=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(s['request_id'],)).fetchone())
        with transaction(self.state.db):pipe.control(self.state,p['id'],'pause')
        with self.assertRaisesRegex(ValueError,'paused'):pipe.guard(self.state,job,self.result())
        pipe.tick(self.state);self.assertIsNone(self.step(p,'finish')['request_id'])
        with transaction(self.state.db):pipe.control(self.state,p['id'],'resume')
        pipe.guard(self.state,job,self.result())
        with transaction(self.state.db):pipe.control(self.state,p['id'],'cancel')
        with self.assertRaisesRegex(ValueError,'cancelled'):pipe.guard(self.state,job,self.result())

    def test_planning_only_does_not_run_and_queue_rollback_is_atomic(self):
        p=self.create(planning_only=True);pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_requests').fetchone()[0],0)
        with transaction(self.state.db):pipe.control(self.state,p['id'],'resume')
        p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone();s=self.step(p,'outline')
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with transaction(self.state.db):
                pipe.enqueue_step(self.state,p,s);raise RuntimeError('rollback')
        self.assertIsNone(self.step(p,'outline')['request_id'])
        pipe.tick(self.state);pipe.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_requests').fetchone()[0],1)

    def test_stage_cannot_dispatch_unplanned_kind_or_drop_deliverables(self):
        p=self.create([self.stage('report','production'),self.stage('summary')]);pipe.tick(self.state)
        job=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(self.step(p,'report')['request_id'],)).fetchone())
        with self.assertRaisesRegex(ValueError,'scope'):pipe.guard(self.state,job,{'kind':'generate_image'})
        with self.assertRaisesRegex(ValueError,'deliverables'):pipe.guard(self.state,job,dict(kind='plan_production',step_capabilities=[],deliverables={}))
        with self.assertRaisesRegex(ValueError,'nested'):pipe.validate(json.loads(p['spec']),{'pipeline_step':{'stage':1}})

    def test_production_selection_queues_next_stage_and_freezes_selected_bytes(self):
        p=self.create([self.stage('report','production','selection'),self.stage('summary')])
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],artifact_ids=[],planning_only=False,step_capabilities=[],deliverables={'report':'Exact report output'})
        self.answer(action);stage=self.step(p,'report');self.assertEqual(stage['status'],'running')
        response=self.response();response['deliverable_map']={'report':{'task':'produce','output':'output.txt'}}
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        self.assertEqual(row['status'],'ready',row['error'])
        self.bridge.flush(False);pipe.tick(self.state)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        self.assertEqual(row['status'],'started')
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.factory.finish(self.rt.task(row['run'],'produce')['latest']);worker.tick()
        self.factory.finish(self.rt.task(row['run'],'review')['latest'],decision='accept');worker.tick()
        pipe.tick(self.state);self.assertIsNone(self.step(p,'summary')['request_id'])
        self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=?',(row['run'],)).fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        pipe.tick(self.state);pipe.tick(self.state)
        next_step=self.step(p,'summary');self.assertIsNotNone(next_step['request_id'])
        job=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(next_step['request_id'],)).fetchone())
        records=pipe.frozen_sources(self.state,job)
        artifact=self.rt.artifact(card['artifact'])
        selected=next(r for r in records if r['sha256']==artifact['sha256'])
        self.assertEqual(Path(selected['path']).read_bytes(),Path(artifact['blob']).read_bytes())
        self.assertEqual(len(self.factory.calls),2)
        # A changed registered source stops downstream dispatch; no substitution.
        Path(artifact['blob']).chmod(0o600);Path(artifact['blob']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):pipe.frozen_sources(self.state,job)

    def test_clarification_is_not_completion_and_keeps_original_request(self):
        p=self.create();self.answer(None)
        self.assertEqual(self.step(p,'outline')['status'],'awaiting_input')
        pipe.tick(self.state);self.assertIsNone(self.step(p,'finish')['request_id'])
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (2,?,?,?,?,0)',('Use the local brief.',p['id'],'gemini','fixture'))
            pipe.bind_reply(self.state,2,p['id'])
        ctx=pipe.request_context(self.state,2);self.assertEqual(ctx['original_request'],p['request'])
        self.answer(self.result('Read requested source.'))
        self.assertEqual(self.step(p,'outline')['status'],'completed')

    def test_host_code_never_uses_automatic_workflow_grant(self):
        p=self.create([self.stage('report','production','selection'),self.stage('summary')]);s=self.step(p,'report')
        plan={'tasks':[dict(max_attempts=1,limits={'seconds':600,'tool_calls':1},execution={'capability':'rhino.run_python'})]}
        spec=json.loads(p['spec']);spec['stages'][0]['capabilities']=['rhino.run_python'];p=dict(p);p['spec']=json.dumps(spec)
        self.assertFalse(pipe.check_plan(self.state,p,s,{'plan':json.dumps(plan)}))
        plan['tasks'][0]['max_attempts']=2
        with self.assertRaisesRegex(ValueError,'bounds'):pipe.check_plan(self.state,p,s,{'plan':json.dumps(plan)})


    def test_paused_queue_does_not_consume_provider_or_fail_on_resume(self):
        p=self.create();pipe.tick(self.state)
        with transaction(self.state.db):pipe.control(self.state,p['id'],'pause')
        def never(*args):raise AssertionError('Paused workflow called provider')
        chat.Worker(self.state,never).tick()
        self.assertEqual(self.step(p,'outline')['status'],'queued')
        with transaction(self.state.db):pipe.control(self.state,p['id'],'resume')
        self.answer(self.result('Finished after resume.'))
        self.assertEqual(self.step(p,'outline')['status'],'completed')

    def test_image_selection_freezes_one_candidate_and_queues_next_without_prompt(self):
        from task_relay import gemini, backends
        from tests.test_gemini import PNG
        root=self.root/'generated';root.mkdir()
        p=self.create([self.stage('visual','image','selection'),self.stage('compose')])
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'image':'test-image'}}),patch.object(backends,'WORKSPACES',self.root/'projects'):
            self.answer(dict(kind='generate_image',reference_ids=[],artifact_ids=[]))
        s=self.step(p,'visual');job=self.state.db.execute('SELECT * FROM backend_jobs WHERE id=?',(s['target'],)).fetchone()
        with patch.object(gemini,'GENERATED',root):
            with transaction(self.state.db):
                for i in range(2):
                    path=root/f'candidate-{i}.png';path.write_bytes(PNG)
                    gemini.artifact(self.state,job['thread_id'],job['id'],'output',path,path.name,'image/png')
                self.state.db.execute("UPDATE backend_jobs SET status='completed' WHERE id=?",(job['id'],))
            pipe.tick(self.state);s=self.step(p,'visual');self.assertEqual(s['status'],'awaiting_choice')
            choice=json.loads(s['choices'])[1]['id'];pipe.tick(self.state)
            self.assertIsNone(self.step(p,'compose')['request_id'])
            with transaction(self.state.db),self.assertRaisesRegex(ValueError,'complete image'):pipe.choose(self.state,p['id'],'visual',choice)
            self.bridge.flush(False);self.bridge.flush_media()
            with transaction(self.state.db):pipe.choose(self.state,p['id'],'visual',choice)
            pipe.tick(self.state);pipe.tick(self.state)
            next_step=self.step(p,'compose');ctx=pipe.request_context(self.state,next_step['request_id'])
            self.assertEqual([a['artifact'] for a in ctx['inputs']['sources']],[choice])
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)
            job=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(next_step['request_id'],)).fetchone())
            records=pipe.frozen_sources(self.state,job)
            self.assertTrue(any(Path(r['path']).read_bytes()==PNG for r in records))

    def test_changed_image_or_missing_reference_is_not_silently_replaced(self):
        p=self.create([self.stage('visual','image','selection'),self.stage('compose')]);pipe.tick(self.state)
        s=self.step(p,'visual');job=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(s['request_id'],)).fetchone())
        with transaction(self.state.db):
            self.state.db.execute('UPDATE relay_pipeline_requests SET inputs=? WHERE request_id=?',(json.dumps({'sources':[{'artifact':'selected-image','media_type':'image/png'}],'prior_results':[]}),job['id']))
        with patch.object(pipe,'artifact_source',return_value={'artifact':'selected-image','media_type':'image/png'}):
            with self.assertRaisesRegex(ValueError,'exact frozen'):pipe.guard(self.state,job,dict(kind='generate_image',reference_ids=[],artifact_ids=['older-image']))
            with self.assertRaisesRegex(ValueError,'exact frozen'):pipe.guard(self.state,job,dict(kind='generate_image',reference_ids=[],artifact_ids=[]))

    def test_scope_validation_rejects_duplicate_unknown_and_nested_stages(self):
        action=dict(kind='plan_pipeline',title='Plan',planning_only=False,stages=[self.stage(),self.stage()])
        with self.assertRaises(ValueError):pipe.validate(action,{})
        action['stages'][1]['id']='second';action['stages'][1]['capabilities']=['invented.operation']
        with self.assertRaises(ValueError):pipe.validate(action,{})




    def recovered_selected_stage(self, select=True, direct=False):
        stage_spec=self.stage('report','production','selection');stage_spec['deliverables']['details']='Exact supporting output'
        p=self.create([stage_spec,self.stage('summary')])
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],artifact_ids=[],planning_only=False,step_capabilities=[],deliverables={'report':'Exact report output','details':'Exact supporting output'})
        self.answer(action);stage=self.step(p,'report')
        response=self.response();response['deliverable_map']={'report':{'task':'produce','output':'output.txt'},'details':{'task':'produce','output':'details.txt'}}
        producer,review=response['plan']['tasks']
        producer['outputs'].append({'path':'details.txt','purpose':'Selected supporting file'})
        producer['selection_outputs']=['output.txt','details.txt']
        review['inputs'].append(dict(from_task='produce',output='details.txt',path='details.txt',purpose='Inspect supporting file',authority='Unaccepted candidate'))
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        self.bridge.flush(False);pipe.tick(self.state)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        self.assertEqual(row['status'],'started',row['error'])
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.factory.finish(self.rt.task(row['run'],'produce')['latest']);worker.tick()
        # Preserve the parent blocker left by the old scheduler while the child recovers.
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='report'",(p['id'],))
            if direct:self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target=? WHERE pipeline=? AND id='report'",(row['run'],p['id']))
        self.factory.finish(self.rt.task(row['run'],'review')['latest'],decision='accept');worker.tick()
        self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=?',(row['run'],)).fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        if select:
            with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        return p,row,card,mid

    def test_completed_recovery_resumes_parent_once_with_exact_selected_set(self):
        p,row,card,mid=self.recovered_selected_stage()
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts ORDER BY id')]
        from task_relay import production_status
        self.assertNotIn('describe the next stage',production_status.current(self.state,row['run']))
        pipe.tick(self.state);pipe.tick(self.state)
        step=self.step(p,'summary');self.assertIsNotNone(step['request_id'])
        inputs=pipe.request_context(self.state,step['request_id'])['inputs']['sources']
        selected={r[0] for r in self.state.db.execute('SELECT artifact FROM production_decisions WHERE run=?',(row['run'],))}
        self.assertEqual(len(selected),2);self.assertEqual({i['artifact'] for i in inputs},selected)
        self.assertEqual(before,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts ORDER BY id')])
        self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='production_recovery_reconciled'").fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_requests WHERE step=?',('summary',)).fetchone()[0],1)

    def test_recovered_run_still_waits_for_user_selection(self):
        p,row,card,mid=self.recovered_selected_stage(select=False)
        pipe.tick(self.state);self.assertEqual(self.step(p,'report')['status'],'blocked')
        self.assertIsNone(self.step(p,'summary')['request_id'])
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        pipe.tick(self.state);self.assertIsNotNone(self.step(p,'summary')['request_id'])

    def test_recovery_reconciliation_is_atomic_and_respects_pause_cancel(self):
        p,row,card,mid=self.recovered_selected_stage(direct=True)
        with self.assertRaises(RuntimeError),transaction(self.state.db):
            pipe.reconcile_completed_production(self.state);raise RuntimeError('rollback')
        self.assertEqual(self.step(p,'report')['status'],'blocked')
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='production_recovery_reconciled'").fetchone()[0],0)
        for status in ('paused','cancelled'):
            with transaction(self.state.db):self.state.db.execute('UPDATE relay_pipelines SET status=? WHERE id=?',(status,p['id']))
            pipe.tick(self.state);self.assertIsNone(self.step(p,'summary')['request_id'])
            self.assertIn(status,pipe.continuation_text(self.state,row['run']))
        with transaction(self.state.db):self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
        pipe.tick(self.state);self.assertIsNotNone(self.step(p,'summary')['request_id'])

    def test_recovery_does_not_clear_real_failure_or_accept_changed_artifact(self):
        p,row,card,mid=self.recovered_selected_stage()
        with transaction(self.state.db):self.state.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id='produce'",(row['run'],))
        pipe.tick(self.state);self.assertIsNone(self.step(p,'summary')['request_id'])
        with transaction(self.state.db):self.state.db.execute("UPDATE production_tasks SET status='completed' WHERE run=? AND id='produce'",(row['run'],))
        artifact=self.rt.artifact(card['artifact']);path=Path(artifact['blob']);path.chmod(0o600);path.write_text('Changed bytes')
        pipe.tick(self.state);pipe.tick(self.state)
        self.assertEqual(self.step(p,'report')['status'],'blocked')
        self.assertIsNone(self.step(p,'summary')['request_id'])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='production_recovery_reconciled'").fetchone()[0],0)


if __name__=='__main__':unittest.main()
