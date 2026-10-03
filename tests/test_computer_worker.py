"""Scripted model/native integration; synthetic text only, no paid requests."""
from contextlib import nullcontext
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
from orchestrator import contracts,executors,worker_capabilities
from orchestrator.computer_contract import resolve,validate
from orchestrator.computer_worker import run
from orchestrator.workers import atomic
from task_relay import computer_contract as native,computer_sessions as journal
from tests.test_computer_sessions import SessionHelper
from tests.test_computer_use import TARGET,Helper
from tests import test_gemini_executor as fixture


def policy():
    value={'helper':'/synthetic/Relay.app','identity':SessionHelper.identity,
        'spec':{'target':TARGET,'url':'https://example.com/one','allowed_urls':['https://example.com/one','https://example.com/two'],
                'actions':[],'capture':False,'local_fixture':False,'max_seconds':300}}
    value['selection']=native.digest(value)
    return value


class Model:
    def __init__(self,frozen,control,mode='normal'):
        self.frozen,self.control,self.mode=frozen,control,mode;self.calls=[]
    def request(self,path,payload,**kw):
        self.calls.append(copy.deepcopy(payload));n=len(self.calls)
        if n==1:
            initial=json.loads(payload['contents'][0]['parts'][0]['text'])
            previous=initial['computer_observation']
            name,args='computer_navigate',{'token':previous['token'],'url':'https://example.com/two'}
        elif n==2:
            previous=payload['contents'][-1]['parts'][0]['functionResponse']['response']
            if previous.get('refreshed'):
                name,args='computer_navigate',{'token':previous['token'],'url':'https://example.com/two'}
            else:name,args='computer_scroll',{'token':previous['token'],'direction':'down'}
        elif n==3:name,args='file_write',{'path':self.frozen['outputs'][0]['path'],'text':'Observed synthetic page evidence; no acceptance inferred.'}
        else:name,args='finish',{'report_json':json.dumps(fixture.report(self.frozen))}
        if self.mode in ('pause','stop','takeover') and n==1:atomic(self.control/'computer-owner-event.json',{'kind':self.mode,'created_at':'fixture'})
        return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}


