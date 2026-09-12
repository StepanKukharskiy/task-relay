"""Parsers for the supplied chronological Markdown and attempt-ledger formats."""
import re
import time
from pathlib import Path
from .store import digest, encoded

HEADER = re.compile(r'^### (\d{4,}) · (User|Agent)(?: \(([^)]+)\))?\s*$')
STAMP = re.compile(r'^\*\*Timestamp:\*\* `[^`]+` \(`([^`]+)`\)\s*$')
ENTRY = re.compile(r'^- \*\*([A-Z]\d+[a-z]?)\s+[—–-]\s+(.+?)\*\*(.*)$')
LINK = re.compile(r'\]\((?:<([^>]+)>|([^\s)]+))\)')


def artifacts(text):
    return [{'reference': a or b, 'version': 'current-link-not-historical-snapshot'}
            for a, b in LINK.findall(text)]


def parse(text, kind):
    lines = text.splitlines(keepends=True)
    if kind == 'guide':
        return [dict(ordinal=i + 1, role='guide', timestamp=None, line_start=i + 1,
                     line_end=min(i + 80, len(lines)), text=''.join(lines[i:i + 80]),
                     details={'historical_version': False}) for i in range(0, len(lines), 80)]
    if kind == 'ledger':
        entries, seen, section = [], set(), None
        for i, line in enumerate(lines):
            if line.startswith('## '):
                section = line.strip()[3:]
            match = ENTRY.match(line.rstrip('\r\n'))
            if match:
                name = match[1]
                if name in seen:
                    raise ValueError(f'Duplicate ledger ID {name} at line {i + 1}')
                seen.add(name)
                entries.append(dict(ordinal=len(entries) + 1, role='ledger', timestamp=None,
                                    line_start=i + 1, line_end=i + 1, text=line,
                                    details={'message_id': name, 'section': section, 'human_interventions': 'not_observed',
                                             'artifacts': artifacts(line)}))
        if not entries:
            raise ValueError('No supported ledger entries found')
        return entries
    if kind != 'conversation':
        raise ValueError('Supported source types: conversation, ledger, guide')
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == '# Chronological Transcript')
    except StopIteration:
        raise ValueError('Missing chronological transcript boundary') from None
    headers, fence = [], None
    for i in range(start + 1, len(lines)):
        line = lines[i].rstrip('\r\n')
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        match = HEADER.match(line) if fence is None else None
        if match:
            # Require the export envelope, not arbitrary Markdown headings in a message.
            if i + 2 >= len(lines) or lines[i + 1].strip() or not STAMP.match(lines[i + 2].strip()):
                raise ValueError(f'Malformed message envelope at line {i + 1}')
            if int(match[1]) != len(headers) + 1:
                raise ValueError(f'Nonsequential or nested message header at line {i + 1}')
            previous = i - 1
            while previous >= start and (not lines[previous].strip() or re.fullmatch(r'## \d{4}-\d\d-\d\d', lines[previous].strip())):
                previous -= 1
            if headers and lines[previous].strip() != '---':
                raise ValueError(f'Missing message separator at line {i + 1}')
            headers.append((i, match, STAMP.match(lines[i + 2].strip())[1]))
    if not headers:
        raise ValueError('No message records found')
    expected = re.search(r'Public messages exported: `(\d+)`', ''.join(lines[:start]))
    if expected and int(expected[1]) != len(headers):
        raise ValueError(f'Export declares {expected[1]} messages; parsed {len(headers)}')
    result = []
    for index, (i, match, stamp) in enumerate(headers):
        end = headers[index + 1][0] if index + 1 < len(headers) else len(lines)
        body = ''.join(lines[i + 4:end]).rstrip()
        if body.endswith('---'):
            body = body[:-3].rstrip()
        # Date headings between records are export structure.
        body = re.sub(r'\n---\s*\n+## \d{4}-\d\d-\d\d\s*$', '', body)
        interruption = match[2] == 'User' and body.strip().startswith('<turn_aborted>') and body.strip().endswith('</turn_aborted>')
        result.append(dict(ordinal=index + 1, role='interruption' if interruption else
                           ('user' if match[2] == 'User' else 'assistant'), timestamp=stamp,
                           line_start=i + 1, line_end=end, text=body,
                           details={'message_id': match[1], 'export_role': match[2],
                                    'channel': match[3], 'artifacts': artifacts(body)}))
    return result


def import_file(store, dataset, workflow, path, kind):
    path = Path(path).expanduser().resolve(strict=True)
    raw = path.read_bytes()
    records = parse(raw.decode('utf-8'), kind)
    sha = digest(raw)
    sid = 'source:' + digest((str(path) + '\0' + kind + '\0' + sha).encode())
    exists = store.db.execute('SELECT 1 FROM sources WHERE id=?', (sid,)).fetchone() is not None
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?)',
                         (sid, str(path), sha, kind, raw, encoded({'schema_version': 1,
                          'artifact_links': artifacts(raw.decode('utf-8')),
                          'approval_index_authoritative': False}), time.time()))
        store.db.execute('INSERT INTO dataset_sources(dataset,workflow,source_id,selected_at) VALUES (?,?,?,?) '
                         'ON CONFLICT(dataset,workflow,source_id) DO UPDATE SET selected_at=excluded.selected_at',
                         (dataset, workflow, sid, time.time()))
        for record in records:
            eid = sid.replace('source:', 'event:') + ':' + str(record['ordinal'])
            store.db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?)',
                             (eid, sid, record['ordinal'], record['role'], record['timestamp'],
                              record['line_start'], record['line_end'], record['text'], encoded(record['details'])))
    return {'source_id': sid, 'sha256': sha, 'records': len(records), 'duplicate': exists,
            'roles': {role: sum(r['role'] == role for r in records) for role in sorted({r['role'] for r in records})}}
