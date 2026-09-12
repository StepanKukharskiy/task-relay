import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_orchestrator_chat as fixtures
from tests.test_orchestrator import FakeFactory, pair
from orchestrator.runtime import Runtime
import orchestrator_chat as chat
import production_control as pc


class Tests(unittest.TestCase):
    def blocked_revision(self):
        self.finish_stage()
        previous_review = self.rt.task('demo','review')['latest']
        self.rt.revise('demo','produce','Use new market sources')
        self.rt.tick('demo')
        attempt = self.rt.task('demo','produce')['latest']
        self.factory.finish(attempt,decision='blocked')
        self.rt.tick('demo')
        with self.rt.transaction():
            self.rt.db.execute('UPDATE production_attempts SET error=? WHERE id=?', ('Missing dated market sources',attempt))
        return previous_review, attempt

    def test_blocked_producer_does_not_make_waiting_reviewer_active(self):
        self.blocked_revision()
        # Simulate a stale relay cache and stale enabled flag after interruption.
        tasks = self.rt.status('demo')['tasks']
        with self.state.db:
            self.state.put('production-status:demo',{'status':'awaiting_user','tasks':sorted([[t['id'],t['status'],t['attempts']] for t in tasks])})
            self.state.put('production-enabled:demo',True)
        view = pc.inspect(self.state,'demo')[0]
        self.assertEqual(view['status'],self.rt.status('demo')['status'])
        self.assertEqual(view['status'],'blocked')
        self.assertFalse(next(t for t in view['tasks'] if t['id']=='review')['runnable'])
        with self.assertRaisesRegex(ValueError,'blocked, not running.*Missing dated market sources.*exhausted'):
            pc.revision_target(view)

    def test_prior_review_does_not_approve_new_blocked_attempt(self):
        old_review, latest = self.blocked_revision()
        view = pc.inspect(self.state,'demo')[0]
        reviewer = next(t for t in view['tasks'] if t['id']=='review')
        self.assertFalse(reviewer['review_is_current'])
        self.assertNotEqual(reviewer['review_target'],latest)
        self.assertEqual({a['attempt'] for a in view['latest_outputs']},{latest})
        self.assertEqual({a['attempt'] for a in view['historical_outputs']},{old_review})
        self.assertTrue(all(a['attempt']==latest for a in view['output_texts']))

    def test_blocked_feedback_keeps_original_request_without_dispatch(self):
        self.blocked_revision()
        original='I updated the market research file we should use for script. Can we update the script using this research?'
        count=len(self.factory.calls)
        self.assertIsNone(self.revision_card(original,222))
        row=self.state.db.execute('SELECT prompt,answer FROM orchestrator_chats WHERE id=222').fetchone()
        self.assertEqual(row['prompt'],original)
        self.assertIn('blocked, not running',row['answer'])
        self.assertNotIn('Wait for its review',row['answer'])
        self.assertEqual(len(self.factory.calls),count)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_revisions').fetchone()[0],0)

    message = fixtures.Tests.message
    click = fixtures.Tests.click
    def setUp(self):
        fixtures.Tests.setUp(self)
        self.factory = FakeFactory()
        self.rt = Runtime(pc.root(self.state), self.factory, connection=self.state.db)
        source = Path(self.temp.name).resolve() / 'story.md'
        source.write_text('Complete source story with its final paragraph.')
        aid = self.rt.register(source, 'Full source', run='demo', path='story.md')
        value = pair(gate='creative selection')
        for task in value['tasks']:
            task.setdefault('inputs', []).append(dict(artifact=aid, path='story.md', purpose='Source', authority='User story'))
        self.rt.create(value)
        with self.state.db:
            self.state.put('orchestrator_production_focus', 'demo')

    def tearDown(self):
        self.rt.close()
        fixtures.Tests.tearDown(self)

    def stage_card(self):
        self.message('/orchestrator Start the demo preparation stage')
        action = dict(kind='start_production', workflow='demo', items=None, direction='')
        chat.Worker(self.state, lambda *_: json.dumps(dict(answer='Preparation only.', action=action))).tick()
        self.bridge.flush(False)
        return self.state.db.execute('SELECT * FROM orchestrator_proposals').fetchone()

    def worker(self):
        return pc.Worker(self.state, lambda _: self.rt)

    def test_registration_and_proposal_do_not_launch_duplicate_click_launches_once(self):
        worker = self.worker(); worker.tick()
        self.assertEqual(self.factory.calls, [])
        row = self.stage_card(); worker.tick()
        self.assertEqual(self.factory.calls, [])
        self.click(row['token']); worker.tick()
        self.click(row['token']); worker.tick()
        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_proposals').fetchone()[0], 'applied')

    def test_changed_plan_and_undelivered_unauthorized_card_rejected(self):
        row = self.stage_card()
        self.click(row['token'], user=8)
        self.assertFalse(self.state.get('production-enabled:demo'))
        with self.state.db: self.state.db.execute('UPDATE outbox SET sent=0')
        self.click(row['token'])
        self.assertFalse(self.state.get('production-enabled:demo'))
        with self.state.db: self.state.db.execute('UPDATE outbox SET sent=1')
        spec = self.rt.spec(self.rt.task('demo', 'produce'))
        spec['instruction'] = 'Different instruction'
        self.rt.replace_future('demo', spec)
        self.click(row['token'])
        self.assertFalse(self.state.get('production-enabled:demo'))

    def test_mutation_after_approval_stops_before_dispatch(self):
        self.click(self.stage_card()['token'])
        spec = self.rt.spec(self.rt.task('demo', 'produce'))
        spec['instruction'] = 'Different instruction'
        self.rt.replace_future('demo', spec)
        self.worker().tick()
        self.assertEqual(self.factory.calls, [])
        self.assertFalse(self.state.get('production-enabled:demo'))

    def test_complete_review_delivers_documents_and_reply_context_once(self):
        self.click(self.stage_card()['token'])
        worker = self.worker(); worker.tick()
        self.factory.finish(self.rt.task('demo', 'produce')['latest'])
        worker.tick()
        self.factory.finish(self.rt.task('demo', 'review')['latest'], decision='accept')
        worker.tick(); worker.tick()
        self.assertEqual(len(self.factory.calls), 2)
        self.assertFalse(self.state.get('production-enabled:demo'))
        files = self.state.db.execute('SELECT * FROM media_outbox').fetchall()
        self.assertEqual(len(files), 2)
        self.assertTrue(all(Path(f['path']).is_file() for f in files))
        self.assertEqual(pc.inspect(self.state, 'demo')[0]['status'], 'awaiting_user')
        self.bridge.flush()
        self.assertTrue(all(Path(f['path']).is_file() for f in files))
        messages = self.state.db.execute("SELECT message_id FROM orchestrator_messages WHERE focus='demo'").fetchall()
        self.assertGreaterEqual(len(messages), 3)
        self.message('Explain the result', 200, reply=messages[-1][0])
        self.assertEqual(self.state.db.execute('SELECT focus FROM orchestrator_chats WHERE id=200').fetchone()[0], 'demo')
        snapshot = chat.snapshot(self.state, 'demo')['production_runs'][0]
        self.assertEqual(snapshot['reference_texts'][0]['text'], 'Complete source story with its final paragraph.')
        self.assertEqual(len(snapshot['latest_outputs']), 2)

    def test_reviewer_revision_preserves_authorized_contract(self):
        self.click(self.stage_card()['token'])
        worker = self.worker(); worker.tick()
        self.factory.finish(self.rt.task('demo', 'produce')['latest']); worker.tick()
        self.factory.finish(self.rt.task('demo', 'review')['latest'], decision='revise'); worker.tick()
        worker.tick()
        self.assertEqual(len(self.factory.calls), 3)
        self.assertTrue(self.state.get('production-enabled:demo'))

    def test_large_output_does_not_disable_conversation_status(self):
        self.click(self.stage_card()['token'])
        worker=self.worker();worker.tick()
        aid=self.rt.task('demo','produce')['latest']
        self.factory.finish(aid)
        (self.factory.sessions[aid]['workspace']/'output.txt').write_text('x'*300000)
        worker.tick()
        view=chat.snapshot(self.state,'demo')['production_runs'][0]
        self.assertEqual(view['reference_texts'][0]['text'],'Complete source story with its final paragraph.')
        output=view['output_texts'][0]
        self.assertTrue(output['truncated']);self.assertEqual(output['full_chars'],300000)
        self.assertEqual(len(output['text']),20000)

    def test_callback_transport_failure_does_not_undo_authorization(self):
        from bridge import BridgeError
        row = self.stage_card()
        with patch.object(self.telegram, 'call', side_effect=BridgeError('offline')):
            self.click(row['token'])
        self.assertTrue(self.state.get('production-enabled:demo'))
        self.worker().tick()
        self.assertEqual(len(self.factory.calls), 1)


    def finish_stage(self):
        self.click(self.stage_card()['token'])
        worker = self.worker(); worker.tick()
        self.factory.finish(self.rt.task('demo','produce')['latest']); worker.tick()
        self.factory.finish(self.rt.task('demo','review')['latest'],decision='accept'); worker.tick()
        self.bridge.flush()
        return worker

    def revision_card(self, text='Please revise with this exact guide.\nKeep the 65-second limit.  ', ident=200):
        reply = self.state.db.execute("SELECT message_id FROM orchestrator_messages WHERE focus='demo' ORDER BY message_id DESC LIMIT 1").fetchone()[0]
        self.message(text,ident,reply=reply)
        action = dict(kind='revise_production',workflow='demo',items=None,direction='Revise the preparation')
        chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Revision ready.',action=action))).tick()
        self.bridge.flush(False)
        return self.state.db.execute('SELECT * FROM orchestrator_proposals WHERE job_id=?',(ident,)).fetchone()

    def upload_guide(self, ident=150, caption='Use this guide', filename='new-guide.md'):
        reply = self.state.db.execute("SELECT message_id FROM orchestrator_messages WHERE focus='demo' LIMIT 1").fetchone()[0]
        message = {'message_id':ident,'chat':{'id':7,'type':'private'},'from':{'id':7},
                   'reply_to_message':{'message_id':reply}, 'caption':caption,
                   'document':{'file_id':'file','file_name':filename,'file_size':10}}
        self.bridge.process({'update_id':ident,'message':message})
        self.telegram.download_file = lambda fid,path,limit: (path.parent.mkdir(parents=True,exist_ok=True), path.write_text('Original uploaded instructions'))
        pc.Worker(self.state,lambda _:self.rt,telegram=self.telegram).download()
        return self.state.db.execute('SELECT * FROM production_uploads WHERE id=?',(ident,)).fetchone()

    def test_feedback_and_guides_reach_both_workers_once_and_deliver_second_result(self):
        worker=self.finish_stage()
        original = 'Please revise this.\nKeep exactly this constraint.  '
        guide=self.upload_guide()
        card=self.revision_card(original)
        self.assertIsNotNone(card)
        self.assertEqual(len(self.factory.calls),2)
        self.click(card['token']);self.click(card['token'])
        worker.tick();worker.tick()
        self.assertEqual(len(self.factory.calls),3)
        producer=self.rt.task('demo','produce')
        frozen=self.factory.sessions[producer['latest']]['frozen']
        self.assertTrue(frozen['revision']['instruction'].startswith(original))
        self.assertIn('Use this guide',frozen['revision']['instruction'])
        self.assertTrue(any(i.get('previous_delivery') for i in frozen['inputs']))
        for tid in ('produce','review'):
            inputs=self.rt.spec(self.rt.task('demo',tid))['inputs']
            paths=[i['path'] for i in inputs]
            self.assertIn('story.md',paths)
            self.assertTrue(any(p.endswith('feedback.txt') for p in paths))
            self.assertTrue(any(p.endswith('new-guide.md') for p in paths))
        self.assertEqual(Path(guide['path']).read_text(),'Original uploaded instructions')
        self.factory.finish(producer['latest']);worker.tick()
        self.factory.finish(self.rt.task('demo','review')['latest'],decision='accept');worker.tick();worker.tick()
        self.assertEqual(len(self.factory.calls),4)
        self.assertFalse(self.state.get('production-enabled:demo'))
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'production:demo:result:%'").fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0],4)
        captions=[r[0] for r in self.state.db.execute('SELECT caption FROM media_outbox')]
        self.assertTrue(any('attempt 2' in c and 'output.txt' in c for c in captions))
        self.assertIsNone(self.revision_card('Revise again',201))
        answer=self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=201').fetchone()[0]
        self.assertIn('exhausted',answer)

    def test_changed_guides_and_changed_runtime_reject_stale_revision(self):
        worker=self.finish_stage()
        card=self.revision_card()
        self.upload_guide()
        self.click(card['token'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_revisions').fetchone()[0],0)
        card=self.revision_card(ident=201);self.click(card['token'])
        spec=self.rt.spec(self.rt.task('demo','produce'))
        spec['instruction']='Changed after approval'
        with self.rt.transaction():
            self.rt.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),self.rt.task('demo','produce')['assignment']))
        worker.tick()
        self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_revisions').fetchone()[0],'failed')

    def test_tampered_guide_blocks_before_revision_and_keeps_original_assignments(self):
        worker=self.finish_stage();guide=self.upload_guide()
        card=self.revision_card();self.click(card['token'])
        path=Path(guide['path']);path.chmod(0o600);path.write_text('Tampered')
        before=self.rt.task('demo','produce')['assignment']
        worker.tick()
        self.assertEqual(self.rt.task('demo','produce')['assignment'],before)
        self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_revisions').fetchone()[0],'failed')

    def test_revision_rolls_back_assignments_and_receipt_together(self):
        worker=self.finish_stage();card=self.revision_card();self.click(card['token'])
        before=self.rt.task('demo','produce')['assignment']
        real_put=self.state.put
        def fail(key,value):
            if key=='production-enabled:demo':raise RuntimeError('simulated crash before shared commit')
            return real_put(key,value)
        with patch.object(self.state,'put',side_effect=fail):
            with self.assertRaises(RuntimeError):worker.apply_revision()
        self.assertEqual(self.state.db.execute('SELECT status FROM production_revisions').fetchone()[0],'queued')
        self.assertEqual(self.rt.task('demo','produce')['assignment'],before)
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='telegram_revision_applied'").fetchone()[0],0)
        worker.apply_revision()
        self.assertNotEqual(self.rt.task('demo','produce')['assignment'],before)
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='telegram_revision_applied'").fetchone()[0],1)
        worker.tick();self.assertEqual(len(self.factory.calls),3)

    def test_migrated_legacy_revision_receipt_is_not_applied_twice(self):
        worker=self.finish_stage();card=self.revision_card();self.click(card['token'])
        worker.apply_revision()
        before=self.rt.task('demo','produce')['assignment']
        # This represents a pre-migration runtime commit whose relay receipt had
        # not yet caught up. The imported event is still authoritative.
        with self.state.db:self.state.db.execute("UPDATE production_revisions SET status='queued'")
        worker.apply_revision()
        self.assertEqual(self.rt.task('demo','produce')['assignment'],before)
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='telegram_revision_applied'").fetchone()[0],1)

    def test_status_question_does_not_queue_revision(self):
        self.finish_stage()
        self.message('/orchestrator What is the status of demo?',200)
        chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Awaiting review.',action=None))).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_revisions').fetchone()[0],0)
        self.assertEqual(len(self.factory.calls),2)


    def test_album_files_keep_production_focus_without_sticky_mode(self):
        self.finish_stage()
        with self.state.db:self.state.put('orchestrator_mode',False)
        reply=self.state.db.execute("SELECT message_id FROM orchestrator_messages WHERE focus='demo' LIMIT 1").fetchone()[0]
        for ident in (150,151):
            m={'message_id':ident,'media_group_id':'album','chat':{'id':7,'type':'private'},'from':{'id':7},
               'document':{'file_id':str(ident),'file_name':str(ident)+'.md','file_size':10}}
            if ident==150:m['reply_to_message']={'message_id':reply}
            self.bridge.process({'update_id':ident,'message':m})
        self.assertEqual([r[0] for r in self.state.db.execute('SELECT run FROM production_uploads')],['demo','demo'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM codex_inputs').fetchone()[0],0)

    def test_pending_or_failed_upload_cannot_be_silently_omitted(self):
        self.finish_stage();self.upload_guide()
        with self.state.db:self.state.db.execute("UPDATE production_uploads SET status='pending'")
        self.assertIsNone(self.revision_card(ident=201))
        with self.state.db:self.state.db.execute("UPDATE production_uploads SET status='failed'")
        self.assertIsNone(self.revision_card(ident=202))
        self.upload_guide(ident=153)
        self.assertIsNotNone(self.revision_card(ident=203))

    def test_exact_market_feedback_uses_production_context_and_survives_card_handoff(self):
        worker=self.finish_stage()
        original='we need to have current market analysis - what agents are there, what they do, etc'
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created,status,answer) VALUES (150,'Unrelated solver request','spellshape','gemini','test',0,'answered','No research task exists')")
        reply=self.state.db.execute("SELECT message_id FROM orchestrator_messages WHERE focus='demo' LIMIT 1").fetchone()[0]
        self.message(original,200,reply=reply)
        seen=[]
        def generate(job,payload):
            system,context=chat.model_context(payload)
            seen.append((system,context))
            return json.dumps(dict(answer='Add market analysis to preparation; fresh sources are needed.',
                action=dict(kind='revise_production',workflow='demo',items=None,direction='Add current market analysis; identify dated source requirements.')))
        chat.Worker(self.state,generate).tick();self.bridge.flush(False)
        system,context=seen[0]
        self.assertTrue(system.startswith(chat.SYSTEM))
        self.assertEqual(context['interaction'],'production_review_reply')
        self.assertEqual(context['user_message'],original)
        self.assertIn('codex_tasks',context['snapshot'])
        self.assertIn('workflows',context['snapshot'])
        self.assertFalse(any(h['prompt']=='Unrelated solver request' for h in context['history']))
        card=self.state.db.execute('SELECT * FROM orchestrator_proposals WHERE job_id=200').fetchone()
        self.click(card['token']);worker.tick()
        frozen=self.factory.sessions[self.rt.task('demo','produce')['latest']]['frozen']
        self.assertEqual(frozen['revision']['instruction'],original)

    def test_global_production_default_does_not_capture_unfocused_chat(self):
        snap=chat.snapshot(self.state,None)
        self.assertTrue(snap['production_runs'])
        payload=dict(snapshot=snap,user_message='What agents are there?',history=[])
        system,context=chat.model_context(payload)
        self.assertTrue(system.startswith(chat.SYSTEM))
        self.assertEqual(context,payload)

    def test_corrected_card_requires_its_own_complete_delivery(self):
        self.finish_stage();card=self.revision_card()
        event='orchestrator:200:correction'
        with self.state.db:
            self.state.db.execute('UPDATE orchestrator_proposals SET event_id=? WHERE job_id=200',(event,))
            self.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)',(event,'Corrected revision proposal'))
        self.click(card['token'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_revisions').fetchone()[0],0)
        self.bridge.flush(False)
        self.click(card['token'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_revisions').fetchone()[0],1)
