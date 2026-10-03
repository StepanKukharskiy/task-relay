import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from task_relay import work_state as ws


class WorkStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.db = ws.connect(self.root / 'state.sqlite')
        self.pid = ws.create(self.db, 'Guide', 'Make a guide.\nKeep exact wording.', self.root)
        (self.root / 'guide-v1.md').write_text('Guide one.')
        (self.root / 'guide-v2.md').write_text('Guide two, candidate.')
        self.manifest = {'schema': ws.SCHEMA, 'records': [
            {'id': 'source', 'kind': 'evidence', 'title': 'Assistant report', 'data': {'text': 'I accepted version two.', 'role': 'assistant', 'refs': [], 'topics': ['Guide', 'Research']}},
            {'id': 'reported', 'kind': 'decision', 'title': 'Acceptance claim', 'data': {'text': 'Version two accepted', 'refs': ['source'], 'topics': ['Guide']}},
            {'id': 'v1', 'kind': 'artifact', 'title': 'Guide one', 'data': {'path': 'guide-v1.md', 'family': 'guide', 'version': 1, 'sha256': hashlib.sha256(b'Guide one.').hexdigest(), 'refs': ['source'], 'topics': ['Guide']}},
            {'id': 'v2', 'kind': 'artifact', 'title': 'Guide two', 'data': {'path': 'guide-v2.md', 'family': 'guide', 'version': 2, 'sha256': hashlib.sha256(b'Guide two, candidate.').hexdigest(), 'refs': [], 'topics': ['Guide']}},
            {'id': 'issue', 'kind': 'issue', 'title': 'Source needed', 'data': {'text': 'A pricing claim needs a source.', 'refs': ['source'], 'topics': ['Research']}}
        ]}
        ws.import_records(self.db, self.pid, self.manifest, 'Import this exact record.')

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def apply(self, change, request='Explicit reviewed change'):
        review = ws.prepare_change(self.db, self.pid, ws.project(self.db, self.pid)['revision'], request, change)
        return ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True)

    def packet(self, **kwargs):
        return ws.prepare_packet(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Continue the guide.', **kwargs)

    def test_import_is_idempotent_and_does_not_promote_assistant_acceptance(self):
        before = ws.project(self.db, self.pid)['revision']
        ws.import_records(self.db, self.pid, self.manifest, 'Import this exact record.')
        state = ws.snapshot(self.db, self.pid)
        self.assertEqual(state['project']['revision'], before)
        self.assertEqual(state['decisions'], [])
        self.assertFalse(any(a['selected'] for a in state['artifacts']))
        self.assertEqual(state['proposals'][0]['data']['text'], 'Version two accepted')
        self.assertEqual(len(ws.provenance(self.db, self.pid, 'reported')['sources']), 1)

    def test_selected_version_stays_selected_when_newer_candidate_exists(self):
        result = self.apply({'action': 'select_artifact', 'target': 'v1'})
        state = ws.snapshot(self.db, self.pid)
        self.assertTrue(state['artifacts'][0]['selected'])
        self.assertTrue(state['artifacts'][1]['newest_recorded'])
        self.assertFalse(state['artifacts'][1]['selected'])
        packet = self.packet(topic='Guide')
        self.assertEqual(packet['packet']['selected_artifacts'][0]['id'], 'v1')
        self.assertEqual(packet['packet']['artifact_checks'][0]['text'], 'Guide one.')
        self.assertEqual(len(packet['packet']['open_issues']), 1, 'Topic view must not hide global unresolved constraints')
        self.assertIn('select_artifact', {e['relation'] for e in ws.graph(self.db, self.pid)['edges']})
        self.assertIn(result['record_id'], {n['id'] for n in ws.graph(self.db, self.pid)['nodes']})

    def test_review_is_exact_one_time_stale_and_project_scoped(self):
        revision = ws.project(self.db, self.pid)['revision']
        review = ws.prepare_change(self.db, self.pid, revision, 'Use guide one.', {'action': 'select_artifact', 'target': 'v1'})
        with self.assertRaises(ValueError): ws.commit_change(self.db, self.pid, review['review_id'], 'wrong', True)
        with self.assertRaises(ValueError): ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], False)
        other = ws.create(self.db, 'Other', 'Other task')
        with self.assertRaises(ValueError): ws.commit_change(self.db, other, review['review_id'], review['confirmation_token'], True)
        result = ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True)
        self.assertEqual(result, ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True))
        self.assertEqual(ws.project(self.db, self.pid)['revision'], revision + 2)
        stale = ws.prepare_change(self.db, self.pid, revision + 2, 'Record rule.', {'action': 'decision', 'text': 'Use primary sources.', 'supersedes': None})
        self.apply({'action': 'issue', 'text': 'New uncertainty.'})
        with self.assertRaisesRegex(ValueError, 'changed'): ws.commit_change(self.db, self.pid, stale['review_id'], stale['confirmation_token'], True)

    def test_atomic_failure_does_not_leave_request_or_decision(self):
        review = ws.prepare_change(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Use v1.', {'action': 'select_artifact', 'target': 'v1'})
        before = ws.project(self.db, self.pid)['revision']
        original = ws.append
        def fail(db, pid, kind, *args, **kwargs):
            if kind == 'decision': raise RuntimeError('controlled rollback')
            return original(db, pid, kind, *args, **kwargs)
        with patch.object(ws, 'append', side_effect=fail), self.assertRaises(RuntimeError):
            ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True)
        self.assertEqual(ws.project(self.db, self.pid)['revision'], before)
        self.assertEqual(self.db.execute('SELECT status FROM work_reviews WHERE id=?', (review['review_id'],)).fetchone()[0], 'pending')
        ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True)

    def test_supersession_only_marks_reviewed_dependencies_and_retains_history(self):
        old = self.apply({'action': 'decision', 'text': 'Compare all extensions.', 'supersedes': None})['record_id']
        self.apply({'action': 'dependency', 'source': old, 'target': 'v1'})
        new = self.apply({'action': 'decision', 'text': 'Focus on native plugins.', 'supersedes': old})['record_id']
        state = ws.snapshot(self.db, self.pid)
        self.assertEqual([r['id'] for r in state['decisions']], [new])
        self.assertEqual(state['artifacts'][0]['freshness'], 'potentially_affected')
        self.assertEqual(state['artifacts'][1]['freshness'], 'unknown')
        self.assertTrue(next(r for r in state['decision_history'] if r['id'] == old)['superseded'])
        self.assertEqual(ws.provenance(self.db, self.pid, new)['sources'][0]['data']['text'], 'Explicit reviewed change')

    def test_packet_budget_stale_work_and_external_file_change_are_not_silently_repaired(self):
        self.apply({'action': 'select_artifact', 'target': 'v1'})
        value = self.packet()
        self.assertEqual(value['packet_id'], self.packet()['packet_id'])
        ws.validate_packet(self.db, self.pid, value['packet_id'])
        with self.assertRaisesRegex(ValueError, 'budget'): self.packet(max_chars=1000)
        (self.root / 'guide-v1.md').write_text('Edited outside Relay')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): ws.validate_packet(self.db, self.pid, value['packet_id'])
        refreshed = self.packet(); self.assertEqual(refreshed['packet']['artifact_checks'][0]['status'], 'changed')
        self.apply({'action': 'issue', 'text': 'An unresolved scope change.'})
        with self.assertRaisesRegex(ValueError, 'stale'): ws.validate_packet(self.db, self.pid, refreshed['packet_id'])

    def test_original_secret_stays_private_and_all_public_views_are_redacted(self):
        secret = 'AIza' + 'x' * 35
        self.apply({'action': 'decision', 'text': 'api_key=' + secret, 'supersedes': None}, 'Preserve request ' + secret)
        original = self.db.execute("SELECT data FROM work_records WHERE kind='decision' AND authority='explicit_user_review'").fetchone()[0]
        self.assertIn(secret, original)
        for value in [ws.snapshot(self.db, self.pid), self.packet(), ws.graph(self.db, self.pid)]:
            self.assertNotIn(secret, json.dumps(value))

    def test_bad_import_and_linked_file_do_not_grant_access(self):
        for mutation in ('traversal', 'ref', 'role'):
            manifest = copy.deepcopy(self.manifest)
            if mutation == 'traversal': manifest['records'][2]['data']['path'] = '../outside'
            if mutation == 'ref': manifest['records'][0]['data']['refs'] = ['other-project-record']
            if mutation == 'role': manifest['records'][0]['authority'] = 'explicit_user_review'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): ws.import_records(self.db, self.pid, manifest, 'Try invalid import')
        (self.root / 'guide-v1.md').unlink(); (self.root / 'guide-v1.md').symlink_to(self.root / 'guide-v2.md')
        self.apply({'action': 'select_artifact', 'target': 'v1'})
        self.assertEqual(self.packet()['packet']['artifact_checks'][0]['status'], 'unavailable')

    def text_review(self):
        packet = self.packet()
        review = ws.prepare_change(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Write this reviewed guide.',
             {'action': 'write_text', 'packet_id': packet['packet_id'], 'family': 'guide', 'filename': 'guide.md', 'content': '# Reviewed guide\n'})
        return ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True)

    def test_text_execution_follows_commit_and_does_not_accept_new_output(self):
        result = self.text_review()
        write = ws.FILES.write
        def checked_write(*args, **kwargs):
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(self.db.execute('SELECT status FROM work_text_runs WHERE id=?', (result['run_id'],)).fetchone()[0], 'publishing')
            return write(*args, **kwargs)
        with patch.object(ws.FILES, 'write', side_effect=checked_write): receipt = ws.run_text(self.db, self.pid, result['run_id'])
        self.assertEqual((self.root / receipt['path']).read_text(), '# Reviewed guide\n')
        self.assertFalse(receipt['selected'])
        self.assertEqual(ws.run_text(self.db, self.pid, result['run_id']), receipt)
        self.assertEqual(len([a for a in ws.snapshot(self.db, self.pid)['artifacts'] if a['data']['version'] == 3]), 1)

    def test_interrupted_publication_recovers_matching_bytes_and_refuses_replay(self):
        result = self.text_review()
        append = ws.append
        def crash(db, pid, kind, *args, **kwargs):
            if kind == 'artifact': raise RuntimeError('crash after publication')
            return append(db, pid, kind, *args, **kwargs)
        with patch.object(ws, 'append', side_effect=crash), self.assertRaises(RuntimeError): ws.run_text(self.db, self.pid, result['run_id'])
        with self.assertRaisesRegex(ValueError, 'recovery'): ws.run_text(self.db, self.pid, result['run_id'])
        state = ws.snapshot(self.db, self.pid)
        self.assertEqual(state['execution_records'][-1]['current_status'], 'publishing')
        approved = self.apply({'action': 'recover_text', 'run_id': result['run_id']}, 'Recover this exact publication.')
        self.assertTrue(approved['recover'])
        with patch.object(ws.FILES, 'write', side_effect=AssertionError('duplicate publication')):
            receipt = ws.run_text(self.db, self.pid, result['run_id'], recover=True)
        self.assertEqual(receipt['status'], 'completed')
        second = self.text_review()
        with self.db: self.db.execute("UPDATE work_text_runs SET status='publishing' WHERE id=?", (second['run_id'],))
        with self.assertRaisesRegex(ValueError, 'will not repeat'): ws.run_text(self.db, self.pid, second['run_id'], recover=True)

    def test_work_and_selected_file_changes_after_start_block_execution(self):
        self.apply({'action': 'select_artifact', 'target': 'v1'})
        result = self.text_review()
        (self.root / 'guide-v1.md').write_text('Different input')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): ws.run_text(self.db, self.pid, result['run_id'])
        self.assertEqual(self.db.execute('SELECT status FROM work_text_runs WHERE id=?', (result['run_id'],)).fetchone()[0], 'queued')
        (self.root / 'guide-v1.md').write_text('Guide one.')
        self.apply({'action': 'issue', 'text': 'Scope changed after Start.'})
        with self.assertRaisesRegex(ValueError, 'Work changed'): ws.run_text(self.db, self.pid, result['run_id'])


if __name__ == '__main__': unittest.main()
