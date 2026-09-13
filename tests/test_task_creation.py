import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from task_relay import task_creation as creation, codex_app_server, capabilities, orchestrator_chat as chat, relay_channels
from task_relay.bridge import State, Bridge
from tests.test_bridge import TelegramFake

TID='12345678-1234-4321-8123-123456789abc'


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.project=self.root/'project';self.project.mkdir()
        self.path=self.root/'history.jsonl'
        self.path.write_text(json.dumps({'type':'session_meta','payload':{'id':TID}})+'\n')
        self.state=State(self.root/'state.sqlite');self.addCleanup(self.state.db.close)
        with self.state.db:
            self.state.put('orchestrator_routing_enabled',True)
            self.state.put('chat_id',7);self.state.put('user_id',7)
        for p in (patch.object(creation.HOST,'codex',return_value='/fake/codex'),
                  patch.object(creation.HOST,'codex_projects',return_value=[{'cwd':str(self.project),'name':'Project'}]),
                  patch('task_relay.bridge.local_tasks',return_value=[]),
                  patch.object(chat,'provider',return_value=('gemini','fixture'))):
            p.start();self.addCleanup(p.stop)
        self.calls=[];self.starts=[];self.fail=None;self.on_open=None;self.on_read=None;self.control_connected=False
        test=self
        class Client:
            def __enter__(self):test.control_connected=True;return self
            def __exit__(self,*args):test.control_connected=False
            def request(self,method,params):
                test.assertFalse(test.state.db.in_transaction)
                test.calls.append((method,params))
                if test.fail==method:raise TimeoutError('response lost')
                if method=='thread/start':return {'thread':{'id':TID,'cwd':str(test.project),'path':str(test.path)}}
                test.assertEqual(test.row()['task_id'],TID)
                if method=='thread/read':
                    if test.on_read:return test.on_read()
                    return {'thread':{'id':TID,'cwd':str(test.project),'path':str(test.path),'turns':[],'status':{'type':'idle'}}}
                return {}
        class Desktop:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ready_owner(self,tid,**kwargs):
                test.assertFalse(test.control_connected)
                if test.on_open:test.on_open()
                return 'owner'
            def start(self,tid,prompt,owner):
                test.assertFalse(test.state.db.in_transaction)
                if test.row()['start_work']:test.assertEqual(test.row()['status'],'submitting')
                test.starts.append((tid,prompt))
                if test.fail=='desktop.start':raise TimeoutError('first turn response lost')
                return {'confirmed':True}
        self.worker=creation.Worker(self.state,Desktop,Client)
        self.bridge=Bridge(self.state,TelegramFake(),{},Desktop)

    def row(self):return self.state.db.execute('SELECT * FROM task_creations').fetchone()

    def action(self,start=False):
        return dict(kind='create_codex_task',project=str(self.project),title='New research',start_work=start,research_ids=[],artifact_ids=[])

    def queue(self,start=False,channel='telegram'):
        prompt='Create a new task in Project'+(' and inspect the inputs.\nDo not render.  ' if start else '. Do not start work.')
        with self.state.db:
            self.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(71,channel))
            self.state.db.execute('BEGIN IMMEDIATE') if not self.state.db.in_transaction else None
            snap={'codex_projects':creation.projects(self.state)}
            result=capabilities.dispatch(self.state,{'id':71,'prompt':prompt},self.action(start),snap)
            self.assertEqual(result,capabilities.dispatch(self.state,{'id':71,'prompt':prompt},self.action(start),snap))
        return prompt

    def test_empty_creation_is_idle_and_routes_receipt_to_original_channel(self):
        self.queue(channel='messages');self.worker.tick();self.worker.tick()
        self.assertEqual(self.row()['status'],'created');self.assertEqual(self.starts,[])
        self.assertEqual([c[0] for c in self.calls],['thread/start','thread/name/set','thread/read'])
        self.assertEqual(self.calls[0][1],{'cwd':str(self.project),'ephemeral':False})
        self.assertEqual(creation.task_status(self.state,TID,self.path),'idle')
        self.assertEqual(relay_channels.event_channel(self.state,'task-created:71:result'),'messages')
        self.path.write_text('changed unknown history')
        self.assertEqual(creation.task_status(self.state,TID,self.path),'unknown')

    def test_create_start_sends_exact_request_once_and_remembers_receipt(self):
        original=self.queue(True);self.worker.tick();self.worker.started=False;self.worker.tick()
        self.assertEqual(self.row()['status'],'submitted');self.assertEqual(len(self.starts),1)
        self.assertIn('--- ORIGINAL USER REQUEST ---\n'+original,self.starts[0][1])
        record=self.state.db.execute("SELECT * FROM task_creation_calls WHERE method='desktop.start'").fetchone()
        self.assertEqual(json.loads(record['params'])['prompt'],self.starts[0][1])
        self.assertEqual(self.state.db.execute('SELECT thread_id FROM capability_dispatches').fetchone()[0],TID)

    def test_reply_to_created_empty_task_starts_first_instruction(self):
        self.queue();self.worker.tick();self.bridge.flush(False)
        message_id=self.state.db.execute('SELECT message_id FROM messages WHERE thread_id=?',(TID,)).fetchone()[0]
        self.bridge.process({'update_id':72,'message':{'text':'Inspect files only.',
            'reply_to_message':{'message_id':message_id},'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        self.assertEqual(self.starts,[(TID,'Inspect files only.')])
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=72').fetchone()[0],'submitted')

    def test_disabled_routing_after_queue_prevents_creation(self):
        self.queue()
        with self.state.db:self.state.put('orchestrator_routing_enabled',False)
        self.worker.tick();self.assertEqual(self.row()['status'],'failed');self.assertEqual(self.calls,[])

    def test_creation_reply_lost_never_replayed(self):
        self.queue();self.fail='thread/start';self.worker.tick();self.worker.started=False;self.worker.tick()
        self.assertEqual(self.row()['status'],'uncertain');self.assertEqual(len(self.calls),1)
        self.assertIsNone(self.row()['task_id'])

    def test_title_failure_keeps_known_id_no_first_turn(self):
        self.queue(True);self.fail='thread/name/set';self.worker.tick();self.worker.started=False;self.worker.tick()
        self.assertEqual(self.row()['status'],'needs_inspection');self.assertEqual(self.row()['task_id'],TID)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.starts,[])
        self.assertIn(TID,self.state.db.execute('SELECT text FROM outbox').fetchone()[0])

    def test_first_turn_uncertain_preserves_task_without_replay(self):
        self.queue(True);self.fail='desktop.start';self.worker.tick();self.worker.started=False;self.worker.tick()
        self.assertEqual(self.row()['status'],'uncertain');self.assertEqual(self.row()['task_id'],TID)
        self.assertEqual(len(self.calls),3);self.assertEqual(len(self.starts),1)

    def test_interrupted_external_boundaries_do_not_replay(self):
        self.queue()
        with self.state.db:self.state.db.execute("UPDATE task_creations SET status='creating'")
        self.worker.tick()
        self.assertEqual(self.row()['status'],'uncertain');self.assertEqual(self.calls,[])

    def test_crash_after_response_recovers_id_without_creating_again(self):
        self.queue()
        with self.state.db:
            self.state.db.execute("UPDATE task_creations SET status='creating'")
            self.state.db.execute('INSERT INTO task_creation_calls(request_id,method,params,response) VALUES (?,?,?,?)',
                (71,'thread/start','{}',json.dumps({'thread':{'id':TID,'path':str(self.path)}})))
        self.worker.tick()
        self.assertEqual(self.row()['status'],'needs_inspection');self.assertEqual(self.row()['task_id'],TID)
        self.assertEqual(self.calls,[])

    def test_replaced_project_fails_before_creation(self):
        self.queue();self.project.rename(self.root/'old-project');self.project.mkdir()
        self.worker.tick();self.assertEqual(self.row()['status'],'failed');self.assertEqual(self.calls,[])

    def test_empty_history_changed_during_open_blocks_start(self):
        self.queue(True);self.on_open=lambda:self.path.write_text('unknown new work')
        self.worker.tick();self.assertEqual(self.row()['status'],'needs_inspection');self.assertEqual(self.starts,[])

    def test_no_persisted_history_preserves_id_but_does_not_claim_ready(self):
        self.queue();self.path.unlink();self.worker.tick()
        self.assertEqual(self.row()['status'],'needs_inspection');self.assertEqual(self.row()['task_id'],TID)

    def test_lazy_rollout_is_flushed_before_desktop_handoff(self):
        original=self.queue(True);self.path.unlink()
        def materialize():
            self.assertEqual(self.starts,[])
            self.path.write_text(json.dumps({'type':'session_meta','payload':{'id':TID}})+'\n')
            return {'thread':{'id':TID,'cwd':str(self.project),'path':str(self.path),
                'turns':[],'status':{'type':'idle'}}}
        self.on_read=materialize
        self.worker.tick();self.worker.started=False;self.worker.tick()
        self.assertEqual(self.row()['status'],'submitted')
        self.assertEqual(len(self.starts),1);self.assertIn(original,self.starts[0][1])
        receipt=self.state.db.execute("SELECT response FROM task_creation_calls WHERE method='thread/read'").fetchone()
        self.assertEqual(json.loads(receipt[0])['thread']['id'],TID)

    def test_full_read_failure_keeps_identity_without_submission_or_replay(self):
        self.queue(True);self.fail='thread/read';self.worker.tick()
        self.worker.started=False;self.worker.tick()
        self.assertEqual(self.row()['status'],'needs_inspection')
        self.assertEqual(self.row()['task_id'],TID);self.assertEqual(self.starts,[])
        self.assertEqual(len(self.calls),3)

    def test_full_read_must_confirm_same_empty_idle_task(self):
        self.queue(True)
        for changes in ({'id':'other'},{'path':'/other/history'}, {'cwd':str(self.root)},
                        {'turns':[{'id':'existing-turn'}]}, {'status':{'type':'active'}}):
            with self.subTest(changes=changes):
                with self.state.db:
                    self.state.db.execute('DELETE FROM task_creation_calls')
                    self.state.db.execute("UPDATE task_creations SET status='queued'")
                self.on_read=lambda:{'thread':dict(id=TID,cwd=str(self.project),path=str(self.path),
                    turns=[],status={'type':'idle'})|changes}
                self.worker.tick()
                self.assertEqual(self.row()['status'],'needs_inspection');self.assertEqual(self.starts,[])

    def test_restart_during_persistence_never_recreates(self):
        self.queue(True)
        with self.state.db:
            self.state.db.execute("UPDATE task_creations SET status='created_pending',task_id=?",(TID,))
        self.worker.tick()
        self.assertEqual(self.row()['status'],'needs_inspection');self.assertEqual(self.calls,[])

    def test_rollback_has_no_queue_or_external_effect(self):
        with self.assertRaisesRegex(ValueError,'rollback'):
            with self.state.db:
                self.state.db.execute('BEGIN IMMEDIATE')
                capabilities.dispatch(self.state,{'id':1,'prompt':'Create only'},self.action(),
                                      {'codex_projects':creation.projects(self.state)})
                raise ValueError('rollback')
        self.worker.tick();self.assertIsNone(self.row());self.assertEqual(self.calls,[])

    def test_real_orchestrator_boundary_to_worker_and_task_reply_identity(self):
        original='Can you start a new Codex task in Project to research whether we can run Keynote autonomously? Or HTML to PDF? What other options do we have?'
        with self.state.db:
            self.state.put('orchestrator_mode',False)
            self.state.put('selected','busy-old')
            self.state.db.execute("INSERT INTO watched(id,title,status) VALUES ('busy-old','Existing task','running')")
        self.bridge.process({'update_id':71,'message':{'text':original,
            'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Queued','action':self.action(True)})).tick()
        self.assertIsNotNone(self.row(),self.state.db.execute('SELECT answer FROM orchestrator_chats').fetchone()[0])
        self.worker.tick();self.bridge.flush(False)
        self.assertEqual(self.row()['status'],'submitted')
        self.assertIn(original,self.starts[0][1])
        self.assertTrue(self.state.db.execute('SELECT 1 FROM messages WHERE thread_id=?',(TID,)).fetchone())

    def test_telegram_request_through_stdio_creation_and_first_turn(self):
        script=self.root/'app-server.py'
        script.write_text('''import json,sys
initialized=False
for line in sys.stdin:
 v=json.loads(line)
 if v['method']=='initialized':initialized=True;continue
 if v['method']=='initialize':result={}
 elif v['method']=='thread/start':
  assert initialized and v['params']=={'cwd':sys.argv[1],'ephemeral':False}
  result={'thread':{'id':sys.argv[3],'cwd':sys.argv[1],'path':sys.argv[2]}}
 elif v['method']=='thread/read':
  assert v['params']=={'threadId':sys.argv[3],'includeTurns':True}
  result={'thread':{'id':sys.argv[3],'cwd':sys.argv[1],'path':sys.argv[2],'turns':[],'status':{'type':'idle'}}}
 elif v['method']=='thread/name/set':
  assert v['params']['threadId']==sys.argv[3]
  result={}
 else:raise AssertionError('Unexpected external method')
 print(json.dumps({'id':v['id'],'result':result}),flush=True)
''')
        self.worker.client_factory=lambda:codex_app_server.Client(command=[sys.executable,str(script),
            str(self.project),str(self.path),TID],timeout=2)
        self.test_real_orchestrator_boundary_to_worker_and_task_reply_identity()

    def test_direct_creation_command_no_interpretation_and_deduplicated(self):
        update={'update_id':71,'message':{'text':'/new codex "'+str(self.project)+'" Research task',
            'from':{'id':7},'chat':{'id':7,'type':'private'}}}
        self.bridge.process(update);self.bridge.process(update);self.worker.tick()
        self.assertEqual(self.row()['status'],'created');self.assertEqual(self.row()['prompt'],update['message']['text'])
        self.assertEqual(self.starts,[])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)

    def test_unknown_project_and_creation_only_sources_rejected(self):
        snap={'codex_projects':creation.projects(self.state)}
        action=self.action();action['project']='/not-offered'
        with self.assertRaises(ValueError):creation.validate_action(action,snap)
        action=self.action();action['research_ids']=[1]
        with self.assertRaises(ValueError):creation.validate_action(action,snap)


class ProtocolTests(unittest.TestCase):
    def test_unowned_task_activates_desktop_before_owner_retry(self):
        from task_relay.bridge import Desktop,OwnerUnavailable
        from task_relay.host import Host
        active=False
        def launch(args,**kwargs):
            nonlocal active
            active='-g' not in args and args[-1]=='codex://threads/'+TID
            return type('Result',(),{'returncode':0})()
        def owner(tid):
            if not active:raise OwnerUnavailable('Inactive window')
            return 'desktop-owner'
        desktop=Desktop()
        with patch('task_relay.bridge.HOST',Host('darwin')), \
                patch('task_relay.host.Path.is_dir',return_value=True), \
                patch('task_relay.host.subprocess.run',side_effect=launch) as run, \
                patch.object(desktop,'owner',side_effect=owner),patch('task_relay.bridge.time.sleep'):
            self.assertEqual(desktop.ready_owner(TID),'desktop-owner')
            self.assertEqual(run.call_count,1)
            self.assertEqual(desktop.ready_owner(TID),'desktop-owner')
            self.assertEqual(run.call_count,1)  # Existing owners need no activation.

    def test_subprocess_protocol_handshake_notifications_and_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'server.py';log=Path(tmp)/'calls.jsonl'
            script.write_text('''import json,sys
for line in sys.stdin:
 v=json.loads(line)
 with open(sys.argv[1],'a') as f:f.write(line)
 if 'id' not in v:continue
 print(json.dumps({'method':'test/notification','params':{}}),flush=True)
 print(json.dumps({'id':v['id'],'result':{'ok':True}}),flush=True)
''')
            with codex_app_server.Client(command=[sys.executable,str(script),str(log)],timeout=2) as client:
                self.assertEqual(client.request('thread/start',{'cwd':tmp,'ephemeral':False}),{'ok':True})
                client.request('thread/name/set',{'threadId':TID,'name':'Test'})
            calls=[json.loads(x) for x in log.read_text().splitlines()]
            self.assertEqual([c['method'] for c in calls],['initialize','initialized','thread/start','thread/name/set'])
            self.assertNotIn('turn/start',[c['method'] for c in calls])

    def test_correlated_rejection_distinct_from_lost_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'server.py'
            script.write_text('''import json,sys
for line in sys.stdin:
 v=json.loads(line)
 if 'id' not in v:continue
 if v['method']=='initialize':print(json.dumps({'id':v['id'],'result':{}}),flush=True)
 else:print(json.dumps({'id':v['id'],'error':{'code':-1,'message':'unsupported'}}),flush=True)
''')
            with codex_app_server.Client(command=[sys.executable,str(script)],timeout=2) as client:
                with self.assertRaises(codex_app_server.Rejected):client.request('thread/start',{})
