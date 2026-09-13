"""Registered asynchronous media operations; one submission, retained remote identity."""
import base64
import hashlib
import io
import json
import os
import struct
import time

from task_relay import cloud_providers as providers, gemini
from .workers import atomic

KINDS = {'runway.image':'image', 'runway.video':'video', 'higgsfield.image':'image',
         'higgsfield.video':'video', 'meshy.mesh':'mesh'}
OUTPUTS = {'image':('image/png','.png'), 'video':('video/mp4','.mp4'), 'mesh':('model/gltf-binary','.glb')}
SPECS = {}
for ident, kind in KINDS.items():
    params={'model':'Exact configured model ID', 'prompt':'Self-contained generation brief preserving the original intent, without Relay routing instructions; maximum '+('800' if kind=='mesh' else '1000')+' characters'}
    if kind!='mesh': params['aspect_ratio']='16:9 or 9:16'
    if kind=='video': params['duration']='Integer seconds: 2–10'
    SPECS[ident]={'version':1,'kind':'api','input_types':['text/plain','text/markdown']+(['image/png','image/jpeg','image/webp'] if ident.startswith('runway.') else []),
        'output_type':OUTPUTS[kind][0], 'max_inputs':20,'input_bytes':11000000,'seconds':600,'output_bytes':50000000,
        'parameters':params,'external_requests':1,
        'criteria':['One provider task completed and its bounded '+('PNG decoded' if kind=='image' else 'MP4 container checked' if kind=='video' else 'self-contained GLB mesh checked')+'; output hash and remote identity are recorded. Content, dimensions and suitability require separate review.'],
        'cancellation':'Stop local waiting; accepted remote work may continue and incur usage. Retain remote task identity; never repeat an uncertain submission.',
        'permissions':'One generation POST, bounded status GETs and credential-free public output download. The reviewed prompt and declared image inputs are sent; other input documents remain local context.'}


def validate(capability, params, inputs):
    provider, kind = capability.split('.')
    if params['model'] not in providers.PROVIDERS[provider]['models'][kind]:
        raise ValueError('This media model has no registered request adapter.')
    if not isinstance(params['prompt'],str) or not 1<=len(params['prompt'].strip())<= (800 if kind=='mesh' else 1000):
        raise ValueError('Use a bounded, self-contained generation prompt.')
    if kind!='mesh' and params['aspect_ratio'] not in ('16:9','9:16'): raise ValueError('Unsupported generation aspect ratio.')
    if kind=='video' and (type(params['duration']) is not int or not 2<=params['duration']<=10): raise ValueError('Choose a clip duration from 2 to 10 seconds.')
    count=sum(i.get('media_type','').startswith('image/') for i in inputs)
    maximum=3 if capability=='runway.image' else 1 if capability=='runway.video' else 0
    if count>maximum: raise ValueError('This operation supports at most '+str(maximum)+' image references. No selected reference may be discarded.')


def request(capability, params, references):
    validate(capability, params, [{'media_type':mime} for mime,_ in references])
    provider, kind=capability.split('.')
    if any(len(raw)>3_500_000 for _,raw in references): raise ValueError('A Runway reference exceeds the local data-URI limit.')
    refs=['data:'+mime+';base64,'+base64.b64encode(raw).decode() for mime,raw in references]
    if provider=='meshy':
        return '/openapi/v2/text-to-3d', {'mode':'preview','model_type':'standard','ai_model':params['model'],
            'prompt':params['prompt'],'should_remesh':False}
    if provider=='higgsfield':
        body={'prompt':params['prompt'],'aspect_ratio':params['aspect_ratio']}
        if kind=='image': body.update(num_images=1,resolution='2K')
        else: body.update(duration=params['duration'],resolution='720',camera_fixed=False)
        return '/'+params['model'], body
    body={'model':params['model'],'promptText':params['prompt']}
    if kind=='image':
        body['ratio']='1920:1080' if params['aspect_ratio']=='16:9' else '1080:1920'
        if refs: body['referenceImages']=[{'uri':uri,'tag':'ref'+str(n+1)} for n,uri in enumerate(refs)]
        return '/text_to_image',body
    body.update(ratio='1280:720' if params['aspect_ratio']=='16:9' else '720:1280',duration=params['duration'])
    if refs: body['promptImage']=refs[0]
    return '/image_to_video',body


def state(provider, response):
    status=response.get('status')
    if status in ('SUCCEEDED','completed'): return 'completed'
    if status in ('FAILED','CANCELED','CANCELLED','failed','canceled','cancelled','nsfw','EXPIRED'): return 'failed'
    if status in ('PENDING','THROTTLED','RUNNING','IN_PROGRESS','queued','in_progress'): return 'pending'
    raise ValueError('Unknown remote generation state; retain the receipt and inspect it before continuing.')


