"""Usage I/O must leave the shared writer available; tiny local fixtures only."""
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from task_relay import usage_tracker as usage,usage_sources
from tests import test_preparation_capacity as capacity

class Boundary(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'state.sqlite'
        self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL');usage.initialize(self.db)
        self.db.execute('CREATE TABLE orchestrator_chats(id INTEGER,provider TEXT,model TEXT,created REAL,focus TEXT)')
        self.db.executemany('INSERT INTO orchestrator_chats VALUES (?,?,?,?,?)',[(1,'codex','m',1,None),(2,'codex','m',2,None)]);self.db.commit()
        self.reads=self.root/'orchestrator-reads';self.reads.mkdir()
        for ident in (1,2):
            (self.reads/(hashlib.sha256(str(ident).encode()).hexdigest()+'.json')).write_text(json.dumps([{'step':0,'response':{'usage':{'input_tokens':10,'output_tokens':2}}}]))
        self.other=sqlite3.connect(self.path,timeout=.01);self.addCleanup(self.other.close)
    def competing_write(self):
        self.assertFalse(self.db.in_transaction)
        with self.other:self.other.execute('CREATE TABLE IF NOT EXISTS independent(value)');self.other.execute('INSERT INTO independent VALUES (1)')
    def test_relay_journal_read_allows_writer_and_publishes_once(self):
        original=Path.read_text;seen=[]
        def read(path,*a,**kw):
            if path.parent==self.reads:self.competing_write();seen.append(path)
            return original(path,*a,**kw)
        with patch.object(Path,'read_text',read):usage.collect_relay(self.db,self.path)
        self.assertEqual(len(seen),2);self.assertEqual(self.db.execute('SELECT count(*) FROM usage_events').fetchone()[0],2)
        usage.collect_relay(self.db,self.path)
        self.assertEqual(self.db.execute('SELECT count(*) FROM usage_events').fetchone()[0],2)
    def test_failed_publication_rolls_back_records_and_health(self):
        original=usage.record;calls=[]
        def record(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('interrupted commit')
            return original(*args)
        with patch.object(usage,'record',record),self.assertRaises(RuntimeError):usage.collect_relay(self.db,self.path)
        self.assertEqual(self.db.execute('SELECT count(*) FROM usage_events').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM usage_health').fetchone()[0],0)
    def test_local_decode_allows_writer_and_cursor_is_atomic(self):
        root=self.root/'logs';root.mkdir();log=root/'session.jsonl'
        event={'type':'assistant','message':{'id':'m','usage':{'input_tokens':1,'output_tokens':2}}}
        log.write_text(json.dumps(event)+'\n'+json.dumps(event)+'\n')
        original=json.loads;seen=[]
        def loads(raw,*a,**kw):
            if isinstance(raw,bytes):self.competing_write();seen.append(raw)
            return original(raw,*a,**kw)
        with patch.object(json,'loads',loads):usage_sources.collect_local(self.db,[('claude',root)])
        self.assertEqual(len(seen),2);self.assertEqual(self.db.execute('SELECT offset FROM usage_cursors').fetchone()[0],log.stat().st_size)
        self.assertEqual(self.db.execute('SELECT count(*) FROM usage_events').fetchone()[0],1)
        log.write_text(log.read_text()+json.dumps({**event,'message':{'id':'n','usage':{}}})+'\n')
        before=[tuple(r) for r in self.db.execute('SELECT * FROM usage_cursors')]
        with patch.object(usage_sources,'consume',side_effect=RuntimeError('interrupt')),self.assertRaises(RuntimeError):usage_sources.collect_local(self.db,[('claude',root)])
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM usage_cursors')])
    def test_cursor_change_during_read_preserves_other_commit(self):
        root=self.root/'logs';root.mkdir();log=root/'session.jsonl'
        log.write_text(json.dumps({'type':'session_meta','payload':{}})+'\n')
        original=json.loads
        def loads(raw,*a,**kw):
            if isinstance(raw,bytes):
                with self.other:self.other.execute('INSERT INTO usage_cursors VALUES (?,?,?,?,?,?)',(str(log),'other',1,'{}',1,1))
            return original(raw,*a,**kw)
        with patch.object(json,'loads',loads),self.assertRaisesRegex(ValueError,'cursor changed'):
            usage_sources.collect_local(self.db,[('codex',root)])
        self.assertEqual(self.db.execute('SELECT identity FROM usage_cursors').fetchone()[0],'other')
        self.assertEqual(self.db.execute('SELECT count(*) FROM usage_events').fetchone()[0],0)
    def test_outer_transaction_is_not_committed(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(ValueError,'caller commits'):usage.collect_relay(self.db,self.path)
            with self.assertRaisesRegex(ValueError,'caller commits'):usage_sources.collect_local(self.db,[])
            self.assertTrue(self.db.in_transaction)
        finally:self.db.rollback()
    def test_complete_preparation_can_commit_during_journal_read(self):
        helper=capacity.Capacity();helper.setUp();self.addCleanup(helper.doCleanups)
        source=sqlite3.connect(helper.root/'rt/state.sqlite');source.row_factory=sqlite3.Row;self.addCleanup(source.close);usage.initialize(source)
        source.execute('CREATE TABLE orchestrator_chats(id,provider,model,created,focus)');source.executemany("INSERT INTO orchestrator_chats VALUES (?,'codex','m',1,NULL)",[(1,),(2,)]);source.commit()
        reads=helper.root/'rt/orchestrator-reads';reads.mkdir();
        for ident in (b'1',b'2'):(reads/(hashlib.sha256(ident).hexdigest()+'.json')).write_text('[]')
        original=Path.read_text;ran=[]
        def read(path,*a,**kw):
            if path.parent==reads and path.stem==hashlib.sha256(b'2').hexdigest():
                helper.rt.db.execute('PRAGMA busy_timeout=10')
                helper.test_full_176_object_handoff_under_unchanged_limits_and_restart();ran.append(True)
            return original(path,*a,**kw)
        with patch.object(Path,'read_text',read):usage.collect_relay(source,helper.root/'rt/state.sqlite')
        self.assertEqual(ran,[True]);self.assertTrue(helper.store.progress()['sealed'])

if __name__=='__main__':unittest.main()
