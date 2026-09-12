import unittest

import approval_text
import codex_approvals as approvals
from bridge import split_text
from telegram_text import split_rendered, units


class ApprovalTextTests(unittest.TestCase):
    def test_file_card_has_literal_diff_and_no_protocol_json(self):
        diff = '@@ -1 +1 @@\n-old = "&amp;"\n+new = r"\\b(**literal**)\\b"\n'
        request = {'id': 406, 'method': approvals.FILE, 'params': {
            'threadId': 'thread-id', 'turnId': 'turn-id', 'itemId': 'exec-id',
            'startedAtMs': 1788955924536, 'grantRoot': None, 'reason': None}}
        detail = {'request': request, 'fileChange': {'changes': [{
            'kind': {'type': 'update', 'move_path': None},
            'path': '/private/tmp/export_content_conversation.py', 'diff': diff}]}}
        text, entities = approval_text.render('Create CODEX pipeline', request, detail, True)
        self.assertIn('Edit /private/tmp/export_content_conversation.py\n+1 / −1 lines', text)
        self.assertIn(diff, text)
        for raw in ('fileChange', 'thread-id', 'turn-id', 'exec-id', 'startedAtMs', 'null', '/allow cx-'):
            self.assertNotIn(raw, text)
        pre = next(e for e in entities if e['type'] == 'pre')
        raw = text.encode('utf-16-le')
        self.assertEqual(raw[pre['offset']*2:(pre['offset']+pre['length'])*2].decode('utf-16-le'), diff)

    def test_multi_file_actions_moves_and_granted_root_remain_visible(self):
        request = {'method': approvals.FILE, 'params': {'grantRoot': '/outside/project', 'reason': 'Write the export'}}
        detail = {'fileChange': {'changes': [
            {'path': '/a.py', 'kind': {'type': 'update', 'move_path': '/b.py'}, 'diff': '-old\n+new'},
            {'path': '/new.py', 'kind': {'type': 'add'}, 'diff': '+new'},
            {'path': '/gone.py', 'kind': {'type': 'delete'}, 'diff': '-gone'}]}}
        text, _ = approval_text.render('Task', request, detail, True)
        for value in ('Edit /a.py', 'Move path: /b.py', 'Create /new.py', 'Delete /gone.py',
                      'Requested folder access: /outside/project', 'Write the export'):
            self.assertIn(value, text)

    def test_command_preserves_scope_and_hides_unselected_persistent_rule(self):
        request = {'method': approvals.COMMAND, 'params': {'command': 'echo "🚀 &amp; `x`"',
            'cwd': '/project', 'reason': 'Run checks', 'proposedExecpolicyAmendment': ['echo'],
            'additionalPermissions': {'fileSystem': {'write': ['/outside']}},
            'newScopeField': {'enabled': True}}}
        text, _ = approval_text.render('Task', request, {}, True)
        self.assertIn(request['params']['command'], text)
        self.assertIn('/outside', text)
        self.assertIn('New scope field / Enabled: yes', text)
        self.assertIn('No command rule will be saved', text)
        self.assertNotIn('proposedExecpolicyAmendment', text)

    def test_network_and_permissions_are_readable_without_losing_scope(self):
        request = {'method': approvals.COMMAND, 'params': {'networkApprovalContext': {
            'host': 'example.com', 'protocol': 'https', 'port': 8443}}}
        text, _ = approval_text.render('Task', request, {}, True)
        for value in ('Network access', 'example.com', 'https', '8443', 'multiple queued connections'):
            self.assertIn(value, text)
        request = {'method': approvals.PERMISSIONS, 'params': {'permissions': {
            'fileSystem': {'read': ['/one'], 'write': ['/two']}, 'network': {'enabled': False}}}}
        text, _ = approval_text.render('Task', request, {}, True)
        for value in ('File system / Read: /one', 'File system / Write: /two', 'Network / Enabled: no', 'this turn only'):
            self.assertIn(value, text)

    def test_long_unicode_diff_keeps_valid_entities_across_parts(self):
        diff = ('+print("🚀 &amp; **exact**")\n' * 250)
        request = {'method': approvals.FILE, 'params': {}}
        detail = {'fileChange': {'changes': [{'path': '/one.py', 'kind': {'type': 'update'}, 'diff': diff}]}}
        text, entities = approval_text.render('Task 🚀', request, detail, True)
        parts = split_rendered(text, entities, split_text)
        self.assertGreater(len(parts), 1)
        self.assertEqual(''.join(p.split('\n\n', 1)[1] for p, _ in parts), text)
        for part, spans in parts:
            self.assertLessEqual(units(part), 4096)
            self.assertTrue(all(0 <= e['offset'] < e['offset'] + e['length'] <= units(part) for e in spans))

    def test_oversized_reason_does_not_create_many_messages(self):
        request = {'method': approvals.COMMAND, 'params': {'reason': 'x' * 100000}}
        text, _ = approval_text.render('Task', request, {}, False, too_large=True)
        self.assertLess(len(text), 500)
        self.assertIn('desktop review', text)


if __name__ == '__main__':
    unittest.main()
