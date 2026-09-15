import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge import Bridge, BridgeError
import orchestrator_chat as chat
import production_control as pc
import relay_channels as channels
from messages_orchestrator import OrchestratorRouter
from messages_pilot import Pilot, Store
from tests.test_bridge import TelegramFake
from tests import test_messages_pilot as pilot_fixtures
from tests import test_production_control as production_fixtures
from tests import test_task_routing as routing_fixtures


class Tests(unittest.TestCase):
    setUp = pilot_fixtures.Tests.setUp
    tearDown = pilot_fixtures.Tests.tearDown
    new_pilot = pilot_fixtures.Tests.new_pilot
    append = pilot_fixtures.Tests.append
    date = pilot_fixtures.Tests.date
    msg = pilot_fixtures.Tests.msg
    pair = pilot_fixtures.Tests.pair
    drain = pilot_fixtures.Tests.drain

    def router(self, ready=False):
        router = OrchestratorRouter(self.root / 'main.sqlite', require_ready=ready)
        self.addCleanup(router.close)
        self.pilot.orchestrator = router
        p = patch.object(chat, 'provider', return_value=('gemini', 'fixture'))
        p.start(); self.addCleanup(p.stop)
        return router

    def answer(self, router, text='Answer'):
        chat.Worker(router.state, lambda *_: json.dumps({'answer': text, 'action': None})).tick()

    def test_plain_text_exactly_once_explicit_commands_and_echo_filter(self):
        r = self.router(); self.pair()
        original = '  Inspect the project.\nKeep every source.  '
        self.pilot.receive(self.msg(original)); self.pilot.receive(self.msg(original))
        for i, changes in enumerate([{'is_from_me': False}, {'is_group': True}, {'chat_id': 99},
                                     {'created_at': self.date(time.time()-1000)}, {'is_reaction': True}]):
            self.pilot.receive(self.msg('Never run this', str(i), **changes))
        self.pilot.receive(self.msg('🤖 Orchestrator\n\nEcho', 'echo'))
        self.pilot.receive(self.msg('/ping', 'ping'))
        rows = r.state.db.execute('SELECT prompt FROM orchestrator_chats').fetchall()
        self.assertEqual([row[0] for row in rows], [original])
        self.pilot.receive(self.msg('/codex Direct instruction', 'codex'))
        self.assertEqual(self.desktop.starts, [('task', 'Direct instruction')])
        self.pilot.receive(self.msg('Still orchestrator', 'plain-again'))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 2)

    def test_routing_help_and_legacy_off_do_not_redirect_or_submit(self):
        r=self.router();self.pair()
        self.pilot.receive(self.msg('/routing','route-help'))
        self.pilot.receive(self.msg('/orchestrator off','old-off'))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        self.pilot.receive(self.msg('Start new research','next-research'))
        self.assertEqual(r.state.db.execute('SELECT prompt FROM orchestrator_chats').fetchone()[0],'Start new research')
        texts='\n'.join(row[0] for row in self.pilot.store.db.execute('SELECT text FROM messages_delivery'))
        self.assertIn('selecting a provider does not redirect ordinary text',texts)

    def test_bundled_template_listing_needs_no_model_or_dispatch(self):
        r=self.router();self.pair()
        self.pilot.receive(self.msg('/templates','templates-list'))
        self.pilot.receive(self.msg('/templates model-revision','templates-detail'))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        texts='\n'.join(row[0] for row in self.pilot.store.db.execute('SELECT text FROM messages_delivery'))
        self.assertIn('model-revision',texts);self.assertIn('Native model',texts)

    def test_procedure_listing_and_approval_stay_in_messages_without_a_model(self):
        from task_relay import procedures, pipelines
        from orchestrator.storage import transaction
        r=self.router();self.pair()
        scoped=channels.ScopedState(r.state,'messages')
        stage=lambda ident:dict(id=ident,instruction='Explain the sample project',route='conversation',gate='none',capabilities=[],deliverables={ident:'Explanation'})
        plan=dict(kind='plan_pipeline',title='Sample procedure',planning_only=True,stages=[stage('one'),stage('two')])
        with transaction(r.state.db):
            r.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(99,'messages'))
            pipelines.dispatch(scoped,dict(id=99,prompt='Explain the sample project in two stages',provider='gemini',model='fixture'),plan,{})
            r.state.db.execute("UPDATE relay_pipelines SET status='completed'")
            r.state.db.execute("UPDATE relay_pipeline_steps SET status='completed'")
            pid=r.state.db.execute('SELECT id FROM relay_pipelines').fetchone()[0]
            procedures.dispatch(scoped,dict(id=100,prompt='Save this'),dict(kind='draft_procedure',pipeline_id=pid,name='Study',parameters=[dict(name='subject',example='sample project')]),{})
        ident=procedures.catalog(scoped)[0]['id']
        self.pilot.receive(self.msg('/procedures','procedures-list'))
        self.pilot.receive(self.msg('/procedures approve '+ident,'procedures-approve'))
        self.pilot.receive(self.msg('/procedures approve '+ident,'procedures-approve'))
        self.assertEqual(procedures.load(scoped,ident)[0]['status'],'approved')
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        self.assertEqual(r.state.db.execute("SELECT count(*) FROM relay_procedure_events WHERE kind='approved'").fetchone()[0],1)
        self.assertEqual(procedures.catalog(r.state),[])
        texts='\n'.join(row[0] for row in self.pilot.store.db.execute('SELECT text FROM messages_delivery'))
        self.assertIn('Procedure approved',texts)

    def test_opportunities_are_channel_scoped_local_analysis_without_a_model(self):
        from task_relay import opportunities
        r=self.router();self.pair()
        self.pilot.receive(self.msg('/opportunities','wrong',chat_id=99))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM relay_opportunity_scans').fetchone()[0],0)
        self.pilot.receive(self.msg('/opportunities','opportunity-scan'))
        self.pilot.receive(self.msg('/opportunities','opportunity-scan'))
        self.pilot.receive(self.msg('/opportunities list','opportunity-list'))
        scans=r.state.db.execute('SELECT channel,request FROM relay_opportunity_scans').fetchall()
        self.assertEqual([(s['channel'],s['request']) for s in scans],[('messages','/opportunities')])
        self.assertIsNone(opportunities.latest(r.state))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        texts='\n'.join(row[0] for row in self.pilot.store.db.execute('SELECT text FROM messages_delivery'))
        self.assertIn('Automation opportunities',texts)
        self.assertIn('Local analysis only; no work started.',texts)

    def test_browser_setup_command_is_paired_and_bypasses_the_model(self):
        r=self.router();self.pair()
        self.pilot.receive(self.msg('/browser connect','wrong',chat_id=99))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0],0)
        self.pilot.receive(self.msg('/browser connect','connect'))
        self.pilot.receive(self.msg('/browser connect','connect'))
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM provider_jobs').fetchone()[0],1)
        self.assertEqual(r.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        row=r.state.db.execute('SELECT channel FROM browser_setup_requests').fetchone()
        self.assertEqual(row['channel'],'messages')

    def test_service_readiness_and_queue_cap(self):
        r = self.router(ready=True)
        with self.assertRaisesRegex(ValueError, 'offline'): r.submit('a', 'hello')
        with r.state.db:
            r.state.put('health:scan', {'last_success': time.time()})
            r.state.put('health:orchestrator-chat', {'last_success': time.time()-100, 'interface_version': 1})
        first = r.submit('a', 'hello')
        self.assertEqual(r.submit('a', 'hello'), first)
        for i in range(4): r.submit(str(i), 'more')
        with self.assertRaisesRegex(ValueError, 'Five'): r.submit('overflow', 'more')

    def test_history_and_delivery_are_separate_from_telegram(self):
        r = self.router(); self.pair(); state = r.state
        tg = TelegramFake(); bridge = Bridge(state, tg, {})
        with state.db:
            state.put('chat_id', 7); state.put('user_id', 7)
            state.db.execute("INSERT INTO orchestrator_chats(id,prompt,answer,status,provider,model,created) VALUES (1,'telegram only','old','answered','gemini','fixture',0)")
            chat.queue_notice(state, '1', 'Telegram result')
        one = r.submit('one', 'Messages first'); self.answer(r)
        two = r.submit('two', 'Messages second')
        payloads = []
        def generate(job, payload):
            payloads.append(payload)
            return json.dumps({'answer': 'second', 'action': None})
        chat.Worker(state, generate).tick()
        self.assertEqual(payloads[0]['interface'], 'messages')
        self.assertEqual([x['prompt'] for x in payloads[0]['history']], ['Messages first'])
        bridge.flush(False)
        self.assertEqual(len(tg.sent), 1)
        self.assertIn('Telegram result', tg.sent[0][1])
        r.tick(self.pilot); r.tick(self.pilot)
        event = 'orchestrator:' + str(one)
        self.assertEqual(state.db.execute('SELECT sent FROM outbox WHERE id=?', (event,)).fetchone()[0], 0)
        self.drain(); r.acknowledge(self.pilot)
        self.assertEqual(state.db.execute('SELECT sent FROM outbox WHERE id=?', (event,)).fetchone()[0], 1)
        self.assertEqual(sum('🤖 Orchestrator' in text for _, text in self.transport.sent), 2)

    def test_uncertain_part_never_acknowledges_or_retries(self):
        r = self.router(); self.pair(); self.drain()
        ident = r.submit('one', 'hello'); self.answer(r, 'Long response. ' * 600)
        r.tick(self.pilot); self.transport.fail = True
        with self.assertRaises(BridgeError): self.pilot.deliver()
        r.tick(self.pilot); self.pilot.deliver()
        self.assertEqual(len(self.transport.sent), 2)  # Pairing plus one uncertain part.
        self.assertEqual(r.state.db.execute('SELECT sent FROM outbox WHERE id=?', ('orchestrator:' + str(ident),)).fetchone()[0], 0)

    def test_held_exports_do_not_starve_new_replies_or_acknowledge_old_ones(self):
        r = self.router(); self.pair(); self.drain()
        with r.state.db, self.store.db:
            for index in range(21):
                event = 'held-' + str(index)
                r.state.db.execute('INSERT INTO outbox(id,text) VALUES (?,?)', (event, 'Original'))
                r.state.db.execute('INSERT INTO relay_event_channels VALUES (?,?)', (event, 'messages'))
                r.state.db.execute('INSERT INTO messages_orchestrator_exports VALUES (?,?,?)', (event, event, 'Original'))
                self.store.db.execute('INSERT INTO messages_delivery VALUES (?,?,?)', (event+':1', 'Original', 'uncertain'))
        ident = r.submit('fresh', 'New question')
        self.answer(r, 'Fresh answer')
        r.tick(self.pilot); self.drain(); r.acknowledge(self.pilot)
        self.assertIn('Fresh answer', self.transport.sent[-1][1])
        self.assertEqual(r.state.db.execute('SELECT sent FROM outbox WHERE id=?', ('orchestrator:'+str(ident),)).fetchone()[0], 1)
        self.assertEqual(r.state.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'held-%' AND sent=0").fetchone()[0], 21)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM messages_delivery WHERE status='uncertain'").fetchone()[0], 21)

    def test_current_task_final_only_delivered_once_in_either_order(self):
        r = self.router(); self.pair(); self.drain()
        for first in ('pilot', 'shared'):
            with r.state.db:
                channels.bind(r.state, 'task', 'task', 'messages')
                r.state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                   (f'task:{first}:task_complete', 'task', 'Shared final'))
            self.append('task_complete', first)
            if first == 'pilot': self.pilot.scan()
            r.tick(self.pilot); self.pilot.scan(); self.drain(); r.acknowledge(self.pilot)
            self.assertEqual(self.store.db.execute('SELECT count(*) FROM messages_delivery WHERE id=?', (f'{first}:task_complete:1',)).fetchone()[0], 1)
        self.assertEqual(len(self.transport.sent), 3)

    def test_prior_outputs_keep_channel_after_ownership_changes(self):
        r = self.router(); s = r.state
        with s.db:
            channels.bind(s, 'task', 'task', 'messages')
            s.db.execute("INSERT INTO outbox(id,thread_id,text) VALUES ('old','task','old')")
            channels.bind(s, 'task', 'task', 'telegram')
            s.db.execute("INSERT INTO outbox(id,thread_id,text) VALUES ('new','task','new')")
        self.assertEqual(channels.event_channel(s, 'old'), 'messages')
        self.assertEqual(channels.event_channel(s, 'new'), 'telegram')


