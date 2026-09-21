"""Read-only installed-application discovery behind a portable host boundary.

Presence is not execution permission. Workers retain their existing sandbox,
assignment scope and supervisor limits. Discovery never launches an application.
"""
import os
from pathlib import Path
import shutil
import sys

RHINO_APPLICATIONS=Path('/Applications')
APPLICATIONS=Path('/Applications')


def bundle_version(executable):
    import plistlib
    for parent in Path(executable).parents:
        if parent.suffix == '.app':
            try: return str(plistlib.loads((parent/'Contents/Info.plist').read_bytes())['CFBundleShortVersionString'])
            except (OSError, ValueError, KeyError): return None
    return None


def codex_candidates(environ=None, platform=None, which=None):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    which=shutil.which if which is None else which
    if env.get('TASK_RELAY_CODEX'): return [Path(env['TASK_RELAY_CODEX']).expanduser()]
    paths=[]; found=which('codex')
    if found: paths.append(Path(found))
    if platform=='darwin':
        paths += [root/(name+'.app')/'Contents/Resources/codex' for root in (APPLICATIONS,Path.home()/'Applications') for name in ('ChatGPT','Codex')]
    return paths


def blender_candidates(environ=None, platform=None, which=None):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    which=shutil.which if which is None else which
    if env.get('TASK_RELAY_BLENDER'): return [Path(env['TASK_RELAY_BLENDER']).expanduser()]
    paths=[]; found=which('blender')
    if found: paths.append(Path(found))
    if platform=='darwin':
        for root in (APPLICATIONS,Path.home()/'Applications'):
            paths.append(root/'Blender.app/Contents/MacOS/Blender')
            paths.extend(p/'Contents/MacOS/Blender' for p in sorted(root.glob('Blender*.app'),reverse=True))
    elif platform=='win32':
        paths.extend(sorted((Path(env.get('PROGRAMFILES','C:/Program Files'))/'Blender Foundation').glob('Blender */blender.exe'),reverse=True))
    return paths


def rhino_candidates(environ=None, platform=None):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    if env.get('TASK_RELAY_RHINO'):return [Path(env['TASK_RELAY_RHINO']).expanduser()]
    if platform=='win32':
        return [Path(env.get('PROGRAMFILES','C:/Program Files'))/('Rhino '+m)/'System/Rhino.exe' for m in ('8','7')]
    result=[]
    for root in (RHINO_APPLICATIONS,Path.home()/'Applications'):
        result.extend(root/('Rhino '+m+'.app')/'Contents/MacOS/Rhinoceros' for m in ('8','7'))
        result.extend(p/'Contents/MacOS/Rhinoceros' for p in sorted(root.glob('Rhino*.app'),reverse=True))
    return result


def claude_candidates(which=None):
    from .relay_paths import PATHS
    which=shutil.which if which is None else which
    root=PATHS.data/'claude-venv'
    paths=list(root.glob('lib/python*/site-packages/claude_agent_sdk/_bundled/claude'))
    paths.append(root/'Lib/site-packages/claude_agent_sdk/_bundled/claude.exe')
    found=which('claude')
    if found:paths.append(Path(found))
    return paths


def sketchup_candidates(environ=None, platform=None):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    if env.get('TASK_RELAY_SKETCHUP'):return [Path(env['TASK_RELAY_SKETCHUP']).expanduser()]
    if platform=='win32':
        return sorted((Path(env.get('PROGRAMFILES','C:/Program Files'))/'SketchUp').glob('SketchUp */SketchUp.exe'),reverse=True)
    return [p/'Contents/MacOS/SketchUp' for root in (APPLICATIONS,Path.home()/'Applications')
            for p in sorted(root.glob('SketchUp*/SketchUp.app'),reverse=True)] + [APPLICATIONS/'SketchUp.app/Contents/MacOS/SketchUp']


