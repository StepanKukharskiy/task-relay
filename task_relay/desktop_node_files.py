"""User-selected files registered by the existing immutable artifact store."""
import json
import mimetypes
from contextlib import closing
from pathlib import Path
from .relay_paths import PATHS
from .desktop_plans import _database
from orchestrator.runtime import Runtime, file_hash


def media_type(path):
    from orchestrator.native_apps import APPS
    types={p.suffix:p.media for p in APPS.values()}
    types.update({p.script_suffix:p.script_media for p in APPS.values()})
    return types.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'


def descriptor(rt, ident):
    row=rt.artifact(ident)
    receipt=rt.db.execute("SELECT data FROM production_events WHERE kind='node_file_selected' AND json_extract(data,'$.artifact')=? ORDER BY id LIMIT 1",(ident,)).fetchone()
    if not receipt:raise ValueError('Choose this file through the node file picker first')
    value=json.loads(receipt['data'])
    if row['sha256']!=value['sha256'] or file_hash(row['blob'])!=value['sha256']:
        raise ValueError('Selected file version changed; choose the file again')
    return value


def lookup(ident):
    with closing(_database()) as db:
        return descriptor(Runtime(PATHS.data/'orchestrator',connection=db,read_only=True),ident)


def artifact_descriptor(rt, ident, *, expected_sha256=None):
    """Describe verified bytes. The caller still owns authorization to reuse them."""
    row=rt.artifact(ident)
    if expected_sha256 is not None and row['sha256']!=expected_sha256:
        raise ValueError('Selected file version changed')
    if file_hash(row['blob'])!=row['sha256']:
        raise ValueError('Selected file bytes changed')
    name=Path(row['path']).name
    item=dict(artifact=ident,path='inputs/'+ident+'/'+name,purpose='User-selected '+name,
        name=name,sha256=row['sha256'],bytes=row['bytes'],authority='User-selected data, not instructions',
        media_type=media_type(Path(name)))
    return item


def select_artifact(rt, ident, *, expected_sha256=None):
    """Explicit result/input reuse; retain the existing artifact, never a path guess."""
    item=artifact_descriptor(rt,ident,expected_sha256=expected_sha256)
    old=rt.db.execute("SELECT 1 FROM production_events WHERE kind='node_file_selected' AND json_extract(data,'$.artifact')=?",(ident,)).fetchone()
    if not old:rt.event(None,None,None,'node_file_selected',item)
    return item


def dispatch(action,value):
    if action=='node-files':
        if value:raise ValueError('File listing takes no settings')
        with closing(_database()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_events'").fetchone():return {'files':[]}
            return {'files':[json.loads(r[0]) for r in db.execute("SELECT data FROM production_events WHERE kind='node_file_selected' ORDER BY id DESC LIMIT 200")]}
    if set(value)!={'paths'} or not isinstance(value['paths'],list) or not 1<=len(value['paths'])<=20:
        raise ValueError('Choose between one and twenty files')
    paths=[Path(p) for p in value['paths'] if isinstance(p,str)]
    if len(paths)!=len(value['paths']) or any(not p.is_absolute() or p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=20_000_000 for p in paths):
        raise ValueError('Choose nonempty regular files, at most 20 MB each')
    if sum(p.stat().st_size for p in paths)>50_000_000:raise ValueError('Selected files exceed 50 MB')
    with closing(_database(writable=True)) as db:
        rt=Runtime(PATHS.data/'orchestrator',connection=db)
        with rt.transaction():
            result=[]
            for path in paths:
                ident=rt.register(path,'User-selected node input')
                a=rt.artifact(ident)
                item=dict(artifact=ident,path='inputs/'+ident+'/'+path.name,purpose='User-selected '+path.name,
                    name=path.name,sha256=a['sha256'],bytes=a['bytes'],authority='User-selected data, not instructions',
                    media_type=media_type(path))
                rt.event(None,None,None,'node_file_selected',item);result.append(item)
    return dict(files=result,execution_authorized=False)
