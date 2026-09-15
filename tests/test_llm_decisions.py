import json
import unittest

from task_relay import orchestrator_chat as chat
from tests import test_task_routing as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request

    def test_question_wording_can_discover_guides_when_model_chooses(self):
        (self.root/'card-guide.md').write_text('# Card guide\nUse concrete headlines.')
        prompt='How about following our usual approach for these?'
        self.request({'kind':'discover_guides','query':'card headlines'},prompt)
        row=self.state.db.execute('SELECT * FROM orchestrator_guide_choices').fetchone()
        self.assertEqual(row['status'],'pending')
        self.assertIn('card-guide.md',row['manifest'])
        self.assertEqual(self.state.db.execute('SELECT prompt FROM orchestrator_chats').fetchone()[0],prompt)
        self.assertEqual(self.calls,[])

    def test_work_words_do_not_force_discovery_when_model_answers(self):
        (self.root/'card-guide.md').write_text('# Card guide\nUse concrete headlines.')
        self.request(None,'Explain what "create a card draft" means.')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_guide_choices').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'answered')

    def test_empty_discovery_resumes_same_request_and_cannot_loop(self):
        prompt='Can we follow the usual approach?'
        self.request({'kind':'discover_guides','query':'unmatched topic'},prompt)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'queued')
        seen=[]
        def answer(job,payload):
            seen.append(payload)
            return json.dumps({'answer':'No guide matched; here is the requested explanation.','action':None})
        worker=chat.Worker(self.state,answer);worker.tick();worker.tick()
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0]['user_message'],prompt)
        self.assertIn('No matching guides',str(seen[0]['guide_discovery']['warnings']))
        with self.state.db:self.state.db.execute("UPDATE orchestrator_chats SET status='queued' WHERE id=1")
        worker=chat.Worker(self.state,lambda *_:json.dumps({'answer':'Again','action':{'kind':'discover_guides'}}))
        worker.tick();worker.tick()
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats').fetchone()[0],'failed')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_guide_choices').fetchone()[0],1)

    def test_catalog_is_available_regardless_of_utterance_words(self):
        snap={'focus':'video','production_runs':[{'name':'video'}],
              'codex_tasks':[{'id':'t0','title':'Writing workspace'}],
              'capabilities':{'targets':[{'id':'claude:1'}]}}
        for prompt in ['Could that go over there?', 'Почему это так?', 'We need better research.']:
            system,payload=chat.model_context({'snapshot':snap,'user_message':prompt})
            self.assertEqual(payload['snapshot'],snap)
            self.assertIn('focus supplies context, not a forced action',system)

    def test_research_selection_is_model_explicit_not_inferred(self):
        snap={'research_documents':[{'id':1},{'id':2}],
              'codex_tasks':[{'id':'t0','status':'idle'}]}
        action={'kind':'route_task','task_id':'t0'}
        with self.assertRaises(ValueError):chat.interpret(json.dumps({'answer':'Route both','action':action}),snap)
        for ids in [[],[2],[1,2]]:
            selected={**action,'research_ids':ids}
            result=chat.interpret(json.dumps({'answer':'Route','action':selected}),snap)
            self.assertEqual(result['action']['research_ids'],ids)
        with self.assertRaises(ValueError):
            chat.interpret(json.dumps({'answer':'Route','action':{**action,'research_ids':[3]}}),snap)

    def test_discovery_cannot_smuggle_execution_fields(self):
        for extra in [{'shell':'rm x'}, {'query':{'command':'run'}}, {'query':'x'*2001}]:
            with self.assertRaises(ValueError):
                chat.interpret(json.dumps({'answer':'Search','action':{'kind':'discover_guides',**extra}}),{})


if __name__=='__main__':unittest.main()
