"""Local service startup contention; no provider, browser or message dispatch."""
import sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from task_relay.bridge import State,BackgroundWorkers

class Tests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'state.sqlite';self.workers=BackgroundWorkers(self.path,{},None)

    def test_locked_initialization_retries_without_dispatch_and_preserves_database(self):
        state=State(self.path)
        with state.db:state.put('fixture-request','Exact authorized request')
        state.db.close()
        error=sqlite3.OperationalError('controlled lock');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch('task_relay.bridge.State',side_effect=[error,State(self.path)]) as factory,patch.object(self.workers.stop,'wait',return_value=False) as wait:
            current=self.workers.open_state('desktop')
        self.addCleanup(current.db.close)
        self.assertEqual(factory.call_count,2);wait.assert_called_once_with(2)
        self.assertEqual(current.get('fixture-request'),'Exact authorized request')
        self.assertEqual(current.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)

    def test_failed_migration_closes_its_partial_connection(self):
        connections=[]
        def fail(state,path):
            state.db=sqlite3.connect(path);connections.append(state.db)
            state.db.execute('CREATE TABLE IF NOT EXISTS marker(value)')
            state.db.execute('INSERT INTO marker VALUES(1)')
            raise sqlite3.OperationalError('controlled later migration failure')
        with patch.object(State,'_initialize',fail),self.assertRaises(sqlite3.OperationalError):State(self.path)
        with self.assertRaises(sqlite3.ProgrammingError):connections[0].execute('SELECT 1')
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM marker').fetchone()[0],0)

    def test_cancellation_interrupts_startup_backoff(self):
        error=sqlite3.OperationalError('controlled lock');error.sqlite_errorcode=sqlite3.SQLITE_LOCKED
        with patch('task_relay.bridge.State',side_effect=error) as factory,patch.object(self.workers.stop,'wait',return_value=True):
            self.assertIsNone(self.workers.open_state('desktop'))
        self.assertEqual(factory.call_count,1)

    def test_worker_connections_initialize_serially(self):
        active=0;peak=0;results=[]
        def construct(_):
            nonlocal active,peak
            active+=1;peak=max(peak,active);time.sleep(.01);active-=1
            return object()
        with patch('task_relay.bridge.State',side_effect=construct):
            threads=[threading.Thread(target=lambda:results.append(self.workers.open_state('fixture'))) for _ in range(4)]
            for t in threads:t.start()
            for t in threads:t.join()
        self.assertEqual(peak,1);self.assertEqual(len({id(v) for v in results}),4)

if __name__=='__main__':unittest.main()
