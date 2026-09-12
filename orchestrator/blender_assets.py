"""Explicit immutable asset manifests and portable bundle construction."""
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import time
import unicodedata
import zipfile
from .runtime import file_hash,safe_file
from .workers import atomic

DESCRIPTION={'version':1,'scene':'Path of the one scene entry in files',
    'files':'1–30 entries: {path: original relative bundle layout, sha256: exact selected hash, kind: scene/library/image, provenance: {source: supplied origin text, license: supplied license or null}}. Unique hashes and portable paths. PNG/JPEG images and .blend scenes/libraries only.',
    'imports':'0–30 entries: {type: append_objects, library: file path, names: 1–100 exact existing mesh names, collection: destination collection name}; or {type: image_texture, file: image path, material: existing material, node: existing Image Texture node, image_name: new image name}. No link mode, downloads or arbitrary code.',
    'preview':{'camera':'Existing camera name','resolution':'[width,height], 64–1024','samples':'1–16, CPU Cycles'},
    'result':'A packed portable candidate, preview, source bundle retaining layout/provenance, manifest and verification receipts. Persistent library links and non-image external dependencies are not supported.'}
TYPES={'scene':'application/x-blender','library':'application/x-blender','image':('image/png','image/jpeg')}
SOURCES=('blender_assets.py','blender_assets_worker.py','blender_snapshot.py','blender_edit_worker.py')

