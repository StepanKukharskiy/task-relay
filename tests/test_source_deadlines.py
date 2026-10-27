"""Original operation allowance reaches source transports without paid calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import codex_sources
from orchestrator.runtime_outcomes import Hold
from task_relay import orchestrator_web


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.backend=dict(type='codex-agent',model='fixture',reasoning='high',budget_semantics='cli-exchanges-v1')
        self.executor=dict(executable='fixture')
        self.config=dict(api_key='fixture',models=dict(text='fixture'),backend=self.backend,
                         cli_executor=self.executor,operation_deadline=1800)

    def test_persistent_transport_uses_remaining_original_allowance_and_records_it(self):
        with patch('time.time',return_value=100),patch.object(codex_sources,'configuration',return_value=(self.executor,self.backend)),patch.object(codex_sources,'Client') as client:
            client.return_value.__enter__.return_value.search.return_value=dict(sources=[],summary='Controlled result')
            codex_sources.Session(self.root/'first.json',self.config).search('fixture')
            self.assertEqual(client.call_args.args[-1],1700)
        with patch('time.time',return_value=1300),patch.object(codex_sources,'configuration',return_value=(self.executor,self.backend)),patch.object(codex_sources,'Client') as client:
            client.return_value.__enter__.return_value.search.return_value=dict(sources=[],summary='Controlled result')
            codex_sources.Session(self.root/'second.json',self.config).search('fixture2')
            self.assertEqual(client.call_args.args[-1],500)
        receipt=json.loads((self.root/'second/search-0.json').read_text())
        self.assertEqual(receipt['operation_deadline'],1800)
        self.assertEqual(receipt['transport_seconds'],500)

    def test_api_transport_keeps_its_cap_but_cannot_exceed_remaining_operation(self):
        response=dict(candidates=[dict(content=dict(parts=[]),groundingMetadata=dict(webSearchQueries=['fixture'],groundingChunks=[dict(web=dict(uri='https://example.org/source'))]))])
        for now,expected in ((100,120),(1755,45)):
            with self.subTest(now=now),patch('time.time',return_value=now),patch('task_relay.orchestrator_web.gemini.Client') as client:
                client.return_value.request.return_value=response
                orchestrator_web.Session(self.root/str(now),self.config).search('fixture')
                self.assertEqual(client.return_value.request.call_args.kwargs['timeout'],expected)

    def test_exhausted_deadline_rejects_both_providers_before_submission(self):
        for cls in (orchestrator_web.Session,codex_sources.Session):
            with self.subTest(provider=cls.__module__),patch('time.time',return_value=1801),patch.object(codex_sources,'configuration',return_value=(self.executor,self.backend)),patch.object(codex_sources,'Client') as codex,patch('task_relay.orchestrator_web.gemini.Client') as gemini:
                with self.assertRaises(Hold):cls(self.root/'expired.json',self.config).search('fixture')
                codex.assert_not_called();gemini.assert_not_called()
                self.assertFalse((self.root/'expired/search-0.json').exists())


if __name__=='__main__':unittest.main()
