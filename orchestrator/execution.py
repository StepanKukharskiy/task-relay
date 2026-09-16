"""Versioned graph capabilities. Plans choose registered operations, never commands."""
import copy
import importlib.util
import re
from .media_adapters import PROVIDERS as IMAGE_PROVIDERS
from .cloud_media import SPECS as CLOUD_MEDIA

TEXT_TYPES = ('text/plain','text/markdown')
REGISTRY = {
    'text.bundle': {'version':1,'kind':'procedure','input_types':list(TEXT_TYPES),'output_type':'text/plain',
        'max_inputs':20,'input_bytes':2000000,'seconds':30,'output_bytes':2100000,
        'criteria':['Inputs are preserved verbatim in a UTF-8 bundle with artifact identities and hashes.'],
        'parameters':{},'external_requests':0,'cancellation':'Local process termination; no external effects.'},
    'gemini.text': {'version':1,'kind':'api','input_types':list(TEXT_TYPES),'output_type':'text/plain',
        'max_inputs':20,'input_bytes':120000,'seconds':180,'output_bytes':200000,
        'criteria':['The API returned complete nonempty text within the declared bounds; its content is not independently verified.'],
        'parameters':{'model':'Exact configured or explicitly chosen model ID','max_output_tokens':'Integer 1–4096'},
        'external_requests':1,'cancellation':'Stop local waiting; an accepted remote request cannot be undone and usage may remain unknown.'},
    'blender.startup': {'version':1,'kind':'host','input_types':list(TEXT_TYPES),'output_type':'application/json',
        'max_inputs':20,'input_bytes':2000000,'seconds':120,'output_bytes':200000,
        'outputs':{'delivery/execution.json':'application/json'},
        'criteria':['The fixed Blender startup probe has a recorded exit status, output and startup-marker result.'],
        'parameters':{},'external_requests':0,'cancellation':'Terminate the local process group; no automatic retry.',
        'permissions':'Host Blender process with normal OS permissions; fixed Relay probe only; no agent shell escalation.'},
    'blender.scene': {'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/json'],'output_type':None,
        'max_inputs':20,'input_bytes':2000000,'seconds':600,'output_bytes':100000000,
        'outputs':{'delivery/scene.blend':'application/x-blender','delivery/preview.png':'image/png',
                   'delivery/scene-script.py':'text/plain','delivery/execution.json':'application/json'},
        'criteria':['The validated primitive scene is saved, reopened in a separate Blender process, checked and rendered to PNG.'],
        'parameters':{},'external_requests':0,'cancellation':'Terminate the local process group; partial files may remain; no retry.',
        'permissions':'Host Blender process with normal OS permissions; fixed Relay code and bounded primitive JSON only; no arbitrary scripts or existing blend inputs.'},
}

