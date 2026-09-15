"""Scripted browser model and planner tests; no provider calls or live websites."""
from contextlib import nullcontext,closing
import copy
import json
import sqlite3
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from orchestrator import executors,contracts as c
from orchestrator.adapters import GeminiFactory,ExecutionFactory
from orchestrator.runtime import Runtime
from orchestrator.browser_worker import run
from orchestrator.workers import atomic
from tests import test_gemini_executor as file_fixtures
from tests.test_gemini_executor import CONFIG,report
from tests.test_general_browser import browser_graph,Driver,policy
from tests import test_executor_planning as planning_fixtures
from task_relay import production_planning as planning


class ScriptedBrowser:
    def __init__(self,frozen):self.frozen=frozen;self.calls=[]
    def request(self,path,payload,**kwargs):
        self.calls.append(copy.deepcopy(payload));n=len(self.calls)
        if n==1:name,args='browser_open',{'url':self.frozen['browser']['origins'][0]+'/form'}
        elif self.frozen.get('review_of'):
            if n==2:name,args='file_write',{'path':self.frozen['outputs'][0]['path'],'text':'Independently observed the fixture page.'}
            else:name,args='finish',report(self.frozen)
        elif n in (2,3):
            previous=payload['contents'][-1]['parts'][0]['functionResponse']['response']
            name='browser_fill' if n==2 else 'browser_click'
            descriptor=next(x for x in previous['controls'] if x['tag']==('INPUT' if n==2 else 'BUTTON'))
            args=dict(tab=previous['tab'],observation=previous['observation'],ref=descriptor['ref'],purpose='Submit the requested fixture text once')
            if n==2:args['text']='Fixture request'
        elif n==4:name,args='file_write',{'path':self.frozen['outputs'][0]['path'],'text':'Observed the fixture result. No user acceptance inferred.'}
        else:name,args='finish',report(self.frozen)
        return {'usageMetadata':{'promptTokenCount':5,'candidatesTokenCount':3},'candidates':[{'finishReason':'STOP',
            'content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args,'id':'response-'+str(n)}}]}}]}


class SupervisorFixture(GeminiFactory):
    def __init__(self,mode='normal'):super().__init__();self.mode=mode
    def create(self,control,workspace,frozen,backend):
        from task_relay.host import HOST
        with patch.object(HOST,'browser_python',return_value=sys.executable):
            session=super().create(control,workspace,frozen,backend)
        path=Path(control)/'launch.json';launch=json.loads(path.read_text())
        # The supervisor runs in the isolated workspace. Use a service-owned
        # fixture entry point that explicitly bootstraps this checkout.
        launch['registered_command']=[sys.executable,str(Path(__file__).resolve()),'fixture',str(control),str(workspace),self.mode]
        atomic(path,launch);return session


class Tests(unittest.TestCase):
    setUp=file_fixtures.Tests.setUp
    tearDown=file_fixtures.Tests.tearDown

    def browser_frozen(self):
        frozen=c.assignment(browser_graph()['tasks'][0])
        frozen.update(assignment_id='fixture',backend=browser_graph()['backend'],workspace=str(self.ws))
        return frozen

    def test_loop_records_actions_and_usage_and_preserves_uncertainty(self):
        frozen=self.browser_frozen();client=ScriptedBrowser(frozen);driver=Driver()
        with closing(sqlite3.connect(':memory:')) as db:
            result=run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(driver))
            self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.calls),5)
            from orchestrator.browser_contract import WEBSITE_TASK_INSTRUCTIONS
            self.assertIn(WEBSITE_TASK_INSTRUCTIONS,client.calls[0]['systemInstruction']['parts'][0]['text'])
            self.assertEqual([a[0] for a in driver.actions],['fill','click'])
            receipt=json.loads((self.control/'browser-result.json').read_text())
            self.assertEqual(len(receipt['actions']),3);self.assertFalse(receipt['uncertain_actions'])
            self.assertEqual(len(list(self.control.glob('api-*.response.json'))),5)
            with self.assertRaisesRegex(ValueError,'replay'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(driver))
            self.assertEqual(len(client.calls),5)

    def test_uncertain_browser_tool_stops_model_loop_before_any_retry(self):
        frozen=self.browser_frozen();client=ScriptedBrowser(frozen);driver=Driver();driver.fail=True
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaisesRegex(ValueError,'uncertain'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(driver))
            self.assertEqual(len(client.calls),2);self.assertEqual(len(driver.actions),1)
            self.assertFalse((self.ws/'.relay/result.json').exists())
            self.assertTrue(json.loads((self.control/'browser-result.json').read_text())['uncertain_actions'])
            self.assertEqual(json.loads((self.control/'tool-02-00.json').read_text())['result']['outcome'],'uncertain')

    def test_browsing_budget_reserves_evidence_output_and_finish(self):
        frozen=self.browser_frozen();client=ScriptedBrowser(frozen)
        def respond(path,payload,**kwargs):
            client.calls.append(copy.deepcopy(payload));n=len(client.calls)
            if n==1:name,args='browser_open',{'url':frozen['browser']['origins'][0]+'/form'}
            elif n<=6:name,args='browser_tabs',{}
            elif n==7:name,args='file_write',{'path':frozen['outputs'][0]['path'],'text':'No date-specific fares were observed; no booking was made.'}
            else:name,args='finish',report(frozen)
            return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        client.request=respond
        with closing(sqlite3.connect(':memory:')) as db:
            result=run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(Driver()))
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.calls),8)
        self.assertIn('No date-specific fares',(self.ws/frozen['outputs'][0]['path']).read_text())
        self.assertEqual({t['name'] for t in client.calls[6]['tools'][0]['functionDeclarations']},{'file_write','finish'})
        self.assertEqual([t['name'] for t in client.calls[7]['tools'][0]['functionDeclarations']],['finish'])
        self.assertIn('Host UTC time at worker start:',client.calls[0]['systemInstruction']['parts'][0]['text'])

    def test_reviewer_cannot_accept_candidate_without_independent_page_evidence(self):
        frozen=self.browser_frozen();frozen['review_of']='produce';client=file_fixtures.Scripted(frozen)
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaisesRegex(ValueError,'request budget'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(Driver()))
        self.assertFalse((self.ws/'.relay/result.json').exists())
        self.assertIn('actual page observation',json.loads((self.control/'tool-02-00.json').read_text())['result']['error'])

    def test_late_browser_call_cannot_consume_reserved_round_or_invent_completion(self):
        frozen=self.browser_frozen();client=ScriptedBrowser(frozen)
        def respond(path,payload,**kwargs):
            client.calls.append(copy.deepcopy(payload))
            return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':'browser_tabs','args':{}}}]}}]}
        client.request=respond
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaisesRegex(ValueError,'request budget'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(Driver()))
        self.assertEqual(len(client.calls),8);self.assertFalse((self.ws/'.relay/result.json').exists())
        for n in (7,8):self.assertIn('finalization',json.loads((self.control/f'tool-{n:02d}-00.json').read_text())['result']['error'])

    def test_recovery_reports_browser_uncertainty_even_with_all_model_responses(self):
        from orchestrator.workers import CodexFactory
        session={'control':str(self.control),'backend':browser_graph()['backend']}
        atomic(self.control/'browser-result.json',{'profile':'fixture','job':'fixture','actions':[], 'uncertain_actions':[{'id':'click'}]})
        with patch.object(CodexFactory,'inspect',return_value={'status':'finished'}):
            result=GeminiFactory().inspect(session)
            self.assertEqual(result['status'],'uncertain');self.assertTrue(result['local_terminal'])
            self.assertEqual(result['external_outcome'],'unknown')
        atomic(self.control/'cancel.json',{})
        with patch.object(CodexFactory,'inspect',return_value={'status':'finished'}):
            self.assertEqual(GeminiFactory().inspect(session)['external_outcome'],'unknown')

    def test_missing_corrupt_or_misattributed_browser_receipt_is_not_success(self):
        from orchestrator.workers import CodexFactory
        session={'id':'fixture','control':str(self.control),'backend':browser_graph()['backend']}
        for value in (None,'broken','{}',json.dumps({'profile':'fixture','job':'another','actions':[],'uncertain_actions':[]})):
            if value is not None:(self.control/'browser-result.json').write_text(value)
            with patch.object(CodexFactory,'inspect',return_value={'status':'finished'}):
                result=GeminiFactory().inspect(session)
                self.assertEqual(result['status'],'uncertain');self.assertEqual(result['external_outcome'],'unknown')

    def test_local_preparation_freezes_request_without_dispatch(self):
        from task_relay.browser_cli import prepare
        request=self.root/'request.txt';request.write_text('Inspect the requested page; do not submit anything.')
        with patch('task_relay.general_browser.browser') as launch,patch.object(executors,'available') as eligibility:
            runtime=Runtime(self.root/'runtime')
            try:
                plan=prepare(runtime,'prepared',request,browser_graph()['backend'],policy(interaction_scope=''))
                request.write_text('Later edit, not part of the prepared request')
                artifact=runtime.artifact(plan['tasks'][0]['inputs'][0]['artifact'])
                self.assertEqual(Path(artifact['blob']).read_text(),'Inspect the requested page; do not submit anything.')
                self.assertEqual(runtime.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)
                self.assertEqual(plan['tasks'][1]['browser']['interaction_scope'],'')
                launch.assert_not_called();eligibility.assert_not_called()
            finally:runtime.db.close()

    def test_changed_support_rejected_before_browser_launch(self):
        frozen=self.browser_frozen();frozen['runtime_sources']={}
        with closing(sqlite3.connect(':memory:')) as db,patch('task_relay.general_browser.browser') as launch:
            with self.assertRaisesRegex(ValueError,'implementation changed'):run(frozen,self.control,db,self.root)
            launch.assert_not_called()

    def test_supervised_browser_pair_reopens_without_duplicate_dispatch_and_records_usage(self):
        with patch.object(executors,'configured',return_value=(CONFIG,file_fixtures.BACKEND)),patch.object(executors,'available'):
            factory=ExecutionFactory(gemini=SupervisorFixture());runtime=Runtime(self.root/'runtime',factory)
            runtime.create(browser_graph());runtime.tick('demo');runtime.db.close()
            runtime=Runtime(self.root/'runtime',factory)
            try:
                status=file_fixtures.Tests.until(self,runtime,lambda s:s['status']=='awaiting_user')
                self.assertEqual(len(status['attempts']),2)
                for attempt in status['attempts']:
                    receipt=json.loads(attempt['receipt'])
                    self.assertEqual(receipt['backend']['type'],'gemini-browser');self.assertTrue(receipt['usage'])
                    self.assertFalse(receipt['browser']['uncertain_actions'])
                self.assertEqual(len(runtime.tick('demo')['attempts']),2)
                from task_relay import usage_tracker as usage
                with closing(sqlite3.connect(self.root/'usage.sqlite')) as ledger:
                    ledger.row_factory=sqlite3.Row;usage.initialize(ledger)
                    usage.collect_relay(ledger,runtime.root/'state.sqlite')
                    self.assertEqual({r[0] for r in ledger.execute('SELECT provider FROM usage_events')},{'gemini'})
            finally:
                for child in factory.gemini.children:child.wait(timeout=5)
                runtime.db.close()

    def test_supervised_lost_browser_action_is_terminal_after_recovery(self):
        with patch.object(executors,'configured',return_value=(CONFIG,file_fixtures.BACKEND)),patch.object(executors,'available'):
            factory=ExecutionFactory(gemini=SupervisorFixture('uncertain'));runtime=Runtime(self.root/'runtime',factory)
            runtime.create(browser_graph());runtime.tick('demo')
            try:
                status=file_fixtures.Tests.until(self,runtime,lambda s:s['status']=='uncertain')
                self.assertTrue(json.loads(status['attempts'][0]['receipt'])['local_terminal'])
                for _ in range(3):self.assertEqual(len(runtime.tick('demo')['attempts']),1)
                self.assertEqual(len(list((runtime.root/'workers').glob('*/api-*.request.json'))),2)
            finally:
                for child in factory.gemini.children:child.wait(timeout=5)
                runtime.db.close()


