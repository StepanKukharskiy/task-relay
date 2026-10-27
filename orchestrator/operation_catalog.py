"""Read-only catalog descriptions supplied by built-in adapters."""
import copy
import importlib.util
from .media_adapters import PROVIDERS as IMAGE_PROVIDERS
from .native_apps import profile as native_profile

def configuration(context):
    from task_relay import gemini
    if 'gemini' not in context:context['gemini']=gemini.read_config()
    return context['gemini']

def gemini_model(entry, context):
    from task_relay import gemini
    config=configuration(context);kind=entry['id'].split('.')[1]
    entry.update(available=bool(config),configured_model=config.get('models',{}).get(kind,gemini.DEFAULT_MODELS[kind]) if config else None)

def search(entry, context):
    from task_relay import api_providers
    config=configuration(context)
    entry.update(available=bool(config and config.get('models', {}).get('text')), configured_model=(config or {}).get('models', {}).get('text'), availability_evidence='Configured Gemini text model and public page reader; live search and source coverage are checked during execution.')

def prepared(entry, context):
    entry['query_schema'] = {'version': 1, 'targets': [{'id': 'observed-item-id', 'queries': ['specific US item search'], 'required_options': 3}]}

def rendered(entry, context):
    if entry.get('browser_transport')=='native':
        try:
            from task_relay.source_native_browser import discover
            binding=discover()
            entry.update(available=True,browser_transport=binding['transport'],availability_evidence='Verified native helper present; foreground and permissions are checked before execution. Page access and visible-text coverage require actual reads.')
        except (OSError,ValueError,RuntimeError) as exc:
            entry.update(available=False,availability_evidence=str(exc))
        return
    try:
        from task_relay.host import HOST
        from task_relay.relay_paths import PATHS
        HOST.browser_python(PATHS.install, PATHS.data)
        entry.update(available=True, availability_evidence='Optional browser runtime executable present; renderer availability is checked during execution.')
    except RuntimeError as exc:
        entry.update(available=False, availability_evidence=str(exc))

def rhino_library_script(entry, context):
    from .rhino3dm_script import discover
    from .rhino3dm_script_contract import DESCRIPTION
    app = discover()
    entry.update(available=app['available'], availability_evidence=app['evidence'], blocker=app['blocker'], library_version=app['version'], interpreter=app['interpreter'], checks_schema=DESCRIPTION)

def rhino_library(entry, context):
    from . import rhino3dm_document, rhino3dm_contract
    entry['geometry_schema'] = rhino3dm_contract.DESCRIPTION
    entry['execution_mode'] = 'standalone_library'
    try:
        rhino3dm_document.available()
    except ValueError as exc:
        entry.update(available=False, availability_evidence=str(exc), blocker=str(exc))
    else:
        entry['availability_evidence'] = 'Pinned rhino3dm library available; no Rhino installation or native verification required or implied.'

def sketchup(entry, context):
    app = native_profile(entry['id']).discover()
    entry.update(available=app['available'], availability_evidence=app['evidence'], blocker=app['blocker'], application_version=app['version'], interpreter=app['interpreter'])
    if entry['id'] == 'sketchup.run_ruby':
        from .sketchup_contract import DESCRIPTION
        entry['checks_schema'] = copy.deepcopy(DESCRIPTION)

def photos(entry, context):
    from .image_sources import DESCRIPTION
    entry['image_source_schema'] = DESCRIPTION
    entry.update(available=importlib.util.find_spec('PIL') is not None, availability_evidence='Public Commons adapter and local image validation; live coverage varies by subject.')

def merge_photos(entry, context):
    entry['image_source_schema'] = 'Inputs are ordered application/zip bundles: base first defines all subjects, followed by recovery ZIPs. Preserve found base bytes; fill only gaps using matching subject id, label and query. Download/observation metadata stays verbatim. Output is one validated ZIP with source_bundle_sha256 provenance; independently review coverage and identity.'
    entry.update(available=importlib.util.find_spec('PIL') is not None, availability_evidence='Local hash-validated photo bundle composition; no network or model.')

def fetch_photos(entry, context):
    from .browser_images import DESCRIPTION
    entry['image_source_schema'] = DESCRIPTION
    entry.update(available=importlib.util.find_spec('PIL') is not None, availability_evidence='Observed browser image references and public downloads; browser discovery requires a configured browser worker.')

def catalog_photos(entry, context):
    entry['image_source_schema'] = 'Exact typed inventory/catalog/source-pack JSON; code uses saved product-page image metadata. Missing references remain gaps; optional browser discovery can fill only missing subjects. No image URL is supplied by a model.'
    entry.update(available=importlib.util.find_spec('PIL') is not None, availability_evidence='Observed product-page image extraction and bounded public photo downloads.')

def presentation_preview(entry, context):
    from task_relay.presentation_host import discover
    try:
        entry['presentation_runtime'] = discover()
    except ValueError as exc:
        entry.update(available=False, blocker=str(exc), availability_evidence=str(exc))
    else:
        entry['availability_evidence'] = 'Compatible renderer and PDF rasterizer discovered; actual opening/rendering requires execution.'

