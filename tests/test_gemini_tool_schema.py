import copy,json,unittest
from pathlib import Path
from orchestrator import gemini_tool_schema as wire,gemini_worker,job_owner,parameter_contracts
from tests import test_owner_intents as intent
from tests.test_operation_session import Script,CONFIG
from orchestrator import executors
from orchestrator.workers import atomic


def concrete(schema):
    if schema.get('type')=='object':
        if not schema.get('properties'):raise ValueError('Open-ended object in constrained provider schema')
        for value in schema['properties'].values():concrete(value)
    if schema.get('type')=='array':concrete(schema['items'])
    if 'anyOf' in schema or 'oneOf' in schema or 'additionalProperties' in schema:raise ValueError('Unprojected local contract')


class Tests(unittest.TestCase):
    def test_provider_projection_keeps_typed_tasks_and_exact_local_contract(self):
        tools=job_owner.definitions(dict(delegation_version=2));before=copy.deepcopy(tools)
        for t in gemini_worker.gemini_declarations(tools):
            if 'parameters' in t:concrete(t['parameters'])
        delegated=next(t for t in gemini_worker.gemini_declarations(tools) if t['name']=='job_delegate')['parameters']
        properties=delegated['properties']['tasks']['items']['properties']
        self.assertEqual(properties['inputs']['items']['type'],'object')
        self.assertEqual(properties['parameters']['type'],'string')
        self.assertEqual(tools,before)
        self.assertEqual(gemini_worker.gemini_declarations(tools),gemini_worker.gemini_declarations(json.loads(json.dumps(tools,sort_keys=True))))
        native=next(t for t in tools if t['name']=='job_delegate')['parameters']
        value=dict(request_id='one',tasks=[dict(id='test',objective='Build',parameters='{"width":70}',inputs=[dict(artifact='a')])])
        decoded=wire.decode(value,native);self.assertEqual(decoded['tasks'][0]['parameters'],{'width':70})
        parameter_contracts.validate(decoded,native)
        decoded['tasks'][0]['inputs'][0].update(task='other',output='result')
        with self.assertRaises(ValueError):parameter_contracts.validate(decoded,native)
        value['tasks'][0]['parameters']='{bad'
        with self.assertRaisesRegex(ValueError,'Malformed JSON'):wire.decode(value,native)

    def test_shared_projection_of_map_and_union_does_not_execute_payloads(self):
        schema=dict(type='object',properties=dict(mapping=dict(type='object',additionalProperties=dict(type='string')),choice=dict(anyOf=[dict(type='string'),dict(type='integer')])),required=['mapping','choice'])
        concrete(wire.project(schema))
        value=wire.decode(dict(mapping='{"arbitrary":"exact"}',choice='7'),schema)
        self.assertEqual(value,dict(mapping={'arbitrary':'exact'},choice=7))
        with self.assertRaises(ValueError):wire.decode(dict(mapping='__import__("os")',choice='7'),schema)


