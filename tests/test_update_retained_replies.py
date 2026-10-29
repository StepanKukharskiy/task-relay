"""Updater admission uses real routing/transport holds; all sends are fixtures."""
from unittest.mock import Mock, patch
import unittest

from task_relay import app_bundle, app_updates, channel_policy, relay_channels
from task_relay.app_updates_macos import MacUpdater
from task_relay.messages_orchestrator import OrchestratorRouter
from tests import test_channel_policy as fixtures
from tests.test_app_updates import ExitStackMock


class Tests(unittest.TestCase):
    setUp=fixtures.ChannelTests.setUp
    queue=fixtures.ChannelTests.queue

    def adapter(self):
        return MacUpdater(installed=self.paths.install/'Task Relay.app',paths=self.paths)

    def retained(self):
        self.queue('held')
        with self.state.db:
            self.state.db.execute("INSERT INTO outbox_parts(event_id,part,text) VALUES ('held',0,'Exact held text')")
            channel_policy.begin_telegram_delivery_window(self.state.db,10)
        self.queue('uncertain')
        with self.state.db:
            self.state.db.execute("INSERT INTO outbox_parts(event_id,part,text) VALUES ('uncertain',0,'Exact uncertain text')")
            self.state.db.execute("INSERT INTO relay_delivery_effects VALUES ('text:uncertain:0','uncertain','frozen','uncertain',1,NULL,'Unknown acknowledgement',12)")
        self.queue('messages','messages')
        self.router=OrchestratorRouter(state=self.state)
        with self.state.db:
            self.pilot.notify('shared-orchestrator:messages','Exact Messages text')
            self.state.db.execute("UPDATE messages_delivery SET status='uncertain'")
            self.state.db.execute("INSERT INTO messages_delivery(id,text,status) VALUES ('shared-orchestrator:messages:2','Retained remaining part','pending')")
            self.state.db.execute("INSERT INTO messages_orchestrator_exports VALUES ('messages','shared-orchestrator:messages','Exact Messages text')")

    def original(self):
        return {t:[tuple(r) for r in self.state.db.execute('SELECT * FROM '+t+' ORDER BY rowid')]
                for t in ('outbox','outbox_parts','relay_delivery_effects','messages_delivery','relay_delivery_holds')}

    def test_retained_replies_pass_install_and_repeated_flush_without_mutation_or_replay(self):
        self.retained();before=self.original();adapter=self.adapter()
        adapter.idle();self.assertEqual(before,self.original())
        for method in ('validate_prepared','preflight','stop_owners','compatible','start_owners','reopen'):
            setattr(adapter,method,Mock())
        adapter.data_locks=ExitStackMock;adapter.services=lambda:[]
        record=dict(id='fixture',folder=str(self.paths.data),candidate_app=str(self.paths.install/'candidate'),services=[])
        with patch.object(app_bundle,'replace_contents') as replace:
            adapter.install(record,lambda:None)
        replace.assert_called_once();self.assertEqual(record['phase'],'complete')
        # Real sender selection still holds the original replies after an update.
        for _ in range(2):
            self.bridge.flush();self.router.tick(self.pilot);self.pilot.deliver()
        self.assertEqual(self.telegram.sent,[]);self.assertEqual(self.transport.sent,[])
        self.assertEqual(before,self.original())

    def test_active_send_still_blocks_even_when_its_reply_is_held(self):
        self.retained()
        with self.state.db:
            self.state.db.execute("UPDATE relay_delivery_effects SET status='submitting'")
            channel_policy.begin_telegram_delivery_window(self.state.db,20)
        with self.assertRaisesRegex(app_updates.UpdateError,'work'):self.adapter().idle()

    def test_unknown_pending_and_orphan_parts_still_block(self):
        self.retained();self.queue('fresh')
        with self.assertRaisesRegex(app_updates.UpdateError,'pending replies'):self.adapter().idle()
        with self.state.db:
            self.state.db.execute("UPDATE outbox SET sent=1 WHERE id='fresh'")
            self.state.db.execute("INSERT INTO outbox_parts(event_id,part,text) VALUES ('orphan',0,'No receipt')")
        with self.assertRaisesRegex(app_updates.UpdateError,'pending replies'):self.adapter().idle()

    def test_wrong_channel_hold_and_foreign_export_do_not_authorize_install(self):
        self.queue('msg','messages')
        with self.state.db:channel_policy.begin_telegram_delivery_window(self.state.db,10)
        self.assertFalse(relay_channels.reply_retained(self.state,'msg'))
        router=OrchestratorRouter(state=self.state)
        with self.state.db:
            self.state.db.execute("INSERT INTO messages_orchestrator_exports VALUES ('msg','exact-key','Exact text')")
            self.pilot.notify('exact-key:foreign','Other reply')
            self.state.db.execute("UPDATE messages_delivery SET status='uncertain'")
        self.assertFalse(relay_channels.reply_retained(self.state,'msg'))
        with self.assertRaisesRegex(app_updates.UpdateError,'pending replies'):self.adapter().idle()

    def test_unheld_messages_part_still_blocks_without_an_outbox_row(self):
        with self.state.db:self.pilot.notify('direct-message','Pending direct reply')
        with self.assertRaisesRegex(app_updates.UpdateError,'pending replies'):self.adapter().idle()

    def test_new_reply_during_shutdown_blocks_replacement(self):
        self.retained();adapter=self.adapter()
        adapter.validate_prepared=Mock()
        adapter.preflight=lambda record:adapter.idle()
        adapter.stop_owners=lambda *args:self.queue('arrived-during-stop')
        adapter.recover=Mock();adapter.data_locks=ExitStackMock
        record=dict(id='fixture',folder=str(self.paths.data),services=[])
        with patch.object(app_bundle,'replace_contents') as replace:
            with self.assertRaisesRegex(app_updates.UpdateError,'pending replies'):
                adapter.install(record,lambda:None)
        replace.assert_not_called();adapter.recover.assert_called_once()

    def test_interrupted_install_leaves_retained_replies_and_receipts_unchanged(self):
        self.retained();before=self.original();adapter=self.adapter()
        for method in ('validate_prepared','preflight','stop_owners','compatible','start_owners','reopen'):
            setattr(adapter,method,Mock())
        adapter.data_locks=ExitStackMock;adapter.services=lambda:[]
        record=dict(id='fixture',folder=str(self.paths.data),candidate_app=str(self.paths.install/'candidate'),services=[])
        with patch.object(app_bundle,'replace_contents',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):adapter.install(record,lambda:None)
        self.assertTrue(record['replacement_intent']);adapter.start_owners.assert_not_called()
        self.assertEqual(before,self.original());adapter.idle()


if __name__=='__main__':unittest.main()
