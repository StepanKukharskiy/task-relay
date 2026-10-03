"""Read-only local Codex/project capture adapter; no UI automation or dispatch."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime

from .filesystem import FILES, Grant
from .host import HOST

SKIP = {'.git', 'node_modules', '__pycache__', 'private', 'credentials'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_db(path):
    # Opening the root through the host grant also rejects linked ancestors.
    with FILES.open(Grant(path.parent, 'selected Codex history'), path.name):
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db


def text_parts(content):
    return '\n'.join(p.get('text', '') for p in content if isinstance(p, dict)
                     and p.get('type') in ('text', 'Text', 'input_text', 'output_text'))


def rollout_lines(stream, hasher):
    """Hash oversized tool/media events without loading their payload into memory."""
    number = 0
    while True:
        head = stream.readline(8192)
        if not head:
            return
        number += 1
        hasher.update(head)
        relevant = (re.search(rb'"type"\s*:\s*"session_meta"', head[:300]) or
                    (re.search(rb'"type"\s*:\s*"event_msg"', head[:300]) and
                     (re.search(rb'"type"\s*:\s*"task_started"', head[:500]) or
                      re.search(rb'"type"\s*:\s*"(?:UserMessage|AgentMessage)"', head[:1500]))))
        chunks, size, tail = [head], len(head), head
        while not tail.endswith(b'\n'):
            tail = stream.readline(1048576)
            if not tail:
                break
            hasher.update(tail)
            if relevant:
                size += len(tail)
                if size > 16000000:
                    raise ValueError('Canonical message exceeds capture limit')
                chunks.append(tail)
        # Small records can be parsed normally. Large irrelevant events contain
        # tools/reasoning/media, which are outside the stated collection scope.
        if relevant or head.endswith(b'\n'):
            yield number, b''.join(chunks)


def capture(project, codex_home, excluded=(), max_files=10000, max_text_bytes=2000000):
    HOST.require_posix('Local Codex project context capture')
    project, codex_home = Path(project).absolute(), Path(codex_home).absolute()
    grant = Grant(project, 'user selected project context analysis')
    with FILES.root(grant):
        pass
    for name in excluded:
        grant.parts(name)
    state = read_db(codex_home / 'state_5.sqlite')
    history = read_db(codex_home / 'thread_history_1.sqlite')
    sources, threads, files, omissions = [], [], [], []
    text_bytes = 0
    try:
        rows = state.execute('SELECT id,name,title,rollout_path,created_at,updated_at,archived '
                             'FROM threads WHERE cwd=? ORDER BY created_at,id', (str(project),)).fetchall()
        if not rows:
            raise ValueError('No Codex chats matched the exact selected project root')
        for row in rows:
            thread = dict(row)
            threads.append(thread)
            by_id = {}
            for item_row in history.execute("SELECT * FROM thread_items WHERE thread_id=? AND "
                                            "item_type IN ('userMessage','agentMessage') ORDER BY rollout_ordinal", (row['id'],)):
                item = json.loads(item_row['item_json'])
                role = 'user' if item['type'] == 'userMessage' else 'assistant'
                if role == 'assistant' and item.get('phase') != 'final_answer':
                    continue
                text = item.get('text', '') if role == 'assistant' else text_parts(item.get('content', []))
                if text.strip():
                    by_id[item_row['item_id']] = dict(kind='message', role=role, text=text,
                        thread_id=row['id'], title=row['name'] or row['title'], item_id=item_row['item_id'],
                        turn_id=item_row['turn_id'], timestamp_ms=item_row['created_at_ms'],
                        ordinal=item_row['rollout_ordinal'], locator='thread_items:' + row['id'] + ':' + item_row['item_id'])
            rollout = Path(row['rollout_path'])
            relative = rollout.relative_to(codex_home)
            rgrant = Grant(codex_home, 'selected project chat rollout', reads=frozenset({relative.as_posix()}))
            hasher, turn, base = hashlib.sha256(), None, 0
            with FILES.open(rgrant, relative) as fd, os.fdopen(os.dup(fd), 'rb') as stream:
                before = os.fstat(fd)
                for line_number, line in rollout_lines(stream, hasher):
                    event = json.loads(line)
                    p = event.get('payload', {})
                    if event.get('type') == 'session_meta':
                        base = (p.get('history_base') or {}).get('end_ordinal_exclusive', 0)
                    if event.get('type') != 'event_msg':
                        continue
                    if p.get('type') == 'task_started':
                        turn = p.get('turn_id')
                    if p.get('type') != 'item_completed':
                        continue
                    item = p.get('item', {})
                    role = {'UserMessage': 'user', 'AgentMessage': 'assistant'}.get(item.get('type'))
                    if role is None or (role == 'assistant' and item.get('phase') != 'final_answer'):
                        continue
                    text = text_parts(item.get('content', []))
                    if not text.strip() or text.lstrip().startswith(('<environment_context>', '# AGENTS.md instructions', '<external_codex_apps_open_page>')):
                        continue
                    iid = item.get('id')
                    if not iid:
                        raise ValueError('Canonical chat event has no message identity')
                    if iid in by_id:
                        if by_id[iid]['text'] != text:
                            raise ValueError('History projection conflicts with canonical rollout message')
                        continue
                    timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')).timestamp() * 1000
                    by_id[iid] = dict(kind='message', role=role, text=text, thread_id=row['id'],
                        title=row['name'] or row['title'], item_id=iid, turn_id=p.get('turn_id') or turn,
                        timestamp_ms=p.get('started_at_ms') or timestamp, ordinal=base + line_number,
                        locator=str(rollout) + ':' + str(line_number))
                after = os.fstat(fd)
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Chat changed during capture; take a fresh snapshot before analysis')
            thread['rollout_sha256'] = hasher.hexdigest()
            thread['message_count'] = len(by_id)
            sources.extend(sorted(by_id.values(), key=lambda s: (s['timestamp_ms'] or 0, s['ordinal'])))
        for folder, dirs, names in os.walk(project, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in SKIP and not (Path(folder)/d).is_symlink())
            for name in sorted(names):
                path = Path(folder) / name
                rel = path.relative_to(project).as_posix()
                if name.startswith('.') or path.is_symlink() or not path.is_file():
                    continue
                if rel in excluded:
                    omissions.append({'path': rel, 'reason': 'explicit exclusion'})
                    continue
                info = path.stat()
                files.append({'path': rel, 'bytes': info.st_size, 'modified_ns': info.st_mtime_ns})
                if len(files) > max_files:
                    raise ValueError('Project file inventory exceeds capture limit')
                if path.suffix.lower() == '.md' and (rel.startswith(('wiki/', 'exports/')) or rel == 'AGENTS.md'):
                    raw = FILES.read(grant, rel, max_text_bytes)
                    text_bytes += len(raw)
                    if text_bytes > max_text_bytes:
                        raise ValueError('Project text exceeds capture budget; nothing silently truncated')
                    sources.append({'kind': 'document', 'path': rel, 'locator': str(path),
                                    'sha256': digest(raw), 'text': raw.decode('utf-8')})
    finally:
        state.close()
        history.close()
    for index, source in enumerate(sources, 1):
        source['id'] = 's' + str(index).zfill(4)
        source['text_sha256'] = digest(source['text'].encode())
    return {'schema_version': 1, 'project': str(project), 'adapter': 'local-codex-project-v1',
            'threads': threads, 'sources': sources, 'files': files, 'omissions': omissions,
            'limitations': ['User messages and assistant final answers only; tools and reasoning excluded',
                            'Native file contents and media not revalidated',
                            'Assistant reports do not establish acceptance',
                            'Local database schema adapter; not a general ChatGPT history API']}
