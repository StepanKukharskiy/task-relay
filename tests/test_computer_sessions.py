"""Small synthetic receipts exercise O15.2 durable dispatch and recovery."""
from contextlib import closing, contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay import computer_sessions as sessions
from task_relay import computer_contract as contract
from tests.test_computer_use import Helper, TARGET


class SessionHelper:
    identity = {'protocol': contract.PROTOCOL, 'binary_sha256': 'fixture-session'}

    def __init__(self, db, hook=None):
        self.db, self.hook = db, hook
        self.calls, self.opens = [], 0

    @contextmanager
    def session(self):
        self.opens += 1
        yield self

    def call(self, request):
        assert not self.db.in_transaction
        # Another connection sees the committed intent before the external call.
        path = self.db.execute('PRAGMA database_list').fetchone()[2]
        with closing(sqlite3.connect(path)) as reader:
            assert reader.execute("SELECT count(*) FROM relay_computer_actions WHERE state='claimed' AND resolved=0").fetchone()[0] == 1
        self.calls.append(copy.deepcopy(request))
        if self.hook:
            self.hook(request, len(self.calls))
        observation = Helper().call(request['observation_request'])
        return {'protocol': contract.PROTOCOL, 'ok': True, 'token': 'token-' + str(len(self.calls)), 'observation': observation}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = sqlite3.connect(self.root/'state.sqlite', isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE relay_pipelines(id TEXT PRIMARY KEY)')
        self.db.execute("INSERT INTO relay_pipelines VALUES ('job')")
        sessions.initialize(self.db)
        self.spec = {'target': TARGET, 'url': 'https://example.com/one',
                     'allowed_urls': ['https://example.com/one', 'https://example.com/two'],
                     'actions': [{'operation': 'navigate', 'url': 'https://example.com/two'},
                                 {'operation': 'scroll', 'direction': 'down'}],
                     'capture': False, 'local_fixture': False, 'max_seconds': 300}

    def approve(self, key='request-1', spec=None):
        return sessions.approve(self.db, job='job', request_key=key,
            exact_request='Read these two synthetic pages, then scroll once.',
            spec=spec or self.spec, helper=SessionHelper.identity, output_root=self.root/'evidence', actor='fixture user')

    def test_committed_intents_exact_plan_and_completed_duplicate_never_dispatch(self):
        ident = self.approve()
        helper = SessionHelper(self.db)
        result = sessions.run(self.db, ident, helper)
        self.assertEqual(result['assignment']['state'], 'completed')
        self.assertEqual([r['operation'] for r in helper.calls], ['bind', 'navigate', 'scroll'])
        self.assertEqual(helper.calls[1]['token'], 'token-1')
        before = list(self.db.iterdump())
        sessions.run(self.db, ident, helper)
        self.assertEqual(helper.opens, 1)
        self.assertEqual(before, list(self.db.iterdump()))
        self.assertEqual(self.approve(), ident)
        changed = copy.deepcopy(self.spec); changed['actions'] = []
        with self.assertRaises(ValueError): self.approve(spec=changed)

    def test_timeout_is_uncertain_and_new_key_cannot_evade_recovery(self):
        ident = self.approve()
        def fail(req, count):
            if count == 2: raise TimeoutError('lost after navigation')
        helper = SessionHelper(self.db, fail)
        with self.assertRaises(TimeoutError): sessions.run(self.db, ident, helper)
        result = sessions.inspect(self.db, ident)
        self.assertEqual(result['actions'][-1]['state'], 'uncertain')
        self.assertEqual(result['assignment']['cursor'], 1)
        with self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
        with self.assertRaises(ValueError): self.approve(key='evade')
        sessions.resume(self.db, ident, current_url=self.spec['allowed_urls'][1], actor='user', note='Continue; skip uncertain navigation.')
        recovered = SessionHelper(self.db)
        sessions.run(self.db, ident, recovered)
        self.assertEqual([r['operation'] for r in recovered.calls], ['bind', 'scroll'])
        old = sessions.actions(self.db, ident)[1]
        self.assertEqual(old['state'], 'uncertain')
        self.assertEqual(old['resolved'], 1)

    def test_crash_after_claim_before_call_is_not_replayed(self):
        ident = self.approve()
        with transaction(self.db):
            self.db.execute("UPDATE relay_computer_assignments SET state='running',deadline=9999999999 WHERE id=?", (ident,))
        sessions._claim(self.db, ident, {'operation': 'navigate'}, 0)
        helper = SessionHelper(self.db)
        with self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
        self.assertEqual(helper.opens, 0)
        sessions.resume(self.db, ident, current_url=self.spec['url'], actor='user', note='Inspected page; skip unproven action.')
        sessions.run(self.db, ident, helper)
        self.assertEqual([r['operation'] for r in helper.calls], ['bind', 'scroll'])

    def test_pause_and_cancel_during_call_stop_future_dispatch(self):
        for kind in ('pause', 'cancel'):
            with self.subTest(kind=kind):
                # Finish the previous iteration before authorizing another plan.
                ident = self.approve(key=kind)
                def stop(req, count):
                    sessions.control(self.db, ident, kind, actor='user', note='Stop after current call.')
                helper = SessionHelper(self.db, stop)
                result = sessions.run(self.db, ident, helper)
                self.assertEqual(len(helper.calls), 1)
                self.assertEqual(result['actions'][0]['state'], 'completed')
                self.assertEqual(result['assignment']['state'], 'paused' if kind == 'pause' else 'cancelled')
                if kind == 'pause': sessions.control(self.db, ident, 'cancel', actor='user', note='End fixture.')

    def test_publication_failure_preserves_uncertainty_and_cannot_recapture(self):
        ident = self.approve()
        helper = SessionHelper(self.db)
        with patch.object(sessions, 'write_new', side_effect=OSError('full disk')):
            with self.assertRaises(OSError): sessions.run(self.db, ident, helper)
        with self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
        self.assertEqual(len(helper.calls), 1)
        self.assertEqual(sessions.actions(self.db, ident)[0]['state'], 'uncertain')

    def test_changed_saved_evidence_cannot_trigger_repair_by_execution(self):
        ident = self.approve()
        helper = SessionHelper(self.db)
        sessions.run(self.db, ident, helper)
        receipt = json.loads(sessions.actions(self.db, ident)[0]['receipt'])
        (Path(receipt['folder'])/'page.txt').write_text('changed')
        with self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
        self.assertEqual(helper.opens, 1)

    def test_outer_transaction_and_changed_helper_block_before_native_start(self):
        ident = self.approve()
        helper = SessionHelper(self.db)
        with transaction(self.db), self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
        helper.identity = {'different': True}
        with self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
        self.assertEqual(helper.opens, 0)

    def test_stale_token_or_changed_url_stops_plan_and_keeps_uncertainty(self):
        for changed in ('token', 'url'):
            ident = self.approve(key=changed)
            class BadReply(SessionHelper):
                def call(self, request):
                    reply = super().call(request)
                    if len(self.calls) == 2:
                        if changed == 'token': reply['token'] = request['token']
                        else: reply['observation']['url'] = 'https://other.example/'
                    return reply
            helper = BadReply(self.db)
            with self.assertRaises(ValueError): sessions.run(self.db, ident, helper)
            self.assertEqual(len(helper.calls), 2)
            self.assertEqual(sessions.actions(self.db, ident)[-1]['state'], 'uncertain')
            sessions.resume(self.db, ident, current_url=self.spec['url'], actor='user', note='Stop invalid fixture reply.', abandon=True)

    def test_private_pipe_transport_handles_response_and_eof_without_resending(self):
        import subprocess
        import sys
        from task_relay.host_computer import NativeSession
        script = ('import sys,json; x=json.loads(sys.stdin.readline()); '
                  'print(json.dumps({"protocol":x["protocol"],"ok":True,"token":"fixture"}),flush=True)')
        child = subprocess.Popen([sys.executable, '-u', '-c', script], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            native = NativeSession(child)
            request = {'protocol': contract.PROTOCOL, 'operation': 'bind', 'padding': 'a' * 18000}
            self.assertEqual(native.call(request)['token'], 'fixture')
            child.wait(timeout=5)
            with self.assertRaises((ValueError, BrokenPipeError)):
                native.call(request)
        finally:
            if child.poll() is None: child.kill()
            child.wait(timeout=5)
            child.stdin.close(); child.stdout.close()

    def test_url_and_operation_scope_cannot_expand(self):
        for bad in ({'operation': 'navigate', 'url': 'https://other.example/'},
                    {'operation': 'scroll', 'direction': 'down', 'pages': 999},
                    {'operation': 'type', 'text': 'send'}, {'operation': 'click'}):
            spec = copy.deepcopy(self.spec); spec['actions'] = [bad]
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.approve(spec=spec)
        ident = self.approve()
        sessions.control(self.db, ident, 'pause', actor='user', note='Pause.')
        with self.assertRaises(ValueError):
            sessions.resume(self.db, ident, current_url='https://other.example/', actor='user', note='Outside grant.')

    def test_deadline_does_not_reset_after_recovery(self):
        ident = self.approve()
        sessions.control(self.db, ident, 'pause', actor='user', note='Pause.')
        self.db.execute('UPDATE relay_computer_assignments SET deadline=1 WHERE id=?', (ident,))
        with self.assertRaises(ValueError):
            sessions.resume(self.db, ident, current_url=self.spec['url'], actor='user', note='Expired.')
        sessions.resume(self.db, ident, current_url=self.spec['url'], actor='user', note='Stop expired assignment.', abandon=True)
        self.assertEqual(sessions.get(self.db, ident)['state'], 'cancelled')

    def test_job_projection_and_deletion_own_receipts_and_block_uncertainty(self):
        from tests.test_job_delete import JobDeleteTests, PID
        from task_relay import job_record, job_delete
        fixture = JobDeleteTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.pipeline()
        db = fixture.state.db
        ident = sessions.approve(db, job=PID, request_key='native', exact_request='Inspect local fixture.',
            spec=self.spec, helper=SessionHelper.identity, output_root=self.root/'owned', actor='user')
        self.assertIn('Native computer assignment must be stopped and reconciled first.', job_delete.preview(PID, fixture.paths)['blockers'])
        def fail(req, count): raise TimeoutError('lost native reply')
        with self.assertRaises(TimeoutError): sessions.run(db, ident, SessionHelper(db, fail))
        sessions.control(db, ident, 'cancel', actor='user', note='Cancel future work.')
        self.assertIn('Native computer action has an unresolved outcome.', job_delete.preview(PID, fixture.paths)['blockers'])
        with transaction(db, write=False):
            ledger = job_record.collect(db, {'id': PID, 'artifacts': [], 'plan': {}}, set(), set())
        self.assertIn('relay_computer_actions', json.dumps(ledger))
        sessions.resume(db, ident, current_url=self.spec['url'], actor='user', note='Inspected; retain unknown outcome and stop.', abandon=True)
        review = job_delete.preview(PID, fixture.paths)
        self.assertFalse(review['blockers'])
        job_delete.delete(PID, review['digest'], fixture.paths)
        for table in sessions.TABLES:
            self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)


if __name__ == '__main__': unittest.main()