def portable(path):
    if not isinstance(path,str) or not 1<=len(path)<=240 or '\\' in path:raise ValueError('Invalid bundle path')
    parts=path.split('/')
    if any(not p or p in ('.','..') or re.search(r'[<>:"|?*\x00-\x1f]',p) or p.endswith((' ','.')) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?',p,re.I) for p in parts):raise ValueError('Bundle paths must be portable relative paths')
    if parts[0].casefold() in ('candidate.blend','manifest.json','.relay'):raise ValueError('Reserved bundle path')
    return path

def validate(value):
    if not isinstance(value,dict) or set(value)!={'version','scene','files','imports','preview'} or type(value['version']) is not int or value['version']!=1:raise ValueError('Use the version-1 asset manifest schema')
    files=value['files']
    if not isinstance(files,list) or not 1<=len(files)<=30:raise ValueError('Select 1–30 exact bundle files')
    paths={};hashes=set()
    for f in files:
        if not isinstance(f,dict) or set(f)!={'path','sha256','kind','provenance'}:raise ValueError('Invalid asset entry')
        path=portable(f['path']);key=unicodedata.normalize('NFC',path).casefold()
        if key in paths or any(key.startswith(p+'/') or p.startswith(key+'/') for p in paths):raise ValueError('Colliding bundle paths')
        if f['kind'] not in TYPES or not isinstance(f['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',f['sha256']) or f['sha256'] in hashes:raise ValueError('Select distinct, exact asset hashes')
        if PurePosixPath(path).suffix.lower() not in (('.png','.jpg','.jpeg') if f['kind']=='image' else ('.blend',)):raise ValueError('Unsupported asset extension')
        p=f['provenance']
        if not isinstance(p,dict) or set(p)!={'source','license'} or not isinstance(p['source'],str) or not 1<=len(p['source'])<=2000 or (p['license'] is not None and (not isinstance(p['license'],str) or len(p['license'])>2000)):raise ValueError('Record supplied provenance; unknown license is null')
        paths[key]=f;hashes.add(f['sha256'])
    scenes=[f for f in files if f['kind']=='scene']
    if len(scenes)!=1 or value['scene']!=scenes[0]['path']:raise ValueError('Select exactly one source scene')
    exact={f['path']:f for f in files};imports=value['imports']
    if not isinstance(imports,list) or len(imports)>30:raise ValueError('At most 30 explicit imports')
    names=set()
    for item in imports:
        if not isinstance(item,dict):raise ValueError('Invalid import')
        if item.get('type')=='append_objects':
            if set(item)!={'type','library','names','collection'} or exact.get(item['library'],{}).get('kind')!='library':raise ValueError('Choose an exact library for append')
            ns=item['names']
            if not isinstance(ns,list) or not 1<=len(ns)<=100 or any(not isinstance(n,str) for n in ns) or len(set(ns))!=len(ns) or names.intersection(ns):raise ValueError('Duplicate or invalid appended object names')
            names.update(ns);strings=[*ns,item['collection']]
        elif item.get('type')=='image_texture':
            if set(item)!={'type','file','material','node','image_name'} or exact.get(item['file'],{}).get('kind')!='image':raise ValueError('Choose an exact image for binding')
            strings=[item[k] for k in ('material','node','image_name')]
        else:raise ValueError('Unsupported import mode; no persistent links or arbitrary code')
        if any(not isinstance(s,str) or not 1<=len(s)<=200 for s in strings):raise ValueError('Use exact bounded datablock names')
    p=value['preview']
    if not isinstance(p,dict) or set(p)!={'camera','resolution','samples'} or not isinstance(p['camera'],str) or not 1<=len(p['camera'])<=200:raise ValueError('Select a preview camera')
    if not isinstance(p['resolution'],list) or len(p['resolution'])!=2 or any(type(n) is not int or not 64<=n<=1024 for n in p['resolution']):raise ValueError('Invalid preview dimensions')
    if type(p['samples']) is not int or not 1<=p['samples']<=16:raise ValueError('Invalid preview sample count')
    return value

def match_assets(manifest,assets):
    if len(assets)!=len(manifest['files']):raise ValueError('Every declared asset needs one selected input; no unlisted assets')
    matched={}
    for f in manifest['files']:
        matches=[i for i in assets if i['sha256']==f['sha256']]
        if len(matches)!=1:raise ValueError('Missing or ambiguous selected asset: '+f['path'])
        item=matches[0];allowed=TYPES[f['kind']]
        if item['media_type'] not in (allowed if isinstance(allowed,tuple) else (allowed,)):raise ValueError('Asset media type mismatch')
        matched[f['path']]=item
    return matched

def bind_registered(rt,spec):
    """Validate concrete selected versions before presenting/approving a plan."""
    inputs=[]
    for item in spec['inputs']:
        a=rt.artifact(item['artifact'])
        if file_hash(a['blob'])!=a['sha256']:raise ValueError('Selected asset changed')
        inputs.append({**item,'sha256':a['sha256'],'blob':a['blob']})
    source=next(i for i in inputs if i['media_type']=='application/json')
    if source['sha256']!=spec['execution']['parameters']['manifest_sha256']:raise ValueError('Asset manifest hash mismatch')
    if Path(source['blob']).stat().st_size>200000:raise ValueError('Asset manifest exceeds 200 KB')
    manifest=validate(json.loads(Path(source['blob']).read_text()))
    match_assets(manifest,[i for i in inputs if i['media_type'] in ('application/x-blender','image/png','image/jpeg')])
    return manifest

def selected(frozen,workspace):
    manifests=[i for i in frozen['inputs'] if i['media_type']=='application/json']
    if len(manifests)!=1:raise ValueError('Select one asset manifest')
    source=safe_file(workspace,manifests[0]['path'])
    if file_hash(source)!=frozen['execution']['parameters']['manifest_sha256']:raise ValueError('Asset manifest hash changed')
    if source.stat().st_size>200000:raise ValueError('Asset manifest exceeds 200 KB')
    manifest=validate(json.loads(source.read_text()))
    assets=[i for i in frozen['inputs'] if i['media_type'] in ('application/x-blender','image/png','image/jpeg')]
    matched=match_assets(manifest,assets)
    resolved={}
    for f in manifest['files']:
        item=matched[f['path']]
        path=safe_file(workspace,item['path'])
        if file_hash(path)!=f['sha256']:raise ValueError('Selected asset content changed')
        resolved[f['path']]=(path,item)
    return manifest,resolved

def extract_bundle(archive,destination,expected,limit):
    destination=Path(destination);destination.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist()
        if len(entries)!=len(expected) or {i.filename for i in entries}!=set(expected) or sum(i.file_size for i in entries)>limit:raise ValueError('Bundle contents or size differ from the retained manifest')
        for i in entries:
            if i.filename not in ('candidate.blend','manifest.json'):portable(i.filename)
            if (i.external_attr>>16)&0o170000==0o120000:raise ValueError('Linked bundle entry')
            path=destination/i.filename;path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out,z.open(i) as src:shutil.copyfileobj(src,out)
            if file_hash(path)!=expected[i.filename]:raise ValueError('Bundle entry hash mismatch')

def execute(frozen,control,documents):
    from task_relay.host_apps import blender
    workspace=Path(frozen['workspace']);control=Path(control);out=workspace/'delivery'
    if out.exists() or out.is_symlink():raise ValueError('Asset outputs already exist; no replay or replacement')
    for n in SOURCES:
        if frozen['runtime_sources'].get(n)!=file_hash(Path(__file__).with_name(n)):raise ValueError('Asset implementation changed after dispatch')
    manifest,resolved=selected(frozen,workspace)
    receipt={'capability':'blender.import_asset','assignment':frozen['assignment_id'],'inputs':[{k:i[k] for k in ('artifact','path','sha256')} for i in frozen['inputs']],
        'manifest':manifest,'runs':[],'passed':False,'selected':False,'host_execution':True,
        'scope':'Fixed host import/packing code; embedded auto-execution disabled. Normal OS permissions, not a filesystem sandbox. No network fetch or persistent library link.'}
    with (control/'asset-intent.json').open('x') as f:json.dump(receipt,f)
    out.mkdir();stage=control/'asset-stage';stage.mkdir()
    for path,(source,item) in resolved.items():
        dst=stage/path;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dst)
    atomic(stage/'manifest.json',manifest)
    deadline=time.monotonic()+max(1,frozen['limits']['seconds']-5)
    def run(mode,root):
        command=[blender()['executable'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(Path(__file__).with_name('blender_assets_worker.py')),'--',mode,str(root),str(out)]
        start=time.monotonic()
        try:
            r=subprocess.run(command,cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,timeout=max(.1,deadline-start))
            data={'command':command,'returncode':r.returncode,'timeout':False,'stdout':r.stdout.decode(errors='replace')[-64000:],'stderr':r.stderr.decode(errors='replace')[-64000:]}
        except subprocess.TimeoutExpired as e:
            data={'command':command,'returncode':None,'timeout':True,'stdout':(e.stdout or b'').decode(errors='replace')[-64000:],'stderr':(e.stderr or b'').decode(errors='replace')[-64000:]}
        except OSError as e:data={'command':command,'returncode':None,'timeout':False,'stdout':'','stderr':str(e)}
        data.update(mode=mode,elapsed_seconds=time.monotonic()-start,streams_may_be_truncated=True);receipt['runs'].append(data)
        atomic(out/'execution.json',receipt)
        return data['returncode']==0 and 'RELAY_ASSETS_'+mode.upper()+'_OK' in data['stdout']
    try:
        if not run('build',stage):raise ValueError('Asset build failed; see process receipt')
        candidate=safe_file(stage,'candidate.blend');shutil.copyfile(candidate,out/'candidate.blend')
        expected={f['path']:f['sha256'] for f in manifest['files']}
        for name,digest in expected.items():
            if file_hash(safe_file(stage,name))!=digest:raise ValueError('Staged source asset changed')
        expected.update({'candidate.blend':file_hash(candidate),'manifest.json':file_hash(stage/'manifest.json')})
        if sum(safe_file(stage,p).stat().st_size for p in expected)>frozen['limits']['output_bytes']//2:raise ValueError('Bundle exceeds retained output budget')
        with zipfile.ZipFile(out/'bundle.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
            for name in sorted(expected):z.write(safe_file(stage,name),name)
        restored=control/'relocated-bundle';extract_bundle(out/'bundle.zip',restored,expected,frozen['limits']['output_bytes']//2)
        stage.rename(control/'retired-asset-stage')
        if not run('verify',restored):raise ValueError('Relocated candidate verification failed')
        checks=json.loads(safe_file(workspace,'delivery/checks.json').read_text())
        if checks.get('passed') is not True:raise ValueError('Asset checks did not pass')
        if safe_file(workspace,'delivery/preview.png').read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid preview')
        if any(file_hash(safe_file(workspace,i['path']))!=i['sha256'] for i in frozen['inputs']):raise ValueError('Frozen source changed')
        atomic(out/'manifest.json',{'request':manifest,'bundle_files':expected,'bundle_sha256':file_hash(out/'bundle.zip'),
            'candidate_sha256':file_hash(out/'candidate.blend'),'source_versions':receipt['inputs'],'attempt':frozen['assignment_id'],'selected':False})
        if sum(p.stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:raise ValueError('Output budget exceeded')
        receipt['passed']=True
    except (ValueError,OSError,zipfile.BadZipFile) as exc:receipt['error']=str(exc)
    receipt['recorded_at']=time.time();atomic(out/'execution.json',receipt)
    passed=receipt['passed'];summary='Portable candidate and exact source bundle verified after relocation; awaiting review/selection.' if passed else 'Asset import blocked: '+receipt['error']+'. No automatic retry.'
    details={'outcome':'completed' if passed else 'failed','execution':frozen['execution'],'summary':summary,'usage':{}}
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',{'assignment_id':frozen['assignment_id'],'summary':summary,'decision':'delivered' if passed else 'blocked','instruction':'','checks':[{'criterion':1,'passed':passed,'evidence':'delivery/checks.json and delivery/execution.json'}]})
    return details
