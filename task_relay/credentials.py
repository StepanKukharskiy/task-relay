"""Explicit secret sources. Resolution failures never select a fallback credential."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .filesystem import FILES, Grant
from .host import HOST, UnsupportedHost


class CredentialError(ValueError):
    pass


def private_json(path, require_private=True):
    path=Path(path)
    try:
        grant=Grant(path.parent,'configured credential file',frozenset({path.name}))
        with FILES.open(grant,path.name) as fd:
            info=os.fstat(fd)
            if require_private and (info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077):
                raise CredentialError('Credential file must be owned by this account with mode 0600')
            with os.fdopen(os.dup(fd),'rb') as stream:raw=stream.read(1_000_001)
        if len(raw)>1_000_000:raise CredentialError('Credential file exceeds its size limit')
        value=json.loads(raw)
        if not isinstance(value,dict):raise CredentialError('Credential configuration must be an object')
        return value
    except UnsupportedHost as exc:raise CredentialError(str(exc)) from None
    except CredentialError:raise
    except Exception:
        raise CredentialError('Configured credential file is unavailable or invalid') from None


def resolve(reference, *, host=HOST, environ=None):
    env=os.environ if environ is None else environ
    if not isinstance(reference,dict):raise CredentialError('Credential reference must be an object')
    kind=reference.get('source')
    try:
        if kind=='environment' and set(reference)=={'source','name'}:
            name=reference['name']
            if not isinstance(name,str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name):raise CredentialError('Invalid credential environment reference')
            value=env.get(name)
        elif kind=='dotenv' and set(reference)=={'source','path','name'}:
            path=Path(reference['path'])
            if not path.is_absolute():raise CredentialError('Credential path must be absolute')
            value=dotenv_values(path).get(reference['name'])
        elif kind=='private-file' and set(reference)=={'source','path','field'}:
            path=Path(reference['path'])
            if not path.is_absolute():raise CredentialError('Credential file reference must be absolute')
            value=private_json(path).get(reference['field'])
        elif kind=='macos-keychain' and set(reference)=={'source','service','account'}:
            host.require_macos('Keychain credential source')
            if any(not isinstance(reference[k],str) or not reference[k] or reference[k].startswith('-') for k in ('service','account')):
                raise CredentialError('Invalid Keychain credential reference')
            result=subprocess.run(['/usr/bin/security','find-generic-password','-s',reference['service'],'-a',reference['account'],'-w'],capture_output=True,text=True,timeout=10)
            if result.returncode:raise CredentialError('Configured Keychain item is missing, locked or denied')
            value=result.stdout.rstrip('\n')
        else:raise CredentialError('Unsupported credential source or reference fields')
        if not isinstance(value,str) or not value.strip():raise CredentialError('Configured credential source is empty or unavailable')
        return value
    except UnsupportedHost as exc:raise CredentialError(str(exc)) from None
    except CredentialError:raise
    except Exception:raise CredentialError('Configured credential source could not be resolved') from None


def configuration(path, secret='api_key', enabled=True):
    """Existing fixed config paths explicitly retain their private-file source."""
    value=private_json(path)
    if enabled and not value.get('enabled',True):return None
    reference=secret+'_ref'
    if reference in value:
        # A reference always wins, even if an obsolete inline key is also present.
        value={**value,secret:resolve(value[reference])}
    if not isinstance(value.get(secret),str) or not value[secret].strip():return None
    return value


def save(path,value):
    """Explicit private-file writes, atomically replaced with owner-only mode."""
    path=Path(path)
    if not path.is_absolute():raise CredentialError('Configuration path must be absolute')
    root=path.parent
    while not root.exists() and not root.is_symlink():root=root.parent
    relative=path.relative_to(root).as_posix()
    grant=Grant(root,'explicit provider configuration update',writes=frozenset({relative}))
    FILES.write(grant,relative,(json.dumps(value,indent=2)+'\n').encode())


def public_settings(value):
    return {k:v for k,v in value.items() if k in ('enabled','model','models','voice','base_url','catalog_checked_at')}


def status(path,secret='api_key'):
    try:
        settings=private_json(path)
        value=configuration(path,secret)
        return {'available':value is not None,'source':settings.get(secret+'_ref',{}).get('source','configured-private-file'),
                'settings':public_settings(settings),'blocker':None if value else 'Disabled or empty credential'}
    except CredentialError as exc:return {'available':False,'blocker':str(exc)}


def main():
    import argparse
    from .relay_paths import PATHS
    parser=argparse.ArgumentParser(description='Inspect configured credential availability without displaying secrets')
    parser.add_argument('provider',choices=('telegram','gemini','openai','qwen','deepseek','openrouter'))
    args=parser.parse_args()
    print(json.dumps(status(PATHS.data/('config.json' if args.provider=='telegram' else args.provider+'.json'),
                            'token' if args.provider=='telegram' else 'api_key'),indent=2))


if __name__ == '__main__':
    main()


def dotenv_values(path):
    """Read literal dotenv values. No expansion, shell execution or secret errors."""
    import shlex
    path=Path(path)
    if path.is_symlink():raise CredentialError('Credential file cannot be a symbolic link')
    try:
        grant=Grant(path.parent,'configured credential file',frozenset({path.name}))
        with FILES.open(grant,path.name) as fd:
            info=os.fstat(fd)
            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or info.st_size>1_000_000:
                raise CredentialError('Credential file must be private (0600) and below 1 MB')
            with os.fdopen(os.dup(fd),'rb') as stream:data=stream.read(1_000_001)
        if len(data)>1_000_000:raise CredentialError('Credential file exceeds its size limit')
        values={}
        for raw in data.decode().splitlines():
            line=raw.strip()
            if not line or line.startswith('#'):continue
            name,sep,value=line.partition('=')
            if not sep or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name.strip()) or name.strip() in values:
                raise CredentialError('Credential file has invalid or duplicate variable names')
            tokens=shlex.split(value,comments=True,posix=True)
            if len(tokens)!=1:raise CredentialError('Credential file needs one literal value per variable')
            values[name.strip()]=tokens[0]
        return values
    except CredentialError:raise
    except Exception:raise CredentialError('Credential file is unavailable or invalid') from None


def save_dotenv(path, name, value):
    """Atomic private shared key file; callers serialize through setup_lock."""
    import shlex
    path=Path(path)
    if not path.is_absolute() or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name):raise CredentialError('Invalid credential location')
    if not isinstance(value,str) or not value or len(value)>4000 or any(c in value for c in '\r\n\0'):
        raise CredentialError('Enter a nonempty single-line API key')
    if path.is_symlink():raise CredentialError('Credential file cannot be a symbolic link')
    if path.exists():dotenv_values(path)
    lines=FILES.read(Grant(path.parent,'configured credential file',frozenset({path.name})),path.name,1_000_000).decode().splitlines() if path.exists() else ['# Relay API keys. Private; never commit or export.']
    replacement=name+'='+shlex.quote(value)
    found=False
    for i,line in enumerate(lines):
        if line.strip().partition('=')[0].strip()==name:lines[i]=replacement;found=True
    if not found:lines.append(replacement)
    root=path.parent
    while not root.exists() and not root.is_symlink():root=root.parent
    relative=path.relative_to(root).as_posix()
    FILES.write(Grant(root,'explicit shared API key update',writes=frozenset({relative})),relative,('\n'.join(lines)+'\n').encode())
