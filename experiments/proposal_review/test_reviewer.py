import copy
import unittest

from .reviewer import apply_literal, request_for, validate


class ReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.case = {'documents': {'u': {'kind': 'user', 'text': 'Always record attendees.'},
                                   'g': {'kind': 'guide', 'text': 'Export notes.'}},
                     'change': {'target': 'g', 'before': 'Export notes.',
                                'after': 'Export notes. Record attendees.'},
                     'proposal': {'scope': 'Meeting notes'},
                     'expected': 'secret oracle', 'provenance': 'secret source label'}
        self.docs = request_for(self.case)[1]
        self.review = {
            'scope': {'kind': 'standing_rule', 'supported': True, 'reason': 'Explicit request',
                      'citations': [self.cite('u')]},
            'coverage': {'status': 'novel', 'reason': 'Missing from guide',
                         'citations': [self.cite('g')]},
            'benefit': {'status': 'hypothesis', 'reason': 'Needs a production trial'},
            'issues': [], 'counterexamples': [{'situation': 'No names in source',
                      'expected_behavior': 'Do not invent names', 'proposal_behavior': 'Requires judgment'}],
            'recommendation': 'ready_for_human_review', 'summary': 'Ready for user review'}

    def cite(self, name):
        return {'document': name, 'line_start': 1, 'line_end': 1,
                'quote': self.docs[name]['text']}

    def test_valid_review_routes_without_approval(self):
        result = validate(self.review, self.docs)
        self.assertEqual(result['status'], 'ready_for_human_review')
        self.assertFalse(result['approval'])

    def test_exact_quote_is_required(self):
        self.review['scope']['citations'][0]['quote'] = 'Always include everyone.'
        with self.assertRaisesRegex(ValueError, 'exact line span'):
            validate(self.review, self.docs)

    def test_agent_interpretation_is_not_user_authority(self):
        self.docs['u']['kind'] = 'assistant'
        with self.assertRaisesRegex(ValueError, 'source kind'):
            validate(self.review, self.docs)

    def test_contradiction_overrides_ready_recommendation(self):
        self.review['issues'] = [{'kind': 'contradiction', 'explanation': 'Opposing instruction remains',
                                  'citations': [self.cite('A:g')]}]
        self.assertEqual(validate(self.review, self.docs)['status'], 'needs_revision_or_evidence')

    def test_contradiction_must_refer_to_amended_document(self):
        self.review['issues'] = [{'kind': 'contradiction', 'explanation': 'Conflict',
                                  'citations': [self.cite('g')]}]
        with self.assertRaisesRegex(ValueError, 'source kind'):
            validate(self.review, self.docs)

    def test_missing_scope_and_existing_coverage_block_readiness(self):
        for field, key, value in [('scope', 'supported', False),
                                  ('coverage', 'status', 'already_covered'),
                                  ('benefit', 'status', 'unsupported_guarantee')]:
            review = copy.deepcopy(self.review)
            review[field][key] = value
            with self.subTest(field=field):
                self.assertEqual(validate(review, self.docs)['status'], 'needs_revision_or_evidence')

    def test_full_amended_document_includes_untouched_remainder(self):
        self.case['documents']['g']['text'] += '\nLater conflicting instruction.'
        payload, docs = request_for(self.case)
        self.assertTrue(docs['A:g']['text'].endswith('Later conflicting instruction.'))
        self.assertNotIn('expected', payload)
        self.assertNotIn('provenance', payload)

    def test_stale_ambiguous_and_noop_replacements_fail(self):
        for original, before, after in [('abc', 'missing', 'x'), ('a a', 'a', 'b'),
                                         ('a', 'a', 'a'), ('a', '', 'b')]:
            with self.subTest(original=original, before=before):
                with self.assertRaises(ValueError):
                    apply_literal(original, before, after)

    def test_malformed_or_uncited_review_cannot_pass(self):
        for value in [None, [], {}, {**self.review, 'issues': None}]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate(value, self.docs)
        self.review['scope']['citations'] = []
        with self.assertRaises(ValueError):
            validate(self.review, self.docs)


if __name__ == '__main__':
    unittest.main()
