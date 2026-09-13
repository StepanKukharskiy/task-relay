"""Bounded projection, exact retrieval and tamper rejection without model calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay import context_handoff as context, api_providers as api
from tests import test_api_providers as fixtures


class ArchiveTests(unittest.TestCase):
    def test_projection_retains_requests_and_can_retrieve_omitted_response(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'turn.context.json'
            turns=[{'request':'Keep the courtyard. Do not accept yet.','response':'old evidence '*500},
                   {'request':'Use version 2 exactly.','response':'current draft'}]
            result=context.fit(turns,lambda text:{'prompt':text,'current':'Only revise the roof'},2000,path,provider='test',can_read=True)
            self.assertIn(turns[0]['request'],result['prompt']);self.assertIn('current draft',result['prompt'])
            receipt=json.loads(path.read_text());self.assertEqual(receipt['omitted_responses'],[0])
            answer=context.read(path,{'turn':0,'field':'response','offset':10,'limit':90})
            self.assertEqual(answer['text'],turns[0]['response'][10:100])
            archive=Path(receipt['archive']['path']);archive.write_text('tampered')
            self.assertFalse(context.read(path,{'turn':0,'field':'response','offset':0,'limit':5})['ok'])

    def test_instructions_never_trimmed_and_no_archive_on_failed_fit(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'turn.context.json'
            with self.assertRaisesRegex(ValueError,'no history was deleted'):
                context.fit([{'request':'constraint '*500,'response':'answer'}],lambda text:{'prompt':text},1000,path,provider='test',can_read=True)
            self.assertFalse(path.exists())

    def test_no_response_omission_without_retrieval_tool(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                context.fit([{'request':'x','response':'z'*5000}],lambda text:{'prompt':text},1000,Path(root)/'c.json',provider='image')


class APIIntegrationTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    create=fixtures.Tests.create
    send=fixtures.Tests.send
    queue=fixtures.Tests.queue

    def test_archive_read_runs_through_normal_tool_receipts(self):
        from task_relay import backends, api_runner
        from unittest.mock import Mock
        tid,job=self.queue('openai')
        with self.state.db:
            self.state.db.execute('INSERT INTO api_history VALUES (?,?,?,?,?)',
                ('old-result',tid,'Keep the exact facade.','retained evidence '*3000,1))
        with patch.object(api,'MAX_CONTEXT',12000):
            prepared=api.prepare_run(self.state,job['id'],backends.task(self.state,tid),job['prompt'])
            with self.state.db:self.state.db.execute('UPDATE api_runs SET request_json=? WHERE job_id=?',(prepared[-1],job['id']))
            client=Mock();client.request.side_effect=[fixtures.tool_response('openai','context_read',
                {'turn':0,'field':'response','offset':0,'limit':30}),fixtures.response('openai','Used the retained evidence.')]
            api_runner.run_job(self.state,job['id'],client=client)
        status=self.state.db.execute('SELECT status FROM backend_jobs WHERE id=?',(job['id'],)).fetchone()[0]
        self.assertEqual(status,'completed')
        tool=json.loads(self.state.db.execute('SELECT result_json FROM api_tool_calls WHERE job_id=?',(job['id'],)).fetchone()[0])
        self.assertEqual(tool['text'],('retained evidence '*3000)[:30])
        self.assertEqual(client.request.call_count,2)

    def test_every_direct_text_adapter_uses_same_archive_without_changing_model(self):
        from task_relay import backends
        for provider in api.SPECS:
            with self.subTest(provider=provider):
                tid=self.create(provider)
                with self.state.db:
                    self.state.db.execute('INSERT INTO api_history VALUES (?,?,?,?,?)',
                        (provider+'-old',tid,'Preserve this exact decision.','Earlier result '*3000,1))
                info=backends.task(self.state,tid)
                with patch.object(api,'MAX_CONTEXT',12000):
                    prepared=api.prepare_run(self.state,provider+'-new',info,'Read the earlier result before editing.')
                payload=json.loads(prepared[-1]);self.assertEqual(payload['model'],info['model'])
                self.assertIn('context_read',prepared[-1]);self.assertIn('Preserve this exact decision.',prepared[-1])
                receipt=Path(prepared[3]).with_suffix('.context.json')
                found=context.read(receipt,{'turn':0,'field':'response','offset':0,'limit':20})
                self.assertTrue(found['ok']);self.assertEqual(found['text'],('Earlier result '*3000)[:20])