REGISTRY['pptx.create'] = {
    'review_correction':'application/json',
    'version':1, 'kind':'procedure',
    'input_types':[*TEXT_TYPES,'application/json','image/png','image/jpeg','application/zip'],
    'output_type':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'max_inputs':50, 'input_bytes':50000000, 'seconds':120, 'output_bytes':50000000,
    'criteria':['The bounded slide specification produced a PPTX that reopened with matching editable text, tables, chart data and embedded images; visual layout and Keynote import require separate review.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Terminate the local process; preserve partial results and never automatically replay.'}

REGISTRY['images.collect'] = {
    'version':1,'kind':'procedure','input_types':list(TEXT_TYPES),'output_type':'application/zip',
    'min_inputs':0,'max_inputs':20,'input_bytes':120000,'seconds':600,'output_bytes':45000000,
    'criteria':['Each requested subject has a found or missing receipt; downloaded JPEG/PNG candidates retain source, author, licence and byte hashes. Metadata matches are not visual identification.'],
    'parameters':{'subjects':'1–40 {id,label,query} objects; literal public subject names'},
    'external_requests':320,
    'permissions':'Public read-only Wikimedia Commons search and image downloads; no credentials, paid model, generation or arbitrary URLs.',
    'cancellation':'Stop local downloads; retain receipts; no automatic replay.'}

# Separate versioned capability preserves existing primitive-only plan contracts.
REGISTRY.update(CLOUD_MEDIA)
REGISTRY['gemini.image'] = {
    'version':1,'kind':'api','input_types':[*TEXT_TYPES,'image/png','image/jpeg','image/webp'],
    'output_type':'image/png','max_inputs':20,'input_bytes':11000000,'seconds':600,'output_bytes':50000000,
    'criteria':['One complete valid generated image was saved as PNG; its visual and geometric fidelity requires separate review.'],
    'parameters':{'model':'Exact configured image model ID','max_output_tokens':'Integer 1–4096','aspect_ratio':'1:1, 16:9 or 9:16'},
    'external_requests':1,'cancellation':'Stop local waiting; accepted API work cannot be undone. Unknown submissions are never replayed.'}
REGISTRY['openai.image'] = {**copy.deepcopy(REGISTRY['gemini.image']),
    'parameters':{'model':'Exact configured GPT Image model ID','size':'auto, 1024x1024, 1536x1024 or 1024x1536',
                  'quality':'auto, low, medium or high'}}

REGISTRY['openrouter.image'] = {**copy.deepcopy(REGISTRY['gemini.image']),
    'parameters': {'model': 'Exact configured OpenRouter image model slug', 'aspect_ratio': '1:1, 16:9 or 9:16'}}

REGISTRY['blender.mesh_scene']={**copy.deepcopy(REGISTRY['blender.scene']),
    'input_bytes':20000000,
    'criteria':['The validated mesh scene is saved, reopened in a separate Blender process, checked against its geometry data and rendered to PNG.'],
    'permissions':'Host Blender process with normal OS permissions; fixed Relay code and bounded mesh/primitive data only; no arbitrary host scripts or existing blend inputs.'}

REGISTRY['blender.inspect']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/x-blender'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':120,'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact selected Blender scene has a complete bounded inventory, embedded auto-execution disabled and unchanged source-copy hash.'],
    'parameters':{},'external_requests':0,'cancellation':'Terminate the local process group; retain receipt and do not retry.',
    'permissions':'Host inspection of one selected .blend using fixed Relay code with embedded scripts disabled. Native linked libraries may resolve on the host; this is not dependency isolation.'}

# Fixed inspections may supply evidence to an already-declared reviewer.
REGISTRY['blender.inspect']['review_evidence'] = True

REGISTRY['blender.run_python']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/x-blender','text/x-python','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.blend':'application/x-blender','delivery/before.png':'image/png',
               'delivery/after.png':'image/png','delivery/edit.py':'text/plain','delivery/checks.json':'application/json',
               'delivery/execution.json':'application/json'},
    'criteria':['The exact approved script ran against the selected scene copy; a candidate reopened independently, passed the declared preservation/dimension checks and produced matching-camera previews; original input copies remain unchanged.'],
    'parameters':{'scene_sha256':'Selected native scene SHA-256','script_sha256':'Exact reviewed Python SHA-256',
                  'checks_sha256':'Exact JSON verification/preview contract SHA-256','permissions':'unrestricted_host'},
    'external_requests':None,'cancellation':'Terminate the local process group; preserve partial results and never replay. Host script side effects cannot be undone.',
    'permissions':'Explicit exact-script host approval required. Python has normal host filesystem/network access; no workspace or network isolation is enforced. Embedded scene auto-execution stays disabled.'}


REGISTRY['blender.import_asset']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/json','application/x-blender','image/png','image/jpeg'],
    'output_type':None,'max_inputs':50,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.blend':'application/x-blender','delivery/preview.png':'image/png',
               'delivery/bundle.zip':'application/zip','delivery/manifest.json':'application/json',
               'delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['Exact selected assets were appended/packed into a candidate; the retained source bundle preserves paths, hashes and supplied provenance; its candidate reopened after relocation with matching scene and packed image hashes; original inputs remain unchanged.'],
    'parameters':{'manifest_sha256':'Exact registered asset manifest SHA-256'},'external_requests':0,
    'cancellation':'Terminate the local process group; preserve partial files and receipts; never replay automatically.',
    'permissions':'Fixed host append/packing code with embedded auto-execution disabled. Normal host permissions, not filesystem isolation. Only declared selected files are staged; no downloads, persistent links or arbitrary scripts.'}

