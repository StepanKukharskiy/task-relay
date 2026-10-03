"""OAuth resource verification for an explicitly configured Relay owner and issuer.

The authorization server owns login, consent, clients and refresh tokens. Relay
verifies its signed access tokens and publishes protected-resource discovery.
"""
import time
from urllib.parse import urlparse


class OwnerTokenVerifier:
    def __init__(self, issuer, resource, jwks_url, subject, key_client=None):
        for value in (issuer, resource, jwks_url):
            parsed = urlparse(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('OAuth issuer, resource and JWKS must use explicit HTTPS URLs')
        if urlparse(resource).path != '/mcp' or urlparse(resource).query:
            raise ValueError('OAuth resource URL must identify the /mcp endpoint')
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError('Configure the exact authorized owner subject')
        import jwt
        self.issuer, self.resource, self.subject = issuer, resource, subject
        self.key_client = key_client or jwt.PyJWKClient(jwks_url, timeout=5, lifespan=300)

    async def verify_token(self, token):
        import anyio
        import jwt
        from mcp.server.auth.provider import AccessToken
        try:
            key = await anyio.to_thread.run_sync(self.key_client.get_signing_key_from_jwt, token)
            claims = jwt.decode(token, key.key, algorithms=['RS256'], audience=self.resource, issuer=self.issuer,
                                options={'require': ['exp', 'iat', 'iss', 'aud', 'sub']})
            if claims['sub'] != self.subject or claims['exp'] <= time.time():
                return None
            scopes = claims.get('scope', '')
            if not isinstance(scopes, str):
                return None
            scopes = scopes.split()
            if 'relay:read' not in scopes:
                return None
            return AccessToken(token=token, client_id=str(claims.get('client_id') or claims.get('azp') or 'oauth-owner'),
                scopes=scopes, expires_at=int(claims['exp']), resource=self.resource, subject=self.subject,
                claims={'iss': self.issuer})
        except (jwt.PyJWTError, OSError, ValueError, TypeError):
            return None