def sketchup(environ=None, platform=None, respect_access=True):
    platform=sys.platform if platform is None else platform
    from .app_access import enabled
    present=[p.resolve() for p in sketchup_candidates(environ,platform) if p.is_absolute() and p.is_file() and os.access(p,os.X_OK)]
    selected=next((p for p in present if not respect_access or enabled('sketchup',p)),None)
    version=bundle_version(selected) if selected else None
    blocker=('Direct SketchUp requires the macOS desktop adapter.' if platform!='darwin' else
             'SketchUp is off in Settings → Apps and tools.' if present and selected is None else
             'Selected SketchUp executable is unavailable; no fallback for an explicit path.' if selected is None else
             'SketchUp 2025/2026 application bundle required.' if not version or version.split('.')[0] not in ('25','26','2025','2026') else None)
    return dict(id='sketchup',available=blocker is None,executable=str(selected) if selected else None,version=version,
        interpreter='Embedded Ruby',blocker=blocker,
        executor='Registered sketchup.startup / sketchup.inspect / sketchup.run_ruby; exact Ruby/checks approval for modeling',
        evidence='Executable/bundle presence only; desktop startup, license and Ruby execution require qualification.',
        outputs=['Editable .skp candidate','Viewport PNG','Ruby source and verification/receipt JSON'],
        verification='Owned desktop process; saved candidate reopened independently. No existing user session attachment or automatic replay.')


def claude_cli():
    from .app_access import enabled
    present=[p for p in claude_candidates() if p.is_absolute() and p.is_file() and os.access(p,os.X_OK)]
    chosen=next((p for p in present if enabled('claude',p)),None)
    if present and chosen is None:raise ValueError('Claude executors are off in Settings → Apps and tools.')
    return str(chosen) if chosen else None


def installed(environ=None, platform=None, which=None):
    """Bounded known installation locations, no process launches or credential reads."""
    from .app_access import key
    from .relay_paths import PATHS
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    which=shutil.which if which is None else which
    candidates=[(f,p) for f,paths in (
        ('rhino',rhino_candidates(env,platform)),('blender',blender_candidates(env,platform,which)),('sketchup',sketchup_candidates(env,platform)),
        ('codex',codex_candidates(env,platform,which))) for p in paths]
    candidates.extend(('claude',p) for p in claude_candidates(which))
    # The account integration uses this SDK environment; desktop Claude alone
    # does not establish a usable Relay executor.
    candidates.append(('claude',PATHS.data/'claude-venv'/('Scripts/python.exe' if platform=='win32' else 'bin/python')))
    if platform=='darwin':
        candidates.extend(('claude',root/'Claude.app/Contents/MacOS/Claude') for root in (APPLICATIONS,Path.home()/'Applications'))
    for tool in ('ffmpeg','ffprobe'):
        raw=env.get('TASK_RELAY_'+tool.upper()) or which(tool)
        if raw:candidates.append(('ffmpeg',Path(raw)))
    rows=[];seen=set()
    for family,p in candidates:
        if not p.is_absolute() or not p.is_file() or not os.access(p,os.X_OK):continue
        account_runtime=family=='claude' and 'claude-venv' in p.parts and p.name.startswith('python')
        p=p.resolve();ident=key(family,p)
        if ident in seen:continue
        seen.add(ident);version=bundle_version(p)
        desktop_claude=family=='claude' and any(parent.name=='Claude.app' for parent in p.parents)
        supported=not desktop_claude and not (family=='rhino' and (platform!='darwin' or not version or version.split('.')[0] not in ('7','8')))
        if family=='sketchup':supported=platform=='darwin' and bool(version and version.split('.')[0] in ('25','26','2025','2026'))
        rows.append({'id':ident,'family':family,'name':('Claude desktop' if desktop_claude else 'Claude account worker' if account_runtime else 'Codex worker' if family=='codex' else family.capitalize()),
            'version':version,'executable':str(p),'supported':supported,
            'detail':('Desktop app detected; Relay uses the Claude account SDK, not desktop UI control.' if desktop_claude else
                      'Native adapter unavailable on this host.' if not supported else 'Detected locally; license and account readiness are checked when used.')})
    return rows


