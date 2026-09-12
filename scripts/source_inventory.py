"""Read-only source/release inventory; explicit candidates for a local Git baseline."""
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def inventory(root=ROOT):
    root=Path(root).resolve();policy=json.loads((root/'source_inventory.json').read_text())
    files={}
    for group in policy['groups']:
        for pattern in group['patterns']:
            for path in root.glob(pattern):
                if not path.is_file():continue
                rel=path.relative_to(root).as_posix()
                if any(fnmatch.fnmatch(rel,p) for p in group.get('exclude',[])):continue
                if any(part in policy['excluded_roots'] or part=='__pycache__' or part.startswith('.venv') for part in path.relative_to(root).parts) and rel not in policy['maintained_exceptions']:continue
                if any(p.is_symlink() for p in (path,*path.parents) if p!=root.parent):raise ValueError('Source inventory refuses symlinks: '+rel)
                if path.stat().st_nlink!=1:raise ValueError('Source inventory refuses linked files: '+rel)
                if rel in files:raise ValueError('Overlapping source groups: '+rel)
                raw=path.read_bytes()
                files[rel]=dict(path=rel,kind=group['kind'],release=group['release'],bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    if any(p not in files for p in policy['maintained_exceptions']):raise ValueError('Missing maintained asset')
    return dict(version=policy['version'],root=str(root),files=[files[k] for k in sorted(files)],
                release_note=policy['release_note'],excluded_roots=policy['excluded_roots'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--paths',action='store_true',help='NUL-separated reviewed source paths for git pathspec input')
    args=parser.parse_args();value=inventory()
    if args.paths:
        import sys
        sys.stdout.buffer.write(b''.join(f['path'].encode()+b'\0' for f in value['files']))
    else:print(json.dumps(value,indent=2))

if __name__=='__main__':main()
