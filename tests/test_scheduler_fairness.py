"""Scheduler receipt priority without dispatching any work."""
import sqlite3
import unittest
from types import SimpleNamespace
from task_relay.production_control import Worker

class Tests(unittest.TestCase):
    def state(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE production_runs(id TEXT)');db.execute('CREATE TABLE production_attempts(run TEXT,state TEXT)')
        enabled={}
        return SimpleNamespace(db=db,get=lambda key:enabled.get(key)),enabled

    def test_current_work_gets_seven_ticks_while_historical_unknowns_remain_fair(self):
        state,enabled=self.state()
        state.db.execute("INSERT INTO production_runs VALUES ('current')");enabled['production-enabled:current']='unchanged-grant'
        for i in range(8):
            name='unknown-'+str(i);state.db.execute('INSERT INTO production_runs VALUES (?)',(name,));state.db.execute('INSERT INTO production_attempts VALUES (?,?)',(name,'uncertain'))
        before=state.db.total_changes;worker=Worker(state)
        sequence=[worker.next_run() for _ in range(64)]
        self.assertEqual(sequence.count('current'),56)
        self.assertEqual([s for s in sequence if s!='current'],['unknown-'+str(i) for i in range(8)])
        self.assertEqual(state.db.total_changes,before);self.assertIsNone(worker.runtime)

    def test_disabled_live_workers_are_drained_before_historical_unknowns(self):
        state,_=self.state()
        for name,status in [('stopped-stage','running'),('historical','uncertain')]:
            state.db.execute('INSERT INTO production_runs VALUES (?)',(name,));state.db.execute('INSERT INTO production_attempts VALUES (?,?)',(name,status))
        worker=Worker(state);self.assertEqual(worker.next_run(),'stopped-stage')
        state.db.execute("UPDATE production_attempts SET state='completed' WHERE run='stopped-stage'")
        self.assertEqual(worker.next_run(),'historical')
