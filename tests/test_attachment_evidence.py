import copy
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from task_relay import attachment_evidence as evidence, orchestrator_context as context


class Tests(unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE production_attempts(id TEXT,run TEXT,task TEXT,state TEXT,frozen TEXT)')
        self.state = SimpleNamespace(db=db)
        self.addCleanup(db.close)
        self.correct = 'a' * 64
        self.other = 'b' * 64
        self.files = [{'id': 3, 'filename': 'photo.jpg', 'path': '/saved/3/photo.jpg',
                       'sha256': self.correct, 'status': 'ready', 'bytes': 123}]

    def attempt(self, ident, digest, **extra):
        self.state.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?)',
            (ident, 'run-' + ident, 'inspect', 'blocked', json.dumps({
                'inputs': [{'artifact': ident, 'path': 'photo.jpg', 'sha256': digest}], **extra})))

    def payload(self):
        return {'user_message': 'Inspect this new image and source three options per item.',
                'snapshot': {'focus': None, 'current_attachment_ids': [3], 'uploaded_files': self.files,
                    'production_runs': [{'name': 'run-old', 'status': 'blocked',
                        'tasks': [{'error': 'The old photo shows a botanical slide, not furniture.'}]}],
                    'production_plans': [{'id': 'old-plan', 'run': 'run-old', 'status': 'started',
                        'result': {'message': 'Reject old botanical image'}}]},
                'history': [{'id': 2, 'prompt': 'Source furniture.',
                             'answer': 'This exact photo.jpg was botanical.'}],
                'current_attachment_evidence': evidence.capture(self.state, [3], self.files)}

    def test_other_hash_same_filename_cannot_supply_current_observation(self):
        self.attempt('old', self.other)
        current = evidence.capture(self.state, [3], self.files)
        self.assertEqual(current['files'][0]['matching_worker_inputs'], [])
        self.assertEqual(current['files'][0]['sha256'], self.correct)
        self.assertIn('No pixels', current['observation_state'])

    def test_reupload_same_bytes_keeps_matching_receipt_not_acceptance(self):
        self.attempt('same', self.correct)
        files = [{**self.files[0], 'id': 99, 'path': '/saved/99/photo.jpg'}]
        item = evidence.capture(self.state, [99], files)['files'][0]
        self.assertEqual(item['matching_worker_inputs'][0]['attempt_id'], 'same')
        self.assertEqual(item['matching_worker_inputs'][0]['state'], 'blocked')
        self.assertNotIn('accepted', item)

    def test_digest_mentioned_in_prose_is_not_an_input_receipt(self):
        self.attempt('old', self.other, instruction='Current upload hash ' + self.correct)
        self.assertEqual(evidence.capture(self.state, [3], self.files)['files'][0]['matching_worker_inputs'], [])

    def test_missing_binding_never_substitutes_another_photo(self):
        result = evidence.capture(self.state, [99], self.files)
        self.assertEqual(result['missing_ids'], [99])
        self.assertEqual(result['files'], [])

    def test_fresh_upload_overview_excludes_stale_claims_but_exact_reads_remain(self):
        self.attempt('old', self.other)
        payload = self.payload()
        original = copy.deepcopy(payload)
        small = context.overview(payload)
        self.assertNotIn('botanical', json.dumps(small))
        self.assertEqual(small['history'][0]['prompt'], payload['history'][0]['prompt'])
        self.assertEqual(small['history'][0]['answer_pointer'], '/history/0/answer')
        pointer = small['snapshot']['production_runs'][0]['catalog_pointer']
        read = context.Evidence(payload).execute({'arguments': json.dumps({'pointer': pointer, 'offset': 0, 'limit': 16000})})
        self.assertEqual(json.loads(read['text']), payload['snapshot']['production_runs'][0])
        self.assertEqual(payload, original)

    def test_matching_run_or_explicit_reply_keeps_its_record(self):
        self.attempt('old', self.correct)
        payload = self.payload()
        scoped_runs = context.overview(payload)['snapshot']['production_runs']
        self.assertIn('botanical', json.dumps(scoped_runs))
        self.assertEqual(scoped_runs[0]['attachment_input_receipts'][0]['sha256'], self.correct)
        payload['current_attachment_evidence'] = evidence.capture(self.state, [99], self.files)
        for extra in ({'reply_plan_id': 'old-plan'}, {'entry_context': {'followup': {'mode': 'work'}}}):
            with self.subTest(extra=extra):
                self.assertEqual(evidence.overview_scope({**payload, **extra}), {**payload, **extra})
        payload['snapshot']['focus'] = 'run-old'
        self.assertEqual(evidence.overview_scope(payload), payload)

    def test_bounded_receipts_do_not_claim_complete_search_or_visual_read(self):
        for i in range(evidence.LIMIT + 1):
            self.attempt(str(i), self.correct)
        item = evidence.capture(self.state, [3], self.files)['files'][0]
        self.assertFalse(item['complete'])
        self.assertEqual(len(item['matching_worker_inputs']), evidence.LIMIT)
        self.assertIn('does not prove visual inspection', evidence.INSTRUCTIONS)

    def test_saved_photo_followup_gets_same_provenance_without_selecting_a_file(self):
        self.attempt('old', self.other)
        payload = self.payload()
        payload['user_message'] = '2'
        payload['snapshot'].pop('current_attachment_ids')
        payload['conversation_attachment_evidence'] = payload.pop('current_attachment_evidence')
        payload['conversation_attachment_evidence']['authority'] = 'Historical context only'
        small = context.overview(payload)
        self.assertNotIn('botanical', json.dumps(small))
        self.assertNotIn('current_attachment_ids', small['snapshot'])
        self.assertEqual(small['conversation_attachment_evidence']['files'][0]['id'], 3)
        self.assertNotIn('current_attachment_evidence', small)
        payload['snapshot']['catalog'] = ['unrelated context ' * 20000] * 20
        with patch.object(context, 'MAX_OVERVIEW', 35000):
            small = context.overview(payload)
        self.assertEqual(small['conversation_attachment_evidence'], payload['conversation_attachment_evidence'])

    def test_hash_evidence_survives_large_overview(self):
        payload = self.payload()
        payload['snapshot']['catalog'] = ['long unrelated context ' * 10000] * 30
        with patch.object(context, 'MAX_OVERVIEW', 35000):
            small = context.overview(payload)
        self.assertEqual(small['current_attachment_evidence'], payload['current_attachment_evidence'])
        self.assertLessEqual(len(context.encoded(small).encode()), 35000)


if __name__ == '__main__':
    unittest.main()
