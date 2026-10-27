"""Opt-in local installer retention; never touch live state or recovery receipts."""
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import zipfile

from .host import HOST

SUCCESS = {'complete', 'installed_messages_permission_required'}
TERMINAL = SUCCESS | {'needs_inspection'}


def _write(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    tmp.chmod(0o600)
    tmp.replace(path)


def _plain(path):
    if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Linked or non-regular retention file: ' + str(path))
    s = path.stat()
    return s.st_ino, s.st_mtime_ns, s.st_size


def _receipt(path, roots):
    if path.name != 'install-receipt.json' or not any(r in path.parents for r in roots):
        raise ValueError('Receipt outside retention roots')
    _plain(path)
    return json.loads(path.read_text())


def _payloads(receipt, record):
    db, app = Path(record['database_backup']), Path(record['app_backup'])
    if (db.parent != receipt.parent or app.parent != receipt.parent or
            not db.name.startswith('state-before-') or db.suffix != '.sqlite' or
            app.name != 'previous-app.zip'):
        raise ValueError('Unexpected installation payload path')
    hashes = [record['database_backup_sha256'], record['archive']['archive_sha256']]
    if any(not isinstance(h, str) or len(h) != 64 for h in hashes):
        raise ValueError('Missing installation hashes')
    return [(db, hashes[0]), (app, hashes[1])]


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_pair(receipt):
    """Verify the ready-to-use replacement recovery pair before any retirement."""
    receipt = Path(receipt)
    _plain(receipt)
    record = json.loads(receipt.read_text())
    if record.get('phase') not in SUCCESS or not record.get('completed_at'):
        raise ValueError('Installation is not complete; retain older backups')
    payloads = _payloads(receipt, record)
    identities = [(p, _plain(p)) for p, _ in payloads]
    for p, expected in payloads:
        if _hash(p) != expected:
            raise ValueError('Recovery payload checksum mismatch')
    db, app = [p for p, _ in payloads]
    wal = Path(str(db) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Recovery database has pending writes')
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Recovery database integrity check failed')
    with zipfile.ZipFile(app) as archive:
        if archive.testzip() is not None:
            raise ValueError('Recovery app ZIP integrity check failed')
    for p, identity in identities:
        if _plain(p) != identity:
            raise ValueError('Recovery payload changed during verification')
    return record, identities


def maintain(data, receipt, *, prune=False):
    """Register before installation; prune only after a verified successful update.

    A failed update remains protected until a later successful installation.
    Missing/changed/linked old files are reported, never blindly removed.
    """
    data, receipt = Path(data).absolute(), Path(receipt).absolute()
    policy = data / 'installation-retention.json'
    if not policy.exists():
        return {'status': 'disabled'}
    _plain(policy)
    lock = data / 'installation-retention.lock'
    if lock.is_symlink():
        raise ValueError('Linked retention lock')
    with lock.open('a+b') as stream:
        HOST.lock(stream)
        spec = json.loads(policy.read_text())
        if spec.get('version') != 1 or spec.get('keep') != 1:
            raise ValueError('Unsupported installation retention policy')
        roots = [Path(p) for p in spec['roots']]
        if any(not p.is_absolute() or p.resolve() != p for p in roots):
            raise ValueError('Invalid retention root')
        current = _receipt(receipt, roots)
        receipts = sorted(set(spec.get('receipts', [])) | {str(receipt)})
        spec['receipts'] = receipts
        _write(policy, spec)
        if not prune:
            return {'status': 'registered'}
        records = [(Path(p), _receipt(Path(p), roots)) for p in receipts]
        if any(r.get('started_at', 0) > current.get('started_at', 0) for _, r in records):
            return {'status': 'preserved_newer_installation'}
        current, keeper_identities = verify_pair(receipt)
        spec['keeper'] = str(receipt)
        _write(policy, spec)
        result = {'status': 'complete', 'keeper': str(receipt), 'removed': [], 'preserved': []}
        journal = data / 'installation-retention.jsonl'
        if journal.is_symlink():
            raise ValueError('Linked retention journal')
        with journal.open('a') as log:
            def record(event):
                log.write(json.dumps(dict(event, time=time.time(), keeper=str(receipt))) + '\n')
                log.flush(); os.fsync(log.fileno())
            for old, value in records:
                if old == receipt:
                    continue
                try:
                    if value.get('phase') not in TERMINAL:
                        raise ValueError('Installation still pending')
                    files = []
                    for original, expected in _payloads(old, value):
                        wal = Path(str(original) + '-wal')
                        if wal.exists() and wal.stat().st_size:
                            raise ValueError('Backup has pending database writes')
                        for p in (original, Path(str(original) + '.gz')):
                            if not p.exists() and not p.is_symlink():
                                continue
                            identity = _plain(p)
                            if p.suffix == '.gz':
                                with gzip.open(p, 'rb') as src:
                                    actual = hashlib.file_digest(src, 'sha256').hexdigest()
                            else:
                                actual = _hash(p)
                            if actual != expected:
                                raise ValueError('Superseded backup checksum mismatch')
                            files.append((p, identity))
                        if original.suffix == '.sqlite':
                            for suffix in ('-wal', '-shm'):
                                p = Path(str(original) + suffix)
                                if p.exists() or p.is_symlink():
                                    files.append((p, _plain(p)))
                    for p, identity in files + keeper_identities:
                        if _plain(p) != identity:
                            raise ValueError('Backup changed during retention')
                    for p, identity in files:
                        if _plain(p) != identity:
                            raise ValueError('Backup changed before removal')
                        record({'phase': 'removing', 'path': str(p), 'receipt': str(old)})
                        p.unlink()
                        record({'phase': 'removed', 'path': str(p), 'receipt': str(old)})
                        result['removed'].append(str(p))
                except (ValueError, OSError, KeyError, EOFError, zipfile.BadZipFile) as exc:
                    item = {'receipt': str(old), 'reason': str(exc)}
                    result['preserved'].append(item)
                    record(dict(item, phase='preserved'))
        if result['preserved']:
            result['status'] = 'partial'
        return result
