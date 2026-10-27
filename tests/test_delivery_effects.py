"""Durable transport intent and restart boundaries, using text only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from task_relay.bridge import State,TelegramError
from task_relay import delivery_effects as effects

class Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'state.sqlite';self.state=State(self.path)
        self.addCleanup(lambda:self.state.db.close())

    def test_confirmed_receipt_survives_restart_before_parent_ack(self):
        calls=[]
        def transport():
            self.assertFalse(self.state.db.in_transaction)
            other=State(self.path)
            try:self.assertEqual(other.db.execute('SELECT status FROM relay_delivery_effects').fetchone()[0],'submitting')
            finally:other.db.close()
            calls.append(1);return dict(message_id=42)
        response=effects.send(self.state,'part','event',{'text':'exact'},transport)
        self.state.db.close();self.state=State(self.path)
        self.assertEqual(effects.send(self.state,'part','event',{'text':'exact'},transport),response)
        self.assertEqual(calls,[1])
        with self.assertRaises(effects.UncertainDelivery):effects.send(self.state,'part','event',{'text':'changed'},transport)

    def test_timeout_and_process_interruption_never_replay(self):
        for index,error in enumerate((OSError('lost response'),KeyboardInterrupt())):
            transport=Mock(side_effect=error)
            with self.assertRaises(type(error)):effects.send(self.state,str(index),'event',{},transport)
            with self.assertRaises(effects.UncertainDelivery):effects.send(self.state,str(index),'event',{},transport)
            self.assertEqual(transport.call_count,1)

    def test_explicit_refusal_can_retry_and_missing_receipt_cannot(self):
        transport=Mock(side_effect=[TelegramError('sendMessage',429),{'message_id':7}])
        with self.assertRaises(TelegramError):effects.send(self.state,'refused','event',{},transport)
        self.assertEqual(effects.send(self.state,'refused','event',{},transport),{'message_id':7})
        with self.assertRaises(effects.UncertainDelivery):effects.send(self.state,'no-receipt','event',{},lambda:{})
        with self.assertRaises(effects.UncertainDelivery):effects.send(self.state,'no-receipt','event',{},transport)
        self.assertEqual(transport.call_count,2)

    def test_old_pending_transport_is_unknown_but_desktop_files_are_inert(self):
        with self.state.db:
            self.state.db.execute('DROP TABLE relay_delivery_effects')
            for channel in ('telegram','desktop'):
                self.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)',(channel,'exact'))
                self.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)',(channel,channel))
                self.state.db.execute('INSERT INTO outbox_parts(event_id,part,text) VALUES (?,0,?)',(channel,'exact'))
            effects.initialize(self.state.db)
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT event_id,status FROM relay_delivery_effects')],[('telegram','uncertain')])
        with self.assertRaises(effects.UncertainDelivery):effects.send(self.state,'text:telegram:0','telegram',{},lambda:self.fail('must not dispatch'))
