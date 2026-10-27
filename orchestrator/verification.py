"""Code-owned deterministic evidence receipts. Never semantic acceptance."""
import hashlib
import io
import json
from pathlib import Path
import platform
import time
import uuid
import zipfile

from . import contracts as c

INSTRUCTIONS = ('Relay supplies verification with code-owned deterministic check receipts. '
    'Reuse passing mechanical checks for the exact unchanged input hashes; do not write another '
    'hash/archive/JSON audit to repeat those checks. Failed or missing checks remain unresolved. '
    'These receipts do not verify factual meaning, visual correspondence, current availability, '
    'or acceptance. Independently review the candidate and all required semantic criteria. '
    'The change list is navigation evidence, not permission to skip previously unchecked content. '
    'Newly written outputs still require their declared validation.')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS production_verifications(
        id TEXT PRIMARY KEY, check_key TEXT NOT NULL, definition TEXT NOT NULL,
        result TEXT NOT NULL, result_sha256 TEXT NOT NULL, created REAL NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS production_verifications_key ON production_verifications(check_key)')


def implementation():
    # Conservative dependency closure: an unrelated runtime update also invalidates
    # receipts. Narrow this only when validators declare complete dependencies.
    import zlib
    try:
        from PIL import __version__ as pillow_version, features
        codecs={k:features.version(k) for k in ('jpg','zlib','webp')}
    except ImportError:
        pillow_version=None;codecs={}
    return dict(sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(Path(__file__).parent.glob('*.py'))},
                python=platform.python_version(),pillow=pillow_version,
                codecs=codecs,
                zlib=zlib.ZLIB_RUNTIME_VERSION)


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    def constant(_):raise ValueError('Non-finite JSON number')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def evaluate(check,raw,parameters):
    if parameters:raise ValueError('Unsupported verification parameters')
    if check=='json.structure':
        value=strict_json(raw)
        return dict(type=type(value).__name__,members=len(value) if isinstance(value,(dict,list)) else None)
    if check=='image.decode':
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height>32_000_000:raise ValueError('Image exceeds deterministic decode pixel allowance')
                image.load()
                return dict(format=image.format,width=image.width,height=image.height)
        except Image.DecompressionBombError as exc:raise ValueError('Image exceeds deterministic decode pixel allowance') from exc
    if check=='images.archive':
        from .image_sources import unpack
        images,_,manifest=unpack(raw)
        return dict(subjects=len(manifest['subjects']),usable_images=len(images),
                    missing=sum(s['status']=='missing' for s in manifest['subjects']),
                    scope='Archive membership, declared byte hashes and retained-image conversion integrity only')
    raise ValueError('Unregistered deterministic check')


def verify(db,check,raw,*,parameters=None,code=None):
    if not db.in_transaction:raise ValueError('Verification receipts require an atomic transaction')
    if check not in ('json.structure','image.decode','images.archive'):raise ValueError('Unregistered deterministic check')
    definition=dict(version=1,check=check,parameters=parameters or {},
                    inputs=[dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))],
                    implementation=code if code is not None else implementation())
    encoded=c.encoded(definition);key=c.digest(definition)
    for row in db.execute('SELECT id,definition,result,result_sha256 FROM production_verifications WHERE check_key=? ORDER BY created DESC,id',(key,)):
        if row['definition']!=encoded or hashlib.sha256(row['result'].encode()).hexdigest()!=row['result_sha256']:continue
        try:result=json.loads(row['result'])
        except ValueError:continue
        if not isinstance(result,dict) or type(result.get('passed')) is not bool:continue
        if result['passed'] and not isinstance(result.get('observations'),dict):continue
        if not result['passed'] and not isinstance(result.get('error'),str):continue
        return dict(receipt=row['id'],check=check,key=key,reused=True,**result)
    try:result=dict(passed=True,observations=evaluate(check,raw,definition['parameters']))
    except (ValueError,OSError,KeyError,TypeError,ImportError,RecursionError,zipfile.BadZipFile) as exc:
        result=dict(passed=False,error=str(exc)[:300])
    ident=uuid.uuid4().hex;encoded_result=c.encoded(result)
    db.execute('INSERT INTO production_verifications VALUES (?,?,?,?,?,?)',
               (ident,key,encoded,encoded_result,hashlib.sha256(encoded_result.encode()).hexdigest(),time.time()))
    return dict(receipt=ident,check=check,key=key,reused=False,**result)


