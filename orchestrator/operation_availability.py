"""Read-only built-in availability checks; no dispatch or credentials in output."""
import importlib.util
from .native_apps import profile as native_profile

def search(a, spec):
    from task_relay import gemini
    config = gemini.read_config()
    if not config or config.get('models', {}).get('text') != a['execution']['parameters']['model']:
        raise ValueError('The configured Gemini text model for web.sources is unavailable or changed.')

def hyperframes(a, spec):
    from .hyperframes_project import available as project_available
    project_available()

def compose(a, spec):
    from .reel_document import available as reel_available
    reel_available()

def geometry(a, spec):
    from .rhino3dm_document import available as library_available
    library_available()

def photos(a, spec):
    if importlib.util.find_spec('PIL') is None:
        raise ValueError('Image collection requires the bundled Pillow image validator.')

def presentation_create(a, spec):
    from .pptx_document import available as pptx_available
    pptx_available()

def presentation_edit(a, spec):
    from .pptx_edit import available as pptx_edit_available
    pptx_edit_available()

def presentation_preview(a, spec):
    from task_relay.presentation_host import discover
    discover()

def image_conversion(a, spec):
    if importlib.util.find_spec('PIL') is None:
        raise ValueError('Image conversion dependency is missing; no provider request was sent. Install task-relay[images] or update the desktop app.')

def native(a, spec):
    app = native_profile(a['execution']['capability']).discover()
    if not app['available']:
        raise ValueError(app['blocker'])
    if a['execution']['capability'] == 'blender.animate':
        from task_relay.host_apps import video_tools
        if not video_tools()['available']:
            raise ValueError('Animation needs installed ffmpeg and ffprobe executables')

def provider(a, spec):
    from task_relay import gemini, api_providers
    name = a['execution']['capability'].split('.')[0]
    from task_relay import cloud_providers
    config = cloud_providers.read_config(name) if name in cloud_providers.PROVIDERS else api_providers.read_config(name) if name in api_providers.SPECS else gemini.read_config()
    if not config:
        raise ValueError(name + ' capability is unavailable: provider configuration is missing.')
