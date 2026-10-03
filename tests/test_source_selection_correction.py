"""A missing source decision must not require regenerating an authorized task."""
import copy
import json
import unittest
from unittest.mock import patch

from task_relay import orchestrator_chat as chat
from tests import test_production_planning as fixtures
from tests.test_artifact_handoff import Tests as ArtifactFixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    corrected_request=ArtifactFixtures.corrected_request
    action=fixtures.Tests.action
    row=fixtures.Tests.row

    def run_correction(self, selection):
        original=self.action(artifact_ids=[],task_seconds=300,deliverables={
            'profile_summary':'Profile and visible posts after scroll, with citations and excerpts'})
        before=copy.deepcopy(original)
        with patch.object(chat.orchestrator_images,'files',return_value=[
                {'id':'unrelated-upload','status':'ready','filename':'unrelated.txt'}]):
            calls=self.corrected_request(original,selection,'Start a new run of the same profile research task.')
        self.assertEqual(original,before)
        self.assertEqual(len(calls),2)
        return original,calls

    def test_source_only_patch_preserves_exact_proposal_and_queues_once(self):
        original,calls=self.run_correction({'reference_ids':[]})
        row=self.row(92)
        self.assertIsNotNone(row)
        self.assertEqual(row['request'],'Start a new run of the same profile research task.')
        options=json.loads(row['options'])
        self.assertEqual(options['deliverables'],original['deliverables'])
        self.assertEqual(options['limits']['seconds'],300)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        receipt=self.state.get('orchestrator-source-correction:92')
        self.assertEqual(json.loads(receipt['response'])['action'],original)
        self.assertEqual(json.loads(receipt['corrected_response'])['action'],{'reference_ids':[]})
        expected={**original,'reference_ids':[]}
        self.assertEqual(receipt['validated_response']['action'],expected)
        saved=json.loads(self.state.db.execute('SELECT response FROM orchestrator_chats WHERE id=92').fetchone()[0])
        self.assertEqual(saved['action'],expected)
        self.assertEqual(calls[1]['routing_source_correction']['missing_fields'],['reference_ids'])

    def test_scope_field_in_patch_cannot_expand_task(self):
        self.run_correction({'reference_ids':[],'task_seconds':1800})
        self.assertIsNone(self.row(92))
        receipt=self.state.get('orchestrator-source-correction:92')
        self.assertIn('corrected_response',receipt)
        self.assertNotIn('validated_response',receipt)

    def test_paraphrased_full_action_still_cannot_replace_saved_task(self):
        changed=self.action(artifact_ids=[],reference_ids=[],task_seconds=300,
            deliverables={'profile_summary':'Profile and visible posts after scroll, with direct citations'})
        self.run_correction(changed)
        self.assertIsNone(self.row(92))

    def test_unknown_selected_upload_is_rejected_before_queue(self):
        self.run_correction({'reference_ids':['invented']})
        self.assertIsNone(self.row(92))

    def test_ambiguous_sources_can_ask_without_queue(self):
        self.run_correction(None)
        self.assertIsNone(self.row(92))
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=92').fetchone()[0],'answered')


if __name__=='__main__':unittest.main()
