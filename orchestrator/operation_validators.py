"""Built-in adapter admission checks. No scheduling, grants or dispatch."""
import re

def image_subjects(a, spec):
    params = a['execution']['parameters']
    from .image_sources import validate_subjects
    validate_subjects(params['subjects'])
    if any((not str(o.get('path', '')).endswith('.zip') for o in a.get('outputs', []))):
        raise ValueError('Image collection requires a .zip output.')

def rendered_sources(a, spec):
    params = a['execution']['parameters']
    from .web_sources import validate as validate_queries
    validate_queries(['domain validation'], params['domains'])
    if spec.get('browser_transport')=='native':
        from task_relay.source_native_browser import TRANSPORT
        if params['browser']!=TRANSPORT or type(params['max_observations']) is not int or not 2<=params['max_observations']<=8:
            raise ValueError('Select an explicit native browser and 2–8 observations')
        if type(params['max_pages']) is not int or not 1<=params['max_pages']<=3:raise ValueError('Native read batch requires 1–3 pages')
        minimum=30+(50+25*params['max_observations'])*params['max_pages']
        if a.get('limits',{}).get('seconds',spec['seconds'])<minimum:raise ValueError('Native observation batch exceeds its action and cleanup allowance; split the batch')
        return
    if type(params['max_pages']) is not int or not 1 <= params['max_pages'] <= 12:
        raise ValueError('Rendered source reads need 1–12 observed candidates')
    if a.get('limits', {}).get('seconds', spec['seconds']) < 30 + 65 * params['max_pages']:
        raise ValueError('Rendered source batch exceeds its page-read and cleanup time allowance; split the batch')

def prepared_sources(a, spec):
    params = a['execution']['parameters']
    from .web_sources import validate as validate_queries
    validate_queries(['domain validation'], params['domains'])
    if not isinstance(params['model'], str) or not params['model'].strip():
        raise ValueError('Prepared source collection requires an exact text model.')
    if len(a.get('inputs', [])) != 1 or a['inputs'][0].get('media_type') != 'application/json':
        raise ValueError('Prepared source collection requires exactly one JSON query specification.')

def source_queries(a, spec):
    params = a['execution']['parameters']
    from .web_sources import validate as validate_queries
    validate_queries(params['queries'], params['domains'])
    if not isinstance(params['model'], str) or not params['model'].strip():
        raise ValueError('Web source collection requires an exact text model.')

def zip_output(a, spec):
    if any((not o['path'].endswith('.zip') for o in a.get('outputs', []))):
        raise ValueError('Image fetching requires a .zip output.')

def cloud_media(a, spec):
    e = a['execution']
    params = a['execution']['parameters']
    from .cloud_media import validate as validate_cloud, OUTPUTS
    validate_cloud(e['capability'], params, a.get('inputs', []))
    if any((not str(o.get('path', '')).endswith(OUTPUTS[e['capability'].split('.')[1]][1]) for o in a.get('outputs', []))):
        raise ValueError('Use the registered media output file extension.')

def openai_image(a, spec):
    params = a['execution']['parameters']
    if not isinstance(params['model'], str) or not re.fullmatch('gpt-image-[A-Za-z0-9._-]{1,100}', params['model']):
        raise ValueError('Choose an exact GPT Image model ID; text models cannot generate through the image adapter.')
    if params['size'] not in ('auto', '1024x1024', '1536x1024', '1024x1536') or params['quality'] not in ('auto', 'low', 'medium', 'high'):
        raise ValueError('Unsupported image size or quality.')
    if sum((i.get('media_type', '').startswith('image/') for i in a.get('inputs', []))) > 6:
        raise ValueError('Choose at most six image references.')

def openrouter_image(a, spec):
    params = a['execution']['parameters']
    from task_relay.api_providers import model_name
    model_name(params['model'])
    if '/' not in params['model'] or params['aspect_ratio'] not in ('1:1', '16:9', '9:16'):
        raise ValueError('Choose an exact OpenRouter image model slug and supported aspect ratio.')
    if sum((i.get('media_type', '').startswith('image/') for i in a.get('inputs', []))) > 6:
        raise ValueError('Choose at most six image references.')