REGISTRY['blender.animate']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/json','application/x-blender','application/zip'],
    'output_type':None,'max_inputs':30,'input_bytes':150000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.blend':'application/x-blender','delivery/animation.mp4':'video/mp4',
               'delivery/preview.png':'image/png','delivery/checkpoint.zip':'application/zip',
               'delivery/frames.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected scene and numeric animation contract produced an independently reopened candidate, verified frame/FPS and transform checks, hashed per-frame receipts and an encoded video with the exact frame count/dimensions/FPS; original inputs remain unchanged.'],
    'parameters':{'manifest_sha256':'Exact registered animation manifest SHA-256'},'external_requests':0,
    'cancellation':'Terminate the local process group. Explicit continuation can reuse verified completed frames from a confirmed stopped attempt. Unresolved frame intents block; no automatic retry.',
    'permissions':'Fixed native Blender and ffmpeg operations with embedded scripts disabled, normal OS permissions. Numeric transforms only; no arbitrary Python, downloads or simulation. Output remains unselected.'}


REGISTRY['rhino.startup'] = {
    'version':1, 'kind':'host', 'input_types':list(TEXT_TYPES), 'output_type':None,
    'max_inputs':20, 'input_bytes':2000000, 'seconds':120, 'output_bytes':200000,
    'outputs':{'delivery/execution.json':'application/json'},
    'criteria':['The owned Rhino 7/8 process has a recorded interpreter startup result, exit status and runtime evidence.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Terminate the owned supervisor process group; no automatic retry.',
    'permissions':'Fixed startup script with normal host permissions; macOS Rhino 7/8 desktop session required. No Grasshopper.'}
REGISTRY['rhino.inspect'] = {
    **copy.deepcopy(REGISTRY['rhino.startup']), 'input_types':[*TEXT_TYPES,'application/vnd.rhino'],
    'input_bytes':100000000, 'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact selected .3dm has a complete bounded geometry/document inventory and unchanged source-copy hash.'],
    'permissions':'Fixed native .3dm inspection in an owned Rhino process. Native dependencies/plugins use normal host permissions; not filesystem isolation. No Grasshopper.'}
REGISTRY['rhino.inspect']['review_evidence'] = True

REGISTRY['rhino.run_python'] = {
    'version':1, 'kind':'host', 'input_types':[*TEXT_TYPES,'application/vnd.rhino','text/x-python','application/json'],
    'output_type':None, 'max_inputs':20, 'input_bytes':100000000, 'seconds':600, 'output_bytes':100000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/preview.png':'image/png',
               'delivery/model.py':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved Rhino Python created/edited an assigned document; the saved candidate reopened in a separate process, passed declared geometry/preservation checks and produced a viewport preview; input copies remain unchanged.'],
    'parameters':{'scene_sha256':'Selected .3dm SHA-256, or null for a new model',
                  'script_sha256':'Exact reviewed source SHA-256 for the selected Rhino interpreter', 'checks_sha256':'Exact Rhino checks JSON SHA-256',
                  'permissions':'unrestricted_host'}, 'external_requests':None,
    'cancellation':'Terminate the owned supervisor process group. Preserve partial files; no automatic replay. Script side effects cannot be undone.',
    'permissions':'Exact-script approval required for IronPython 2.7 (Rhino 7) or CPython 3 (Rhino 8)/RhinoCommon with normal host filesystem/network access. No OS isolation. Grasshopper support is paused.'}

REGISTRY['rhino.render'] = {
    'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/vnd.rhino','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':10000000,
    'outputs':{'delivery/render.png':'image/png','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected model rendered through built-in Rhino Render from the exact named-view/resolution manifest; PNG dimensions and source-copy preservation were checked.'],
    'parameters':{'manifest_sha256':'Exact registered render manifest SHA-256'},'external_requests':0,
    'cancellation':'Terminate the owned process group; keep partial files and receipts, never automatically replay.',
    'permissions':'Fixed host rendering with model materials/lighting and normal OS permissions. No arbitrary script, third-party renderer or model save; Grasshopper paused.'}


