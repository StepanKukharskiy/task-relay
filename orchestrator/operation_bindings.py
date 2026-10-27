"""Host and transport bindings captured before dispatch by registered adapters."""
from pathlib import Path
from .runtime import file_hash

def presentation(frozen):
    from task_relay import presentation_host
    frozen['presentation_runtime'] = presentation_host.discover()
    frozen['runtime_sources']['task_relay/presentation_host.py'] = file_hash(Path(presentation_host.__file__))

def media(frozen):
    from task_relay import media_host
    frozen['media_runtime'] = media_host.available('project' if frozen['execution']['capability'].startswith('hyperframes.') else 'template')
    frozen['runtime_sources']['task_relay/media_host.py'] = file_hash(Path(media_host.__file__))

def sketchup(frozen):
    from .sketchup_execution import application_binding
    frozen['sketchup_application'] = application_binding()

def rendered(frozen):
    from task_relay import source_browser, general_browser, orchestrator_web, public_browser_navigation
    frozen['runtime_sources'].update({'task_relay/' + Path(m.__file__).name: file_hash(Path(m.__file__)) for m in (source_browser, general_browser, orchestrator_web, public_browser_navigation)})
    if frozen.get('execution',{}).get('capability')=='web.sources.native':
        from task_relay import source_native_browser
        frozen['source_browser_runtime']=source_native_browser.discover()
        frozen['runtime_sources'].update({'task_relay/'+Path(m.__file__).name:file_hash(Path(m.__file__)) for m in source_native_browser.modules()})

def cloud(frozen):
    from task_relay import cloud_providers
    frozen['runtime_sources']['task_relay/cloud_providers.py'] = file_hash(Path(cloud_providers.__file__))

def rhino(frozen):
    from task_relay import rhino_host, host_apps
    frozen['rhino_host_sources'] = {m.__name__: file_hash(Path(m.__file__)) for m in (rhino_host, host_apps)}
    from task_relay.host_evidence import application_signature
    rhino_app = host_apps.rhino()
    frozen['rhino_application'] = {'signature': application_signature(rhino_app['executable']), 'major': rhino_app.get('major', 8), 'version': rhino_app.get('version')}
