"""Retention for runner-owned offline fixtures, never live execution storage."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from task_relay.host import Host

MARKER = 'lifecycle-retention.json'
RETIRED = 'retired-evidence.json'
OWNER = 'task-relay.offline-lifecycle'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.retention-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def lock(path):
    if path.is_symlink():
        raise ValueError('Linked lifecycle lock refused')
    with path.open('a+b') as stream:
        Host().lock(stream)
        yield


def register(root):
    write(root / MARKER, dict(owner=OWNER, version=1, root=str(root),
                              started=time.time_ns(), state='running'))


def complete(root):
    marker = json.loads((root / MARKER).read_text())
    marker.update(state='completed', report_sha256=sha(root / 'report.json'),
                  audit_sha256=sha(root / 'AUDIT.md'))
    write(root / MARKER, marker)


def receipt(root):
    """An unfinished, copied, modified or legacy directory is not cleanup authority."""
    for name in (MARKER, 'report.json', 'AUDIT.md'):
        if (root / name).is_symlink():
            raise ValueError('Linked lifecycle receipt refused')
    marker = json.loads((root / MARKER).read_text())
    if (marker.get('owner') != OWNER or marker.get('version') != 1 or
            marker.get('root') != str(root) or marker.get('state') != 'completed'):
        raise ValueError('Not a completed runner-owned lifecycle directory')
    if (sha(root / 'report.json') != marker['report_sha256'] or
            sha(root / 'AUDIT.md') != marker['audit_sha256']):
        raise ValueError('Lifecycle receipt changed')
    report = json.loads((root / 'report.json').read_text())
    if not report.get('scope', '').startswith('Controlled offline shared lifecycle') or not report.get('finished'):
        raise ValueError('Not a finished offline lifecycle report')
    return marker, report


def retire(root, latest):
    marker, report = receipt(root)
    record_path = root / RETIRED
    if record_path.is_symlink():
        raise ValueError('Linked lifecycle retirement refused')
    if record_path.exists():
        record = json.loads(record_path.read_text())
        if record['report_sha256'] != marker['report_sha256']:
            raise ValueError('Retirement belongs to another report')
        if record.get('state') not in ('retiring', 'retired'):
            raise ValueError('Unknown retirement state')
        if record['state'] == 'retired':
            return None
    else:
        trees = []
        for group in report['groups']:
            name = group['group']
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
                raise ValueError('Unsafe lifecycle group')
            parent = root / name
            tree = parent / 'journals'
            if parent.is_symlink() or tree.is_symlink():
                raise ValueError('Linked lifecycle fixture refused')
            if tree.exists():
                trees.append(tree)
        # Check all candidates before deleting any. Unregistered files are not fixtures.
        removed = 0
        allocated = 0
        for tree in trees:
            for path in tree.rglob('*'):
                if path.is_symlink():
                    raise ValueError('Linked lifecycle fixture member refused')
                if path.is_file():
                    name = path.relative_to(root).as_posix()
                    digest = sha(path)
                    if report['evidence'].get(name) != digest:
                        raise ValueError('Unregistered or modified lifecycle fixture: ' + name)
                    removed += 1
                    stat = path.stat()
                    allocated += stat.st_blocks * 512 if hasattr(stat, 'st_blocks') else stat.st_size
        record = dict(version=1, state='retiring', report_sha256=marker['report_sha256'],
                      latest=str(latest), trees=[t.relative_to(root).as_posix() for t in trees],
                      removed_files=removed, allocated_bytes=allocated,
                      limitation='Original report is unchanged. Retired fixture bytes are unavailable; this is not a full-evidence receipt.')
        write(record_path, record)  # Durable intent precedes irreversible removal.
    for relative in record['trees']:
        parts = Path(relative).parts
        if (len(parts) != 2 or parts[1] != 'journals' or
                parts[0] not in {g['group'] for g in report['groups']} or
                not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', parts[0])):
            raise ValueError('Unsafe retirement path')
        tree = root / relative
        if tree.is_symlink() or tree.parent.is_symlink():
            raise ValueError('Linked retirement path')
        if tree.exists():
            # Also validate surviving members when resuming an interrupted deletion.
            for path in tree.rglob('*'):
                if path.is_symlink():
                    raise ValueError('Linked retirement member')
                if path.is_file() and report['evidence'].get(path.relative_to(root).as_posix()) != sha(path):
                    raise ValueError('Fixture changed during retirement')
            shutil.rmtree(tree)
    record['state'] = 'retired'
    write(record_path, record)
    return record


def prune(parent):
    """Keep newest completed run plus active/interrupted runs; old logs always stay."""
    parent = Path(parent).resolve()
    result = dict(retired=[], skipped=[])
    try:
        with lock(parent / '.lifecycle-retention.lock'):
            with contextlib.ExitStack() as locks:
                runs = []
                for root in sorted(parent.iterdir()):
                    if root.is_symlink() or not root.is_dir() or not (root / MARKER).exists():
                        continue
                    try:
                        locks.enter_context(lock(root / '.lifecycle.lock'))
                        marker, report = receipt(root)
                        runs.append((root, marker, report))
                    except (OSError, ValueError, KeyError) as exc:
                        result['skipped'].append(dict(path=str(root), reason=str(exc)))
                if not runs:
                    return result
                latest = max(runs, key=lambda item: (item[2]['finished'], item[1]['started'], str(item[0])))[0]
                result['latest'] = str(latest)
                for root, _, _ in runs:
                    if root == latest:
                        continue
                    try:
                        record = retire(root, latest)
                        if record is not None:
                            result['retired'].append(dict(path=str(root), files=record['removed_files'],
                                                         allocated_bytes=record['allocated_bytes']))
                    except (OSError, ValueError, KeyError) as exc:
                        result['skipped'].append(dict(path=str(root), reason=str(exc)))
    except BlockingIOError:
        result['skipped'].append(dict(path=str(parent), reason='Another cleanup owns the retention lock'))
    return result
