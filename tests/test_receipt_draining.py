"""Offline shared receipts and all stop reasons; no external providers."""
import json,sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
from orchestrator import receipt_reconciliation as receipts,codex_sources
from orchestrator.codex_transport import Client,Failure
from orchestrator.runtime import Runtime
from tests import test_codex_executor as codex
from tests import test_owner_parallel_progress as owner
from tests.test_orchestrator import FakeFactory,plan,task


class Receipts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def peer(self):
        events=[dict(method='item/started',params=dict(threadId='thread',turnId='turn',item=dict(id='read',type='webSearch'))),
            dict(method='item/completed',params=dict(threadId='thread',turnId='turn',item=dict(id='read',type='webSearch',query='fixture',results=[dict(url='https://example.org/source',title='Fixture')]))),
            dict(method='turn/completed',params=dict(threadId='thread',turn=dict(id='turn',status='completed')))]
        script=self.root/'script.json';script.write_text(json.dumps([dict(events=events)]))
        return Client(codex.CONFIG,codex.BACKEND,self.root/'control',10,command=[sys.executable,'-B',str(Path(__file__).with_name('codex_protocol_fixture.py')),str(script)])
    def test_completed_protocol_response_survives_cleanup_permission_error_and_restart(self):
        with self.peer() as client:
            result=client.search('fixture');process=client.process;wait=process.wait
            with patch.object(process,'wait',side_effect=subprocess.TimeoutExpired('fixture',1)),patch('orchestrator.codex_transport.HOST.stop_tree',side_effect=PermissionError('Operation not permitted')):
                client.close()
            wait(timeout=5)
        saved=receipts.restore(self.root/'control');self.assertEqual(saved['result'],result)
        self.assertEqual(saved['terminal']['status'],'completed')
        cleanup=json.loads((self.root/'control/cleanup-outcome.json').read_text());self.assertTrue(cleanup['response_preserved'])
        self.assertFalse(cleanup['acceptance']);self.assertFalse(cleanup['replayed'])
        sent=[json.loads(v) for v in (self.root/'control/codex-sent.jsonl').read_text().splitlines()]
        self.assertEqual(sum(v.get('method')=='turn/start' for v in sent),1)
        (self.root/'control/codex-events.jsonl').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'changed'):receipts.restore(self.root/'control')
    def test_incomplete_wrong_terminal_or_pending_effects_never_confirm(self):
        for terminal,pending in [(dict(id='other',status='completed'),[]),(dict(id='id',status='running'),[]),(dict(id='id',status='completed'),['pending'])]:
            with self.assertRaises(ValueError):receipts.commit(self.root,'id',terminal,dict(ok=True),pending)
        with self.assertRaises(PermissionError):receipts.cleanup(self.root,[('stop',lambda:(_ for _ in ()).throw(PermissionError('denied')))])
    def test_original_request_error_is_not_masked_by_cleanup(self):
        receipts.cleanup(self.root,[('stop',lambda:(_ for _ in ()).throw(PermissionError('cleanup failed')))],preserve_error=True)
        outcome=json.loads((self.root/'cleanup-outcome.json').read_text());self.assertTrue(outcome['body_error_preserved']);self.assertFalse(outcome['response_preserved'])
    def test_source_restart_reconciles_committed_result_without_provider_or_new_submission(self):
        with self.peer() as client:
            client.operation_id='submission-fixture';result=client.search('fixture')
        session=codex_sources.Session(self.root/'source.json',dict(backend=codex.BACKEND,cli_executor=codex.CONFIG))
        session.root.mkdir(exist_ok=True)
        import shutil
        shutil.copytree(self.root/'control',session.root/'codex')
        # Receipt identity keeps the original hashed journal paths, never replays.
        path=session.root/'search-0.json';original=dict(request_id='submission-fixture',query='fixture',backend=codex.BACKEND,status='submitted')
        path.write_text(json.dumps(original))
        with patch('orchestrator.codex_sources.Client') as provider:
            restored=session.search('fixture');provider.assert_not_called()
        self.assertEqual(restored,result);self.assertEqual(json.loads(path.read_text())['status'],'responded')
        self.assertEqual(json.loads((session.root/'search-reconciliation.json').read_text())['original'],original)
        with patch('orchestrator.codex_sources.Client') as provider:
            self.assertEqual(session.search('fixture'),result);provider.assert_not_called()
        self.assertEqual(json.loads((session.root/'search-reconciliation.json').read_text())['original'],original)
        with self.assertRaisesRegex(Failure,'different request'):session.search('another query')
        path.write_text(json.dumps({**original,'request_id':'different-submission'}))
        with self.assertRaisesRegex(Failure,'different submission'):session.search('fixture')


