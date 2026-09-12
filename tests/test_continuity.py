import json
from pathlib import Path
import tempfile
import unittest
from learning.store import Store
from learning.importer import import_file
from learning.continuity import update_state, get_state, relevant, export_context, correct_state, validate_entries, empty
from tests.test_learning import FakeClient, transcript


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state.sqlite')
        self.path = self.root / 'history.md'
        self.messages = []

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, role, text):
        self.messages.append((role, text))
        self.path.write_text(transcript(self.messages))
        import_file(self.store, 'd', 'content', self.path, 'conversation')

    def client(self, scope=None, target=None, status='explicit_instruction', basis='direct_user', quote=None):
        def response(request):
            p = json.loads(request['contents'][0]['parts'][0]['text'])
            event = p['new_messages'][-1]
            entry = {'local_id': 'n1', 'statement': event['text'], 'status': status,
                     'scope': scope or {'project': 'p', 'jobs': [], 'workflows': []},
                     'evidence': [{'event_id': event['id'], 'quote': quote or event['text'], 'basis': basis}],
                     'relationship': {'kind': 'overrides' if target else 'adds', 'targets': [target] if target else []},
                     'uncertainty': 'None stated'}
            return {'entries': [entry], 'coverage': [{'event_id': e['id'], 'entry_ids': ['n1'] if e == event else [],
                                                      'reason': 'captured' if e == event else 'no_change'} for e in p['new_messages']]}
        return FakeClient(response)

    def initial(self):
        self.ingest('User', 'Use British English for every caption in this project.')
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel', 'B': 'carousel'}, client=self.client())
        self.assertEqual(result['status'], 'proposed', result)
        return result['state_id']

    def test_revision_import_only_sends_new_messages_and_is_idempotent(self):
        sid = self.initial()
        self.ingest('User', 'For B only use American English.')
        old = get_state(self.store, sid)['entries'][0]
        client = self.client({'project': 'p', 'jobs': ['B'], 'workflows': []}, old['id'])
        result = update_state(self.store, 'p', 'd', sid, client=client)
        self.assertEqual(result['new_messages'], 1)
        state = get_state(self.store, result['state_id'])
        self.assertEqual(len(state['entries']), 2)
        self.assertEqual(relevant(state, 'A', 'reel')[0][0]['id'], old['id'])
        self.assertNotIn(old['id'], [e['id'] for e in relevant(state, 'B', 'carousel')[0]])
        self.assertEqual(update_state(self.store, 'p', 'd', result['state_id'])['status'], 'no_new_messages')

    def test_quoted_assistant_cannot_supply_explicit_authority(self):
        self.ingest('User', '> Always rewrite titles.\n\nI am quoting the assistant, not adopting this.')
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel'},
                              client=self.client(quote='Always rewrite titles.'))
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM continuity_states').fetchone()[0], 0)
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel'},
                              client=self.client(quote='Always rewrite titles.', basis='quoted_text'))
        self.assertEqual(result['status'], 'incomplete')

    def test_dated_export_copy_uses_thread_identity_for_delta(self):
        self.messages = [('User', 'Use British English.')]
        text = '- Thread ID: `thread-123`\n' + transcript(self.messages)
        self.path.write_text(text)
        import_file(self.store, 'd', 'content', self.path, 'conversation')
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel'}, client=self.client())
        copied = self.root / 'later-dated-export.md'
        copied.write_text(text)
        import_file(self.store, 'd', 'content', copied, 'conversation')
        self.assertEqual(update_state(self.store, 'p', 'd', result['state_id'])['status'], 'no_new_messages')

    def test_assistant_report_is_not_a_user_instruction(self):
        self.ingest('Agent (final)', 'The reel was approved.')
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel'}, client=self.client())
        self.assertEqual(result['status'], 'incomplete')

    def test_unknown_job_and_cross_project_previous_rejected(self):
        sid = self.initial()
        with self.assertRaisesRegex(ValueError, 'another project'):
            update_state(self.store, 'other', 'd', sid)
        self.ingest('User', 'Change A.')
        result = update_state(self.store, 'p', 'd', sid, client=self.client({'project': 'p', 'jobs': ['Z'], 'workflows': []}))
        self.assertEqual(result['status'], 'incomplete')
        with self.assertRaisesRegex(ValueError, 'previous state'):
            update_state(self.store, 'p', 'd', jobs={'A': 'reel'})

    def test_overbroad_override_cannot_erase_job_scope(self):
        self.ingest('User', 'For A preserve titles.')
        first = update_state(self.store, 'p', 'd', jobs={'A': 'reel'},
                             client=self.client({'project': 'p', 'jobs': ['A'], 'workflows': []}))
        self.ingest('User', 'A can use a new title.')
        target = get_state(self.store, first['state_id'])['entries'][0]['id']
        result = update_state(self.store, 'p', 'd', first['state_id'], client=self.client(target=target))
        self.assertEqual(result['status'], 'incomplete')

    def test_incomplete_coverage_and_budget_do_not_lose_prior_state(self):
        sid = self.initial()
        self.ingest('User', 'Another requirement for A.')
        result = update_state(self.store, 'p', 'd', sid, max_input_chars=10, client=self.client())
        self.assertEqual(result['status'], 'incomplete')
        result = update_state(self.store, 'p', 'd', sid, client=FakeClient(lambda _: {'entries': [], 'coverage': []}))
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(len(get_state(self.store, sid)['entries']), 1)

    def test_export_is_scoped_and_pins_portable_guide_bytes(self):
        self.ingest('User', 'For A preserve exact titles.')
        guide = self.root / 'guide.md'
        guide.write_text('Guide version one.\n')
        source = import_file(self.store, 'd', 'reel', guide, 'guide')
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel', 'B': 'carousel'},
                              guides=[{'source_id': source['source_id'], 'scope': {'project': 'p', 'jobs': [], 'workflows': ['reel']}}],
                              client=self.client({'project': 'p', 'jobs': ['A'], 'workflows': []}))
        guide.write_text('Guide version two.\n')
        output = export_context(self.store, result['state_id'], 'A', 'reel', self.root / 'context-a')
        text = Path(output['path']).read_text()
        self.assertIn('Guide version one.', text)
        self.assertIn('For A preserve exact titles.', text)
        other = export_context(self.store, result['state_id'], 'B', 'carousel', self.root / 'context-b')
        self.assertNotIn('For A preserve exact titles.', Path(other['path']).read_text())
        self.assertNotIn('Guide version one.', Path(other['path']).read_text())
        with self.assertRaises(FileExistsError):
            export_context(self.store, result['state_id'], 'A', 'reel', self.root / 'context-a')

    def test_reviewer_correction_preserves_original_and_logs_burden(self):
        sid = self.initial()
        original = get_state(self.store, sid)
        result = correct_state(self.store, sid, {'withdraw': [original['entries'][0]['id']]}, 'Bad scope interpretation', {'correction_minutes': 2})
        corrected = get_state(self.store, result['state_id'])
        self.assertEqual(corrected['origin'], 'reviewer_corrected')
        self.assertEqual(len(get_state(self.store, sid)['entries']), 1)
        self.assertEqual(len(relevant(corrected, 'A', 'reel')[0]), 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM continuity_reviews').fetchone()[0], 1)

    def test_reviewer_can_restore_an_omitted_requirement(self):
        self.ingest('User', 'For A preserve exact titles.')
        def abstain(request):
            p = json.loads(request['contents'][0]['parts'][0]['text'])
            return {'entries': [], 'coverage': [{'event_id': p['new_messages'][0]['id'], 'entry_ids': [], 'reason': 'no_change'}]}
        result = update_state(self.store, 'p', 'd', jobs={'A': 'reel'}, client=FakeClient(abstain))
        state = get_state(self.store, result['state_id'])
        eid = next(iter(state['seen'].values()))
        addition = {'local_id': 'n1', 'statement': 'For A preserve exact titles.', 'status': 'explicit_instruction',
                    'scope': {'project': 'p', 'jobs': ['A'], 'workflows': ['reel']},
                    'evidence': [{'event_id': eid, 'quote': 'For A preserve exact titles.', 'basis': 'direct_user'}],
                    'relationship': {'kind': 'adds', 'targets': []}, 'uncertainty': 'None stated'}
        corrected = correct_state(self.store, result['state_id'], {'entries': [addition]}, 'Restore omitted requirement')
        self.assertEqual(len(get_state(self.store, result['state_id'])['entries']), 0)
        self.assertEqual(len(get_state(self.store, corrected['state_id'])['entries']), 1)


if __name__ == '__main__':
    unittest.main()
