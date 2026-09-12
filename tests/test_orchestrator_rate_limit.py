import unittest
import gemini
import orchestrator_chat as chat
from tests import test_orchestrator_chat as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    message=fixture.Tests.message

    def test_tools_question_reaches_llm_and_rate_limit_preserves_request(self):
        prompt='what tools do you have? how do you call them?'
        self.message('/orchestrator '+prompt)
        calls=[]
        def fail(job,payload):
            calls.append(payload)
            raise gemini.ProviderError(429)
        worker=chat.Worker(self.state,fail);worker.tick();worker.tick()
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(len(calls),1)
        self.assertIn('capabilities',calls[0]['snapshot'])
        self.assertEqual(row['prompt'],prompt)
        self.assertEqual(row['status'],'failed')
        self.assertIn('rate or quota',row['answer'])
        self.assertIn('exact limit or reset time',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)


if __name__=='__main__':unittest.main()