# These operations need already registered versions before execution approval.
for _capability in ('blender.run_python','blender.import_asset','blender.animate',
                    'rhino.run_python','rhino.render'):
    REGISTRY[_capability]['requires_registered_inputs'] = True


def catalog():
    from task_relay import gemini, api_providers
    config=gemini.read_config()
    result = [dict(id=ident,**copy.deepcopy(spec),available=not ident.startswith('gemini.') or bool(config),
        availability_evidence='Local implementation; provider configuration only, not authentication proof.',
        configured_model=(config.get('models',{}).get(ident.split('.')[1],gemini.DEFAULT_MODELS[ident.split('.')[1]]) if config and ident.startswith('gemini.') else None))
        for ident,spec in REGISTRY.items()]
    for entry in result:
        if entry['id']=='images.collect':
            from .image_sources import DESCRIPTION
            entry['image_source_schema']=DESCRIPTION
            entry.update(available=importlib.util.find_spec('PIL') is not None,
                         availability_evidence='Public Commons adapter and local image validation; live coverage varies by subject.')
        if entry['id'] in CLOUD_MEDIA:
            from task_relay.cloud_providers import read_config
            provider,kind=entry['id'].split('.')
            selected=read_config(provider)
            entry.update(available=bool(selected), configured_model=(selected or {}).get('models',{}).get(kind),
                         availability_evidence='Saved API credential and implemented model adapter; generation access and credits are unverified.')
            entry['available']=entry['available'] and bool(entry['configured_model'])
        if entry['id']=='pptx.create':
            from . import pptx_document
            entry['slide_schema']=pptx_document.DESCRIPTION
            try:pptx_document.available()
            except ValueError as exc:entry.update(available=False,availability_evidence=str(exc))
            else:entry['availability_evidence']='Local python-pptx dependency available; native-app import and visual quality are not qualified.'
        if entry['id'] in IMAGE_PROVIDERS and IMAGE_PROVIDERS[entry['id']] != 'gemini':
            provider=IMAGE_PROVIDERS[entry['id']]; selected=api_providers.read_config(provider)
            model=(selected or {}).get('models',{}).get('image')
            entry.update(available=bool(selected and model),configured_model=model,
                availability_evidence='Configured image model and credentials; account access unverified. Set the image default in /providers.')
        if (entry['id'] in IMAGE_PROVIDERS or entry['id'] in CLOUD_MEDIA and entry['id'].endswith('.image')) and importlib.util.find_spec('PIL') is None:
            entry.update(available=False,availability_evidence='Image conversion dependency missing. Install task-relay[images] or use a rebuilt desktop app.')
    from task_relay.host_apps import blender,rhino
    from .blender_host import SCENE_DESCRIPTION,MESH_DESCRIPTION
    app=blender()
    for entry in result:
        if entry['kind']=='host':
            if entry['id'].startswith('rhino.'):
                rhino_app=rhino()
                entry.update(available=rhino_app['available'],availability_evidence=rhino_app['evidence'])
                if entry['id']=='rhino.run_python':
                    from .rhino_contract import DESCRIPTION
                    entry['checks_schema']=DESCRIPTION
                if entry['id']=='rhino.render':
                    from .rhino_contract import RENDER_DESCRIPTION
                    entry['render_schema']=RENDER_DESCRIPTION
                entry['rhino_version']=rhino_app.get('version')
                entry['interpreter']=rhino_app.get('interpreter')
                continue
            entry.update(available=app['available'],availability_evidence=app['evidence'])
            if entry['id']=='blender.scene':entry['scene_schema']=SCENE_DESCRIPTION
            if entry['id']=='blender.mesh_scene':entry['scene_schema']=MESH_DESCRIPTION
            if entry['id']=='blender.run_python':
                from .blender_edit import CHECKS_DESCRIPTION
                entry['checks_schema']=CHECKS_DESCRIPTION
            if entry['id']=='blender.import_asset':
                from .blender_assets import DESCRIPTION
                entry['asset_schema']=DESCRIPTION
            if entry['id']=='blender.animate':
                from .blender_animation import DESCRIPTION
                from task_relay.host_apps import video_tools
                entry['animation_schema']=DESCRIPTION
                entry['available']=app['available'] and video_tools()['available']
                entry['availability_evidence']='Executable presence only; Blender, ffmpeg and ffprobe required.'
    return result


