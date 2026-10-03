"""Portable O15.1 observation contract; no desktop imports or execution authority."""
import base64
from datetime import datetime
import hashlib
import json
from urllib.parse import urlsplit

PROTOCOL = 'relay.computer-observer.v1'
MAX_TEXT_BYTES = 24000
MAX_IMAGE_BYTES = 10000000
NEW_WINDOW = {'mode': 'new-window'}
SCRIPTING_WINDOW = {'mode': 'new-scripting-window'}


def managed_target(value):
    return value == NEW_WINDOW or value == SCRIPTING_WINDOW


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def target(value):
    if not isinstance(value, dict) or set(value) != {'pid', 'launch_id', 'window_id'}:
        raise ValueError('Select an exact Safari process and window from computer-use windows.')
    for name in ('pid', 'window_id'):
        if type(value[name]) is not int or not 0 < value[name] < 2**32:
            raise ValueError('Invalid target identity.')
    if not isinstance(value['launch_id'], str) or not 1 <= len(value['launch_id']) <= 80:
        raise ValueError('Missing process launch identity.')
    return dict(value)


def url(value, fixture=False):
    if not isinstance(value, str) or len(value) > 4000 or any(ord(c) < 33 for c in value) or '\\' in value:
        raise ValueError('Expected an exact URL without whitespace or credentials.')
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Expected an exact URL without credentials or fragment.')
    if parsed.scheme != 'https' and not (fixture and parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('HTTPS required; --local-fixture permits loopback HTTP only.')
    _ = parsed.port
    return value


def request(selected, expected_url, instruction, capture=False, fixture=False, *, launch=False):
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction.encode()) > 16000:
        raise ValueError('An exact bounded observation request is required.')
    if type(capture) is not bool or type(fixture) is not bool:
        raise ValueError('Invalid observation flags.')
    if launch and (not managed_target(selected) or capture):
        raise ValueError('Window launch requires a new text-only Safari window.')
    return {'protocol': PROTOCOL, 'operation': 'observe', 'target': dict(selected) if launch else target(selected),
            'expected_url': url(expected_url, fixture), 'request': instruction,
            'capture': capture, 'local_fixture': fixture}


def validate_response(value, frozen):
    """Validate bytes and provenance before publishing any native observation."""
    if not isinstance(value, dict) or value.get('protocol') != PROTOCOL:
        raise ValueError('Native helper protocol mismatch.')
    if value.get('ok') is not True:
        raise ValueError('Native observation blocked: ' + str(value.get('error', 'unknown'))[:200])
    if value.get('target') != frozen['target'] or value.get('url') != frozen['expected_url']:
        raise ValueError('Native observation target or URL changed.')
    if value.get('document_stable') is not True:
        raise ValueError('Native document did not remain stable during observation.')
    stamp = value.get('captured_at')
    if not isinstance(stamp, str) or not stamp.endswith('Z'):
        raise ValueError('Missing UTC observation timestamp.')
    datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    text = value.get('text')
    if not isinstance(text, str) or len(text.encode()) > MAX_TEXT_BYTES:
        raise ValueError('Native text exceeds its bound.')
    if type(value.get('truncated')) is not bool or not isinstance(value.get('coverage'), list):
        raise ValueError('Missing observation coverage.')
    if not text.strip():
        raise ValueError('No readable visible document text; observation is incomplete.')
    image = None
    if frozen['capture']:
        encoded = value.get('png_base64')
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError('Missing or oversized native PNG.')
        image = base64.b64decode(encoded, validate=True)
        from orchestrator.browser_contract import png_info
        png_info(image)
    elif 'png_base64' in value:
        raise ValueError('Native capture was not granted.')
    cleaned = {k: value[k] for k in ('protocol', 'target', 'url', 'document_stable',
                                    'captured_at', 'text', 'truncated', 'coverage')}
    return cleaned, image


def session_spec(value):
    """Frozen, finite manual action plan. No provider or arbitrary input surface."""
    keys = {'target', 'url', 'allowed_urls', 'actions', 'capture', 'local_fixture', 'max_seconds'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Session needs an exact target, URL list, action plan and limits.')
    if managed_target(value['target']):
        if value['actions'] or value['capture']:
            raise ValueError('Automatic windows require an empty worker plan and text-only evidence.')
    else:
        target(value['target'])
    if type(value['capture']) is not bool or type(value['local_fixture']) is not bool:
        raise ValueError('Session flags must be booleans.')
    if type(value['max_seconds']) is not int or not 1 <= value['max_seconds'] <= 300:
        raise ValueError('Session duration must be 1–300 seconds across all runs.')
    allowed = value['allowed_urls']
    if (not isinstance(allowed, list) or not 1 <= len(allowed) <= 10 or
            any(not isinstance(item, str) for item in allowed) or len(set(allowed)) != len(allowed)):
        raise ValueError('Choose 1–10 distinct exact allowed URLs.')
    for item in allowed:
        url(item, value['local_fixture'])
    origins = {(urlsplit(item).scheme, urlsplit(item).hostname, urlsplit(item).port) for item in allowed}
    if len(origins) > 3 or value['url'] not in allowed:
        raise ValueError('Initial URL must be allowed; at most three origins are supported.')
    actions = value['actions']
    if not isinstance(actions, list) or len(actions) > 19:
        raise ValueError('At most 19 actions plus initial observation are supported.')
    if value['capture'] and len(actions) > 4:
        raise ValueError('At most five captures, including the binding observation, are supported.')
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError('Invalid action.')
        op = action.get('operation')
        if op == 'navigate' and set(action) == {'operation', 'url'} and action['url'] in allowed:
            continue
        if op == 'scroll' and set(action) == {'operation', 'direction'} and action['direction'] in ('up', 'down'):
            continue
        if action == {'operation': 'observe'}:
            continue
        raise ValueError('Only exact allowed navigation, one-page scrolling and observation are supported.')
    # Serialize now to reject non-JSON values and detach callers' mutable objects.
    return json.loads(json.dumps(value, allow_nan=False))
