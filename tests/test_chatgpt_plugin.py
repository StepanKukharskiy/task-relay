import json
from pathlib import Path
import sys
import tempfile
import unittest

from task_relay import work_state as ws

try:
    import mcp
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from starlette.testclient import TestClient
    from task_relay import chatgpt_plugin as plugin
except ImportError:
    mcp = None


@unittest.skipUnless(mcp, 'Install the plugin extra for MCP protocol checks')
class PluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'state.sqlite'
        db = ws.connect(self.path)
        self.pid = ws.create(db, 'Guide', 'Create the guide.', self.root)
        self.other = ws.create(db, 'Private other work', 'Other request')
        db.close()

    def tearDown(self): self.temp.cleanup()

    async def test_completed_text_is_automatically_visible_in_scoped_protocol_work(self):
        db = ws.connect(self.path)
        try:
            packet = ws.prepare_packet(db, self.pid, ws.project(db, self.pid)['revision'], 'Continue with exact text.')
            review = ws.prepare_change(db, self.pid, ws.project(db, self.pid)['revision'], 'Write this candidate.',
                {'action': 'write_text', 'packet_id': packet['packet_id'], 'family': 'text',
                 'filename': 'candidate.txt', 'content': 'A controlled candidate.'})
            started = ws.commit_change(db, self.pid, review['review_id'], review['confirmation_token'], True)
            ws.run_text(db, self.pid, started['run_id'])
            captured = json.loads(db.execute("SELECT receipt FROM execution_result_deliveries WHERE status='captured'").fetchone()[0])
        finally:
            db.close()
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'task_relay.chatgpt_plugin', '--db', str(self.path), '--project', self.pid],
            cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                state = (await client.call_tool('relay_open_work', {'project_id': self.pid})).structuredContent['work']
                result = state['execution_results'][0]
                self.assertEqual(result['id'], captured['record_id'])
                self.assertEqual(result['data']['envelope']['status']['execution'], 'completed')
                self.assertFalse(state['artifacts'][0]['selected'])
                continuation = await client.call_tool('relay_prepare_continuation', {'project_id': self.pid,
                    'revision': state['project']['revision'], 'request': 'Review the candidate.'})
                self.assertEqual(continuation.structuredContent['packet']['execution_results'][0]['id'], result['id'])
                denied = await client.call_tool('relay_provenance', {'project_id': self.other, 'record_id': result['id']})
                self.assertTrue(denied.isError)
                tools = (await client.list_tools()).tools
                self.assertEqual(len(tools), 13, 'Local source grants do not expand the model-facing tool surface')

    async def test_real_sdk_stdio_work_review_packet_and_ui_resource(self):
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'task_relay.chatgpt_plugin', '--db', str(self.path), '--project', self.pid],
            cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                self.assertEqual(len(tools), 13)
                confirm = next(t for t in tools if t.name == 'relay_commit_change')
                self.assertEqual(confirm.meta['ui']['visibility'], ['app'])
                self.assertFalse(confirm.annotations.readOnlyHint)
                opened = next(t for t in tools if t.name == 'relay_open_work')
                self.assertEqual(opened.meta['openai/ui']['entrypoints'], [{'type': 'global'}, {'type': 'thread'}])
                projects = await client.call_tool('relay_list_work', {})
                self.assertEqual([p['id'] for p in projects.structuredContent['projects']], [self.pid])
                initial = await client.call_tool('relay_open_work', {})
                self.assertEqual(initial.structuredContent, projects.structuredContent)
                denied = await client.call_tool('relay_open_work', {'project_id': self.other})
                self.assertTrue(denied.isError)
                secret = 'AIza' + 'z' * 35
                invalid = await client.call_tool('relay_open_work', {'project_id': self.pid, 'secret': secret})
                self.assertTrue(invalid.isError)
                self.assertNotIn(secret, json.dumps(invalid.model_dump()))
                state = await client.call_tool('relay_open_work', {'project_id': self.pid})
                review = await client.call_tool('relay_prepare_change', {'project_id': self.pid,
                    'revision': state.structuredContent['work']['project']['revision'], 'request': 'Use primary sources.',
                    'change': {'action': 'decision', 'text': 'Use primary sources.', 'supersedes': None}})
                self.assertIn('confirmation_token', review.meta)
                self.assertEqual(review.structuredContent['work']['project']['id'], self.pid, 'A newly mounted review includes its work state')
                self.assertNotIn('confirmation_token', json.dumps(review.structuredContent))
                confirmed = await client.call_tool('relay_commit_change', {'project_id': self.pid,
                    'review_id': review.structuredContent['review']['review_id'], 'confirmation_token': review.meta['confirmation_token'], 'confirmed': True})
                self.assertFalse(confirmed.isError)
                self.assertEqual(len(confirmed.structuredContent['work']['decisions']), 1)
                packet = await client.call_tool('relay_prepare_continuation', {'project_id': self.pid,
                    'revision': confirmed.structuredContent['work']['project']['revision'], 'request': 'Continue the guide.'})
                ready = await client.call_tool('relay_validate_continuation', {'project_id': self.pid, 'packet_id': packet.structuredContent['packet_id']})
                self.assertEqual(ready.structuredContent['status'], 'ready')
                self.assertEqual(packet.structuredContent['model_calls'], 0)
                resources = await client.list_resources()
                self.assertEqual(str(resources.resources[0].uri), plugin.UI_URI)
                ui = await client.read_resource(plugin.UI_URI)
                html = ui.contents[0].text
                self.assertIn('Continue this work', html)
                self.assertIn('ui/initialize', html)
                self.assertNotIn('RELAY_WORK_SCRIPT', html)
                self.assertNotIn('RELAY_WORK_STYLE', html)

    async def test_http_requires_token_and_protocol_initializes(self):
        server = plugin.make_server(plugin.Service(self.path, [self.pid]))
        token = 'fixture-local-' + 'x' * 40
        app = plugin.http_app(server, token)
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'controlled-test', 'version': '1'}}}
        with TestClient(app, base_url='http://localhost:8766') as client:
            headers = {'accept': 'application/json, text/event-stream'}
            self.assertEqual(client.post('/mcp', json=request, headers=headers).status_code, 401)
            response = client.post('/mcp', json=request, headers={**headers, 'authorization': 'Bearer ' + token})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['result']['serverInfo']['name'], 'relay-work')
            self.assertEqual(client.post('/mcp', json=request, headers={**headers, 'authorization': 'Bearer wrong'}).status_code, 401)
        with self.assertRaises(ValueError): plugin.http_app(server, 'short')

    async def test_actual_protocol_understanding_and_result_capture_do_not_accept_decisions(self):
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'task_relay.chatgpt_plugin', '--db', str(self.path), '--project', self.pid],
            cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                source = {'id': 'shared', 'kind': 'evidence', 'title': 'Deliberately supplied note',
                    'data': {'text': 'Verify the source.', 'origin': 'explicitly_supplied', 'refs': [], 'topics': []}}
                imported = await client.call_tool('relay_import_work', {'project_id': self.pid,
                    'request': 'Use the note I supplied.', 'manifest': {'schema': ws.SCHEMA, 'records': [source]}})
                state = imported.structuredContent['work']
                prepared = await client.call_tool('relay_prepare_understanding', {'project_id': self.pid,
                    'revision': state['project']['revision'], 'request': 'Understand this connected work.'})
                self.assertFalse(prepared.isError)
                cite = [{'record_id': 'shared', 'quote': 'Verify the source.'}]
                report = {'objective': {'text': 'Verify the guide source.', 'citations': cite}, 'conclusions': [],
                    'decision_proposals': [{'text': 'Use a verified source.', 'citations': cite}], 'open_questions': [],
                    'next_actions': [{'text': 'Verify the source.', 'reason': 'The note explicitly asks for this.', 'citations': cite, 'topics': ['Sources']}],
                    'workstreams': [{'name': 'Sources', 'record_ids': ['shared']}], 'limits': ['No source verification has run.']}
                saved = await client.call_tool('relay_save_understanding', {'project_id': self.pid,
                    'input_id': prepared.structuredContent['input_id'], 'report': report})
                self.assertFalse(saved.isError)
                state = saved.structuredContent['work']
                self.assertEqual(state['decisions'], [])
                action = state['next_actions'][0]
                context = await client.call_tool('relay_prepare_continuation', {'project_id': self.pid,
                    'revision': state['project']['revision'], 'request': action['data']['text'], 'action_id': action['id']})
                self.assertFalse(context.isError)
                capture = await client.call_tool('relay_capture_result', {'project_id': self.pid,
                    'packet_id': context.structuredContent['packet_id'], 'notes': 'The source remains unverified.', 'questions': ['Which primary source supports it?']})
                self.assertFalse(capture.isError)
                self.assertFalse(capture.structuredContent['result']['execution_dispatch'])
                self.assertTrue(capture.structuredContent['work']['understanding']['stale'])
                self.assertEqual(capture.structuredContent['work']['decisions'], [])
                self.assertEqual(len(capture.structuredContent['work']['open_issues']), 1)
                denied = await client.call_tool('relay_capture_result', {'project_id': self.other,
                    'packet_id': context.structuredContent['packet_id'], 'notes': 'Another project.', 'questions': []})
                self.assertTrue(denied.isError)

    async def test_schema_and_scope_reject_unreviewed_changes(self):
        service = plugin.Service(self.path, [self.pid])
        with self.assertRaises(ValueError): service.call('relay_create_work', {'title': 'Other', 'request': 'Create other work.'})
        with self.assertRaises(ValueError): service.call('relay_prepare_change', {'project_id': self.other, 'revision': 1, 'request': 'Change it.', 'change': {'action': 'decision', 'text': 'Rule', 'supersedes': None}})
        from jsonschema.exceptions import ValidationError
        with self.assertRaises(ValidationError): service.call('relay_open_work', {'project_id': self.pid, 'root': '/outside'})


if __name__ == '__main__': unittest.main()
