"""Check staged/committed public source without printing matched sensitive values."""
import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zlib

if __package__:
    from .source_inventory import inventory
else:
    from source_inventory import inventory

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
    'personal-home-path': rb'(?:/Users/|/home/)(?!runner(?:admin)?(?:/|\b))[A-Za-z0-9_.-]+[/\\]',
    'windows-home-path': rb'[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][A-Za-z0-9_.-]+[\\/]',
    'private-key': rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
    'google-api-key': rb'AIza[0-9A-Za-z_-]{35}',
    'github-token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})',
    'telegram-token': rb'\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b',
    'provider-key': rb'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{30,}',
    'aws-access-id': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'slack-token': rb'\bxox[baprs]-[A-Za-z0-9-]{20,}',
    'private-evidence-link': rb'\]\([^)]*(?:outputs/|docs/(?:analysis|history)/|\.\./private/)',
    'dated-local-replay': rb'(?:private|outputs)/[a-z0-9-]+-202[0-9][0-9-]*/',
}


def png_text(raw):
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):return
    offset=8
    while offset+12<=len(raw):
        size=int.from_bytes(raw[offset:offset+4],'big');kind=raw[offset+4:offset+8]
        body=raw[offset+8:offset+8+size];offset+=size+12
        if kind==b'tEXt':yield body
        elif kind in (b'zTXt',b'iTXt'):
            if kind==b'zTXt':content=body.split(b'\0',1)[1][1:];compressed=True
            else:
                _,rest=body.split(b'\0',1);compressed=rest[0];content=rest[2:].split(b'\0',2)[2]
            if compressed:
                inflater=zlib.decompressobj();content=inflater.decompress(content,1_000_001)
                if len(content)>1_000_000 or inflater.unconsumed_tail:raise ValueError('Oversized image text metadata')
            yield content


def scan(path,raw):
    findings=[]
    try:payloads=[raw,*png_text(raw)]
    except (ValueError,IndexError,zlib.error):return [{'path':path,'kind':'unreadable-image-metadata'}]
    for data in payloads:
        for label,pattern in PATTERNS.items():
            if re.search(pattern,data):findings.append({'path':path,'kind':label})
    if path.endswith('.py'):
        try:tree=ast.parse(raw)
        except (SyntaxError,ValueError):return [*findings,{'path':path,'kind':'invalid-python'}]
        for node in ast.walk(tree):
            # Product runtime must obtain installation-specific IDs from configuration.
            if path.startswith('task_relay/') and isinstance(node,ast.Assign):
                if isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                    if any(isinstance(t,ast.Name) and t.id in {'DEFAULT_TASK','DEFAULT_CHAT','PAIR_CODE'} for t in node.targets):
                        findings.append({'path':path,'kind':'personal-runtime-default'})
            if isinstance(node,ast.Dict):
                for key,value in zip(node.keys,node.values):
                    if isinstance(key,ast.Constant) and key.value in ('api_key','token','access_token','refresh_token','password','client_secret'):
                        if isinstance(value,ast.Constant) and isinstance(value.value,str) and len(value.value)>=20:
                            if not value.value.startswith(('fixture-','example-','test-')):
                                findings.append({'path':path,'kind':'embedded-credential-literal'})
    return findings


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged',action='store_true',help='Inspect index bytes and require equality with reviewed working source')
    args=parser.parse_args();expected={f['path']:f for f in inventory()['files']}
    names=[p.decode() for p in (git('ls-files','-z') if args.staged else git('ls-tree','-r','--name-only','-z','HEAD')).split(b'\0') if p]
    findings=[];blobs={}
    for name in sorted(set(names)-set(expected)):findings.append({'path':name,'kind':'outside-public-inventory'})
    for name in sorted(set(expected)-set(names)):findings.append({'path':name,'kind':'missing-inventory-source'})
    import hashlib
    for name in names:
        raw=git('show',(':' if args.staged else 'HEAD:')+name);blobs[name]=raw
        if name in expected and hashlib.sha256(raw).hexdigest()!=expected[name]['sha256']:
            findings.append({'path':name,'kind':'reviewed-source-byte-mismatch'})
        findings.extend(scan(name,raw))
    for name,raw in blobs.items():
        if not name.endswith('.md'):continue
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',raw.decode()):
            if '://' in target or target.startswith('#'):continue
            path=target.split('#',1)[0].strip('<>')
            resolved=(ROOT/PurePosixPath(name).parent/path).resolve()
            if not resolved.is_relative_to(ROOT) or resolved.relative_to(ROOT).as_posix() not in blobs:
                findings.append({'path':name,'kind':'unpublished-documentation-link'})
    report={'files_checked':len(names),'mode':'staged' if args.staged else 'HEAD',
            'passed':not findings,'findings':findings,
            'limitations':'Heuristic publication guard, not a complete secret detector. Review new files and inspect private-data boundaries.'}
    print(json.dumps(report,indent=2));return 0 if not findings else 1


if __name__=='__main__':sys.exit(main())
