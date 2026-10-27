"""Role-neutral authority correction across providers and persistent CLI pipes."""
import copy
import json
import runpy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from orchestrator import agent_loop,executors
from orchestrator.codex_transport import Client,POLICY
from orchestrator.workers import atomic
from task_relay import code_runtime,native_code_host
from tests import test_gemini_executor as fixture
from tests.test_shared_code_workers import RECEIPT
from tests.test_tool_authority import PROVIDERS,response


def setup_case():
    case=fixture.Tests();case.setUp()
    case.frozen['tools']=['files','python']
    case.frozen['limits'].update(tool_calls=20,provider_requests=12,output_bytes=100000)
    return case


def steps_for(frozen,provider):
    finish=fixture.report(frozen)
    if provider=='gemini':finish=dict(report_json=json.dumps(finish))
    return [('file_list',{})]*4+[
        ('python_run',dict(code='DENIED edit must not execute',seconds=5)),
        ('python_checkpoint',dict(code='Write a substantive corrected text fixture',seconds=5)),
        ('finish',finish)]


def host_result(calls):
    def run(runtime,folder,code,seconds,maximum,cancelled):
        calls.append(code)
        assert code=='Write a substantive corrected text fixture'
        out=folder/'outputs';out.mkdir();(out/'output.txt').write_text('Substantive corrected fixture')
        return dict(returncode=0,log='Controlled local edit',outputs=str(out))
    return run


class Tests(unittest.TestCase):
    def test_plain_code_worker_denial_recovers_with_registered_checkpoint_for_all_providers(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                case=setup_case()
                try:
                    backend=dict(type=provider+'-code',model='fixture',runtime=RECEIPT['id'])
                    if provider=='codex':backend.update(reasoning='high',budget_semantics=POLICY)
                    case.frozen['backend']=backend;config=dict(api_key='fixture')
                    atomic(case.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,backend)))
                    steps=iter(steps_for(case.frozen,provider));requests=[];declared=[];calls=[]
                    class Peer:
                        def set_tools(self,tools):declared.extend(copy.deepcopy(tools))
                        def request(self,*args,**kwargs):
                            requests.append(copy.deepcopy(args[1]));return response(provider,[next(steps)])
                    with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=host_result(calls)):
                        result=agent_loop.execute(case.frozen,case.control,Peer(),lambda:(config,backend))
                    self.assertEqual(result['decision'],'delivered');self.assertEqual(len(calls),1)
                    self.assertEqual(len(requests),7)
                    self.assertEqual(json.loads((case.control/'api-05.validation.json').read_text())['effect'],'none')
                    self.assertFalse((case.control/'tool-05-00.json').exists())
                    self.assertEqual((case.ws/'output.txt').read_text(),'Substantive corrected fixture')
                    if provider=='codex':self.assertIn('python_checkpoint',[t['name'] for t in declared])
                finally:case.tearDown()

    def test_persistent_pipe_registers_lifecycle_closure_and_answers_denied_rpc_before_recovery(self):
        case=setup_case()
        try:
            backend=dict(type='codex-code',model='fixture',runtime=RECEIPT['id'],reasoning='high',budget_semantics=POLICY)
            case.frozen['backend']=backend;config=dict(executable='fixture')
            atomic(case.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,backend)))
            script=case.control/'script.json';atomic(script,steps_for(case.frozen,'codex'))
            command=[sys.executable,'-B',str(Path(__file__).with_name('codex_protocol_fixture.py')),str(script),'chatgpt','strict']
            calls=[]
            with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=host_result(calls)),Client(config,backend,case.control,30,command=command) as client:
                # Production workers launch this file as a script, without a package.
                script_loop=runpy.run_path(str(Path(agent_loop.__file__)))['execute']
                result=script_loop(case.frozen,case.control,client,lambda:(config,backend))
            self.assertEqual(result['decision'],'delivered');self.assertEqual(len(calls),1)
            sent=[json.loads(l) for l in (case.control/'codex-sent.jsonl').read_text().splitlines()]
            self.assertEqual(sum(e.get('method')=='thread/start' for e in sent),1)
            denied=next(e for e in sent if e.get('id')==105 and 'result' in e)
            self.assertEqual(json.loads(denied['result']['contentItems'][0]['text'])['code'],'tool_authority_denied')
            self.assertEqual((case.ws/'output.txt').read_text(),'Substantive corrected fixture')
        finally:case.tearDown()


if __name__=='__main__':unittest.main()