def json_changes(before,after,limit=200):
    """Exact JSON pointers; structural array edits invalidate the whole array."""
    old,new=strict_json(before),strict_json(after);paths=[];truncated=False
    def visit(a,b,path,depth=0):
        nonlocal truncated
        if c.encoded(a)==c.encoded(b):return
        if len(paths)>=limit:truncated=True;return
        if depth>=32 or len(path)>2048:
            paths.append(path);truncated=True;return
        if isinstance(a,dict) and isinstance(b,dict) and a.keys()==b.keys():
            for key in sorted(a):visit(a[key],b[key],path+'/'+key.replace('~','~0').replace('/','~1'),depth+1)
        elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            for index,(x,y) in enumerate(zip(a,b)):visit(x,y,path+'/'+str(index),depth+1)
        else:paths.append(path)
    visit(old,new,'')
    return dict(changed_json_pointers=paths,complete=not truncated,
                whole_candidate_review_required=True,semantic_acceptance=False)


def selected_check(item,raw):
    media=item.get('media_type','');suffix=Path(item['path']).suffix.lower()
    if media=='application/json' or suffix=='.json':return 'json.structure'
    if media in ('image/png','image/jpeg','image/webp','image/avif'):return 'image.decode'
    if media=='application/zip' or suffix=='.zip':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info=archive.getinfo('manifest.json')
                if info.file_size>1_000_000:return None
                value=strict_json(archive.read(info))
                if isinstance(value,dict) and value.get('kind')=='task-relay-sourced-images':return 'images.archive'
        except (ValueError,OSError,KeyError,zipfile.BadZipFile):pass
    return None


def stage(rt,plan,frozen,relay):
    frozen.pop('verification',None)
    marker=plan.get('origin',{}).get('registered_revision',{})
    if frozen.get('execution') or not (frozen.get('review_of') or marker):return
    from .runtime import safe_file,file_hash
    code=implementation();checks=[]
    for item in frozen['inputs']:
        raw=safe_file(Path(frozen['workspace']),item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Verification input changed')
        check=selected_check(item,raw)
        if check:
            checks.append(dict(path=item['path'],artifact=item['artifact'],sha256=item['sha256'],
                               **verify(rt.db,check,raw,code=code)))
    packet=dict(version=1,instructions=INSTRUCTIONS,checks=checks,semantic_acceptance=False)
    prior=marker.get('proof',{}).get('candidate')
    current=[i for i in frozen['inputs'] if i.get('from_task')==frozen.get('review_of') and i.get('media_type')=='application/json']
    if prior and len(current)==1:
        artifact=rt.artifact(prior['artifact']);blob=safe_file(rt.root,str(Path(artifact['blob']).relative_to(rt.root)))
        if file_hash(blob)!=prior['sha256']:raise ValueError('Prior comparison candidate changed')
        try:
            packet['changes']=dict(before_artifact=prior['artifact'],before_sha256=prior['sha256'],
                after_artifact=current[0]['artifact'],after_sha256=current[0]['sha256'],
                **json_changes(blob.read_bytes(),safe_file(Path(frozen['workspace']),current[0]['path']).read_bytes()))
        except (ValueError,UnicodeError,RecursionError):
            packet['changes']=dict(complete=False,whole_candidate_review_required=True,reason='No safe structural comparison available')
    path=relay/'verification.json';path.write_text(c.encoded(packet)+'\n');path.chmod(0o400)
    frozen['verification']=packet
    rt.event(frozen['run'],frozen['id'],frozen['assignment_id'],'deterministic_checks_bound',
             dict(receipts=[r['receipt'] for r in checks],reused=sum(r['reused'] for r in checks),
                  executed=sum(not r['reused'] for r in checks),packet_sha256=file_hash(path),semantic_acceptance=False))
