"""Portable copies of the existing workflow document. Never execution or history."""
import copy
import hashlib
import io
import json
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

from orchestrator import node_spec
from orchestrator.runtime import Runtime, file_hash
from . import desktop_node_drafts as drafts, desktop_node_files as files
from .app_updates import write
from .desktop_plans import _database
from .relay_paths import PATHS

MAX_PACKAGE = 52_000_000
MAX_FILES = 50_000_000
SECRET_FIELDS = {'api_key','apikey','access_token','refresh_token','password','private_key','authorization'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def clean(value):
    """Reject credential fields, never copy connection configuration into a package."""
    if isinstance(value, dict):
        if any(str(k).lower().replace('-','_') in SECRET_FIELDS for k in value):
            raise ValueError('Remove credential fields from the workflow before sharing it')
        for item in value.values():clean(item)
    elif isinstance(value,list):
        for item in value:clean(item)


def remap(document, mapping, connections):
    result=copy.deepcopy(document)
    def walk(value):
        if isinstance(value,dict):
            if set(value)=={'artifact'} and value['artifact'] in mapping:value['artifact']=mapping[value['artifact']]
            else:
                for item in value.values():walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    ports={(c['task'],c['input']) for c in connections if 'artifact' in c['source']}
    for task in result['tasks']:
        for name,binding in task.get('inputs',{}).items():
            if (task['id'],name) in ports:walk(binding)
    return result


def source(value):
    if not isinstance(value,dict) or set(value)!={'kind','id','revision'} or value['kind'] not in ('draft','canvas'):
        raise ValueError('Choose a saved workflow to export')
    from .desktop_node_runs import canvas_document,canvas_lookup
    with closing(_database()) as db:
        rt=Runtime(PATHS.data/'orchestrator',connection=db,read_only=True)
        record=(drafts.dispatch('node-draft',{'id':value['id']}) if value['kind']=='draft' else canvas_document(rt,value['id']))
        if record['revision']!=value['revision']:raise ValueError('Workflow changed. Reopen it before exporting')
        lookup=(lambda ident:files.descriptor(rt,ident)) if value['kind']=='draft' else canvas_lookup(rt,value['id'])
        document=record['workflow'];clean(document)
        checked=node_spec.resolve_workflow(document,artifact=lookup)
        identifiers=list(dict.fromkeys(c['source']['artifact'] for c in checked['connections'] if 'artifact' in c['source']))
        if len(identifiers)>20:raise ValueError('Export supports at most 20 input files')
        inputs=[];blobs={};mapping={}
        for index,ident in enumerate(identifiers):
            item=lookup(ident);a=rt.artifact(ident);name=item['name']
            if name.lower()=='.env' or name.lower().startswith('.env.') or name.lower().endswith(('.pem','.key')):
                raise ValueError('Credential files cannot be shared as workflow inputs')
            key=f'input-{index+1}';mapping[ident]=key;blobs[key]=Path(a['blob'])
            inputs.append(dict(id=key,name=name,media_type=item['media_type'],sha256=a['sha256'],bytes=a['bytes']))
        if any(not 0<i['bytes']<=20_000_000 for i in inputs) or sum(i['bytes'] for i in inputs)>MAX_FILES:
            raise ValueError('Input files exceed the 20 MB per-file or 50 MB total limit')
        return dict(title=record['title'],workflow=remap(document,mapping,checked['connections']),inputs=inputs),blobs


def export(value):
    if set(value)!={'source','path','include_files'} or type(value['include_files']) is not bool:
        raise ValueError('Choose an export destination and whether to include input files')
    content,blobs=source(value['source']);path=Path(value['path'])
    if not path.is_absolute() or path.suffix!='.zip' or path.exists() or path.is_symlink():
        raise ValueError('Choose a new .zip file; existing files are not overwritten')
    document=encoded(content.pop('workflow'))
    manifest=dict(format='relay-workflow',version=1,**content,workflow_sha256=digest(document),includes_files=value['include_files'])
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('workflow.json',document);archive.writestr('manifest.json',encoded(manifest))
        if value['include_files']:
            for item in content['inputs']:
                data=blobs[item['id']].read_bytes()
                if len(data)!=item['bytes'] or digest(data)!=item['sha256']:raise ValueError('An input file changed during export')
                archive.writestr('inputs/'+item['id'],data)
    data=output.getvalue()
    if len(data)>MAX_PACKAGE:raise ValueError('Package exceeds the export limit')
    with path.open('xb') as handle:
        path.chmod(0o600);handle.write(data)
    return dict(path=str(path),sha256=digest(data),nodes=len(json.loads(document)['tasks']),files=len(content['inputs']),execution_authorized=False)


def package(path):
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_PACKAGE:
        raise ValueError('Choose a regular Relay workflow ZIP, at most 52 MB')
    data=path.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist();names=[i.filename for i in infos]
            if len(names)!=len(set(names)) or len(names)>22 or sum(i.file_size for i in infos)>MAX_PACKAGE:
                raise ValueError('Duplicate entries or oversized workflow package')
            if any((i.external_attr>>16)&0o170000==0o120000 or i.flag_bits&1 for i in infos):
                raise ValueError('Encrypted entries and symbolic links are not supported')
            for name in ('manifest.json','workflow.json'):
                if archive.getinfo(name).file_size>500_000:raise ValueError('Workflow metadata exceeds 500 KB')
            manifest=json.loads(archive.read('manifest.json'));docbytes=archive.read('workflow.json');workflow=json.loads(docbytes)
            if set(manifest)!={'format','version','title','inputs','workflow_sha256','includes_files'} or manifest['format']!='relay-workflow' or manifest['version']!=1 or type(manifest['includes_files']) is not bool:
                raise ValueError('Unsupported workflow package')
            if not isinstance(manifest['title'],str) or not 1<=len(manifest['title'].strip())<=180:raise ValueError('Invalid workflow title')
            if digest(docbytes)!=manifest['workflow_sha256']:raise ValueError('Workflow checksum mismatch')
            inputs=manifest['inputs']
            if not isinstance(inputs,list) or len(inputs)>20:raise ValueError('Invalid input file manifest')
            descriptors={};assets={}
            for item in inputs:
                if not isinstance(item,dict) or set(item)!={'id','name','media_type','sha256','bytes'}:raise ValueError('Invalid input file entry')
                ident=item['id'];name=item['name']
                if not isinstance(ident,str) or not re.fullmatch(r'input-[1-9][0-9]*',ident) or ident in descriptors:raise ValueError('Invalid or duplicate input identity')
                if not isinstance(name,str) or not name or len(name)>255 or Path(name).name!=name or '\\' in name or name in ('.','..'):raise ValueError('Invalid input file name')
                if type(item['bytes']) is not int or not 0<item['bytes']<=20_000_000 or not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256']):raise ValueError('Invalid input file checksum or size')
                if files.media_type(Path(name))!=item['media_type']:raise ValueError('Input file type mismatch')
                descriptors[ident]=dict(item,artifact=ident,path='inputs/'+ident+'/'+name,purpose='Imported input')
                if manifest['includes_files']:
                    blob=archive.read('inputs/'+ident)
                    if len(blob)!=item['bytes'] or digest(blob)!=item['sha256']:raise ValueError('Input file checksum mismatch')
                    assets[ident]=blob
            expected={'manifest.json','workflow.json'}|({'inputs/'+i for i in descriptors} if manifest['includes_files'] else set())
            if set(names)!=expected or sum(i['bytes'] for i in inputs)>MAX_FILES:raise ValueError('Unexpected entries or excessive input size')
            clean(workflow)
            def lookup(ident):
                if ident not in descriptors:raise ValueError('Workflow references an undeclared input file')
                return descriptors[ident]
            checked=node_spec.resolve_workflow(workflow,artifact=lookup)
            used={c['source']['artifact'] for c in checked['connections'] if 'artifact' in c['source']}
            if used!=set(descriptors):raise ValueError('Input manifest does not match workflow bindings')
            return manifest,workflow,assets,digest(data)
    except (zipfile.BadZipFile,KeyError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('Invalid Relay workflow package') from exc


def preview(value):
    if set(value)!={'path'}:raise ValueError('Choose a workflow package')
    m,w,a,h=package(value['path'])
    return dict(title=m['title'],nodes=len(w['tasks']),files=m['inputs'],missing_files=[i for i in m['inputs'] if i['id'] not in a],sha256=h,execution_authorized=False)


def import_workflow(value):
    if set(value)!={'path','sha256','files'} or not isinstance(value['files'],dict):raise ValueError('Choose a package and its missing input files')
    m,w,assets,h=package(value['path'])
    if h!=value['sha256']:raise ValueError('Package changed; choose it again')
    missing={i['id'] for i in m['inputs'] if i['id'] not in assets}
    if set(value['files'])!=missing:raise ValueError('Supply all omitted input files before importing')
    for item in m['inputs']:
        if item['id'] in missing:
            path=Path(value['files'][item['id']])
            if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size!=item['bytes']:raise ValueError('Choose the original file for '+item['name'])
            data=path.read_bytes()
            if digest(data)!=item['sha256']:raise ValueError('File does not match '+item['name'])
            assets[item['id']]=data
    portable={i['id']:dict(i,artifact=i['id'],path='inputs/'+i['id']+'/'+i['name'],purpose='Imported input') for i in m['inputs']}
    connections=node_spec.resolve_workflow(w,artifact=portable.__getitem__)['connections']
    # No original identity/history is imported. Write only new immutable inputs and
    # a new ordinary draft; rollback removes only files created by this transaction.
    created=[];draft_path=None
    try:
        with tempfile.TemporaryDirectory() as tmp,closing(_database(writable=True)) as db:
            rt=Runtime(PATHS.data/'orchestrator',connection=db)
            with rt.transaction():
                mapping={};descriptors={}
                for item in m['inputs']:
                    local=Path(tmp).resolve()/item['id']/item['name'];local.parent.mkdir();local.write_bytes(assets[item['id']])
                    ident=rt.register(local,'Imported workflow input',path=item['name']);created.append(rt.root/'artifacts'/ident)
                    descriptor=files.select_artifact(rt,ident);mapping[item['id']]=ident;descriptors[ident]=descriptor
                document=remap(w,mapping,connections);checked=node_spec.resolve_workflow(document,artifact=descriptors.__getitem__)
                title=m['title'];revision=hashlib.sha256(json.dumps(dict(title=title,workflow=document),sort_keys=True).encode()).hexdigest()
                ident=uuid.uuid4().hex;record=dict(title=title,workflow=document,revision=revision)
                draft_path=PATHS.data/'node-drafts'/(ident+'.json');draft_path.parent.mkdir(parents=True,exist_ok=True);write(draft_path,record)
            return dict(id=ident,**record,missing_inputs=checked['missing_inputs'],execution_authorized=False)
    except BaseException:
        if draft_path is not None:draft_path.unlink(missing_ok=True)
        for path in created:shutil.rmtree(path)
        raise


def dispatch(action,value):
    return {'workflow-export':export,'workflow-import-preview':preview,'workflow-import':import_workflow}[action](value)
