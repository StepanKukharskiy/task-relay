import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bridge import Bridge, State
from tests.test_bridge import TelegramFake
import orchestrator_chat as chat
import workflows


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.temp.name) / 'state.sqlite')
        self.telegram = TelegramFake()
        self.bridge = Bridge(self.state, self.telegram, {})
        self.data = dict(name='spellshape', cwd=self.temp.name, strategy_id='s', executor_id='e',
                         strategy_title='Strategy', executor_title='Executor', status='paused',
                         phase='executing', blocked=True, accepted=0, step_limit=1, attempts=1,
                         attempt_limit=1, planning_only=False, run_id='old', reason='ps denied; zero launches')
        with self.state.db:
            self.state.put('user_id', 7); self.state.put('chat_id', 7)
            self.state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)', ('spellshape', json.dumps(self.data)))
        self.config = patch.object(chat, 'provider', return_value=('gemini', 'test-model'))
        self.config.start()

    def tearDown(self):
        self.config.stop(); self.state.db.close(); self.temp.cleanup()

    def message(self, text, ident=1, reply=None, user=7):
        m = {'text':text,'chat':{'id':7,'type':'private'},'from':{'id':user}}
        if reply is not None: m['reply_to_message']={'message_id':reply}
        self.bridge.process({'update_id':ident,'message':m})

    def result(self, action=None):
        return json.dumps({'answer':'The saved record reports a permission failure before launch.', 'action':action})

    def action(self, kind='plan'):
        return dict(kind=kind,workflow='spellshape',items=1 if kind=='run' else None,
                    direction='Review the permission blocker without launching solvers.' if kind in ('plan','run') else '')

    def prepare(self, kind='plan'):
        self.message('/orchestrator Plan a recovery for spellshape')
        chat.Worker(self.state, lambda *_: self.result(self.action(kind))).tick()
        self.bridge.flush(False)
        return self.state.db.execute('SELECT * FROM orchestrator_proposals').fetchone()

    def click(self, token, user=7, verb='apply'):
        self.bridge.process({'update_id':100,'callback_query':{'id':'cb','data':f'orch:{verb}:{token}',
            'from':{'id':user},'message':{'chat':{'id':7,'type':'private'},'message_id':1}}})

    def test_legacy_off_explains_routing_without_disabling_new_messages(self):
        self.message('/orchestrator')
        self.assertTrue(self.state.get('orchestrator_mode'))
        self.message('Why is Spellshape blocked?',2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)
        self.message('/orchestrator off',3)
        self.message('Another question',4)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],2)
        self.bridge.flush(False)
        self.assertIn('New messages always go', self.telegram.sent[-1][1])

    def test_auth_and_duplicate_delivery(self):
        self.message('/orchestrator why?',user=8)
        self.assertFalse(self.state.get('orchestrator_mode'))
        self.message('/orchestrator why?',2);self.message('/orchestrator why?',2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)

    def test_task_and_unknown_replies_do_not_fall_through_to_mode(self):
        self.message('/orchestrator')
        for reply in (22,99):
            with patch.object(self.bridge,'submit_text') as submit:
                self.message('talk to agent',reply,reply=reply)
                submit.assert_called_once()

    def test_workflow_notice_reply_routes_to_orchestrator_without_mode(self):
        with self.state.db: workflows.notice(self.state,self.data,'Blocked.','test')
        self.bridge.flush(False)
        self.message('Why did this stop?',reply=1)
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['focus'],'spellshape')
        self.assertFalse(self.state.get('orchestrator_mode'))

    def test_pending_approval_has_priority(self):
        self.message('/orchestrator')
        with patch('approval_ui.reply_input',return_value=True): self.message('yes',2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)

    def test_direct_workflow_status_reply_routes_to_orchestrator(self):
        self.message('/workflow status spellshape');self.bridge.flush(False)
        self.message('Explain this',2,reply=1)
        self.assertEqual(self.state.db.execute('SELECT focus FROM orchestrator_chats').fetchone()[0],'spellshape')

    def test_read_only_answer_never_changes_workflow(self):
        self.message('/orchestrator Why blocked?')
        payloads=[]
        def generate(job,payload): payloads.append(payload);return self.result()
        chat.Worker(self.state,generate).tick()
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        self.assertEqual(len(payloads),1)
        self.assertIn('ps denied',payloads[0]['snapshot']['workflows'][0]['reason'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)

    def test_original_comments_survive_lossy_model_summary_and_newlines(self):
        import workflow_protocol
        original = 'Why narrow strips?\nStart with rooms along the façade.\n' + 'Keep this constraint. ' * 230
        self.message('/orchestrator ' + original)
        chat.Worker(self.state, lambda *_: self.result(self.action())).tick()
        self.bridge.flush(False)
        row = self.state.db.execute('SELECT * FROM orchestrator_proposals').fetchone()
        self.click(row['token'])
        data, _ = workflows.read(self.state, 'spellshape')
        self.assertEqual(data['source_request']['text'], original)
        prompt = workflow_protocol.prompt(data, 'planning', '[relay-workflow:test]')
        self.assertIn(original, prompt)
        self.assertIn(self.action()['direction'], prompt)
        self.assertIn('hypotheses to investigate', prompt)

    def test_snapshot_distinguishes_applied_queued_and_submitted_current_run(self):
        row = self.prepare(); self.click(row['token'])
        queued = chat.snapshot(self.state, None)['workflows'][0]
        self.assertEqual(queued['phase'], 'plan_ready')
        self.assertEqual(queued['control_receipts'][0]['status'], 'applied')
        self.assertEqual(queued['current_run_dispatches'], [])
        data, rev = workflows.read(self.state, 'spellshape')
        data['operation'] = {'marker':'current-marker','phase':'planning'}
        with self.state.db:
            workflows.event(self.state, 'spellshape', 'dispatch_claimed', data)
            self.state.db.execute('INSERT INTO workflow_dispatches VALUES (?,?,?,?,?,?)',
                ('current-marker','spellshape','s','Actual handoff','submitted',123))
            old = dict(data, run_id='previous', operation={'marker':'old-marker','phase':'executing'})
            workflows.event(self.state, 'spellshape', 'dispatch_claimed', old)
            self.state.db.execute('INSERT INTO workflow_dispatches VALUES (?,?,?,?,?,?)',
                ('old-marker','spellshape','e','Old handoff','submitted',124))
        sent = chat.snapshot(self.state, None)['workflows'][0]
        self.assertEqual(sent['current_run_dispatches'], [{'thread_id':'s','status':'submitted','created':123,'phase':'planning','original_message_included':True}])
        self.assertEqual(sent['control_receipts'][0]['original_user_message'], 'Plan a recovery for spellshape')

    def test_snapshot_preserves_uncertain_delivery_and_expired_card(self):
        self.prepare()
        data, _ = workflows.read(self.state, 'spellshape')
        data['operation'] = {'marker':'uncertain-marker','phase':'planning'}
        with self.state.db:
            self.state.db.execute('UPDATE orchestrator_proposals SET expires=0')
            workflows.event(self.state, 'spellshape', 'dispatch_claimed', data)
            self.state.db.execute('INSERT INTO workflow_dispatches VALUES (?,?,?,?,?,?)',
                ('uncertain-marker','spellshape','s','Handoff','uncertain',123))
        view = chat.snapshot(self.state, None)['workflows'][0]
        self.assertEqual(view['control_receipts'][0]['status'], 'expired')
        self.assertEqual(view['current_run_dispatches'][0]['status'], 'uncertain')
        self.assertFalse(view['current_run_dispatches'][0]['original_message_included'])

    def test_confirmed_plan_uses_workflow_controls_and_is_not_replayed(self):
        row=self.prepare()
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        self.click(row['token'])
        data,rev=workflows.read(self.state,'spellshape')
        self.assertTrue(data['planning_only']);self.assertEqual(data['phase'],'plan_ready')
        self.click(row['token'])
        self.assertEqual(workflows.read(self.state,'spellshape')[1],rev)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM workflow_dispatches').fetchone()[0],0)

    def test_stale_expired_and_unauthorized_controls_do_not_apply(self):
        row=self.prepare();self.click(row['token'],user=8)
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        with self.state.db: self.state.db.execute('UPDATE workflows SET revision=revision+1')
        self.click(row['token'])
        self.assertEqual(workflows.read(self.state,'spellshape')[1],1)
        with self.state.db: self.state.db.execute('UPDATE orchestrator_proposals SET expires=0')
        self.click(row['token'])
        self.assertEqual(workflows.read(self.state,'spellshape')[1],1)

    def test_blocked_resume_is_rejected_and_proposal_receipt_rolls_back(self):
        row=self.prepare('resume');self.click(row['token'])
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_proposals').fetchone()[0],'pending')

    def test_complete_card_required_before_apply(self):
        row=self.prepare()
        with self.state.db: self.state.db.execute('UPDATE outbox SET sent=0')
        self.click(row['token'])
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)

    def test_dismiss_never_changes_workflow(self):
        row=self.prepare();self.click(row['token'],verb='dismiss')
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_proposals').fetchone()[0],'dismissed')

    def test_restart_never_replays_submitted_generation(self):
        self.message('/orchestrator why?')
        with self.state.db: self.state.db.execute("UPDATE orchestrator_chats SET status='sending'")
        with patch.object(chat,'generate') as generate:
            chat.Worker(self.state,generate).tick();generate.assert_not_called()
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'uncertain')

    def test_provider_failure_and_invalid_response_never_dispatch(self):
        for i, response in enumerate(('not json',self.result(dict(self.action('run'),items=100))),1):
            self.message('/orchestrator run',i)
            chat.Worker(self.state,lambda *_:response).tick()
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)

    def test_queue_preserves_order_and_bounded_history(self):
        self.message('/orchestrator why?',1);self.message('and then?',2)
        calls=[]
        worker=chat.Worker(self.state,lambda job,payload:(calls.append((job['id'],payload)) or self.result()))
        worker.tick();worker.tick()
        self.assertEqual([c[0] for c in calls],[1,2])
        self.assertEqual(calls[1][1]['history'][0]['prompt'],'why?')

    def test_input_parser_rejects_duplicate_keys_and_unsupported_actions(self):
        snap=chat.snapshot(self.state,None)
        for raw in ('{"answer":"a","answer":"b","action":null}', self.result(dict(self.action(),kind='shell')),
                    self.result(dict(self.action('run'),items=True))):
            with self.assertRaises(ValueError):chat.interpret(raw,snap)

    def test_media_in_mode_is_not_staged_for_previously_selected_agent(self):
        self.message('/orchestrator')
        self.bridge.process({'update_id':2,'message':{'chat':{'id':7,'type':'private'},'from':{'id':7},'document':{'file_id':'f'}}})
        row=self.state.db.execute('SELECT run,status FROM production_uploads').fetchone()
        self.assertEqual(tuple(row),('@orchestrator','pending'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM codex_inputs').fetchone()[0],0)

    def test_use_selects_commands_without_redirecting_new_messages(self):
        with self.state.db:self.state.db.execute('INSERT INTO watched(id,title) VALUES (?,?)',('s','Strategy'))
        self.message('/orchestrator');self.message('/use s',2)
        self.assertEqual(self.state.get('selected'),'s')
        self.assertIn('Selected for commands: Strategy',self.telegram.sent[-1][1])
        self.message('Start new research',3)
        self.assertEqual(self.state.db.execute('SELECT prompt FROM orchestrator_chats').fetchone()[0],'Start new research')

    def test_persisted_old_selection_cannot_bypass_orchestrator_after_restart(self):
        with self.state.db:
            self.state.put('orchestrator_mode',False)
            self.state.put('selected','busy')
            self.state.db.execute("INSERT INTO watched(id,title,status) VALUES ('busy','Old selected task','running')")
        restarted=State(Path(self.temp.name)/'state.sqlite')
        try:
            bridge=Bridge(restarted,self.telegram,{})
            original='Can you start a new Codex task to research Keynote? Or HTML to PDF?'
            update={'update_id':42,'message':{'text':original,'chat':{'id':7,'type':'private'},'from':{'id':7}}}
            with patch.object(bridge,'submit_text') as submit:
                bridge.process(update);bridge.process(update)
            submit.assert_not_called()
            rows=restarted.db.execute('SELECT prompt FROM orchestrator_chats').fetchall()
            self.assertEqual([row[0] for row in rows],[original])
        finally:restarted.db.close()

    def test_missing_provider_never_falls_back_to_selected_task(self):
        with self.state.db:self.state.put('selected','busy')
        with patch.object(chat,'provider',side_effect=ValueError('Connect a conversation provider first.')), patch.object(self.bridge,'submit_text') as submit:
            self.message('Start a new research task')
        submit.assert_not_called()
        self.assertIn('Connect a conversation provider',self.telegram.sent[-1][1])

    def test_routing_reports_command_target_without_model_or_dispatch(self):
        with self.state.db:
            self.state.put('selected','s')
            self.state.db.execute("INSERT INTO watched(id,title) VALUES ('s','Strategy')")
        self.message('/routing')
        self.assertIn('Selected target for commands: Strategy',self.telegram.sent[-1][1])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)

    def test_run_budget_is_only_applied_after_user_tap(self):
        row=self.prepare('run')
        self.assertEqual(workflows.read(self.state,'spellshape')[1],0)
        self.click(row['token'])
        data,_=workflows.read(self.state,'spellshape')
        self.assertEqual(data['step_limit'],1);self.assertFalse(data['planning_only'])
        self.assertEqual(data['phase'],'plan_ready')

    def test_clock_distinguishes_fixed_cet_from_summer_civil_time(self):
        from datetime import datetime, timezone
        summer=chat.clock_context(datetime(2026,9,10,7,20,tzinfo=timezone.utc))
        self.assertEqual(summer['cet_fixed'],'2026-09-10T08:20:00+01:00')
        self.assertEqual(summer['central_europe']['datetime'],'2026-09-10T09:20:00+02:00')
        self.assertEqual(summer['central_europe']['abbreviation'],'CEST')
        winter=chat.clock_context(datetime(2026,1,10,23,20,tzinfo=timezone.utc))
        self.assertEqual(winter['cet_fixed'],'2026-01-11T00:20:00+01:00')
        self.assertEqual(winter['central_europe']['datetime'],winter['cet_fixed'])
        self.assertEqual(winter['central_europe']['abbreviation'],'CET')

    def test_provider_request_replaces_stale_clock_with_fresh_host_clock(self):
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':self.result()}]}}]}
        with patch.object(chat.gemini,'read_config',return_value={'api_key':'test'}), \
             patch.object(chat.gemini,'DATA',Path(self.temp.name)), \
             patch.object(chat.gemini,'Client') as client, \
             patch.object(chat,'clock_context',return_value={'utc':'fresh-clock'}):
            client.return_value.request.return_value=response
            chat.generate({'id':'clock-fixture','provider':'gemini','model':'test-model'},{'host_clock':{'utc':'stale-clock'},'user_message':'CET now?'})
        sent=client.return_value.request.call_args.args[1]
        payload=json.loads(sent['contents'][0]['parts'][0]['text'])
        self.assertEqual(payload['host_clock'],{'utc':'fresh-clock'})


if __name__=='__main__': unittest.main()
