from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from task_relay import backends, gemini, relay_channels, usage_tracker
from task_relay.bridge import State
from task_relay.messages_orchestrator import OrchestratorRouter
from task_relay.messages_pilot import Store, Pilot
from task_relay.messages_providers import ProviderRouter
from task_relay import messages_storage as storage
from tests.test_messages_pilot import Transport


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as db, db:
        yield db


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / 'state.sqlite'
        self.folder = self.root / 'messages-pilot'
        self.folder.mkdir()
        self.main = State(self.target)
        self.main.db.commit()
        self.addCleanup(self.main.db.close)
        self.config = patch.object(gemini, 'read_config', return_value={'api_key': 'test-only', 'models': gemini.DEFAULT_MODELS})
        self.config.start()
        self.addCleanup(self.config.stop)
        with database(self.folder / 'state.sqlite') as db:
            db.executescript('''CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE commands(guid TEXT PRIMARY KEY,status TEXT NOT NULL);
                CREATE TABLE delivery(id TEXT PRIMARY KEY,text TEXT NOT NULL,status TEXT NOT NULL);''')
            db.execute('INSERT INTO settings VALUES (?,?)', ('chat', json.dumps({'id': 42, 'guid': 'any;-;self@example.test'})))
            db.execute('INSERT INTO settings VALUES (?,?)', ('pending', json.dumps({'guid': 'request', 'since': 1})))
            db.execute('INSERT INTO commands VALUES (?,?)', ('request', 'uncertain'))
            db.executemany('INSERT INTO delivery VALUES (?,?,?)', [('old:1', 'Original part', 'uncertain'), ('old:2', 'Later part', 'pending')])
        legacy = State(self.folder / 'providers.sqlite')
        with legacy.db:
            legacy.db.execute('CREATE TABLE message_requests(guid TEXT PRIMARY KEY,update_id INTEGER UNIQUE NOT NULL,job_id TEXT NOT NULL)')
        self.tid, _, _ = backends.create_task(legacy, 'gemini ' + str(self.root), 73, prompt='  Keep this exact request.\nAnd this line.  ')
        self.job = legacy.db.execute('SELECT id FROM backend_jobs').fetchone()[0]
        with legacy.db:
            legacy.db.execute("UPDATE backend_jobs SET status='completed'")
            legacy.db.execute("UPDATE watched SET status='idle'")
            legacy.db.execute('INSERT INTO message_requests VALUES (?,?,?)', ('gemini-request', 73, self.job))
            legacy.put('messages:gemini_task', self.tid)
            legacy.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)', ('backend:' + self.job + ':result', self.tid, 'Saved reply'))
            legacy.db.execute('INSERT INTO api_steps VALUES (?,?,?)', (self.job, 0, json.dumps({'totalTokenCount': 17})))
            legacy.db.execute('INSERT INTO gemini_history VALUES (?,?,?,?,?,?)',
                              (self.job, self.tid, 'text', str(self.root / 'input.json'), str(self.root / 'response.json'), time.time()))
        legacy.db.close()
        with self.main.db:
            self.main.put('selected', 'telegram-task')
            self.main.put('orchestrator_mode', True)

    def migrate(self):
        return storage.consolidate(self.target, self.folder)

    def test_preserves_records_delivery_order_paths_and_channel_and_retires_sources(self):
        evidence = self.migrate()
        self.assertEqual(self.main.get('selected'), 'telegram-task')
        self.assertTrue(self.main.get('orchestrator_mode'))
        self.assertEqual(self.main.get('messages:gemini_task'), self.tid)
        row = self.main.db.execute('SELECT prompt FROM backend_jobs').fetchone()
        self.assertEqual(row[0], '  Keep this exact request.\nAnd this line.  ')
        self.assertEqual([tuple(r) for r in self.main.db.execute('SELECT id,status FROM messages_delivery ORDER BY rowid')],
                         [('old:1', 'uncertain'), ('old:2', 'pending')])
        self.assertEqual(json.loads(self.main.db.execute("SELECT value FROM messages_settings WHERE key='pending'").fetchone()[0])['guid'], 'request')
        self.assertEqual(self.main.db.execute('SELECT input_path FROM gemini_history').fetchone()[0], str(self.root / 'input.json'))
        self.assertEqual(len(relay_channels.pending(self.main, 'messages')), 1)
        self.assertEqual(relay_channels.pending(self.main, 'telegram'), [])
        for entry in evidence['sources']:
            self.assertFalse(Path(entry['source']).exists())
            with database(entry['backup']) as backup:
                self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(storage.digest(backup), entry['digest'])
        self.assertEqual(self.migrate(), evidence)

    def test_collision_rolls_back_every_record_and_receipt(self):
        with self.main.db:
            self.main.db.execute('INSERT INTO incoming VALUES (?,?,?)', (73, 'handled', 'telegram-task'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.migrate()
        self.assertEqual(self.main.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 0)
        self.assertEqual(self.main.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 0)
        self.assertIsNone(storage.receipt(self.main.db))
        self.assertTrue((self.folder / 'state.sqlite').exists())
        self.assertTrue((self.folder / 'providers.sqlite').exists())

    def test_unknown_populated_table_aborts_instead_of_dropping_it(self):
        with database(self.folder / 'providers.sqlite') as db:
            db.executescript("CREATE TABLE future_decisions(id TEXT PRIMARY KEY); INSERT INTO future_decisions VALUES ('keep-me');")
        with self.assertRaisesRegex(ValueError, 'future_decisions'):
            self.migrate()
        self.assertIsNone(storage.receipt(self.main.db))

    def test_interrupted_retirement_resumes_without_reimporting(self):
        with patch.object(storage, 'archive_sources', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.migrate()
        self.assertIsNotNone(storage.receipt(self.main.db))
        with self.assertRaisesRegex(ValueError, 'offline consolidation'):
            storage.require_consolidated(self.target, self.folder)
        self.migrate()
        self.assertEqual(self.main.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        storage.require_consolidated(self.target, self.folder)

    def test_changed_source_after_commit_is_preserved_for_review(self):
        with patch.object(storage, 'archive_sources', side_effect=OSError):
            with self.assertRaises(OSError):
                self.migrate()
        with database(self.folder / 'state.sqlite') as db:
            db.execute("UPDATE delivery SET text='Changed by an old service'")
        with self.assertRaisesRegex(ValueError, 'changed after consolidation'):
            self.migrate()
        self.assertTrue((self.folder / 'state.sqlite').exists())

    def test_inflight_work_and_held_service_lock_prevent_migration(self):
        with patch.object(storage.HOST, 'lock', side_effect=BlockingIOError):
            with self.assertRaisesRegex(ValueError, 'Stop both'):
                self.migrate()
        with database(self.folder / 'providers.sqlite') as db:
            db.execute("UPDATE backend_jobs SET status='running'")
        with self.assertRaisesRegex(ValueError, 'in-flight'):
            self.migrate()
        self.assertIsNone(storage.receipt(self.main.db))

    def test_usage_refresh_does_not_double_count_migrated_calls(self):
        usage_tracker.collect_relay(self.main.db, self.folder / 'providers.sqlite')
        before = usage_tracker.report(self.main.db)
        self.assertEqual(before['groups'][0]['total_tokens'], 17)
        evidence = self.migrate()
        usage_tracker.refresh(self.main.db, data=self.root, local=False)
        after = usage_tracker.report(self.main.db)
        self.assertEqual(after['groups'][0]['total_tokens'], 17)
        self.assertEqual(after['records'], before['records'])
        self.assertEqual(evidence['usage_ids_rebound'], 1)

    def test_generated_emoji_collision_is_recorded_without_changing_existing_choice(self):
        with database(self.folder / 'providers.sqlite') as db:
            emoji, key = db.execute('SELECT emoji,emoji_key FROM task_emojis').fetchone()
        with self.main.db:
            self.main.db.execute('INSERT INTO task_emojis VALUES (?,?,?,0)', ('telegram-task', emoji, key))
        evidence = self.migrate()
        self.assertEqual(self.main.db.execute("SELECT emoji FROM task_emojis WHERE thread_id='telegram-task'").fetchone()[0], emoji)
        self.assertEqual(evidence['emoji_changes'][0]['previous'], emoji)
        self.assertNotEqual(evidence['emoji_changes'][0]['current'], emoji)

    def test_uncertain_provider_job_is_not_replayed_by_shared_worker(self):
        with database(self.folder / 'providers.sqlite') as db:
            db.execute("UPDATE backend_jobs SET status='uncertain'")
            db.execute("UPDATE watched SET status='uncertain'")
        self.migrate()
        start = Mock(side_effect=AssertionError('must not replay'))
        worker = backends.BackendWorker(self.main, popen=start, backend='gemini')
        worker.tick()
        start.assert_not_called()
        self.assertEqual(self.main.db.execute('SELECT status FROM backend_jobs').fetchone()[0], 'uncertain')

    def test_already_migrated_readonly_runtime_is_archived_without_writing_it(self):
        runtime = self.root / 'orchestrator/runtime.sqlite'
        runtime.parent.mkdir()
        with database(runtime) as db:
            db.executescript("CREATE TABLE events(id TEXT PRIMARY KEY); INSERT INTO events VALUES ('original');")
        runtime.chmod(0o400)
        with self.main.db:
            self.main.db.execute('INSERT INTO storage_migrations VALUES (?,?,?)', ('production-runtime-v1', time.time(), '{}'))
        evidence = self.migrate()
        self.assertFalse(runtime.exists())
        archive = Path(evidence['sources'][-1]['backup']).with_suffix('.retired.sqlite')
        self.assertEqual(archive.stat().st_mode & 0o777, 0o400)
        with database(archive) as db:
            self.assertEqual(db.execute('SELECT id FROM events').fetchone()[0], 'original')


class SharedRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = State(self.root / 'state.sqlite')
        self.addCleanup(self.state.db.close)
        self.store = Store(state=self.state)
        self.exporter = OrchestratorRouter(state=self.state, require_ready=False)
        self.router = ProviderRouter(state=self.state, require_ready=False)
        self.pilot = Pilot(self.store, Transport(), 'codex-task', providers=self.router, orchestrator=self.exporter)
        self.config = patch.object(gemini, 'read_config', return_value={'api_key': 'test-only', 'models': gemini.DEFAULT_MODELS})
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_submission_is_atomic_scoped_and_never_starts_a_second_worker(self):
        with self.state.db:
            self.state.put('selected', 'telegram-task')
            self.state.put('orchestrator_mode', True)
        with patch.object(backends, 'BackendWorker', side_effect=AssertionError('second worker')):
            self.router = ProviderRouter(state=self.state, require_ready=False)
            jid = self.router.submit('input', 'Exact prompt', self.root)
            self.assertEqual(self.router.submit('input', 'Exact prompt', self.root), jid)
        self.assertEqual(self.state.get('selected'), 'telegram-task')
        self.assertTrue(self.state.get('orchestrator_mode'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0], 1)
        second = sqlite3.connect(self.root / 'state.sqlite')
        self.addCleanup(second.close)
        self.assertEqual(second.execute('SELECT count(*) FROM messages_provider_requests').fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, 'different saved'):
            self.router.submit('input', 'Changed prompt', self.root)

    def test_failed_enqueue_leaves_no_job_channel_or_selected_task(self):
        original = backends.enqueue
        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise ValueError('transaction interrupted')
        with patch.object(backends, 'enqueue', side_effect=fail_after_insert):
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                self.router.submit('input', 'Exact prompt', self.root)
        for table in ('backend_jobs', 'backend_tasks', 'relay_request_channels', 'messages_provider_requests', 'watched'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_export_failure_rolls_back_choices_and_parts_and_other_channel_is_untouched(self):
        with self.state.db:
            self.state.db.executemany('INSERT INTO outbox(id,text) VALUES (?,?)', [('ours', 'Our answer'), ('theirs', 'Their answer')])
            self.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)', ('ours', 'messages'))
        original = self.pilot.notify
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise ValueError('export interrupted')
        with patch.object(self.pilot, 'notify', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                self.exporter.tick(self.pilot)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM messages_orchestrator_exports').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 0)
        self.exporter.tick(self.pilot)
        self.assertEqual([r['id'] for r in relay_channels.pending(self.state, 'telegram')], ['theirs'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 1)

    def test_existing_delivery_parts_are_frozen_when_another_watcher_exports(self):
        with self.state.db:
            self.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)', ('same', 'A much longer replacement ' * 500))
            self.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)', ('same', 'messages'))
            self.state.db.execute('INSERT INTO messages_delivery VALUES (?,?,?)',
                                  ('shared-orchestrator:same:1', 'Already delivered original', 'sent'))
        self.exporter.tick(self.pilot)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM messages_delivery').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT text FROM messages_delivery').fetchone()[0], 'Already delivered original')


if __name__ == '__main__':
    unittest.main()
