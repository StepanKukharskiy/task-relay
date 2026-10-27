"""Real SQLite contention and shared record reads; no live providers or media."""
import copy,json,sqlite3,threading,unittest
from unittest.mock import patch
from orchestrator import operation_records,storage
from tests import test_operation_records as fixture
from tests.test_browser_fallback_lifecycle import retain_evidence

class Reads(unittest.TestCase):
    tearDown=retain_evidence
    def setUp(self):
        self.helper=fixture.Tests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.root=self.helper.root;self.db=self.helper.db;self.store=self.helper.store;self.files=self.helper.files
        self.db.execute('PRAGMA journal_mode=WAL');self.helper.submit();self.store.export(self.files,complete=True)
        self.db.execute('CREATE TABLE contention_probe(n INTEGER)');self.db.executemany('INSERT INTO contention_probe VALUES (?)',[(0,),(1,)])
        self.other=sqlite3.connect(self.helper.frozen['operation_store'],isolation_level=None,timeout=.05);self.addCleanup(self.other.close)
    def test_read_snapshot_survives_intervening_commit_and_preserves_exact_exports(self):
        cursor=self.db.execute('SELECT * FROM contention_probe');cursor.fetchone()
        self.other.execute('UPDATE contention_probe SET n=n+1')
        expected=self.files.read_bytes('delivery/research_audit.json')
        self.assertEqual(self.store.progress()['remaining'],0)
        self.store.verify_export(self.files.read_bytes);self.store.export(self.files,complete=True)
        self.assertEqual(self.files.read_bytes('delivery/research_audit.json'),expected)
        cursor.close()
    def test_reader_does_not_wait_for_unrelated_writer_and_readonly_connection_works(self):
        self.db.execute('PRAGMA busy_timeout=10');self.other.execute('BEGIN IMMEDIATE')
        try:
            self.assertEqual(self.store.progress()['committed'],3)
            self.store.verify_export(self.files.read_bytes)
            # The standalone path opens mode=ro; both paths have identical checks.
            standalone=operation_records.Store(self.helper.frozen)
            self.assertEqual(standalone.progress(),self.store.progress())
            from pathlib import Path
            ro=sqlite3.connect(Path(self.helper.frozen['operation_store']).as_uri()+'?mode=ro',uri=True,isolation_level=None)
            try:operation_records.Store(self.helper.frozen,ro).verify_export(self.files.read_bytes)
            finally:ro.close()
        finally:self.other.execute('ROLLBACK')
    def test_nested_observation_never_commits_outer_write(self):
        with self.assertRaisesRegex(ValueError,'rollback'),storage.transaction(self.db):
            self.db.execute('UPDATE contention_probe SET n=99')
            self.store.progress();self.store.verify_export(self.files.read_bytes)
            self.assertNotEqual(self.other.execute('SELECT n FROM contention_probe LIMIT 1').fetchone()[0],99)
            raise ValueError('rollback')
        self.assertEqual(self.db.execute('SELECT n FROM contention_probe LIMIT 1').fetchone()[0],0)
    def test_stale_snapshot_cannot_replay_a_write_body(self):
        cursor=self.db.execute('SELECT * FROM contention_probe');cursor.fetchone();self.other.execute('UPDATE contention_probe SET n=n+1')
        called=[]
        with self.assertRaises(sqlite3.OperationalError):
            with storage.transaction(self.db):called.append(True)
        self.assertEqual(called,[]);cursor.close()
        self.assertFalse(self.db.in_transaction)
    def test_tamper_and_foreign_assignment_still_rejected_under_contention(self):
        self.other.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(ValueError,'differs'):self.store.verify_export(lambda p:b'forged')
            frozen=copy.deepcopy(self.helper.frozen);frozen['limits']['output_bytes']+=1
            with self.assertRaisesRegex(ValueError,'authoritative'):operation_records.Store(frozen,self.db).progress()
        finally:self.other.execute('ROLLBACK')

class Writes(unittest.TestCase):
    tearDown=retain_evidence
    def setUp(self):
        self.helper=fixture.Tests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.root=self.helper.root;self.db=self.helper.db;self.db.execute('PRAGMA journal_mode=WAL')
    def test_transient_writer_lock_waits_before_body_one_receipt_and_restart_reuse(self):
        acquired=threading.Event();release=threading.Event();errors=[]
        def writer():
            db=sqlite3.connect(self.helper.frozen['operation_store'],isolation_level=None)
            try:
                db.execute('BEGIN IMMEDIATE');acquired.set();assert release.wait(5);db.execute('COMMIT')
            except BaseException as e:errors.append(e)
            finally:db.close()
        t=threading.Thread(target=writer);t.start();self.assertTrue(acquired.wait(5))
        def trace(sql):
            if sql=='BEGIN IMMEDIATE':release.set()
        self.db.set_trace_callback(trace)
        try:receipt=self.helper.submit()
        finally:release.set();t.join(5);self.db.set_trace_callback(None)
        self.assertFalse(t.is_alive());self.assertEqual(errors,[])
        reopened=operation_records.Store(self.helper.frozen)
        args=dict(request_key='batch-1',revision=0,records=self.helper.audit['claims'])
        self.assertEqual(reopened.submit(args,self.helper.context),receipt)
        self.assertEqual(self.db.execute('SELECT count(*) FROM operation_submissions').fetchone()[0],1)
        self.assertEqual(reopened.progress()['committed'],3)
    def test_exhausted_lock_commits_no_records_and_does_not_fake_acceptance(self):
        other=sqlite3.connect(self.helper.frozen['operation_store'],isolation_level=None);self.db.execute('PRAGMA busy_timeout=10');other.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(sqlite3.OperationalError):self.helper.submit()
            self.assertEqual(self.db.execute('SELECT count(*) FROM operation_submissions').fetchone()[0],0)
            self.assertEqual(self.helper.store.progress()['committed'],0)
        finally:other.execute('ROLLBACK');other.close()

class CatalogCorrection(unittest.TestCase):
    def test_catalog_content_amendment_review_restart_with_real_competing_writer(self):
        from tests import test_content_baseline_construction as baselines
        helper=baselines.Baselines();helper.setUp();self.addCleanup(helper.doCleanups)
        original_session=helper.session;catalogs=[]
        def session():
            owner=original_session()
            # Exercise actual shared discovery with completed inline records as
            # the flow advances, while another SQLite writer retains its lock.
            writer=sqlite3.connect(helper.rt.root/'state.sqlite',isolation_level=None)
            owner.rt.db.execute('PRAGMA busy_timeout=10');writer.execute('BEGIN IMMEDIATE')
            try:
                value=owner.call('job_catalog',dict(operations=[],records=True))
                catalogs.append(value)
                self.assertEqual(value['effective_request_ceiling'],24)
            finally:writer.execute('ROLLBACK');writer.close()
            return owner
        try:
            with patch.object(helper,'session',side_effect=session):
                helper.test_explicit_baseline_drives_worker_review_restart_and_raw_intent()
            self.assertGreaterEqual(len(catalogs),2)
        finally:retain_evidence(helper)

if __name__=='__main__':unittest.main()
