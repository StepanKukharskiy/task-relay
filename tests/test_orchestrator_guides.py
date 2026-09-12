import json
from pathlib import Path
import unittest
from unittest.mock import patch

import orchestrator_chat as chat
import orchestrator_guides as guides
from tests import test_task_routing as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown

    def start(self,prompt='Create a set of LinkedIn cards.',action=None,discover=True):
        folder=self.root/'Content';folder.mkdir(exist_ok=True)
        (folder/'linkedin-card-guide.md').write_text('# LinkedIn cards\nOne concrete idea per card. Avoid hype.')
        self.tasks[1]['cwd']=str(folder)
        self.seen=[]
        def generate(job,payload):
            self.seen.append(payload)
            return json.dumps({'answer':'Find guides first.' if len(self.seen)==1 and discover else 'Card 1: The concrete idea.',
                               'action':{'kind':'discover_guides'} if len(self.seen)==1 and discover else action})
        self.chat_worker=chat.Worker(self.state,generate)
        self.bridge.process({'update_id':1,'message':{'text':'/orchestrator '+prompt,'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        self.chat_worker.tick()

    def choose(self,action='all',user=7):
        row=self.state.db.execute('SELECT * FROM orchestrator_guide_choices').fetchone()
        self.bridge.process({'update_id':98,'callback_query':{'id':'g','data':'guides:'+row['token']+':'+action,'from':{'id':user},'message':{'chat':{'id':7,'type':'private'}}}})

    def test_cross_project_discovery_then_direct_draft_without_codex(self):
        self.start()
        self.assertEqual(len(self.seen),1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)
        self.bridge.flush(False);self.choose();self.chat_worker.tick()
        self.assertEqual(len(self.seen),2)
        context=self.seen[-1]['approved_guides']
        self.assertIn('Avoid hype',context[0]['text'])
        self.assertIn('/Content/',context[0]['source'])
        self.assertEqual(self.seen[0]['user_message'],'Create a set of LinkedIn cards.')
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'answered')
        self.assertEqual(self.calls,[])

    def test_skip_preserves_request_and_does_not_apply_guide(self):
        self.start();self.bridge.flush(False);self.choose('skip');self.chat_worker.tick()
        self.assertEqual(self.seen[-1]['approved_guides'],[])
        self.assertEqual(self.seen[0]['user_message'],'Create a set of LinkedIn cards.')

    def test_auth_delivery_expiry_and_duplicates(self):
        self.start();self.choose();self.chat_worker.tick();self.assertEqual(len(self.seen),1)
        self.bridge.flush(False);self.choose(user=8);self.chat_worker.tick();self.assertEqual(len(self.seen),1)
        with self.state.db:self.state.db.execute('UPDATE orchestrator_guide_choices SET expires=0')
        self.choose();self.chat_worker.tick();self.assertEqual(len(self.seen),1)
        with self.state.db:self.state.db.execute('UPDATE orchestrator_guide_choices SET expires=9999999999')
        self.choose();self.choose();self.chat_worker.tick();self.chat_worker.tick()
        self.assertEqual(len(self.seen),2)

    def test_cancel_does_not_resume_provider_or_launch_work(self):
        self.start();self.bridge.flush(False);self.choose('cancel');self.chat_worker.tick()
        self.assertEqual(len(self.seen),1)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'cancelled')

    def test_saved_guide_version_and_tamper_guard(self):
        self.start();self.bridge.flush(False)
        row=self.state.db.execute('SELECT * FROM orchestrator_guide_choices').fetchone()
        record=json.loads(row['manifest'])[0]
        Path(record['source']).write_text('Changed since the offer')
        self.choose()
        self.assertIn('Avoid hype',guides.context(self.state,1)[0]['text'])
        path=Path(record['path']);path.chmod(0o600);path.write_text('Tampered snapshot')
        self.chat_worker.tick();self.assertEqual(len(self.seen),1)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'failed')

    def test_guides_survive_focused_production_payload_filter(self):
        self.start();self.bridge.flush(False);self.choose();self.chat_worker.tick()
        payload=self.seen[-1]
        payload['snapshot']['focus']='example'
        payload['snapshot']['production_runs']=[{'name':'example'}]
        _,filtered=chat.model_context(payload)
        self.assertEqual(filtered['approved_guides'],payload['approved_guides'])

    def test_codex_handoff_uses_same_selection_without_second_gate(self):
        self.start(action={'kind':'route_task','task_id':'t0'})
        self.bridge.flush(False);self.choose();self.chat_worker.tick()
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone()
        self.assertEqual(row['status'],'queued')
        self.worker.tick()
        self.assertIn('linkedin-card-guide.md',self.calls[0][1])
        self.assertEqual(self.calls[0][0],'t0')

    def test_status_question_does_not_start_guide_discovery(self):
        self.start('Why did my LinkedIn card update fail?',discover=False)
        self.assertEqual(len(self.seen),1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_guide_choices').fetchone()[0],0)

    def test_managed_agent_project_is_discoverable_without_codex_or_dispatch_enabled(self):
        (self.root/'card-guide.md').write_text('# Card guide\nUse concrete card titles.')
        self.tasks.clear()
        with self.state.db:
            self.state.put('orchestrator_routing_enabled',False)
            self.state.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,0)',('openai:cards','openai','session',str(self.root),'test'))
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,provider,model,created) VALUES (1,?,?,?,0)',('Create card text','gemini','test'))
        job=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        payload={'snapshot':{},'user_message':job['prompt']}
        self.assertTrue(guides.discover(self.state,job,payload))
        self.bridge.flush(False);self.choose()
        self.assertFalse(guides.preflight(self.state,job,payload))
        self.assertIn(str(self.root),payload['snapshot']['project_roadmaps']['available_projects'])
        self.assertIn('Use concrete',payload['approved_guides'][0]['text'])


