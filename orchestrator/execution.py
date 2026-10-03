"""Versioned graph capabilities. Plans choose registered operations, never commands."""
import copy
import importlib.util
import re
from .media_adapters import PROVIDERS as IMAGE_PROVIDERS
from .cloud_media import SPECS as CLOUD_MEDIA
from .native_apps import profile as native_profile

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

REGISTRY['web.sources'] = {
    'version': 1, 'kind': 'api', 'input_types': [], 'min_inputs': 0,
    'output_type': 'application/json', 'outputs': {'delivery/source-pack.json': 'application/json'},
    'max_inputs': 0, 'input_bytes': 0, 'seconds': 1800, 'output_bytes': 2000000,
    'criteria': ['The exact literal queries, grounded search candidates, fetched public page versions and failures are recorded; no source candidate is asserted as a verified fact.'],
    'parameters': {'queries': '1–20 distinct literal public search queries',
                   'domains': '0–8 exact allowed public domains; empty permits any public domain',
                   'model': 'Exact configured Gemini text model'},
    'external_requests': 60,
    'cancellation': 'Stop after the current request; an uncertain search submission is never replayed.',
    'permissions': 'Public Google-grounded search and bounded HTTPS page reads; no login, JavaScript or private network.'}

from .reel_contract import OUTPUTS as REEL_OUTPUTS
from .hyperframes_contract import PREVIEW_OUTPUTS,RENDER_OUTPUTS,ASSET_TYPES
REGISTRY['hyperframes.preview']={
    'version':1,'kind':'procedure','review_correction':'application/json',
    'input_types':list(dict.fromkeys([*TEXT_TYPES,'application/json',*ASSET_TYPES])),
    'output_type':None,'outputs':PREVIEW_OUTPUTS,'max_inputs':100,'input_bytes':50000000,
    'seconds':600,'output_bytes':50000000,'parameters':{},'external_requests':0,
    'criteria':['The exact authored HyperFrames project passed local check, produced the declared full-size preview samples and a hash-bound editable bundle; source inputs are unchanged. Technical checks do not establish visual/editorial quality or user acceptance.'],
    'permissions':'Author-supplied front-end HTML/CSS/JavaScript runs in local Chromium. Fixed installed HyperFrames commands, scoped filesystem reads/writes, clean environment, external network denied; local sockets/loopback remain available. No Node programs, shell commands, downloads or package installation.',
    'cancellation':'Stop owned processes and retain evidence; confirmed failures may use an explicitly planned bounded source-correction loop. Never replay uncertain execution.'}
REGISTRY['hyperframes.render']={
    'version':1,'kind':'procedure','input_types':[*TEXT_TYPES,'application/json','application/zip'],
    'output_type':None,'outputs':RENDER_OUTPUTS,'max_inputs':20,'input_bytes':50000000,
    'seconds':1200,'output_bytes':50000000,'requires_registered_inputs':True,
    'parameters':{'project_sha256':'Exact selected preview project.zip SHA-256','preview_sha256':'Exact passed preview verification.json SHA-256'},
    'external_requests':0,
    'criteria':['The exact selected preview project was rechecked and rendered to H.264 with matching dimensions, FPS, frame count, duration and audio presence; source bundle and inputs are unchanged. Rendered samples require independent review and human visual selection.'],
    'permissions':'Same scoped local front-end execution as hyperframes.preview; exact registered project/preview hashes, no source regeneration.',
    'cancellation':'Stop owned processes; preserve partial files and receipts; no automatic replay.'}

REGISTRY['media.compose'] = {
    'version':1,'kind':'procedure','input_types':[*TEXT_TYPES,'application/json','image/png','image/jpeg','audio/mpeg','audio/wav'],
    'output_type':None,'outputs':REEL_OUTPUTS,'max_inputs':50,'input_bytes':50000000,
    'seconds':1200,'output_bytes':100000000,'parameters':{},'external_requests':0,
    'criteria':['The bounded scene specification produced an H.264 reel with matching dimensions, FPS, frame count, duration and audio presence, scene samples and an editable project; source inputs are unchanged. Technical checks do not establish visual/editorial quality or user acceptance.'],
    'permissions':'Fixed local HyperFrames/Chromium/FFmpeg commands with a clean environment and external network denied; loopback is permitted. Normal host file permissions; no arbitrary agent shell, HTML, JavaScript, downloads or generated audio.',
    'cancellation':'Stop owned rendering processes; preserve partial files and receipts; no automatic replay.'}