def validate(a):
    e=a.get('execution')
    if not isinstance(e,dict) or set(e)!={'capability','version','parameters'}:
        raise ValueError('Execution needs an exact capability, version and parameters.')
    spec=REGISTRY.get(e['capability']) if isinstance(e['capability'],str) else None
    if not spec or type(e['version']) is not int or e['version']!=spec['version']:
        raise ValueError('Unknown capability or unsupported execution version.')
    params=e['parameters']
    if not isinstance(params,dict) or set(params)!=set(spec['parameters']):raise ValueError('Invalid registered-operation parameters.')
    if e['capability']=='images.collect':
        from .image_sources import validate_subjects
        validate_subjects(params['subjects'])
        if any(not str(o.get('path','')).endswith('.zip') for o in a.get('outputs',[])):
            raise ValueError('Image collection requires a .zip output.')
    if e['capability'] in CLOUD_MEDIA:
        from .cloud_media import validate as validate_cloud, OUTPUTS
        validate_cloud(e['capability'],params,a.get('inputs',[]))
        if any(not str(o.get('path','')).endswith(OUTPUTS[e['capability'].split('.')[1]][1]) for o in a.get('outputs',[])):
            raise ValueError('Use the registered media output file extension.')
    if e['capability']=='openai.image':
        if not isinstance(params['model'],str) or not re.fullmatch(r'gpt-image-[A-Za-z0-9._-]{1,100}',params['model']):
            raise ValueError('Choose an exact GPT Image model ID; text models cannot generate through the image adapter.')
        if params['size'] not in ('auto','1024x1024','1536x1024','1024x1536') or params['quality'] not in ('auto','low','medium','high'):
            raise ValueError('Unsupported image size or quality.')
        if sum(i.get('media_type','').startswith('image/') for i in a.get('inputs',[]))>6:raise ValueError('Choose at most six image references.')
    if e['capability']=='openrouter.image':
        from task_relay.api_providers import model_name
        model_name(params['model'])
        if '/' not in params['model'] or params['aspect_ratio'] not in ('1:1','16:9','9:16'):
            raise ValueError('Choose an exact OpenRouter image model slug and supported aspect ratio.')
        if sum(i.get('media_type','').startswith('image/') for i in a.get('inputs',[]))>6:
            raise ValueError('Choose at most six image references.')
    if e['capability']=='rhino.render':
        if not isinstance(params['manifest_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',params['manifest_sha256']):
            raise ValueError('Rhino render requires an exact manifest hash')
        for media in ('application/vnd.rhino','application/json'):
            if sum(i.get('media_type')==media for i in a.get('inputs',[]) if isinstance(i,dict))!=1:
                raise ValueError('Rhino render needs exactly one model and manifest')
        if any('artifact' not in i or 'from_task' in i for i in a.get('inputs',[])):
            raise ValueError('Rhino render requires already registered inputs')
    if e['capability']=='rhino.run_python':
        if params['permissions']!='unrestricted_host':raise ValueError('Rhino Python requires unrestricted_host; no isolation is enforced')
        for key in ('scene_sha256','script_sha256','checks_sha256'):
            if key=='scene_sha256' and params[key] is None:continue
            if not isinstance(params[key],str) or not re.fullmatch('[a-f0-9]{64}',params[key]):raise ValueError('Rhino Python requires exact input hashes')
        for media,count in (('application/vnd.rhino',int(params['scene_sha256'] is not None)),('text/x-python',1),('application/json',1)):
            if sum(i.get('media_type')==media for i in a.get('inputs',[]) if isinstance(i,dict))!=count:
                raise ValueError('Rhino Python needs exact script/checks and a scene only for edits')
        if any('artifact' not in i or 'from_task' in i for i in a.get('inputs',[])):
            raise ValueError('Rhino Python accepts only already registered inputs; prepare and review scripts in a separate stage')
    if e['capability']=='blender.animate':
        if not isinstance(params['manifest_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',params['manifest_sha256']):raise ValueError('Select the exact animation manifest hash')
        for media in ('application/json','application/x-blender'):
            if sum(i.get('media_type')==media for i in a.get('inputs',[]))!=1:raise ValueError('Select one animation manifest and one scene')
        if sum(i.get('media_type')=='application/zip' for i in a.get('inputs',[]))>1:raise ValueError('Select at most one animation checkpoint')
        if any('artifact' not in i or 'from_task' in i for i in a.get('inputs',[])):raise ValueError('Animation requires already registered inputs; prepare the manifest in a separate stage')
    if e['capability']=='blender.import_asset':
        if not isinstance(params['manifest_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',params['manifest_sha256']):raise ValueError('Select the exact asset manifest hash')
        if sum(i.get('media_type')=='application/json' for i in a.get('inputs',[]) if isinstance(i,dict))!=1:raise ValueError('Select one asset manifest JSON')
        if any('artifact' not in i or 'from_task' in i for i in a.get('inputs',[])):raise ValueError('Asset imports require already registered files and manifest; prepare them in a separate stage')
    if e['capability']=='blender.run_python':
        if params['permissions']!='unrestricted_host':raise ValueError('Blender Python requires explicit unrestricted_host scope; no isolation is enforced.')
        if any(not isinstance(params[k],str) or not re.fullmatch('[a-f0-9]{64}',params[k]) for k in ('scene_sha256','script_sha256','checks_sha256')):
            raise ValueError('Blender Python needs exact scene, script and checks hashes.')
        for media in ('application/x-blender','text/x-python','application/json'):
            if sum(i.get('media_type')==media for i in a.get('inputs',[]) if isinstance(i,dict))!=1:
                raise ValueError('Blender Python needs exactly one native scene, Python script and checks JSON.')
        if any('artifact' not in i or 'from_task' in i for i in a.get('inputs',[])):
            raise ValueError('Blender Python accepts only already registered inputs; prepare scripts in a separate stage before approval.')
    if e['capability'] in ('gemini.text','gemini.image'):
        if not isinstance(params['model'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}',params['model']):
            raise ValueError('Choose an exact Gemini model ID.')
        if type(params['max_output_tokens']) is not int or not 1<=params['max_output_tokens']<=4096:
            raise ValueError('API output token limit must be 1–4096.')
        if e['capability']=='gemini.image':
            if params['aspect_ratio'] not in ('1:1','16:9','9:16'):raise ValueError('Unsupported image aspect ratio.')
            if sum(i.get('media_type','').startswith('image/') for i in a.get('inputs',[]))>6:
                raise ValueError('Choose at most six image references.')
    if a.get('review_of'):raise ValueError('Registered operations cannot impersonate an independent agent reviewer.')
    if e['capability']=='pptx.create':
        if sum(i.get('media_type')=='application/json' for i in a.get('inputs',[]) if isinstance(i,dict))!=1:
            raise ValueError('PPTX creation requires exactly one JSON slide specification.')
        if any(not isinstance(o,dict) or not str(o.get('path','')).endswith('.pptx') for o in a.get('outputs',[])):
            raise ValueError('PPTX creation requires a .pptx output path.')
    if a.setdefault('tools',[])!=[]:raise ValueError('Registered operations have no agent tools.')
    if a.get('criteria')!=spec['criteria']:raise ValueError('Use the registered operation criteria; semantic review is a separate agent step.')
    if not isinstance(a.get('inputs'),list) or not spec.get('min_inputs',1)<=len(a['inputs'])<=spec['max_inputs']:raise ValueError('Invalid registered-operation input count.')
    if any(not isinstance(i,dict) or i.get('media_type') not in spec['input_types'] for i in a['inputs']):raise ValueError('Registered input media types do not match the selected operation.')
    if spec['kind']=='host':
        if any(i.get('path','').split('/')[0]=='delivery' for i in a['inputs']):
            raise ValueError('Host inputs must stay outside the reserved delivery directory.')
        outputs=a.get('outputs')
        if (not isinstance(outputs,list) or len(outputs)!=len(spec['outputs'])
                or any(not isinstance(o,dict) for o in outputs)
                or {o.get('path'):o.get('media_type') for o in outputs}!=spec['outputs']):
            raise ValueError('Use the exact registered host output paths and media types.')
        if e['capability']=='rhino.inspect' and sum(i['media_type']=='application/vnd.rhino' for i in a['inputs'])!=1:
            raise ValueError('Select exactly one Rhino model version for inspection')
        if e['capability']=='blender.inspect' and sum(i['media_type']=='application/x-blender' for i in a['inputs'])!=1:
            raise ValueError('Select exactly one Blender scene version for inspection.')
        if e['capability'] in ('blender.scene','blender.mesh_scene') and sum(i['media_type']=='application/json' for i in a['inputs'])!=1:
            raise ValueError('Blender scene needs exactly one application/json scene input; context inputs are text/plain.')
    elif not isinstance(a.get('outputs'),list) or len(a['outputs'])!=1 or not isinstance(a['outputs'][0],dict) or a['outputs'][0].get('media_type')!=spec['output_type']:
        raise ValueError('Registered operation needs one output with its declared media type.')
    limits=a.setdefault('limits',{})
    for key,maximum in [('seconds',spec['seconds']),('output_bytes',spec['output_bytes']),('tool_calls',1)]:
        limits.setdefault(key,maximum)
        if type(limits[key]) is not int or not 1<=limits[key]<=maximum:raise ValueError('Registered operation exceeds its '+key+' limit.')
    correction=a.get('review_correction')
    if correction is not None:
        if (not spec.get('review_correction') or spec['kind']!='procedure' or spec['external_requests']!=0
                or not isinstance(correction,dict) or set(correction)!={'producer'}):
            raise ValueError('Correction requires a supported local data-only operation.')
        from .contracts import label
        label(correction['producer'])
        if a.setdefault('max_attempts',2)!=2:raise ValueError('Local document correction permits two operation attempts.')
    elif a.setdefault('max_attempts',1)!=1:raise ValueError('Registered operations permit one attempt; uncertain calls are never replayed.')
    return spec


def available(a):
    spec=validate(copy.deepcopy(a))
    if a['execution']['capability']=='images.collect' and importlib.util.find_spec('PIL') is None:
        raise ValueError('Image collection requires the bundled Pillow image validator.')
    if a['execution']['capability']=='pptx.create':
        from .pptx_document import available as pptx_available
        pptx_available()
    if (a['execution']['capability'] in IMAGE_PROVIDERS or a['execution']['capability'] in CLOUD_MEDIA and a['execution']['capability'].endswith('.image')) and importlib.util.find_spec('PIL') is None:
        raise ValueError('Image conversion dependency is missing; no provider request was sent. Install task-relay[images] or update the desktop app.')
    if spec['kind']=='host':
        from task_relay.host_apps import blender,rhino
        app=rhino() if a['execution']['capability'].startswith('rhino.') else blender()
        if not app['available']:raise ValueError(app['blocker'])
        if a['execution']['capability']=='blender.animate':
            from task_relay.host_apps import video_tools
            if not video_tools()['available']:raise ValueError('Animation needs installed ffmpeg and ffprobe executables')
    if spec['kind']=='api':
        from task_relay import gemini, api_providers
        name=a['execution']['capability'].split('.')[0]
        from task_relay import cloud_providers
        config=(cloud_providers.read_config(name) if name in cloud_providers.PROVIDERS else
                api_providers.read_config(name) if name in api_providers.SPECS else gemini.read_config())
        if not config:raise ValueError(name+' capability is unavailable: provider configuration is missing.')
