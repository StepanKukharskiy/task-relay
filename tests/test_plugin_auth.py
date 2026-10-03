from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from starlette.testclient import TestClient
    from task_relay.plugin_auth import OwnerTokenVerifier
    from task_relay import chatgpt_plugin as plugin, work_state as ws
except ImportError:
    jwt = None


@unittest.skipUnless(jwt, 'Install the plugin extra for OAuth verification')
class AuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.issuer = 'https://issuer.example/'
        self.resource = 'https://relay.example/mcp'
        self.verifier = OwnerTokenVerifier(self.issuer, self.resource, 'https://issuer.example/jwks', 'fixture-owner',
            SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.key.public_key())))

    def token(self, **updates):
        claims = {'iss': self.issuer, 'aud': self.resource, 'sub': 'fixture-owner',
                  'iat': int(time.time()), 'exp': int(time.time()) + 60, 'scope': 'relay:read relay:write'}
        claims.update(updates)
        return jwt.encode(claims, self.key, algorithm='RS256')

    async def test_signature_issuer_audience_expiry_owner_and_scope(self):
        valid = await self.verifier.verify_token(self.token())
        self.assertEqual(valid.subject, 'fixture-owner')
        for updates in ({'iss': 'https://other.example/'}, {'aud': 'https://other.example/mcp'},
                        {'sub': 'someone-else'}, {'exp': int(time.time()) - 10}, {'exp': '9999999999'}, {'scope': 'relay:write'}):
            with self.subTest(updates=updates): self.assertIsNone(await self.verifier.verify_token(self.token(**updates)))
        bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signed_elsewhere = jwt.encode({'iss': self.issuer, 'aud': self.resource, 'sub': 'fixture-owner',
            'iat': int(time.time()), 'exp': int(time.time())+60, 'scope': 'relay:read'}, bad_key, algorithm='RS256')
        self.assertIsNone(await self.verifier.verify_token(signed_elsewhere))
        self.assertIsNone(await self.verifier.verify_token('not-a-token'))

    async def test_discovery_challenge_and_read_only_scope_blocks_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'state.sqlite'
            db = ws.connect(path); pid = ws.create(db, 'Guide', 'Create guide.'); db.close()
            service = plugin.Service(path, [pid], oauth=True)
            app = plugin.http_app(plugin.make_server(service), verifier=self.verifier)
            headers = {'accept': 'application/json, text/event-stream'}
            with TestClient(app, base_url='https://relay.example') as client:
                meta = client.get('/.well-known/oauth-protected-resource/mcp')
                self.assertEqual(meta.status_code, 200)
                self.assertEqual(meta.json()['resource'], self.resource)
                self.assertEqual(meta.json()['authorization_servers'], [self.issuer])
                payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'relay_open_work', 'arguments': {'project_id': pid}}}
                no_auth = client.post('/mcp', json=payload, headers=headers)
                self.assertEqual(no_auth.status_code, 401)
                self.assertIn('resource_metadata=', no_auth.headers['www-authenticate'])
                read_headers = {**headers, 'authorization': 'Bearer ' + self.token(scope='relay:read')}
                result = client.post('/mcp', json=payload, headers=read_headers)
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()['result'].get('isError', False))
                payload['params'] = {'name': 'relay_prepare_change', 'arguments': {'project_id': pid, 'revision': 1,
                    'request': 'Record a decision.', 'change': {'action': 'decision', 'text': 'Use primary sources.', 'supersedes': None}}}
                blocked = client.post('/mcp', json=payload, headers=read_headers)
                self.assertTrue(blocked.json()['result']['isError'])
                full_headers = {**headers, 'authorization': 'Bearer ' + self.token()}
                allowed = client.post('/mcp', json=payload, headers=full_headers)
                self.assertFalse(allowed.json()['result'].get('isError', False))
                self.assertIn('confirmation_token', allowed.json()['result']['_meta'])
                payload['params'] = {'name': 'relay_prepare_understanding', 'arguments': {'project_id': pid,
                    'revision': 1, 'request': 'Understand deliberately connected work.'}}
                blocked = client.post('/mcp', json=payload, headers=read_headers)
                self.assertTrue(blocked.json()['result']['isError'])
                self.assertIn('required Task Relay scope', blocked.json()['result']['content'][0]['text'])
                prepared = client.post('/mcp', json=payload, headers=full_headers)
                self.assertFalse(prepared.json()['result'].get('isError', False))
                self.assertEqual(prepared.json()['result']['structuredContent']['model_calls'], 0)
            db = ws.connect(path); self.assertEqual(ws.project(db, pid)['revision'], 1); db.close()
        with self.assertRaises(ValueError): plugin.Service('/unused', None, oauth=True)


if __name__ == '__main__': unittest.main()
