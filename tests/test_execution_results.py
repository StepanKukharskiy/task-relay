"""Small saved-record fixtures; no workers, native packages or provider calls."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import storage
from task_relay import execution_results as er, work_state as ws, work_understanding as wu
from task_relay import agent_candidate, fact_revisions, impact_handoff, work_state_cli


class ExecutionResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.db = ws.connect(self.root / 'state.sqlite')
        with ws.transaction(self.db):
            storage.initialize(self.db)
            agent_candidate.initialize(self.db)
            fact_revisions.initialize(self.db)
            impact_handoff.initialize(self.db)
        self.pid = ws.create(self.db, 'Saved work', 'Make a candidate.\nPreserve the request.', self.root)
        self.packet = self.prepare()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.db.close)

    def prepare(self):
        return ws.prepare_packet(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Continue the bounded action.')

    def production(self, ident='attempt', operation=None, provider='codex-cli', path='delivery/result.md', state='completed', receipt=None):
        spec = {'id': ident, 'instruction': 'Make exactly this candidate.\nDo not select it.'}
        frozen = {**spec, 'assignment_id': ident, 'assignment_version': 'assignment:' + ident, 'run': 'run',
                  'brief': 'Exact original brief.', 'backend': {'type': provider, 'model': 'fixture-model'},
                  'inputs': [{'artifact': 'input-v1', 'path': 'input.txt', 'sha256': '1' * 64}], 'outputs': [{'path': path}]}
        if operation: frozen['execution'] = {'capability': operation, 'parameters': {}}
        with ws.transaction(self.db):
            self.db.execute('INSERT INTO production_assignments VALUES (?,?,?,?,?)', ('assignment:' + ident, 'run', ident, 1, ws.encoded(spec)))
            self.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (ident, 'run', ident, 'assignment:' + ident, state, None, ws.encoded(frozen), '{"adapter":"fixture-process"}',
                             ws.encoded(receipt or {'exit_code': 0, 'started': 1, 'finished': 2}), None))
            self.db.execute('INSERT INTO production_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
                            ('output:' + ident, 'run', ident, ident, path, 'unopened-blob', '2' * 64, 12, 'candidate', 'worker'))
            self.db.execute('INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (?,?,?,?,?,?)',
                            (2, 'run', ident, ident, 'checks_recorded', ws.encoded({'kind': 'procedural', 'passed': True, 'checks': ['bounded output']})))

    def capture(self, kind='production_attempt', ident='attempt', key='capture', expected=None, packet=None, **kw):
        observed = er.inspect(self.db, kind, ident, kw.get('source_project'))
        return er.capture(self.db, self.pid, (packet or self.packet)['packet_id'], source_db=self.db, kind=kind, ident=ident,
                          expected_sha256=expected or observed['sha256'], request_key=key, request='Retain this exact result.', **kw)

    def external(self, native=True):
        ident = 'native' if native else 'sheet'
        plan = {'affected': []}
        with ws.transaction(self.db):
            self.db.execute('INSERT OR IGNORE INTO production_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
                ('baseline', None, None, None, 'baseline.fixture', 'never-read', '1' * 64, 10, 'baseline', 'external'))
            self.db.execute('INSERT INTO relay_impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('handoff:' + ident, 'job', 'source:' + ident, 'Modify only the bounded native locations.', 'fixture', 'baseline',
                 ws.encoded({'baseline_artifact': 'baseline'}), ws.digest(plan), ws.encoded(plan), 'fixture-user', 1))
            self.db.execute('INSERT INTO production_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
                ('candidate:' + ident, None, 'agent_candidate', None, ident + '.fixture', 'never-read', '3' * 64, 10, 'candidate', 'external'))
            common = (ident, 'job', 'submission', 'handoff:' + ident, 'candidate:' + ident, '3' * 64)
            if native:
                self.db.execute('INSERT INTO relay_agent_candidates VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (*common, '{}', 'fixture-worker', '{"semantic_review":"pending","visual_review":"not_performed"}', 2))
            else:
                self.db.execute('INSERT INTO relay_fact_external_submissions VALUES (?,?,?,?,?,?,?,?,?)',
                    (*common, '{"cells_checked":2}', 'fixture-worker', 2))
        return ident

    def direct(self):
        from task_relay import backends, gemini
        backends.initialize(self.db); gemini.initialize(self.db)
        with ws.transaction(self.db):
            self.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,?)', ('thread', 'gemini', 'session', 'not-opened', 'fixture-model', 1))
            self.db.execute('INSERT INTO backend_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            ('media', 'thread', 42, 'Generate the approved candidate.', 'completed', 1, 2, 3, 0, None, 'saved-response'))
            self.db.execute('INSERT INTO gemini_runs VALUES (?,?,?,?,?,?,?,?,?)',
                            ('media', 'image', 'fixture-image-model', 'complete', None, 'saved-response', '{}', '{}', 1))
            self.db.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            ('image', 'thread', 'media', 'output', 'image.fixture', 'image.fixture', 'text/plain', '4' * 64, 10, 3, 1))

    def test_five_job_shapes_and_provider_swap_keep_capture_logic(self):
        self.production('research', operation='pptx.create', path='deck.fixture')
        self.production('geometry', operation='rhino.run_python', path='model.fixture')
        sheet = self.external(native=False)
        self.production('code', provider='openai-code', path='patch.txt')
        self.direct()
        cases = [('production_attempt', 'research'), ('production_attempt', 'geometry'), ('xlsx_candidate', sheet),
                 ('production_attempt', 'code'), ('backend_job', 'media')]
        for kind, ident in cases:
            value = er.inspect(self.db, kind, ident)['envelope']
            self.assertEqual(value['schema'], er.SCHEMA)
            self.assertEqual(value['version'], 1)
            self.assertTrue(value['outputs']['artifacts'])
            self.assertEqual(value['status']['selection'], 'not_projected')
            self.assertEqual(value['status']['delivery'], 'not_projected')
            self.capture(kind, ident, key='capture:' + ident)
        self.production('swap', provider='gemini-agent')
        self.capture(ident='swap', key='capture:swap')
        state = ws.snapshot(self.db, self.pid)
        self.assertEqual(len(state['execution_results']), 6)
        self.assertEqual(state['decisions'], [])
        self.assertEqual(state['artifacts'], [], 'External result references never become selected project files')
        packet = self.prepare()['packet']
        self.assertEqual(len(packet['execution_results']), 6)
        sources = wu.prepare(self.db, self.pid, state['project']['revision'], 'Understand these results.')['input']['sources']
        evidence_ids = {json.loads(r[0])['evidence_id'] for r in self.db.execute('SELECT receipt FROM work_execution_captures')}
        self.assertTrue(evidence_ids <= {r['id'] for r in sources})

    def test_exact_requests_receipts_inputs_and_uncertainty_survive_capture(self):
        receipt = {'exit_code': 0, 'external_outcome': 'unknown', 'local_terminal': True, 'pending_requests': ['request-1']}
        self.production(receipt=receipt)
        before = self.db.execute('SELECT receipt FROM production_attempts').fetchone()[0]
        saved = self.capture()
        result = ws.snapshot(self.db, self.pid)['execution_results'][0]['data']['envelope']
        self.assertEqual(result['status']['execution'], 'completed')
        self.assertEqual(result['status']['certainty'], 'uncertain')
        self.assertEqual(result['assignment']['request'], 'Make exactly this candidate.\nDo not select it.')
        self.assertEqual(result['receipt']['attempt'], receipt)
        self.assertEqual(result['inputs'][0]['artifact'], 'input-v1')
        self.assertEqual(result['outputs']['artifacts'][0]['sha256'], '2' * 64)
        self.assertFalse(saved['execution_dispatch'])
        self.assertEqual(self.db.execute('SELECT receipt FROM production_attempts').fetchone()[0], before)
        original = json.loads(self.db.execute('SELECT result FROM work_execution_captures').fetchone()[0])['original']
        self.assertEqual(original[0]['rows'][0]['receipt'], before)

    def test_source_change_conflicting_retry_and_project_scope_are_guarded(self):
        self.production()
        old = er.inspect(self.db, 'production_attempt', 'attempt')['sha256']
        with ws.transaction(self.db): self.db.execute("UPDATE production_attempts SET state='uncertain'")
        with self.assertRaisesRegex(ValueError, 'source changed'): self.capture(expected=old)
        self.assertEqual(ws.project(self.db, self.pid)['revision'], 1)
        saved = self.capture()
        revision = ws.project(self.db, self.pid)['revision']
        expected = saved['result_sha256']
        with ws.transaction(self.db): self.db.execute("DELETE FROM production_attempts")
        # Same-key recovery reads its exact retained receipt even after deletion.
        kwargs = dict(source_db=self.db, kind='production_attempt', ident='attempt', expected_sha256=expected,
                      request_key='capture', request='Retain this exact result.')
        self.assertEqual(er.capture(self.db, self.pid, self.packet['packet_id'], **kwargs), saved)
        self.assertEqual(ws.project(self.db, self.pid)['revision'], revision)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            er.capture(self.db, self.pid, self.packet['packet_id'], **{**kwargs, 'request': 'Changed request.'})
        other = ws.create(self.db, 'Other', 'Other work')
        with self.assertRaisesRegex(ValueError, 'this project'):
            er.capture(self.db, other, self.packet['packet_id'], **kwargs)

    def test_capture_rollback_and_late_result_stale_understanding(self):
        self.production()
        with ws.transaction(self.db):
            rid = ws.append(self.db, self.pid, 'evidence', 'Shared source', 'explicit_local_request',
                            {'text': 'The candidate needs review.', 'origin': 'explicitly_supplied', 'refs': []})
        source = wu.prepare(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Understand the work.')
        citation = [{'record_id': rid, 'quote': 'The candidate needs review.'}]
        wu.save(self.db, self.pid, source['input_id'], {'objective': {'text': 'Review candidate.', 'citations': citation},
                 'conclusions': [], 'decision_proposals': [], 'open_questions': [], 'next_actions': [], 'workstreams': [], 'limits': []})
        self.assertFalse(ws.snapshot(self.db, self.pid)['understanding']['stale'])
        before = ws.project(self.db, self.pid)['revision']
        original = ws.append
        def fail(db, pid, kind, *args, **kwargs):
            if kind == 'evidence': raise RuntimeError('controlled capture interruption')
            return original(db, pid, kind, *args, **kwargs)
        with patch.object(ws, 'append', side_effect=fail), self.assertRaises(RuntimeError): self.capture()
        self.assertEqual(ws.project(self.db, self.pid)['revision'], before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM work_execution_captures').fetchone()[0], 0)
        saved = self.capture()
        state = ws.snapshot(self.db, self.pid)
        self.assertTrue(saved['state_changed_since_continuation'])
        self.assertTrue(state['understanding']['stale'])
        self.assertFalse(saved['execution_dispatch'])

    def test_changed_continuation_file_is_disclosed_without_losing_selected_version(self):
        self.production()
        (self.root / 'input.txt').write_text('Original input.')
        ws.import_records(self.db, self.pid, {'schema': ws.SCHEMA, 'records': [
            {'id': 'input', 'kind': 'artifact', 'title': 'Selected input', 'data': {
                'path': 'input.txt', 'family': 'guide', 'version': 1,
                'sha256': hashlib.sha256(b'Original input.').hexdigest(), 'refs': []}}]}, 'Connect this input.')
        control = ws.prepare_change(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Select this input.',
                                    {'action': 'select_artifact', 'target': 'input'})
        ws.commit_change(self.db, self.pid, control['review_id'], control['confirmation_token'], True)
        packet = self.prepare()
        (self.root / 'input.txt').write_text('Externally changed input.')
        with self.assertRaisesRegex(ValueError, 'artifact changed'): ws.validate_packet(self.db, self.pid, packet['packet_id'])
        saved = self.capture(packet=packet)
        self.assertTrue(saved['continuation_inputs_changed'])
        self.assertFalse(saved['state_changed_since_continuation'])
        self.assertEqual([a['id'] for a in ws.snapshot(self.db, self.pid)['artifacts'] if a['selected']], ['input'])

    def test_missing_sources_bounds_and_outer_transaction_preserve_atomicity(self):
        self.production()
        with self.assertRaisesRegex(ValueError, 'Missing'): er.inspect(self.db, 'production_attempt', 'absent')
        with ws.transaction(self.db), self.assertRaisesRegex(RuntimeError, 'outer rollback'):
            # Let the exception escape a separate nested transaction so the
            # caller's ownership transaction can still roll back the capture.
            with ws.transaction(self.db):
                self.capture()
                raise RuntimeError('outer rollback')
        self.assertEqual(self.db.execute('SELECT count(*) FROM work_execution_captures').fetchone()[0], 0)
        with ws.transaction(self.db):
            self.db.executemany('INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (?,?,?,?,?,?)',
                [(1, 'run', 'attempt', 'attempt', 'fixture', '{}')] * 1000)
        with self.assertRaisesRegex(ValueError, 'record budget'): self.capture()
        self.assertEqual(ws.project(self.db, self.pid)['revision'], 1)

    def test_external_candidate_plugin_notes_and_text_receipt_have_distinct_authority(self):
        ident = self.external()
        value = er.inspect(self.db, 'native_candidate', ident)['envelope']
        self.assertEqual(value['status']['execution'], 'not_recorded')
        self.assertEqual(value['status']['validation'], 'recorded')
        self.assertEqual(value['validation']['checks'][0]['data']['semantic_review'], 'pending')
        self.capture('native_candidate', ident)
        wu.capture(self.db, self.pid, self.packet['packet_id'], 'I selected the candidate.', ['Review the claim.'])
        key = self.db.execute('SELECT hash FROM work_result_captures').fetchone()[0]
        report = er.inspect(self.db, 'plugin_capture', key, self.pid)['envelope']
        self.assertEqual(report['status']['execution'], 'not_recorded')
        self.assertEqual(report['status']['selection'], 'not_projected')
        self.assertEqual(report['receipt']['authority'], 'model_report')
        self.capture('plugin_capture', key, key='model-report', source_project=self.pid)
        packet = self.prepare()
        review = ws.prepare_change(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Write exact text.',
            {'action': 'write_text', 'packet_id': packet['packet_id'], 'family': 'text', 'filename': 'candidate.txt', 'content': 'Small candidate.'})
        start = ws.commit_change(self.db, self.pid, review['review_id'], review['confirmation_token'], True)
        receipt = ws.run_text(self.db, self.pid, start['run_id'])
        text = er.inspect(self.db, 'work_text_run', start['run_id'])['envelope']
        self.assertEqual(text['receipt'], receipt)
        self.assertEqual(text['executor']['locality']['execution'], 'local')
        self.assertEqual(text['outputs']['artifacts'][0]['sha256'], receipt['sha256'])
        self.assertFalse(any(r['selected'] for r in ws.snapshot(self.db, self.pid)['artifacts']))

    def test_identity_hash_mismatch_and_unknown_source_are_not_promoted(self):
        self.production()
        with ws.transaction(self.db): self.db.execute("UPDATE production_artifacts SET run='foreign'")
        with self.assertRaisesRegex(ValueError, 'ownership'): er.inspect(self.db, 'production_attempt', 'attempt')
        native = self.external()
        with ws.transaction(self.db): self.db.execute("UPDATE relay_agent_candidates SET candidate_sha256=?", ('5' * 64,))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): er.inspect(self.db, 'native_candidate', native)
        with self.assertRaisesRegex(ValueError, 'Unsupported'): er.inspect(self.db, 'arbitrary_table', 'attempt')
        self.assertEqual(ws.snapshot(self.db, self.pid)['execution_results'], [])

    def test_export_recovers_after_write_and_refuses_changed_or_linked_outputs(self):
        self.production(); self.capture()
        original = er.FILES.read
        calls = 0
        def interrupted(*args):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError('controlled read-back interruption')
            return original(*args)
        with patch.object(er.FILES, 'read', side_effect=interrupted), self.assertRaises(OSError):
            er.export(self.db, self.pid, 'capture', 'result.json')
        self.assertTrue((self.root / 'result.json').is_file())
        self.assertIsNone(self.db.execute('SELECT receipt FROM work_execution_exports').fetchone()[0])
        saved = er.export(self.db, self.pid, 'capture', 'result.json')
        self.assertEqual(er.export(self.db, self.pid, 'capture', 'result.json'), saved)
        (self.root / 'result.json').write_text('Edited outside Relay.')
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'): er.export(self.db, self.pid, 'capture', 'result.json')
        self.assertEqual((self.root / 'result.json').read_text(), 'Edited outside Relay.')
        (self.root / 'linked.json').symlink_to(self.root / 'result.json')
        with self.assertRaises((ValueError, OSError)): er.export(self.db, self.pid, 'capture', 'linked.json')
        with self.assertRaises(ValueError): er.export(self.db, self.pid, 'capture', '../outside.json')
        with ws.transaction(self.db): self.db.execute("UPDATE work_execution_captures SET result='{}'")
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): er.export(self.db, self.pid, 'capture', 'other.json')

    def test_redaction_keeps_original_receipt_private(self):
        secret = 'AIza' + 'x' * 35
        self.production(receipt={'exit_code': 0, 'api_key': secret})
        observed = er.inspect(self.db, 'production_attempt', 'attempt')
        self.assertNotIn(secret, json.dumps(observed))
        self.capture()
        er.export(self.db, self.pid, 'capture', 'public.json')
        self.assertNotIn(secret, (self.root / 'public.json').read_text())
        self.assertNotIn(secret, json.dumps(ws.snapshot(self.db, self.pid)))
        self.assertIn(secret, self.db.execute('SELECT result FROM work_execution_captures').fetchone()[0])

    def test_cli_readonly_external_database_and_capture(self):
        self.production()
        source_path = self.root / 'source.sqlite'
        with contextlib.closing(sqlite3.connect(source_path)) as target: self.db.backup(target)
        (self.root / 'request.txt').write_text('Capture this externally saved result.')
        common = ['--db', str(self.root / 'state.sqlite')]
        source = ['--source-db', str(source_path), '--kind', 'production_attempt', '--source-id', 'attempt']
        with contextlib.redirect_stdout(io.StringIO()) as output:
            work_state_cli.main([*common, 'inspect-result', *source])
        observed = json.loads(output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            work_state_cli.main([*common, 'capture-execution', *source, '--project', self.pid,
                '--packet', self.packet['packet_id'], '--sha256', observed['sha256'], '--key', 'external-db',
                '--request-file', str(self.root / 'request.txt')])
        self.assertEqual(json.loads(output.getvalue())['status'], 'captured')
        with contextlib.closing(sqlite3.connect(source_path)) as source_db:
            self.assertEqual(source_db.execute('SELECT count(*) FROM work_execution_captures').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
