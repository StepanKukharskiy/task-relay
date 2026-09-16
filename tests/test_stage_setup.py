"""Worker-specific source limits and saved local setup recovery; no live calls."""
import copy
import json
import unittest
from unittest.mock import patch
from orchestrator import executors
from orchestrator.storage import transaction
from task_relay import pipelines,production_planning as planning,routing_inputs
from tests import test_production_planning as fixtures,test_pipelines as pipeline_fixtures
from tests.test_browser_screenshots import capture_graph
from tests.test_gemini_executor import CONFIG


class InputsTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request;action=fixtures.Tests.action;queue=fixtures.Tests.queue
    row=fixtures.Tests.row;response=fixtures.Tests.response

    def browser_plan(self,suffix='.zip',raw=None):
        asset=self.rt.root/('previous-stage'+suffix)
        asset.write_bytes(raw if raw is not None else b'x'*(executors.MAX_INPUT_BYTES+1))
        original=routing_inputs.freeze
        def freeze(state,job,*args,**kwargs):
            return original(state,job,*args,**kwargs)+routing_inputs.capture(state,job,
                [(asset,asset.name,'Exact upstream source',None,None)],section='fixture')
        backend={'type':'gemini-agent','model':'fixture-model'}
        with patch.object(executors,'configured',return_value=(CONFIG,backend)),patch.object(executors,'available'),patch.object(routing_inputs,'freeze',side_effect=freeze):
            row=self.queue(action=self.action(executor='gemini-browser'),text='Capture the requested public map. Retain earlier workflow sources.')
        result=self.response();result['plan']['tasks']=capture_graph()['tasks']
        return row,result

    def test_large_upstream_bundle_is_retained_without_becoming_browser_text(self):
        row,result=self.browser_plan();payload=json.loads(row['context'])
        bundle=next(s for s in payload['sources'] if s['path'].endswith('.zip'))
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertTrue(all(bundle['artifact'] not in {i.get('artifact') for i in t['inputs']} for t in plan['tasks']))
        self.assertIn(bundle['artifact'],payload['required_artifacts'])
        planning.validate_bound_worker_inputs(self.rt,plan,payload)
        self.assertEqual(self.rt.artifact(bundle['artifact'])['sha256'],bundle['sha256'])
        bad=copy.deepcopy(result)
        bad['plan']['tasks'][0]['inputs']=[dict(artifact=bundle['artifact'],path='explicit.zip',purpose='Explicit binary',authority='User-selected source')]
        with self.assertRaises(ValueError):planning.validate_result(json.dumps(bad),row)

    def test_real_text_limit_still_applies_after_binding(self):
        row,result=self.browser_plan('.txt')
        with self.assertRaisesRegex(ValueError,'512 KB'):planning.validate_result(json.dumps(result),row)

    def test_non_utf8_assigned_text_rejected_before_worker_creation(self):
        row,result=self.browser_plan('.txt',b'\xff\xfe not UTF-8')
        _,plan=planning.validate_result(json.dumps(result),row)
        with self.assertRaisesRegex(ValueError,'UTF-8'):planning.validate_bound_worker_inputs(self.rt,plan,json.loads(row['context']))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)


class RecoveryTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request;response=fixtures.Tests.response
    create=pipeline_fixtures.Tests.create;stage=pipeline_fixtures.Tests.stage
    step=pipeline_fixtures.Tests.step;answer=pipeline_fixtures.Tests.answer

    def stopped(self):
        p=self.create([self.stage('maps','production'),self.stage('deck')])
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                    research_ids=[],planning_only=False,deliverables={'maps':'Exact maps output'})
        with patch.object(planning,'enqueue',side_effect=ValueError('API text input pack exceeds 512 KB.')):
            self.answer(action)
        pipelines.tick(self.state)
        s=self.step(p,'maps')
        self.assertIn('planning setup failed: API text input pack exceeds 512 KB',s['error'])
        self.assertIsNone(s['target'])
        return p,s

    def test_recover_uses_exact_saved_action_and_keeps_failed_receipt(self):
        p,s=self.stopped()
        old=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(s['request_id'],)).fetchone())
        error=dict(self.state.db.execute('SELECT * FROM orchestrator_chat_errors WHERE job_id=?',(s['request_id'],)).fetchone())
        self.assertIn('Recover stage setup',json.dumps(pipelines.controls(self.state,f"pipeline:{p['id']}:maps:blocked")))
        view=next(v for v in pipelines.catalog(self.state) if v['id']==p['id'])
        self.assertTrue(view['stages'][0]['setup_recovery_available'])
        with transaction(self.state.db):pipelines.control(self.state,p['id'],'recover_planning',request='Recover this saved setup.')
        current=self.step(p,'maps');plan=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(current['target'],)).fetchone()
        self.assertEqual(plan['status'],'queued')
        self.assertEqual(plan['request'],old['prompt'])
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(old['id'],)).fetchone()),old)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chat_errors WHERE job_id=?',(old['id'],)).fetchone()),error)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(len(self.factory.calls),0)
        with self.assertRaises(ValueError),transaction(self.state.db):pipelines.control(self.state,p['id'],'recover_planning')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_uncertain_and_provider_failures_are_not_replayed(self):
        p,s=self.stopped()
        with self.state.db:self.state.db.execute("UPDATE orchestrator_chats SET status='uncertain' WHERE id=?",(s['request_id'],))
        self.assertIsNone(pipelines.setup_failure(self.state,s))
        with self.state.db:
            self.state.db.execute("UPDATE orchestrator_chats SET status='failed' WHERE id=?",(s['request_id'],))
            self.state.db.execute("UPDATE orchestrator_chat_errors SET phase='provider' WHERE job_id=?",(s['request_id'],))
        with self.assertRaises(ValueError),transaction(self.state.db):pipelines.control(self.state,p['id'],'recover_planning')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)


