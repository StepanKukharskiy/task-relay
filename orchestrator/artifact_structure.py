"""Registered structural checks and content fingerprints, never semantic acceptance."""
import hashlib
import io
import json
import posixpath
import zipfile
from pathlib import PurePosixPath, Path
from xml.etree import ElementTree as ET

PPTX='application/vnd.openxmlformats-officedocument.presentationml.presentation'


def pptx(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or len(names)>10000 or sum(i.file_size for i in z.infolist())>100000000:
            raise ValueError('Invalid or oversized document package')
        for name in names:
            if name.startswith('/') or '..' in PurePosixPath(name).parts:raise ValueError('Invalid document member path')
        members={n:z.read(n) for n in names}
    xml={}
    for name,data in members.items():
        if name.endswith(('.xml','.rels')):
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('Document XML declarations are unsupported')
            xml[name]=ET.fromstring(data)
    presentation=xml['ppt/presentation.xml']
    ids=presentation.findall('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst/{http://schemas.openxmlformats.org/presentationml/2006/main}sldId')
    if not ids:raise ValueError('Presentation contains no slides')
    targets={}
    for name,node in xml.items():
        if not name.endswith('.rels'):continue
        base=posixpath.dirname(posixpath.dirname(name))
        rels={}
        for rel in node:
            if rel.get('TargetMode')=='External':continue
            target=rel.get('Target','')
            dest=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(base,target))
            if dest not in members:raise ValueError('Broken document relationship: '+dest)
            if rel.get('Id') in rels:raise ValueError('Duplicate document relationship')
            rels[rel.get('Id')]=dest
        targets[name]=rels
    slide_paths=[]
    for item in ids:
        rid=item.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        path=targets.get('ppt/_rels/presentation.xml.rels',{}).get(rid)
        if not path or path not in xml:raise ValueError('Slide reference is missing')
        slide_paths.append(path)
    if len(set(slide_paths))!=len(slide_paths):raise ValueError('Repeated slide relationship')
    # Container ordering/timestamps and package properties are not draft progress.
    content={n:hashlib.sha256(v).hexdigest() for n,v in members.items() if not n.startswith('docProps/')}
    return dict(units=len(ids),fingerprint=hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest())


def pdf(raw):
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(raw),strict=True)
    if reader.is_encrypted:raise ValueError('Encrypted PDF cannot be inspected')
    if not len(reader.pages):raise ValueError('PDF contains no pages')
    # Raw identity is retained for formats without a qualified content normalizer.
    return dict(units=len(reader.pages),fingerprint=hashlib.sha256(raw).hexdigest())


def json_data(raw):
    value=json.loads(raw)
    return dict(units=len(value) if isinstance(value,(dict,list)) else 1,
        fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())


REGISTRY={PPTX:dict(extensions=['.pptx'],inspect=pptx),
          'application/pdf':dict(extensions=['.pdf'],inspect=pdf),
          'application/json':dict(extensions=['.json'],inspect=json_data)}


def inspect(output,raw):
    suffix=PurePosixPath(output['path']).suffix.lower()
    matches=[(media,entry) for media,entry in REGISTRY.items() if output.get('media_type')==media or suffix in entry['extensions']]
    if not matches:return None
    if len(matches)!=1:raise ValueError('Document extension conflicts with declared format')
    media,entry=matches[0]
    try:detail=entry['inspect'](raw)
    except Exception as exc:
        raise ValueError('Structural check failed for '+output['path']+': '+str(exc)) from exc
    return dict(format=media,version=1,sha256=hashlib.sha256(raw).hexdigest(),**detail)


def progress(outputs,read):
    state={};failures=[]
    for output in outputs:
        raw=read(output['path'])
        try:receipt=inspect(output,raw)
        except ValueError as exc:failures.append(str(exc));continue
        state[output['path']]=receipt['fingerprint'] if receipt else hashlib.sha256(raw).hexdigest()
    return state,failures


def inspect_cached(output,raw,folder):
    """Reuse only exact bytes and exact registered validator implementation."""
    import inspect as python_inspect
    from .workers import atomic
    suffix=PurePosixPath(output['path']).suffix.lower()
    entries=[(media,entry) for media,entry in REGISTRY.items() if output.get('media_type')==media or suffix in entry['extensions']]
    if len(entries)!=1:return inspect(output,raw)
    media,entry=entries[0];hook=entry['inspect']
    source=python_inspect.getsourcefile(hook)
    identity=dict(format=media,version=entry.get('version',1),sha256=hashlib.sha256(raw).hexdigest(),
        implementation=hashlib.sha256(Path(__file__).read_bytes()+(Path(source).read_bytes() if source else b'')).hexdigest(),hook=hook.__module__+'.'+hook.__qualname__)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    path=Path(folder)/(key+'.json')
    if path.exists():
        saved=json.loads(path.read_text())
        if saved.get('identity')!=identity or saved.get('receipt',{}).get('sha256')!=identity['sha256']:
            raise ValueError('Structural receipt identity changed')
        return saved['receipt']
    receipt=inspect(output,raw)
    Path(folder).mkdir(parents=True,exist_ok=True)
    atomic(path,dict(identity=identity,receipt=receipt))
    return receipt


def check_outputs(assignment,read,cache=None):
    return [r for o in assignment['outputs'] if (r:=(inspect_cached(o,read(o['path']),cache) if cache else inspect(o,read(o['path'])))) is not None]
