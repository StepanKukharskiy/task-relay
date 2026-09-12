"""Versioned graph capabilities. Plans choose registered operations, never commands."""
import copy
import re

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

# Separate versioned capability preserves existing primitive-only plan contracts.
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


def catalog():
    from task_relay import gemini
    config=gemini.read_config()
    result = [dict(id=ident,**copy.deepcopy(spec),available=ident!='gemini.text' or bool(config),
        availability_evidence='Local implementation; provider configuration only, not authentication proof.',
        configured_model=(config.get('models',{}).get('text',gemini.DEFAULT_MODELS['text']) if config and ident=='gemini.text' else None))
        for ident,spec in REGISTRY.items()]
    from task_relay.host_apps import blender
    from .blender_host import SCENE_DESCRIPTION,MESH_DESCRIPTION
    app=blender()
    for entry in result:
        if entry['kind']=='host':
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
    if e['capability']=='gemini.text':
        if not isinstance(params['model'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}',params['model']):
            raise ValueError('Choose an exact Gemini model ID.')
        if type(params['max_output_tokens']) is not int or not 1<=params['max_output_tokens']<=4096:
            raise ValueError('API output token limit must be 1–4096.')
    if a.get('review_of'):raise ValueError('Registered operations cannot impersonate an independent agent reviewer.')
    if a.setdefault('tools',[])!=[]:raise ValueError('Registered operations have no agent tools.')
    if a.get('criteria')!=spec['criteria']:raise ValueError('Use the registered operation criteria; semantic review is a separate agent step.')
    if not isinstance(a.get('inputs'),list) or not 1<=len(a['inputs'])<=spec['max_inputs']:raise ValueError('Invalid registered-operation input count.')
    if any(not isinstance(i,dict) or i.get('media_type') not in spec['input_types'] for i in a['inputs']):raise ValueError('Registered input media types do not match the selected operation.')
    if spec['kind']=='host':
        if any(i.get('path','').split('/')[0]=='delivery' for i in a['inputs']):
            raise ValueError('Blender inputs must stay outside its reserved delivery directory.')
        outputs=a.get('outputs')
        if (not isinstance(outputs,list) or len(outputs)!=len(spec['outputs'])
                or any(not isinstance(o,dict) for o in outputs)
                or {o.get('path'):o.get('media_type') for o in outputs}!=spec['outputs']):
            raise ValueError('Use the exact registered Blender output paths and media types.')
        if e['capability']=='blender.inspect' and sum(i['media_type']=='application/x-blender' for i in a['inputs'])!=1:
            raise ValueError('Select exactly one Blender scene version for inspection.')
        if e['capability'] in ('blender.scene','blender.mesh_scene') and sum(i['media_type']=='application/json' for i in a['inputs'])!=1:
            raise ValueError('Blender scene needs exactly one application/json scene input; context inputs are text/plain.')
    elif not isinstance(a.get('outputs'),list) or len(a['outputs'])!=1 or not isinstance(a['outputs'][0],dict) or a['outputs'][0].get('media_type')!=spec['output_type']:
        raise ValueError('Registered operation needs one explicitly typed text output.')
    limits=a.setdefault('limits',{})
    for key,maximum in [('seconds',spec['seconds']),('output_bytes',spec['output_bytes']),('tool_calls',1)]:
        limits.setdefault(key,maximum)
        if type(limits[key]) is not int or not 1<=limits[key]<=maximum:raise ValueError('Registered operation exceeds its '+key+' limit.')
    if a.setdefault('max_attempts',1)!=1:raise ValueError('Registered operations permit one attempt; uncertain calls are never replayed.')
    return spec


def available(a):
    spec=validate(copy.deepcopy(a))
    if spec['kind']=='host':
        from task_relay.host_apps import blender
        app=blender()
        if not app['available']:raise ValueError(app['blocker'])
        if a['execution']['capability']=='blender.animate':
            from task_relay.host_apps import video_tools
            if not video_tools()['available']:raise ValueError('Animation needs installed ffmpeg and ffprobe executables')
    if spec['kind']=='api':
        from task_relay import gemini
        if not gemini.read_config():raise ValueError('Gemini text capability is unavailable: provider configuration is missing.')