REGISTRY['pptx.create'] = {
    'review_correction':'application/json',
    'version':1, 'kind':'procedure',
    'input_types':[*TEXT_TYPES,'application/json','image/png','image/jpeg','application/zip'],
    'output_type':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'max_inputs':50, 'input_bytes':50000000, 'seconds':120, 'output_bytes':50000000,
    'criteria':['The bounded slide specification produced a PPTX that reopened with matching editable text, tables, chart data and embedded images; visual layout and Keynote import require separate review.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Terminate the local process; preserve partial results and never automatically replay.'}

REGISTRY['pptx.edit'] = {
    'review_correction':'application/json', 'version':1, 'kind':'procedure',
    'input_types':['application/json','application/vnd.openxmlformats-officedocument.presentationml.presentation','image/png','image/jpeg'],
    'output_type':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'min_inputs':2, 'max_inputs':20, 'input_bytes':51000000, 'seconds':120, 'output_bytes':50000000,
    'criteria':['The exact baseline PPTX and guarded manifest produced a new editable PPTX; every untargeted package part retained its bytes and edited text or pictures reopened correctly. Visual fit requires separate review.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Terminate the local process; preserve the baseline and partial evidence; never automatically replay.'}

REGISTRY['images.collect'] = {
    'version':1,'kind':'procedure','input_types':list(TEXT_TYPES),'output_type':'application/zip',
    'min_inputs':0,'max_inputs':20,'input_bytes':120000,'seconds':600,'output_bytes':45000000,
    'criteria':['At least one usable photo is collected. Each requested subject has a found or missing receipt; downloaded JPEG/PNG candidates retain source, author, licence and byte hashes. Metadata matches are not visual identification.'],
    'parameters':{'subjects':'1–40 {id,label,query} objects; literal public subject names; optional identity and exclude_titles'},
    'external_requests':320,
    'permissions':'Public read-only Wikimedia Commons search and image downloads; no credentials, paid model, generation or arbitrary URLs.',
    'cancellation':'Stop local downloads; retain receipts; no automatic replay.'}

REGISTRY['images.fetch'] = {
    'version':1,'kind':'procedure','input_types':['application/json'],'output_type':'application/zip',
    'min_inputs':1,'max_inputs':1,'input_bytes':512000,'seconds':600,'output_bytes':45000000,
    'criteria':['At least one observed source image was downloaded and validated. Exact source URLs, image bytes, hashes and gaps are retained. Subject identity and reuse rights require independent review.'],
    'parameters':{},'external_requests':320,
    'permissions':'Public HTTPS GETs to observed image/publisher hosts, no credentials or cookies. Unknown author/licence remain explicitly unknown. No image generation.',
    'cancellation':'Stop downloads; retain evidence; no automatic replay.'}

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


REGISTRY['rhino3dm.create'] = {
    'version':1, 'kind':'procedure', 'input_types':[*TEXT_TYPES,'application/json'],
    'output_type':None, 'max_inputs':20, 'input_bytes':20000000, 'seconds':120, 'output_bytes':50000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/checks.json':'application/json',
               'delivery/execution.json':'application/json'},
    'criteria':['The bounded geometry specification produced a new .3dm, reopened with rhino3dm and checked for valid geometry, coordinates, topology, names, layers, colors, units and tolerance; source inputs are unchanged. These are library checks, not native Rhino or visual/source-fidelity verification.'],
    'parameters':{}, 'external_requests':0,
    'permissions':'Fixed local rhino3dm library code and bounded geometry JSON only. No user scripts, native app launch, plugins, rendering or network requests.',
    'cancellation':'Stop the local operation; preserve partial files and receipts; never automatically replay or fall back to Rhino.'}

REGISTRY['rhino.startup'] = {
    'version':1, 'kind':'host', 'input_types':list(TEXT_TYPES), 'output_type':None,
    'max_inputs':20, 'input_bytes':2000000, 'seconds':120, 'output_bytes':200000,
    'outputs':{'delivery/execution.json':'application/json'},
    'criteria':['The selected Rhino 7/8 runtime has an identity-bound interpreter result and transport evidence.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Stop the owned process or shared-session client only; never kill an existing Rhino. A shared script may continue; no automatic retry.',
    'permissions':'Fixed startup script with normal host permissions; macOS Rhino 7/8 desktop session required. No Grasshopper.'}

REGISTRY['rhino3dm.run_python'] = {
    'version':1,'kind':'host','execution_mode':'standalone_library',
    'input_types':[*TEXT_TYPES,'application/vnd.rhino','text/x-python','application/json','application/octet-stream','image/png','image/jpeg'],
    'output_type':None,'max_inputs':50,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/model.py':'text/plain',
               'delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved standalone Python used the installed rhino3dm API to create/edit a File3dm; the candidate reopened in a separate Python process with the approved archive version, valid geometry, declared preservation checks and unchanged input copies. Library checks do not establish native Rhino, visual or source-fidelity verification.'],
    'parameters':{'scene_sha256':'Exact primary source .3dm SHA-256 or null for create','script_sha256':'Exact reviewed Python SHA-256',
                  'checks_sha256':'Exact reviewed library checks SHA-256, including target file version','permissions':'unrestricted_host'},
    'requires_registered_inputs':True,'external_requests':None,
    'permissions':'Exact-script approval for standalone CPython and the full pinned rhino3dm Python API. Normal filesystem/network permissions, not OS isolation. The runner never launches Rhino; scripts must stay within their approved scope.',
    'cancellation':'Stop the supervised local process tree; preserve receipts and partial files. Uncertain script outcomes require reconciliation. Never automatically replay or switch to native Rhino.'}
REGISTRY['rhino.inspect'] = {
    **copy.deepcopy(REGISTRY['rhino.startup']), 'input_types':[*TEXT_TYPES,'application/vnd.rhino'],
    'input_bytes':100000000, 'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact selected .3dm has a complete bounded geometry/document inventory and unchanged source-copy hash.'],
    'permissions':'Fixed native .3dm inspection in an owned process or a separate document in connected Rhino 8. Native dependencies/plugins use normal host permissions; not filesystem isolation. No Grasshopper.'}
