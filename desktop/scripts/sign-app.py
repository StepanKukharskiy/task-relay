"""Stable signing for local builds; never silently replace a missing identity.

Initialize once with --init-local. The private key lives in a dedicated macOS
keychain, not in source or the app. No system trust roots or privacy grants change.
Public distribution requires a separately supplied Developer ID identity.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import tempfile


def run(args, **kwargs):
    kwargs.setdefault('text',True)
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode: raise RuntimeError(result.stderr.strip() or 'Signing command failed')
    return result


def keychain(path, password, create=False):
    security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    reference = ctypes.c_void_p()
    if create:
        fn=security.SecKeychainCreate
        fn.argtypes=[ctypes.c_char_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
        raw=os.fsencode(path)
        status=fn(raw,len(password),password,False,None,ctypes.byref(reference))
    else:
        security.SecKeychainOpen.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)]
        status=security.SecKeychainOpen(os.fsencode(path),ctypes.byref(reference))
    if status: raise RuntimeError('Could not open local signing keychain: '+str(status))
    security.SecKeychainUnlock.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_bool]
    status=security.SecKeychainUnlock(reference,len(password),password,True)
    if status: raise RuntimeError('Could not unlock local signing keychain: '+str(status))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app',nargs='?',type=Path)
    parser.add_argument('--init-local',action='store_true')
    parser.add_argument('--resume-empty-init',action='store_true')
    parser.add_argument('--identity-dir',type=Path,default=Path.home()/'Library/Application Support/Task Relay Signing')
    args=parser.parse_args();os.umask(0o077)
    directory=args.identity_dir;settings=directory/'identity.json';chain=directory/'signing.keychain-db'
    external=os.environ.get('TASK_RELAY_SIGNING_IDENTITY')
    if external:
        if args.init_local:raise ValueError('Choose local initialization or an existing identity.')
        sign_args=['--sign',external]
    else:
        if not settings.is_file():
            if not args.init_local:raise ValueError('Stable signing is not configured. Run sign-app.py --init-local once, or set TASK_RELAY_SIGNING_IDENTITY. No ad hoc fallback.')
            if chain.exists() and not args.resume_empty_init:raise ValueError('An unfinished signing keychain exists; inspect it before recovery.')
            if chain.exists():
                identities=run(['/usr/bin/security','find-identity',str(chain)])
                if '0 identities found' not in identities.stdout or '1) ' in identities.stdout:
                    raise ValueError('The unfinished keychain contains a signing identity; preserve it for inspection.')
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            password=secrets.token_urlsafe(40).encode()
            # Store recovery credentials privately before creating the keychain.
            pending=directory/'initialization.json'
            if pending.is_file():password=json.loads(pending.read_text())['password'].encode()
            else:
                with pending.open('x') as stream:json.dump({'password':password.decode()},stream)
            keychain(chain,password,create=not chain.exists())
            with tempfile.TemporaryDirectory(dir=directory) as temp:
                temp=Path(temp);config=temp/'certificate.cnf'
                config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=extensions\nprompt=no\n[dn]\nCN=Task Relay Local Development\n[extensions]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=critical,codeSigning\n')
                run(['/usr/bin/openssl','req','-new','-newkey','rsa:3072','-nodes','-x509','-days','3650','-config',str(config),'-keyout',str(temp/'key.pem'),'-out',str(temp/'certificate.pem')])
                run(['/usr/bin/security','import',str(temp/'certificate.pem'),'-k',str(chain)])
                run(['/usr/bin/openssl','rsa','-in',str(temp/'key.pem'),'-out',str(temp/'rsa.pem')])
                run(['/usr/bin/security','import',str(temp/'rsa.pem'),'-k',str(chain),'-T','/usr/bin/codesign'])
                cert=run(['/usr/bin/openssl','x509','-in',str(temp/'certificate.pem'),'-outform','DER'],text=False).stdout
                fingerprint=hashlib.sha1(cert).hexdigest().upper()
                (directory/'certificate.pem').write_bytes((temp/'certificate.pem').read_bytes())
            with settings.open('x') as stream:json.dump({'identity':fingerprint,'password':password.decode(),'kind':'local-development'},stream)
            pending.unlink()
        config=json.loads(settings.read_text())
        keychain(chain,config['password'].encode())
        # codesign consults the search list for the certificate chain even when
        # --keychain selects the private identity. Preserve all existing entries.
        search=shlex.split(run(['/usr/bin/security','list-keychains','-d','user']).stdout)
        if str(chain) not in search:
            run(['/usr/bin/security','list-keychains','-d','user','-s',*search,str(chain)])
        sign_args=['--keychain',str(chain),'--sign',config['identity']]
    if args.app:
        app=args.app.resolve()
        if app.suffix!='.app' or not (app/'Contents/MacOS/task-relay-desktop').is_file():raise ValueError('Choose a built Task Relay.app.')
        run(['/usr/bin/codesign','--force','--deep',*sign_args,'--timestamp=none',str(app)])
        run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)])
        requirement=run(['/usr/bin/codesign','-d','-r-',str(app)])
        print((requirement.stdout+requirement.stderr).strip())
    else:
        print('Stable local signing identity is ready. No privacy grants or system trust roots changed.')


if __name__=='__main__':main()