from tests import test_production_control as production_fixture
import production_control as pc


class ProductionTests(unittest.TestCase):
    setUp=production_fixture.Tests.setUp
    tearDown=production_fixture.Tests.tearDown
    message=production_fixture.Tests.message
    click=production_fixture.Tests.click
    worker=production_fixture.Tests.worker
    stage_card=production_fixture.Tests.stage_card
    finish_stage=production_fixture.Tests.finish_stage
    blocked_revision=production_fixture.Tests.blocked_revision

    def prepare_choice(self,kind):
        root=Path(self.temp.name).resolve()
        (root/'card-guide.md').write_text('# Card guide\nOne concrete idea per card.')
        self.message('/orchestrator Update the cards using my guide.',201)
        action=dict(kind=kind,workflow='demo',items=None,direction='' if kind=='start_production' else 'Update the cards')
        decisions=iter([{'kind':'discover_guides'},action])
        worker=chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Updating.',action=next(decisions))))
        with patch('project_roadmaps.context',return_value={'available_projects':[str(root)]}):worker.tick()
        self.bridge.flush(False)
        row=self.state.db.execute('SELECT * FROM orchestrator_guide_choices WHERE job_id=201').fetchone()
        self.assertIsNotNone(row)
        self.bridge.process({'update_id':202,'callback_query':{'id':'guides','data':'guides:'+row['token']+':all','from':{'id':7},'message':{'chat':{'id':7,'type':'private'}}}})
        worker.tick();self.bridge.flush(False)

    def check_workers(self,run):
        for tid in ('produce','review'):
            inputs=self.rt.spec(self.rt.task(run,tid))['inputs']
            bodies=[Path(self.rt.artifact(i['artifact'])['blob']).read_text() for i in inputs if i.get('artifact')]
            self.assertTrue(any('One concrete idea per card.' in b for b in bodies),tid)

    def test_discovered_guide_reaches_production_revision_and_review(self):
        worker=self.finish_stage()
        self.prepare_choice('revise_production')
        card=self.state.db.execute('SELECT * FROM orchestrator_proposals WHERE job_id=201').fetchone()
        self.assertIsNotNone(card)
        self.click(card['token']);worker.tick()
        self.assertEqual(self.state.db.execute('SELECT status FROM production_revisions WHERE id=201').fetchone()[0],'applied')
        self.check_workers('demo')

    def test_discovered_guide_reaches_continuation_producer_and_review(self):
        self.blocked_revision()
        self.prepare_choice('continue_production')
        row=self.state.db.execute('SELECT * FROM production_continuations WHERE id=201').fetchone()
        self.assertIsNotNone(row)
        self.worker().tick()
        self.check_workers(row['child'])

    def test_new_guide_cannot_silently_change_frozen_start_contract(self):
        self.prepare_choice('start_production')
        row=self.state.db.execute('SELECT status,answer FROM orchestrator_chats WHERE id=201').fetchone()
        self.assertEqual(row['status'],'failed')
        self.assertIn('frozen production stage',row['answer'])
        self.assertEqual(self.factory.calls,[])


if __name__=='__main__':unittest.main()
