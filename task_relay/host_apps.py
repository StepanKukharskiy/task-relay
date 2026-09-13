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


def rhino(environ=None, platform=None):
    """Read installed major version; never launch, guess or switch an override."""
    import plistlib
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    override = env.get('TASK_RELAY_RHINO')
    requested = env.get('TASK_RELAY_RHINO_VERSION')
    candidates = ([Path(override).expanduser()] if override else
        [Path('/Applications')/('Rhino '+major+'.app')/'Contents/MacOS/Rhinoceros' for major in ([requested] if requested in ('7','8') else ['8','7'])])
    path = next((p for p in candidates if p.is_absolute() and p.is_file() and os.access(p,os.X_OK)), candidates[0])
    present = path.is_absolute() and path.is_file() and os.access(path,os.X_OK)
    version = major = None
    try:
        info=plistlib.loads((path.parent.parent/'Info.plist').read_bytes())
        version=info['CFBundleShortVersionString'];major=int(version.split('.')[0])
    except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
    blocker = ('Direct Rhino needs the macOS adapter.' if platform != 'darwin' else
        'TASK_RELAY_RHINO_VERSION must be 7 or 8.' if requested is not None and requested not in ('7','8') else
        'Selected Rhino executable is unavailable; no fallback.' if not present else
        'Only verified Rhino 7/8 application bundles are supported.' if major not in (7,8) else
        'Selected Rhino version does not match TASK_RELAY_RHINO_VERSION.' if requested and str(major)!=requested else None)
    available = blocker is None
    return dict(id='rhino', available=available, executable=str(path.resolve()) if present else None,
        version=version, major=major, interpreter='IronPython 2.7' if major==7 else 'CPython 3' if major==8 else None,
        executor='Registered rhino.startup / rhino.inspect / rhino.run_python / rhino.render; exact Python/checks approval for modeling',
        evidence='Executable/bundle version only; runtime, license and rendering require a host check.', blocker=blocker,
        outputs=['Editable .3dm candidate', 'Viewport .png preview or native Rhino Render image', 'Python source and verification/receipt JSON'],
        verification='Reopen saved candidate in a separate owned Rhino process and check declared geometry/preservation. Grasshopper is paused.')


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


def launcher_tools(host=None, which=None):
    """Read-only, portable presence signals for the local setup page."""
    from .host import HOST, UnsupportedHost
    host = HOST if host is None else host
    which = shutil.which if which is None else which
    try:
        host.codex()
        codex = True
    except UnsupportedHost:
        codex = False
    blender_tool = blender(platform=host.platform, which=which)
    video = video_tools(which=which)
    return [
        dict(name='Git', available=bool(which('git')),
             detail='Executable presence only; needed for a source checkout.'),
        dict(name='Codex worker', available=codex,
             detail='Executable presence only; desktop task access is unchecked.'),
        dict(name='Claude CLI', available=bool(which('claude')),
             detail='Executable presence only; account access is unchecked.'),
        dict(name='Blender', available=blender_tool['available'], detail=blender_tool['evidence']),
        dict(name='Rhino 7 / 8', available=rhino(platform=host.platform)['available'], detail=rhino(platform=host.platform)['evidence']),
        dict(name='FFmpeg + FFprobe', available=video['available'],
             detail='Executable presence only; no media operation was run.'),
    ]


def catalog(state=None):
    result=[blender(),rhino()]
    if state is not None:
        from task_relay.host_evidence import environments
        result[0]['execution_environments']=environments(state,result[0])
    return result
