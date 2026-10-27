"""Activation → late history discovery → text/media delivery, no network."""
import datetime
import unittest
from unittest.mock import patch

from task_relay import channel_policy as policy, relay_channels
from task_relay.bridge import State, Bridge, Watcher
from tests.test_channel_policy import ChannelTests
from tests.test_bridge import TelegramFake, DesktopFake


class DeliveryWindowTests(unittest.TestCase):
    setUp = ChannelTests.setUp
    queue = ChannelTests.queue
    change = ChannelTests.change

    def activate(self, now=1000):
        with self.state.db:
            policy.begin_telegram_delivery_window(self.state.db, now)

    def media(self, ident):
        path = self.paths.data / (ident + '.txt')
        path.write_text('Exact saved bytes')
        with self.state.db:
            self.state.db.execute('INSERT INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                                 (ident, ident, str(path), path.name, 'original', 'Saved attachment'))

    def source(self, ident, when):
        event = dict(type='event_msg', payload=dict(type='task_complete', turn_id=ident, last_agent_message=ident))
        if when is not None:
            event['timestamp'] = datetime.datetime.fromtimestamp(when, datetime.timezone.utc).isoformat()
        with self.state.db:
            Watcher(self.state).event('thread', 'Thread', event)
        return 'thread:' + ident + ':task_complete'

    def test_start_holds_queued_text_and_already_announced_attachments(self):
        self.queue('old'); self.queue('announced'); self.queue('other', 'messages')
        self.media('old'); self.media('announced')
        with self.state.db:
            self.state.db.execute("UPDATE outbox SET sent=1 WHERE id='announced'")
        before = [tuple(r) for r in self.state.db.execute('SELECT * FROM outbox')]
        self.activate()
        self.bridge.flush()
        self.assertEqual(self.telegram.sent, [])
        self.assertEqual(self.telegram.media, [])
        self.assertEqual(before, [tuple(r) for r in self.state.db.execute('SELECT * FROM outbox')])
        self.assertEqual([r['id'] for r in relay_channels.pending(self.state, 'messages')], ['other'])
        self.queue('new'); self.media('new')
        self.bridge.flush(); self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 2)
        self.assertEqual(self.telegram.media, [('original', b'Exact saved bytes')])
        self.assertEqual(self.state.db.execute("SELECT status FROM media_outbox WHERE id='old'").fetchone()[0], 'pending')

    def test_late_discovered_old_and_undated_results_stay_local(self):
        self.activate()
        old = self.source('old', 999)
        undated = self.source('unknown', None)
        fresh = self.source('fresh', 1001)
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.assertIn('fresh', self.telegram.sent[0][1])
        self.assertFalse(policy.event_allowed(self.state.db, 'telegram', old))
        self.assertFalse(policy.event_allowed(self.state.db, 'telegram', undated))
        self.assertTrue(policy.event_allowed(self.state.db, 'telegram', fresh))

    def test_reopening_worker_does_not_reset_window_but_service_activation_does(self):
        self.activate(); self.queue('fresh')
        reopened = State(self.paths.state)
        self.addCleanup(reopened.db.close)
        Bridge(reopened, self.telegram, {}, DesktopFake).flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.queue('between_services')
        self.activate(2000)
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.source('after_restart', 2001)
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 2)

    def test_disable_enable_and_pause_resume_have_new_cutoffs(self):
        self.change(channel='telegram', enabled=False)
        self.queue('offline')
        self.change(channel='telegram', enabled=True)
        self.source('old', 999)
        self.source('new', 1001)
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.change(paused=True); self.queue('paused')
        self.change(paused=False); self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.queue('resumed'); self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 2)

    def test_uncertain_receipts_and_partial_sends_are_never_rewritten(self):
        self.queue('unknown')
        self.telegram.send = lambda *a, **kw: (_ for _ in ()).throw(TimeoutError('ambiguous'))
        with self.assertRaises(TimeoutError): self.bridge.flush()
        old = [tuple(r) for r in self.state.db.execute('SELECT * FROM relay_delivery_effects')]
        self.activate()
        self.telegram = TelegramFake(); self.bridge.telegram = self.telegram
        self.bridge.flush()
        self.assertEqual(self.telegram.sent, [])
        self.assertEqual(old, [tuple(r) for r in self.state.db.execute('SELECT * FROM relay_delivery_effects')])

    def test_activation_rolls_back_with_failed_settings_update(self):
        self.queue('before')
        self.change(channel='telegram', enabled=False)
        revision = policy.read(self.state.db)['revision']
        with self.assertRaises(ValueError):
            policy.update(dict(revision=revision, channel='telegram', enabled=True, proactive='invalid'), self.paths)
        self.assertEqual(policy.read(self.state.db)['revision'], revision)
        self.assertTrue(policy.event_allowed(self.state.db, 'telegram', 'before'))
        self.assertIsNone(self.state.get('telegram:delivery_since'))

    def test_same_enabled_setting_does_not_hide_new_results(self):
        self.activate(); self.queue('new')
        self.change(channel='telegram', enabled=True)
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)

    def test_reenable_between_parts_rechecks_window(self):
        self.queue('parts', text='Sentence. ' * 1800)
        original = self.telegram.send
        def send(*a, **kw):
            response = original(*a, **kw)
            self.change(channel='telegram', enabled=False)
            self.change(channel='telegram', enabled=True)
            return response
        self.telegram.send = send
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent), 1)
        self.assertEqual(self.state.db.execute("SELECT sent FROM outbox WHERE id='parts'").fetchone()[0], 0)

    def test_service_entry_commits_window_before_workers_can_start(self):
        from task_relay import bridge
        self.queue('previous')
        class ReachedWorkers(Exception): pass
        def workers(*args):
            with __import__('sqlite3').connect(self.paths.state) as db:
                self.assertIsNotNone(db.execute("SELECT value FROM kv WHERE key='telegram:delivery_since'").fetchone())
                self.assertFalse(policy.event_allowed(db, 'telegram', 'previous'))
            raise ReachedWorkers()
        with patch.object(bridge, 'DATA', self.paths.data), patch.object(bridge, 'PATHS', self.paths), \
                patch.object(bridge, 'service_config', return_value={'token': None}), \
                patch.object(bridge, 'service_transport', return_value=self.telegram), \
                patch.object(bridge, 'State', return_value=self.state), \
                patch.object(bridge.HOST, 'lock', side_effect=lambda stream: self.addCleanup(stream.close)), \
                patch('task_relay.update_gate.startup'), \
                patch('task_relay.messages_storage.require_consolidated'), \
                patch('task_relay.desktop_tasks.recover_commands'), \
                patch('task_relay.job_delete.recover_pending'), \
                patch('task_relay.task_delete.recover_pending'), \
                patch.object(bridge, 'BackgroundWorkers', side_effect=workers):
            with self.assertRaises(ReachedWorkers): bridge.run()
