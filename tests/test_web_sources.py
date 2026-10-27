"""Controlled public-source collection and production recovery checks."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import execution
from orchestrator.adapters import ExecutionFactory, RegisteredFactory
from orchestrator.runtime import Runtime
from orchestrator.step_runner import execute
from orchestrator.workers import atomic
from orchestrator import web_sources
from task_relay import gemini, orchestrator_web
from tests.test_orchestrator import FakeFactory, plan


CONFIG = {'api_key': 'fixture', 'models': {'text': 'fixture-text'}}


class FakeSession:
    calls = []
    error = None

    def __init__(self, receipt, config):
        self.receipt = Path(receipt)
        self.receipt.parent.mkdir(parents=True, exist_ok=True)

    def search(self, query):
        self.calls.append(('search', query))
        if self.error:
            self.receipt.with_suffix('').mkdir(parents=True, exist_ok=True)
            atomic(self.receipt.with_suffix('') / 'search-0.json',
                   {'query': query, 'status': 'uncertain'})
            raise self.error
        return {'sources': [{'url': 'https://parts.example.com/abc', 'title': 'Part ABC'},
                            {'url': 'https://other.example.org/abc', 'title': 'Other'}],
                'queries': [query], 'retrieved_at': 123.0}

    def fetch(self, url, offset, limit, allowed_hosts=None):
        self.calls.append(('fetch', url))
        return {'url': url, 'requested_url': url, 'title': 'Part ABC',
                'text': 'ABC-9182: stainless steel', 'retrieved_at': 124.0,
                'sha256': 'a' * 64, 'content_type': 'text/html',
                'total_characters': 25, 'next_offset': None}


def assignment():
    spec = execution.REGISTRY['web.sources']
    return {'id': 'sources', 'role': 'research', 'objective': 'Collect public part sources',
            'instruction': 'Find source candidates for the exact article.',
            'execution': {'capability': 'web.sources', 'version': 1,
                          'parameters': {'queries': ['ABC-9182 OEM material'],
                                         'domains': ['example.com'], 'model': 'fixture-text'}},
            'inputs': [], 'outputs': [{'path': 'delivery/source-pack.json',
                                      'purpose': 'Public source candidates',
                                      'media_type': 'application/json'}],
            'dependencies': [], 'criteria': copy.deepcopy(spec['criteria'])}


class SourceFactory(RegisteredFactory):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def submit(self, session):
        self.calls += 1
        control = Path(session['control'])
        (control / 'supervisor.claim').write_text('fixture')
        launch = json.loads((control / 'launch.json').read_text())
        workspace = Path(launch['workspace'])
        frozen = json.loads((workspace / '.relay/ASSIGNMENT.json').read_text())
        code = 0
        try:
            with patch.object(orchestrator_web, 'Session', FakeSession), \
                 patch.object(orchestrator_web, 'public_url', side_effect=lambda url: url):
                execute(frozen, control, config_reader=lambda: CONFIG)
        except Exception:
            code = 1
        atomic(control / 'done.json', {'token': session['id'], 'exit_code': code,
                                       'reason': None, 'usage': [{}], 'tool_calls': 0})
        return {'submitted': True, 'fixture': True}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = patch.object(gemini, 'read_config', return_value=CONFIG)
        self.config.start()
        FakeSession.calls = []
        FakeSession.error = None

    def tearDown(self):
        FakeSession.error = None
        self.config.stop()
        self.temp.cleanup()

    def test_completed_observation_survives_failed_generation_with_error_provenance(self):
        from orchestrator.observation_outcomes import retained_reads
        outcome=retained_reads(dict(id='turn',status='failed',error=dict(message='Provider unavailable')),['read'],[])
        class Observed(FakeSession):
            def search(self,query):
                return dict(super().search(query),observation_outcome=outcome)
        raw,counts=web_sources.collect(['ABC-9182 OEM material'],['example.com'],'fixture-text',Path(self.temp.name),CONFIG,session_factory=Observed)
        entry=json.loads(raw)['entries'][0]
        self.assertEqual(entry['observation_outcome'],outcome)
        self.assertEqual(counts['fetched'],1)
        self.assertEqual(FakeSession.calls,[('search','ABC-9182 OEM material'),('fetch','https://parts.example.com/abc')])
        self.assertFalse(entry['observation_outcome']['acceptance'])

    def test_bounded_source_pack_has_exact_query_domain_and_page_hash(self):
        with patch.object(orchestrator_web, 'Session', FakeSession), \
             patch.object(orchestrator_web, 'public_url', side_effect=lambda url: url):
            raw, counts = web_sources.collect(['ABC-9182 OEM material'], ['example.com'],
                                              'fixture-text', Path(self.temp.name), CONFIG)
        pack = json.loads(raw)
        self.assertEqual(counts, {'queries': 1, 'grounded': 1, 'fetched': 1, 'unresolved': 0})
        self.assertEqual(pack['entries'][0]['pages'][0]['sha256'], 'a' * 64)
        self.assertEqual(pack['entries'][0]['grounding'],
                         [{'url': 'https://parts.example.com/abc', 'title': 'Part ABC'}])
        self.assertEqual(FakeSession.calls, [('search', 'ABC-9182 OEM material'),
                                             ('fetch', 'https://parts.example.com/abc')])
        self.assertIn('not verified facts', pack['interpretation'])

    def test_repeated_pages_are_reused_and_variants_and_target_mappings_survive(self):
        class RepeatedSession(FakeSession):
            def search(self,query):
                self.calls.append(('search',query))
                return dict(queries=[query],retrieved_at=123,sources=[
                    dict(url='https://parts.example.com/chair?variant=red&utm_source='+query,title='Red chair'),
                    dict(url='https://parts.example.com/chair?variant=red&utm_source=duplicate',title='Repeated red chair'),
                    dict(url='https://parts.example.com/chair?variant=blue',title='Blue chair')])
        data=dict(version=1,targets=[dict(id='item-1',queries=['first'],required_options=3),dict(id='item-2',queries=['second'],required_options=3)])
        with patch.object(orchestrator_web,'Session',RepeatedSession),patch.object(orchestrator_web,'public_url',side_effect=lambda url:url):
            raw,_=web_sources.collect(['first','second'],['example.com'],'fixture-text',self.temp.name,CONFIG,
                                     prepared_spec=dict(path='queries.json',sha256='a'*64,data=data))
        pack=json.loads(raw);index=pack['mechanical']
        self.assertEqual(len([c for c in FakeSession.calls if c[0]=='fetch']),2)
        self.assertEqual(len([c for c in FakeSession.calls if c[0]=='search']),2)
        self.assertEqual(index['counts'],dict(observations=4,distinct_urls=2,distinct_captures=2,exact_repeats=2))
        self.assertEqual([e['target_ids'] for e in pack['entries']],[['item-1'],['item-2']])
        self.assertEqual([len(e['grounding']) for e in pack['entries']],[3,3])
        self.assertEqual(pack['entries'][1]['pages'][0]['reused_from'],'entries[0].pages[0]')
        self.assertEqual(pack['entries'][1]['pages'][0]['retrieved_at'],124)
        self.assertEqual([t['fetched_page_count'] for t in index['targets']],[2,2])
        self.assertEqual(index['page_groups'][0]['target_ids'],['item-1','item-2'])
        # Shared content is a warning, not proof that red and blue are one product.
        self.assertEqual(len(index['repeated_text'][0]),4)

    def test_page_index_keeps_changed_versions_and_unknown_url_parameters(self):
        original=dict(url='https://retailer.example/product?sku=1',sha256='a'*64,text='Price 10')
        changed=dict(original,sha256='b'*64,text='Price 20')
        index=web_sources.mechanical_index(dict(entries=[dict(pages=[original,changed],target_ids=['item-1'])]))
        self.assertEqual(index['counts']['distinct_urls'],1)
        self.assertEqual(index['counts']['distinct_captures'],2)
        self.assertEqual(index['counts']['exact_repeats'],0)
        self.assertIsNone(index['observations'][1]['duplicate_of'])
        self.assertNotEqual(web_sources.page_identity('https://retailer.example/p?sku=1'),web_sources.page_identity('https://retailer.example/p?sku=2'))
        self.assertNotEqual(web_sources.page_identity('https://retailer.example/p?signature=a%20b'),web_sources.page_identity('https://retailer.example/p?signature=a+b'))

    def test_registered_step_delivers_pack_with_request_and_response_receipts(self):
        factory = SourceFactory()
        rt = Runtime(Path(self.temp.name) / 'runtime', ExecutionFactory(FakeFactory(), factory))
        try:
            rt.create(plan([assignment()]))
            for _ in range(4):
                status = rt.tick('demo')
                if status['status'] == 'completed':
                    break
            self.assertEqual(status['status'], 'completed', status)
            self.assertEqual(factory.calls, 1)
            pack = json.loads(Path(rt.output('demo', 'sources', 'delivery/source-pack.json')['blob']).read_text())
            self.assertEqual(pack['entries'][0]['status'], 'source_fetched')
            control = rt.root / 'workers' / rt.task('demo', 'sources')['latest']
            self.assertTrue((control / 'request.json').is_file())
            self.assertTrue((control / 'response.json').is_file())
        finally:
            rt.close()

    def test_uncertain_search_stops_without_second_submission(self):
        FakeSession.error = gemini.ProviderError('connection lost', uncertain=True)
        factory = SourceFactory()
        rt = Runtime(Path(self.temp.name) / 'runtime', ExecutionFactory(FakeFactory(), factory))
        try:
            rt.create(plan([assignment()]))
            rt.tick('demo')
            status = rt.tick('demo')
            self.assertEqual(status['status'], 'uncertain', status)
            rt.tick('demo')
            self.assertEqual(factory.calls, 1)
            control = rt.root / 'workers' / rt.task('demo', 'sources')['latest']
            self.assertEqual(json.loads((control / 'operation.json').read_text())['outcome'], 'uncertain')
            self.assertTrue((control / 'request.json').is_file())
            self.assertFalse((control / 'response.json').exists())
        finally:
            rt.close()

    def test_invalid_query_and_domain_are_rejected_before_dispatch(self):
        for queries, domains in [([], []), (['a'] * 21, []), (['a'], ['localhost']),
                                 (['a'], ['https://example.com'])]:
            with self.subTest(queries=queries, domains=domains), self.assertRaises(ValueError):
                web_sources.validate(queries, domains)

    def test_domain_filter_blocks_a_fetch_before_network(self):
        with patch.object(orchestrator_web, 'public_addresses') as resolve:
            with self.assertRaisesRegex(ValueError, 'selected source domains'):
                orchestrator_web.download('https://other.example.org/abc',
                                          allowed_hosts=['example.com'])
            resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
