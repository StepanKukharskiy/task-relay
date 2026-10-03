"""Completion/capture recovery over small text records; no external execution."""
import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib

from orchestrator.runtime import Runtime
from task_relay import execution_capture as ec, execution_results as er, work_state as ws, work_understanding as wu
from task_relay import agent_candidate, fact_revisions, impact_handoff, revision_bundle, bundle_continuation
from task_relay import work_state_cli
from tests.test_orchestrator import FakeFactory, plan


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.factory = FakeFactory()
        self.rt = Runtime(self.root / 'runtime', self.factory)
        self.db = self.rt.db; self.addCleanup(self.rt.close)
        ws.initialize(self.db)
        self.pid = ws.create(self.db, 'Controlled continuation', 'Keep this exact request.', self.root)
        self.packet = ws.prepare_packet(self.db, self.pid, ws.project(self.db, self.pid)['revision'], 'Continue this exact action.')
        self.rt.create(plan()); self.rt.tick('demo')
        self.aid = self.rt.task('demo', 'produce')['latest']

    def link(self, **kw):
        return ec.bind(self.db, self.pid, self.packet['packet_id'], kind='production_attempt', ident=self.aid,
                       request_key='explicit-link', request='Capture this bounded action in this project.', **kw)

    def finish(self):
        self.factory.finish(self.aid)
        self.rt.tick('demo', dispatch=False)

    def test_runtime_completion_and_explicit_link_capture_once_without_selection(self):
        self.link(); self.finish()
        state = ws.snapshot(self.db, self.pid)
        envelope = state['execution_results'][0]['data']['envelope']
        self.assertEqual(envelope['assignment']['attempt_id'], self.aid)
        self.assertEqual(envelope['status']['execution'], 'completed')
        self.assertEqual(envelope['outputs']['artifacts'][0]['sha256'], self.rt.artifact(envelope['outputs']['artifacts'][0]['id'])['sha256'])
        self.assertEqual(state['decisions'], []); self.assertEqual(state['artifacts'], [])
        revision = state['project']['revision']
        ec.notify(self.db, 'production_attempt', self.aid); ec.recover(self.db)
        self.assertEqual(ws.project(self.db, self.pid)['revision'], revision)
        self.assertEqual(self.factory.calls, [self.aid])
        packet = ws.prepare_packet(self.db, self.pid, revision, 'Return to this result.')
        self.assertEqual(packet['packet']['execution_results'][0]['data']['envelope'], envelope)

    def test_unlinked_completion_records_observation_without_creating_work_or_capturing(self):
        before = ws.project(self.db, self.pid)['revision']; self.finish()
        self.assertEqual(ws.project(self.db, self.pid)['revision'], before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_result_observations').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_result_deliveries').fetchone()[0], 0)
        self.link()
        self.assertEqual(len(ws.snapshot(self.db, self.pid)['execution_results']), 1)

    def test_capture_failure_reopens_from_frozen_observation_after_source_disappears(self):
        self.link()
        with patch.object(er, 'capture', side_effect=OSError('controlled capture interruption')): self.finish()
        self.assertEqual(self.rt.task('demo', 'produce')['status'], 'completed')
        self.assertEqual(ec.status(self.db)['deliveries'][0]['status'], 'pending')
        self.assertEqual(ws.snapshot(self.db, self.pid)['execution_capture_state']['items'][0]['status'], 'pending')
        self.assertEqual(ws.snapshot(self.db, self.pid)['execution_results'], [])
        oid = self.db.execute('SELECT id FROM execution_result_observations').fetchone()[0]
        original = ec.observation(self.db, oid)
        with ws.transaction(self.db): self.db.execute('DELETE FROM production_attempts WHERE id=?', (self.aid,))
        self.rt.close()
        reopened = ws.connect(self.root / 'runtime/state.sqlite')
        try:
            ec.recover(reopened)
            state = ws.snapshot(reopened, self.pid)
            self.assertEqual(state['execution_results'][0]['data']['envelope'], ws.model_evidence(original['envelope']))
            self.assertEqual(ec.status(reopened)['deliveries'][0]['status'], 'captured')
            receipt = reopened.execute('SELECT receipt FROM execution_result_deliveries').fetchone()[0]
            ec.recover(reopened)
            self.assertEqual(reopened.execute('SELECT receipt FROM execution_result_deliveries').fetchone()[0], receipt)
        finally: reopened.close()
        self.assertEqual(self.factory.calls, [self.aid])

    def test_projection_failure_preserves_worker_completion_and_repairs_without_dispatch(self):
        self.link()
        with patch.object(er, '_inspect', side_effect=ValueError('controlled projection interruption')): self.finish()
        self.assertEqual(self.rt.task('demo', 'produce')['status'], 'completed')
        self.assertEqual(ec.status(self.db)['intents'][0]['status'], 'pending')
        self.assertEqual(ws.snapshot(self.db, self.pid)['execution_capture_state']['items'][0]['status'], 'projection_pending')
        receipt = self.db.execute('SELECT receipt FROM production_attempts WHERE id=?', (self.aid,)).fetchone()[0]
        ec.recover(self.db)
        self.assertEqual(ec.status(self.db)['intents'][0]['status'], 'recorded')
        self.assertEqual(len(ws.snapshot(self.db, self.pid)['execution_results']), 1)
        self.assertEqual(self.db.execute('SELECT receipt FROM production_attempts WHERE id=?', (self.aid,)).fetchone()[0], receipt)
        self.assertEqual(self.factory.calls, [self.aid])

    def test_changed_pending_source_is_retained_and_not_reinterpreted(self):
        with patch.object(er, '_inspect', side_effect=ValueError('controlled interruption')): self.finish()
        with ws.transaction(self.db): self.db.execute('UPDATE production_attempts SET error=? WHERE id=?', ('Later reconciliation', self.aid))
        ec.recover(self.db)
        status = ec.status(self.db)['intents'][0]
        self.assertEqual(status['status'], 'pending'); self.assertIn('source changed', status['error'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_result_observations').fetchone()[0], 0)

    def test_uncertain_launch_is_observed_and_never_resubmitted(self):
        self.rt.create({**plan(), 'id': 'ambiguous'})
        self.factory.fail = True; self.rt.tick('ambiguous')
        aid = self.rt.task('ambiguous', 'produce')['latest']
        value = self.db.execute('''SELECT o.id FROM execution_result_observations o JOIN execution_result_intents i ON i.id=o.intent
                                  WHERE i.source_id=?''', (aid,)).fetchone()
        self.assertEqual(ec.observation(self.db, value[0])['envelope']['status']['certainty'], 'uncertain')
        ec.recover(self.db); self.rt.tick('ambiguous')
        self.assertEqual(self.factory.calls.count(aid), 1)

    def test_outer_rollback_leaves_no_completion_observation_or_partial_work(self):
        self.link(); self.factory.finish(self.aid)
        previous = self.rt.task('demo', 'produce')['status']
        receipt = self.factory.inspect(self.factory.sessions[self.aid]['session'])
        with self.assertRaises(RuntimeError):
            with self.rt.transaction():
                self.rt.collect(self.db.execute('SELECT * FROM production_attempts WHERE id=?', (self.aid,)).fetchone(), receipt)
                raise RuntimeError('controlled outer rollback')
        self.assertEqual(self.rt.task('demo', 'produce')['status'], previous)
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_result_observations').fetchone()[0], 0)
        self.assertEqual(ws.snapshot(self.db, self.pid)['execution_results'], [])
        self.rt.tick('demo', dispatch=False)
        self.assertEqual(len(ws.snapshot(self.db, self.pid)['execution_results']), 1)

    def test_link_conflicts_cross_project_packets_and_nonterminal_backfill_are_refused(self):
        before = self.link()
        self.assertEqual(self.link(), before)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            ec.bind(self.db, self.pid, self.packet['packet_id'], kind='production_attempt', ident=self.aid,
                    request_key='explicit-link', request='Different request.')
        other = ws.create(self.db, 'Other', 'Other request')
        with self.assertRaisesRegex(ValueError, 'this project'):
            ec.bind(self.db, other, self.packet['packet_id'], kind='production_attempt', ident=self.aid, request_key='other', request='Foreign packet.')
        with self.assertRaisesRegex(ValueError, 'no completion'): ec.notify(self.db, 'production_attempt', self.aid)
        with self.assertRaises(ValueError): ec.recover(self.db, limit=0)

    def test_owned_plugin_capture_auto_envelope_remains_model_report_and_retry_is_exact(self):
        captured = wu.capture(self.db, self.pid, self.packet['packet_id'], 'I accepted the candidate.', ['Check this claim.'])
        state = ws.snapshot(self.db, self.pid)
        value = state['execution_results'][0]['data']['envelope']
        self.assertEqual(value['status']['execution'], 'not_recorded')
        self.assertEqual(value['receipt']['authority'], 'model_report')
        self.assertEqual(state['decisions'], [])
        revision = state['project']['revision']
        self.assertEqual(wu.capture(self.db, self.pid, self.packet['packet_id'], 'I accepted the candidate.', ['Check this claim.']), captured)
        self.assertEqual(ws.project(self.db, self.pid)['revision'], revision)

    def native_sources(self):
        with ws.transaction(self.db):
            for module in (agent_candidate, fact_revisions, impact_handoff, revision_bundle, bundle_continuation): module.initialize(self.db)
        baseline = self.root / 'baseline.txt'; baseline.write_text('Controlled baseline.')
        aid = self.rt.register(baseline, 'Controlled source')
        raw = {'baseline_artifact': aid}
        frozen = {'job': 'saved-fixture', 'plan_digest': ws.digest({}), 'plan': {}}
        with ws.transaction(self.db):
            self.db.execute('INSERT INTO relay_impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            ('native-handoff', frozen['job'], 'native-key', 'Bounded candidate only.', 'fixture', aid,
                             ws.encoded(raw), frozen['plan_digest'], '{}', 'fixture-user', 1))
        return frozen, aid

    def test_native_submission_hook_failure_preserves_admitted_candidate_and_retry(self):
        frozen, aid = self.native_sources()
        candidate = self.root / 'candidate.txt'; candidate.write_text('Admitted fixture bytes.')
        checks = {'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest()}
        args = dict(handoff_id='native-handoff', submission_key='candidate-key', candidate_path=candidate,
                    manifest={'edits': []}, image_files={}, submitted_by='fixture-worker')
        with patch.object(agent_candidate.pptx_edit, 'validate'), patch.object(agent_candidate, '_validate', return_value=(frozen, checks)), \
                patch.object(er, '_inspect', side_effect=ValueError('controlled projection failure')):
            candidate_id = agent_candidate.submit(self.rt, **args)
        self.assertEqual(self.rt.artifact(candidate_id)['sha256'], checks['candidate_sha256'])
        self.assertEqual(ec.status(self.db)['intents'][0]['status'], 'pending')
        ec.recover(self.db)
        self.assertEqual(ec.status(self.db)['intents'][0]['status'], 'recorded')
        with patch.object(agent_candidate.pptx_edit, 'validate'), patch.object(agent_candidate, 'verified'):
            self.assertEqual(agent_candidate.submit(self.rt, **args), candidate_id)
        self.assertEqual(self.db.execute('SELECT count(*) FROM relay_agent_candidates').fetchone()[0], 1)
        self.assertEqual(ws.snapshot(self.db, self.pid)['execution_results'], [], 'An unbound external candidate cannot choose a work project')

    def test_bundle_and_continuation_submission_hooks_preserve_three_member_sets(self):
        frozen, baseline = self.native_sources()
        candidate = self.rt.register(self.root / 'baseline.txt', 'Controlled native candidate')
        companions = {}; members = []
        for role in ('slides', 'photo_manifest'):
            path = self.root / (role + '.txt'); path.write_text('Controlled ' + role)
            companions[role] = path
            members.append({'role': role, 'baseline_artifact': baseline, 'baseline_sha256': self.rt.artifact(baseline)['sha256'],
                            'candidate_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        with ws.transaction(self.db):
            self.db.execute('INSERT INTO relay_revision_bundle_plans VALUES (?,?,?,?,?,?,?,?,?)',
                ('bundle-plan', frozen['job'], 'bundle-key', 'native-handoff', 'Bounded candidate set.', ws.digest({}), '{}', 'fixture-user', 1))
        checks = {'set_digest': 'a' * 64, 'declared_checks': 13}
        with patch.object(revision_bundle, '_check', return_value=(frozen, members, checks)):
            bundle = revision_bundle.submit(self.rt, plan_id='bundle-plan', pptx_candidate_artifact=candidate,
                submission_key='bundle-key', companion_files=companions, submitted_by='fixture-worker')
            self.assertEqual(revision_bundle.submit(self.rt, plan_id='bundle-plan', pptx_candidate_artifact=candidate,
                submission_key='bundle-key', companion_files=companions, submitted_by='fixture-worker'), bundle)
        selected_receipt = ws.encoded({'explicit_selection': 'fixture'})
        parent = {'pptx_baseline_artifact': candidate, 'pptx_baseline_sha256': self.rt.artifact(candidate)['sha256'],
                  'image_artifact': baseline, 'image_sha256': self.rt.artifact(baseline)['sha256'], 'companions': [], 'reused': [],
                  'parent_set_digest': checks['set_digest'], 'parent_selection_sha256': hashlib.sha256(selected_receipt.encode()).hexdigest()}
        with ws.transaction(self.db):
            self.db.execute('INSERT INTO relay_revision_bundle_selections VALUES (?,?,?,?,?,?)', (bundle, frozen['job'], checks['set_digest'], 'fixture-user', selected_receipt, 2))
            self.db.execute('INSERT INTO relay_bundle_continuation_plans VALUES (?,?,?,?,?,?,?,?,?)',
                            ('continuation-plan', frozen['job'], 'continued-key', bundle, 'Continue this selected set.',
                             ws.digest(parent), ws.encoded(parent), 'fixture-user', 3))
        continued_checks = {'set_digest': 'b' * 64, 'pptx_sha256': self.rt.artifact(candidate)['sha256'],
                            'companions': {m['role']: {'candidate_sha256': m['candidate_sha256']} for m in members}}
        frozen = {**frozen, 'plan': parent, 'plan_digest': ws.digest(parent)}
        with patch.object(bundle_continuation, '_check', return_value=(frozen, continued_checks)), patch.object(bundle_continuation, 'verified'):
            continued = bundle_continuation.submit(self.rt, plan_id='continuation-plan', submission_key='continued-key',
                pptx_file=self.root / 'baseline.txt', companion_files=companions, submitted_by='fixture-worker')
            self.assertEqual(bundle_continuation.submit(self.rt, plan_id='continuation-plan', submission_key='continued-key',
                pptx_file=self.root / 'baseline.txt', companion_files=companions, submitted_by='fixture-worker'), continued)
        observations = [ec.observation(self.db, r[0])['envelope'] for r in self.db.execute('SELECT id FROM execution_result_observations')]
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(len(r['outputs']['artifacts']) == 3 for r in observations))
        self.assertTrue(all(r['status']['selection'] == 'not_projected' for r in observations))

    def test_spreadsheet_submission_hook_retains_checked_candidate_without_native_execution(self):
        frozen, baseline = self.native_sources()
        path = self.root / 'sheet.txt'; path.write_text('Checked cell fixture.')
        plan = {'baseline_artifact': baseline, 'old_source': baseline, 'replacement_source': baseline,
                'digest': 'c' * 64, 'affected': []}
        checks = {'candidate_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        with patch.object(fact_revisions, '_external_checks', return_value=({**frozen, 'plan': plan}, checks)), \
                patch('task_relay.reviewed_links.save_impact'), patch.object(fact_revisions, '_verified_candidate'):
            aid = fact_revisions.submit_external_xlsx(self.rt, handoff_id='native-handoff', submission_key='sheet-key', candidate_file=path, submitted_by='fixture-worker')
            self.assertEqual(fact_revisions.submit_external_xlsx(self.rt, handoff_id='native-handoff', submission_key='sheet-key', candidate_file=path, submitted_by='fixture-worker'), aid)
        observed = ec.observation(self.db, self.db.execute('SELECT id FROM execution_result_observations').fetchone()[0])['envelope']
        self.assertEqual(observed['outputs']['artifacts'][0]['sha256'], checks['candidate_sha256'])
        self.assertEqual(observed['status']['execution'], 'not_recorded')

    def test_local_cli_binding_status_and_recovery_use_existing_completion(self):
        request = self.root / 'capture-request.txt'; request.write_text('Connect exactly this completion.')
        prefix = ['--db', str(self.root / 'runtime/state.sqlite')]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            work_state_cli.main([*prefix, 'bind-result', '--project', self.pid, '--packet', self.packet['packet_id'],
                '--kind', 'production_attempt', '--source-id', self.aid, '--key', 'cli-link', '--request-file', str(request)])
        self.assertFalse(json.loads(output.getvalue())['execution_dispatch'])
        with patch.object(er, 'capture', side_effect=OSError('controlled interruption')): self.finish()
        with contextlib.redirect_stdout(io.StringIO()) as output: work_state_cli.main([*prefix, 'recover-results', '--limit', '1'])
        self.assertEqual(json.loads(output.getvalue())['deliveries'][0]['status'], 'captured')
        with contextlib.redirect_stdout(io.StringIO()) as output: work_state_cli.main([*prefix, 'completion-status'])
        self.assertEqual(json.loads(output.getvalue())['intents'][0]['status'], 'recorded')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            work_state_cli.main([*prefix, 'observe-result', '--kind', 'production_attempt', '--source-id', self.aid])
        self.assertFalse(json.loads(output.getvalue())['execution_dispatch'])
        self.assertEqual(len(ws.snapshot(self.db, self.pid)['execution_results']), 1)
        self.assertEqual(self.factory.calls, [self.aid])


if __name__ == '__main__': unittest.main()
