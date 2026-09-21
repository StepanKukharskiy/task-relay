"""Service-owned native application profiles; plans cannot supply adapters or commands.

Shared execution/authorization metadata, with geometry and process mechanics kept
in each application's adapter. Unknown host capabilities never fall back to Blender.
"""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class NativeApp:
    name: str
    media: str
    suffix: str
    script_operation: str
    script_media: str
    script_suffix: str
    contract_module: str
    sources: tuple
    new_model: bool = False

    def discover(self):
        if self.name == 'rhino3dm':
            from .rhino3dm_script import discover
            return discover()
        from task_relay import host_apps
        return getattr(host_apps, self.name)()

    def validate_checks(self, value):
        return import_module('orchestrator.' + self.contract_module).validate_checks(value)

    def validate_script(self, data, app):
        from .host_script import validate_script_bytes
        validate_script_bytes(data)
        text = data.decode('utf-8')
        if '\x00' in text: raise ValueError('Host script contains a NUL byte')
        if self.script_suffix == '.py' and not (self.name == 'rhino' and app.get('major', 8) == 7):
            compile(text, 'host-script.py', 'exec')
        # Ruby syntax is compiled, without execution, by SketchUp's own Ruby
        # runtime in the baseline phase. A system Ruby is not authoritative.


COMMON = ('host_code.py', 'host_script.py', 'native_apps.py', 'execution.py', 'step_runner.py', 'outcomes.py')
APPS = {
    'rhino3dm': NativeApp('rhino3dm', 'application/vnd.rhino', '.3dm', 'rhino3dm.run_python',
        'text/x-python', '.py', 'rhino3dm_script_contract', COMMON + ('rhino3dm_script_contract.py',
        'rhino3dm_script.py', 'rhino3dm_script_worker.py', 'rhino3dm_document.py', 'rhino3dm_contract.py'), True),
    'blender': NativeApp('blender', 'application/x-blender', '.blend', 'blender.run_python',
        'text/x-python', '.py', 'blender_edit', COMMON + ('blender_edit.py', 'blender_edit_worker.py', 'blender_snapshot.py')),
    'rhino': NativeApp('rhino', 'application/vnd.rhino', '.3dm', 'rhino.run_python',
        'text/x-python', '.py', 'rhino_contract', COMMON + ('rhino_contract.py', 'rhino_execution.py', 'rhino_worker.py',
        '../task_relay/rhino_host.py', '../task_relay/host_apps.py'), True),
    'sketchup': NativeApp('sketchup', 'application/vnd.sketchup.skp', '.skp', 'sketchup.run_ruby',
        'text/x-ruby', '.rb', 'sketchup_contract', COMMON + ('sketchup_contract.py', 'sketchup_execution.py', 'sketchup_worker.rb',
        '../task_relay/sketchup_host.py', '../task_relay/host_apps.py'), True),
}
SCRIPT_OPERATIONS = tuple(p.script_operation for p in APPS.values())
NATIVE_MEDIA = tuple(p.media for p in APPS.values())


def profile(capability):
    name = capability.split('.')[0]
    if name not in APPS: raise ValueError('Unknown native application; no fallback')
    return APPS[name]


def execute(frozen, control, documents):
    capability = frozen['execution']['capability']
    app = profile(capability)
    if app.name == 'rhino3dm':
        module = 'rhino3dm_script'
    elif app.name in ('rhino', 'sketchup'):
        module = app.name + '_execution'
    else:
        modules = {'blender.startup':'blender_host', 'blender.scene':'blender_host',
            'blender.mesh_scene':'blender_host', 'blender.inspect':'blender_inspection',
            'blender.run_python':'blender_edit', 'blender.import_asset':'blender_assets',
            'blender.animate':'blender_animation'}
        if capability not in modules: raise ValueError('Unknown native operation; no fallback')
        module = modules[capability]
    return import_module('orchestrator.' + module).execute(frozen, control, documents)