def cloud(entry, context):
    from task_relay.cloud_providers import read_config
    provider, kind = entry['id'].split('.')
    selected = read_config(provider)
    entry.update(available=bool(selected), configured_model=(selected or {}).get('models', {}).get(kind), availability_evidence='Saved API credential and implemented model adapter; generation access and credits are unverified.')
    entry['available'] = entry['available'] and bool(entry['configured_model'])

def hyperframes(entry, context):
    from . import hyperframes_project, hyperframes_contract
    entry['project_schema'] = hyperframes_contract.DESCRIPTION
    try:
        hyperframes_project.available()
    except (ValueError, ImportError) as exc:
        entry.update(available=False, availability_evidence=str(exc), blocker=str(exc))
    else:
        entry['availability_evidence'] = 'Local authored-project check, snapshots and render are qualified; provider authorship and visual quality require independent review.'

def compose(entry, context):
    from . import reel_document, reel_contract
    entry['composition_schema'] = reel_contract.DESCRIPTION
    try:
        reel_document.available()
    except ValueError as exc:
        entry.update(available=False, availability_evidence=str(exc), blocker=str(exc))
    else:
        entry['availability_evidence'] = 'Configured local HyperFrames runtime passed the recorded fixture qualification; each reel still requires independent review and visual selection.'

def presentation_create(entry, context):
    from . import pptx_document
    entry['slide_schema'] = pptx_document.DESCRIPTION
    try:
        pptx_document.available()
    except ValueError as exc:
        entry.update(available=False, availability_evidence=str(exc))
    else:
        entry['availability_evidence'] = 'Local python-pptx dependency available; native-app import and visual quality are not qualified.'

def presentation_edit(entry, context):
    from . import pptx_edit
    entry['edit_schema'] = pptx_edit.DESCRIPTION
    try:
        pptx_edit.available()
    except ValueError as exc:
        entry.update(available=False, availability_evidence=str(exc), blocker=str(exc))
    else:
        entry['availability_evidence'] = 'Local OOXML package editor available; visual fit and native-app import require review.'

def image_provider(entry, context):
    from task_relay import api_providers
    provider = IMAGE_PROVIDERS[entry['id']]
    selected = api_providers.read_config(provider)
    model = (selected or {}).get('models', {}).get('image')
    entry.update(available=bool(selected and model), configured_model=model, availability_evidence='Configured image model and credentials; account access unverified. Set the image default in /providers.')

def image_dependency(entry, context):
    if importlib.util.find_spec('PIL') is None:
        entry.update(available=False, availability_evidence='Image conversion dependency missing. Install task-relay[images] or use a rebuilt desktop app.')

def native(entry, context):
    from task_relay.host_apps import blender
    from .blender_host import SCENE_DESCRIPTION, MESH_DESCRIPTION
    app=blender()
    if entry['id'] == 'rhino3dm.run_python':
        return
    if entry['id'].startswith('sketchup.'):
        return
    if entry['id'].startswith('rhino.'):
        rhino_app = native_profile(entry['id']).discover()
        entry.update(available=rhino_app['available'], availability_evidence=rhino_app['evidence'])
        if entry['id'] == 'rhino.grasshopper':
            from .grasshopper_contract import DESCRIPTION
            entry['checks_schema'] = DESCRIPTION
        if entry['id'] == 'rhino.run_python':
            from .rhino_contract import DESCRIPTION
            entry['checks_schema'] = DESCRIPTION
        if entry['id'] == 'rhino.document':
            from .prepared_schemas import REGISTRY
            entry['document_schema'] = REGISTRY['rhino.document']['schema']
            entry['availability_evidence'] += '; fixed data-only box/polyline/text/dimension/named-view builder; actual execution is qualified separately'
        if entry['id'] == 'rhino.render':
            from .rhino_contract import RENDER_DESCRIPTION
            entry['render_schema'] = RENDER_DESCRIPTION
        entry['rhino_version'] = rhino_app.get('version')
        entry['interpreter'] = rhino_app.get('interpreter')
        return
    entry.update(available=app['available'], availability_evidence=app['evidence'])
    if entry['id'] == 'blender.scene':
        entry['scene_schema'] = SCENE_DESCRIPTION
    if entry['id'] == 'blender.mesh_scene':
        entry['scene_schema'] = MESH_DESCRIPTION
    if entry['id'] == 'blender.run_python':
        from .blender_edit import CHECKS_DESCRIPTION
        entry['checks_schema'] = CHECKS_DESCRIPTION
    if entry['id'] == 'blender.import_asset':
        from .blender_assets import DESCRIPTION
        entry['asset_schema'] = DESCRIPTION
    if entry['id'] == 'blender.animate':
        from .blender_animation import DESCRIPTION
        from task_relay.host_apps import video_tools
        entry['animation_schema'] = DESCRIPTION
        entry['available'] = app['available'] and video_tools()['available']
        entry['availability_evidence'] = 'Executable presence only; Blender, ffmpeg and ffprobe required.'
