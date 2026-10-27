"""Bounded pixel reads from declared PNG files and PNG members of ZIP files."""
import hashlib
import io
import zipfile
import base64
import json
from pathlib import Path
from .browser_contract import png_info,MAX_PNG_BYTES
from .contracts import relative
from .image_representation import inspection_preview

DEFINITION=dict(name='image_view',description='Inspect assigned image pixels or an exact registered evidence representation. Oversized PNG/JPEG images automatically receive an aspect-preserving preview within the existing display bounds; original bytes remain unchanged. Receipts distinguish source_sha256 and source_dimensions from displayed sha256, dimensions and transformation. A preview may omit fine detail and is not an exact-resolution inspection. For a ZIP or represented document use members:[] to list image names, then up to eight exact members per call. No network or generated images.',parameters=dict(type='object',properties=dict(path={'type':'string'},members={'type':'array','items':{'type':'string'}}),required=['path','members']))


def confirmed_pixels(control):
    """Hashes of actual image parts in requests with a recorded model response.

    A tool receipt, transport flag or image-shaped text is not observation. Only
    provider image fields count; lost/rejected requests cannot establish review.
    """
    result=set()
    for path in Path(control).glob('api-*.request.json'):
        response=path.with_name(path.name.replace('.request.json','.response.json'))
        if not response.is_file():continue
        record=json.loads(path.read_text());payload=record['payload'];encoded=[]
        if record['provider']=='gemini':
            for message in payload.get('contents',[]):
                if message.get('role')!='user':continue
                for part in message.get('parts',[]):
                    image=part.get('inlineData',{})
                    if image.get('mimeType')=='image/png':encoded.append(image.get('data',''))
        else:
            messages=payload.get('input',[]) if record['provider']=='openai' else payload.get('messages',[])
            for message in messages:
                if not isinstance(message,dict) or message.get('role')!='user':continue
                content=message.get('content',[])
                if not isinstance(content,list):continue
                for part in content:
                    url=part.get('image_url') if part.get('type')=='input_image' else part.get('image_url',{}).get('url') if part.get('type')=='image_url' else None
                    if isinstance(url,str) and url.startswith('data:image/png;base64,'):encoded.append(url.split(',',1)[1])
        for value in encoded:
            raw=base64.b64decode(value,validate=True);png_info(raw)
            digest=hashlib.sha256(raw).hexdigest()
            if record['provider']=='codex':
                # Multiple CLI tool calls can originate from one generation.
                # A queued call is not proof that later image replies were seen.
                received=json.loads(response.read_text())
                if digest not in received.get('relay_transport',{}).get('observed_pixel_sha256',[]):continue
            result.add(digest)
    return result


def rendered_pixels(raw,media_type):
    """All displayed page hashes derived from the exact registered render."""
    if media_type=='image/png':
        data,_=inspection_preview(raw,'render.png');return {hashlib.sha256(data).hexdigest()}
    if media_type!='application/zip':return set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        pages=[i for i in archive.infolist() if i.filename.lower().endswith('.png')]
        if not 1<=len(pages)<=200 or sum(i.file_size for i in pages)>100000000:
            raise ValueError('Rendered pixel evidence exceeds its bounded page scope')
        result=set()
        for info in pages:
            relative(info.filename);data,_=inspection_preview(archive.read(info),info.filename)
            result.add(hashlib.sha256(data).hexdigest())
        return result


def read(files,args):
    if set(args)!={'path','members'} or not isinstance(args['members'],list) or len(args['members'])>8:raise ValueError('Read at most eight declared PNG images')
    path=args['path']
    if path not in files.inputs and (path not in files.outputs or path not in files.written):raise ValueError('Visual inspection requires an exact assigned input or saved declared draft')
    from .artifact_roles import view
    route=view(files,path)
    if route and route['path']!=path:
        result=read(files,dict(args,path=route['path']))
        result['evidence']=dict(path=path,representation=route)
        return result
    raw=files.read_bytes(path)
    if path in files.inputs and hashlib.sha256(raw).hexdigest()!=files.inputs[path]['sha256']:raise ValueError('Visual source changed')
    images=[]
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if not args['members']:return dict(path=path,members=[x.filename for x in archive.infolist() if x.filename.lower().endswith(('.png','.jpg','.jpeg'))][:200])
            total=0
            for member in args['members']:
                relative(member);info=archive.getinfo(member);total+=info.file_size
                if not member.lower().endswith(('.png','.jpg','.jpeg')) or total>MAX_PNG_BYTES:raise ValueError('Visual member pack exceeds image scope')
                images.append((member,archive.read(info)))
    else:
        if args['members']:raise ValueError('Members apply only to a ZIP')
        images=[(path,raw)]
    result=[];pixels=[];total=0
    for name,data in images:
        source_hash=hashlib.sha256(data).hexdigest()
        data,representation=inspection_preview(data,name);total+=len(data)
        if total>MAX_PNG_BYTES:raise ValueError('Visual preview pack exceeds 10 MB; request fewer members')
        result.append(dict(path=path,member=name,sha256=hashlib.sha256(data).hexdigest(),source_sha256=source_hash,**representation,**png_info(data)));pixels.append(data)
    return dict(images=result,_pixels=pixels)