class RateLimitTests(unittest.TestCase):
    setUp=pipeline_fixtures.Tests.setUp;tearDown=pipeline_fixtures.Tests.tearDown
    request=fixtures.Tests.request
    create=pipeline_fixtures.Tests.create;stage=pipeline_fixtures.Tests.stage
    step=pipeline_fixtures.Tests.step;answer=pipeline_fixtures.Tests.answer
    result=pipeline_fixtures.Tests.result

    def stopped(self,route='image'):
        from task_relay import orchestrator_chat as chat,gemini
        p=self.create([self.stage('research'),self.stage('visual',route,'selection' if route=='image' else 'none'),self.stage('deck')])
        self.answer(self.result('Completed original research'))
        def reject(*_):raise gemini.ProviderError(429)
        chat.Worker(self.state,reject).tick();pipelines.tick(self.state)
        s=self.step(p,'visual');self.assertEqual(s['status'],'blocked')
        self.assertIsNone(s['target'])
        return p,s

    def test_explicit_continue_retries_interpretation_preserving_completed_work_and_evidence(self):
        p,s=self.stopped()
        old=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(s['request_id'],)).fetchone())
        research=dict(self.step(p,'research'))
        inputs=self.state.db.execute('SELECT inputs FROM relay_pipeline_requests WHERE request_id=?',(old['id'],)).fetchone()[0]
        error=dict(self.state.db.execute('SELECT * FROM orchestrator_chat_errors WHERE job_id=?',(old['id'],)).fetchone())
        self.assertIn('Retry stage',json.dumps(pipelines.controls(self.state,f"pipeline:{p['id']}:visual:blocked")))
        self.request(dict(kind='pipeline_control',pipeline_id=p['id'],verb='retry_planning'),'continue this workflow',904)
        current=self.step(p,'visual');self.assertEqual(current['status'],'queued')
        new=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(current['request_id'],)).fetchone()
        for key in ('prompt','provider','model','focus'):self.assertEqual(new[key],old[key])
        self.assertEqual(dict(self.step(p,'research')),research)
        self.assertEqual(self.state.db.execute('SELECT inputs FROM relay_pipeline_requests WHERE request_id=?',(new['id'],)).fetchone()[0],inputs)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(old['id'],)).fetchone()),old)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chat_errors WHERE job_id=?',(old['id'],)).fetchone()),error)
        self.assertEqual(self.step(p,'deck')['status'],'pending')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_image_requests').fetchone()[0],0)
        self.assertEqual(len(self.factory.calls),0)
        with transaction(self.state.db),self.assertRaises(ValueError):pipelines.control(self.state,p['id'],'retry_planning',request='duplicate')

    def test_retry_can_complete_a_conversation_stage_and_continue(self):
        p,s=self.stopped('conversation')
        with transaction(self.state.db):pipelines.control(self.state,p['id'],'retry_planning',request='Continue')
        self.answer(self.result('Recovered result'))
        self.assertEqual(self.step(p,'visual')['status'],'completed')
        pipelines.tick(self.state);self.assertEqual(self.step(p,'deck')['status'],'queued')

    def test_retry_requires_explicit_request_and_rolls_back_atomically(self):
        p,s=self.stopped()
        before=self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        with transaction(self.state.db),self.assertRaises(ValueError):pipelines.control(self.state,p['id'],'retry_planning')
        with self.assertRaisesRegex(RuntimeError,'rollback'),transaction(self.state.db):
            pipelines.control(self.state,p['id'],'retry_planning',request='Continue');raise RuntimeError('rollback')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],before)
        self.assertEqual(self.step(p,'visual')['request_id'],s['request_id'])

    def test_uncertain_response_or_dispatched_target_cannot_retry(self):
        p,s=self.stopped()
        for status,response in [('uncertain',None),('failed','{"partial":"response"}')]:
            with transaction(self.state.db):self.state.db.execute('UPDATE orchestrator_chats SET status=?,response=? WHERE id=?',(status,response,s['request_id']))
            self.assertIsNone(pipelines.rate_limited_stage(self.state,s))
        with transaction(self.state.db):self.state.db.execute("UPDATE orchestrator_chats SET status='failed',response=NULL WHERE id=?",(s['request_id'],))
        self.assertIsNone(pipelines.rate_limited_stage(self.state,{**dict(s),'target':'already-dispatched'}))
        with transaction(self.state.db):self.state.db.execute("UPDATE orchestrator_chat_errors SET message='Gemini request failed (timeout)' WHERE job_id=?",(s['request_id'],))
        self.assertIsNone(pipelines.rate_limited_stage(self.state,s))

    def test_wrong_channel_and_changed_input_are_rejected(self):
        from task_relay.relay_channels import ScopedState
        p,s=self.stopped()
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'channel'):
            pipelines.control(ScopedState(self.state,'messages'),p['id'],'retry_planning',request='Continue')
        with transaction(self.state.db):
            old=json.loads(self.state.db.execute('SELECT inputs FROM relay_pipeline_requests WHERE request_id=?',(s['request_id'],)).fetchone()[0])
            old['sources']=[{'artifact':'missing','sha256':'a'*64,'bytes':1}]
            self.state.db.execute('UPDATE relay_pipeline_requests SET inputs=? WHERE request_id=?',(json.dumps(old),s['request_id']))
        with transaction(self.state.db),self.assertRaises(ValueError):pipelines.control(self.state,p['id'],'retry_planning',request='Continue')

    def test_old_retry_button_cannot_retry_a_second_rate_limit(self):
        from task_relay import orchestrator_chat as chat,gemini
        p,s=self.stopped()
        button=pipelines.controls(self.state,f"pipeline:{p['id']}:visual:blocked")['inline_keyboard'][0][0]['callback_data']
        self.assertLessEqual(len(button.encode()),64)
        update={'callback_query':{'id':'retry','data':button,'from':{'id':7},'message':{'chat':{'id':7,'type':'private'}}}}
        pipelines.callback(self.bridge,update)
        def reject(*_):raise gemini.ProviderError(429)
        chat.Worker(self.state,reject).tick();pipelines.tick(self.state)
        current=dict(self.step(p,'visual'));self.assertEqual(current['status'],'blocked')
        self.assertNotEqual(current['request_id'],s['request_id'])
        count=self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        pipelines.callback(self.bridge,update)
        self.assertEqual(dict(self.step(p,'visual')),current)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],count)
