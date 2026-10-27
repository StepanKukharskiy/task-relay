import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from orchestrator.execution_audit import export


class Tests(unittest.TestCase):
    def test_completed_runtime_exports_derived_status_without_mutating_history(self):
        from orchestrator.runtime import Runtime
        from tests.test_orchestrator import FakeFactory,plan,task
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);factory=FakeFactory();rt=Runtime(root/'runtime',factory)
            try:
                rt.create(plan([task('write')]))
                rt.tick('demo');factory.finish(rt.task('demo','write')['latest']);rt.tick('demo')
                self.assertEqual(rt.status('demo')['status'],'completed')
                self.assertEqual(rt.db.execute('SELECT status FROM production_runs').fetchone()[0],'active')
                database=Path(rt.db.execute('PRAGMA database_list').fetchone()[2])
                before=list(rt.db.execute('SELECT id,kind,data FROM production_events'))
                result=export(database,rt.root/'workers','demo',root/'audit')
                audit=json.loads(Path(result['json']).read_text())
                self.assertEqual(audit['status'],'completed');self.assertEqual(audit['stored_status'],'active')
                self.assertEqual(list(rt.db.execute('SELECT id,kind,data FROM production_events')),before)
            finally:rt.close()

    def test_exact_prompt_response_rejection_and_controller_event_survive_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'state.sqlite';workers=root/'workers';folder=workers/'a1';folder.mkdir(parents=True)
            connection=sqlite3.connect(db)
            connection.executescript('CREATE TABLE production_runs(id,plan,status); CREATE TABLE production_attempts(id,run,task,state,frozen,receipt,error); CREATE TABLE production_events(id,created,run,task,attempt,kind,data);')
            connection.execute('INSERT INTO production_runs VALUES(?,?,?)',('job',json.dumps(dict(brief='Exact user request')), 'active'))
            connection.execute('INSERT INTO production_attempts VALUES(?,?,?,?,?,?,?)',('a1','job','owner','uncertain',json.dumps(dict(backend=dict(type='codex-agent'))),None,'No second response'))
            connection.execute('INSERT INTO production_events VALUES(?,?,?,?,?,?,?)',(7,12.5,'job','owner','a1','proposal_rejected',json.dumps(dict(reason='Invalid output binding'))))
            connection.commit();connection.close();before=db.read_bytes()
            request=dict(provider='gemini',payload=dict(systemInstruction=dict(parts=[dict(text='Exact system instruction')]),contents=[]))
            raw=json.dumps(request,indent=3).encode();(folder/'api-01.request.json').write_bytes(raw)
            (folder/'api-01.response.json').write_text(json.dumps(dict(candidates=[dict(content=dict(parts=[dict(functionCall=dict(name='job_delegate',args=dict(bad=True)))]))])))
            (folder/'tool-01-00.json').write_text(json.dumps(dict(name='job_delegate',arguments=dict(bad=True),result=dict(error='Invalid output binding'))))
            (folder/'api-02.request.json').write_text('{}')
            (folder/'api-02.outcome.json').write_text(json.dumps(dict(outcome='uncertain')))
            (folder/'codex-thread-request.json').write_text(json.dumps(dict(baseInstructions='Exact CLI base',developerInstructions='Exact Relay system')))
            (folder/'codex-events.jsonl').write_text('{"method":"item/started"}\n{"unfinished":')
            native=folder/'query-01';native.mkdir();(native/'search-0.json').write_text(json.dumps(dict(status='uncertain',query='fixture')))
            result=export(db,workers,'job',root/'audit');audit=json.loads(Path(result['json']).read_text())
            self.assertEqual(db.read_bytes(),before)
            self.assertEqual(audit['status'],'uncertain')
            self.assertEqual(audit['events'][0]['id'],7)
            self.assertEqual(audit['events'][0]['data']['reason'],'Invalid output binding')
            first,second=audit['attempts'][0]['exchanges']
            self.assertEqual(first['request']['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(first['reactions'][0]['result']['error'],'Invalid output binding')
            self.assertEqual(second['response_state'],'not_recorded');self.assertIsNone(second['response'])
            self.assertEqual(second['outcome_detail']['outcome'],'uncertain')
            self.assertEqual(len(audit['attempts'][0]['native']),2)
            self.assertEqual(len(audit['attempts'][0]['registered']),1)
            page=Path(result['markdown']).read_text()
            self.assertIn('Exact system',Path(first['request']['path']).read_text())
            self.assertIn('Invalid output binding',page)
            self.assertIn('job_delegate',page)
            # A new observation retains the earlier index and its exact hashes.
            again=export(db,workers,'job',root/'audit')
            self.assertNotEqual(again['json'],result['json']);self.assertTrue(Path(result['json']).is_file())
            self.assertEqual(json.loads((root/'audit/SUMMARY.json').read_text())['json'],again['json'])

    def test_unknown_run_does_not_create_an_audit_or_write_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'state.sqlite'
            with sqlite3.connect(db) as connection:connection.execute('CREATE TABLE production_runs(id,plan,status)')
            with self.assertRaisesRegex(ValueError,'Unknown run'):export(db,root/'workers','missing',root/'audit')
            self.assertFalse((root/'audit').exists())


if __name__=='__main__':unittest.main()
