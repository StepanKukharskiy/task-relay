"""Display saved inputs without dispatching work or inventing delivery history."""
import json
from pathlib import Path


def bounded_messages(items):
    result = []
    remaining = 100_000
    for item in reversed(items):
        item = dict(item)
        encoded = json.dumps(item, ensure_ascii=False).encode('utf-8')
        if len(encoded) > 24_000:
            item['text'] = item['text'][:8000] + '\n\n[Display excerpt; the complete message remains in saved history.]'
            encoded = json.dumps(item, ensure_ascii=False).encode('utf-8')
        if len(encoded) > remaining:
            break
        remaining -= len(encoded)
        result.append(item)
    return list(reversed(result))


def codex_messages(path):
    """Read complete message records from a bounded tail of the known rollout."""
    if not path:
        return []
    try:
        with Path(path).open('rb') as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 2_000_000))
            if size > 2_000_000:
                stream.readline()
            lines = stream.read(2_000_000).splitlines(keepends=True)
    except OSError:
        return []
    messages = []
    for line in lines:
        if not line.endswith(b'\n'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        payload = event.get('payload')
        if not isinstance(payload, dict) or event.get('type') != 'response_item':
            continue
        if payload.get('type') != 'message' or payload.get('role') not in ('user', 'assistant'):
            continue
        content = payload.get('content')
        if not isinstance(content, list):
            continue
        text = '\n'.join(item['text'] for item in content if isinstance(item, dict)
                         and isinstance(item.get('text'), str)
                         and item.get('type') in ('input_text', 'output_text', 'text'))
        if text:
            messages.append({'role': payload['role'], 'text': text,
                             'channel': 'codex', 'id': 'rollout:' + str(len(messages))})
    return messages[-80:]


def messages(db, task, events):
    if task['backend'] == 'codex':
        native = codex_messages(task['path'])
        if native:
            # Native messages are ordered by the source log. Local unsubmitted
            # inputs are separate and cannot masquerade as accepted Codex turns.
            pending = db.execute("SELECT * FROM desktop_commands WHERE task_id=? AND status!='accepted' ORDER BY created", (task['id'],))
            return native + [dict(id=r['request_id'], role='user', text=r['prompt'],
                                  channel='desktop', status=r['status']) for r in pending]
    result = [dict(e, role='assistant') for e in events]
    commands = list(db.execute('SELECT * FROM desktop_commands WHERE task_id=? ORDER BY created', (task['id'],)))
    jobs = list(db.execute('SELECT * FROM backend_jobs WHERE thread_id=? ORDER BY created_at', (task['id'],)))
    represented = {r['incoming_id'] for r in commands}
    inputs = [(r['request_id'], r['prompt'], r['status'], 'desktop', 'desktop:' + r['request_id'] + ':') for r in commands]
    inputs += [(r['id'], r['prompt'], r['status'], 'relay', 'backend:' + r['id'] + ':') for r in jobs if r['update_id'] not in represented]
    # Place an input immediately before its exact receipt/result identity. Do
    # not fabricate timestamps for the legacy outbox, which never stored them.
    for ident, text, status, channel, prefix in inputs[-80:]:
        entry = dict(id=ident, text=text, role='user', status=status, channel=channel)
        at = next((i for i, e in enumerate(result) if e['id'].startswith(prefix)), len(result))
        result.insert(at, entry)
    return result