class PlanningTests(unittest.TestCase):
    setUp=planning_fixtures.Tests.setUp;tearDown=planning_fixtures.Tests.tearDown
    request=planning_fixtures.Tests.request;action=planning_fixtures.Tests.action;queue=planning_fixtures.Tests.queue
    row=planning_fixtures.Tests.row;response=planning_fixtures.Tests.response;click=planning_fixtures.Tests.click;start=planning_fixtures.Tests.start

    def test_browser_scope_survives_reviewed_plan_and_atomic_start(self):
        backend={'type':'gemini-agent','model':'fixture-model'}
        with patch.object(executors,'configured',return_value=(CONFIG,backend)),patch.object(executors,'available'):
            self.queue(action=self.action(executor='gemini-browser'))
            response=self.response()
            for task in response['plan']['tasks']:
                task.update(tools=['files','browser'],limits=executors.GEMINI_LIMITS.copy(),browser=policy(interaction_scope='' if task.get('review_of') else 'Submit fixture once'))
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
            row=self.row();self.assertEqual(row['status'],'ready',row['error'])
            card=planning.preview(row)
            self.assertIn('https://example.test',card);self.assertIn('Submit fixture once',card);self.assertIn('External transfer',card)
            self.start(row);self.assertEqual(self.row()['status'],'started')
            plan=json.loads(self.state.db.execute('SELECT plan FROM production_runs').fetchone()[0])
            self.assertEqual(plan['backend']['type'],'gemini-browser')
            self.assertEqual(plan['tasks'][0]['browser']['interaction_scope'],'Submit fixture once')
            self.assertEqual(plan['tasks'][1]['browser']['interaction_scope'],'')


if __name__=='__main__':
    if sys.argv[1:2]==['fixture']:
        control,workspace,mode=sys.argv[2:];frozen=json.loads((Path(workspace)/'.relay/ASSIGNMENT.json').read_text())
        driver=Driver();driver.fail=mode=='uncertain'
        client=ScriptedBrowser(frozen)
        with closing(sqlite3.connect(Path(control)/'fixture-journal.sqlite')) as db:
            run(frozen,control,db,Path(control),client=client,config_reader=lambda:(CONFIG,frozen['backend']),driver_context=nullcontext(driver))
    else:unittest.main()
