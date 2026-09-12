"""Migration proofs use small text records; service actions are controlled fixtures."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from task_relay import credentials, migrations, updates
from tests import test_updates


class MigrationTests(unittest.TestCase):
    def database(self, sql):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(sql)
        return db

    def derive(self, change):
        before = self.database("CREATE TABLE requests(id INTEGER PRIMARY KEY, text TEXT); INSERT INTO requests VALUES(7,'Exact original request');")
        after = self.database('')
        before.backup(after)
        after.executescript(change)
        return before, after, migrations.derive(before, after)

    def test_reversal_keeps_new_rows_and_exact_old_values(self):
        before, after, plan = self.derive('ALTER TABLE requests ADD COLUMN note TEXT; CREATE TABLE versions(id TEXT PRIMARY KEY,value TEXT); CREATE INDEX versions_value ON versions(value);')
        after.execute("INSERT INTO requests(id,text) VALUES(9,'Newer decision remains')")
        after.commit()
        migrations.transform(after, plan, 'down')
        self.assertEqual(after.execute('SELECT * FROM requests ORDER BY id').fetchall(), [(7, 'Exact original request'), (9, 'Newer decision remains')])
        self.assertEqual(migrations.schema(after), migrations.schema(before))

    def test_used_new_columns_or_tables_block_reversal(self):
        for change, insert in [('ALTER TABLE requests ADD COLUMN note TEXT', "UPDATE requests SET note='New evidence'"),
                               ('CREATE TABLE versions(id TEXT)', "INSERT INTO versions VALUES('accepted-v2')")]:
            with self.subTest(change=change):
                _, after, plan = self.derive(change)
                after.execute(insert)
                after.commit()
                original = migrations.fingerprint(after)
                with self.assertRaisesRegex(ValueError, 'discard newer data'):
                    migrations.transform(after, plan, 'down')
                self.assertEqual(migrations.fingerprint(after), original)

    def test_row_rewrites_and_seeded_tables_are_not_additive_authorization(self):
        for change in ["ALTER TABLE requests ADD COLUMN note TEXT; UPDATE requests SET text='Changed request'",
                       "CREATE TABLE versions(id TEXT); INSERT INTO versions VALUES('seed')",
                       'ALTER TABLE requests RENAME COLUMN text TO prompt',
                       'ALTER TABLE requests ADD COLUMN note TEXT DEFAULT \'hidden\'',
                       'CREATE TRIGGER edit AFTER INSERT ON requests BEGIN UPDATE requests SET text=\'changed\'; END']:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.derive(change)

    def test_hidden_row_identity_changes_are_not_accepted(self):
        before = self.database("CREATE TABLE events(text TEXT); INSERT INTO events(rowid,text) VALUES(7,'Exact delivered result');")
        after = self.database('')
        before.backup(after)
        after.executescript('CREATE TABLE versions(id TEXT); UPDATE events SET rowid=99;')
        with self.assertRaisesRegex(ValueError, 'changes existing data'):
            migrations.derive(before, after)

    def test_implicit_version_metadata_changes_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError, 'changes existing data'):
            self.derive('CREATE TABLE versions(id TEXT); PRAGMA user_version=7;')

    def test_schema_and_receipt_roll_back_together_on_failure(self):
        before, _, plan = self.derive('CREATE TABLE versions(id TEXT)')
        plan['id'] = migrations.digest(plan)
        original = migrations.fingerprint(before)
        with self.assertRaises(RuntimeError):
            with before:
                before.execute('BEGIN IMMEDIATE')
                migrations.transition(before, plan, 'up', 'attempt')
                raise RuntimeError('fixture power loss before commit')
        self.assertEqual(migrations.fingerprint(before), original)
        self.assertIsNone(migrations.applied(before, 'attempt'))

    def test_recovery_keeps_receipts_and_is_idempotent(self):
        before, _, plan = self.derive('CREATE TABLE versions(id TEXT)')
        plan['id'] = migrations.digest(plan)
        record = {'nonce': 'attempt', 'migration': {'plan': plan['id'], 'direction': 'up'}}
        with before:
            before.execute('BEGIN IMMEDIATE')
            migrations.transition(before, plan, 'up', 'attempt')
        for _ in range(2):
            with before:
                before.execute('BEGIN IMMEDIATE')
                migrations.undo(before, record)
        self.assertEqual(before.execute('SELECT event,direction FROM relay_update_migrations ORDER BY event').fetchall(), [('attempt', 'up'), ('attempt-recovery', 'down')])
        self.assertEqual(before.execute('SELECT text FROM requests').fetchone()[0], 'Exact original request')


class MigrationIntegrationTests(unittest.TestCase):
    setUp = test_updates.UpdateTests.setUp

    def target_schema(self, conditional=False):
        module = Path(self.target['install']) / 'task_relay/bridge.py'
        # Existing State initialization plus one idempotent additive release change.
        code = module.read_text()
        code += '\n_OriginalState = State\nclass State(_OriginalState):\n def __init__(self, p):\n  super().__init__(p)\n  self.db.execute("CREATE TABLE IF NOT EXISTS fixture_versions(id TEXT PRIMARY KEY, text TEXT)")\n'
        if conditional:
            code += '  if self.db.execute("SELECT 1 FROM kv WHERE key=\'late\'").fetchone(): self.db.execute("UPDATE kv SET value=\'changed\' WHERE key=\'late\'")\n'
        code += '  self.db.commit()\n'
        module.write_text(code)
        self.target['code_hash'] = updates.code_hash(self.target['install'])
        return updates.migration_plan(self.target, self.paths)

    def activate(self, plan, target=None):
        return updates.activate(target or self.target, self.paths, self.factory, migration=plan['id'])

    def test_legacy_recovery_controller_cannot_own_a_migration(self):
        legacy = dict(updates.current(self.paths), protocol=1, version='0.12.0')
        credentials.save(updates.activation_path(self.paths), {'phase': 'active', 'target': legacy,
            'previous': legacy, 'bindings': self.paths.environment()})
        with self.assertRaisesRegex(ValueError, 'First activate migration-aware code'):
            self.target_schema()
        self.assertEqual(self.service.starts, 0)

    def test_plan_is_nonmutating_and_explicit_apply_reverse_preserves_history(self):
        original = updates.content(self.state.db)
        plan = self.target_schema()
        self.assertEqual(updates.content(self.state.db), original)
        self.assertEqual(self.service.starts, 0)
        record = self.activate(plan)
        with self.state.db:
            self.state.put('newer', {'request': 'Exact new decision'})
        with self.assertRaisesRegex(ValueError, 'Rollback needs'):
            updates.activate(record['previous'], self.paths, self.factory)
        self.activate(plan, record['previous'])
        self.assertEqual(self.state.get('newer'), {'request': 'Exact new decision'})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_update_migrations').fetchone()[0], 2)
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())

    def test_new_migration_data_refuses_rollback_without_service_or_data_loss(self):
        plan = self.target_schema()
        record = self.activate(plan)
        with self.state.db:
            self.state.db.execute("INSERT INTO fixture_versions VALUES ('v2','New accepted output')")
        raw = self.service.raw
        with self.assertRaisesRegex(ValueError, 'discard newer data'):
            self.activate(plan, record['previous'])
        self.assertEqual(self.service.raw, raw)
        self.assertEqual(self.state.db.execute('SELECT text FROM fixture_versions').fetchone()[0], 'New accepted output')
        self.assertEqual(updates.load(updates.activation_path(self.paths))['target'], self.target)

    def test_intervening_data_rewrite_by_candidate_is_refused(self):
        plan = self.target_schema(conditional=True)
        with self.state.db:
            self.state.put('late', {'request': 'Keep this late instruction'})
        with self.assertRaisesRegex(ValueError, 'now changes data'):
            self.activate(plan)
        self.assertEqual(self.state.get('late'), {'request': 'Keep this late instruction'})
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())

    def test_changed_plan_or_schema_is_refused(self):
        plan = self.target_schema()
        file = migrations.path(self.paths, plan['id'])
        changed = dict(plan, forward=['DROP TABLE kv'])
        credentials.save(file, changed)
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            self.activate(plan)
        credentials.save(file, plan)
        with self.state.db:
            self.state.db.execute('CREATE TABLE other_task_changes(id TEXT)')
        with self.assertRaisesRegex(ValueError, 'schema changed'):
            self.activate(plan)
        self.assertTrue(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='other_task_changes'").fetchone())

    def test_failed_start_reverses_committed_migration_and_keeps_receipts(self):
        plan = self.target_schema()
        self.service.fail_starts = 1
        with self.assertRaisesRegex(ValueError, 'fixture start failure'):
            self.activate(plan)
        self.assertEqual(self.service.raw, b'old definition')
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())
        self.assertEqual(self.state.db.execute('SELECT direction FROM relay_update_migrations ORDER BY rowid').fetchall()[0][0], 'up')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_update_migrations').fetchone()[0], 2)

    def test_interrupted_recovery_resumes_once_from_original_transaction(self):
        plan = self.target_schema()
        self.service.fail_starts = 2
        with self.assertRaisesRegex(RuntimeError, 'recovery are incomplete'):
            self.activate(plan)
        with patch.object(updates, 'Service', self.factory):
            updates.recover(self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_update_migrations').fetchone()[0], 2)
        self.assertEqual(updates.load(updates.activation_path(self.paths))['phase'], 'active')

    def test_process_loss_after_schema_commit_recovers_from_database_receipt(self):
        plan = self.target_schema()
        with patch.object(self.service, 'write', side_effect=KeyboardInterrupt), patch.object(updates, 'restore', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.activate(plan)
        interrupted = updates.load(updates.activation_path(self.paths))
        self.assertEqual(interrupted['phase'], 'migrating')
        self.assertTrue(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())
        with patch.object(updates, 'Service', self.factory):
            updates.recover(self.paths)
        self.assertEqual(self.service.raw, b'old definition')
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_update_migrations').fetchone()[0], 2)

    def test_process_loss_during_restore_retains_original_migration_identity(self):
        plan = self.target_schema()
        self.service.fail_starts = 1
        save = credentials.save
        def interrupted(path, value):
            save(path, value)
            if path == updates.activation_path(self.paths) and value.get('recovery_source'):
                raise SystemExit
        with patch.object(credentials, 'save', side_effect=interrupted):
            with self.assertRaises(SystemExit):
                self.activate(plan)
        self.assertIn('recovery_source', updates.load(updates.activation_path(self.paths)))
        with patch.object(updates, 'Service', self.factory):
            updates.recover(self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_update_migrations').fetchone()[0], 2)
        self.assertEqual(updates.load(updates.activation_path(self.paths))['phase'], 'active')

    def test_failure_before_schema_commit_leaves_no_applied_receipt(self):
        plan = self.target_schema()
        transition = migrations.transition
        def interrupted(*args):
            transition(*args)
            raise RuntimeError('fixture failure before database commit')
        with patch.object(migrations, 'transition', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'before database commit'):
                self.activate(plan)
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_update_migrations'").fetchone())
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())

    def test_lost_activation_commit_ack_does_not_reverse_committed_migration(self):
        plan = self.target_schema()
        save = credentials.save
        def lost_ack(path, value):
            save(path, value)
            if path == updates.activation_path(self.paths) and value.get('phase') == 'active':
                raise KeyboardInterrupt
        with patch.object(credentials, 'save', side_effect=lost_ack):
            with self.assertRaisesRegex(RuntimeError, 'commit may have completed'):
                self.activate(plan)
        self.assertTrue(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_versions'").fetchone())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_update_migrations').fetchone()[0], 1)
        self.assertEqual(self.service.starts, 1)


if __name__ == '__main__':
    unittest.main()
