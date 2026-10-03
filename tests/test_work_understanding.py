import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay import work_state as ws, work_understanding as understand


class UnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.db = ws.connect(self.root / 'state.sqlite')
        self.pid = ws.create(self.db, 'Guide', 'Make a guide.', self.root)
        (self.root / 'guide.md').write_text('First guide.')
        ws.import_records(self.db, self.pid, {'schema': ws.SCHEMA, 'records': [
            {'id': 'brief', 'kind': 'evidence', 'title': 'Shared brief', 'data': {
                'text': 'Make a guide. Verify the climate source.', 'role': 'user', 'origin': 'explicitly_supplied', 'refs': [], 'topics': []}},
            {'id': 'v1', 'kind': 'artifact', 'title': 'First guide', 'data': {'path': 'guide.md', 'family': 'guide', 'version': 1,
                'sha256': hashlib.sha256(b'First guide.').hexdigest(), 'refs': ['brief'], 'topics': []}},
            {'id': 'archive', 'kind': 'evidence', 'title': 'Unselected archive', 'data': {'text': 'Unrelated historic text.', 'refs': [], 'topics': []}}
        ]}, 'Connect this brief and its draft.')
        self.review({'action': 'select_artifact', 'target': 'v1'})

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def review(self, change):
        control = ws.prepare_change(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Explicit fixture review.', change)
        return ws.commit_change(self.db, self.pid, control['review_id'], control['confirmation_token'], True)

    def prepare(self, **kwargs):
        return understand.prepare(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Understand the guide.', **kwargs)

    def report(self):
        cite = [{'record_id': 'brief', 'quote': 'Verify the climate source.'}]
        return {'objective': {'text': 'Produce the guide with a checked climate source.', 'citations': cite},
            'conclusions': [{'text': 'The brief asks for climate verification.', 'citations': cite}],
            'decision_proposals': [{'text': 'Use only verified climate references.', 'citations': cite}],
            'open_questions': [{'text': 'Which climate source supports the guide?', 'citations': cite}],
            'next_actions': [{'text': 'Verify the climate source.', 'reason': 'The explicit brief still requires it.', 'citations': cite, 'topics': ['Climate']}],
            'workstreams': [{'name': 'Climate', 'record_ids': ['brief', 'v1']}],
            'limits': ['Quote checks establish source identity, not semantic correctness.']}

    def test_connected_loop_keeps_proposals_selected_version_and_captures_late_output(self):
        source = self.prepare()
        self.assertEqual(source['input_id'], self.prepare()['input_id'])
        self.assertNotIn('archive', {r['id'] for r in source['input']['sources']})
        self.assertGreater(source['input']['coverage']['available_records'], source['input']['coverage']['selected_records'])
        saved = understand.save(self.db, self.pid, source['input_id'], self.report())
        state = ws.snapshot(self.db, self.pid)
        self.assertFalse(state['understanding']['stale'])
        self.assertEqual(state['decisions'], [], 'Model decision proposals do not establish user acceptance')
        self.assertEqual([a['id'] for a in state['artifacts'] if a['selected']], ['v1'])
        action = state['next_actions'][0]
        context = ws.prepare_packet(self.db, self.pid, state['project']['revision'], action['data']['text'], 'Climate', action_id=action['id'])
        self.assertEqual([a['id'] for a in context['packet']['selected_artifacts']], ['v1'], 'Derived views preserve selected artifacts')
        self.assertIn('brief', {r['id'] for r in context['packet']['evidence']})
        self.assertEqual(context['packet']['understanding']['authority'], 'model_proposal')
        assignment = self.review({'action': 'write_text', 'packet_id': context['packet_id'], 'family': 'guide', 'filename': 'guide.md', 'content': 'Second guide.'})
        ws.run_text(self.db, self.pid, assignment['run_id'])
        result = understand.capture(self.db, self.pid, context['packet_id'], 'A second candidate guide was produced; climate verification remains unresolved.', ['Verify the source before selection.'])
        self.assertTrue(result['state_changed_since_continuation'])
        self.assertEqual(result, understand.capture(self.db, self.pid, context['packet_id'], 'A second candidate guide was produced; climate verification remains unresolved.', ['Verify the source before selection.']))
        final = ws.snapshot(self.db, self.pid)
        self.assertTrue(final['understanding']['stale'])
        self.assertEqual([a['data']['version'] for a in final['artifacts'] if a['selected']], [1])
        self.assertEqual([a['data']['version'] for a in final['artifacts'] if not a['selected']], [2])
        self.assertFalse(result['execution_dispatch'])
        graph = ws.graph(self.db, self.pid)
        ids = {n['id'] for n in graph['nodes']}
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in graph['edges']))
        self.assertTrue(any(e['relation'] == 'in_workstream_view' and e['source'] == 'v1' for e in graph['edges']))
        self.assertEqual(saved, understand.save(self.db, self.pid, source['input_id'], self.report()), 'Exact saved retries retain their receipt after work moves on')
        self.assertIn(result['record_id'], {r['id'] for r in self.prepare()['input']['sources']})

    def test_foreign_sources_invalid_quotes_and_unselected_archive_are_rejected_atomically(self):
        source = self.prepare(); before = ws.project(self.db, self.pid)['revision']
        other = ws.create(self.db, 'Other', 'Private request.')
        foreign = ws.records(self.db, other)[0]['id']
        for rid, quote in [('brief', 'Invented quote'), (foreign, 'Private request.'), ('archive', 'Unrelated historic text.')]:
            report = self.report(); report['next_actions'][0]['citations'] = [{'record_id': rid, 'quote': quote}]
            with self.assertRaises(ValueError): understand.save(self.db, self.pid, source['input_id'], report)
            self.assertEqual(ws.project(self.db, self.pid)['revision'], before)
            self.assertIsNone(ws.snapshot(self.db, self.pid)['understanding'])
        included = self.prepare(record_ids=['archive'])
        self.assertIn('archive', {r['id'] for r in included['input']['sources']})

    def test_coverage_and_freshness_follow_saved_inputs_and_explicit_changes(self):
        with patch.object(ws.time, 'time', return_value=2000):
            source = self.prepare()
        with patch.object(ws.time, 'time', return_value=3000):
            understand.save(self.db, self.pid, source['input_id'], self.report())
        state = ws.snapshot(self.db, self.pid)
        self.assertEqual(state['understanding']['saved_at'], 3000, 'Show save time, not input preparation time')
        self.assertEqual(state['understanding']['coverage'], {
            'considered_records': 3, 'considered_sources': 3, 'cited_sources': 1})
        self.assertEqual(state['source_coverage'], {'connected_sources': 5, 'added_since_understanding': 0})
        ws.provenance(self.db, self.pid, 'archive')
        self.assertEqual(ws.snapshot(self.db, self.pid)['understanding'], state['understanding'],
                         'Inspecting an unselected source must not imply it informed the saved overview')
        ws.import_records(self.db, self.pid, {'schema': ws.SCHEMA, 'records': [
            {'id': 'new-note', 'kind': 'evidence', 'title': 'New brief', 'data': {
                'text': 'New work since the overview.', 'origin': 'explicitly_supplied', 'refs': []}}]}, 'Connect the new note.')
        changed = ws.snapshot(self.db, self.pid)
        self.assertTrue(changed['understanding']['stale'])
        self.assertEqual(changed['understanding']['changed_records'], 1)
        self.assertEqual(changed['source_coverage'], {'connected_sources': 6, 'added_since_understanding': 1})
        self.assertEqual(changed['understanding']['coverage'], state['understanding']['coverage'])
        self.review({'action': 'issue', 'text': 'Confirm the source.'})
        issue = next(r for r in ws.snapshot(self.db, self.pid)['open_issues'] if r['data']['text'] == 'Confirm the source.')
        self.review({'action': 'resolve_issue', 'target': issue['id']})
        final = ws.snapshot(self.db, self.pid)
        self.assertEqual([r['id'] for r in final['resolved_issues']], [issue['id']])
        self.assertEqual(final['resolved_issues'][0]['resolution_authority'], 'explicit_user_review')
        self.assertEqual(final['decisions'], [], 'Resolving a question must not accept a model decision')

    def test_changed_state_or_selected_file_blocks_analysis_and_suggestion_use(self):
        source = self.prepare()
        (self.root / 'guide.md').write_text('Outside edit.')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): understand.save(self.db, self.pid, source['input_id'], self.report())
        (self.root / 'guide.md').write_text('First guide.')
        understand.save(self.db, self.pid, source['input_id'], self.report())
        state = ws.snapshot(self.db, self.pid); action = state['next_actions'][0]
        (self.root / 'guide.md').write_text('Changed after analysis.')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): ws.prepare_packet(self.db, self.pid, state['project']['revision'], action['data']['text'], action_id=action['id'])
        (self.root / 'guide.md').write_text('First guide.')
        stale_input = self.prepare()
        self.review({'action': 'issue', 'text': 'A new unresolved instruction.'})
        with self.assertRaisesRegex(ValueError, 'stale'): understand.save(self.db, self.pid, stale_input['input_id'], self.report())
        with self.assertRaisesRegex(ValueError, 'stale'): ws.prepare_packet(self.db, self.pid, ws.project(self.db, self.pid)['revision'], action['data']['text'], action_id=action['id'])

    def test_partial_save_rolls_back_and_can_be_retried_without_duplicate_actions(self):
        source = self.prepare(); original = ws.append
        def fail_action(*args, **kwargs):
            if args[2] == 'next_action': raise OSError('Controlled publication failure')
            return original(*args, **kwargs)
        with patch.object(ws, 'append', side_effect=fail_action):
            with self.assertRaises(OSError): understand.save(self.db, self.pid, source['input_id'], self.report())
        self.assertIsNone(ws.snapshot(self.db, self.pid)['understanding'])
        receipt = understand.save(self.db, self.pid, source['input_id'], self.report())
        self.assertEqual(receipt, understand.save(self.db, self.pid, source['input_id'], self.report()))
        self.assertEqual(len(ws.snapshot(self.db, self.pid)['next_actions']), 1)
        changed = self.report(); changed['next_actions'][0]['reason'] = 'Changed reason.'
        with self.assertRaisesRegex(ValueError, 'cannot be replaced'): understand.save(self.db, self.pid, source['input_id'], changed)

    def test_capture_cannot_cross_project_or_mask_corrupt_context(self):
        context = ws.prepare_packet(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Continue the guide.')
        other = ws.create(self.db, 'Other', 'Other work.')
        with self.assertRaises(ValueError): understand.capture(self.db, other, context['packet_id'], 'A result.', [])
        with ws.transaction(self.db): self.db.execute("UPDATE work_packets SET sha256='invalid' WHERE id=?", (context['packet_id'],))
        before = ws.project(self.db, self.pid)['revision']
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): understand.capture(self.db, self.pid, context['packet_id'], 'A result.', [])
        self.assertEqual(ws.project(self.db, self.pid)['revision'], before)

    def test_budget_excess_and_unbound_groups_do_not_save_partial_understanding(self):
        count = self.db.execute('SELECT COUNT(*) FROM work_understanding_inputs').fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'budget'): self.prepare(max_chars=1000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM work_understanding_inputs').fetchone()[0], count)
        source = self.prepare()
        report = self.report(); report['workstreams'][0]['record_ids'] = ['archive']
        with self.assertRaises(ValueError): understand.save(self.db, self.pid, source['input_id'], report)
        self.assertIsNone(ws.snapshot(self.db, self.pid)['understanding'])

    def test_action_only_evidence_uses_disclosed_excerpts_instead_of_archive_text(self):
        ws.import_records(self.db, self.pid, {'schema': ws.SCHEMA, 'records': [
            {'id': 'long-note', 'kind': 'evidence', 'title': 'Explicit source note',
             'data': {'text': 'Background. ' * 10000 + 'Verify the climate source.', 'refs': [], 'topics': []}}
        ]}, 'Connect this particular source note.')
        report = self.report()
        report['next_actions'][0]['citations'] = [{'record_id': 'long-note', 'quote': 'Verify the climate source.'}]
        source = self.prepare(record_ids=['long-note'], max_chars=200000)
        understand.save(self.db, self.pid, source['input_id'], report)
        state = ws.snapshot(self.db, self.pid); action = state['next_actions'][0]
        packet = ws.prepare_packet(self.db, self.pid, state['project']['revision'], action['data']['text'], action_id=action['id'])['packet']
        note = next(r for r in packet['evidence'] if r['id'] == 'long-note')
        self.assertEqual(note['data']['text'], 'Verify the climate source.')
        self.assertEqual(packet['evidence_coverage']['excerpted_record_ids'], ['long-note'])
        self.assertIn('Background.', ws.provenance(self.db, self.pid, 'long-note')['record']['data']['text'])


if __name__ == '__main__': unittest.main()
