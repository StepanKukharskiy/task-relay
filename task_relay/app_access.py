"""User choices for registered app integrations, independent of discovery.

These are Relay dispatch controls, not an OS sandbox for other applications.
Missing preferences retain existing app availability; malformed preferences fail
closed. Exact executable keys survive app version updates at the same location.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from .relay_paths import PATHS

FAMILIES = ('rhino', 'blender', 'sketchup', 'codex', 'claude', 'ffmpeg')


def path(): return PATHS.data/'app-access.json'


def key(family, executable=None):
    if family not in FAMILIES: raise ValueError('Unknown app integration.')
    return family if executable is None else family+':'+hashlib.sha256(str(Path(executable).resolve()).encode()).hexdigest()


def read():
    p = path()
    if p.is_symlink(): raise ValueError('App settings must not be a link.')
    try:
        with p.open() as stream: value = json.loads(stream.read(100001))
    except FileNotFoundError: return {}
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('choices'), dict):
        raise ValueError('App settings are invalid; restore them before dispatch.')
    choices = value['choices']
    if any(not isinstance(k, str) or k.split(':')[0] not in FAMILIES or type(v) is not bool for k,v in choices.items()):
        raise ValueError('App settings contain an invalid choice.')
    return choices


def enabled(family, executable=None):
    try:
        choices = read()
        return choices.get(key(family), True) and choices.get(key(family, executable), True)
    except (OSError, ValueError): return False


def require(family, executable=None):
    if not enabled(family, executable):
        raise ValueError(family.capitalize()+' is off in Settings → Apps and tools. No new app operation was started.')


@contextmanager
def settings_lock(root=None):
    from .host import HOST
    root = Path(root) if root is not None else path().parent
    if root.is_symlink(): raise ValueError('App settings folder must not be a link.')
    root.mkdir(parents=True, exist_ok=True)
    lock = root/'app-access.lock'
    if lock.is_symlink(): raise ValueError('App settings lock must not be a link.')
    fd = os.open(lock, os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0), 0o600)
    with os.fdopen(fd, 'r+') as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError('Invalid app settings lock.')
        HOST.lock(stream)
        yield


def update(value):
    from .host_apps import installed
    if not isinstance(value, dict) or set(value) != {'id','enabled'} or type(value['enabled']) is not bool:
        raise ValueError('Choose an app and whether it is on or off.')
    rows = installed()
    allowed = set(FAMILIES)|{r['id'] for r in rows}
    if value['id'] not in allowed: raise ValueError('This app is no longer detected. Refresh Settings.')
    with settings_lock():
        choices = read(); choices[value['id']] = value['enabled']
        # Unique temporary files avoid lost/crossed writes between desktop calls.
        fd, temporary = tempfile.mkstemp(prefix='app-access-', dir=path().parent)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump({'version':1,'choices':choices}, stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path())
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    return {'message':'App access saved. New Relay operations respect this choice; running work is not cancelled. Saved plans keep their exact app and approvals.'}


def snapshot():
    from .host_apps import installed
    rows = installed()
    try:read();error=None
    except (ValueError,OSError) as exc:error=str(exc)
    return {'error':error,'apps':[{**r,'enabled':enabled(r['family'],r['executable'])} for r in rows],
            'groups':[{'id':f,'enabled':enabled(f)} for f in FAMILIES],
            'detail':'Controls Relay’s registered operations and agent dispatch. Turning an app off does not cancel running work or change permissions inside external agents.'}
