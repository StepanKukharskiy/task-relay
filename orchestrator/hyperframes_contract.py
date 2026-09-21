"""Transport and execution bounds for provider-authored HyperFrames projects.

The files are real front-end source, not a Relay layout or animation schema.
"""
import math
from pathlib import PurePosixPath
from html.parser import HTMLParser
from .reel_contract import load

PREVIEW_OUTPUTS={'delivery/project.json':'application/json','delivery/project.zip':'application/zip',
    'delivery/frames.zip':'application/zip','delivery/contact-sheet.png':'image/png','delivery/verification.json':'application/json'}
RENDER_OUTPUTS={'delivery/reel.mp4':'video/mp4','delivery/project.zip':'application/zip',
    'delivery/contact-sheet.png':'image/png','delivery/verification.json':'application/json'}
ASSET_TYPES=('image/png','image/jpeg','image/webp','image/svg+xml','video/mp4','video/webm',
    'audio/mpeg','audio/wav','audio/mp4','audio/ogg','font/ttf','font/otf','font/woff','font/woff2',
    'text/javascript','application/javascript','text/css','text/plain')
TEXT_SUFFIXES={'.html','.css','.js','.mjs','.json','.svg','.glsl','.wgsl','.txt','.md'}
ASSET_SUFFIXES=TEXT_SUFFIXES|{'.png','.jpg','.jpeg','.webp','.mp4','.webm','.mp3','.wav','.m4a','.ogg','.ttf','.otf','.woff','.woff2'}
DESCRIPTION='''HyperFrames project version 1: {version:1,width:1080,height:1920,fps:30,
duration:14,audio:false,samples:[0.8,3,7,13.8],files:{"index.html":"<!doctype html>...",
"styles.css":"...","motion.js":"..."},assets:{"assets/photo.png":"exact/input.png"}}.
All fields required. files maps project-relative names to exact UTF-8 source text;
assets maps project-relative names to exact declared input paths. These are REAL
HTML/CSS/JavaScript files, not predefined scenes. Author arbitrary layers, typography,
cards, characters, transitions, SVG/canvas/WebGL and seekable animation. Follow the
user's guides and selected storyboard. Never substitute the media.compose template.
Use inline styles/scripts or separate local files. index.html is the entrypoint.
Give its single root data-composition-id, matching data-width/data-height/data-duration.
Register a paused seekable timeline, or use paused WAAPI plus data-no-timeline.
Use local declared libraries (including GSAP) and media; no CDN, package installation,
Node programs, package.json, hyperframes.json, server code or shell commands. The
framework controls timed clip visibility and audio/video playback. No wall-clock,
unseeded randomness or remote services. Fonts may use the supplied assets/relay-font.ttf.
Bounds: 1–30 authored files, 2 MB total source; <=50 assets; even 320–1920 dimensions,
<=2073600 pixels; 15/24/30 FPS; 0.5–120 seconds, frame aligned; 1–20 sorted distinct
sample times within duration. Samples should cover scene midpoints AND transition
boundaries. Audio declares expected encoded audio presence, not synthesized speech.

hyperframes.preview compiles the exact source and assets, runs HyperFrames check,
captures selected full-size frames, and delivers project.json, project.zip,
frames.zip, contact-sheet.png and verification.json. Its optional approved correction
loop sends confirmed validation failures or independent review findings back to the
author to revise the source, then checks a NEW immutable attempt. No uncertain replay.
Preview selection is a human gate. Text providers author/review source; same-provider
code workers can inspect binary receipts/ZIPs but cannot claim visual inspection.

hyperframes.render is a separate operation using an already registered selected
preview project.zip and its verification.json. Parameters project_sha256 and
preview_sha256 bind those exact bytes. It rechecks the same project, renders H.264,
verifies dimensions/FPS/frames/duration/audio and delivers reel.mp4, project.zip,
contact-sheet.png and verification.json. It must not redesign or regenerate source.
Keep the completed content workflow unchanged; use its selected storyboard/guides
as preparation inputs and propose only the missing preview/render continuation.
'''


