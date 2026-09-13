"""Channel changes use local databases and transports that never contact providers."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from task_relay import channel_policy as policy, releases, relay_channels
from task_relay.bridge import State, Bridge, Telegram, receive_updates
from task_relay.messages_pilot import Store, Pilot, Messages
from task_relay.relay_paths import Paths
from tests.test_bridge import TelegramFake, DesktopFake
from tests.test_messages_pilot import Transport


class ChannelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.paths = Paths(root / 'install', root / 'data', root / 'projects', root / 'generated')
        self.state = State(self.paths.state)
        self.addCleanup(self.state.db.close)
        self.telegram = TelegramFake()
        self.bridge = Bridge(self.state, self.telegram, {}, DesktopFake)
        self.store = Store(state=self.state)
        self.transport = Transport()
        self.pilot = Pilot(self.store, self.transport, 'task')
        with self.state.db:
            self.state.put('chat_id', 123)
            self.state.put('user_id', 123)
            self.store.put('chat', {'id': 42, 'guid': 'iMessage;-;fixture@example.test'})

    def change(self, **values):
        return policy.update(dict(revision=policy.read(self.state.db)['revision'], **values), self.paths, clock=lambda: 1000)

    def queue(self, ident, channel='telegram', text='Result'):
        with self.state.db:
            self.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)', (ident, text))
            self.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)', (ident, channel))

    def test_paused_replies_survive_restart_and_keep_their_destination(self):
        self.queue('tg')
        self.queue('msg', 'messages')
        self.change(paused=True)
        self.bridge.flush()
        self.assertEqual(self.telegram.sent, [])
        self.assertEqual(policy.load(self.paths.state)['paused'], True)
        self.change(paused=False)
        self.bridge.flush()
        self.bridge.flush()
        self.assertEqual(self.telegram.sent, [(123, 'Result')])
        self.assertEqual(self.state.db.execute("SELECT sent FROM outbox WHERE id='msg'").fetchone()[0], 0)

    def test_stale_and_invalid_edits_do_not_overwrite_saved_policy(self):
        self.change(channel='messages', enabled=False)
        for changes in ({'revision': 0, 'paused': True}, {'revision': 1, 'channel': 'slack', 'enabled': True},
                        {'revision': 1, 'paused': 'false'}, {'revision': 1, 'unknown': True}):
            with self.assertRaises(ValueError):
                policy.update(changes, self.paths)
        self.assertEqual(policy.load(self.paths.state)['revision'], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_channel_changes').fetchone()[0], 1)

    def test_corrupt_policy_fails_closed(self):
        self.change(paused=False)
        broken = policy.read(self.state.db)
        broken['enabled'] = None
        with self.state.db:
            self.state.db.execute('UPDATE relay_channel_settings SET value=?', (json.dumps(broken),))
        with self.assertRaises(ValueError):
            self.bridge.flush()
        self.assertEqual(self.telegram.sent, [])

    def test_resume_does_not_admit_old_messages(self):
        self.change(channel='telegram', enabled=False)
        self.change(channel='telegram', enabled=True)
        with patch('task_relay.bridge.orchestrator_chat.callback', return_value=True) as callback:
            self.bridge.process({'update_id': 1, 'callback_query': {}}, received_at=999)
            callback.assert_not_called()
            self.bridge.process({'update_id': 2, 'callback_query': {}}, received_at=1001)
            callback.assert_called_once()
        self.assertFalse(policy.accepting(self.state.db, 'telegram', float('nan')))
        self.assertFalse(policy.accepting(self.state.db, 'telegram', 999))
        self.assertTrue(policy.accepting(self.state.db, 'telegram', 1001))

    def test_disabled_poll_advances_offset_without_executing_callback(self):
        self.change(paused=True)
        self.telegram.call = Mock(return_value=[{'update_id': 10, 'callback_query': {}}])
        with patch('task_relay.bridge.orchestrator_chat.callback') as callback, \
                patch('task_relay.desktop_tasks.process_commands'), patch('task_relay.desktop_plans.process_requests'):
            receive_updates(self.bridge)
        self.assertEqual(self.state.get('offset'), 11)
        callback.assert_not_called()
        self.assertEqual(self.telegram.sent, [])

    def test_messages_intake_rejects_commands_while_disabled(self):
        self.change(channel='messages', enabled=False)
        with patch.object(self.pilot, 'notify') as notify:
            self.pilot.receive(dict(guid='input', chat_id=42, chat_guid='iMessage;-;fixture@example.test',
                is_group=False, is_from_me=True, created_at=dt.datetime.now(dt.timezone.utc).isoformat(), text='/ping'))
        notify.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM messages_commands').fetchone()[0], 0)

    def test_offline_resume_drains_undated_callbacks_before_accepting_fresh_clicks(self):
        self.change(paused=True)
        self.change(paused=False)
        self.telegram.call = Mock(side_effect=[[{'update_id': n, 'callback_query': {}} for n in range(100)],
                                               [{'update_id': 100, 'callback_query': {}}],
                                               [{'update_id': 101, 'callback_query': {}}]])
        with patch('task_relay.bridge.orchestrator_chat.callback', return_value=True) as callback, \
                patch('task_relay.desktop_tasks.process_commands'), patch('task_relay.desktop_plans.process_requests'):
            receive_updates(self.bridge)
            callback.assert_not_called()
            receive_updates(self.bridge)
            callback.assert_not_called()
            receive_updates(self.bridge)
            callback.assert_called_once()
        self.assertEqual(self.state.get('offset'), 102)

    def test_disabled_media_keeps_pending_identity_and_attempts(self):
        media = self.paths.data / 'small.txt'
        media.write_text('Small attachment')
        self.queue('attachment')
        with self.state.db:
            self.state.db.execute("UPDATE outbox SET sent=1 WHERE id='attachment'")
            self.state.db.execute('INSERT INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                ('file', 'attachment', str(media), 'small.txt', 'original', 'File'))
        self.change(channel='telegram', enabled=False)
        self.bridge.flush_media()
        row = self.state.db.execute('SELECT status,attempts FROM media_outbox').fetchone()
        self.assertEqual(tuple(row), ('pending', 0))
        self.assertEqual(self.telegram.media, [])
        self.change(channel='telegram', enabled=True)
        self.bridge.flush_media()
        self.bridge.flush_media()
        self.assertEqual(self.telegram.media, [('original', b'Small attachment')])

    def test_transport_rechecks_after_pacing_and_before_messages_subprocess(self):
        pacer = Mock()
        pacer.wait.side_effect = lambda: self.change(paused=True)
        tg = Telegram('fixture', pacer)
        tg.policy_path = self.paths.state
        msg = Messages('fixture-imsg')
        msg.policy_path = self.paths.state
        with patch('task_relay.bridge.urllib.request.urlopen') as network, patch('task_relay.messages_pilot.subprocess.run') as process:
            with self.assertRaises(policy.ChannelPaused):
                tg.call('sendMessage', chat_id=123, text='Never sent')
            with self.assertRaises(policy.ChannelPaused):
                tg.call('answerCallbackQuery', callback_query_id='fixture')
            with self.assertRaises(policy.ChannelPaused):
                msg.send({'guid': 'fixture'}, 'Never sent')
        network.assert_not_called()
        process.assert_not_called()

    def test_pause_between_parts_resumes_only_remaining_text(self):
        self.queue('parts', text=('One sentence. ' * 700))
        original = self.telegram.send
        def send(*args, **kwargs):
            result = original(*args, **kwargs)
            self.change(paused=True)
            return result
        self.telegram.send = send
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.assertEqual(self.state.db.execute("SELECT sent FROM outbox WHERE id='parts'").fetchone()[0], 0)
        self.telegram.send = original
        self.change(paused=False)
        self.bridge.flush()
        delivered = list(self.telegram.sent)
        self.bridge.flush()
        self.assertGreater(len(delivered), 1)
        self.assertEqual(self.telegram.sent, delivered)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox_parts WHERE sent=0").fetchone()[0], 0)

    def test_known_messages_pause_is_pending_but_ambiguous_send_is_not_replayed(self):
        with self.state.db:
            self.pilot.notify('result', 'Exact result')
        original = self.transport.send
        self.transport.send = Mock(side_effect=policy.ChannelPaused())
        self.pilot.deliver()
        self.assertEqual(self.state.db.execute('SELECT status FROM messages_delivery').fetchone()[0], 'pending')
        self.transport.send = original
        self.change(paused=True)
        self.pilot.deliver()
        self.assertEqual(self.transport.sent, [])
        self.change(paused=False)
        self.pilot.deliver()
        self.pilot.deliver()
        self.assertEqual(len(self.transport.sent), 1)
        with self.state.db:
            self.pilot.notify('ambiguous', 'Check before retry')
            self.state.db.execute("UPDATE messages_delivery SET status='uncertain' WHERE id='ambiguous:1'")
        self.change(paused=True)
        self.change(paused=False)
        self.pilot.deliver()
        self.assertEqual(len(self.transport.sent), 1)

    def test_proactive_off_holds_exported_notices_without_blocking_user_replies(self):
        with self.state.db:
            self.pilot.notify('shared-orchestrator:proactive:release:1', 'Release')
            self.pilot.notify('answer', 'User reply')
        self.change(proactive='none')
        self.pilot.deliver()
        self.assertEqual(len(self.transport.sent), 1)
        self.assertIn('User reply', self.transport.sent[0][1])
        self.assertEqual(self.state.db.execute("SELECT status FROM messages_delivery WHERE id LIKE '%proactive%'").fetchone()[0], 'pending')
        self.change(proactive='messages')
        self.pilot.deliver()
        self.assertEqual(len(self.transport.sent), 2)

    def test_release_queue_is_once_and_does_not_follow_changed_preference(self):
        major, minor, patch_version = releases.version(releases.VERSION)
        future = f'{major}.{minor}.{patch_version + 1}'
        release = dict(version=future, url=releases.WEB + 'tag/v' + future)
        self.change(proactive='messages')
        with patch.object(releases.Store, 'check', return_value=release):
            releases.tick(self.state, self.telegram)
            self.change(proactive='telegram')
            releases.tick(self.state, self.telegram)
        row = self.state.db.execute('SELECT id FROM outbox').fetchone()
        self.assertEqual(relay_channels.event_channel(self.state, row[0]), 'messages')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
        self.change(proactive='none')
        self.assertEqual(relay_channels.pending(self.state, 'messages'), [])
        self.assertEqual(self.telegram.sent, [])

    def test_runtime_must_acknowledge_current_revision(self):
        self.assertFalse(policy.snapshot(self.paths)['runtime']['telegram'])
        for role in ('intake', 'delivery'):
            policy.heartbeat(self.state, 'telegram', role)
        self.assertTrue(policy.snapshot(self.paths)['runtime']['telegram'])
        self.change(paused=True)
        self.assertFalse(policy.snapshot(self.paths)['runtime']['telegram'])
        for role in ('intake', 'delivery'):
            policy.heartbeat(self.state, 'telegram', role)
        self.assertTrue(policy.snapshot(self.paths)['runtime']['telegram'])
