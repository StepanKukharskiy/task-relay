"""Native provider envelopes over the real browser journal; no network or GUI."""
import copy
from contextlib import closing, nullcontext
import json
import sqlite3
import unittest
from unittest.mock import patch

from orchestrator import contracts, executors
from orchestrator.browser_worker import run
from orchestrator.workers import atomic
from task_relay import api_providers, browser_requests, gemini
from tests import test_gemini_executor as fixtures
from tests.test_general_browser import browser_graph, Driver
from tests import test_executor_planning as planning_fixtures


class NativeClient:
    def __init__(self,provider,frozen,mode='normal'):
        self.provider,self.frozen,self.mode=provider,frozen,mode
        self.calls=[]

    def request(self,path,payload):
        self.calls.append((path,copy.deepcopy(payload)));n=len(self.calls)
        if self.mode=='timeout':raise gemini.ProviderError('fixture disconnect',uncertain=True)
        if n==1:name,args='browser_open',{'url':self.frozen['browser']['origins'][0]+'/form'}
        elif n in (2,3):
            previous=json.loads(payload['input'][-1]['output'] if self.provider=='openai' else payload['messages'][-1]['content'])
            name='browser_fill' if n==2 else 'browser_click'
            control=next(x for x in previous['controls'] if x['tag']==('INPUT' if n==2 else 'BUTTON'))
            args=dict(tab=previous['tab'],observation=previous['observation'],ref=control['ref'],purpose='Submit the fixture once')
            if n==2:args['text']='Fixture request'
        elif n==4:name,args='file_write',{'path':self.frozen['outputs'][0]['path'],'text':'Observed fixture answer.'}
        else:name,args='finish',fixtures.report(self.frozen)
        call={'type':'function_call','call_id':'call-'+str(n),'name':name,'arguments':json.dumps(args)}
        if self.mode=='malformed':call['arguments']='{broken'
        if self.provider=='openai':
            return {'id':'response-'+str(n),'status':'incomplete' if self.mode=='incomplete' else 'completed',
                    'usage':{'input_tokens':5,'output_tokens':3},'output':[
                        {'type':'reasoning','id':'reason-'+str(n),'summary':[],'encrypted_content':'opaque-fixture'},call]}
        return {'id':'response-'+str(n),'usage':{'prompt_tokens':5,'completion_tokens':3},'choices':[{
            'finish_reason':'length' if self.mode=='incomplete' else 'tool_calls',
            'message':{'role':'assistant','content':None,'reasoning_content':'opaque-fixture',
                       'tool_calls':[{'id':call['call_id'],'type':'function','function':{k:call[k] for k in ('name','arguments')}}]}}]}


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown

    def prepare(self,provider):
        frozen=contracts.assignment(browser_graph()['tasks'][0])
        frozen.update(assignment_id='fixture',backend={'type':provider+'-browser','model':'fixture-model'},workspace=str(self.ws))
        config={'api_key':'fixture-only','model':'fixture-model'}
        atomic(self.control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,frozen['backend'])})
        return frozen,config

    def exercise(self,provider,mode='normal',driver=None):
        frozen,config=self.prepare(provider);client=NativeClient(provider,frozen,mode)
        with closing(sqlite3.connect(':memory:')) as db:
            result=run(frozen,self.control,db,self.root,client=client,
                       config_reader=lambda:(config,frozen['backend']),driver_context=nullcontext(driver or Driver()))
            with self.assertRaisesRegex(ValueError,'replay'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(config,frozen['backend']),driver_context=nullcontext(Driver()))
        self.assertEqual(result['decision'],'delivered')
        self.assertEqual(len(client.calls),5)
        self.assertEqual((self.ws/frozen['outputs'][0]['path']).read_text(),'Observed fixture answer.')
        saved=json.loads((self.control/'api-01.request.json').read_text())
        self.assertEqual(saved['provider'],provider)
        self.assertEqual(saved['payload'],client.calls[0][1])
        from orchestrator.browser_contract import WEBSITE_TASK_INSTRUCTIONS
        system=saved['payload']['instructions'] if provider=='openai' else saved['payload']['messages'][0]['content']
        self.assertIn(WEBSITE_TASK_INSTRUCTIONS,system)
        return client

    def test_openai_browser_preserves_native_reasoning_and_call_ids(self):
        client=self.exercise('openai')
        self.assertEqual(client.calls[0][0],'responses')
        following=client.calls[1][1]
        self.assertEqual(following['input'][1]['encrypted_content'],'opaque-fixture')
        self.assertEqual(following['input'][-1]['call_id'],'call-1')
        self.assertFalse(following['store'])

    def test_qwen_browser_preserves_native_reasoning_and_call_ids(self):
        client=self.exercise('qwen')
        self.assertEqual(client.calls[0][0],'chat/completions')
        following=client.calls[1][1]
        self.assertEqual(following['messages'][2]['reasoning_content'],'opaque-fixture')
        self.assertEqual(following['messages'][-1]['tool_call_id'],'call-1')

    def test_incomplete_response_never_executes_a_browser_tool(self):
        frozen,config=self.prepare('openai');driver=Driver();client=NativeClient('openai',frozen,'incomplete')
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaisesRegex(ValueError,'incomplete'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(config,frozen['backend']),driver_context=nullcontext(driver))
        self.assertEqual(len(client.calls),1);self.assertEqual(driver.actions,[])
        receipt=json.loads((self.control/'browser-result.json').read_text())
        self.assertEqual(receipt['actions'],[])

    def test_malformed_qwen_arguments_never_execute(self):
        with self.assertRaises(json.JSONDecodeError):self.exercise('qwen','malformed')
        self.assertTrue((self.control/'api-01.response.json').exists())
        self.assertEqual(json.loads((self.control/'browser-result.json').read_text())['actions'],[])

    def test_uncertain_provider_request_retains_intent_and_cannot_replay(self):
        frozen,config=self.prepare('qwen');client=NativeClient('qwen',frozen,'timeout')
        with closing(sqlite3.connect(':memory:')) as db:
            for attempt in range(2):
                with self.assertRaises(ValueError if attempt else gemini.ProviderError):
                    run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(config,frozen['backend']),driver_context=nullcontext(Driver()))
        self.assertEqual(len(client.calls),1)
        self.assertEqual(json.loads((self.control/'api-01.outcome.json').read_text())['outcome'],'uncertain')

    def test_uncertain_browser_action_stops_before_another_model_call(self):
        frozen,config=self.prepare('openai');client=NativeClient('openai',frozen);driver=Driver();driver.fail=True
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaisesRegex(ValueError,'uncertain'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(config,frozen['backend']),driver_context=nullcontext(driver))
        self.assertEqual(len(client.calls),2)
        self.assertTrue(json.loads((self.control/'browser-result.json').read_text())['uncertain_actions'])

    def test_qwen_endpoint_change_stops_before_provider_or_browser_use(self):
        frozen,config=self.prepare('qwen');changed={**config,'base_url':api_providers.QWEN_ENDPOINTS['Beijing']};client=NativeClient('qwen',frozen)
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaisesRegex(ValueError,'connection changed'):
                run(frozen,self.control,db,self.root,client=client,config_reader=lambda:(changed,frozen['backend']),driver_context=nullcontext(Driver()))
        self.assertEqual(client.calls,[])

    def test_configured_provider_does_not_consult_gemini(self):
        with patch.object(gemini,'read_config',side_effect=AssertionError('Gemini dependency')),patch.object(api_providers,'read_config',return_value={'api_key':'fixture-only','model':'fixture-model'}):
            self.assertEqual(executors.configured('openai')[1]['type'],'openai-browser')
            self.assertEqual(executors.configured('qwen')[1]['type'],'qwen-browser')

    def test_explicit_browser_provider_cannot_be_substituted(self):
        for provider in ('openai','qwen'):
            text='/browser '+provider+' Research this in Perplexity'
            browser_requests.validate({'kind':'plan_production','executor':provider+'-browser'},text)
            with self.assertRaises(ValueError):browser_requests.validate({'kind':'plan_production','executor':'gemini-browser'},text)

    def test_failed_metadata_refresh_invalidates_old_eligibility(self):
        from task_relay.host import HOST
        frozen,config=self.prepare('openai');backend=frozen['backend']
        with patch.object(executors,'receipt_path',return_value=self.root/'verification.json'),patch.object(executors,'configured',return_value=(config,backend)),patch.object(HOST,'browser_python'),patch.object(api_providers,'catalog',return_value=['fixture-model']) as catalog:
            executors.probe('openai');executors.available(backend)
            catalog.side_effect=gemini.ProviderError('fixture unavailable')
            with self.assertRaises(gemini.ProviderError):executors.probe('openai')
            with self.assertRaisesRegex(ValueError,'stale'):executors.available(backend)

    def test_browser_metadata_does_not_expire_or_grant_changed_connections(self):
        from task_relay.host import HOST
        import time
        for provider in ('gemini','openai','qwen'):
            with self.subTest(provider=provider):
                config={'api_key':'fixture-key',
                        'models':{'text':'fixture-model'}}
                base=executors.verification_backend(provider,'fixture-model')
                browser={'type':provider+'-browser','model':'fixture-model'}
                path=self.root/'metadata.json'
                atomic(path,{'backend':base,'fingerprint':executors.fingerprint(config,base),
                             'verified_at':time.time()-86400})
                with patch.object(executors,'receipt_path',return_value=path),patch.object(executors,'configured',return_value=(config,base)),patch.object(HOST,'browser_python') as runtime:
                    executors.available(browser)
                    runtime.assert_called_once()
                    changes=[{**config,'api_key':'changed'}]
                    if provider=='qwen':changes.append({**config,'base_url':api_providers.QWEN_ENDPOINTS['Beijing']})
                    for changed in changes:
                        with patch.object(executors,'configured',return_value=(changed,base)):
                            with self.assertRaisesRegex(ValueError,'stale'):executors.available(browser)
                    with self.assertRaisesRegex(ValueError,'changed'):
                        executors.available({**browser,'model':'different-model'})
                    runtime.side_effect=ValueError('Browser runtime unavailable')
                    with self.assertRaisesRegex(ValueError,'runtime unavailable'):executors.available(browser)
                    runtime.side_effect=None
                    atomic(path,{'verified_at':0})
                    with self.assertRaisesRegex(ValueError,'stale'):executors.available(browser)

    def test_local_preparation_and_usage_keep_each_provider(self):
        from orchestrator.runtime import Runtime
        from task_relay.browser_cli import prepare
        from task_relay import usage_tracker as usage
        request=self.root/'request.txt';request.write_text('Inspect the fixture page.')
        source=self.root/'receipts.sqlite'
        with closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE production_attempts (id TEXT,frozen TEXT,receipt TEXT)')
            for provider in ('openai','qwen'):
                backend={'type':provider+'-browser','model':'fixture-model'}
                runtime=Runtime(self.root/provider)
                try:plan=prepare(runtime,'fixture',request,backend,browser_graph()['tasks'][0]['browser'])
                finally:runtime.db.close()
                self.assertEqual(plan['backend'],backend)
                native={'input_tokens':5,'output_tokens':3} if provider=='openai' else {'prompt_tokens':5,'completion_tokens':3}
                db.execute('INSERT INTO production_attempts VALUES (?,?,?)',(provider,json.dumps({'backend':backend}),json.dumps({'usage':[native]})))
            db.commit()
        with closing(sqlite3.connect(':memory:')) as ledger:
            ledger.row_factory=sqlite3.Row;usage.initialize(ledger)
            usage.collect_relay(ledger,source);usage.collect_relay(ledger,source)
            rows=ledger.execute('SELECT provider,counts FROM usage_events ORDER BY provider').fetchall()
            self.assertEqual([(r['provider'],json.loads(r['counts'])['total_tokens']) for r in rows],[('openai',8),('qwen',8)])