def rhino_render(a, spec):
    params = a['execution']['parameters']
    if not isinstance(params['manifest_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', params['manifest_sha256']):
        raise ValueError('Rhino render requires an exact manifest hash')
    for media in ('application/vnd.rhino', 'application/json'):
        if sum((i.get('media_type') == media for i in a.get('inputs', []) if isinstance(i, dict))) != 1:
            raise ValueError('Rhino render needs exactly one model and manifest')
    if any(('artifact' not in i or 'from_task' in i for i in a.get('inputs', []))):
        raise ValueError('Rhino render requires already registered inputs')

def sketchup_script(a, spec):
    params = a['execution']['parameters']
    if params['permissions'] != 'unrestricted_host':
        raise ValueError('SketchUp Ruby requires unrestricted_host')
    for key in ('scene_sha256', 'script_sha256', 'checks_sha256'):
        if key == 'scene_sha256' and params[key] is None:
            continue
        if not isinstance(params[key], str) or not re.fullmatch('[a-f0-9]{64}', params[key]):
            raise ValueError('SketchUp requires exact input hashes')
    for media, count in (('application/vnd.sketchup.skp', int(params['scene_sha256'] is not None)), ('text/x-ruby', 1), ('application/json', 1)):
        if sum((i.get('media_type') == media for i in a.get('inputs', []))) != count:
            raise ValueError('SketchUp needs exact Ruby/checks and a model only for edits')
    if any(('artifact' not in i or 'from_task' in i for i in a.get('inputs', []))):
        raise ValueError('SketchUp accepts only already registered inputs')

def new_grasshopper(a, spec):
    params = a['execution']['parameters']
    if params['scene_sha256'] is not None:
        raise ValueError('Grasshopper supports new definitions only; scene_sha256 must be null')

def rhino_script(a, spec):
    params = a['execution']['parameters']
    if params['permissions'] != 'unrestricted_host':
        raise ValueError('Rhino Python requires unrestricted_host; no isolation is enforced')
    for key in ('scene_sha256', 'script_sha256', 'checks_sha256'):
        if key == 'scene_sha256' and params[key] is None:
            continue
        if not isinstance(params[key], str) or not re.fullmatch('[a-f0-9]{64}', params[key]):
            raise ValueError('Rhino Python requires exact input hashes')
    for media, count in (('application/vnd.rhino', int(params['scene_sha256'] is not None)), ('text/x-python', 1), ('application/json', 1)):
        if sum((i.get('media_type') == media for i in a.get('inputs', []) if isinstance(i, dict))) != count:
            raise ValueError('Rhino Python needs exact script/checks and a scene only for edits')
    if any(('artifact' not in i or 'from_task' in i for i in a.get('inputs', []))):
        raise ValueError('Rhino Python accepts only already registered inputs; prepare and review scripts in a separate stage')

def blender_animation(a, spec):
    params = a['execution']['parameters']
    for key in ('manifest_sha256','scene_sha256'):
        if key not in params:continue
        value=params[key]
        if not isinstance(value,str) or not value or len(value)>500:
            raise ValueError('Select an exact animation input reference')
        if not re.fullmatch('[a-f0-9]{64}',value):
            from .contracts import relative
            relative(value)
            media='application/json' if key=='manifest_sha256' else 'application/x-blender'
            if sum(i['path']==value and i.get('media_type')==media for i in a.get('inputs',[]))!=1:
                raise ValueError('Animation named input is not bound: '+key)
    for media in ('application/json', 'application/x-blender'):
        if sum(i.get('media_type') == media for i in a.get('inputs', [])) != 1:
            raise ValueError('Select one animation manifest and one scene')
    if sum(i.get('media_type') == 'application/zip' for i in a.get('inputs', [])) > 1:
        raise ValueError('Select at most one animation checkpoint')
    future=[i for i in a.get('inputs',[]) if 'from_task' in i]
    if future and ('scene_sha256' not in params or any(re.fullmatch('[a-f0-9]{64}',params[k]) for k in ('manifest_sha256','scene_sha256'))):
        raise ValueError('Legacy hash bindings require already registered inputs')
    if any(i.get('media_type')=='application/zip' for i in future):
        raise ValueError('Animation checkpoints require a confirmed stopped registered attempt')

def blender_assets(a, spec):
    params = a['execution']['parameters']
    if not isinstance(params['manifest_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', params['manifest_sha256']):
        raise ValueError('Select the exact asset manifest hash')
    if sum((i.get('media_type') == 'application/json' for i in a.get('inputs', []) if isinstance(i, dict))) != 1:
        raise ValueError('Select one asset manifest JSON')
    if any(('artifact' not in i or 'from_task' in i for i in a.get('inputs', []))):
        raise ValueError('Asset imports require already registered files and manifest; prepare them in a separate stage')

def blender_script(a, spec):
    params = a['execution']['parameters']
    if params['permissions'] != 'unrestricted_host':
        raise ValueError('Blender Python requires explicit unrestricted_host scope; no isolation is enforced.')
    for key in ('scene_sha256','script_sha256','checks_sha256'):
        if key=='scene_sha256' and params[key] is None:continue
        if not isinstance(params[key],str) or not params[key] or len(params[key])>500:
            raise ValueError('Blender Python needs exact input references')
        if not re.fullmatch('[a-f0-9]{64}',params[key]):
            from .contracts import relative
            relative(params[key])
            if sum(i['path']==params[key] for i in a.get('inputs',[]))!=1:raise ValueError('Blender named input is not bound')
    for media,count in (('application/x-blender',int(params['scene_sha256'] is not None)),('text/x-python',1),('application/json',1)):
        if sum(i.get('media_type')==media for i in a.get('inputs',[]))!=count:
            raise ValueError('Blender Python needs script/checks and a scene only for edits')
    if any('from_task' in i for i in a.get('inputs',[])) and re.fullmatch('[a-f0-9]{64}',params['script_sha256']):
        raise ValueError('Legacy hash bindings require already registered inputs')
    # Producer references are resolved by Runtime before exact-script approval.
    # This permits a wire, never approval of an as-yet unwritten script.


def gemini_model(a, spec):
    e = a['execution']
    params = a['execution']['parameters']
    if not isinstance(params['model'], str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,119}', params['model']):
        raise ValueError('Choose an exact Gemini model ID.')
    if type(params['max_output_tokens']) is not int or not 1 <= params['max_output_tokens'] <= 4096:
        raise ValueError('API output token limit must be 1–4096.')
    if e['capability'] == 'gemini.image':
        if params['aspect_ratio'] not in ('1:1', '16:9', '9:16'):
            raise ValueError('Unsupported image aspect ratio.')
        if sum((i.get('media_type', '').startswith('image/') for i in a.get('inputs', []))) > 6:
            raise ValueError('Choose at most six image references.')

def pptx_create(a, spec):
    if sum((i.get('media_type') == 'application/json' for i in a.get('inputs', []) if isinstance(i, dict))) != 1:
        raise ValueError('PPTX creation requires exactly one JSON slide specification.')
    if any((not isinstance(o, dict) or not str(o.get('path', '')).endswith('.pptx') for o in a.get('outputs', []))):
        raise ValueError('PPTX creation requires a .pptx output path.')

def record_slides(a, spec):
    from .sourcing_slides import validate_assignment
    validate_assignment(a)

def catalog_images(a, spec):
    from .product_photos import validate_assignment
    validate_assignment(a)

def pptx_edit(a, spec):
    types = [i.get('media_type') for i in a.get('inputs', []) if isinstance(i, dict)]
    if types.count('application/json') != 1 or types.count('application/vnd.openxmlformats-officedocument.presentationml.presentation') != 1 or any((t not in spec['input_types'] for t in types)):
        raise ValueError('PPTX edit requires one baseline PPTX, one JSON edit manifest and optional declared PNG/JPEG pictures.')
    if any((not isinstance(o, dict) or not str(o.get('path', '')).endswith('.pptx') for o in a.get('outputs', []))):
        raise ValueError('PPTX edit requires a .pptx output path.')

def hyperframes(a, spec):
    e = a['execution']
    params = a['execution']['parameters']
    if sum((i.get('media_type') == 'application/json' for i in a['inputs'])) != 1:
        raise ValueError('HyperFrames needs exactly one project JSON or preview receipt')
    if e['capability'] == 'hyperframes.render':
        if sum((i.get('media_type') == 'application/zip' for i in a['inputs'])) != 1 or any(('artifact' not in i or 'from_task' in i for i in a['inputs'])):
            raise ValueError('Render requires already registered preview project and receipt; select the preview before the render stage')
        if any((not isinstance(params[k], str) or not re.fullmatch('[a-f0-9]{64}', params[k]) for k in ('project_sha256', 'preview_sha256'))):
            raise ValueError('Render requires exact project and preview SHA-256 values')

def media_compose(a, spec):
    if sum((i.get('media_type') == 'application/json' for i in a['inputs'])) != 1:
        raise ValueError('Reel composition requires exactly one JSON scene specification')

def rhino3dm_create(a, spec):
    if sum((i.get('media_type') == 'application/json' for i in a['inputs'])) != 1:
        raise ValueError('Standalone 3DM creation needs exactly one geometry JSON specification')

def rhino_inspect(a, spec):
    if sum((i['media_type'] == 'application/vnd.rhino' for i in a['inputs'])) != 1:
        raise ValueError('Select exactly one Rhino model version for inspection')

def blender_inspect(a, spec):
    if sum((i['media_type'] == 'application/x-blender' for i in a['inputs'])) != 1:
        raise ValueError('Select exactly one Blender scene version for inspection.')

def sketchup_inspect(a, spec):
    if sum((i['media_type'] == 'application/vnd.sketchup.skp' for i in a['inputs'])) != 1:
        raise ValueError('Select exactly one SketchUp model version for inspection.')

def blender_scene(a, spec):
    if sum((i['media_type'] == 'application/json' for i in a['inputs'])) != 1:
        raise ValueError('Blender scene needs exactly one application/json scene input; context inputs are text/plain.')

def crop_image(a, spec):
    region=a['execution']['parameters']['region']
    if region[2]<=0 or region[3]<=0 or max(region[2:])>4096 or region[2]*region[3]>8_000_000:
        raise ValueError('Crop dimensions exceed PNG upload bounds')
    if not a['outputs'][0]['path'].lower().endswith('.png'):raise ValueError('Crop output needs a PNG path')

VALIDATORS = {
    'images.crop': (crop_image,),
    'images.collect': (image_subjects,),
    'web.sources.rendered': (rendered_sources,),
    'web.sources.native': (rendered_sources,),
    'web.sources.prepared': (prepared_sources,),
    'web.sources': (source_queries,),
    'images.fetch': (zip_output,),
    'images.merge': (zip_output,),
    'images.products': (zip_output, catalog_images,),
    'images.catalog': (zip_output, catalog_images,),
    'runway.image': (cloud_media,),
    'runway.video': (cloud_media,),
    'higgsfield.image': (cloud_media,),
    'higgsfield.video': (cloud_media,),
    'meshy.mesh': (cloud_media,),
    'openai.image': (openai_image,),
    'openrouter.image': (openrouter_image,),
    'rhino.render': (rhino_render,),
    'sketchup.run_ruby': (sketchup_script,),
    'rhino.grasshopper': (new_grasshopper, rhino_script,),
    'rhino.run_python': (rhino_script,),
    'rhino3dm.run_python': (rhino_script,),
    'blender.animate': (blender_animation,),
    'blender.import_asset': (blender_assets,),
    'blender.run_python': (blender_script,),
    'gemini.text': (gemini_model,),
    'gemini.image': (gemini_model,),
    'pptx.create': (pptx_create,),
    'sourcing.slides': (record_slides,),
    'collection.slides': (record_slides,),
    'pptx.edit': (pptx_edit,),
    'hyperframes.preview': (hyperframes,),
    'hyperframes.render': (hyperframes,),
    'media.compose': (media_compose,),
    'rhino3dm.create': (rhino3dm_create,),
    'rhino.inspect': (rhino_inspect,),
    'blender.inspect': (blender_inspect,),
    'blender.geometry': (blender_inspect,),
    'sketchup.inspect': (sketchup_inspect,),
    'blender.scene': (blender_scene,),
    'blender.mesh_scene': (blender_scene,),
}

from .document_compose import validate_assignment as compose_assignment
VALIDATORS["document.compose"]=(compose_assignment,)
