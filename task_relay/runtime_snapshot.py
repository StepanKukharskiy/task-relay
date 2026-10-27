"""Exact private runtime copies; no installation, refresh or historical rebinding."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import re


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def derived_cache(path):
    """Only regular PEP 3147 caches with a retained source sibling are derived.

    Sourceless bytecode, links, unknown files and all source remain pinned.
    Version 2 is used only with the shared source-only interpreter launch policy.
    """
    path=Path(path)
    if path.parent.name!='__pycache__' or path.is_symlink() or not path.is_file():return False
    match=re.fullmatch(r'(.+?)\.[\w-]+(?:\.opt-[0-9]+)?\.pyc',path.name)
    if not match:return False
    source=path.parent.parent/(match[1]+'.py')
    return source.is_file() and not source.is_symlink() and not path.parent.is_symlink()


def inventory(root,version=1):
    root=Path(root).resolve();result={}
    for p in sorted(root.rglob('*')):
        if version==2 and derived_cache(p):continue
        name=str(p.relative_to(root))
        if p.is_symlink():
            target=p.resolve()
            if not target.is_relative_to(root):
                if target.exists():raise ValueError('Runtime link escapes snapshot: '+name)
                # Preserve inert packaging links exactly; never dereference or
                # copy their destinations. If a destination appears, verification
                # fails before use. The native sandbox grants no external path.
                result[name]=dict(unresolved_link=os.readlink(p))
            else:result[name]=dict(link=str(target.relative_to(root)))
        elif p.is_file():result[name]=dict(sha256=sha(p),executable=bool(p.stat().st_mode & 0o111))
        elif not p.is_dir():raise ValueError('Runtime contains a special file: '+name)
    return result


def verify(receipt):
    root=Path(receipt['root'])
    if not root.is_absolute() or root.is_symlink():raise ValueError('Invalid runtime snapshot root')
    manifest=root.parent/'manifest.json'
    if manifest.is_symlink() or sha(manifest)!=receipt['manifest_sha256']:raise ValueError('Runtime snapshot manifest changed')
    value=json.loads(manifest.read_text())
    version=value.get('version')
    if version==2 and (receipt.get('version')!=2 or receipt.get('cache_policy')!=value.get('cache_policy')):
        raise ValueError('Runtime snapshot policy binding changed')
    if version not in (1,2) or (version==2 and value.get('cache_policy')!='source-only-v1'):
        raise ValueError('Unknown runtime snapshot policy')
    if value.get('files')!=inventory(root,version):raise ValueError('Runtime snapshot files changed')
    return root


def capture(source,destination):
    """Copy once, compare both ends, then publish atomically. Never hardlink."""
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists():
        receipt=json.loads((destination/'receipt.json').read_text());verify(receipt);return receipt
    if destination.is_relative_to(source) or source.is_relative_to(destination):raise ValueError('Runtime copy must be outside its source')
    before=inventory(source,2)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.runtime-',dir=destination.parent) as tmp:
        stage=Path(tmp);target=stage/'python'
        shutil.copytree(source,target,symlinks=True,
            ignore=lambda folder,names:[name for name in names if derived_cache(Path(folder)/name)])
        for name,entry in before.items():
            if 'link' in entry:
                p=target/name;p.unlink();p.symlink_to(os.path.relpath(target/entry['link'],p.parent))
        if inventory(source,2)!=before or inventory(target,2)!=before:raise ValueError('Runtime changed during snapshot; nothing admitted')
        for p in target.rglob('*'):
            if p.is_file() and not p.is_symlink():p.chmod(stat.S_IMODE(p.stat().st_mode) & ~0o222)
        manifest=stage/'manifest.json';manifest.write_text(json.dumps(dict(version=2,cache_policy='source-only-v1',source=str(source),files=before),sort_keys=True)+'\n')
        receipt=dict(version=2,cache_policy='source-only-v1',root=str(destination/'python'),manifest_sha256=sha(manifest))
        (stage/'receipt.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
        # rename refuses replacing a nonempty existing snapshot; competing
        # preparations cannot silently adopt another copy's receipt.
        stage.rename(destination)
    verify(receipt);return receipt