def blender(environ=None, platform=None, which=None, respect_access=True):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    which=shutil.which if which is None else which
    override=env.get('TASK_RELAY_BLENDER')
    from .app_access import enabled
    candidates=blender_candidates(env,platform,which)
    present=[p.resolve() for p in candidates if p.is_absolute() and p.is_file() and os.access(p,os.X_OK)]
    executable=next((p for p in present if not respect_access or enabled('blender',p)),None)
    return dict(id='blender',available=executable is not None,executable=str(executable) if executable else None,
        executor='Registered blender.startup / blender.scene / blender.mesh_scene / blender.inspect / blender.import_asset / blender.animate host operations; blender.run_python requires exact-code host approval; agent shell remains sandboxed',
        evidence='Executable presence only; each approved operation must establish successful execution.',
        blocker=None if executable else ('Blender is off in Settings → Apps and tools.' if present else 'Configured TASK_RELAY_BLENDER is not an executable absolute file.' if override else 'Blender executable not found on this host.'),
        invocation=['--background','--factory-startup','--python-exit-code','1','--python','SCRIPT.py'],
        outputs=['Editable .blend scene','Rendered .png preview','Source .py and execution/verification evidence'],
        verification='Save the scene, reopen it in a separate Blender process, inspect geometry and render the saved scene. Return real files; code alone is not completion.')


def rhino(environ=None, platform=None, respect_access=True):
    """Read installed major version; never launch, guess or switch an override."""
    import plistlib
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    override = env.get('TASK_RELAY_RHINO')
    requested = env.get('TASK_RELAY_RHINO_VERSION')
    if environ is None and not override and requested is None:
        from .rhino_preferences import preference
        selected=preference()
        if selected!='auto':requested=selected
    candidates = rhino_candidates(env,platform)
    if requested in ('7','8') and not override:
        matches=[p for p in candidates if (bundle_version(p) or '').split('.')[0]==requested]
        candidates=matches or [RHINO_APPLICATIONS/('Rhino '+requested+'.app')/'Contents/MacOS/Rhinoceros']
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
    from .app_access import enabled
    if available and respect_access and not enabled('rhino',path):
        # Auto may choose another enabled installation only before a plan is
        # frozen. Explicit version/path selection never silently falls back.
        if not override and requested is None:
            for candidate in rhino_candidates(env,platform):
                if candidate==path:continue
                found=rhino({'TASK_RELAY_RHINO':str(candidate)},platform,respect_access=True)
                if found['available']:return found
        available=False;blocker='Selected Rhino is off in Settings → Apps and tools.'
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
        from .app_access import enabled
        if result[name] and not enabled('ffmpeg',result[name]):result[name]=None
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
        dict(name='SketchUp', available=sketchup(platform=host.platform)['available'], detail=sketchup(platform=host.platform)['evidence']),
        dict(name='FFmpeg + FFprobe', available=video['available'],
             detail='Executable presence only; no media operation was run.'),
    ]


def catalog(state=None):
    # Catalog enrichment must not mutate a detector's reusable result.
    result=[dict(blender()),dict(rhino()),dict(sketchup())]
    result[1]['installed_versions']=[r for major in ('7','8')
        if (r:=rhino({'TASK_RELAY_RHINO_VERSION':major},respect_access=False))['available']]
    result[1]['selection_note']='The top-level Rhino is selected for new plans, not the only installed version or evidence of a running session. installed_versions lists other detected versions. Change the preferred version in Settings → Apps and tools before preparing version-specific code; existing plans keep their exact runtime approval.'
    if state is not None:
        from task_relay.host_evidence import environments
        result[0]['execution_environments']=environments(state,result[0])
    return result