REGISTRY['rhino.inspect']['review_evidence'] = True

REGISTRY['rhino.run_python'] = {
    'version':1, 'kind':'host', 'input_types':[*TEXT_TYPES,'application/vnd.rhino','text/x-python','application/json'],
    'output_type':None, 'max_inputs':20, 'input_bytes':100000000, 'seconds':600, 'output_bytes':100000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/preview.png':'image/png',
               'delivery/model.py':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved Rhino Python created/edited an assigned document; the saved candidate reopened in a fresh headless document, passed declared geometry/preservation checks and produced a viewport preview; input copies remain unchanged.'],
    'parameters':{'scene_sha256':'Selected .3dm SHA-256, or null for a new model',
                  'script_sha256':'Exact reviewed source SHA-256 for the selected Rhino interpreter', 'checks_sha256':'Exact Rhino checks JSON SHA-256',
                  'permissions':'unrestricted_host'}, 'external_requests':None,
    'cancellation':'Stop the owned process or shared-session client only; never kill an existing Rhino. A shared script may continue; retain its pending receipt and never replay. Script side effects cannot be undone.',
    'permissions':'Exact-script approval required for IronPython 2.7 (Rhino 7) or CPython 3 (Rhino 8)/RhinoCommon with normal host filesystem/network access. No OS isolation. Grasshopper authoring requires the separate rhino.grasshopper operation.'}

