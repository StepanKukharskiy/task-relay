"""Host input aliases are compiled before approval, without changing artifacts."""
import copy
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import contracts as c
from orchestrator.storage import transaction
from task_relay import production_planning as planning
from tests import test_native_inspection_binding as native
from tests import test_rhino_planning as rhino
from tests.test_blender_operations import operation


class PathTests(unittest.TestCase):
    def task(self):
        return operation('blender.startup', [dict(artifact='source', path='delivery/request.txt',
            purpose='Request', authority='Exact user request', media_type='text/plain')])

    def test_runtime_still_rejects_reserved_inputs(self):
        task=self.task()
        with self.assertRaisesRegex(ValueError, 'reserved delivery directory'):
            c.assignment(task)
        planning.bind_host_input_paths([task])
        c.assignment(task)
        self.assertEqual(planning.bind_host_input_paths([task]), [])

    def test_collisions_and_traversal_are_not_repaired(self):
        for path in ('source-inputs/delivery/request.txt', 'SOURCE-INPUTS/delivery/REQUEST.txt',
                     'source-inputs', 'source-inputs/delivery/request.txt/child'):
            with self.subTest(path=path):
                task=self.task();task['inputs'].append({**task['inputs'][0], 'artifact':'other', 'path':path})
                with self.assertRaisesRegex(ValueError, 'conflicts'):
                    planning.bind_host_input_paths([task])
        task=self.task();task['inputs'][0]['path']='delivery/../request.txt'
        with self.assertRaises(ValueError):planning.bind_host_input_paths([task])

    def test_safe_aliases_and_agent_tasks_remain_unchanged(self):
        host=self.task();host['inputs'][0]['path']='selected/request.txt'
        agent={'id':'author','inputs':[{'path':'delivery/reference.txt'}]}
        tasks=[host,agent];original=copy.deepcopy(tasks)
        self.assertEqual(planning.bind_host_input_paths(tasks), [])
        self.assertEqual(tasks,original)


class InspectionTests(unittest.TestCase):
    def setUp(self):
        native.Tests.setUp(self)
        del self.fail
    tearDown=native.Tests.tearDown
    request=native.Tests.request
    action=native.Tests.action
    queue=native.Tests.queue
    row=native.Tests.row
    response=native.Tests.response
    case=native.Tests.case

    def check_upstream(self,kind):
        row,response,_,media=self.case(kind)
        item=response['plan']['tasks'][1]['inputs'][0]
        item['path']=item['output'];original=copy.deepcopy(response)
        _,plan=planning.validate_result(json.dumps(response),row)
        self.assertEqual(response,original)
        inspector=plan['tasks'][1]
        bound=next(i for i in inspector['inputs'] if i.get('media_type')==media)
        self.assertEqual(bound['path'],'source-inputs/'+item['output'])
        self.assertEqual(bound['output'],item['output'])
        self.assertEqual(bound['from_task'],item['from_task'])
        self.assertEqual(plan['tasks'][0]['outputs'],original['plan']['tasks'][0]['outputs'])
        self.assertEqual(len(plan['origin']['input_path_bindings']),1)

    def test_rhino_output_identity(self):self.check_upstream('rhino')
    def test_blender_output_identity(self):self.check_upstream('blender')
    def test_sketchup_output_identity(self):self.check_upstream('sketchup')


class SelectedScriptTests(unittest.TestCase):
    def setUp(self):
        rhino.Tests.setUp(self)
        del self.fail
        signature=patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/rhino'})
        signature.start();self.addCleanup(signature.stop)
    tearDown=rhino.Tests.tearDown
    request=rhino.Tests.request
    action=rhino.Tests.action
    queue=rhino.Tests.queue
    row=rhino.Tests.row
    response=rhino.Tests.response
    setup_plan=rhino.Tests.setup_plan

    def saved_proposal(self):
        row=self.setup_plan()
        response=copy.deepcopy(self.prepared_response)
        for item in response['plan']['tasks'][0]['inputs']:
            item['path']='delivery/'+Path(item['path']).name
        return row,response

    def test_selected_code_checks_and_limits_are_unchanged(self):
        row,response=self.saved_proposal();original=copy.deepcopy(response)
        _,plan=planning.validate_result(json.dumps(response),row)
        host=plan['tasks'][0];proposal=response['plan']['tasks'][0]
        for field in ('execution','limits','max_attempts','user_gate','outputs'):
            self.assertEqual(host[field],proposal[field])
        self.assertEqual(response,original)
        for item in proposal['inputs']:
            bound=next(i for i in host['inputs'] if i.get('artifact')==item['artifact'])
            self.assertEqual(bound['path'],'source-inputs/'+item['path'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_blocked_saved_proposal_recovers_without_provider_or_execution(self):
        row,response=self.saved_proposal();raw=json.dumps(response)
        error='Host inputs must stay outside the reserved delivery directory.'
        with self.state.db:
            self.state.db.execute("UPDATE production_plans SET status='blocked',error=?,plan=NULL,result=NULL WHERE id=?",(error,row['id']))
            self.state.db.execute('DELETE FROM production_plan_calls WHERE plan_id=?',(row['id'],))
            self.state.db.execute('INSERT INTO production_plan_calls VALUES (?,?,?,?,?,?,?)',(row['id'],1,'{}',raw,'{}',error,time.time()))
        old=dict(self.row())
        with transaction(self.state.db),patch.object(planning.Worker,'tick',side_effect=AssertionError('No provider retry')):
            ident,receipt=planning.recover_validated_response(self.state,row['id'])
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        self.assertEqual(successor['status'],'ready');self.assertIsNone(successor['run'])
        self.assertEqual(dict(self.row()),old)
        call=self.state.db.execute('SELECT * FROM production_plan_calls').fetchone()
        self.assertEqual(call['response'],raw);self.assertEqual(call['error'],error)
        self.assertEqual(receipt['plan_id'],row['id'])
        self.assertTrue(json.loads(successor['plan'])['origin']['input_path_bindings'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'already recovered'),transaction(self.state.db):
            planning.recover_validated_response(self.state,row['id'])