class ProductionChoices(unittest.TestCase):
    setUp = production_fixtures.Tests.setUp
    tearDown = production_fixtures.Tests.tearDown

    def test_delivery_binding_status_and_apply_stay_in_messages(self):
        root = Path(self.temp.name)
        r = OrchestratorRouter(root / 'state.sqlite', require_ready=False)
        store = Store(root / 'pilot.sqlite')
        self.addCleanup(r.close); self.addCleanup(store.db.close)
        pilot = Pilot(store, pilot_fixtures.Transport(), 'unused', orchestrator=r)
        with store.db: store.put('chat', {'id': 42, 'guid': 'any;-;self'})
        ident = r.submit('start', 'Start the demo preparation stage')
        action = dict(kind='start_production', workflow='demo', items=None, direction='')
        chat.Worker(r.state, lambda *_: json.dumps(dict(answer='Preparation only.', action=action))).tick()
        r.tick(pilot)
        card = r.state.db.execute('SELECT * FROM messages_orchestrator_cards').fetchone()
        options = json.loads(card['options'])
        status_index = next(i for i, b in enumerate(options, 1) if b['callback_data'].startswith('prodstatus:'))
        apply_index = next(i for i, b in enumerate(options, 1) if b['callback_data'].startswith('orch:apply:'))
        with self.assertRaisesRegex(ValueError, 'complete'): r.choose(pilot, 'early', card['code'] + f' {apply_index}')
        for _ in range(15): pilot.deliver()
        r.choose(pilot, 'status', card['code'] + f' {status_index}')
        statuses = r.state.db.execute("SELECT id,text FROM outbox WHERE id LIKE 'production:demo:status:%'").fetchall()
        self.assertEqual(len(statuses), 1)
        self.assertIn('Queued; scheduling is off', statuses[0]['text'])
        self.assertEqual(channels.event_channel(r.state, statuses[0]['id']), 'messages')
        r.choose(pilot, 'apply', card['code'] + f' {apply_index}')
        self.assertTrue(r.state.get('production-enabled:demo'))
        with self.assertRaisesRegex(ValueError, 'handled'): r.choose(pilot, 'apply-again', card['code'] + f' {apply_index}')
        with r.state.db: pc.notice(r.state, 'demo', 'future', 'Future progress')
        self.assertEqual(channels.event_channel(r.state, 'production:demo:future'), 'messages')


class TaskDispatch(unittest.TestCase):
    setUp = routing_fixtures.Tests.setUp
    tearDown = routing_fixtures.Tests.tearDown

    def test_existing_worker_dispatch_and_result_use_messages_origin(self):
        r = OrchestratorRouter(self.root / 'state.sqlite', require_ready=False)
        self.addCleanup(r.close)
        original = 'Use Codex to inspect the video sources.\nDo not render.  '
        ident = r.submit('route', original)
        chat.Worker(r.state, lambda *_: json.dumps({'answer': 'selected', 'action': {'kind': 'route_task', 'task_id': 't0'}})).tick()
        self.worker.tick(); self.worker.tick()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][1].endswith(original))
        self.bridge.flush(False)
        self.assertEqual(self.telegram.sent, [])
        self.assertEqual(channels.event_channel(self.state, f'routed:{ident}:result'), 'messages')
        with self.state.db:
            self.state.db.execute("INSERT INTO outbox(id,thread_id,text) VALUES ('t0:turn:task_complete','t0','Done')")
        self.assertEqual(channels.event_channel(self.state, 't0:turn:task_complete'), 'messages')


if __name__ == '__main__':
    unittest.main()