def output_url(provider, kind, response):
    if provider=='runway': urls=response.get('output',[])
    elif provider=='meshy': urls=[response.get('model_urls',{}).get('glb')]
    elif kind=='image': urls=[i.get('url') for i in response.get('images',[])]
    else: urls=[response.get('video',{}).get('url')]
    if not isinstance(urls,list) or len(urls)!=1 or not isinstance(urls[0],str):
        raise ValueError('Expected one completed output; inspect the saved provider response.')
    return urls[0]


def validate_output(kind, data):
    if kind=='image':
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            if image.width*image.height>40000000: raise ValueError('Generated image exceeds the pixel limit.')
            image.load();buffer=io.BytesIO();image.convert('RGBA' if 'A' in image.getbands() else 'RGB').save(buffer,format='PNG')
            return buffer.getvalue()
    if kind=='video':
        offset=0;boxes=set()
        while offset<len(data):
            if offset+8>len(data): raise ValueError('Incomplete MP4 container.')
            size,tag=struct.unpack_from('>I4s',data,offset);header=8
            if size==1:
                if offset+16>len(data): raise ValueError('Incomplete MP4 container.')
                size=struct.unpack_from('>Q',data,offset+8)[0];header=16
            if size==0:size=len(data)-offset
            if size<header or offset+size>len(data): raise ValueError('Invalid MP4 box size.')
            boxes.add(tag);offset+=size
        if not {b'ftyp',b'moov',b'mdat'}<=boxes: raise ValueError('Provider output is not a complete MP4 container.')
        return data
    if len(data)<20 or data[:4]!=b'glTF' or struct.unpack_from('<II',data,4)!=(2,len(data)):
        raise ValueError('Provider output is not a GLB 2.0 file.')
    length,tag=struct.unpack_from('<II',data,12)
    if tag!=0x4e4f534a or length%4 or 20+length>len(data): raise ValueError('Invalid GLB JSON chunk.')
    doc=json.loads(data[20:20+length])
    if not doc.get('meshes') or any('uri' in b for b in doc.get('buffers',[])) or any('uri' in i and not i['uri'].startswith('data:') for i in doc.get('images',[])):
        raise ValueError('Expected a self-contained GLB mesh without external resource paths.')
    offset=20+length
    while offset<len(data):
        if offset+8>len(data): raise ValueError('Invalid GLB chunk.')
        size,_=struct.unpack_from('<II',data,offset)
        if size%4 or offset+8+size>len(data): raise ValueError('Invalid GLB chunk size.')
        offset+=8+size
    return data


def generate(capability, params, references, control, seconds, limit, client=None, downloader=None, sleep=time.sleep, clock=time.monotonic):
    provider,kind=capability.split('.')
    config=providers.read_config(provider) if client is None else None
    if client is None and not config: raise ValueError('Connect '+providers.PROVIDERS[provider]['name']+' in Task Relay Settings first.')
    client=client or providers.Client(provider,config['api_key'])
    downloader=downloader or providers.download
    path,payload=request(capability,params,references)
    frozen={'provider':provider,'path':path,'payload':payload}
    intent=control/'request.json';accepted=control/'accepted.json';terminal=control/'response.json'
    if intent.exists():
        if json.loads(intent.read_text())!=frozen: raise ValueError('Saved generation request differs; no submission was sent.')
        if not accepted.exists(): raise ValueError('Previous submission outcome is unknown. No automatic resubmission.')
    else:
        with intent.open('x') as stream:
            json.dump(frozen,stream);stream.flush();os.fsync(stream.fileno())
        try: response=client.request(path,payload)
        except gemini.ProviderError as exc:
            atomic(control/'operation.json',{'outcome':'uncertain' if exc.uncertain else 'rejected','reason':str(exc),'usage':None})
            raise
        # Save the entire accepted response before interpreting its identifier.
        atomic(accepted,response)
    response=json.loads(accepted.read_text())
    ident=providers.task_id(response.get('id') if provider=='runway' else response.get('request_id') if provider=='higgsfield' else response.get('result'))
    poll=providers.poll_path(provider,ident)
    atomic(control/'remote.json',{'provider':provider,'task_id':ident,'poll_path':poll,'request_sha256':hashlib.sha256(intent.read_bytes()).hexdigest()})
    deadline=clock()+max(1,seconds-100)
    if terminal.exists(): response=json.loads(terminal.read_text())
    else:
        while True:
            if clock()>=deadline: raise ValueError('Generation is still pending; its task ID was retained. Do not submit it again.')
            response=client.request(poll)
            atomic(control/'latest.json',response)
            returned=response.get('request_id' if provider=='higgsfield' else 'id')
            if returned!=ident: raise ValueError('Provider returned another task identity; no output was accepted.')
            status=state(provider,response)
            if status!='pending':
                atomic(terminal,response);break
            sleep(5)
    if state(provider,response)!='completed': raise ValueError('The provider reported generation failure; its response is retained. No automatic retry.')
    raw=downloader(output_url(provider,kind,response),limit)
    data=validate_output(kind,raw)
    if len(data)>limit: raise ValueError('Generated media exceeds the approved output limit.')
    return data, ident, response.get('usage',{'consumed_credits':response['consumed_credits']} if 'consumed_credits' in response else {})
