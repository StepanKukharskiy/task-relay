"""Small indexed-evidence and confirmed zero-dispatch recovery fixtures."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import executors,sourcing_contract
from orchestrator.gemini_worker import Files
from task_relay import input_preflight_recovery as recovery
from tests import test_sourcing_records,test_input_preflight
from tests.test_gemini_executor import graph


class IndexedTests(unittest.TestCase):
    setUp=test_sourcing_records.Tests.setUp
    input=test_sourcing_records.Tests.input
    assignment=test_sourcing_records.Tests.assignment
    save=test_sourcing_records.Tests.save
    def test_indexed_artifact_is_not_an_inline_model_request(self):
        with patch.object(executors,'MAX_INPUT_BYTES',64):
            files=Files(self.frozen)
            self.assertEqual(files.call('file_read',dict(path='sources.json',offset=0,limit=24))['text'],
                             (self.root/'sources.json').read_text()[:24])
            excerpt=sourcing_contract.source_read(self.store.sourcing_context(),dict(observation='page-0-0',offset=0,limit=12))
            self.assertEqual(excerpt['text'],self.text[:12])
            legacy=copy.deepcopy(self.frozen);legacy.pop('operation_contract')
            with self.assertRaises(ValueError):Files(legacy)
            with patch.object(executors,'text_input_limit',return_value=64):
                with self.assertRaises(ValueError):Files(self.frozen)


class RecoveryTests(unittest.TestCase):
    setUp=test_input_preflight.Tests.setUp
    tearDown=test_input_preflight.Tests.tearDown

    def blocked(self):
        self.rt.create(graph());self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        (self.factory.sessions[aid]['workspace']/'output.txt').write_text('x'*65)
        with patch.object(executors,'MAX_INPUT_BYTES',64):self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        return aid

    def test_requeue_keeps_artifacts_assignments_and_attempts_then_dispatches_once(self):
        aid=self.blocked();task=dict(self.rt.task('demo','review'));artifact=dict(self.rt.output('demo','produce','output.txt'))
        assignments=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_assignments')]
        with patch.object(executors,'MAX_INPUT_BYTES',64),patch.object(executors,'text_input_limit',return_value=128):
            with self.rt.transaction():result=recovery.requeue(self.rt,'demo')
            self.assertEqual(len(result),1)
            with self.rt.transaction():self.assertEqual(recovery.requeue(self.rt,'demo'),[])
        self.assertEqual(dict(self.rt.output('demo','produce','output.txt')),artifact)
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_assignments')],assignments)
        self.assertEqual(self.rt.task('demo','review')['assignment'],task['assignment'])
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.rt.tick('demo');self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(self.rt.task('demo','produce')['latest'],aid)

    def test_pause_and_uncertain_work_are_ineligible(self):
        self.blocked()
        with patch.object(executors,'MAX_INPUT_BYTES',64),patch.object(executors,'text_input_limit',return_value=128):
            with self.rt.transaction():
                self.state.db.execute("UPDATE production_runs SET status='paused' WHERE id='demo'")
                self.assertEqual(recovery.requeue(self.rt,'demo'),[])
                self.state.db.execute("UPDATE production_runs SET status='active' WHERE id='demo'")
                self.state.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run='demo' AND id='produce'")
                self.assertEqual(recovery.requeue(self.rt,'demo'),[])
        self.assertEqual(len(self.factory.calls),1)

    def test_changed_source_is_not_requeued(self):
        self.blocked();artifact=self.rt.output('demo','produce','output.txt')
        from pathlib import Path
        p=Path(artifact['blob']);p.chmod(0o600);p.write_text('changed')
        with patch.object(executors,'MAX_INPUT_BYTES',64),patch.object(executors,'text_input_limit',return_value=128):
            with self.rt.transaction():self.assertEqual(recovery.requeue(self.rt,'demo'),[])
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        self.assertEqual(len(self.factory.calls),1)


if __name__=='__main__':unittest.main()
