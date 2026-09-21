"""Controlled planner-schema/compilation regressions; no provider or host calls."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import contracts, executors
from task_relay import gemini, planning_contract, production_planning as planning
from tests import test_production_planning as fixtures
from tests.test_gemini_executor import CONFIG, BACKEND


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        del self.fail  # Routing fixture's boolean would shadow unittest.fail.
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    click=fixtures.Tests.click
    start=fixtures.Tests.start

    def locked(self):
        with patch.object(executors,'configured',return_value=(CONFIG,BACKEND)),patch.object(executors,'available'):
            return self.queue(action=self.action(executor='gemini-agent'))

    def draft(self):
        value=self.response()
        for task in value['plan']['tasks']:
            task.pop('tools')
            task['limits']=executors.GEMINI_LIMITS.copy()
        return value

    def test_locked_executor_is_compiled_without_model_repeating_worker_or_tools(self):
        row=self.locked()
        _,plan=planning.validate_result(json.dumps(self.draft()),row)
        for task in plan['tasks']:
            self.assertEqual(task['worker']['backend'],BACKEND)
            self.assertEqual(task['tools'],['files'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_exact_misplaced_executor_is_recorded_without_second_provider_call(self):
        self.locked();value=self.draft()
        for task in value['plan']['tasks']:
            task['executor']='gemini-agent'
            task['worker']={'requires':['files.text']}
        raw=json.dumps(value)
        generator=lambda *_:(raw,{'controlled':True})
        worker=planning.Worker(self.state,generator);worker.tick();worker.tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.assertEqual(row['calls'],1)
        self.assertEqual(json.loads(row['result']),value)
        call=self.state.db.execute('SELECT response FROM production_plan_calls').fetchone()[0]
        self.assertEqual(call,raw)
        plan=json.loads(row['plan'])
        self.assertEqual(len(plan['origin']['planner_field_bindings']),2)
        self.assertNotIn('executor',plan['tasks'][0])
        self.assertEqual(plan['tasks'][0]['worker']['backend'],BACKEND)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        with patch.object(executors,'available'):
            self.start(row)
            self.click(row['token'])
        self.assertEqual(self.row()['status'],'started',self.row()['error'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def test_conflicting_selectors_and_backend_injection_are_not_discarded(self):
        row=self.locked()
        for injected in ({'executor':'codex-cli'},
                         {'executor':'gemini-agent','worker':{'requires':['files.text'],'executor':'codex-cli'}},
                         {'worker':{'requires':['files.text'],'backend':BACKEND}}):
            with self.subTest(injected=injected):
                value=self.draft();value['plan']['tasks'][0].update(injected)
                with self.assertRaisesRegex(ValueError,r'\$\.plan\.tasks\[0\]'):
                    planning.validate_result(json.dumps(value),row)
        self.assertEqual(self.row()['status'],'queued')

    def test_unlocked_task_level_executor_is_not_guessed(self):
        row=self.queue();value=self.response();value['plan']['tasks'][0]['executor']='codex-cli'
        with self.assertRaisesRegex(ValueError,r'tasks\[0\]\.executor: unsupported'):
            planning.validate_result(json.dumps(value),row)

    def test_mixed_input_reference_and_wrong_types_fail_before_compilation(self):
        row=self.queue()
        cases=[]
        value=self.response();value['plan']['tasks'][1]['inputs'][0]['artifact']='invented';cases.append((value,'inputs'))
        value=self.response();value['plan']['tasks'][0]['limits']['seconds']=True;cases.append((value,'seconds: expected integer'))
        value=self.response();value['plan']['tasks'][0]['worker']=[];cases.append((value,'worker: expected object'))
        value=self.response();value['plan']['tasks'][0]['outputs'][0]['model']='invented';cases.append((value,'model: unsupported'))
        for value,message in cases:
            with self.subTest(message=message),self.assertRaisesRegex(ValueError,message):
                planning.validate_result(json.dumps(value),row)

    def test_correction_receives_field_path_and_same_frozen_contract(self):
        row=self.queue();value=self.response();value['plan']['tasks'][0]['executer']='codex-cli'
        requests=[]
        def generator(row,payload):
            requests.append(copy.deepcopy(payload))
            return json.dumps(value if len(requests)==1 else self.response()),{}
        worker=planning.Worker(self.state,generator);worker.tick();worker.tick()
        self.assertEqual(self.row()['status'],'ready',self.row()['error'])
        error=requests[1]['structural_correction']['error']
        self.assertIn('$.plan.tasks[0].executer',error)
        self.assertEqual(requests[0]['response_contract'],requests[1]['response_contract'])
        self.assertEqual(requests[1]['structural_correction']['previous_response'],value)
        self.assertEqual(json.loads(row['context'])['response_contract'],requests[0]['response_contract'])

    def test_gemini_receives_native_schema_and_legacy_request_is_unchanged(self):
        row=self.locked();payload=json.loads(row['context'])
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(gemini.Client,'request',return_value={'candidates':[]}) as call:
            planning.generate(row,payload)
            config=call.call_args.args[1]['generationConfig']
            self.assertEqual(config['responseJsonSchema'],payload['response_contract']['schema'])
            task_schema=config['responseJsonSchema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']
            self.assertFalse(task_schema['additionalProperties'])
            self.assertNotIn('executor',task_schema['properties']['worker']['properties'])
            del payload['response_contract']
            planning.generate(row,payload)
            self.assertNotIn('responseJsonSchema',call.call_args.args[1]['generationConfig'])

    def test_provider_schema_rejection_is_not_retried_without_schema(self):
        self.locked()
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(gemini.Client,'request',side_effect=ValueError('Schema rejected')) as call:
            worker=planning.Worker(self.state);worker.tick();worker.tick()
        self.assertEqual(call.call_count,1)
        self.assertEqual(self.row()['status'],'blocked')
        self.assertEqual(self.row()['error'],'Schema rejected')

    def test_locked_text_profile_reports_validator_requirement_without_fallback(self):
        row=dict(self.locked());payload=json.loads(row['context'])
        source={'artifact':'validator-fixture','path':'operation-support/rhino3dm.run_python/validate.py',
                'purpose':'Validate the prepared contract','authority':'Frozen contract',
                'bytes':20,'sha256':'a'*64}
        payload['sources'].append(source);payload['required_artifacts'].append(source['artifact'])
        row['context']=contracts.encoded(payload)
        value=self.draft();value['plan']['tasks'][0]['executor']='gemini-agent'
        with self.assertRaisesRegex(ValueError,'validator inputs require code.execute'):
            planning.validate_result(json.dumps(value),row)
        self.assertEqual(json.loads(self.row()['options'])['backend'],BACKEND)

    def test_legacy_frozen_response_does_not_acquire_normalization(self):
        row=dict(self.locked());payload=json.loads(row['context']);del payload['response_contract']
        row['context']=json.dumps(payload)
        value=self.draft();value['plan']['tasks'][0]['executor']='gemini-agent'
        with self.assertRaisesRegex(ValueError,'Executor belongs inside worker'):
            planning.validate_result(json.dumps(value),row)
        original=copy.deepcopy(value)
        proposal,bindings=planning_contract.prepare(value,payload,json.loads(row['options']))
        self.assertEqual(proposal,original);self.assertEqual(bindings,[])


if __name__=='__main__':unittest.main()
