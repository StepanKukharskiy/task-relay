"""Provider-independent, data-only reel composition contract."""
import json
import math
import re
from pathlib import PurePosixPath

DESCRIPTION='''media.compose version 1 accepts exactly one JSON specification plus declared
PNG/JPEG assets and optional WAV/MP3 audio. No HTML, JavaScript, shell or URLs.
Specification: {version:1,width:1080,height:1920,fps:30,background:"#101820",
foreground:"#ffffff",accent:"#82cfff",audio:null,scenes:[{duration:6,title:"...",
body:"...",image:"assets/photo.png"|null,entrance:"left"|"right"|"up"|"down"|"fade",
narration:"..."}]}. Every field is required. 1–20 scenes; each duration 0.5–30
seconds and an integral number of frames; total <=120 seconds. Canvas dimensions
are even integers 320–1920, total <=2073600 pixels; fps is 15,24 or 30.
Title <=90 characters; body <=300; narration <=1000. Title must be nonempty.
Image/audio paths name exact declared inputs, never URLs or live project paths.
Images are contained with their full aspect ratio above the text panel; no crop,
distortion, per-scene arbitrary layout, source-code injection or asset generation.
Scene entrance is a short panel translation/fade; no motion presets are invented.
Narration text is planning metadata, NOT synthesized audio. Optional supplied audio
must fit the total timeline within 0.25 seconds. Without audio, delivery is silent.
Narration is limited to 180 words/minute per scene; visible title/body reading is
limited to 240 words/minute, excluding 0.4 seconds for transitions. These are
declared production bounds, not proof of comfortable pacing or visual quality.
Outputs: delivery/reel.mp4, delivery/project.zip (editable HTML, JSON and assets),
delivery/contact-sheet.png, delivery/verification.json. Local checks verify
render status, H.264 dimensions/fps/duration/audio and scene samples; an independent
review and human visual selection are still required. A text provider can author
the JSON. Raw assets go to the operation, not to the text-only author. A same-provider
code worker can inspect all deliverables and receipts; it must disclose that code
inspection is not visual inspection. Use images.view when actual visual review is
required and available; never switch model providers without authorization.
'''

OUTPUTS={'delivery/reel.mp4':'video/mp4','delivery/project.zip':'application/zip',
         'delivery/contact-sheet.png':'image/png','delivery/verification.json':'application/json'}

def load(text):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('Duplicate reel specification key: '+k)
            result[k]=v
        return result
    return json.loads(text,object_pairs_hook=unique)

def fields(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError('Invalid reel fields; follow media.compose composition_schema')

def words(text):return len(re.findall(r"\w+(?:['’\-]\w+)*",text))

def asset(path,types,assets):
    if path is None:return
    if (not isinstance(path,str) or not path or '\\' in path or ':' in path
            or PurePosixPath(path).is_absolute() or any(p in ('','.','..') for p in path.split('/'))
            or assets.get(path) not in types):raise ValueError('Reel asset must name an exact declared file of the required media type')

def validate(value,assets=None):
    assets=assets or {}
    fields(value,('version','width','height','fps','background','foreground','accent','audio','scenes'))
    if type(value['version']) is not int or value['version']!=1:raise ValueError('Unsupported reel version')
    if any(type(value[k]) is not int or not 320<=value[k]<=1920 or value[k]%2 for k in ('width','height')) or value['width']*value['height']>2073600:
        raise ValueError('Invalid reel canvas dimensions')
    if type(value['fps']) is not int or value['fps'] not in (15,24,30):raise ValueError('Unsupported reel frame rate')
    for k in ('background','foreground','accent'):
        if not isinstance(value[k],str) or not re.fullmatch('#[0-9a-fA-F]{6}',value[k]):raise ValueError('Reel colors must be six-digit hex values')
    asset(value['audio'],('audio/mpeg','audio/wav'),assets)
    if not isinstance(value['scenes'],list) or not 1<=len(value['scenes'])<=20:raise ValueError('Reel requires 1–20 scenes')
    total=0
    for scene in value['scenes']:
        fields(scene,('duration','title','body','image','entrance','narration'))
        duration=scene['duration']
        if (type(duration) not in (int,float) or not math.isfinite(duration) or not .5<=duration<=30
                or abs(duration*value['fps']-round(duration*value['fps']))>1e-6):raise ValueError('Scene duration must be bounded and frame-aligned')
        total+=duration
        for key,maximum in (('title',90),('body',300),('narration',1000)):
            text=scene[key]
            if not isinstance(text,str) or len(text)>maximum or any(ord(c)<32 and c not in '\n\t' for c in text):raise ValueError('Invalid reel '+key)
        if not scene['title'].strip():raise ValueError('Scene title is required')
        if scene['entrance'] not in ('left','right','up','down','fade'):raise ValueError('Unsupported scene entrance')
        asset(scene['image'],('image/png','image/jpeg'),assets)
        if words(scene['narration'])>duration*3:raise ValueError('Narration exceeds 180 words/minute; shorten it or extend this scene')
        if words(scene['title']+' '+scene['body'])>max(0,duration-.4)*4:raise ValueError('On-screen text exceeds the scene reading allowance')
    if total>120:raise ValueError('Reel duration exceeds 120 seconds')
    return value
