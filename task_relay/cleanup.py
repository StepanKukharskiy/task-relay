"""List regenerable files, then remove only unchanged entries from that list.

Project artifacts, environments, source, live databases and unique backups are
not garbage just because they are old. They are excluded from this first policy.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from task_relay.relay_paths import PATHS


def identity(path):
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_nlink != 1:
        raise ValueError('Not a standalone regular file.')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return {'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'inode': info.st_ino, 'sha256': h.hexdigest()}


def within(path, root):
    return path.is_relative_to(root) and path.resolve() == path and not path.is_symlink()


def eligible(path, paths, builds=False):
    root, data = paths.install.resolve(), paths.data.resolve()
    if not within(path, root) and not within(path, data):
        return None
    # Private project evidence and user work are never scanned as caches.
    if within(path, data):
        rel = path.relative_to(data)
        if not rel.parts or rel.parts[0] not in ('claude-venv', 'browser-venv'):
            return None
    else:
        rel = path.relative_to(root)
        if any(part in ('.git', '.agents', '.codex', 'projects', 'generated', 'outputs', 'output', 'node_modules') for part in rel.parts):
            return None
    if path.name == '.DS_Store':
        return 'finder-cache'
    if path.suffix == '.pyc' and '__pycache__' in path.parts:
        return 'python-cache'
    if builds and path.is_relative_to(root / 'build'):
        return 'build-output'
    return None


def retired_pairs(paths):
    from task_relay.messages_storage import receipt, digest
    if not paths.state.is_file():
        return {}
    with closing(sqlite3.connect(paths.state.as_uri() + '?mode=ro', uri=True)) as db:
        saved = receipt(db)
    result = {}
    for entry in (saved or {}).get('sources', []):
        keeper = Path(entry['backup'])
        retired = keeper.with_suffix('.retired.sqlite')
        if not all(within(p, paths.data.resolve() / 'backups') and p.is_file() for p in (keeper, retired)):
            continue
        if any(Path(str(p) + '-wal').exists() and Path(str(p) + '-wal').stat().st_size for p in (keeper, retired)):
            continue
        with closing(sqlite3.connect(keeper.as_uri() + '?mode=ro', uri=True)) as a, \
             closing(sqlite3.connect(retired.as_uri() + '?mode=ro', uri=True)) as b:
            if (a.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                    and b.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                    and digest(a) == digest(b) == entry['digest']):
                result[retired] = keeper
    return result


def plan(paths=PATHS, builds=False):
    candidates = {}
    roots = {paths.install.resolve(), paths.data.resolve() / 'claude-venv', paths.data.resolve() / 'browser-venv'}
    for root in roots:
        if not root.is_dir():
            continue
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ('.git', '.agents', '.codex', 'projects', 'generated', 'outputs', 'output', 'node_modules')
                       and not (Path(folder) / d).is_symlink()
                       and (Path(folder) / d).resolve() != paths.data.resolve()]
            for name in files:
                path = Path(folder) / name
                kind = eligible(path, paths, builds)
                if kind:
                    candidates[path] = {'kind': kind}
    for path, keeper in retired_pairs(paths).items():
        candidates[path] = {'kind': 'duplicate-database', 'keeper': str(keeper), 'keeper_identity': identity(keeper)}
    files = []
    for path, details in sorted(candidates.items()):
        try:
            files.append({'path': str(path), **details, **identity(path)})
        except (OSError, ValueError):
            continue
    folder = paths.data / 'cleanup'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = folder / (uuid.uuid4().hex + '.json')
    result = {'version': 1, 'created': time.time(), 'install': str(paths.install.resolve()),
              'data': str(paths.data.resolve()), 'include_builds': builds, 'files': files,
              'bytes': sum(f['bytes'] for f in files)}
    with manifest.open('x') as stream:
        json.dump(result, stream, indent=2)
    manifest.chmod(0o600)
    return manifest, result


def apply(manifest, paths=PATHS):
    manifest = Path(manifest).absolute()
    if not within(manifest, (paths.data / 'cleanup').resolve()):
        raise ValueError('Use a cleanup plan saved by this installation.')
    saved = json.loads(manifest.read_text())
    if saved['install'] != str(paths.install.resolve()) or saved['data'] != str(paths.data.resolve()):
        raise ValueError('The cleanup plan belongs to another installation.')
    pairs = retired_pairs(paths)
    result = {'removed': 0, 'bytes': 0, 'skipped': 0}
    journal = manifest.with_suffix('.receipts.jsonl')
    with journal.open('a') as stream:
        journal.chmod(0o600)
        for row in saved['files']:
            path = Path(row['path'])
            try:
                kind = eligible(path, paths, saved.get('include_builds', False))
                if row['kind'] == 'duplicate-database':
                    keeper = pairs.get(path)
                    if not keeper or str(keeper) != row['keeper'] or identity(keeper) != row['keeper_identity']:
                        raise ValueError('The verified recovery copy changed or is unavailable.')
                elif kind != row['kind']:
                    raise ValueError('This path is not covered by the cleanup policy.')
                if identity(path) != {k: row[k] for k in ('bytes', 'mtime_ns', 'inode', 'sha256')}:
                    raise ValueError('File changed since listing.')
                stream.write(json.dumps({'path': str(path), 'phase': 'removing', 'sha256': row['sha256']}) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
                path.unlink()
                result['removed'] += 1
                result['bytes'] += row['bytes']
                record = {'path': str(path), 'phase': 'removed', 'bytes': row['bytes']}
            except (OSError, ValueError) as exc:
                result['skipped'] += 1
                record = {'path': str(path), 'phase': 'skipped', 'reason': str(exc)}
            stream.write(json.dumps(record) + '\n')
            stream.flush()
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('plan')
    listing.add_argument('--include-builds', action='store_true', help='Also list generated files under the installation build/ folder')
    deleting = commands.add_parser('apply')
    deleting.add_argument('manifest', type=Path)
    args = parser.parse_args()
    if args.command == 'plan':
        manifest, report = plan(builds=args.include_builds)
        print(json.dumps({'manifest': str(manifest), 'files': len(report['files']), 'bytes': report['bytes']}, indent=2))
    else:
        print(json.dumps(apply(args.manifest), indent=2))


if __name__ == '__main__':
    main()
