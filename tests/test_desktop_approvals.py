"""Desktop approval cards share the request-bound, no-replay decision path."""
from pathlib import Path
import tempfile
import time
import unittest

from task_relay.bridge import State
from task_relay import codex_approvals
from task_relay.desktop_approvals import decide, pending
from task_relay.relay_paths import Paths


class DesktopApprovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root / 'app', root / 'data', root / 'workspaces', root / 'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)

    def test_claude_permission_requires_current_card_and_is_one_shot(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES ('job','task',1,'test','waiting',?)", (time.time(),))
            self.state.db.execute("INSERT INTO tool_requests VALUES ('tool','job','task','Bash','{\"command\":\"echo ok\"}','pending',?)", (time.time() + 900,))
        card = pending(self.state.db, 'task')[0]
        self.assertIn('echo ok', card['review'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            decide('task', 'tool', '0' * 64, True, paths=self.paths)
        self.assertEqual(decide('task', 'tool', card['fingerprint'], True, paths=self.paths)['status'], 'submitted')
        with self.assertRaisesRegex(ValueError, 'no longer pending'):
            decide('task', 'tool', card['fingerprint'], True, paths=self.paths)
        self.assertEqual(self.state.db.execute("SELECT status FROM tool_requests WHERE id='tool'").fetchone()[0], 'allowed')

    def test_codex_desktop_review_skips_telegram_delivery_but_checks_live_scope(self):
        request = {'id': 11, 'method': codex_approvals.COMMAND, 'params': {
            'threadId': 'task', 'turnId': 'turn', 'itemId': 'item', 'command': 'echo ok', 'cwd': '/project'}}
        snapshot = {'id': 'task', 'requests': [request], 'turns': []}
        calls = []
        class DesktopFake:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def owner(self, _): return 'owner'
            def approval_snapshot(self, *_): return snapshot
            def request(self, method, params, version, target=None):
                calls.append((method, params, version, target))
                return {'method': method, 'result': {'ok': True}}
        codex_approvals.sync(self.state, 'task', 'owner', snapshot, 'Fixture task')
        card = pending(self.state.db, 'task')[0]
        self.assertIn('echo ok', card['review'])
        self.assertTrue(card['can_allow'])
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox').fetchone()[0], 0)
        decide('task', card['token'], card['fingerprint'], True, paths=self.paths, desktop_factory=DesktopFake)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['decision'], 'accept')
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            decide('task', card['token'], card['fingerprint'], True, paths=self.paths, desktop_factory=DesktopFake)
        self.assertEqual(len(calls), 1)

    def test_codex_changed_request_cannot_be_allowed_from_old_desktop_card(self):
        request = {'id': 11, 'method': codex_approvals.COMMAND, 'params': {
            'threadId': 'task', 'turnId': 'turn', 'itemId': 'item', 'command': 'echo ok'}}
        snapshot = {'requests': [request], 'turns': []}
        calls = []
        class DesktopFake:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def owner(self, _): return 'owner'
            def approval_snapshot(self, *_): return snapshot
            def request(self, *args, **kwargs): calls.append((args, kwargs))
        codex_approvals.sync(self.state, 'task', 'owner', snapshot, 'Fixture task')
        card = pending(self.state.db, 'task')[0]
        request['params']['command'] = 'different command'
        with self.assertRaisesRegex(ValueError, 'changed or was already answered'):
            decide('task', card['token'], card['fingerprint'], True, paths=self.paths, desktop_factory=DesktopFake)
        self.assertFalse(calls)

    def test_codex_card_is_available_without_telegram_pairing(self):
        request = {'id': 12, 'method': codex_approvals.COMMAND, 'params': {
            'threadId': 'task', 'turnId': 'turn', 'itemId': 'item', 'command': 'echo local'}}
        snapshot = {'requests': [request], 'turns': []}
        with self.state.db:
            self.state.db.execute("INSERT INTO watched(id,path,offset,title,status,updated_at) VALUES ('task','',0,'Local task','running',?)", (time.time(),))
        class DesktopFake:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def owner(self, _): return 'owner'
            def approval_snapshot(self, *_): return snapshot
        codex_approvals.Worker(self.state, DesktopFake).tick()
        self.assertIn('echo local', pending(self.state.db, 'task')[0]['review'])

    def test_large_file_review_must_match_saved_document(self):
        request = {'id': 15, 'method': codex_approvals.FILE, 'params': {
            'threadId': 'task', 'turnId': 'turn', 'itemId': 'item'}}
        snapshot = {'requests': [request], 'turns': [{'turnId': 'turn', 'items': [
            {'id': 'item', 'type': 'fileChange', 'changes': [
                {'path': '/project/a.txt', 'kind': {'type': 'update'}, 'diff': '+ ' + 'x' * 7000}]}]}]}
        codex_approvals.sync(self.state, 'task', 'owner', snapshot, 'Fixture task')
        card = pending(self.state.db, 'task')[0]
        self.assertTrue(card['can_allow'])
        self.assertIn('x' * 100, card['review'])
        report = self.state.db.execute('SELECT path FROM codex_approval_reports').fetchone()[0]
        Path(report).chmod(0o600)
        Path(report).write_text('changed review')
        self.assertFalse(pending(self.state.db, 'task')[0]['can_allow'])


if __name__ == '__main__':
    unittest.main()
