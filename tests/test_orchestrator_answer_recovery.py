import json
import unittest
import orchestrator_chat as chat
from tests import test_orchestrator_chat as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    message=fixture.Tests.message

    def run_response(self,raw):
        self.message('/orchestrator List your tools with code examples.')
        worker=chat.Worker(self.state,lambda *_:raw)
        worker.tick();worker.tick()
        return self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=1').fetchone()

    def test_unescaped_code_examples_are_delivered_as_text_without_action(self):
        answer='Example:\n```json\n{"action":{"kind":"run","workflow":"spellshape","items":1}}\n```\nThis is an example only.'
        raw='{"answer":"'+answer+'","action":null}'
        row=self.run_response(raw)
        self.assertEqual(row['status'],'answered');self.assertEqual(row['answer'],answer)
        self.assertEqual(row['response'],raw)
        self.assertEqual(self.state.get('orchestrator-answer-recovery:1')['method'],'answer_only')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE id='orchestrator:1'").fetchone()[0],1)

    def test_literal_newlines_with_valid_escapes_retain_code(self):
        raw='{"answer":"First line\nCode: \\"name\\": \\"value\\"","action":null}'.replace('\\\\"','\\"')
        value=chat.interpret(chat.recover_answer_only(raw),{})
        self.assertEqual(value,{'answer':'First line\nCode: "name": "value"','action':None})

    def test_malformed_action_is_never_repaired_or_executed(self):
        raw='{"answer":"Two\nlines","action":{"kind":"run","workflow":"spellshape","items":1,"direction":"Run a step"}}'
        row=self.run_response(raw)
        self.assertEqual(row['status'],'failed')
        self.assertIn('provider returned an invalid response format',row['answer'])
        self.assertNotIn('rephrase',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)

    def test_valid_duplicate_fields_remain_rejected(self):
        row=self.run_response('{"answer":"one","answer":"two","action":null}')
        self.assertEqual(row['status'],'failed')
        self.assertIsNone(self.state.get('orchestrator-answer-recovery:1'))

    def test_truncated_extra_envelope_fields_and_control_bytes_are_rejected(self):
        for raw in ('{"answer":"hello\n',
                    '{"answer":"hello\nworld","extra":true,"action":null}',
                    '{"answer":"hello\u0000world","action":null}',
                    'preamble {"answer":"hello\nworld","action":null}',
                    '{"answer":"hello\nworld","action":null} trailing'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):chat.interpret(chat.recover_answer_only(raw),{})

    def test_answer_length_limit_still_applies(self):
        raw='{"answer":"'+('x'*12001)+'\n","action":null}'
        with self.assertRaises(ValueError):chat.interpret(chat.recover_answer_only(raw),{})

    def test_long_valid_code_answer_is_delivered_in_parts_once(self):
        import telegram_text
        answer='Blender script example:\n```python\n'+('print("tower")\n'*580)+'```'
        raw=json.dumps({'answer':answer,'action':None})
        row=self.run_response(raw)
        self.assertGreater(len(answer),6000)
        self.assertEqual(row['status'],'answered');self.assertEqual(row['response'],raw)
        self.telegram.sent.clear()
        self.bridge.flush(False)
        parts=self.state.db.execute("SELECT text,sent FROM outbox_parts WHERE event_id='orchestrator:1' ORDER BY part").fetchall()
        self.assertGreater(len(parts),1)
        self.assertTrue(all(p['sent'] and telegram_text.units(p['text'])<=4096 for p in parts))
        bodies=[p['text'].split('\n\n',1)[1] for p in parts]
        self.assertEqual(''.join(bodies),telegram_text.render('Orchestrator\n'+answer)[0])
        sent=len(self.telegram.sent);self.bridge.flush(False)
        self.assertEqual(len(self.telegram.sent),sent)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)

    def test_long_action_answer_is_rejected_with_specific_reason(self):
        action={'kind':'run','workflow':'spellshape','items':1,'direction':'Run one step'}
        row=self.run_response(json.dumps({'answer':'x'*6001,'action':action}))
        self.assertEqual(row['status'],'failed')
        self.assertIn('too long',row['answer']);self.assertNotIn('invalid response format',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)


if __name__=='__main__':unittest.main()
