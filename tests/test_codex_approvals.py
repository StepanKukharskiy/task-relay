from pathlib import Path
import tempfile
import unittest
import time
from unittest.mock import patch

import codex_approvals as approvals
import approval_ui
from bridge import Bridge, BridgeError, Desktop, State, Telegram, TelegramError
from tests.test_bridge import TelegramFake


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.temp.name) / 'state.sqlite')
        with self.state.db:
            self.state.put('chat_id', 42)
            self.state.put('user_id', 43)
        self.request = {'id': 73, 'method': approvals.COMMAND, 'params': {
            'threadId': 'task', 'turnId': 'turn', 'itemId': 'item',
            'command': 'echo "**literal** &amp; `value`"', 'cwd': '/project',
            'reason': 'Run the check', 'proposedExecpolicyAmendment': ['echo']}}
        self.snapshot = {'id': 'task', 'hostId': 'local', 'requests': [self.request], 'turns': []}
        self.calls = []
        test = self
        class Fake:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def owner(self, tid): return 'owner'
            def approval_snapshot(self, tid, owner): return test.snapshot
            def request(self, method, params, version, target=None):
                test.calls.append((method, params, version, target))
                return {'method': method, 'result': {'ok': True}}
        self.factory = Fake

    def tearDown(self):
        self.state.db.close()
        self.temp.cleanup()

    def queue(self, delivered=True):
        approvals.sync(self.state, 'task', 'owner', self.snapshot, 'A task')
        row = self.state.db.execute('SELECT * FROM codex_approvals ORDER BY rowid DESC').fetchone()
        if delivered:
            with self.state.db:
                self.state.db.execute('UPDATE outbox SET sent=1')
        return row['id']

    def deliver(self):
        token = self.queue(delivered=False)
        telegram = TelegramFake()
        bridge = Bridge(self.state, telegram, {}, self.factory)
        bridge.flush(False)
        return token, telegram, bridge

    def button(self, token, message_id, action='allow', user=43, chat=42):
        return {'update_id': 91, 'callback_query': {'id': 'click', 'from': {'id': user},
                'data': f'approval:{action}:{token}', 'message': {
                    'message_id': message_id, 'chat': {'type': 'private', 'id': chat}}}}

    def test_allow_button_submits_exact_request_once(self):
        token, telegram, bridge = self.deliver()
        button = telegram.keyboards[-1]['inline_keyboard'][0][0]
        self.assertEqual(button['callback_data'], 'approval:allow:' + token)
        update = self.button(token, len(telegram.sent))
        bridge.process(update)
        bridge.process(update)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]['decision'], 'accept')
        self.assertTrue(any(m == 'editMessageReplyMarkup' for m, _ in telegram.calls))

    def test_deny_button_submits_decline(self):
        token, telegram, bridge = self.deliver()
        bridge.process(self.button(token, len(telegram.sent), action='deny'))
        self.assertEqual(self.calls[0][1]['decision'], 'decline')

    def test_bare_allow_has_missing_id_explanation_without_dispatch(self):
        _, telegram, bridge = self.deliver()
        with patch('backends.decide') as claude:
            bridge.process({'update_id': 92, 'message': {'from': {'id': 43},
                           'chat': {'id': 42, 'type': 'private'}, 'text': '/allow'}})
        claude.assert_not_called()
        self.assertFalse(self.calls)
        self.assertIn('without a request ID', telegram.sent[-1][1])
        self.assertNotIn('expired', telegram.sent[-1][1])

    def test_bare_reply_uses_the_exact_approval_card(self):
        token, telegram, bridge = self.deliver()
        with self.state.db:
            self.state.put('selected', 'unrelated-task')
        bridge.process({'update_id': 92, 'message': {'from': {'id': 43},
                       'chat': {'id': 42, 'type': 'private'}, 'text': '/allow',
                       'reply_to_message': {'message_id': len(telegram.sent)}}})
        self.assertEqual(self.calls[0][1]['requestId'], self.request['id'])

    def test_button_rejects_wrong_user_chat_message_and_token(self):
        token, telegram, bridge = self.deliver()
        mid = len(telegram.sent)
        for update in (self.button(token, mid, user=99), self.button(token, mid, chat=99),
                       self.button(token, 999), self.button('cx-unrelated', mid)):
            bridge.process(update)
        self.assertFalse(self.calls)

    def test_multipart_buttons_only_on_final_part_and_reply_maps_all_parts(self):
        self.request['params']['command'] = 'echo ' + 'x' * 6500
        token, telegram, bridge = self.deliver()
        self.assertGreater(len(telegram.sent), 1)
        self.assertFalse(any(telegram.keyboards[:-1]))
        self.assertTrue(telegram.keyboards[-1])
        rows = self.state.db.execute('SELECT request_id FROM approval_messages').fetchall()
        self.assertEqual([r[0] for r in rows], [token] * len(telegram.sent))

    def test_desktop_only_approval_gets_deny_button_only(self):
        self.request['params']['command'] = 'x' * 12000
        _, telegram, _ = self.deliver()
        self.assertEqual([b['text'] for b in telegram.keyboards[-1]['inline_keyboard'][0]], ['Deny'])

    def test_buttons_do_not_revive_resolved_desktop_requests(self):
        token, telegram, bridge = self.deliver()
        self.snapshot['requests'] = []
        bridge.process(self.button(token, len(telegram.sent)))
        self.assertFalse(self.calls)
        self.assertIn('already answered', telegram.sent[-1][1])

    def test_claude_button_uses_claude_request_handler(self):
        token = 'claude-request'
        with self.state.db:
            self.state.db.execute("INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES ('job','claude-task',1,'test','waiting',?)", (time.time(),))
            self.state.db.execute("INSERT INTO tool_requests VALUES (?,'job','claude-task','Bash','{}','pending',?)", (token, time.time() + 60))
            self.state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                  ('permission:' + token, 'claude-task', 'Claude approval details'))
        telegram = TelegramFake()
        bridge = Bridge(self.state, telegram, {}, self.factory)
        bridge.flush(False)
        bridge.process(self.button(token, len(telegram.sent)))
        self.assertEqual(self.state.db.execute('SELECT status FROM tool_requests WHERE id=?', (token,)).fetchone()[0], 'allowed')
        self.assertFalse(self.calls)

    def test_plain_text_transport_fallback_keeps_approval_buttons(self):
        telegram = Telegram('fake')
        markup = {'inline_keyboard': [[{'text': 'Allow', 'callback_data': 'approval:allow:cx-test'}]]}
        with patch.object(telegram, 'call', side_effect=[TelegramError('sendMessage', 400), {'message_id': 1}]) as call:
            telegram.send(42, 'details', entities=[{'type': 'bold', 'offset': 0, 'length': 7}], reply_markup=markup)
        self.assertEqual(call.call_args.kwargs['reply_markup'], markup)

    def test_allow_exact_request_once_without_saved_rule(self):
        token = self.queue()
        self.assertEqual(approvals.decide(self.state, token, True, self.factory), ('task', 'Approval sent to Codex.'))
        self.assertEqual(self.calls, [(approvals.METHODS[approvals.COMMAND],
                         {'conversationId': 'task', 'requestId': 73, 'decision': 'accept'}, 1, 'owner')])
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, self.factory)
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_poll_and_restart_do_not_repeat_card(self):
        self.queue()
        approvals.initialize(self.state.db)
        self.queue()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_command_details_are_literal_through_telegram_delivery(self):
        self.queue(delivered=False)
        telegram = TelegramFake()
        Bridge(self.state, telegram, {}).flush(False)
        text = '\n'.join(t for _, t in telegram.sent)
        self.assertIn('**literal** &amp; `value`', text)
        self.assertTrue(any(e['type'] == 'pre' for entities in telegram.entities for e in entities))

    def test_grant_waits_for_full_card_delivery(self):
        token = self.queue(delivered=False)
        with self.assertRaisesRegex(ValueError, 'all approval details'):
            approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)

    def test_answered_on_desktop_cannot_be_approved(self):
        token = self.queue()
        self.snapshot['requests'] = []
        with self.assertRaisesRegex(ValueError, 'already answered'):
            approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)

    def test_changed_scope_and_reused_request_id_rejected(self):
        token = self.queue()
        self.request['params']['command'] = 'different command'
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)
        self.assertNotEqual(self.queue(), token)

    def test_changed_owner_cannot_receive_old_grant(self):
        token = self.queue()
        parent = self.factory
        class NewOwner(parent):
            def owner(self, tid): return 'new-owner'
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, NewOwner)
        self.assertFalse(self.calls)

    def test_crash_after_claim_does_not_replay(self):
        token = self.queue()
        with self.state.db:
            self.state.db.execute("UPDATE codex_approvals SET status='submitting'")
        self.queue()
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)

    def test_interrupted_approval_explains_receipt_gap_and_removes_spent_buttons(self):
        token, telegram, bridge = self.deliver()
        mid = len(telegram.sent)
        with self.state.db:
            self.state.db.execute("UPDATE codex_approvals SET status='submitting',decision='allow'")
        bridge.process(self.button(token, mid))
        self.assertFalse(self.calls)
        self.assertIn('did not save Codex', telegram.sent[-1][1])
        self.assertNotIn('no longer pending', telegram.sent[-1][1])
        self.assertTrue(any(m == 'editMessageReplyMarkup' for m, _ in telegram.calls))

    def test_reload_during_approval_finishes_acknowledgement_and_update_offset(self):
        import signal
        import bridge as module
        from contextlib import ExitStack
        # Use run() with the real poll/approval path, but no service threads/network.
        # The fake desktop sends SIGTERM exactly when the command is accepted.
        token, telegram, _ = self.deliver()
        update = self.button(token, len(telegram.sent))
        handlers = {}
        parent = self.factory
        class RestartingDesktop(parent):
            def request(self, *args, **kwargs):
                response = super().request(*args, **kwargs)
                handlers[signal.SIGTERM](signal.SIGTERM, None)
                return response
        original_call = telegram.call
        def call(method, **kwargs):
            return [update] if method == 'getUpdates' else original_call(method, **kwargs)
        real_bridge = module.Bridge
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, 'DATA', Path(self.temp.name)))
            stack.enter_context(patch.object(module, 'read_config', return_value={'token':'test'}))
            stack.enter_context(patch.object(module, 'BackgroundWorkers'))
            stack.enter_context(patch.object(module, 'Telegram', return_value=telegram))
            stack.enter_context(patch.object(telegram, 'call', side_effect=call))
            stack.enter_context(patch.object(module, 'Bridge', side_effect=lambda s,t,c: real_bridge(s,t,c,RestartingDesktop)))
            stack.enter_context(patch.object(module.signal, 'signal', side_effect=lambda sig,fn: handlers.update({sig:fn})))
            module.run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM codex_approvals WHERE id=?',(token,)).fetchone()[0], 'submitted')
        self.assertEqual(self.state.get('offset'), update['update_id'] + 1)
        self.assertIn('Approval sent to Codex', telegram.sent[-1][1])

    def test_resolved_unsent_card_is_suppressed(self):
        self.queue(False)
        self.snapshot['requests'] = []
        approvals.sync(self.state, 'task', 'owner', self.snapshot)
        self.assertEqual(self.state.db.execute('SELECT status FROM codex_approvals').fetchone()[0], 'resolved')
        telegram = TelegramFake()
        Bridge(self.state, telegram, {}).flush(False)
        self.assertFalse(telegram.sent)

    def test_timeout_is_uncertain_and_never_retried_after_restart(self):
        token = self.queue()
        parent = self.factory
        class Lost(parent):
            def request(self, *args, **kwargs):
                super().request(*args, **kwargs)
                raise TimeoutError()
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            approvals.decide(self.state, token, True, Lost)
        approvals.initialize(self.state.db)
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, Lost)
        self.assertEqual(len(self.calls), 1)

    def test_file_diff_is_bound_to_request_in_normalized_history(self):
        self.request['method'] = approvals.FILE
        self.request['params'] = {'threadId': 'task', 'turnId': 'turn', 'itemId': 'item', 'grantRoot': '/project'}
        item = {'id': 'item', 'type': 'fileChange', 'changes': [{'path': '/project/a', 'diff': '+new'}]}
        self.snapshot['turnHistory'] = {'history': {'entitiesByKey': {
            'tail:1': {'turnId': 'turn', 'items': [item]}}}}
        token = self.queue()
        self.assertTrue(self.state.db.execute('SELECT can_allow FROM codex_approvals').fetchone()[0])
        item['changes'][0]['diff'] = '+changed'
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)

    def test_missing_file_diff_requires_desktop_review_but_can_deny(self):
        self.request['method'] = approvals.FILE
        token = self.queue()
        with self.assertRaisesRegex(ValueError, 'desktop review'):
            approvals.decide(self.state, token, True, self.factory)
        approvals.decide(self.state, token, False, self.factory)
        self.assertEqual(self.calls[0][1]['decision'], 'decline')

    def test_file_change_accept_routes_to_file_handler(self):
        self.request['method'] = approvals.FILE
        self.snapshot['turns'] = [{'turnId': 'turn', 'items': [{
            'id': 'item', 'type': 'fileChange', 'changes': [{'path': '/project/a', 'diff': '+new'}]}]}]
        token = self.queue()
        approvals.decide(self.state, token, True, self.factory)
        self.assertEqual(self.calls[0][0], approvals.METHODS[approvals.FILE])

    def test_permissions_grant_exact_subset_for_turn_only(self):
        self.request['method'] = approvals.PERMISSIONS
        self.request['params']['permissions'] = {'fileSystem': {'write': ['/project/output']}}
        token = self.queue()
        approvals.decide(self.state, token, True, self.factory)
        self.assertEqual(self.calls[0][1]['response'], {
            'permissions': self.request['params']['permissions'], 'scope': 'turn'})

    def test_permissions_denial_grants_nothing(self):
        self.request['method'] = approvals.PERMISSIONS
        token = self.queue()
        approvals.decide(self.state, token, False, self.factory)
        self.assertEqual(self.calls[0][1]['response'], {'permissions': {}, 'scope': 'turn'})

    def test_large_or_unsupported_requests_cannot_grant(self):
        for method in (approvals.COMMAND, 'mcpServer/elicitation/request'):
            self.request['method'] = method
            self.request['params']['command'] = 'x' * 12000
            token = self.queue()
            with self.assertRaises(ValueError):
                approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)
        self.assertLess(self.state.db.execute('SELECT count(*) FROM outbox_parts').fetchone()[0], 4)

    def test_network_scope_and_available_decisions(self):
        self.request['params']['networkApprovalContext'] = {'host': 'example.com', 'protocol': 'https'}
        self.request['params']['availableDecisions'] = ['decline', 'acceptForSession']
        token = self.queue()
        text = self.state.db.execute('SELECT text FROM outbox').fetchone()[0]
        self.assertIn('Network access', text)
        with self.assertRaises(ValueError):
            approvals.decide(self.state, token, True, self.factory)
        approvals.decide(self.state, token, False, self.factory)

    def test_wrong_telegram_user_or_chat_cannot_answer(self):
        token = self.queue()
        bridge = Bridge(self.state, TelegramFake(), {}, self.factory)
        for sender, chat in ((99, 42), (43, 99)):
            bridge.process({'update_id': 1, 'message': {'from': {'id': sender},
                           'chat': {'id': chat, 'type': 'private'}, 'text': '/allow ' + token}})
        self.assertFalse(self.calls)
        bridge.process({'update_id': 2, 'message': {'from': {'id': 43},
                       'chat': {'id': 42, 'type': 'private'}, 'text': '/allow ' + token}})
        self.assertEqual(len(self.calls), 1)

    def test_worker_only_monitors_running_tasks_and_pending_requests(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO watched(id,title,status) VALUES ('task','Title','running')")
        approvals.Worker(self.state, self.factory).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM codex_approvals').fetchone()[0], 1)

    def test_snapshot_transport_checks_sender_version_and_unsubscribes(self):
        class FakeSocket:
            def settimeout(self, value): pass
        def message(owner='owner', version=11):
            return {'type': 'broadcast', 'method': 'thread-stream-state-changed',
                    'sourceClientId': owner, 'version': version,
                    'params': {'conversationId': 'task', 'hostId': 'local', 'change': {
                        'type': 'snapshot', 'conversationState': self.snapshot}}}
        for version in (11, 12):
            desktop = Desktop()
            desktop.sock, desktop.client_id = FakeSocket(), 'client'
            sent = []
            desktop.send = sent.append
            messages = iter([message(owner='wrong'), message(version=version)])
            desktop.receive = lambda: next(messages)
            if version == 11:
                self.assertEqual(desktop.approval_snapshot('task', 'owner'), self.snapshot)
            else:
                with self.assertRaises(BridgeError):
                    desktop.approval_snapshot('task', 'owner')
            self.assertEqual([m['params']['following'] for m in sent], [True, False])


if __name__ == '__main__':
    unittest.main()
