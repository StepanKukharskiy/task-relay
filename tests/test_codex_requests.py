import copy
import json
import re
import unittest
from unittest.mock import patch

import codex_approvals as approvals
import codex_requests as requests
from tests import test_codex_approvals as fixtures


class RequestTests(unittest.TestCase):
    setUp = fixtures.ApprovalTests.setUp
    tearDown = fixtures.ApprovalTests.tearDown
    queue = fixtures.ApprovalTests.queue
    deliver = fixtures.ApprovalTests.deliver
    button = fixtures.ApprovalTests.button

    def connector(self, prompt='Write a summary'):
        self.request.update(method=requests.MCP, params={
            'threadId': 'task', 'turnId': 'turn', 'serverName': 'codex_app',
            'mode': 'form', 'message': 'Allow tool "send_message_to_thread"?',
            'requestedSchema': {'type': 'object', 'properties': {}},
            '_meta': {'codex_approval_kind': 'mcp_tool_call',
                'tool_params': {'prompt': prompt, 'threadId': 'destination'},
                'tool_params_display': [{'name': 'prompt', 'value': prompt}],
                'persist': ['session', 'always']}})

    def question(self, multiple=False):
        qs = [{'id': 'color', 'header': 'Color', 'question': 'Which color?',
               'options': [{'label': 'Blue', 'description': 'Cool'}, {'label': 'Red', 'description': 'Warm'}]}]
        if multiple:
            qs.append({'id': 'note', 'header': 'Notes', 'question': 'Any other instructions?', 'options': None})
        self.request.update(method=requests.INPUT, params={'threadId': 'task', 'turnId': 'turn', 'questions': qs})

    def reply(self, bridge, mid, text, uid=120, user=43):
        bridge.process({'update_id': uid, 'message': {'from': {'id': user},
            'chat': {'id': 42, 'type': 'private'}, 'text': text,
            'reply_to_message': {'message_id': mid}}})

    def test_long_connector_approval_renders_once_and_submits_no_persistence(self):
        prompt = 'Literal **bold** &amp; \\n 😀\n' + 'detail ' * 900
        self.connector(prompt)
        self.assertGreater(len(json.dumps(self.request)), approvals.MAX_DETAILS)
        token, telegram, bridge = self.deliver()
        rendered = ''.join(x[1] for x in telegram.sent)
        parts = self.state.db.execute('SELECT text FROM outbox_parts ORDER BY part').fetchall()
        self.assertEqual(''.join(re.sub(r'^Part \d+/\d+\n\n', '', x[0]) for x in parts).count(prompt), 1)
        self.assertNotIn('too large', rendered)
        self.assertGreater(len(parts), 1)
        self.assertFalse(any(telegram.keyboards[:-1]))
        bridge.process(self.button(token, len(telegram.sent)))
        self.assertEqual(self.calls[0][0], approvals.METHODS[requests.MCP])
        self.assertEqual(self.calls[0][1]['response'], {'action': 'accept', 'content': {}})

    def test_connector_denial_and_missing_turn_id(self):
        self.connector(); self.request['params'].pop('turnId')
        token = self.queue()
        approvals.decide(self.state, token, False, self.factory)
        self.assertEqual(self.calls[0][1]['response'], {'action': 'decline', 'content': None})

    def test_connector_changed_arguments_and_incomplete_delivery_cannot_approve(self):
        self.connector(); token = self.queue(False)
        with self.assertRaisesRegex(ValueError, 'delivered'):
            approvals.decide(self.state, token, True, self.factory)
        self.state.db.execute('UPDATE outbox SET sent=1'); self.state.db.commit()
        self.request['params']['_meta']['tool_params']['prompt'] = 'different action'
        with self.assertRaisesRegex(ValueError, 'changed'):
            approvals.decide(self.state, token, True, self.factory)
        self.assertFalse(self.calls)

    def test_typed_url_and_execution_bound_forms_are_not_generic_allow(self):
        self.connector(); original = copy.deepcopy(self.request)
        variants = [dict(mode='url'), dict(requestedSchema={'type': 'object', 'properties': {'password': {'type': 'string'}}}),
                    dict(_meta={**self.request['params']['_meta'], 'connector_id': 'connector_20205bf7d4e99a89d7154bb849718324'})]
        for variant in variants:
            self.request = copy.deepcopy(original); self.request['params'].update(variant)
            self.assertFalse(approvals.can_allow(self.request, {'request': self.request}))

    def test_nonredundant_display_details_are_preserved(self):
        self.connector(); self.request['params']['_meta']['tool_params_display'][0]['value'] = 'DIFFERENT DISPLAY'
        text, _ = requests.render('Task', self.request)
        self.assertIn('DIFFERENT DISPLAY', text)
        self.assertIn('Write a summary', text)

    def test_question_option_button_exact_payload_and_duplicate_protection(self):
        self.question(); token, telegram, bridge = self.deliver()
        update = self.button(token, len(telegram.sent))
        update['callback_query']['data'] = f'question:{token}:2'
        bridge.process(update); bridge.process(update)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], requests.INPUT_METHOD)
        self.assertEqual(self.calls[0][1]['response'], {'answers': {'color': {'answers': ['Red']}}})

    def test_direct_question_reply_ignores_selection_and_command_parser(self):
        self.question(); token, telegram, bridge = self.deliver(); mid = len(telegram.sent)
        self.state.put('selected', 'wrong-task'); self.state.db.commit()
        self.reply(bridge, mid, '/gemini This is my literal answer')
        self.reply(bridge, mid, '/gemini This is my literal answer')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]['conversationId'], 'task')
        self.assertEqual(self.calls[0][1]['response']['answers']['color']['answers'], ['/gemini This is my literal answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)

    def test_multi_question_requires_all_answers_and_supports_freeform(self):
        self.question(True); _, telegram, bridge = self.deliver(); mid = len(telegram.sent)
        self.assertTrue(telegram.keyboards[-1]['force_reply'])
        self.reply(bridge, mid, 'Blue')
        self.assertFalse(self.calls)
        self.reply(bridge, mid, '1: 1\n2: Keep **these** &amp; notes\nand this line', uid=121)
        self.assertEqual(self.calls[0][1]['response'], {'answers': {
            'color': {'answers': ['Blue']}, 'note': {'answers': ['Keep **these** &amp; notes\nand this line']}}})

    def test_question_security_invalid_options_stale_and_secret(self):
        self.question(); token, telegram, bridge = self.deliver(); mid = len(telegram.sent)
        self.reply(bridge, mid, '1', user=99)
        self.reply(bridge, mid, '99')
        update = self.button(token, 999)
        update['callback_query']['data'] = f'question:{token}:1'
        bridge.process(update)
        self.assertFalse(self.calls)
        self.snapshot['requests'] = []
        self.reply(bridge, mid, '1', uid=121)
        self.assertFalse(self.calls)
        self.request['params']['questions'][0]['isSecret'] = True
        self.assertFalse(requests.supported(self.request))

    def test_question_uncertain_send_is_not_replayed(self):
        self.question(); token = self.queue()
        with patch.object(self.factory, 'request', side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError, 'uncertain'):
                approvals.decide(self.state, token, False, self.factory, answer='1')
        with self.assertRaisesRegex(ValueError, 'did not save Codex'):
            approvals.decide(self.state, token, False, self.factory, answer='1')

    def test_over_limit_connector_and_question_remain_unapprovable(self):
        self.connector('x' * (requests.MAX_TEXT + 1))
        self.assertFalse(requests.supported(self.request))
        self.question(); self.request['params']['questions'][0]['question'] = 'x' * (requests.MAX_TEXT + 1)
        self.assertFalse(requests.supported(self.request))

    def test_pending_legacy_card_replaced_once_and_old_token_resolved(self):
        self.connector(); token = self.queue()
        with self.state.db:
            self.state.db.execute("UPDATE codex_approvals SET fingerprint='legacy' WHERE id=?", (token,))
        replacement = self.queue()
        self.assertNotEqual(token, replacement)
        self.assertEqual(self.state.db.execute('SELECT status FROM codex_approvals WHERE id=?', (token,)).fetchone()[0], 'resolved')
        self.queue()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM codex_approvals').fetchone()[0], 2)
