"""Read-only desktop summary of recorded tokens and Relay-owned storage."""
from contextlib import closing
from datetime import datetime
from collections import defaultdict
import os
from pathlib import Path
import sqlite3
import stat
import time

from .relay_paths import PATHS
from . import usage_tracker


def _allocated_size(info):
    blocks = getattr(info, 'st_blocks', None)
    return max(0, blocks * 512 if blocks is not None else info.st_size)


def _folder_size(folder, deadline, max_entries, clock):
    """Never follow symlinks; partial scans are lower bounds, never exact totals."""
    folder = Path(folder)
    pending = [folder]
    seen = set()
    total = entries = 0
    while pending:
        if entries >= max_entries or clock() >= deadline:
            return {'bytes': total, 'complete': False}
        path = pending.pop()
        try:
            info = path.lstat()
        except FileNotFoundError:
            if path == folder:
                return {'bytes': 0, 'complete': True}
            return {'bytes': total, 'complete': False}
        except OSError:
            return {'bytes': total, 'complete': False}
        if path == folder and not stat.S_ISDIR(info.st_mode):
            return {'bytes': total, 'complete': False}
        identity = (info.st_dev, info.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        entries += 1
        total += _allocated_size(info)
        if stat.S_ISDIR(info.st_mode):
            try:
                with os.scandir(path) as children:
                    pending.extend(Path(child.path) for child in children)
            except OSError:
                return {'bytes': total, 'complete': False}
    return {'bytes': total, 'complete': True}


def _storage(paths, clock=time.monotonic, seconds=3, max_entries=150000):
    deadline = clock() + seconds
    folders = []
    for name, path in (('Data', paths.data), ('Workspaces', paths.workspaces), ('Generated', paths.generated)):
        result = _folder_size(path, deadline, max_entries, clock)
        folders.append({'name': name, 'path': str(path), **result})
    return {'bytes': sum(folder['bytes'] for folder in folders),
            'complete': all(folder['complete'] for folder in folders), 'folders': folders}


def _source_folder(paths):
    root = paths.data.parent
    if (root / 'source_inventory.json').is_file() and (root / 'pyproject.toml').is_file() and (root / 'task_relay').is_dir():
        return {'path': str(root), **_folder_size(root, time.monotonic() + 3, 150000, time.monotonic)}
    return None


def _tokens(paths, clock=time.monotonic):
    empty = {'total': None, 'input': None, 'output': None, 'records': 0,
             'unmeasured': 0, 'indexing_enabled': False, 'oldest_source_check': None,
             'relay_total': None, 'relay_api_total': None, 'relay_records': 0,
             'relay_unmeasured': 0,
             'status': 'No usage ledger at this data location.'}
    try:
        if not stat.S_ISREG(paths.state.stat().st_mode):
            return {**empty, 'status': 'Usage data is not a regular database file.'}
    except FileNotFoundError:
        return empty
    except OSError:
        return {**empty, 'status': 'Recorded usage could not be read at this data location.'}
    try:
        with closing(sqlite3.connect(paths.state.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'usage_events', 'usage_health'} <= names:
                return empty
            deadline = clock() + 4
            db.set_progress_handler(lambda: int(clock() >= deadline), 10000)
            value = usage_tracker.report(db, days=7)
            start = datetime.fromisoformat(value['start_utc']).timestamp()
            end = datetime.fromisoformat(value['end_utc']).timestamp()
            relay = db.execute('''SELECT COUNT(*),
                  SUM(json_extract(counts,'$.total_tokens')),
                  SUM(CASE WHEN source='relay_api' THEN json_extract(counts,'$.total_tokens') END),
                  SUM(CASE WHEN json_extract(counts,'$.total_tokens') IS NULL THEN 1 ELSE 0 END)
                  FROM usage_events WHERE occurred>=? AND occurred<=? AND source LIKE 'relay_%' ''',
                               (start, end)).fetchone()
            row = db.execute("SELECT value FROM kv WHERE key='usage_tracking_enabled'").fetchone() if 'kv' in names else None
            sources = [source['checked'] for source in value['sources'] if source.get('checked')]
            def summed(field):
                values = [group[field] for group in value['groups'] if group[field] is not None]
                return sum(values) if values else None
            return {'total': summed('total_tokens'), 'input': summed('input_tokens'),
                    'output': summed('output_tokens'), 'records': value['records'],
                    'unmeasured': value['unmeasured_records'],
                    'relay_total': relay[1], 'relay_api_total': relay[2],
                    'relay_records': relay[0], 'relay_unmeasured': relay[3],
                    'indexing_enabled': bool(row and row[0] == 'true'),
                    'oldest_source_check': min(sources) if sources else None,
                    'status': 'Recorded Relay calls and indexed local Codex/Claude sessions, including activity outside Relay; not a bill or account quota.'}
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return {**empty, 'status': 'Recorded usage could not be read at this data location.'}


def summary(paths=PATHS):
    return {'tokens': _tokens(paths), 'storage': _storage(paths),
            'source_folder': _source_folder(paths)}


def breakdown(paths=PATHS, seconds=5, max_entries=200000, clock=time.monotonic):
    """Read-only allocated-byte categories; never follow links or guess cleanup safety."""
    candidate = paths.data.parent
    source = ((candidate / 'source_inventory.json').is_file() and
              (candidate / 'pyproject.toml').is_file() and (candidate / 'task_relay').is_dir())
    root = candidate if source else paths.data
    names = {
        'orchestrator': 'Orchestrator workspaces and artifacts',
        'backups': 'Recovery backups',
        'state.sqlite': 'Live task database',
        'claude-venv': 'Claude environment',
        'desktop-build': 'Desktop build output',
        'outputs': 'Logs and exported outputs',
        '.git': 'Git history',
    }
    totals = defaultdict(int)
    pending = [root]
    seen = set()
    entries = 0
    complete = True
    deadline = clock() + seconds
    while pending:
        if entries >= max_entries or clock() >= deadline:
            complete = False
            break
        path = pending.pop()
        try:
            info = path.lstat()
        except OSError:
            complete = False
            continue
        identity = (info.st_dev, info.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        entries += 1
        parts = path.relative_to(root).parts
        if source:
            if parts and parts[0] == paths.data.name:
                key = parts[1] if len(parts) > 1 else 'other-data'
            elif parts[:3] == ('desktop', 'src-tauri', 'target'):
                key = 'desktop-build'
            elif parts and parts[0] in ('outputs', '.git'):
                key = parts[0]
            else:
                key = 'other-source'
        else:
            key = parts[0] if parts else 'other-data'
        if key not in names and key != 'other-source':
            key = 'other-data'
        totals[key] += _allocated_size(info)
        if stat.S_ISDIR(info.st_mode):
            try:
                with os.scandir(path) as children:
                    pending.extend(Path(child.path) for child in children)
            except OSError:
                complete = False
    labels = {'other-data': 'Other Relay data', 'other-source': 'Other source files'}
    return {'root': str(root), 'complete': complete,
            'categories': [{'name': labels.get(key, names.get(key, key)), 'bytes': size}
                           for key, size in sorted(totals.items(), key=lambda item: item[1], reverse=True)]}
