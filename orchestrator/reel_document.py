"""Compile bounded scene data into a local HyperFrames reel and verified delivery."""
import copy
from fractions import Fraction
import html
import json
from pathlib import Path
import shutil
import time
from urllib.parse import quote
import zipfile

from . import reel_contract as contract
from .runtime import file_hash, safe_file
from .workers import atomic
from task_relay import media_host


def available():
    try:from PIL import Image
    except ImportError as exc:raise ValueError('media.compose needs the bundled Pillow validator.') from exc
    return media_host.available()


def compile_project(value,workspace,project,runtime):
    """Only escaped text and validated data enter this service-owned HTML template."""
    from PIL import Image
    project.mkdir();assets=project/'assets';assets.mkdir()
    local=copy.deepcopy(value);mapping={}
    for name in dict.fromkeys([s['image'] for s in value['scenes'] if s['image']]+([value['audio']] if value['audio'] else [])):
        source=safe_file(workspace,name)
        if name!=value['audio']:
            with Image.open(source) as im:
                if im.format not in ('PNG','JPEG') or im.width*im.height>40000000:raise ValueError('Invalid or oversized reel image')
                im.verify()
        target='assets/'+str(len(mapping))+source.suffix.lower()
        shutil.copyfile(source,project/target);mapping[name]=target
    for scene in local['scenes']:
        if scene['image']:scene['image']=mapping[scene['image']]
    if local['audio']:local['audio']=mapping[local['audio']]
    shutil.copyfile(runtime['paths']['font'],assets/'font.ttf')
    atomic(project/'composition.json',local)
    atomic(project/'source-spec.json',value)
    total=sum(s['duration'] for s in local['scenes']);start=0;scenes=[];motions=[]
    offsets={'left':('-30px','0px'),'right':('30px','0px'),'up':('0px','30px'),'down':('0px','-30px'),'fade':('0px','0px')}
    for index,scene in enumerate(local['scenes']):
        picture=('<img alt="Source asset" src="'+quote(scene['image'])+'">') if scene['image'] else ''
        scenes.append(f'<section id="scene-{index}" class="clip" data-start="{start}" data-duration="{scene["duration"]}" data-track-index="{index}">'
            f'<div class="panel" id="panel-{index}">{picture}<div class="copy"><h1>{html.escape(scene["title"])}</h1>'
            f'<p>{html.escape(scene["body"])}</p></div></div></section>')
        x,y=offsets[scene['entrance']]
        motions.append(f'document.getElementById("panel-{index}").animate('
            f'[{{opacity:0,transform:"translate({x},{y})"}},{{opacity:1,transform:"translate(0px,0px)"}}],'
            f'{{duration:200,delay:{round(start*1000)},fill:"both",iterations:1}}).pause();')
        start+=scene['duration']
    audio=(f'<audio id="audio" src="{quote(local["audio"])}" data-start="0" data-duration="{total}" data-track-index="30"></audio>') if local['audio'] else ''
    width=local['width'];height=local['height'];font=min(width*.048,height*.023)
    document=f'''<!DOCTYPE html><html><head><meta charset="utf-8"><title>Relay reel</title>
<style>@font-face{{font-family:RelaySans;src:url(assets/font.ttf)}}
*{{box-sizing:border-box}}html,body{{width:100%;height:100%;margin:0;overflow:hidden}}
body{{font-family:RelaySans,sans-serif;background:{local['background']};color:{local['foreground']}}}
#reel,.clip,.panel{{position:absolute;inset:0;width:100%;height:100%}}
.panel{{padding:5%;display:flex;flex-direction:column;justify-content:center;gap:4%}}
img{{display:block;width:100%;height:54%;object-fit:contain;flex-shrink:0}}
.copy{{border-left:5px solid {local['accent']};padding-left:4%;max-height:90%}}
h1{{font-size:{font*1.5}px;line-height:1.1;margin:0 0 .45em;overflow-wrap:anywhere}}
p{{font-size:{font}px;line-height:1.25;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}
</style></head><body><main id="reel" data-no-timeline data-composition-id="reel" data-width="{width}" data-height="{height}" data-duration="{total}">
{''.join(scenes)}{audio}</main><script>{''.join(motions)}</script></body></html>'''
    (project/'index.html').write_text(document,encoding='utf-8')
    (project/'README.md').write_text('Editable HyperFrames '+media_host.VERSION+' composition. Open index.html with HyperFrames.\n'
        'composition.json records the scene plan; narration is metadata, not synthesized speech.\n'
        'Images use contain, with no crop. Rebuild/review after edits. Fonts/assets are bundled.\n',encoding='utf-8')
    return local


def verify_probe(probe,value):
    streams=probe.get('streams',[]);video=[s for s in streams if s.get('codec_type')=='video']
    audio=[s for s in streams if s.get('codec_type')=='audio'];duration=sum(s['duration'] for s in value['scenes'])
    if len(video)!=1:raise ValueError('Reel must have exactly one video stream')
    v=video[0]
    if (v.get('codec_name')!='h264' or v.get('width')!=value['width'] or v.get('height')!=value['height']
            or Fraction(v.get('avg_frame_rate','0/1'))!=value['fps'] or int(v.get('nb_frames',0))!=round(duration*value['fps'])
            or abs(float(probe['format']['duration'])-duration)>.25):raise ValueError('Encoded reel differs from dimensions, H.264, FPS, frame count or duration contract')
    if len(audio)!=int(value['audio'] is not None):raise ValueError('Encoded reel audio differs from the specification')
    return {'codec':'h264','width':v['width'],'height':v['height'],'fps':value['fps'],'frames':int(v['nb_frames']),
        'duration':float(probe['format']['duration']),'audio':bool(audio)}