class Flow(unittest.TestCase):
    setUp=intent.Tests.setUp
    create=intent.Tests.create
    def test_mode_only_recovery_requires_exact_declarations_and_retains_validation(self):
        from task_relay.completion_recovery import schema_repair_gap
        self.create();self.rt.tick('job');aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        receipt=dict(status='finished',exit_code=1,reason='Provider request rejected',pending_requests=[],external_outcome='no_pending_response',tool_calls=0,api_requests=1)
        s['status']=receipt;self.rt.tick('job')
        frozen=copy.deepcopy(s['frozen']);frozen['runtime_sources']['gemini_worker.py']='prior-mode-runtime'
        control=Path(s['session']['control']);control.mkdir(parents=True,exist_ok=True)
        declarations=gemini_worker.gemini_declarations(job_owner.definitions(frozen['owner_grant']))
        request=dict(provider='gemini',model=frozen['backend']['model'],payload=dict(tools=[dict(functionDeclarations=declarations)],toolConfig=dict(functionCallingConfig=dict(mode='ANY'))))
        path=control/'api-01.request.json';path.write_text(json.dumps(request,sort_keys=True))
        (control/'api-01.outcome.json').write_text(json.dumps(dict(outcome='rejected',http_status=400)))
        with self.rt.transaction():self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),aid))
        attempt=dict(self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone())
        self.assertEqual(schema_repair_gap(self.rt,attempt,receipt)['changed_tools'],['functionCallingConfig.mode'])
        request['payload']['toolConfig']['functionCallingConfig']['mode']='AUTO';path.write_text(json.dumps(request))
        self.assertIsNone(schema_repair_gap(self.rt,attempt,receipt))
        request['payload']['toolConfig']['functionCallingConfig']['mode']='ANY';path.write_text(json.dumps(request))
        self.assertTrue(self.rt.continue_attempt('job','owner',aid,kind='provider_schema'))
        request['payload']['tools'][0]['functionDeclarations'][0]['description']='Changed after proof';path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError,'evidence or scope changed'):
            from orchestrator.continuations import validate_dispatch
            validate_dispatch(self.rt,self.rt.task('job','owner'))

    def test_confirmed_first_request_repair_reuses_assignment_and_remaining_attempts(self):
        self.create();self.rt.tick('job');aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        receipt=dict(status='finished',exit_code=1,reason='Provider schema rejected',pending_requests=[],external_outcome='no_pending_response',tool_calls=0,api_requests=1)
        s['status']=receipt;self.rt.tick('job')
        frozen=copy.deepcopy(s['frozen']);frozen['runtime_sources']['gemini_worker.py']='prior-qualified-transport'
        control=Path(s['session']['control']);control.mkdir(parents=True,exist_ok=True)
        declarations=job_owner.definitions(frozen['owner_grant'])
        for tool in declarations:
            if tool['name']=='job_delegate':tool['parametersJsonSchema']=tool.pop('parameters')
        (control/'api-01.request.json').write_text(json.dumps(dict(provider='gemini',model=frozen['backend']['model'],payload=dict(tools=[dict(functionDeclarations=declarations)]))))
        (control/'api-01.outcome.json').write_text(json.dumps(dict(outcome='rejected',http_status=400)))
        with self.rt.transaction():self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),aid))
        original=self.rt.task('job','owner');spec=copy.deepcopy(self.rt.spec(original))
        proof=self.rt.continue_attempt('job','owner',aid,kind='provider_schema')
        self.assertTrue(proof);self.assertEqual(self.rt.spec(self.rt.task('job','owner')),spec)
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertFalse(self.rt.continue_attempt('job','owner',aid,kind='provider_schema'))
        self.rt.tick('job');self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertEqual(self.rt.db.execute('SELECT state FROM production_attempts WHERE id=?',(aid,)).fetchone()[0],'blocked')
        self.assertTrue((control/'api-01.outcome.json').exists())

    def test_wire_arguments_reach_compiler_schema_bound_producer_and_native_consumer(self):
        self.grant['operations']=['pptx.create'];self.create();self.rt.tick('job')
        aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid];control=Path(s['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,s['frozen']['backend'])))
        tasks=[intent.worker('content',media='application/json'),intent.native('build','pptx.create',[dict(task='content',output='result')],parameters='{}')]
        class WireClient(Script):
            def request(inner,endpoint,payload,**kwargs):
                if payload['toolConfig']['functionCallingConfig']['mode']!='AUTO':raise ValueError('Forced provider decoding reintroduced')
                for group in payload['tools']:
                    for tool in group['functionDeclarations']:
                        if 'parameters' in tool:concrete(tool['parameters'])
                return super().request(endpoint,payload,**kwargs)
        client=WireClient([dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(text='I am done.')]))]),('job_delegate',dict(request_id='test',tasks=tasks))])
        result=gemini_worker.execute(s['frozen'],control,client,lambda:(CONFIG,s['frozen']['backend']))
        self.assertEqual(result['outcome'],'yielded')
        content=self.rt.spec(self.rt.task('job','content'));build=self.rt.spec(self.rt.task('job','build'))
        self.assertEqual(content['operation_contract']['id'],'document.layout')
        self.assertEqual(build['execution']['capability'],'pptx.create')
        self.assertEqual(build['inputs'][0]['from_task'],'content')
        self.assertEqual(len(client.requests),2)
        self.assertTrue((control/'api-01.validation.json').exists())
