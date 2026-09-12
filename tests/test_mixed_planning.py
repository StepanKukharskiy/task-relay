import json
import unittest
from unittest.mock import patch

import gemini
import production_planning as planning
import capabilities
from tests import test_production_planning as fixtures
from tests.test_mixed_execution import operation,upstream


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    click=fixtures.Tests.click
    start=fixtures.Tests.start

    def mixed_response(self):
        response=self.response();tasks=response['plan']['tasks']
        tasks[0].pop('user_gate');tasks[0]['outputs'][0]['media_type']='text/plain'
        tasks.append(operation('bundle','text.bundle',[upstream('produce','output.txt')],['produce','review']))
        tasks.append(operation('api','gemini.text',[upstream('bundle','bundle.txt')],['bundle'],user_gate='Select the summary'))
        for task in tasks[2:]:
            from orchestrator.contracts import assignment
            normalized=assignment(task);task.update(normalized)
        return response

    def test_mixed_scope_requires_capability_choice_and_card_exposes_external_transfer(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'test-model'}}):
            row=self.queue(action=self.action(step_capabilities=['text.bundle','gemini.text']))
            planning.Worker(self.state,lambda *_:(json.dumps(self.mixed_response()),{})).tick()
            row=self.row();self.assertEqual(row['status'],'ready',row['error'])
            preview=planning.preview(row)
            self.assertIn('External transfer',preview);self.assertIn('test-model',preview)
            plan=json.loads(row['plan']);self.assertEqual(len(plan['tasks']),4)
            self.assertTrue(all(any(i['path']=='request/USER-REQUEST.txt' for i in t['inputs']) for t in plan['tasks']))
            self.start(row);self.click(row['token'])
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
            self.assertEqual(self.row()['status'],'started')

    def test_unrequested_or_unavailable_operation_cannot_be_approved(self):
        row=self.queue()
        with self.assertRaises(ValueError):planning.validate_result(json.dumps(self.mixed_response()),row)
        with patch.object(gemini,'read_config',return_value=None):
            snap={'capabilities':capabilities.catalog(self.state,{})}
            with self.assertRaisesRegex(ValueError,'unavailable'):
                planning.validate_action(self.action(step_capabilities=['gemini.text']),snap)

    def test_disconnection_between_plan_and_start_keeps_registration_atomic(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'test-model'}}):
            self.queue(action=self.action(step_capabilities=['text.bundle','gemini.text']))
            planning.Worker(self.state,lambda *_:(json.dumps(self.mixed_response()),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        with patch.object(gemini,'read_config',return_value=None):self.start(row)
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_planner_cannot_switch_the_frozen_api_model(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'chosen-model'}}):
            row=self.queue(action=self.action(step_capabilities=['text.bundle','gemini.text']))
        with self.assertRaisesRegex(ValueError,'frozen configured'):
            planning.validate_result(json.dumps(self.mixed_response()),row)


if __name__=='__main__':unittest.main()
