"""One working-image projection and pre-dispatch capacity boundary for all roles.

Original provider journals stay immutable. Working history retains one copy of
each representation; explicit reinspection moves that copy to the new exchange.
"""
import base64
import copy
import hashlib
import json
from .workers import atomic
from .runtime_outcomes import Hold

MAX_WIRE_BYTES = 16_000_000
RETAINED_IMAGE_BYTES = 8_000_000


def image_data(part):
    inline=part.get('inlineData', {})
    if inline.get('mimeType', '').startswith('image/'):
        return inline['mimeType'], inline['data']
    url=part.get('image_url')
    if isinstance(url, dict):url=url.get('url')
    if isinstance(url, str) and url.startswith('data:image/') and ';base64,' in url:
        mime, data=url[5:].split(';base64,', 1)
        return mime, data
    return None


def project(messages, folder, max_image_bytes=RETAINED_IMAGE_BYTES):
    """Keep the latest inspection batch intact and bound older retained pixels."""
    result=copy.deepcopy(messages);seen=set();duplicates=0;archived=0;retained_bytes=0;latest=None
    for number,message in reversed(list(enumerate(result))):
        parts=message.get('parts', message.get('content', []))
        if not isinstance(parts, list):continue
        for index in reversed(range(len(parts))):
            part=parts[index]
            if not isinstance(part, dict):continue
            data=image_data(part)
            if not data:continue
            if latest is None:latest=number
            mime, encoded=data;raw=base64.b64decode(encoded, validate=True)
            sha=hashlib.sha256(raw).hexdigest();key=(mime, sha)
            folder.mkdir(parents=True, exist_ok=True)
            path=folder/(sha+'.json')
            value=dict(sha256=sha, media_type=mime, data=encoded)
            if path.exists():
                if json.loads(path.read_text())!=value:raise ValueError('Archived image representation changed')
            else:atomic(path, value)
            duplicate=key in seen
            expired=number!=latest and retained_bytes+len(encoded)>max_image_bytes
            if duplicate or expired:
                text='Exact image '+sha+(' is retained at its latest inspection exchange.' if duplicate else ' is archived outside the bounded working pixel context; use image_view on its declared source to inspect it again.')+' Prior delivery remains in the original journal.'
                parts[index]=dict(text=text) if 'parts' in message else dict(type='input_text' if part.get('type')=='input_image' else 'text', text=text)
                if duplicate:duplicates+=1
                else:archived+=1
            else:retained_bytes+=len(encoded)
            seen.add(key)
    return result, dict(unique_images=len(seen), duplicate_images_removed=duplicates, archived_images=archived, retained_pixel_bytes=retained_bytes)


def prepare(transport, payload, client, control, number, *, owner=None, archive=None, max_wire_bytes=MAX_WIRE_BYTES):
    """Validate the actual next message before provider dispatch, never afterward."""
    payload=copy.deepcopy(payload)
    original=len(json.dumps(payload).encode())
    key=transport.key
    if archive:
        original_history=len(json.dumps(payload[key]).encode())
        payload[key]=archive.view(payload[key]) if transport.provider=='gemini' else archive.native_view(payload[key],transport.provider)
        atomic(control/f'context-{number:02d}.json',dict(schema='relay.browser-context.v1',original_history_bytes=original_history,submitted_history_bytes=len(json.dumps(payload[key]).encode()),archived_results=len(archive.entries),browser_actions_replayed=0))
    if owner and owner.grant.get('working_context_version') in (1,2):
        from .working_context import size
        original_view=payload[key];head=original_view[:transport.head]
        payload[key]=head+owner.working_view.project(original_view[len(head):],transport.provider,version=owner.grant['working_context_version'],history_available=not owner.pending_submission)
        atomic(control/f'working-context-{number:02d}.json',dict(original_text_bytes=size(original_view),submitted_text_bytes=size(payload[key]),provider=transport.provider))
    payload[transport.key], images=project(payload[transport.key], control/'context-images')
    wire=client.prepare_request(payload) if transport.provider=='codex' and hasattr(client, 'prepare_request') else payload
    serialized=(json.dumps(wire,ensure_ascii=False)+'\n').encode() if transport.provider=='codex' else json.dumps(wire).encode()
    size=len(serialized)
    receipt=dict(version=1, provider=transport.provider, logical_bytes=original,
                 working_bytes=len(json.dumps(payload).encode()), wire_bytes=size,
                 wire_sha256=hashlib.sha256(serialized).hexdigest(),
                 measurement='bootstrap_aggregate' if transport.provider=='codex' and 'instructions' in wire else 'prepared_request',
                 provider_retained_tokens=None, retained_context_limit_known=False, **images)
    atomic(control/f'dispatch-context-{number:02d}.json', receipt)
    if size>max_wire_bytes:
        raise Hold('transport_capacity', 'Prepared model dispatch exceeds the registered wire-byte ceiling; no request dispatched', phase='observe')
    return payload
