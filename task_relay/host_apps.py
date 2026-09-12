"""Read-only installed-application discovery behind a portable host boundary.

Presence is not execution permission. Workers retain their existing sandbox,
assignment scope and supervisor limits. Discovery never launches an application.
"""
import os
from pathlib import Path
import shutil
import sys


def blender(environ=None, platform=None, which=None):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    which=shutil.which if which is None else which
    override=env.get('TASK_RELAY_BLENDER')
    candidates=[]
    if override:
        candidates=[Path(override).expanduser()]
    else:
        found=which('blender')
        if found:candidates.append(Path(found))
        if platform=='darwin':candidates.append(Path('/Applications/Blender.app/Contents/MacOS/Blender'))
        elif platform=='win32':
            base=Path(env.get('PROGRAMFILES','C:/Program Files'))/'Blender Foundation'
            if base.is_dir():candidates.extend(sorted(base.glob('Blender */blender.exe'),reverse=True))
    executable=next((p.resolve() for p in candidates if p.is_absolute() and p.is_file() and os.access(p,os.X_OK)),None)
    return dict(id='blender',available=executable is not None,executable=str(executable) if executable else None,
        executor='Registered blender.startup / blender.scene / blender.mesh_scene / blender.inspect / blender.import_asset / blender.animate host operations; blender.run_python requires exact-code host approval; agent shell remains sandboxed',
        evidence='Executable presence only; each approved operation must establish successful execution.',
        blocker=None if executable else ('Configured TASK_RELAY_BLENDER is not an executable absolute file.' if override else 'Blender executable not found on this host.'),
        invocation=['--background','--factory-startup','--python-exit-code','1','--python','SCRIPT.py'],
        outputs=['Editable .blend scene','Rendered .png preview','Source .py and execution/verification evidence'],
        verification='Save the scene, reopen it in a separate Blender process, inspect geometry and render the saved scene. Return real files; code alone is not completion.')


def video_tools(environ=None, which=None):
    """Discover local encoding tools without launching them or installing software."""
    env=os.environ if environ is None else environ
    which=shutil.which if which is None else which
    result={}
    for name in ('ffmpeg','ffprobe'):
        raw=env.get('TASK_RELAY_'+name.upper()) or which(name)
        p=Path(raw).expanduser() if raw else None
        result[name]=str(p.resolve()) if p and p.is_absolute() and p.is_file() and os.access(p,os.X_OK) else None
    result['available']=all(result.values())
    return result


def catalog(state=None):
    result=[blender()]
    if state is not None:
        from task_relay.host_evidence import environments
        result[0]['execution_environments']=environments(state,result[0])
    return result