class Draining(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.factory=FakeFactory();self.root=Path(self.tmp.name)/'runtime';self.rt=Runtime(self.root,self.factory);self.addCleanup(lambda:self.rt.close())
    def graph(self):
        self.rt.create(plan([task('a'),task('b'),task('downstream',dependencies=['a'])],concurrency=2));self.rt.tick('demo')
    def test_each_stop_reason_collects_late_result_after_restart_without_new_dispatch(self):
        for stop in ('uncertain','awaiting_user','paused','cancelled','blocked','completed'):
            with self.subTest(stop=stop):
                self.rt.close();self.root=self.root/stop;self.rt=Runtime(self.root,self.factory);self.graph()
                a=self.rt.task('demo','a')['latest'];b=self.rt.task('demo','b')['latest'];calls=list(self.factory.calls)
                with self.rt.transaction():
                    if stop in ('uncertain','awaiting_user'):
                        self.rt.db.execute('UPDATE production_tasks SET status=? WHERE run=? AND id=?',(stop,'demo','a'))
                        self.rt.db.execute("UPDATE production_attempts SET state=? WHERE id=?",('completed' if stop=='awaiting_user' else 'uncertain',a))
                        self.factory.sessions[a]['status']=dict(status='uncertain',reason='Unresolved fixture')
                    else:
                        self.rt.db.execute('UPDATE production_runs SET status=? WHERE id=?',(stop,'demo'))
                        self.factory.finish(a)
                s=self.rt.status('demo');self.assertEqual(s['status'],'active');self.assertEqual(s['settlement']['terminal_outcome'],stop)
                self.rt.close();self.rt=Runtime(self.root,self.factory)
                self.factory.finish(b);self.rt.tick('demo')
                expected=stop
                self.assertEqual(self.rt.status('demo')['status'],expected)
                self.assertIsNotNone(self.rt.output('demo','b','output.txt'));self.assertIsNone(self.rt.task('demo','downstream')['latest'])
                self.assertEqual(calls,self.factory.calls)
                before=self.rt.db.execute("select count(*) from production_events where kind='worker_finished'").fetchone()[0]
                self.rt.tick('demo');self.assertEqual(before,self.rt.db.execute("select count(*) from production_events where kind='worker_finished'").fetchone()[0])
    def test_real_cancel_and_pause_resume_preserve_control_intent(self):
        self.graph();self.rt.pause('demo');self.assertEqual(self.rt.status('demo')['settlement']['terminal_outcome'],'paused')
        self.rt.resume('demo');self.assertNotIn('settlement',self.rt.status('demo'))
        self.rt.request_cancel('demo');self.assertEqual(self.rt.status('demo')['settlement']['terminal_outcome'],'cancelled')
        self.rt.tick('demo');self.assertEqual(self.rt.status('demo')['status'],'cancelled')
        self.assertIsNone(self.rt.task('demo','downstream')['latest'])


class OwnedDraining(unittest.TestCase):
    create=owner.Tests.create
    start=owner.Tests.start
    invoke=owner.Tests.invoke
    delegate=owner.Tests.delegate
    batch=owner.Tests.batch
    def setUp(self):owner.Tests.setUp(self)
    def test_waiting_owner_uncertain_child_drains_other_child_like_al(self):
        self.start();calls=list(self.factory.calls);a=self.rt.task('job','fast')['latest'];b=self.rt.task('job','slow')['latest']
        self.factory.sessions[a]['status']=dict(status='uncertain',reason='Unknown response',local_terminal=True)
        self.rt.tick('job');s=self.rt.status('job');self.assertEqual(s['status'],'active');self.assertEqual(s['settlement']['terminal_outcome'],'uncertain')
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.factory.finish(b);self.rt.tick('job');self.assertEqual(self.rt.status('job')['status'],'uncertain')
        self.assertIsNotNone(self.rt.output('job','slow','report.txt'));self.assertIsNone(self.rt.task('job','slow_review')['latest'])
        self.assertEqual(calls,self.factory.calls)
