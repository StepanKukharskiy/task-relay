"""Public transport rejection/recovery and isolated packaging; no cloud calls."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from task_relay import web_plugin as web
from scripts.build_relay_web_server import build, HOST, RUNTIME
from tests.test_portable_work import SKILL, WORK


class HostingTests(unittest.TestCase):
    def test_stateless_http_discovery_export_and_host_boundary(self):
        from starlette.testclient import TestClient
        app = web.http_app(web.make_server(), 'https://relay.example.org')
        with TestClient(app, base_url='https://relay.example.org') as client:
            headers = {'Accept': 'application/json, text/event-stream'}
            def rpc(method, params=None):
                response = client.post('/mcp', headers=headers, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn('mcp-session-id', response.headers)
                return response.json()['result']
            health = client.get('/health').json()
            self.assertEqual(health['version'], web.VERSION)
            init = rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                     'clientInfo': {'name': 'controlled-fixture', 'version': '1'}})
            self.assertEqual(init['serverInfo']['version'], web.VERSION)
            tools = rpc('tools/list')['tools']
            self.assertEqual(len(tools), 6)
            for tool in tools:
                for annotation in ('readOnlyHint', 'openWorldHint', 'destructiveHint'):
                    self.assertIsInstance(tool['annotations'][annotation], bool)
            selected = next(t for t in tools if t['name'] == 'relay_import_selected_file')
            self.assertTrue(selected['annotations']['openWorldHint'])
            proposal = rpc('tools/call', {'name': 'relay_propose_reusable',
                'arguments': {'request': 'Make this reusable.', 'skill': SKILL, 'work': WORK}})
            self.assertFalse(proposal['isError'])
            document = proposal['structuredContent']['candidates'][1]
            exported = rpc('tools/call', {'name': 'relay_review_export',
                'arguments': {'document': web.compact_document(document), 'confirmed': True}})
            self.assertFalse(exported['isError'])
            self.assertNotIn('data_base64', json.dumps(exported['structuredContent']))
            self.assertFalse(exported['_meta']['export']['stored_on_server'])
            opened = rpc('tools/call', {'name': 'relay_open_reusable', 'arguments': {}})
            self.assertEqual(opened['structuredContent']['documents'], [])
            denied = client.post('/mcp', headers={**headers, 'Host': 'other.example.org'}, json={})
            self.assertEqual(denied.status_code, 421)

    def test_chunked_and_declared_size_reject_before_mcp_then_recover(self):
        async def run():
            received = []
            async def app(scope, receive, send):
                received.append((await receive())['body'])
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'ok'})
            guard = web.HTTPGuards(app, max_bytes=10)
            async def request(chunks, headers=()):
                events = []
                async def receive(): return chunks.pop(0)
                async def send(message): events.append(message)
                await guard({'type': 'http', 'method': 'POST', 'path': '/mcp', 'headers': headers}, receive, send)
                return events[0]['status']
            self.assertEqual(await request([], [(b'content-length', b'11')]), 413)
            self.assertEqual(await request([{'type': 'http.request', 'body': b'abcdef', 'more_body': True},
                                            {'type': 'http.request', 'body': b'ghijk', 'more_body': False}]), 413)
            self.assertEqual(received, [])
            self.assertEqual(await request([{'type': 'http.request', 'body': b'small'}]), 200)
            self.assertEqual(received, [b'small'])
            self.assertEqual(guard.active, 0)
        asyncio.run(run())

    def test_rate_and_active_limits_recover_without_retaining_client_data(self):
        async def run():
            started, release = asyncio.Event(), asyncio.Event()
            now = [0]
            async def app(scope, receive, send):
                if scope['path'] == '/mcp':
                    started.set()
                    await release.wait()
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'ok'})
            guard = web.HTTPGuards(app, max_active=1, per_minute=2, clock=lambda: now[0])
            async def request(path='/mcp'):
                events = []
                async def receive(): return {'type': 'http.request', 'body': b'private-fixture'}
                async def send(message): events.append(message)
                await guard({'type': 'http', 'method': 'POST', 'path': path, 'headers': []}, receive, send)
                return events[0]
            first = asyncio.create_task(request())
            await started.wait()
            busy = await request()
            self.assertEqual(busy['status'], 503)
            self.assertIn((b'retry-after', b'10'), busy['headers'])
            release.set()
            self.assertEqual((await first)['status'], 200)
            self.assertEqual((await request())['status'], 429)
            self.assertEqual((await request('/health'))['status'], 200)
            now[0] = 61
            self.assertEqual((await request())['status'], 200)
            self.assertEqual(guard.active, 0)
            self.assertNotIn('private-fixture', repr(guard.__dict__))
        asyncio.run(run())

    def test_cancelled_upload_releases_capacity(self):
        async def run():
            waiting = asyncio.Event()
            async def app(*args): raise AssertionError('Incomplete upload reached MCP')
            async def receive():
                waiting.set()
                await asyncio.Event().wait()
            async def send(message): pass
            guard = web.HTTPGuards(app)
            task = asyncio.create_task(guard({'type': 'http', 'path': '/mcp', 'headers': []}, receive, send))
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertEqual(guard.active, 0)
        asyncio.run(run())

    def test_deployment_allowlist_excludes_local_state_and_preserves_builds(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'web'
            receipt = build(target)
            self.assertFalse(receipt['deployed'])
            self.assertFalse(receipt['published'])
            self.assertEqual(set(receipt['files']), set(RUNTIME) | set(HOST))
            self.assertFalse(any(p.suffix in ('.sqlite', '.yaml') for p in target.rglob('*')))
            self.assertFalse((target / 'build-receipt.json').exists())
            with self.assertRaises(ValueError): build(target)
            self.assertEqual((target / 'task_relay/web_plugin.py').read_bytes(),
                             (Path(__file__).resolve().parents[1] / 'task_relay/web_plugin.py').read_bytes())


if __name__ == '__main__': unittest.main()
