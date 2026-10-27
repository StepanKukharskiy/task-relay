"""Workflow clocks and token accounting keep unknown fields and old attempts."""
import json
import unittest
from orchestrator.storage import transaction
from task_relay.workflow_usage import report
from task_relay import delivery_completion
from tests import test_delivery_completion as fixtures

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    stage=fixtures.Tests.stage
    step=fixtures.Tests.step
    answer=fixtures.Tests.answer
    response=fixtures.Tests.response
    action=fixtures.Tests.action
    create=fixtures.Tests.create
    complete_stage=fixtures.Tests.complete_stage

    def test_receipt_counts_do_not_add_cached_tokens_and_unknown_is_not_zero(self):
        p=self.create();run,producer,review=self.complete_stage(p,'outline')
        with transaction(self.state.db):
            for ident,value in [(producer,dict(input_tokens=100,cached_input_tokens=40,output_tokens=20)),(review,{})]:
                row=self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(ident,)).fetchone()
                receipt=json.loads(row[0]);receipt.update(usage=[value],started=100,finished=105)
                self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),ident))
        result=report(self.state,p['id'],now=p['created']+20)
        workers=[e for e in result['records'] if e['kind']=='worker']
        self.assertEqual(sum(e['counts']['input_tokens'] or 0 for e in workers),100)
        self.assertEqual(sum(e['counts']['total_tokens'] or 0 for e in workers),120)
        self.assertEqual(sum(e['counts']['cached_input_tokens'] or 0 for e in workers),40)
        self.assertEqual(result['worker_seconds_reported'],10)
        first=self.state.db.execute('SELECT created FROM orchestrator_chats WHERE id=?',(p['request_id'],)).fetchone()[0]
        self.assertEqual(result['started_at'],first)
        self.assertEqual(result['elapsed_seconds'],p['created']+20-first)
        self.assertGreater(result['totals']['input_tokens']['unknown_records'],0)
        self.assertNotIn('records',delivery_completion.ledger(self.state,p['id'])['usage'])
        self.assertEqual(report(self.state,p['id'],now=p['created']+21)['elapsed_seconds'],p['created']+21-first)