REGISTRY['rhino.render'] = {
    'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/vnd.rhino','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':10000000,
    'outputs':{'delivery/render.png':'image/png','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected model rendered through built-in Rhino Render from the exact named-view/resolution manifest; PNG dimensions and source-copy preservation were checked.'],
    'parameters':{'manifest_sha256':'Exact registered render manifest SHA-256'},'external_requests':0,
    'cancellation':'Stop the owned process or shared-session client only; never kill an existing Rhino. Retain partial files and pending receipts; no automatic replay.',
    'permissions':'Fixed host rendering with model materials/lighting and normal OS permissions. No arbitrary script, third-party renderer or model save; Grasshopper is outside this operation.'}

REGISTRY['rhino.grasshopper'] = {
    'version':1, 'kind':'host', 'input_types':[*TEXT_TYPES,'text/x-python','application/json','application/octet-stream'],
    'output_type':None, 'max_inputs':20, 'input_bytes':100000000, 'seconds':600, 'output_bytes':100000000,
    'outputs':{'delivery/candidate.gh':'application/vnd.grasshopper','delivery/candidate.ghx':'application/vnd.grasshopper',
               'delivery/definition.py':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved interpreter-specific Rhino 7/8 Python authored a new Grasshopper definition; official SaveQuiet wrote .gh and .ghx, both independently reopened and solved with preserved graph identities/wires, no runtime errors and exact declared output counts. Inputs remain unchanged; candidates await independent review and selection.'],
    'parameters':{'scene_sha256':'null; new definitions only','script_sha256':'Exact reviewed authoring Python SHA-256',
                  'checks_sha256':'Exact reviewed Grasshopper checks SHA-256','permissions':'unrestricted_host'},
    'requires_registered_inputs':True, 'external_requests':None,
    'permissions':'Exact script/checks/input approval for Rhino 7 IronPython 2.7 or Rhino 8 CPython 3 and installed Grasshopper/GhPython APIs, including embedded code during build and verification solves. Normal host filesystem/network permissions, not isolation. No edits to existing definitions, baking or UI control.',
    'cancellation':REGISTRY['rhino.run_python']['cancellation']}


REGISTRY['sketchup.startup'] = {
    'version':1,'kind':'host','input_types':list(TEXT_TYPES),'output_type':None,
    'max_inputs':20,'input_bytes':2000000,'seconds':120,'output_bytes':200000,
    'outputs':{'delivery/execution.json':'application/json'},'parameters':{},'external_requests':0,
    'criteria':['The owned SketchUp process has a matching embedded Ruby startup receipt; failure remains diagnostic evidence.'],
    'cancellation':'Stop only the owned process; no automatic replay.',
    'permissions':'macOS desktop SketchUp 2025/2026 with normal host permissions; no attachment to existing user sessions.'}
REGISTRY['sketchup.inspect'] = {
    **copy.deepcopy(REGISTRY['sketchup.startup']),
    'input_types':[*TEXT_TYPES,'application/vnd.sketchup.skp'],'input_bytes':100000000,'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected .skp has a bounded native inventory and unchanged source-copy hash.'],
    'review_evidence':True}
