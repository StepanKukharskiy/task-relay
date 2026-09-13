"""Companion read isolation, exact local decisions, and connection identity."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from task_relay import companion
from task_relay.relay_paths import Paths


class CompanionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.paths = Paths(root / 'app', root / 'data', root / 'workspaces', root / 'generated')

    def test_unconfigured_connections_do_not_initialize_state(self):
        self.assertIsNone(companion.conversation(self.paths)['url'])
        self.assertFalse(companion.messages_state(self.paths)['paired'])
        self.assertFalse(self.paths.data.exists())

    def test_conversation_rejects_untrusted_urls_and_never_exposes_credentials(self):
        self.paths.data.mkdir()
        config = self.paths.data / 'config.json'
        for name in ('https://other.example', 'bot?start=secret', '../bot', 'x'):
            config.write_text(json.dumps({'username': name, 'token': 'private-token'}))
            config.chmod(0o600)
            self.assertIsNone(companion.conversation(self.paths)['url'])
        config.write_text(json.dumps({'username': 'fixture_bot', 'token': 'private-token', 'pair_code': 'private-code'}))
        self.assertEqual(companion.conversation(self.paths), {'url': 'https://t.me/fixture_bot'})

    def test_messages_status_preserves_uncertainty_and_does_not_expose_chat_identity(self):
        self.paths.data.mkdir()
        with closing(sqlite3.connect(self.paths.state)) as db:
            db.executescript('CREATE TABLE messages_settings(key TEXT,value TEXT); CREATE TABLE messages_delivery(id TEXT,status TEXT);')
            db.execute('INSERT INTO messages_settings VALUES (?,?)', ('chat', json.dumps({'id': 42, 'guid': 'private-chat'})))
            db.execute('INSERT INTO messages_delivery VALUES (?,?)', ('uncertain-id', 'uncertain'))
            db.commit()
        result = companion.messages_state(self.paths)
        self.assertTrue(result['paired'])
        self.assertEqual(result['uncertain'], 1)
        self.assertNotIn('private-chat', json.dumps(result))
        with closing(sqlite3.connect(self.paths.state)) as db:
            self.assertEqual(db.execute('SELECT status FROM messages_delivery').fetchone()[0], 'uncertain')

    def test_status_does_not_fetch_tasks_or_scan_storage(self):
        with patch('task_relay.launcher.status', return_value={'version': 'fixture'}), \
             patch('task_relay.desktop_macos.DesktopService.status', return_value={'healthy': False}), \
             patch('task_relay.desktop_messages.MessagesService.status', return_value={'paired': False}), \
             patch('task_relay.desktop_approvals.inbox', return_value={'items': []}), \
             patch.object(companion, 'conversation', return_value={'url': None}), \
             patch('task_relay.desktop_tasks.list_tasks', side_effect=AssertionError('Task catalog read')), \
             patch('task_relay.desktop_usage.summary', side_effect=AssertionError('Storage scan')):
            self.assertEqual(companion.status()['decisions'], {'items': []})


if __name__ == '__main__':
    unittest.main()
