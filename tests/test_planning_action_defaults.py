"""Nullable routing metadata must not block valid work or invent source choices."""
import copy
import json
import unittest
from unittest.mock import Mock

from task_relay import orchestrator_chat as chat, production_planning as planning
from tests import test_production_planning as fixture


class Tests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        del self.fail
    tearDown=fixture.Tests.tearDown
    action=fixture.Tests.action
    request=fixture.Tests.request
    row=fixture.Tests.row

    def test_omitted_unused_pack_queues_once_preserving_raw_response_and_request(self):
        action=self.action();del action['reference_pack_id']
        request='Follow this workflow and make the editable model'
        self.bridge.process({'update_id':1,'message':{'text':request,'chat':{'id':7,'type':'private'},'from':{'id':7}}})
        raw=json.dumps({'answer':'Prepare the requested stage.', 'action':action})
        generator=Mock(return_value=raw)
        worker=chat.Worker(self.state,generator);worker.tick();worker.tick()
        self.assertEqual(generator.call_count,1)
        row=self.row();self.assertIsNotNone(row)
        self.assertIsNone(json.loads(row['options'])['reference_pack_id'])
        self.assertEqual(row['request'],request)
        job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertEqual(job['response'],raw)
        receipt=self.state.get('orchestrator-action-defaults:1')
        self.assertEqual(receipt['normalized_action'],{**action,'reference_pack_id':None})
        self.assertEqual(receipt['response'],raw)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_available_pack_requires_selection_and_explicit_pack_is_preserved(self):
        action=self.action();del action['reference_pack_id']
        snap={'reference_packs':[{'id':'pack-1','status':'ready'}]}
        self.assertEqual(planning.normalize_action(action,snap),action)
        with self.assertRaises(ValueError):planning.validate_action(action,snap)
        explicit={**action,'reference_pack_id':'pack-1'}
        self.assertEqual(planning.normalize_action(explicit,snap),explicit)
        self.assertNotIn('reference_pack_id',action)

    def test_no_defaults_for_authorization_or_required_source_fields(self):
        for field in ('planning_only','research_ids','project'):
            action=self.action();del action['reference_pack_id'];del action[field]
            before=copy.deepcopy(action)
            with self.subTest(field=field), self.assertRaises(ValueError):
                chat.interpret(json.dumps({'answer':'Plan', 'action':action}),{})
            self.assertEqual(action,before)

    def test_explicit_invalid_pack_unknown_field_and_unknown_project_stay_blocked(self):
        for ident, extra in enumerate([{'reference_pack_id':'missing'}, {'unexpected':True}, {'project':'/unknown'}],1):
            action={**self.action(),**extra}
            self.request(action,ident=ident)
            self.assertIsNone(self.row(ident))
            answer=self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()[0]
            self.assertIn('could not validate the proposed action',answer)
            self.assertNotIn('invalid response format',answer)
            self.assertIsNone(self.state.get('orchestrator-action-defaults:'+str(ident)))

    def test_duplicate_keys_are_not_normalized(self):
        raw='{"answer":"Plan","action":{"kind":"plan_production","kind":"run"}}'
        with self.assertRaisesRegex(ValueError,'Duplicate'):chat.interpret(raw,{})
        self.assertFalse(chat.action_response(raw))