REGISTRY['sketchup.run_ruby'] = {
    'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/vnd.sketchup.skp','text/x-ruby','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.skp':'application/vnd.sketchup.skp','delivery/preview.png':'image/png',
               'delivery/model.rb':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'parameters':{'scene_sha256':'Selected .skp SHA-256 or null for create','script_sha256':'Exact reviewed UTF-8 Ruby SHA-256',
                  'checks_sha256':'Exact SketchUp v1 checks SHA-256','permissions':'unrestricted_host'},
    'criteria':['The exact approved Ruby created/edited a candidate, saved it and reopened it in an independent owned process; declared dimensions/preservation and viewport evidence passed; input copies remain unchanged.'],
    'external_requests':None,'requires_registered_inputs':True,
    'permissions':'Exact Ruby/script/checks host approval. Normal filesystem/network access, not an OS sandbox. Desktop session and license required.',
    'cancellation':'Stop only owned work; preserve partial outputs. Script side effects cannot be undone. Never automatically replay.'}

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
        if entry['id']=='web.sources':
            entry.update(available=bool(config and config.get('models',{}).get('text')),
                         configured_model=(config or {}).get('models',{}).get('text'),
                         availability_evidence='Configured Gemini text model and public page reader; live search and source coverage are checked during execution.')
        if entry['id']=='rhino3dm.run_python':
            from .rhino3dm_script import discover
            from .rhino3dm_script_contract import DESCRIPTION
            app=discover()
            entry.update(available=app['available'],availability_evidence=app['evidence'],blocker=app['blocker'],
                library_version=app['version'],interpreter=app['interpreter'],checks_schema=DESCRIPTION)
        if entry['id']=='rhino3dm.create':
            from . import rhino3dm_document, rhino3dm_contract
            entry['geometry_schema']=rhino3dm_contract.DESCRIPTION
            entry['execution_mode']='standalone_library'
            try:rhino3dm_document.available()
            except ValueError as exc:entry.update(available=False,availability_evidence=str(exc),blocker=str(exc))
            else:entry['availability_evidence']='Pinned rhino3dm library available; no Rhino installation or native verification required or implied.'
        if entry['id'].startswith('sketchup.'):
            app=native_profile(entry['id']).discover()
            entry.update(available=app['available'],availability_evidence=app['evidence'],blocker=app['blocker'],
                         application_version=app['version'],interpreter=app['interpreter'])
            if entry['id']=='sketchup.run_ruby':
                from .sketchup_contract import DESCRIPTION
                entry['checks_schema']=copy.deepcopy(DESCRIPTION)
        if entry['id']=='images.collect':
            from .image_sources import DESCRIPTION
            entry['image_source_schema']=DESCRIPTION
            entry.update(available=importlib.util.find_spec('PIL') is not None,
                         availability_evidence='Public Commons adapter and local image validation; live coverage varies by subject.')
        if entry['id']=='images.fetch':
            from .browser_images import DESCRIPTION
            entry['image_source_schema']=DESCRIPTION
            entry.update(available=importlib.util.find_spec('PIL') is not None,
                         availability_evidence='Observed browser image references and public downloads; browser discovery requires a configured browser worker.')
        if entry['id'] in CLOUD_MEDIA:
            from task_relay.cloud_providers import read_config
            provider,kind=entry['id'].split('.')
            selected=read_config(provider)
            entry.update(available=bool(selected), configured_model=(selected or {}).get('models',{}).get(kind),
                         availability_evidence='Saved API credential and implemented model adapter; generation access and credits are unverified.')
            entry['available']=entry['available'] and bool(entry['configured_model'])
        if entry['id'].startswith('hyperframes.'):
            from . import hyperframes_project,hyperframes_contract
            entry['project_schema']=hyperframes_contract.DESCRIPTION
            try:hyperframes_project.available()
            except (ValueError,ImportError) as exc:entry.update(available=False,availability_evidence=str(exc),blocker=str(exc))
            else:entry['availability_evidence']='Local authored-project check, snapshots and render are qualified; provider authorship and visual quality require independent review.'
        if entry['id']=='media.compose':
            from . import reel_document,reel_contract
            entry['composition_schema']=reel_contract.DESCRIPTION
            try:reel_document.available()
            except ValueError as exc:entry.update(available=False,availability_evidence=str(exc),blocker=str(exc))
            else:entry['availability_evidence']='Configured local HyperFrames runtime passed the recorded fixture qualification; each reel still requires independent review and visual selection.'
        if entry['id']=='pptx.create':
            from . import pptx_document
            entry['slide_schema']=pptx_document.DESCRIPTION
            try:pptx_document.available()
            except ValueError as exc:entry.update(available=False,availability_evidence=str(exc))
            else:entry['availability_evidence']='Local python-pptx dependency available; native-app import and visual quality are not qualified.'
        if entry['id']=='pptx.edit':
            from . import pptx_edit
            entry['edit_schema']=pptx_edit.DESCRIPTION
            try:pptx_edit.available()
            except ValueError as exc:entry.update(available=False,availability_evidence=str(exc),blocker=str(exc))
            else:entry['availability_evidence']='Local OOXML package editor available; visual fit and native-app import require review.'
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
            if entry['id']=='rhino3dm.run_python':continue
            if entry['id'].startswith('sketchup.'):continue
            if entry['id'].startswith('rhino.'):
                rhino_app=native_profile(entry['id']).discover()
                entry.update(available=rhino_app['available'],availability_evidence=rhino_app['evidence'])
                if entry['id']=='rhino.grasshopper':
                    from .grasshopper_contract import DESCRIPTION
                    entry['checks_schema']=DESCRIPTION
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
    if not isinstance(params,dict) or set(params)!=set(spec['parameters']):
        expected=set(spec['parameters']);actual=set(params) if isinstance(params,dict) else set()
        issues=[]
        if expected-actual:issues.append('missing '+', '.join(sorted(expected-actual)))
        if actual-expected:issues.append('unsupported '+', '.join(sorted(actual-expected)))
        if not isinstance(params,dict):issues.append('expected an object')
        raise ValueError('Invalid registered-operation parameters for '+e['capability']+': '+'; '.join(issues)+'.')
    if e['capability']=='images.collect':
        from .image_sources import validate_subjects
        validate_subjects(params['subjects'])
        if any(not str(o.get('path','')).endswith('.zip') for o in a.get('outputs',[])):
            raise ValueError('Image collection requires a .zip output.')
    if e['capability']=='web.sources':
        from .web_sources import validate as validate_queries
        validate_queries(params['queries'], params['domains'])
        if not isinstance(params['model'],str) or not params['model'].strip():
            raise ValueError('Web source collection requires an exact text model.')
    if e['capability']=='images.fetch' and any(not o['path'].endswith('.zip') for o in a.get('outputs',[])):
        raise ValueError('Image fetching requires a .zip output.')
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
    if e['capability']=='sketchup.run_ruby':
        if params['permissions']!='unrestricted_host':raise ValueError('SketchUp Ruby requires unrestricted_host')
        for key in ('scene_sha256','script_sha256','checks_sha256'):
            if key=='scene_sha256' and params[key] is None:continue
            if not isinstance(params[key],str) or not re.fullmatch('[a-f0-9]{64}',params[key]):raise ValueError('SketchUp requires exact input hashes')
        for media,count in (('application/vnd.sketchup.skp',int(params['scene_sha256'] is not None)),('text/x-ruby',1),('application/json',1)):
            if sum(i.get('media_type')==media for i in a.get('inputs',[]))!=count:raise ValueError('SketchUp needs exact Ruby/checks and a model only for edits')
        if any('artifact' not in i or 'from_task' in i for i in a.get('inputs',[])):raise ValueError('SketchUp accepts only already registered inputs')
    if e['capability']=='rhino.grasshopper' and params['scene_sha256'] is not None:
        raise ValueError('Grasshopper supports new definitions only; scene_sha256 must be null')
    if e['capability'] in ('rhino.run_python','rhino3dm.run_python','rhino.grasshopper'):
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
    if e['capability']=='pptx.edit':
        types=[i.get('media_type') for i in a.get('inputs',[]) if isinstance(i,dict)]
        if types.count('application/json')!=1 or types.count('application/vnd.openxmlformats-officedocument.presentationml.presentation')!=1 or any(t not in REGISTRY['pptx.edit']['input_types'] for t in types):
            raise ValueError('PPTX edit requires one baseline PPTX, one JSON edit manifest and optional declared PNG/JPEG pictures.')
        if any(not isinstance(o,dict) or not str(o.get('path','')).endswith('.pptx') for o in a.get('outputs',[])):
            raise ValueError('PPTX edit requires a .pptx output path.')
    if a.setdefault('tools',[])!=[]:raise ValueError('Registered operations have no agent tools.')
    if a.get('criteria')!=spec['criteria']:raise ValueError('Use the registered operation criteria; semantic review is a separate agent step.')
    if not isinstance(a.get('inputs'),list) or not spec.get('min_inputs',1)<=len(a['inputs'])<=spec['max_inputs']:raise ValueError('Invalid registered-operation input count.')
    if any(not isinstance(i,dict) or i.get('media_type') not in spec['input_types'] for i in a['inputs']):raise ValueError('Registered input media types do not match the selected operation.')
    if e['capability'] in ('hyperframes.preview','hyperframes.render'):
        if sum(i.get('media_type')=='application/json' for i in a['inputs'])!=1:
            raise ValueError('HyperFrames needs exactly one project JSON or preview receipt')
        if e['capability']=='hyperframes.render':
            if sum(i.get('media_type')=='application/zip' for i in a['inputs'])!=1 or any('artifact' not in i or 'from_task' in i for i in a['inputs']):
                raise ValueError('Render requires already registered preview project and receipt; select the preview before the render stage')
            if any(not isinstance(params[k],str) or not re.fullmatch('[a-f0-9]{64}',params[k]) for k in ('project_sha256','preview_sha256')):
                raise ValueError('Render requires exact project and preview SHA-256 values')
    if e['capability']=='media.compose':
        if sum(i.get('media_type')=='application/json' for i in a['inputs'])!=1:
            raise ValueError('Reel composition requires exactly one JSON scene specification')
    if e['capability']=='rhino3dm.create':
        if sum(i.get('media_type')=='application/json' for i in a['inputs'])!=1:
            raise ValueError('Standalone 3DM creation needs exactly one geometry JSON specification')
    if spec.get('outputs'):
        if any(i.get('path','').split('/')[0]=='delivery' for i in a['inputs']):
            raise ValueError('Operation inputs must stay outside the reserved delivery directory.')
        outputs=a.get('outputs')
        if (not isinstance(outputs,list) or len(outputs)!=len(spec['outputs'])
                or any(not isinstance(o,dict) for o in outputs)
                or {o.get('path'):o.get('media_type') for o in outputs}!=spec['outputs']):
            raise ValueError('Use the exact registered '+('host ' if spec['kind']=='host' else '')+'output paths and media types.')
        if e['capability']=='rhino.inspect' and sum(i['media_type']=='application/vnd.rhino' for i in a['inputs'])!=1:
            raise ValueError('Select exactly one Rhino model version for inspection')
        if e['capability']=='blender.inspect' and sum(i['media_type']=='application/x-blender' for i in a['inputs'])!=1:
            raise ValueError('Select exactly one Blender scene version for inspection.')
        if e['capability']=='sketchup.inspect' and sum(i['media_type']=='application/vnd.sketchup.skp' for i in a['inputs'])!=1:
            raise ValueError('Select exactly one SketchUp model version for inspection.')
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
    if a['execution']['capability']=='web.sources':
        from task_relay import gemini
        config=gemini.read_config()
        if not config or config.get('models',{}).get('text')!=a['execution']['parameters']['model']:
            raise ValueError('The configured Gemini text model for web.sources is unavailable or changed.')
    if a['execution']['capability'].startswith('hyperframes.'):
        from .hyperframes_project import available as project_available
        project_available()
    if a['execution']['capability']=='media.compose':
        from .reel_document import available as reel_available
        reel_available()
    if a['execution']['capability']=='rhino3dm.create':
        from .rhino3dm_document import available as library_available
        library_available()
    if a['execution']['capability'] in ('images.collect','images.fetch') and importlib.util.find_spec('PIL') is None:
        raise ValueError('Image collection requires the bundled Pillow image validator.')
    if a['execution']['capability']=='pptx.create':
        from .pptx_document import available as pptx_available
        pptx_available()
    if a['execution']['capability']=='pptx.edit':
        from .pptx_edit import available as pptx_edit_available
        pptx_edit_available()
    if (a['execution']['capability'] in IMAGE_PROVIDERS or a['execution']['capability'] in CLOUD_MEDIA and a['execution']['capability'].endswith('.image')) and importlib.util.find_spec('PIL') is None:
        raise ValueError('Image conversion dependency is missing; no provider request was sent. Install task-relay[images] or update the desktop app.')
    if spec['kind']=='host':
        app=native_profile(a['execution']['capability']).discover()
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