def render(value,workspace,work,out,runtime,seconds,maximum):
    from PIL import Image,ImageOps,ImageDraw
    deadline=time.monotonic()+seconds
    work.mkdir();project=work/'project';local=compile_project(value,workspace,project,runtime)
    paths=runtime['paths'];count=0
    def run(command):
        nonlocal count
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('Reel task deadline exhausted')
        count+=1
        return media_host.run(runtime,work/('command-'+str(count)),command,work,remaining,
            # Intermediate frames/browser cache have a separate bounded allowance.
            max(10000000,maximum*3),output_root=out)
    def probe(path):return json.loads(run([paths['ffprobe'],'-v','error','-show_streams','-show_format','-of','json',str(path)]))
    if local['audio']:
        audio=probe(project/local['audio'])
        if (not any(s.get('codec_type')=='audio' for s in audio['streams'])
                or abs(float(audio['format']['duration'])-sum(s['duration'] for s in value['scenes']))>.25):
            raise ValueError('Supplied audio duration must match the scene timeline within 0.25 seconds')
    base=[paths['node'],paths['hyperframes']]
    run([*base,'check',str(project)])
    run([*base,'render',str(project),'--fps',str(value['fps']),'--quality','delivery','--strict',
         '--workers','1','--low-memory-mode','--output',str(out/'reel.mp4')])
    checks=verify_probe(probe(out/'reel.mp4'),value)
    frames=[];start=0
    for index,scene in enumerate(value['scenes']):
        moment=start+scene['duration']/2;target=work/f'scene-{index}.png'
        run([paths['ffmpeg'],'-v','error','-nostdin','-ss',str(moment),'-i',str(out/'reel.mp4'),
             '-frames:v','1','-vf','scale=240:-1','-threads','1',str(target)])
        with Image.open(target) as im:frames.append(im.convert('RGB').copy())
        start+=scene['duration']
    tile_height=frames[0].height+24;columns=min(4,len(frames));rows=(len(frames)+columns-1)//columns
    sheet=Image.new('RGB',(240*columns,tile_height*rows),'#181818');draw=ImageDraw.Draw(sheet)
    for index,im in enumerate(frames):
        x=index%columns*240;y=index//columns*tile_height;sheet.paste(im,(x,y))
        draw.text((x+5,y+im.height+3),f'Scene {index+1}',fill='white')
    sheet.save(out/'contact-sheet.png')
    with zipfile.ZipFile(out/'project.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(project.rglob('*')):
            if path.is_file():archive.write(path,str(path.relative_to(project)))
    checks.update(scene_samples=len(frames),visual_review='not_performed',narration_synthesized=False,
        source_crop='contain',files={name:file_hash(out/name) for name in ('reel.mp4','project.zip','contact-sheet.png')})
    return checks


def execute(frozen,control,documents):
    control=Path(control);workspace=Path(frozen['workspace']);out=workspace/'delivery'
    for name in ('reel_contract.py','reel_document.py'):
        if frozen['runtime_sources'].get(name)!=file_hash(Path(__file__).with_name(name)):
            raise ValueError('Reel implementation changed after dispatch')
    if frozen['runtime_sources'].get('task_relay/media_host.py')!=file_hash(Path(media_host.__file__)):
        raise ValueError('Media host implementation changed after dispatch')
    runtime=available()
    if runtime!=frozen.get('media_runtime'):raise ValueError('Media runtime changed after dispatch')
    manifest=next(d for d,i in zip(documents,frozen['inputs']) if i['media_type']=='application/json')
    value=contract.validate(contract.load(manifest['text']),{i['path']:i['media_type'] for i in frozen['inputs']})
    if out.exists() or out.is_symlink():raise ValueError('Reel delivery exists; no replacement or replay')
    receipt=dict(capability='media.compose',assignment=frozen['assignment_id'],passed=False,selected=False,
        runtime=runtime,limits=frozen['limits'],input_versions=[{k:i[k] for k in ('artifact','path','sha256')} for i in frozen['inputs']])
    with (control/'media-intent.json').open('x') as stream:json.dump(receipt,stream)
    out.mkdir();atomic(out/'verification.json',receipt)
    try:
        checks=render(value,workspace,control/'media-work',out,runtime,frozen['limits']['seconds'],frozen['limits']['output_bytes'])
        for item in frozen['inputs']:
            if file_hash(safe_file(workspace,item['path']))!=item['sha256']:raise ValueError('Reel source changed during rendering')
        receipt.update(passed=True,checks=checks,recorded_at=time.time());atomic(out/'verification.json',receipt)
        if sum(p.stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:
            raise ValueError('Reel delivery exceeds the total output byte budget')
    except Exception as exc:
        receipt.update(passed=False,error=str(exc),recorded_at=time.time());atomic(out/'verification.json',receipt)
        atomic(control/'operation.json',dict(outcome='failed',reason=str(exc),usage={},**receipt));raise
    summary='Local reel rendered and technically verified; independent review and human visual selection remain required.'
    details=dict(outcome='completed',execution=frozen['execution'],summary=summary,usage={},**receipt)
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',dict(assignment_id=frozen['assignment_id'],summary=summary,decision='delivered',
        instruction='',checks=[dict(criterion=1,passed=True,evidence='delivery/verification.json: '+summary)]))
    return details
