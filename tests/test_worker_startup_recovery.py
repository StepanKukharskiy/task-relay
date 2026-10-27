"""Same continuation machinery, immutable failed attempt, unchanged capacity."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import worker_startup_recovery as recovery
from orchestrator.workers import atomic
from tests import test_job_owner_loop as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    create=fixture.Tests.create

    def stopped(self):
        self.create();self.rt.tick('job');aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        folder=Path(s['session']['control']);folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/'done.json',dict(token=aid,exit_code=1,tool_calls=0))
        atomic(folder/'agent-result.json',dict(outcome='failed',reason='Synthetic import failure'))
        s['status']=dict(status='finished',token=aid,exit_code=1,tool_calls=0,api_requests=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');return aid,folder

    def attempt(self,aid):return self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()

    def changed(self):
        from orchestrator.runtime import file_hash
        return patch.object(recovery,'file_hash',side_effect=lambda p:'a'*64 if Path(p).name=='gemini_worker.py' else file_hash(p))

    def test_restart_idempotence_preserves_assignment_grant_and_attempt_count(self):
        aid,folder=self.stopped();task=self.rt.task('job','owner');spec=copy.deepcopy(self.rt.spec(task));calls=list(self.factory.calls)
        self.assertFalse(self.rt.continue_attempt('job','owner',aid,kind='worker_startup'))
        with self.changed():
            self.assertTrue(self.rt.continue_attempt('job','owner',aid,kind='worker_startup'))
            self.assertFalse(self.rt.continue_attempt('job','owner',aid,kind='worker_startup'))
            self.assertEqual(self.factory.calls,calls)
            self.assertEqual(self.rt.spec(self.rt.task('job','owner')),spec)
            self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertEqual(self.attempt(aid)['state'],'blocked')
        self.assertEqual(len(self.factory.calls),len(calls)+1)

    def test_any_request_tool_output_uncertainty_or_exhaustion_holds(self):
        aid,folder=self.stopped();task=self.rt.task('job','owner');attempt=dict(self.attempt(aid))
        with self.changed():
            for name in ('api-01.request.json','tool-01-01.json','code-call/intent.json'):
                p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
                self.assertIsNone(recovery.prove(self.rt,task,attempt));p.unlink()
            output=Path(json.loads(attempt['frozen'])['workspace'])/'job-result.json';output.write_text('{}')
            self.assertIsNone(recovery.prove(self.rt,task,attempt));output.unlink()
            for field,value in [('pending_requests',['unknown']),('api_requests',1),('external_outcome','uncertain'),('tool_calls',1)]:
                receipt=json.loads(attempt['receipt']);receipt[field]=value
                self.assertIsNone(recovery.prove(self.rt,task,{**attempt,'receipt':json.dumps(receipt)}))
            self.assertIsNone(recovery.prove(self.rt,{**task,'attempts':self.rt.spec(task)['max_attempts']},attempt))

    def test_changed_journal_after_admission_prevents_dispatch(self):
        aid,folder=self.stopped()
        with self.changed():
            self.assertTrue(self.rt.continue_attempt('job','owner',aid,kind='worker_startup'))
            (folder/'agent-result.json').write_text('{"outcome":"failed","reason":"Changed"}')
            before=len(self.factory.calls);self.rt.tick('job')
        self.assertEqual(len(self.factory.calls),before)
        self.assertEqual(self.rt.task('job','owner')['status'],'blocked')
