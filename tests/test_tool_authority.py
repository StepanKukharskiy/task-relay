"""Small offline authority/recovery graphs; no native apps or model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import agent_loop, agent_transport, executors, worker_capabilities, worker_tools
from orchestrator.codex_transport import Client, POLICY
from orchestrator.runtime_outcomes import Hold, UncertainOperation
from orchestrator.tool_authority import validate_batch
from orchestrator.workers import atomic
from tests import test_gemini_executor as files_fixture
from tests import test_worker_tools as work_fixture
from tests.test_operation_session import CONFIG


PROVIDERS = ('gemini', 'openai', 'qwen', 'deepseek', 'openrouter', 'codex')


def response(provider, calls):
    if provider == 'gemini':
        return dict(candidates=[dict(finishReason='STOP', content=dict(role='model', parts=[
            dict(functionCall=dict(name=name, args=args)) for name, args in calls]))])
    if provider == 'openai':
        return dict(status='completed', output=[dict(type='function_call', call_id=str(i),
            name=name, arguments=json.dumps(args)) for i, (name, args) in enumerate(calls)])
    return dict(choices=[dict(finish_reason='tool_calls', message=dict(role='assistant', tool_calls=[
        dict(id=str(i), type='function', function=dict(name=name, arguments=json.dumps(args)))
        for i, (name, args) in enumerate(calls)]))])


class Tests(unittest.TestCase):
    def test_mixed_batch_has_no_file_effect_for_every_provider(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                fixture=files_fixture.Tests();fixture.setUp()
                try:
                    backend=dict(type=provider+'-agent',model='fixture')
                    if provider=='codex':backend.update(reasoning='high',budget_semantics=POLICY)
                    fixture.frozen['backend']=backend
                    atomic(fixture.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,backend)))
                    candidate=response(provider,[('file_write',dict(path='output.txt',text='Must never be written')),
                                                 ('ambient_undeclared_tool',{})])
                    class Peer:
                        def request(self,*args,**kwargs):return copy.deepcopy(candidate)
                    with self.assertRaisesRegex(ValueError,'Provider request budget exhausted'):
                        agent_loop.execute(fixture.frozen,fixture.control,Peer(),lambda:(CONFIG,backend))
                    self.assertEqual(len(list(fixture.control.glob('api-*.validation.json'))),executors.request_limit(fixture.frozen))
                    self.assertFalse((fixture.ws/'output.txt').exists())
                    self.assertFalse(list(fixture.control.glob('tool-*.json')))
                    self.assertEqual(json.loads((fixture.control/'api-01.response.json').read_text()),candidate)
                finally:fixture.tearDown()

    def test_denied_batch_corrects_through_same_worker_without_first_call_effect(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                fixture=work_fixture.Tests();fixture.setUp()
                try:
                    backend=dict(type=provider+'-agent',model='fixture')
                    if provider=='codex':backend.update(reasoning='high',budget_semantics=POLICY)
                    fixture.grant['workers']=[worker_capabilities.entry(backend)]
                    frozen,control,_=fixture.text_work()
                    finish=json.loads(fixture.report(frozen)[1]['report_json'])
                    if provider=='gemini':finish={'report_json':json.dumps(finish)}
                    steps=iter([
                        [('work_run',dict(step='build',request_key='denied')),('ambient_undeclared_tool',{})],
                        [('work_run',dict(step='build',request_key='permitted'))], [('finish',finish)]])
                    requests=[]
                    class Peer:
                        def request(self,*args,**kwargs):
                            requests.append(copy.deepcopy(args[1]));return response(provider,next(steps))
                    agent_loop.execute(frozen,control,Peer(),lambda:(CONFIG,frozen['backend']))
                    worker_tools.verify_delivery(frozen,control)
                    self.assertEqual(len(requests),3)
                    if provider=='gemini':
                        replies=[part['functionResponse']['response'] for message in requests[1]['contents']
                                 for part in message.get('parts',[]) if 'functionResponse' in part]
                    elif provider=='openai':
                        replies=[json.loads(item['output']) for item in requests[1]['input']
                                 if item.get('type')=='function_call_output']
                    else:
                        replies=[json.loads(item['content']) for item in requests[1]['messages']
                                 if item.get('role')=='tool']
                    self.assertEqual(len(replies),2)
                    self.assertTrue(all(item['code']=='tool_authority_denied' and item['effect']=='none' for item in replies))
                    self.assertFalse((control/'tool-01-00.json').exists())
                    self.assertEqual(len(list((control/'work-operations').glob('*/outcome.json'))),1)
                    self.assertEqual(json.loads((control/'api-01.validation.json').read_text())['effect'],'none')
                finally:fixture.doCleanups()

    def test_recovery_does_not_grant_arbitrary_namespace_or_retired_tools(self):
        validate_batch([dict(name='job_delegate')],[dict(name='job_delegate')])
        for name in ('job_execute_arbitrary','job_wait','file_write'):
            with self.assertRaises(ValueError):
                validate_batch([dict(name=name)],[dict(name='job_delegate')])

    def test_hosted_tool_observation_is_uncertain_not_discarded_as_no_effect(self):
        for provider,candidate in (
            ('openai',dict(status='completed',output=[dict(type='web_search_call'),dict(type='function_call',name='file_write',call_id='x',arguments='{}')])),
            ('openai',dict(status='completed',output=[dict(type='future_hosted_tool')])),
            ('gemini',dict(candidates=[dict(content=dict(parts=[dict(codeExecutionResult=dict(output='already ran'))]))])),
        ):
            with self.subTest(provider=provider),self.assertRaises(UncertainOperation) as error:
                agent_transport.Transport(provider).verify_response_authority(candidate)
            self.assertEqual(error.exception.outcome['effect'],'uncertain')

    def test_unqualified_autonomous_transport_stops_before_process_and_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp,patch('orchestrator.codex_transport.HOST.spawn') as spawn:
            folder=Path(tmp);old=folder/'original-journal.json';old.write_text('Exact previous receipt')
            for _ in range(2):
                with self.assertRaises(Hold) as error:
                    with Client(dict(executable='must-not-run'),dict(model='fixture'),folder,5):
                        self.fail('Unqualified transport entered')
                self.assertEqual(error.exception.outcome['code'],'tool_boundary_unqualified')
                self.assertEqual(error.exception.outcome['effect'],'none')
            spawn.assert_not_called()
            self.assertEqual(old.read_text(),'Exact previous receipt')
            self.assertFalse((folder/'codex-sent.jsonl').exists())

    def test_search_hold_is_not_a_missing_source_or_uncertain_submission(self):
        from orchestrator import codex_sources, web_sources
        backend=dict(type='codex-agent',model='fixture',reasoning='high',budget_semantics=POLICY)
        config=dict(executable='must-not-run')
        with tempfile.TemporaryDirectory() as tmp,patch.object(codex_sources,'configuration',return_value=(config,backend)),patch('orchestrator.codex_transport.HOST.spawn') as spawn:
            with self.assertRaises(Hold):
                web_sources.collect(['one','two'],[],'fixture',Path(tmp),
                    dict(models=dict(text='fixture'),backend=backend,cli_executor=config),
                    session_factory=codex_sources.Session)
            spawn.assert_not_called()
            receipts=list(Path(tmp).rglob('search-0.json'))
            self.assertEqual(len(receipts),1)
            record=json.loads(receipts[0].read_text())
            self.assertEqual(record['status'],'not_submitted')
            self.assertIsNone(record['submitted_at'])
            self.assertFalse((Path(tmp)/'query-02').exists())

    def test_hosted_observation_preserves_raw_reply_and_holds_before_local_effect(self):
        fixture=files_fixture.Tests();fixture.setUp()
        try:
            backend=dict(type='openai-agent',model='fixture')
            fixture.frozen['backend']=backend
            atomic(fixture.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,backend)))
            candidate=response('openai',[('file_write',dict(path='output.txt',text='Must not run'))])
            candidate['output'].insert(0,dict(type='mcp_call',name='undeclared'))
            class Peer:
                def request(self,*args):return copy.deepcopy(candidate)
            with self.assertRaises(UncertainOperation):
                agent_loop.execute(fixture.frozen,fixture.control,Peer(),lambda:(CONFIG,backend))
            self.assertEqual(json.loads((fixture.control/'api-01.response.json').read_text()),candidate)
            self.assertEqual(json.loads((fixture.control/'execution-outcome.json').read_text())['effect'],'uncertain')
            self.assertFalse((fixture.ws/'output.txt').exists())
            self.assertFalse(list(fixture.control.glob('tool-*.json')))
        finally:fixture.tearDown()


if __name__ == '__main__':unittest.main()