class PlanningTests(unittest.TestCase):
    setUp=planning_fixtures.Tests.setUp;tearDown=planning_fixtures.Tests.tearDown
    request=planning_fixtures.Tests.request;action=planning_fixtures.Tests.action;queue=planning_fixtures.Tests.queue
    row=planning_fixtures.Tests.row;response=planning_fixtures.Tests.response;click=planning_fixtures.Tests.click;start=planning_fixtures.Tests.start

    def check_provider(self,provider):
        from task_relay import production_planning as planning
        from tests.test_general_browser import policy
        backend={'type':provider+'-browser','model':'fixture-model'}
        def configured(selected='gemini'):
            if selected!=provider:raise ValueError('Not connected')
            return {'api_key':'fixture-only','model':'fixture-model'},backend
        with patch.object(executors,'configured',side_effect=configured),patch.object(executors,'available'):
            self.queue(action=self.action(executor=backend['type']))
            response=self.response()
            for task in response['plan']['tasks']:
                task.update(tools=['files','browser'],limits=executors.GEMINI_LIMITS.copy(),browser=policy(interaction_scope='' if task.get('review_of') else 'Submit fixture once'))
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
            row=self.row();self.assertEqual(row['status'],'ready',row['error'])
            self.assertIn(provider,planning.preview(row));self.assertIn('Submit fixture once',planning.preview(row))
            with patch.object(executors,'available',side_effect=ValueError('Disconnected')):self.start(row)
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
            self.start(row);self.assertEqual(self.row()['status'],'started')
            plan=json.loads(self.state.db.execute('SELECT plan FROM production_runs').fetchone()[0])
            self.assertEqual(plan['backend'],backend)
            self.assertEqual([t['browser']['interaction_scope'] for t in plan['tasks']],['Submit fixture once',''])

    def test_openai_plan_start_without_gemini(self):self.check_provider('openai')
    def test_qwen_plan_start_without_gemini(self):self.check_provider('qwen')


if __name__=='__main__':unittest.main()
