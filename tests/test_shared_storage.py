from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import storage
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory,plan


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.target=self.root/'state.sqlite';self.legacy=self.root/'runtime.sqlite'
        self.file=self.root/'artifact.md';self.file.write_text('Original immutable output')
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('CREATE TABLE artifacts(id TEXT PRIMARY KEY, value TEXT)')
            db.execute("INSERT INTO artifacts VALUES ('same-id','provider artifact')")
        self.source=sqlite3.connect(self.legacy)
        self.source.executescript((Path(__file__).parent/'fixtures/legacy-runtime.sql').read_text())
        self.source.execute("INSERT INTO runs VALUES ('run','{}','blocked')")
        self.source.execute("INSERT INTO assignments VALUES ('assignment','run','task',1,'{}')")
        self.source.execute("INSERT INTO tasks VALUES ('run','task','assignment','blocked',1,'attempt')")
        self.source.execute("INSERT INTO attempts VALUES ('attempt','run','task','assignment','blocked',NULL,'{}','{}',NULL,'time_limit')")
        self.source.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',('same-id','run','task','attempt','output.md',str(self.file),hashlib.sha256(self.file.read_bytes()).hexdigest(),self.file.stat().st_size,'Draft output',str(self.file)))
        self.source.execute("INSERT INTO events VALUES (71,1,'run','task','attempt','telegram_revision_applied','{}')")
        self.source.execute("INSERT INTO decisions VALUES ('decision','run','task','same-id','retain','Unapproved draft',1)")
        self.source.commit()

    def tearDown(self):
        self.source.close();self.temp.cleanup()

    def test_preserves_all_ids_row_order_bytes_and_provider_artifacts(self):
        before={t:storage.fingerprint(self.source,t) for t in storage.TABLES}
        result=storage.migrate(self.target,self.legacy)
        with closing(sqlite3.connect(self.target)) as db, db:
            self.assertEqual(before,{t:storage.fingerprint(db,'production_'+t) for t in storage.TABLES})
            self.assertEqual(db.execute('SELECT * FROM artifacts').fetchall(),[('same-id','provider artifact')])
        self.assertEqual(result['files_checked'],1)
        self.assertEqual(before,{t:storage.fingerprint(self.source,t) for t in storage.TABLES})
        self.assertTrue(storage.migrate(self.target,self.legacy)['already_migrated'])

    def test_missing_file_or_interrupt_rolls_back_entire_import(self):
        for error in (ValueError('changed file'),KeyboardInterrupt()):
            with patch('orchestrator.runtime.file_hash',side_effect=error):
                with self.assertRaises(type(error)):storage.migrate(self.target,self.legacy)
            with closing(sqlite3.connect(self.target)) as db, db:
                self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='production_runs'").fetchone())
                self.assertEqual(db.execute('SELECT value FROM artifacts').fetchone()[0],'provider artifact')
        storage.migrate(self.target,self.legacy)

    def test_preexisting_production_rows_and_unrecognized_legacy_schema_block(self):
        with closing(sqlite3.connect(self.target)) as db, db:
            storage.initialize(db);db.execute("INSERT INTO production_runs VALUES ('other','{}','active')")
        with self.assertRaisesRegex(ValueError,'already populated'):storage.migrate(self.target,self.legacy)
        with closing(sqlite3.connect(self.target)) as db, db:db.execute('DELETE FROM production_runs')
        self.source.execute('CREATE TABLE unknown_notes(value TEXT)');self.source.commit()
        with self.assertRaisesRegex(ValueError,'Unexpected legacy schema'):storage.migrate(self.target,self.legacy)

    def test_runtime_refuses_unmigrated_legacy_instead_of_creating_empty_history(self):
        with self.assertRaisesRegex(RuntimeError,'offline migration'):Runtime(self.root)
        storage.migrate(self.target,self.legacy)
        rt=Runtime(self.root)
        try:self.assertEqual(rt.task('run','task')['latest'],'attempt')
        finally:rt.close()


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        from task_relay.bridge import State
        self.state=State(self.root/'state.sqlite');self.factory=FakeFactory()
        self.rt=Runtime(self.root/'orchestrator',self.factory,connection=self.state.db)

    def tearDown(self):
        self.rt.close();self.state.db.close();self.temp.cleanup()

    def test_shared_state_and_runtime_rollback_as_one_unit(self):
        with self.assertRaises(RuntimeError),storage.transaction(self.state.db):
            self.state.put('request','queued');self.rt.create(plan())
            raise RuntimeError('crash before commit')
        self.assertIsNone(self.state.get('request'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertFalse((self.root/'orchestrator/runtime.sqlite').exists())
        self.assertFalse((self.root/'orchestrator/state.sqlite').exists())

    def test_nested_read_snapshot_does_not_commit_callers_write(self):
        from task_relay import production_control
        with self.assertRaises(RuntimeError),storage.transaction(self.state.db):
            self.rt.create(plan());self.state.put('pending','yes')
            self.assertEqual(production_control.inspect(self.state)[0]['name'],'demo')
            raise RuntimeError('rollback')
        self.assertIsNone(self.state.get('pending'))
        self.assertEqual(production_control.inspect(self.state),[])

    def test_claims_commit_before_external_submit_and_cli_sees_same_store(self):
        self.rt.create(plan())
        original=self.factory.submit
        def submit(session):
            with closing(sqlite3.connect(self.root/'state.sqlite')) as other, other:
                self.assertEqual(other.execute('SELECT state FROM production_attempts WHERE id=?',(session['id'],)).fetchone()[0],'launching')
            self.assertFalse(self.state.db.in_transaction)
            return original(session)
        self.factory.submit=submit
        self.rt.tick('demo')
        cli=Runtime(self.root/'orchestrator',self.factory)
        try:self.assertEqual(cli.task('demo','produce')['latest'],self.rt.task('demo','produce')['latest'])
        finally:cli.close()

    def test_scheduler_will_not_launch_from_uncommitted_outer_transaction(self):
        with storage.transaction(self.state.db):
            self.rt.create(plan())
            with self.assertRaisesRegex(ValueError,'Commit pending'):self.rt.tick('demo')
        self.assertEqual(self.factory.calls,[])

    def test_wal_readers_keep_working_during_shared_write(self):
        self.rt.create(plan())
        with storage.transaction(self.state.db):
            self.state.put('pending','write')
            with closing(sqlite3.connect(self.root/'state.sqlite',timeout=.1)) as other, other:
                self.assertEqual(other.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
                self.assertIsNone(other.execute("SELECT value FROM kv WHERE key='pending'").fetchone())


if __name__=='__main__':unittest.main()
