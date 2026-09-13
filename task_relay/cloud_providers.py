"""Media-only provider connections and bounded, non-retrying API transport."""
import json
import re
import ssl
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit, urljoin

from . import credentials, gemini
from .relay_paths import PATHS

PROVIDERS = {
    'runway': {'name': 'Runway', 'base': 'https://api.dev.runwayml.com/v1', 'keys': 'https://dev.runwayml.com/',
               'models': {'image': ['gen4_image'], 'video': ['gen4.5']}},
    'higgsfield': {'name': 'Higgsfield', 'base': 'https://api.higgsfield.ai', 'keys': 'https://cloud.higgsfield.ai/',
                  'models': {'image': ['higgsfield-ai/soul/standard'], 'video': ['bytedance/seedance/v1/pro/fast/text-to-video']}},
    'meshy': {'name': 'Meshy', 'base': 'https://api.meshy.ai', 'keys': 'https://www.meshy.ai/settings/api',
              'models': {'mesh': ['meshy-6', 'meshy-7']}},
}


def read_config(provider):
    if provider not in PROVIDERS: raise ValueError('Unsupported media provider.')
    from .capability_defaults import overlay
    try:
        return overlay(provider, credentials.configuration(gemini.DATA/(provider+'.json')), gemini.DATA/'state.sqlite')
    except credentials.CredentialError:
        return None


def connect(value, paths=PATHS):
    if not isinstance(value, dict) or set(value) != {'provider', 'key'} or value['provider'] not in PROVIDERS:
        raise ValueError('Choose one of the supported media providers.')
    provider, key = value['provider'], value['key']
    if not isinstance(key, str) or len(key) > 2000 or any(c.isspace() for c in key):
        raise ValueError('Enter the API credential without spaces or line breaks.')
    if provider == 'higgsfield' and key and (key.count(':') != 1 or not all(key.split(':'))):
        raise ValueError('Higgsfield requires key ID and secret in ID:SECRET format.')
    from .onboarding import setup_lock, saved
    with setup_lock():
        path = paths.data/(provider+'.json')
        config = saved(path)
        if not key:
            if not credentials.configuration(path): raise ValueError('Enter this provider’s API credential.')
            return {'message': 'Saved media connection retained. Generation access is checked when used.'}
        config.update(api_key=key, enabled=True)
        config.pop('api_key_ref', None)
        config.setdefault('models', {})
        for cap, models in PROVIDERS[provider]['models'].items():
            config['models'].setdefault(cap, models[0])
        credentials.save(path, config)
    return {'message': 'Media connection saved. No generation was run; API access and credit balance are unverified.'}


def connections(paths=PATHS):
    return [dict(provider=p, name=spec['name'], keys=spec['keys'],
                 connected=credentials.status(paths.data/(p+'.json'))['available']) for p,spec in PROVIDERS.items()]


def task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise ValueError('The provider returned an invalid task identifier; inspect the saved response.')
    return value


def poll_path(provider, ident):
    ident = quote(task_id(ident), safe='')
    return ('/tasks/'+ident if provider=='runway' else '/requests/'+ident+'/status' if provider=='higgsfield'
            else '/openapi/v2/text-to-3d/'+ident)


class Client:
    def __init__(self, provider, key):
        if provider not in PROVIDERS: raise ValueError('Unsupported media provider.')
        self.provider, self.key = provider, key
        context = ssl.create_default_context()
        if Path('/etc/ssl/cert.pem').is_file(): context.load_verify_locations('/etc/ssl/cert.pem')
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), gemini.NoRedirect())

    def request(self, path, payload=None, timeout=30):
        post_paths = {'runway': ('/text_to_image','/image_to_video'), 'meshy': ('/openapi/v2/text-to-3d',),
                      'higgsfield': tuple('/'+m for group in PROVIDERS['higgsfield']['models'].values() for m in group)}
        allowed = path in post_paths[self.provider] if payload is not None else bool(re.fullmatch(
            {'runway':r'/tasks/[A-Za-z0-9_-]{1,160}', 'meshy':r'/openapi/v2/text-to-3d/[A-Za-z0-9_-]{1,160}',
             'higgsfield':r'/requests/[A-Za-z0-9_-]{1,160}/status'}[self.provider], path))
        if not allowed: raise ValueError('Unsupported media API operation.')
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {'Authorization': ('Key ' if self.provider=='higgsfield' else 'Bearer ')+self.key,
                   'Content-Type':'application/json', 'Accept':'application/json'}
        if self.provider=='runway': headers['X-Runway-Version']='2024-11-06'
        request = urllib.request.Request(PROVIDERS[self.provider]['base']+path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
            if len(raw)>2_000_000: raise ValueError
            result = json.loads(raw)
            if not isinstance(result,dict): raise ValueError
            return result
        except urllib.error.HTTPError as exc:
            code=exc.code;exc.close()
            raise gemini.ProviderError(code, uncertain=payload is not None and code>=500) from None
        except (OSError,ValueError):
            raise gemini.ProviderError('connection or invalid response', uncertain=payload is not None) from None


def download(url, limit):
    """Fetch public output bytes with pinned DNS and no API credential headers."""
    from .orchestrator_web import public_url, public_addresses, PublicHTTPS
    import time
    deadline=time.monotonic()+90
    for _ in range(4):
        parsed=urlsplit(public_url(url))
        remaining=deadline-time.monotonic()
        if remaining<=0: raise ValueError('Media download deadline exceeded; the generation receipt is retained.')
        connection=PublicHTTPS(parsed.hostname,public_addresses(parsed.hostname)[0],min(30,remaining))
        try:
            connection.request('GET',parsed.path+('?' + parsed.query if parsed.query else ''),
                               headers={'Accept-Encoding':'identity','User-Agent':'TaskRelay/1.0'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location: raise ValueError('Media redirect has no destination.')
                url=urljoin(url,location);continue
            if response.status!=200: raise ValueError('Media download failed (HTTP '+str(response.status)+'); the generation receipt is retained.')
            if response.getheader('Content-Encoding','identity') not in ('identity',''): raise ValueError('Unsupported media content encoding.')
            chunks=[];size=0
            while True:
                if time.monotonic()>=deadline: raise ValueError('Media download deadline exceeded.')
                block=response.read(min(65536,limit+1-size))
                if not block: break
                chunks.append(block);size+=len(block)
                if size>limit: raise ValueError('Generated media exceeds the approved byte limit.')
            if not size: raise ValueError('Provider returned an empty media file.')
            return b''.join(chunks)
        finally: connection.close()
    raise ValueError('Too many media redirects.')
