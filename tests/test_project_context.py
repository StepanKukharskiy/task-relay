import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from task_relay import project_context as pc
from task_relay.host_project_context import capture, rollout_lines


class Client:
    def __init__(self, value, db):
        self.value, self.db, self.calls = value, db, 0

    def request(self, path, payload):
        assert not self.db.in_transaction, 'external dispatch before commit'
        self.calls += 1
        return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(self.value)}]}}],
                'usageMetadata': {'promptTokenCount': 50, 'candidatesTokenCount': 25}}


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.db = pc.connect(self.root / 'relay.sqlite')
        self.capture = {'schema_version': 1, 'project': str(self.root / 'project'),
            'threads': [{'id': 't'}], 'limitations': ['Native geometry not validated'],
            'files': [{'path': 'outputs/first.txt', 'bytes': 2}],
            'sources': [{'id': 's1', 'kind': 'message', 'role': 'user', 'text': 'Make a guide instead.', 'thread_id': 't', 'title': 'Guide'},
                        {'id': 's2', 'kind': 'message', 'role': 'assistant', 'text': 'Draft created.', 'thread_id': 't', 'title': 'Guide'}]}
        self.answer = {'topics': [self.topic('guide', 's1', 'explicit_request', 'Make a guide instead.'),
                                  self.topic('draft', 's2', 'reported_result', 'Draft created.')]}

    def topic(self, tid, sid, kind, quote):
        return {'id': tid, 'title': tid, 'summary': 'Awaiting review', 'source_ids': [sid],
                'claims': [{'kind': kind, 'statement': quote, 'evidence': [{'source_id': sid, 'quote': quote}]}],
                'artifact_paths': ['outputs/first.txt'], 'open_questions': ['Accepted?'], 'next_steps': ['Review draft']}

    def prepare(self):
        return pc.prepare(self.db, self.capture, 'Organize this project.', 'test-model')

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_queue_and_owner_atomic_idempotent_and_one_real_dispatch(self, config):
        rid = self.prepare()
        self.assertEqual(rid, self.prepare())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM internal_jobs').fetchone()[0], 1)
        client = Client(self.answer, self.db)
        self.assertEqual(pc.run(self.db, rid, client)['status'], 'proposed')
        pc.run(self.db, rid, client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(pc.inspect(self.db, rid)['usage']['promptTokenCount'], 50)

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_bad_coverage_retains_response_without_paid_replay(self, config):
        rid = self.prepare()
        value = copy.deepcopy(self.answer); value['topics'][1]['source_ids'] = ['s1']; value['topics'][1]['claims'] = []
        client = Client(value, self.db)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'coverage'):
                pc.run(self.db, rid, client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(pc.inspect(self.db, rid)['job_status'], 'completed')
        self.assertEqual(pc.inspect(self.db, rid)['status'], 'incomplete')
        with self.assertRaises(ValueError): pc.export(self.db, rid, self.root / 'export')

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_inexact_quote_is_quarantined_without_repair_or_second_call(self, config):
        rid = self.prepare(); value = copy.deepcopy(self.answer)
        value['topics'][0]['claims'][0]['evidence'][0]['quote'] = 'Invented quotation'
        client = Client(value, self.db)
        result = pc.run(self.db, rid, client)
        self.assertEqual(result['status'], 'proposed_with_gaps')
        self.assertEqual(result['validation'], {'accepted_claims': 1, 'rejected_claims': 1})
        packet = pc.context(self.db, rid, 'guide')
        self.assertEqual(packet['topic']['claims'], [])
        self.assertEqual(packet['rejected_claims'][0]['claim']['evidence'][0]['quote'], 'Invented quotation')
        self.assertEqual(len(packet['sources']), 1)
        pc.run(self.db, rid, client); self.assertEqual(client.calls, 1)
        pc.export(self.db, rid, self.root / 'export')
        self.assertIn('held for review', (self.root / 'export/index.md').read_text())

    def test_uncertain_submission_cannot_be_replayed(self):
        rid = self.prepare(); jid = pc.get(self.db, rid)['job_id']
        with self.db: self.db.execute("UPDATE internal_jobs SET status='sending' WHERE id=?", (jid,))
        pc.internal_jobs.recover(self.db, jid)
        client = Client(self.answer, self.db)
        with self.assertRaisesRegex(ValueError, 'will not be replayed'): pc.run(self.db, rid, client)
        self.assertEqual(client.calls, 0)

    def test_budget_and_duplicate_sources_queue_nothing(self):
        with self.assertRaisesRegex(ValueError, 'budget'): pc.prepare(self.db, self.capture, 'request', 'model', 10)
        self.capture['sources'].append(self.capture['sources'][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.prepare()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM internal_jobs').fetchone()[0], 0)

    def test_authority_quotes_missing_artifacts_and_traversal_rejected(self):
        for mutation in ('role', 'quote', 'path', 'slug', 'quoted'):
            answer, cap = copy.deepcopy(self.answer), copy.deepcopy(self.capture)
            if mutation == 'role': answer['topics'][1]['claims'][0]['kind'] = 'explicit_request'
            if mutation == 'quote': answer['topics'][0]['claims'][0]['evidence'][0]['quote'] = 'invented'
            if mutation == 'path': answer['topics'][0]['artifact_paths'] = ['missing.txt']
            if mutation == 'slug': answer['topics'][0]['id'] = '../escape'
            if mutation == 'quoted': cap['sources'][0]['text'] = '> Make a guide instead.'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): pc.validate(answer, cap)

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_original_credentials_preserved_locally_but_not_sent(self, config):
        secret = 'AIza' + 'a' * 35
        self.capture['sources'][0]['text'] += '\napi_key=' + secret
        rid = self.prepare()
        self.assertIn(secret, pc.get(self.db, rid)['capture_json'])
        request = self.db.execute('SELECT request_json FROM internal_jobs').fetchone()[0]
        self.assertNotIn(secret, request)
        self.assertIn('REDACTED_CREDENTIAL', request)
        json.loads(json.loads(request)['contents'][0]['parts'][0]['text'])

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_recover_committed_answer_and_partial_export_without_provider(self, config):
        rid = self.prepare(); jid = pc.get(self.db, rid)['job_id']
        with self.db:
            self.db.execute("UPDATE internal_jobs SET status='completed',answer=? WHERE id=?", (json.dumps(self.answer), jid))
        client = Client({}, self.db); pc.run(self.db, rid, client)
        self.assertEqual(client.calls, 0)
        out = self.root / 'export'; receipt = pc.export(self.db, rid, out)
        (out / 'topic-draft.md').unlink()
        self.assertEqual(pc.export(self.db, rid, out), receipt)
        (out / 'topic-draft.md').write_text('User edited this.')
        with self.assertRaisesRegex(ValueError, 'edited'): pc.export(self.db, rid, out)
        self.assertEqual((out / 'topic-draft.md').read_text(), 'User edited this.')
        self.assertEqual(pc.context(self.db, rid, 'guide')['sources'][0]['id'], 's1')
        with self.assertRaisesRegex(ValueError, 'exact topic'): pc.context(self.db, rid, 'modeling')

    def test_local_adapter_exact_scope_canonical_dedup_and_exclusions(self):
        home, project = self.root / 'codex', self.root / 'project'
        home.mkdir(); (project / 'wiki').mkdir(parents=True)
        (project / 'wiki/source.md').write_text('Measured scale unknown.')
        (project / 'wiki/manual.md').write_text('Manual answer key.')
        (project / 'wiki/linked.md').symlink_to(self.root / 'outside')
        rollout = home / 'rollout.jsonl'
        def event(iid, text):
            return {'timestamp': '2099-01-01T00:00:00Z', 'type': 'event_msg',
                    'payload': {'type': 'item_completed', 'item': {'type': 'UserMessage', 'id': iid, 'content': [{'type': 'Text', 'text': text}]}}}
        rollout.write_text('\n'.join(json.dumps(e) for e in [event('m1', 'Guide please'), event('m2', 'Preserve old draft')]) + '\n')
        state = sqlite3.connect(home / 'state_5.sqlite')
        state.execute('CREATE TABLE threads(id,name,title,rollout_path,created_at,updated_at,archived,cwd)')
        state.executemany('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)', [('t', 'Guide', 'Guide', str(rollout), 1, 2, 0, str(project)), ('other', 'Other', 'Other', str(rollout), 1, 2, 0, '/different/project')])
        state.commit(); state.close()
        history = sqlite3.connect(home / 'thread_history_1.sqlite')
        history.execute('CREATE TABLE thread_items(thread_id,item_type,item_json,item_id,turn_id,created_at_ms,rollout_ordinal)')
        history.execute('INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)', ('t', 'userMessage', json.dumps({'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Guide please'}]}), 'm1', 'turn', 1, 1))
        history.commit(); history.close()
        result = capture(project, home, ['wiki/manual.md'])
        self.assertEqual(len(result['threads']), 1)
        self.assertEqual(len(result['sources']), 3)
        self.assertEqual([s['item_id'] for s in result['sources'] if s['kind'] == 'message'], ['m1', 'm2'])
        self.assertNotIn('Manual answer key', pc.encoded(result['sources']))
        self.assertEqual(len(result['omissions']), 1)

    def test_large_excluded_tool_event_is_streamed_without_losing_next_message(self):
        tool = json.dumps({'type': 'event_msg', 'payload': {'type': 'item_completed',
                          'item': {'type': 'ToolOutput', 'text': 'x' * 9000}}}).encode() + b'\n'
        user = json.dumps({'type': 'event_msg', 'payload': {'type': 'item_completed',
                          'item': {'type': 'UserMessage', 'id': 'next', 'content': [{'type': 'Text', 'text': 'Keep this.'}]}}}).encode() + b'\n'
        raw = tool + user; hasher = hashlib.sha256()
        rows = list(rollout_lines(io.BytesIO(raw), hasher))
        self.assertEqual(rows, [(2, user)])
        self.assertEqual(hasher.hexdigest(), hashlib.sha256(raw).hexdigest())

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_graph_preserves_cross_topic_chat_links_and_quarantined_citations(self, config):
        from task_relay.project_context_graph import build
        value = copy.deepcopy(self.answer)
        value['topics'][1]['source_ids'].append('s1')
        value['topics'][1]['claims'][0]['evidence'][0]['quote'] = 'Unverified quotation'
        self.capture['sources'][0]['text'] += '\n' + 'AIza' + 'b' * 35
        rid = self.prepare(); client = Client(value, self.db); pc.run(self.db, rid, client)
        graph = build(self.db, rid)
        self.assertEqual(client.calls, 1)
        self.assertEqual(graph['counts']['message'], 2)
        self.assertEqual(len([e for e in graph['edges'] if e['relation'] == 'discusses_topic']), 2)
        self.assertEqual({e['basis'] for e in graph['edges'] if e['relation'] == 'discusses_topic'}, {'model_proposal'})
        self.assertEqual(len([e for e in graph['edges'] if e['relation'] == 'cites']), 1)
        self.assertEqual(len([e for e in graph['edges'] if e['relation'] == 'unverified_citation']), 1)
        ids = {n['id'] for n in graph['nodes']}
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in graph['edges']))
        self.assertNotIn('AIza' + 'b' * 35, pc.encoded(graph))
        self.assertNotIn('accepted', {e['relation'] for e in graph['edges']})

    @patch('task_relay.gemini.read_config', return_value=None)
    def test_graph_export_retains_request_and_recovers_without_mutating_analysis(self, config):
        from task_relay.project_context_graph import export
        rid = self.prepare(); client = Client(self.answer, self.db); pc.run(self.db, rid, client)
        before = pc.get(self.db, rid)
        out = self.root / 'graph.json'; request = 'Build the project connections graph.'
        receipt = export(self.db, rid, out, request)
        self.assertEqual(receipt['exact_request'], request)
        self.assertEqual(receipt['model_calls'], 0)
        out.unlink(); self.assertEqual(export(self.db, rid, out, request), receipt)
        self.assertEqual(before, pc.get(self.db, rid))
        self.assertEqual(client.calls, 1)
        out.write_text('User edited this.')
        with self.assertRaisesRegex(ValueError, 'edited'): export(self.db, rid, out, request)
        self.assertEqual(out.read_text(), 'User edited this.')


if __name__ == '__main__':
    unittest.main()
