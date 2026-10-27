"""Explicit app follow-ups through the existing conversation queue; no network."""
import json
import time
import uuid
import io
import unittest
from unittest.mock import Mock, patch

from task_relay import conversation_flow as flow, conversation_inputs, desktop_plans, desktop_workspace, orchestrator_chat as chat, relay_channels
from tests import test_shared_orchestrator as fixture


class Messages(unittest.TestCase):
    setUp=fixture.SharedTests.setUp

    def root(self,status='failed'):
        with self.state.db:
            self.state.db.execute('''INSERT INTO orchestrator_chats
                (id,prompt,provider,model,status,created,answer) VALUES (41,?,?,?,?,?,?)''',
                ('Original Telegram question','gemini','old-model',status,time.time()-100,'Original failure'))
        self.original=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=41').fetchone())
        return '41'

    def send(self,text='Please continue',identity=None):
        return flow.send_message('41',text,identity or str(uuid.uuid4()),self.paths)

    def admit(self):
        with patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'shared-current-model'}}):
            desktop_plans.process_requests(self.state)
        return self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id!=41 ORDER BY created DESC LIMIT 1').fetchone()

    def test_explicit_message_queues_once_current_model_and_same_job(self):
        self.root();identity=str(uuid.uuid4());receipt=self.send(identity=identity)
        again=self.send(identity=identity)
        self.assertEqual(receipt['request_id'],again['request_id'])
        self.assertEqual(flow.message_status('41',identity,self.paths)['status'],'queued')
        child=self.admit()
        self.assertEqual(child['model'],'shared-current-model');self.assertEqual(child['prompt'],'Please continue')
        self.assertEqual(relay_channels.request_channel(self.state,child['id']),'desktop')
        self.assertEqual(relay_channels.request_channel(self.state,41),'telegram')
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['total'],1)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=41').fetchone()),self.original)
        with self.assertRaisesRegex(ValueError,'different content'):self.send('Changed',identity)
        with self.assertRaisesRegex(ValueError,'still in progress'):self.send('Another message')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],1)

    def test_failed_then_successful_message_preserves_history_and_never_retries(self):
        self.root();self.send();first=self.admit()
        generator=Mock(side_effect=chat.gemini.ProviderError('connection-or-response'))
        snapshot={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}
        with patch.object(chat,'snapshot',return_value=snapshot),patch.object(chat.gemini,'DATA',self.paths.data):
            worker=chat.Worker(self.state,generator=generator);worker.tick();worker.tick()
        generator.assert_called_once()
        failed=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(first['id'],)).fetchone())
        self.assertEqual(failed['status'],'failed')
        self.send('A new follow-up');second=self.admit()
        self.assertNotEqual(second['id'],first['id'])
        payloads=[]
        def respond(job,payload):payloads.append(payload);return json.dumps(fixture.REPLY)
        with patch.object(chat,'snapshot',return_value=snapshot),patch.object(chat.gemini,'DATA',self.paths.data):
            chat.Worker(self.state,generator=respond).tick()
        self.assertEqual([r['id'] for r in payloads[0]['history']],[41,first['id']])
        self.assertEqual(payloads[0]['history'][0]['status'],'failed')
        self.assertEqual(flow.summary(self.state.db,41)['status'],'completed')
        view=desktop_workspace.chat_detail('41',self.paths)
        self.assertEqual(len(view['flow']['stages']),2)
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['total'],1)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(first['id'],)).fetchone()),failed)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=41').fetchone()),self.original)

    def test_context_excludes_unrelated_desktop_and_telegram_conversations(self):
        self.root()
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,status,created,answer) VALUES (99,'Unrelated','gemini','old','answered',?,'Do not include')",(time.time()-50,))
        self.send();child=self.admit()
        history=conversation_inputs.recent(self.state,child)
        self.assertEqual([r['id'] for r in history],[41])

    def test_transport_category_survives_worker_history_and_desktop_projection(self):
        from urllib.error import URLError
        cases=[(TimeoutError('private-key URL'),None,'timeout','timed out'),
               (URLError('private-key URL'),None,'connection','connection'),
               (None,b'not JSON private-key','invalid-response','unreadable response')]
        self.root()
        snapshot={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}
        for error,body,kind,display in cases:
            with self.subTest(kind=kind):
                self.send('Explicit follow-up '+kind);child=self.admit()
                client=chat.gemini.Client('private-key');client.opener=Mock()
                if error:client.opener.open.side_effect=error
                else:
                    from unittest.mock import MagicMock
                    client.opener=MagicMock()
                    client.opener.open.return_value.__enter__.return_value=io.BytesIO(body)
                def generate(*_):return client.request('models/test:generateContent',{})
                with patch.object(chat,'snapshot',return_value=snapshot),patch.object(chat.gemini,'DATA',self.paths.data):
                    worker=chat.Worker(self.state,generator=generate);worker.tick();worker.tick()
                client.opener.open.assert_called_once()
                row=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(child['id'],)).fetchone()
                self.assertEqual(row['status'],'failed')
                self.assertIn(display,row['answer'])
                self.assertIn('outcome remains unknown',row['answer'])
                self.assertIn('no automatic retry',row['answer'])
                saved=self.state.db.execute('SELECT message FROM orchestrator_chat_errors WHERE job_id=?',(child['id'],)).fetchone()[0]
                self.assertIn(kind,saved)
                view=desktop_workspace.chat_detail(str(child['id']),self.paths)
                self.assertEqual(view['display_answer'],row['answer'])
                self.assertNotIn('private-key',saved+row['answer'])
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=41').fetchone()),self.original)

    def test_lineage_failure_rolls_back_admission(self):
        self.root()
        with self.state.db:self.state.db.execute("CREATE TRIGGER reject_message BEFORE INSERT ON conversation_followups BEGIN SELECT RAISE(ABORT,'controlled'); END")
        with self.assertRaises(Exception):self.send()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)

    def test_unknown_receipt_check_does_not_submit_and_uncertain_can_have_new_message(self):
        self.root('uncertain');identity=str(uuid.uuid4())
        self.assertEqual(flow.message_status('41',identity,self.paths)['status'],'not_saved')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],0)
        self.send(identity=identity)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=41').fetchone()[0],'uncertain')

    def test_shared_settings_disclosed_for_telegram_failure(self):
        self.root()
        choice={'capabilities':[{'capability':'text','selected_available':True,'selected':{'provider':'gemini','model':'shared-current-model'}}]}
        with patch('task_relay.capability_defaults.snapshot',return_value=choice):
            view=desktop_workspace.chat_detail('41',self.paths)
        self.assertTrue(view['can_message']);self.assertEqual(view['message_model']['model'],'shared-current-model')
        self.send()
        self.assertFalse(flow.message_available(self.state.db,'41'))
