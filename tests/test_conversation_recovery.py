"""Saved direct text recovery is exact, idempotent and never dispatches work."""
import json
from pathlib import Path
import unittest

from task_relay import conversation_recovery as recovery
from tests import test_orchestrator_chat as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown

    def saved(self,raw=None):
        answer=''.join(f'## Article {i}: Topic {i}\n'+('Example text. '*220)+'\n```python\nprint(1)\n```\n' for i in range(1,6))
        raw=raw or json.dumps({'answer':answer,'action_json':None})
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,status,created,response,snapshot,answer) VALUES (99,?,'gemini','fixture','failed',1,?,'{}','Old size failure')",
                                  ('Please create drafts in md for all 5 articles with code snippets',raw))
            self.state.db.execute("INSERT INTO orchestrator_chat_errors VALUES (99,'provider','AdviceError','Old size limit',1)")
        database=Path(self.state.db.execute('PRAGMA database_list').fetchone()[2])
        return database,raw

    def test_failed_long_response_exports_five_articles_without_changing_receipts(self):
        database,raw=self.saved();destination=Path(self.temp.name)/'recovered'
        before=dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=99').fetchone())
        result=recovery.recover(database,99,destination)
        self.assertEqual((destination/'provider-response.json').read_text(),raw)
        self.assertEqual((destination/'answer.md').read_text(),json.loads(raw)['answer'])
        self.assertEqual(len(result['article_files']),5)
        self.assertEqual(result['provider_calls'],0);self.assertEqual(result['dispatched_actions'],0)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=99').fetchone()),before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT message FROM orchestrator_chat_errors WHERE job_id=99').fetchone()[0],'Old size limit')
        self.assertEqual(recovery.recover(database,99,destination),result)
        (destination/'article-05.md').unlink()
        recovery.recover(database,99,destination)
        self.assertTrue((destination/'article-05.md').is_file())

    def test_recovery_cannot_execute_actions_or_repair_duplicate_truncated_json(self):
        for raw in ('{"answer":"Draft","action":{"kind":"run"}}',
                    '{"answer":"one","answer":"two","action":null}',
                    '{"answer":"unfinished'):
            with self.subTest(raw=raw):
                database,_=self.saved(raw)
                destination=Path(self.temp.name)/'refused'
                with self.assertRaises(ValueError):recovery.recover(database,99,destination)
                self.assertFalse(destination.exists())
                with self.state.db:
                    self.state.db.execute('DELETE FROM orchestrator_chats WHERE id=99')
                    self.state.db.execute('DELETE FROM orchestrator_chat_errors WHERE job_id=99')

    def test_edited_recovery_files_are_never_overwritten(self):
        database,raw=self.saved();destination=Path(self.temp.name)/'recovered'
        recovery.recover(database,99,destination)
        (destination/'answer.md').write_text('User edits')
        (destination/'article-05.md').unlink()
        with self.assertRaisesRegex(ValueError,'different bytes'):recovery.recover(database,99,destination)
        self.assertEqual((destination/'answer.md').read_text(),'User edits')
        self.assertFalse((destination/'article-05.md').exists())

    def test_inline_routing_failure_can_export_unreviewed_text_without_fulfilling_the_contract(self):
        from tests.intake_fixtures import work,outcome
        contract=work([outcome(count=5)])
        database,raw=self.saved(json.dumps({'answer':'Useful but unreviewed inline draft.','action':None,'request_contract':contract}))
        destination=Path(self.temp.name)/'routing-failure'
        result=recovery.recover(database,99,destination)
        self.assertEqual(result['request_contract'],contract)
        self.assertFalse(result['request_fulfilled'])
        self.assertEqual((destination/'answer.md').read_text(),'Useful but unreviewed inline draft.')
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=99').fetchone()[0],'failed')
        self.assertEqual(result['provider_calls'],0);self.assertEqual(result['dispatched_actions'],0)
