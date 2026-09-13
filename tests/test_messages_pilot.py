import datetime as dt
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from bridge import BridgeError
from messages_pilot import Pilot, Store, Messages


class Transport:
    def __init__(self):
        self.sent = []
        self.fail = False
        self.verified = True

    def verify_chat(self, chat_id, guid):
        return self.verified

    def send(self, chat, text):
        self.sent.append((chat, text))
        if self.fail:
            raise TimeoutError()


class Desktop:
    def __init__(self):
        self.starts = []
        self.fail = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def ready_owner(self, task):
        return 'owner'

    def start(self, task, text, owner):
        self.starts.append((task, text))
        if self.fail:
            raise TimeoutError()


class Tests(unittest.TestCase):
    def test_unconfigured_pilot_requires_explicit_task_without_saving_a_default(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'state.sqlite')
            try:
                with self.assertRaisesRegex(BridgeError, '--task'):
                    Pilot(store, Transport(), None)
                self.assertIsNone(store.get('task_id'))
            finally:
                store.db.close()

    def test_restart_uses_saved_task_and_rejects_implicit_rebinding(self):
        self.store.db.close()
        self.store = Store(self.root/'state.sqlite')
        pilot = Pilot(self.store, self.transport, None, lambda: self.desktop, lambda: [self.task])
        self.assertEqual(pilot.task_id, 'task')
        with self.assertRaisesRegex(BridgeError, 'another task'):
            Pilot(self.store, self.transport, 'different-task')
        self.assertEqual(self.store.get('task_id'), 'task')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'rollout.jsonl'
        self.path.write_text('')
        self.store = Store(self.root / 'state.sqlite')
        self.transport, self.desktop = Transport(), Desktop()
        self.task = {'id': 'task', 'title': 'Pilot task', 'rollout_path': str(self.path)}
        self.pilot = self.new_pilot()
        self.append('task_complete', 'old', when=time.time() - 60)

    def new_pilot(self):
        return Pilot(self.store, self.transport, 'task', lambda: self.desktop, lambda: [self.task])

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def append(self, kind, turn='turn', text='Done', when=None):
        event = {'type': 'event_msg', 'timestamp': self.date(when),
                 'payload': {'type': kind, 'turn_id': turn, 'last_agent_message': text}}
        with self.path.open('a') as stream:
            stream.write(json.dumps(event) + '\n')

    def date(self, value=None):
        return dt.datetime.fromtimestamp(time.time() if value is None else value, dt.timezone.utc).isoformat()

    def msg(self, text, guid='input', **kwargs):
        return dict({'guid': guid, 'chat_id': 42, 'chat_guid': 'iMessage;-;self@example.test',
                     'is_group': False, 'is_from_me': True, 'created_at': self.date(), 'text': text}, **kwargs)

    def pair(self):
        self.pilot.receive(self.msg('/pair ' + self.pilot.token, 'pair'))
        self.assertIsNotNone(self.store.get('chat'))

    def drain(self):
        for _ in range(50):
            self.pilot.deliver()

    def test_pair_requires_fresh_owner_direct_imessage(self):
        text = '/pair ' + self.pilot.token
        for extra in ({'is_from_me': False}, {'is_group': True}, {'chat_guid': 'SMS;-;123'},
                      {'created_at': self.date(time.time() - 100)}, {'guid': ''}, {'chat_id': 0}):
            self.pilot.receive(self.msg(text, **extra))
            self.assertIsNone(self.store.get('chat'))
        self.pilot.receive(self.msg('Привет!'))  # Unrelated non-ASCII text must not break pairing.
        self.pilot.receive(self.msg('/pair wrong'))
        self.assertIsNone(self.store.get('chat'))
        self.pair()
        self.drain()
        self.assertIn('Paired to: Pilot task', self.transport.sent[0][1])

    def test_expired_pairing(self):
        self.pilot.expires = time.time() - 1
        self.pilot.receive(self.msg('/pair ' + self.pilot.token))
        self.assertIsNone(self.store.get('chat'))

    def test_modern_macos_any_guid_pairs_and_echo_does_not_execute(self):
        # Regression from the actual 0.15.3/Tahoe diagnostic: both copies share
        # the any;-; chat GUID; only the outbound copy is an owner command.
        chat = {'chat_guid': 'any;-;self@example.test'}
        self.pilot.receive(self.msg('/pair ' + self.pilot.token, 'incoming-pair', is_from_me=False, **chat))
        self.assertIsNone(self.store.get('chat'))
        self.pilot.receive(self.msg('/pair ' + self.pilot.token, 'outgoing-pair', **chat))
        self.assertEqual(self.store.get('chat')['guid'], chat['chat_guid'])
        self.pilot.receive(self.msg('/ask hello', 'incoming-ask', is_from_me=False, **chat))
        self.pilot.receive(self.msg('/ask hello', 'outgoing-ask', **chat))
        self.assertEqual(self.desktop.starts, [('task', 'hello')])

    def test_any_guid_requires_verified_imessage_service(self):
        self.transport.verified = False
        self.pilot.receive(self.msg('/pair ' + self.pilot.token, chat_guid='any;-;self@example.test'))
        self.assertIsNone(self.store.get('chat'))

    def test_verification_requires_exact_id_guid_service_and_direct_chat(self):
        transport = Messages('imsg')
        base = {'id': 42, 'guid': 'any;-;self@example.test', 'service': 'iMessage', 'is_group': False}
        for changes, expected in [({}, True), ({'service': 'SMS'}, False), ({'is_group': True}, False),
                                  ({'is_group': None}, False), ({'id': 43}, False), ({'guid': 'any;-;other'}, False)]:
            with self.subTest(changes=changes), patch('messages_pilot.subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = json.dumps(dict(base, **changes)) + '\n'
                self.assertEqual(transport.verify_chat(42, base['guid']), expected)

    def test_scope_and_echo_prevention(self):
        self.pair()
        for extra in ({'chat_id': 43}, {'chat_guid': 'iMessage;-;other'}, {'is_from_me': False},
                      {'is_group': True}, {'is_reaction': True}):
            self.pilot.receive(self.msg('/ask start', **extra))
        self.pilot.receive(self.msg('🤖 Codex\n\n/ask start', 'echo'))
        self.pilot.receive(self.msg('ordinary text', 'plain'))
        self.assertEqual(self.desktop.starts, [])

    def test_submission_dedup_and_pending_guard(self):
        self.pair()
        message = self.msg('/ask hello')
        self.pilot.receive(message)
        self.pilot.receive(message)
        self.pilot.receive(self.msg('/ask second', 'second'))
        self.assertEqual(self.desktop.starts, [('task', 'hello')])
        self.drain()
        self.assertTrue(any('busy' in text for _, text in self.transport.sent))

    def test_busy_task_rejected(self):
        self.pair()
        self.append('task_started')
        self.pilot.receive(self.msg('/ask hello'))
        self.assertEqual(self.desktop.starts, [])

    def test_uncertain_submission_persists_across_restart(self):
        self.pair()
        self.desktop.fail = True
        message = self.msg('/ask hello')
        self.pilot.receive(message)
        self.assertEqual(self.store.db.execute("SELECT status FROM messages_commands WHERE guid='input'").fetchone()[0], 'uncertain')
        self.pilot = self.new_pilot()
        self.pilot.receive(message)
        self.pilot.receive(self.msg('/ask again', 'again'))
        self.assertEqual(len(self.desktop.starts), 1)

    def test_old_history_not_forwarded_new_completion_delivered(self):
        self.pair()
        self.pilot.scan()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 1)
        self.pilot.receive(self.msg('/ask hello'))
        self.append('task_complete', text='Phone test works')
        self.pilot.scan()
        self.assertIsNone(self.store.get('pending'))
        self.drain()
        self.assertTrue(any('Phone test works' in text for _, text in self.transport.sent))
        self.pilot.scan()
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM messages_delivery WHERE id='turn:task_complete:1'").fetchone()[0], 1)

    def test_partial_completion_line_waits(self):
        self.pair()
        event = json.dumps({'type': 'event_msg', 'timestamp': self.date(),
                            'payload': {'type': 'task_complete', 'turn_id': 'partial', 'last_agent_message': 'ok'}})
        with self.path.open('a') as stream:
            stream.write(event)
        self.pilot.scan()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 1)
        with self.path.open('a') as stream:
            stream.write('\n')
        self.pilot.scan()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 2)

    def test_rewrite_does_not_clear_new_pending_or_repeat_result(self):
        self.pair()
        self.append('task_complete', 'first')
        self.pilot.scan()
        self.pilot.receive(self.msg('/ask next'))
        content = self.path.read_text()
        self.path.write_text('\n' + content)
        self.pilot.scan()
        self.assertIsNotNone(self.store.get('pending'))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM messages_delivery WHERE id='first:task_complete:1'").fetchone()[0], 1)

    def test_uncertain_send_never_retried_and_later_parts_blocked(self):
        self.pair()
        with self.store.db:
            self.pilot.notify('long', 'x' * 6000)
        self.transport.fail = True
        with self.assertRaises(BridgeError):
            self.pilot.deliver()
        self.transport.fail = False
        self.pilot = self.new_pilot()
        self.drain()
        self.assertEqual(len(self.transport.sent), 1)

    def test_all_split_parts_cannot_be_commands(self):
        self.pair()
        with self.store.db:
            self.pilot.notify('long', '/ask ' + 'test\n' * 1800)
        self.drain()
        self.assertGreater(len(self.transport.sent), 3)
        for index, (_, text) in enumerate(self.transport.sent):
            self.assertTrue(text.startswith('🤖 Codex'))
            self.pilot.receive(self.msg(text, f'echo{index}'))
        self.assertEqual(self.desktop.starts, [])

    def test_restart_does_not_accept_offline_command(self):
        self.pair()
        self.pilot.receive(self.msg('/ask old', created_at=self.date(time.time() - 60)))
        self.assertEqual(self.desktop.starts, [])

    def test_crash_during_sends_converts_states_to_uncertain(self):
        self.pair()
        with self.store.db:
            self.store.db.execute("INSERT INTO messages_commands VALUES ('crashed','submitting')")
            self.store.db.execute("UPDATE messages_delivery SET status='sending'")
        self.store.db.close()
        self.store = Store(self.root / 'state.sqlite')
        self.assertEqual(self.store.db.execute("SELECT status FROM messages_commands WHERE guid='crashed'").fetchone()[0], 'uncertain')
        self.assertEqual(self.store.db.execute('SELECT status FROM messages_delivery').fetchone()[0], 'uncertain')


if __name__ == '__main__':
    unittest.main()
