import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bridge import State,Bridge,BridgeError
from tests.test_bridge import TelegramFake
import task_routing as routing
import orchestrator_chat as chat


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.state=State(self.root/'state.sqlite');self.telegram=TelegramFake()
        self.tasks=[];self.calls=[];self.fail=False;self.on_open=None
        for i in range(2):
            path=self.root/f'task{i}.jsonl';path.write_text(json.dumps({'type':'event_msg','payload':{'type':'task_complete','turn_id':'old'}})+'\n')
            self.tasks.append(dict(id=f't{i}',name=f'Video task {i}',title='Existing video production',cwd=str(self.root),rollout_path=str(path),updated_at=1))
            with self.state.db:self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',(f't{i}',str(path),path.stat().st_size,f'Video task {i}','idle',1))
        with self.state.db:
            self.state.put('user_id',7);self.state.put('chat_id',7);self.state.put('orchestrator_routing_enabled',True)
        test=self
        class Desktop:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ready_owner(self,tid,**kwargs):
                if test.on_open:test.on_open()
                return 'owner'
            def start(self,tid,prompt,owner):
                test.calls.append((tid,prompt))
                if test.fail:raise TimeoutError('uncertain')
        self.bridge=Bridge(self.state,self.telegram,{},Desktop)
        self.worker=routing.Worker(self.state,Desktop,lambda:self.tasks)
        self.catalog_patch=patch('bridge.local_tasks',side_effect=lambda:self.tasks);self.catalog_patch.start()
        self.provider_patch=patch.object(chat,'provider',return_value=('gemini','fixture'));self.provider_patch.start()

    def tearDown(self):
        self.provider_patch.stop();self.catalog_patch.stop();self.state.db.close();self.tmp.cleanup()

    def request(self,action,text='Use Codex to inspect the video sources.\nDo not render.',ident=1):
        self.bridge.process({'update_id':ident,'message':{'text':'/orchestrator '+text,'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'selected','action':action})).tick()

    def click(self,index='0',user=7):
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone()
        update={'update_id':90,'callback_query':{'id':'c','data':'route:'+row['token']+':'+index,'from':{'id':user},'message':{'chat':{'id':7,'type':'private'}}}}
        self.bridge.process(update)

    def test_direct_request_sends_verbatim_once_without_extra_card(self):
        original='Use Codex to inspect this video.\nKeep ALL sources; do not render.  '
        self.request({'kind':'route_task','task_id':'t0'},original)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)
        self.worker.tick();self.worker.tick()
        self.assertEqual(len(self.calls),1);self.assertTrue(self.calls[0][1].endswith(original))
        self.assertEqual(self.calls[0][0],'t0')
        self.bridge.flush(False)
        self.assertTrue(any('Sent to Codex: Video task 0' in x[1] for x in self.telegram.sent))
        self.assertTrue(self.state.db.execute("SELECT 1 FROM messages WHERE thread_id='t0'").fetchone())

    def test_shared_capability_dispatch_uses_existing_codex_receipts(self):
        original='Use Codex in Video task 0 to check the source files. Do not render.'
        self.request({'kind':'delegate_task','task_id':'t0','provider':'codex','required_capabilities':['file_read']},original)
        self.worker.tick();self.worker.tick()
        self.assertEqual(len(self.calls),1)
        self.assertTrue(self.calls[0][1].endswith(original))
        receipt=self.state.db.execute('SELECT * FROM capability_dispatches').fetchone()
        self.assertEqual(receipt['executor'],'task_routes')
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'submitted')

    def test_choice_requires_complete_card_and_owner_preserves_original(self):
        original='Inspect the drawing video references using Codex.'
        self.request({'kind':'choose_task','task_ids':['t0','t1']},original)
        self.click();self.worker.tick();self.assertEqual(self.calls,[])
        self.bridge.flush(False)
        self.click(user=8);self.worker.tick();self.assertEqual(self.calls,[])
        self.click('1');self.click('0');self.worker.tick()
        self.assertEqual(self.calls[0][0],'t1');self.assertTrue(self.calls[0][1].endswith(original))
        self.assertEqual(len(self.calls),1)

    def test_changed_task_fails_before_dispatch(self):
        self.request({'kind':'route_task','task_id':'t0'})
        Path(self.tasks[0]['rollout_path']).write_text('changed')
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'failed')

    def test_task_changes_during_open_no_send(self):
        self.request({'kind':'route_task','task_id':'t0'})
        self.on_open=lambda:Path(self.tasks[0]['rollout_path']).write_text('changed')
        self.worker.tick();self.assertEqual(self.calls,[])

    def test_uncertain_ipc_not_replayed_after_restart(self):
        self.request({'kind':'route_task','task_id':'t0'});self.fail=True
        self.worker.tick();self.worker.started=False;self.worker.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'uncertain')

    def test_interrupted_submission_not_replayed(self):
        self.request({'kind':'route_task','task_id':'t0'})
        with self.state.db:self.state.db.execute("UPDATE task_routes SET status='submitting'")
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'uncertain')

    def test_busy_or_unknown_peer_does_not_block_idle_destination(self):
        for payload in ({'type':'task_started','turn_id':'busy'}, {'type':'unrecognized_event'}):
            Path(self.tasks[1]['rollout_path']).write_text(json.dumps({'type':'event_msg','payload':payload})+'\n')
            candidate=routing.catalog(self.state)[0]
            self.assertIsNone(candidate['routing_blocker'])
            self.assertEqual(routing.validate_selection(self.state,candidate)['id'],'t0')
        self.request({'kind':'route_task','task_id':'t0'})
        self.worker.tick();self.assertEqual([c[0] for c in self.calls],['t0'])

    def test_linked_workflow_reserves_its_tasks_only(self):
        with self.state.db:
            self.state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)',('linked',json.dumps(dict(cwd=str(self.root),status='active',phase='plan_ready',strategy_id='t1',executor_id='executor'))))
        entries={t['id']:t for t in routing.catalog(self.state)}
        self.assertIsNone(entries['t0']['routing_blocker'])
        self.assertIn('owns this task',entries['t1']['routing_blocker'])
        routing.validate_selection(self.state,entries['t0'])
        with self.assertRaises(ValueError):routing.validate_selection(self.state,entries['t1'])

    def test_busy_or_unknown_destination_still_blocks(self):
        for payload in ({'type':'task_started','turn_id':'busy'}, {'type':'unrecognized_event'}):
            Path(self.tasks[0]['rollout_path']).write_text(json.dumps({'type':'event_msg','payload':payload})+'\n')
            with self.assertRaises(ValueError):routing.validate_selection(self.state,routing.catalog(self.state)[0])

    def test_expired_or_cancelled_choice_never_starts(self):
        self.request({'kind':'choose_task','task_ids':['t0']});self.bridge.flush(False)
        with self.state.db:self.state.db.execute('UPDATE task_routes SET expires=0')
        self.click();self.worker.tick();self.assertEqual(self.calls,[])
        with self.state.db:self.state.db.execute('UPDATE task_routes SET expires=9999999999')
        self.click('cancel');self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'cancelled')

    def test_unknown_model_target_and_question_do_not_route(self):
        with self.assertRaises(ValueError):chat.interpret(json.dumps({'answer':'x','action':{'kind':'route_task','task_id':'invented'}}),chat.snapshot(self.state,None))
        self.request(None,'What is a workflow?')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)

    def test_same_project_can_queue_two_destinations_but_not_duplicate_target(self):
        self.request({'kind':'route_task','task_id':'t0'})
        self.request({'kind':'route_task','task_id':'t1'},ident=2)
        self.request({'kind':'route_task','task_id':'t0'},ident=3)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],2)
        self.worker.tick();self.worker.tick()
        self.assertEqual([c[0] for c in self.calls],['t0','t1'])

    def test_ordinary_message_can_target_peer_but_cannot_race_same_task(self):
        self.request({'kind':'route_task','task_id':'t0'})
        with self.state.db:self.state.put('selected','t0')
        self.bridge.submit_text({},'Conflicting turn',98,7)
        self.assertEqual(self.calls,[])
        self.assertIn('owns this task',self.telegram.sent[-1][1])
        with self.state.db:self.state.put('selected','t1')
        self.bridge.submit_text({},'Independent edit',99,7)
        self.assertEqual([c[0] for c in self.calls],['t1'])
        self.worker.tick();self.assertEqual([c[0] for c in self.calls],['t1','t0'])

    def test_uncertain_destination_does_not_block_its_peer(self):
        self.request({'kind':'route_task','task_id':'t0'});self.fail=True;self.worker.tick()
        self.fail=False
        self.request({'kind':'route_task','task_id':'t1'},ident=2)
        self.request({'kind':'route_task','task_id':'t0'},ident=3)
        self.worker.tick()
        self.assertEqual([c[0] for c in self.calls],['t0','t1'])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes WHERE id=1').fetchone()[0],'uncertain')

    def test_project_index_migration_preserves_reservations(self):
        import sqlite3
        self.request({'kind':'route_task','task_id':'t0'})
        with self.state.db:
            self.state.db.execute("UPDATE task_routes SET status='uncertain'")
            self.state.db.execute('DROP INDEX one_route_per_task')
            self.state.db.execute("CREATE UNIQUE INDEX one_route_per_project ON task_routes(cwd) WHERE status IN ('queued','opening','submitting','uncertain')")
        routing.initialize(self.state.db)
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'uncertain')
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM sqlite_master WHERE name='one_route_per_project'").fetchone())
        with self.assertRaises(sqlite3.IntegrityError):
            with self.state.db:
                self.state.db.execute("INSERT INTO task_routes(id,token,prompt,candidates,task_id,cwd,status,created,expires) SELECT 99,'duplicate',prompt,candidates,task_id,cwd,status,created,expires FROM task_routes WHERE id=1")
        self.request({'kind':'route_task','task_id':'t1'},ident=2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],2)

    def test_expired_queued_request_is_not_sent_after_downtime(self):
        self.request({'kind':'route_task','task_id':'t0'})
        with self.state.db:self.state.db.execute('UPDATE task_routes SET expires=0')
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'failed')

    def test_just_submitted_destination_blocks_without_blocking_peer(self):
        with self.state.db:self.state.db.execute("UPDATE watched SET status='running' WHERE id='t0'")
        entries={t['id']:t for t in routing.catalog(self.state)}
        self.assertEqual(entries['t0']['status'],'running')
        with self.assertRaises(ValueError):routing.validate_selection(self.state,entries['t0'])
        self.assertEqual(routing.validate_selection(self.state,entries['t1'])['id'],'t1')