class DynamicHelper(SessionHelper):
    def call(self,request):
        result=super().call(request)
        if len(self.calls)==2:
            old={**request['observation_request'],'expected_url':'https://example.com/one'}
            result['observation']=Helper().call(old)
            result.update(refreshed=True,action_executed=False)
        else:result.update(refreshed=False,action_executed=request['operation'] in ('navigate','scroll'))
        return result


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    def prepare(self):
        self.frozen.update(backend={'type':'gemini-computer','model':'fixture-model'},tools=['files','computer'],computer=policy(),run='run')
        db=sqlite3.connect(self.root/'state.sqlite',isolation_level=None);db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.execute('CREATE TABLE relay_pipelines(id TEXT PRIMARY KEY)');db.execute("INSERT INTO relay_pipelines VALUES ('job')")
        db.execute('CREATE TABLE relay_pipeline_steps(pipeline TEXT,target_kind TEXT,target TEXT)')
        db.execute("INSERT INTO relay_pipeline_steps VALUES ('job','production_run','run')")
        journal.initialize(db)
        return db
    def execute(self,db,helper,mode='normal'):
        model=Model(self.frozen,self.control,mode);self.model=model
        return run(self.frozen,self.control,db,client=model,config_reader=lambda:(fixture.CONFIG,self.frozen['backend']),helper=helper,lease_context=nullcontext())

    def test_planner_resolves_selected_window_and_requires_native_capability(self):
        selected=policy();self.assertEqual(resolve({'selection':selected['selection']},selected),selected)
        with self.assertRaises(ValueError):resolve({'selection':'invented'},selected)
        task=copy.deepcopy(self.frozen);task.pop('backend');task.pop('tools');task['computer']=selected
        task['worker']={'requires':['files.text','computer.use']}
        backend={'type':'gemini-computer','model':'fixture-model'}
        worker_capabilities.resolve(task,[worker_capabilities.entry(backend)],backend)
        validated=contracts.assignment(task)
        self.assertEqual(validated['resource'],'computer-safari')
        self.assertEqual(validated['tools'],['files','computer'])
        task['max_attempts']=2
        with self.assertRaisesRegex(ValueError,'one attempt'):contracts.assignment(task)
        self.assertFalse(worker_capabilities.matches(task,['files.text'],backend))

    def test_dynamic_refresh_then_explicit_model_decision_records_no_replay(self):
        db=self.prepare();helper=DynamicHelper(db)
        result=self.execute(db,helper)
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(self.model.calls),4)
        self.assertEqual([x['operation'] for x in helper.calls],['bind','navigate','navigate'])
        history=list(db.execute('SELECT * FROM relay_computer_actions ORDER BY ordinal'))
        refreshed=json.loads(history[1]['receipt']);self.assertTrue(refreshed['refreshed']);self.assertFalse(refreshed['action_executed'])
        self.assertEqual(refreshed['url'],'https://example.com/one')
        self.assertEqual(json.loads(history[1]['request'])['url'],'https://example.com/two')
        self.assertEqual(json.loads((self.control/'computer-result.json').read_text())['state'],'completed')
        self.assertEqual(helper.calls[2]['token'],'token-2')
        for row in history:journal._verify_receipt(row['receipt'])
        before=len(helper.calls);saved_receipt=(self.control/'computer-result.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        self.assertEqual(len(helper.calls),before)
        self.assertEqual((self.control/'computer-result.json').read_bytes(),saved_receipt)

    def test_ownership_pause_during_provider_request_prevents_next_action(self):
        db=self.prepare();helper=SessionHelper(db)
        with self.assertRaisesRegex(ValueError,'stopped'):self.execute(db,helper,'pause')
        self.assertEqual(len(helper.calls),1);self.assertEqual(len(self.model.calls),1)
        self.assertEqual(db.execute('SELECT state FROM relay_computer_assignments').fetchone()[0],'paused')
        self.assertEqual(db.execute("SELECT count(*) FROM relay_computer_decisions WHERE kind='owner_pause'").fetchone()[0],1)
        self.assertTrue((self.control/'api-01.response.json').exists())

    def test_uncertain_action_stops_provider_loop_and_survives_receipt(self):
        db=self.prepare()
        def fail(request,count):
            if count==2:raise TimeoutError('lost response')
        helper=SessionHelper(db,fail)
        with self.assertRaisesRegex(ValueError,'uncertain'):self.execute(db,helper)
        self.assertEqual(len(self.model.calls),1);self.assertEqual(len(helper.calls),2)
        receipt=json.loads((self.control/'computer-result.json').read_text())
        self.assertEqual(len(receipt['uncertain_actions']),1)
        self.assertEqual(receipt['state'],'blocked')

    def test_worker_uses_plan_owner_before_pipeline_projection_updates(self):
        db=self.prepare()
        db.execute('CREATE TABLE production_plans(id TEXT,run TEXT)')
        db.execute("INSERT INTO production_plans VALUES ('plan','run')")
        db.execute("UPDATE relay_pipeline_steps SET target_kind='plan_production',target='plan'")
        result=self.execute(db,SessionHelper(db))
        self.assertEqual(result['decision'],'delivered')
        self.assertEqual(db.execute('SELECT job FROM relay_computer_assignments').fetchone()[0],'job')

    def test_safari_research_counts_as_a_scoped_external_evidence_source(self):
        from task_relay.external_evidence import research_available,validate_plan
        payload={'original_request':'Verify public source catalog evidence online',
                 'options':{'worker_catalog':[worker_capabilities.entry({'type':'gemini-computer','model':'fixture'})]}}
        self.assertTrue(research_available(payload))
        validate_plan({'tasks':[{'id':'research','computer':policy(),'worker':{'requires':['computer.use']},'inputs':[]}]},payload)

    def test_factory_selects_native_worker_and_freezes_support(self):
        from orchestrator.adapters import GeminiFactory
        from orchestrator.computer_worker import support_hashes
        self.prepare()
        target=self.root/'launch-control'
        with patch.object(executors,'available'),patch.object(executors,'configured_worker',return_value=(fixture.CONFIG,self.frozen['backend'])):
            session=GeminiFactory().create(target,self.ws,self.frozen,self.frozen['backend'])
        launch=json.loads((target/'launch.json').read_text())
        self.assertTrue(launch['registered_command'][1].endswith('computer_worker.py'))
        self.assertEqual(launch['computer_support'],support_hashes())
        self.assertEqual(session['backend'],self.frozen['backend'])

    def test_stop_prevents_queued_action_and_retains_provider_reply(self):
        db=self.prepare();helper=SessionHelper(db)
        with self.assertRaisesRegex(ValueError,'stopped'):self.execute(db,helper,'stop')
        self.assertEqual(len(helper.calls),1)
        self.assertEqual(db.execute('SELECT state FROM relay_computer_assignments').fetchone()[0],'cancelled')
        self.assertTrue((self.control/'api-01.response.json').exists())

    def test_takeover_prevents_queued_action(self):
        db=self.prepare();helper=SessionHelper(db)
        with self.assertRaisesRegex(ValueError,'stopped'):self.execute(db,helper,'takeover')
        self.assertEqual(len(helper.calls),1)
        self.assertEqual(db.execute("SELECT count(*) FROM relay_computer_decisions WHERE kind='owner_takeover'").fetchone()[0],1)

    def test_stale_token_and_ungranted_url_never_claim_or_dispatch(self):
        from task_relay.computer_worker_session import Session
        db=self.prepare();helper=SessionHelper(db)
        ident=journal.approve(db,job='job',request_key='tools',exact_request='Read synthetic sources',spec=policy()['spec'],helper=helper.identity,output_root=self.root/'evidence',actor='fixture user')
        session=Session(db,ident,helper,self.control,'Fixture')
        session.call('bind','computer_observe',{'token':''})
        with self.assertRaisesRegex(ValueError,'Stale'):session.call('stale','computer_scroll',{'token':'old','direction':'down'})
        with self.assertRaisesRegex(ValueError,'grant'):session.call('outside','computer_navigate',{'token':'token-1','url':'https://other.example/'})
        self.assertEqual(len(helper.calls),1);self.assertEqual(len(journal.actions(db,ident)),1)
        session.close()

    def test_source_scope_cannot_be_expanded_by_model(self):
        selected=policy();selected['spec']['allowed_urls'].append('https://other.example/')
        with self.assertRaisesRegex(ValueError,'identity'):validate(selected)

from tests import test_production_planning as planning_fixture
from task_relay import production_planning as planning,computer_target

class PlanningTests(unittest.TestCase):
    setUp=planning_fixture.Tests.setUp
    tearDown=planning_fixture.Tests.tearDown
    request=planning_fixture.Tests.request
    action=planning_fixture.Tests.action
    queue=planning_fixture.Tests.queue
    row=planning_fixture.Tests.row
    response=planning_fixture.Tests.response

    def test_natural_plan_creates_computer_worker_from_frozen_host_selection(self):
        backend={'type':'gemini-computer','model':'fixture-model'}
        text={'type':'gemini-agent','model':'fixture-model'}
        catalog=[worker_capabilities.entry(b) for b in (backend,text)]
        with patch.object(worker_capabilities,'capture',return_value=catalog),patch.object(computer_target,'current',return_value=policy()):self.queue()
        response=self.response()
        for t in response['plan']['tasks']:
            t.pop('tools');t['worker']={'requires':['files.text']};t['limits']=executors.GEMINI_LIMITS.copy()
        task=response['plan']['tasks'][0]
        task['limits'].update(provider_requests=12,response_tokens=8192)
        task['computer']={'selection':policy()['selection']};task['worker']['requires'].append('computer.use')
        # Later local selection changes cannot silently alter the queued grant.
        with patch.object(computer_target,'current',return_value=None):
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        plan=json.loads(row['plan']);producer=plan['tasks'][0]
        self.assertEqual(producer['worker']['backend'],backend)
        self.assertEqual(producer['computer'],policy())
        self.assertEqual(plan['tasks'][1]['worker']['backend'],text)
        self.assertIn('Safari scope',planning.preview(row))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
