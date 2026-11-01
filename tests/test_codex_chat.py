"""Chat intake/read/answer over real local protocol pipes; no model or network."""
import json
from pathlib import Path
from contextlib import closing, nullcontext
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.codex_transport import Client, POLICY, Failure
from task_relay import codex_chat, credentials, capability_defaults, orchestrator_files as files
from task_relay import orchestrator_advice as advice, request_contract
from task_relay.relay_paths import Paths
from tests.intake_fixtures import ANSWER


class Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.paths = Paths(self.root, self.root/'data', self.root/'work', self.root/'generated')
        self.receipt = self.root/'read.json'
        self.backend = dict(type='codex-agent', model='fixture', reasoning='high', budget_semantics=POLICY)

    def invoke(self, steps):
        script = self.root/'script.json'; script.write_text(json.dumps(steps))
        command = [sys.executable, '-B', str(Path(__file__).with_name('codex_protocol_fixture.py')), str(script), 'chatgpt', 'strict']
        with Client({}, self.backend, self.root/'wire', 10, command=command) as client:
            return files.run('codex', client, 'chat/completions',
                dict(model='fixture', messages=[dict(role='system', content='Use Relay tools.'), dict(role='user', content='Read status.txt')]),
                [str(self.root)], self.receipt, response_definition=advice.response_definition('Read status.txt', []),
                intake_definition=request_contract.definition())

    def test_intake_read_answer_share_one_thread_and_retain_exact_receipts(self):
        (self.root/'status.txt').write_text('The fixture is ready.')
        answer = dict(answer='The fixture is ready.', action_json=None, next_options=[], claim_sources=[],
                      work_status='respond', answer_basis='supplied_context',
                      research_advice=dict(recommended_mode='none', requirement='unnecessary', reason='Local status.', questions=[]))
        definition = advice.response_definition('Read status.txt', [])
        result = self.invoke([('relay_intake', ANSWER), ('file_read', dict(project=str(self.root),path='status.txt',offset=0,limit=1000)),
                              (definition['name'], answer)])
        self.assertEqual(json.loads(result)['answer'], answer['answer'])
        journal = json.loads(self.receipt.read_text())
        self.assertEqual(len(journal), 3)
        self.assertIn('The fixture is ready.', str(journal[1]['reads']))
        sent = [json.loads(x) for x in (self.root/'wire/codex-sent.jsonl').read_text().splitlines()]
        self.assertEqual(sum(x.get('method')=='thread/start' for x in sent), 1)
        replies = [x for x in sent if 'result' in x]
        self.assertEqual([x['id'] for x in replies], [101,102])
        self.assertIn('frozen', replies[0]['result']['contentItems'][0]['text'])
        self.assertNotIn('fixture-private-account', (self.root/'wire/codex-events.jsonl').read_text())
        self.assertIsNone(json.loads((self.root/'wire/codex-usage.json').read_text())['provider_requests'])

    def test_read_before_intake_is_rejected_without_file_access(self):
        with patch.object(files, 'execute') as execute, self.assertRaises(files.IntakeError):
            self.invoke([('file_read', dict(project=str(self.root),path='status.txt',offset=0,limit=100))])
        execute.assert_not_called()
        self.assertEqual(len(json.loads(self.receipt.read_text())), 1)

    def test_missing_reply_is_not_retried(self):
        with self.assertRaises(Failure) as failure: self.invoke([dict(disconnect=True)])
        self.assertTrue(failure.exception.uncertain)
        journal = json.loads(self.receipt.read_text())
        self.assertEqual(len(journal), 1); self.assertNotIn('response', journal[0])

    def test_selection_needs_qualified_runtime_and_saves_no_credentials(self):
        with patch('orchestrator.codex_transport.configuration', side_effect=ValueError('Unqualified')):
            with self.assertRaisesRegex(ValueError, 'Unqualified'): codex_chat.select(paths=self.paths)
        self.assertFalse(self.paths.data.exists())
        self.paths.data.mkdir()
        with closing(sqlite3.connect(self.paths.state)) as db, db:
            db.execute('CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO kv VALUES (?,?)', ('orchestrator_provider', '"gemini"'))
        with patch('orchestrator.codex_transport.configuration', return_value=({}, self.backend)):
            codex_chat.select('fixture', self.paths)
        self.assertEqual(codex_chat.read_config(self.paths), dict(version=1, model='fixture'))
        with closing(sqlite3.connect(self.paths.state)) as db, db:
            self.assertEqual(db.execute('SELECT value FROM kv').fetchone()[0], '"codex"')
        text = capability_defaults.snapshot(self.paths)['capabilities'][0]
        self.assertEqual(text['selected'], dict(provider='codex', model='fixture'))
        capability_defaults.update(dict(revision=0, capability='text', provider='codex', model='gpt-6-sol'), self.paths)
        self.assertEqual(codex_chat.read_config(self.paths)['model'], 'gpt-6-sol')
        self.assertEqual(set(json.loads((self.paths.data/'codex-chat.json').read_text())), {'version','model'})

    def test_existing_transport_receipt_never_reopens(self):
        self.receipt.with_suffix('.codex').mkdir()
        with patch('orchestrator.codex_transport.configuration', return_value=({}, self.backend)), patch('orchestrator.codex_transport.Client') as client:
            with self.assertRaisesRegex(ValueError, 'already has an execution receipt'):
                with codex_chat.client('fixture', self.receipt): pass
        client.assert_not_called()

    def test_chat_dispatch_uses_codex_and_never_reads_an_api_key(self):
        from task_relay import orchestrator_chat as chat
        from unittest.mock import Mock
        transport = Mock()
        with patch.object(chat.codex_chat, 'read_config', return_value={'model':'fixture'}), \
             patch.object(chat.codex_chat, 'client', return_value=nullcontext(transport)) as create, \
             patch.object(chat.gemini, 'read_config', side_effect=AssertionError('No API key needed')), \
             patch.object(chat.api, 'Client', side_effect=AssertionError('No API billing fallback')), \
             patch.object(chat.gemini, 'DATA', self.root), \
             patch.object(files, 'run', return_value='saved response') as run, \
             patch.object(advice, 'validate', return_value='validated response'):
            result = chat.generate(dict(id='codex-chat', provider='codex', model='fixture'), dict(user_message='What is saved?'))
        self.assertEqual(result, 'validated response')
        self.assertEqual(create.call_args.args[0], 'fixture')
        self.assertEqual(run.call_args.args[:3], ('codex', transport, 'chat/completions'))
        offered = run.call_args.args[6].definitions()
        self.assertFalse(any(tool['name']=='web_search' for tool in offered))