def path(value):
    if (not isinstance(value,str) or not value or len(value)>240 or '\\' in value or ':' in value
            or any(ord(c)<32 for c in value) or any(p in ('','.','..') or p.startswith('.') for p in value.split('/'))
            or PurePosixPath(value).is_absolute()):raise ValueError('Project paths must be plain relative paths without traversal or hidden components')
    if any(p.lower() in ('node_modules','package.json','package-lock.json','hyperframes.json','relay-project.json') for p in value.split('/')):
        raise ValueError('Runtime/configuration paths cannot be authored by a composition')
    return value


def validate(value,inputs=None):
    if not isinstance(value,dict) or set(value)!={'version','width','height','fps','duration','audio','samples','files','assets'}:
        raise ValueError('Use the exact HyperFrames project fields in project_schema')
    if type(value['version']) is not int or value['version']!=1:raise ValueError('Unsupported HyperFrames project version')
    if any(type(value[k]) is not int or not 320<=value[k]<=1920 or value[k]%2 for k in ('width','height')) or value['width']*value['height']>2073600:
        raise ValueError('Invalid canvas dimensions')
    if type(value['fps']) is not int or value['fps'] not in (15,24,30):raise ValueError('Invalid project FPS')
    duration=value['duration']
    if type(duration) not in (int,float) or not math.isfinite(duration) or not .5<=duration<=120 or abs(duration*value['fps']-round(duration*value['fps']))>1e-6:
        raise ValueError('Duration must be finite, bounded and frame aligned')
    if type(value['audio']) is not bool:raise ValueError('Declare expected audio presence as true or false')
    samples=value['samples']
    if (not isinstance(samples,list) or not 1<=len(samples)<=20 or any(type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<duration for t in samples)
            or samples!=sorted(set(samples))):raise ValueError('Declare 1–20 distinct sorted sample times inside the timeline')
    files=value['files'];assets=value['assets']
    if not isinstance(files,dict) or not 1<=len(files)<=30 or 'index.html' not in files:raise ValueError('A project requires index.html and at most 30 source files')
    if not isinstance(assets,dict) or len(assets)>50:raise ValueError('A project permits at most 50 exact local assets')
    seen=set();total=0
    for name,content in files.items():
        path(name)
        if PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES or not isinstance(content,str):raise ValueError('Only UTF-8 front-end source files are supported')
        total+=len(content.encode('utf-8'))
        if not content.strip() or '\x00' in content:raise ValueError('Empty or NUL-containing project source')
        seen.add(name.casefold())
    if len(seen)!=len(files) or total>2000000:raise ValueError('Project source exceeds bounds or duplicates a case-insensitive path')
    for name,source in assets.items():
        path(name);path(source)
        if name.casefold() in seen or PurePosixPath(name).suffix.lower() not in ASSET_SUFFIXES:raise ValueError('Invalid or colliding asset destination')
        seen.add(name.casefold())
        if inputs is not None and inputs.get(source) not in ASSET_TYPES:raise ValueError('Asset must name an exact declared compatible input: '+source)
    # File/directory collisions must fail before any file is materialized.
    for name in seen:
        if any(str(p) in seen for p in PurePosixPath(name).parents if str(p)!='.'):
            raise ValueError('Project file/directory paths collide')
    class Root(HTMLParser):
        def __init__(self):super().__init__();self.roots=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if 'data-composition-id' in a:self.roots.append(a)
    parsed=Root();parsed.feed(files['index.html'])
    if len(parsed.roots)!=1:raise ValueError('index.html needs one explicit composition root; put sub-compositions in separate files')
    root=parsed.roots[0]
    try:matching=all(float(root['data-'+k])==value[k] for k in ('width','height','duration'))
    except (KeyError,ValueError,TypeError):matching=False
    if not matching:raise ValueError('Composition root dimensions/duration must match the project manifest')
    return value
