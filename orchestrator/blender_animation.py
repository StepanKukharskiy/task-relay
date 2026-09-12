"""Bounded native animation/rendering with explicit checkpoint continuation."""
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import zipfile

from .runtime import file_hash, safe_file
from .workers import atomic

SOURCES=('blender_animation.py','blender_animation_worker.py','blender_edit_worker.py','blender_snapshot.py')
DESCRIPTION={'version':1,'scene_sha256':'Exact selected .blend hash','mode':'preview or final',
 'frame_start':'Integer 1..100000','frame_end':'Inclusive, at most 120 frames','fps':'Integer 1..60',
 'camera':'Exact camera name','resolution':'Even integers 64..512 (preview) or 64..1024 (final)',
 'samples':'1..4 preview or 1..16 final',
 'tracks':'0..20 tracks: {object, property: location|rotation_euler|scale, keys:[{frame,value:[x,y,z]}]}. Linear interpolation, endpoint keys required, up to 20 keys per track. Empty tracks render existing animation.'}


def validate(m):
    if not isinstance(m,dict) or set(m)!=set(DESCRIPTION) or type(m['version']) is not int or m['version']!=1:
        raise ValueError('Use the version-1 animation manifest schema')
    if not isinstance(m['scene_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',m['scene_sha256']):raise ValueError('Select an exact scene hash')
    if m['mode'] not in ('preview','final'):raise ValueError('Choose preview or final')
    for k,lo,hi in [('frame_start',1,100000),('frame_end',1,100000),('fps',1,60),('samples',1,4 if m['mode']=='preview' else 16)]:
        if type(m[k]) is not int or not lo<=m[k]<=hi:raise ValueError('Invalid '+k)
    if not 1<=m['frame_end']-m['frame_start']+1<=120:raise ValueError('Render 1–120 contiguous frames')
    if not isinstance(m['camera'],str) or not 1<=len(m['camera'])<=200:raise ValueError('Select an exact camera')
    hi=512 if m['mode']=='preview' else 1024
    if not isinstance(m['resolution'],list) or len(m['resolution'])!=2 or any(type(n) is not int or n%2 or not 64<=n<=hi for n in m['resolution']):raise ValueError('Invalid even render dimensions')
    if not isinstance(m['tracks'],list) or len(m['tracks'])>20:raise ValueError('At most 20 transform tracks')
    seen=set()
    for t in m['tracks']:
        if not isinstance(t,dict) or set(t)!={'object','property','keys'}:raise ValueError('Invalid transform track')
        if not isinstance(t['object'],str) or not 1<=len(t['object'])<=200 or t['property'] not in ('location','rotation_euler','scale'):raise ValueError('Use named objects and transform properties only')
        identity=(t['object'],t['property'])
        if identity in seen:raise ValueError('Duplicate transform track')
        seen.add(identity);keys=t['keys']
        if not isinstance(keys,list) or not 1<=len(keys)<=20:raise ValueError('Use 1–20 keys per track')
        frames=[]
        for k in keys:
            if not isinstance(k,dict) or set(k)!={'frame','value'} or type(k['frame']) is not int:raise ValueError('Invalid keyframe')
            v=k['value'];lo=.001 if t['property']=='scale' else -10000
            if not isinstance(v,list) or len(v)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or not lo<=n<=10000 for n in v):raise ValueError('Invalid transform values')
            frames.append(k['frame'])
        if frames!=sorted(set(frames)) or frames[0]!=m['frame_start'] or frames[-1]!=m['frame_end']:raise ValueError('Ordered unique keys must include both frame endpoints')
    return m


def bind_registered(rt,spec):
    items=[{**i,**rt.artifact(i['artifact'])} for i in spec['inputs']]
    for i in items:
        if file_hash(i['blob'])!=i['sha256']:raise ValueError('Selected animation input changed')
    manifest=next(i for i in items if i['media_type']=='application/json')
    if manifest['sha256']!=spec['execution']['parameters']['manifest_sha256']:raise ValueError('Animation manifest hash mismatch')
    if manifest['bytes']>200000:raise ValueError('Animation manifest exceeds 200 KB')
    m=validate(json.loads(Path(manifest['blob']).read_text()))
    scene=next(i for i in items if i['media_type']=='application/x-blender')
    if scene['sha256']!=m['scene_sha256']:raise ValueError('Animation scene hash mismatch')
    for checkpoint in (i for i in items if i['media_type']=='application/zip'):
        parent=rt.db.execute('SELECT state,receipt,frozen FROM production_attempts WHERE id=?',(checkpoint['attempt'],)).fetchone()
        if not parent or checkpoint['path']!='delivery/checkpoint.zip' or parent['state'] not in ('blocked','cancelled','completed') or json.loads(parent['receipt'] or '{}').get('status')!='finished':
            raise ValueError('Checkpoint requires a confirmed stopped original animation attempt')
        frozen=json.loads(parent['frozen'])
        if frozen.get('execution',{}).get('capability')!='blender.animate' or frozen['execution']['parameters']['manifest_sha256']!=manifest['sha256']:
            raise ValueError('Checkpoint belongs to a different animation contract')
        with zipfile.ZipFile(checkpoint['blob']) as z:
            if z.getinfo('frames.json').file_size>200000:raise ValueError('Checkpoint receipt exceeds 200 KB')
            state=json.loads(z.read('frames.json'))
        if state.get('manifest_sha256')!=manifest['sha256'] or set(state.get('frames',{}))!={str(f) for f in range(m['frame_start'],m['frame_end']+1)}:
            raise ValueError('Checkpoint frame contract differs')
        if any(row.get('state') not in ('pending','completed') for row in state['frames'].values()):
            raise ValueError('Unresolved frame intent; inspect the original attempt before any retry')
    return m


def png(path,resolution):
    with path.open('rb') as f:header=f.read(24)
    if len(header)!=24 or header[:8]!=b'\x89PNG\r\n\x1a\n' or struct.unpack('>II',header[16:24])!=tuple(resolution):raise ValueError('Frame PNG dimensions/signature mismatch')
    return file_hash(path)


def checkpoint(root,out,state,limit):
    """Atomic snapshot. Unresolved intents are retained even if a process is killed."""
    atomic(root/'frames.json',state)
    files=['candidate.blend','checks.json','frames.json']+[v['path'] for v in state['frames'].values() if v['state']=='completed']
    files=[p for p in files if (root/p).is_file()]
    if sum(safe_file(root,p).stat().st_size for p in files)>limit//2:raise ValueError('Checkpoint retained-byte budget exceeded')
    tmp=out/'checkpoint.tmp'
    with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(safe_file(root,p),p)
    tmp.replace(out/'checkpoint.zip')


def restore(archive,root,manifest_hash,m,limit):
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist()
        if len(entries)>123 or len({i.filename for i in entries})!=len(entries) or sum(i.file_size for i in entries)>limit//2:raise ValueError('Invalid checkpoint size or duplicate files')
        for i in entries:
            if i.filename not in ('candidate.blend','checks.json','frames.json') and not re.fullmatch(r'frames/\d{6}\.png',i.filename):raise ValueError('Unexpected checkpoint path')
            if (i.external_attr>>16)&0o170000==0o120000:raise ValueError('Linked checkpoint entry')
            p=root/i.filename;p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('xb') as dst,z.open(i) as src:shutil.copyfileobj(src,dst)
    state=json.loads(safe_file(root,'frames.json').read_text())
    if state.get('manifest_sha256')!=manifest_hash or state.get('candidate_sha256')!=file_hash(safe_file(root,'candidate.blend')):raise ValueError('Checkpoint contract/candidate mismatch')
    if set(state.get('frames',{}))!={str(f) for f in range(m['frame_start'],m['frame_end']+1)}:raise ValueError('Checkpoint frame range mismatch')
    expected={'candidate.blend','checks.json','frames.json'}
    for f,row in state['frames'].items():
        if row.get('path')!=f'frames/{int(f):06d}.png':raise ValueError('Checkpoint frame path mismatch')
        if row['state']=='completed':
            expected.add(row['path'])
            if png(safe_file(root,row['path']),m['resolution'])!=row.get('sha256'):raise ValueError('Checkpoint frame hash mismatch')
        elif row['state']!='pending':raise ValueError('Unresolved frame intent; inspect the original attempt before any retry')
    if {i.filename for i in entries}!=expected:raise ValueError('Unlisted checkpoint data')
    return state


def execute(frozen,control,documents):
    from task_relay.host_apps import blender,video_tools
    control=Path(control);workspace=Path(frozen['workspace']);out=workspace/'delivery'
    for n in SOURCES:
        if frozen['runtime_sources'].get(n)!=file_hash(Path(__file__).with_name(n)):raise ValueError('Animation implementation changed after dispatch')
    if out.exists() or out.is_symlink():raise ValueError('Animation output exists; no replay')
    mi=next(i for i in frozen['inputs'] if i['media_type']=='application/json')
    if mi['sha256']!=frozen['execution']['parameters']['manifest_sha256']:raise ValueError('Manifest hash mismatch')
    mp=safe_file(workspace,mi['path'])
    if mp.stat().st_size>200000:raise ValueError('Manifest exceeds 200 KB')
    m=validate(json.loads(mp.read_text()));si=next(i for i in frozen['inputs'] if i['media_type']=='application/x-blender')
    if si['sha256']!=m['scene_sha256']:raise ValueError('Scene hash mismatch')
    apps=video_tools();app=blender()
    if not app['available'] or not apps['available']:raise ValueError('Blender, ffmpeg and ffprobe must be available')
    from task_relay.host_evidence import application_signature
    environment={'implementation':{n:frozen['runtime_sources'][n] for n in SOURCES},
                 'executables':{n:application_signature(p) for n,p in {'blender':app['executable'],'ffmpeg':apps['ffmpeg'],'ffprobe':apps['ffprobe']}.items()}}
    receipt={'assignment':frozen['assignment_id'],'capability':'blender.animate','manifest':m,'runs':[],'passed':False,'selected':False}
    with (control/'animation-intent.json').open('x') as f:json.dump(receipt,f)
    out.mkdir();root=control/'animation';root.mkdir();(root/'frames').mkdir()
    atomic(root/'manifest.json',m)
    deadline=time.monotonic()+max(1,frozen['limits']['seconds']-10)
    state=None
    def run(command,phase):
        if time.monotonic()>=deadline:raise ValueError('Time budget exhausted before '+phase)
        try:
            r=subprocess.run(command,cwd=workspace,stdin=subprocess.DEVNULL,capture_output=True,timeout=max(.1,deadline-time.monotonic()))
            result={'phase':phase,'command':command,'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace')[-32000:],'stderr':r.stderr.decode(errors='replace')[-32000:]}
        except subprocess.TimeoutExpired as e:
            result={'phase':phase,'command':command,'returncode':None,'timeout':True,'stdout':(e.stdout or b'').decode(errors='replace')[-32000:],'stderr':(e.stderr or b'').decode(errors='replace')[-32000:]}
        receipt['runs'].append(result);atomic(out/'execution.json',receipt)
        if result['returncode']!=0:raise ValueError('Animation process failed or timed out: '+phase)
        return result
    def native(mode,frame='0'):
        r=run([app['executable'],'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(Path(__file__).with_name('blender_animation_worker.py')),'--',mode,str(safe_file(workspace,si['path'])),str(root),str(frame)],mode+':'+str(frame))
        if 'RELAY_ANIMATION_OK' not in r['stdout']:raise ValueError('Native animation marker missing')
    try:
        cp=next((i for i in frozen['inputs'] if i['media_type']=='application/zip'),None)
        if cp:
            state=restore(safe_file(workspace,cp['path']),root,mi['sha256'],m,frozen['limits']['output_bytes'])
            if state.get('environment')!=environment:raise ValueError('Checkpoint implementation or executable identity changed')
        else:
            native('build')
            state={'version':1,'environment':environment,'manifest_sha256':mi['sha256'],'candidate_sha256':file_hash(safe_file(root,'candidate.blend')),
                   'frames':{str(f):{'path':f'frames/{f:06d}.png','state':'pending'} for f in range(m['frame_start'],m['frame_end']+1)}}
        native('verify')
        if json.loads(safe_file(root,'checks.json').read_text()).get('passed') is not True:raise ValueError('Candidate verification failed')
        shutil.copyfile(root/'candidate.blend',out/'candidate.blend')
        checkpoint(root,out,state,frozen['limits']['output_bytes'])
        for f,row in state['frames'].items():
            if row['state']=='completed':continue
            if time.monotonic()>=deadline:raise ValueError('Time budget exhausted; remaining frames are pending')
            row.update(state='in_progress',attempt=frozen['assignment_id']);checkpoint(root,out,state,frozen['limits']['output_bytes'])
            native('frame',f)
            row.update(state='completed',sha256=png(safe_file(root,row['path']),m['resolution']))
            checkpoint(root,out,state,frozen['limits']['output_bytes'])
        run([apps['ffmpeg'],'-nostdin','-v','error','-n','-framerate',str(m['fps']),'-start_number',str(m['frame_start']),'-i',str(root/'frames/%06d.png'),'-frames:v',str(len(state['frames'])),'-an','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-movflags','+faststart',str(out/'animation.mp4')],'encode')
        r=run([apps['ffprobe'],'-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=width,height,nb_read_frames,r_frame_rate','-of','json',str(out/'animation.mp4')],'verify_video')
        streams=json.loads(r['stdout'])['streams']
        from fractions import Fraction
        if len(streams)!=1 or [streams[0]['width'],streams[0]['height']]!=m['resolution'] or int(streams[0]['nb_read_frames'])!=len(state['frames']) or Fraction(streams[0]['r_frame_rate'])!=m['fps']:raise ValueError('Encoded video verification failed')
        if any(file_hash(safe_file(workspace,i['path']))!=i['sha256'] for i in frozen['inputs']):raise ValueError('Original input copy changed')
        shutil.copyfile(root/f'frames/{m["frame_start"]:06d}.png',out/'preview.png')
        receipt['passed']=True
    except (ValueError,OSError,KeyError,zipfile.BadZipFile) as e:receipt['error']=str(e)
    if state:
        try:checkpoint(root,out,state,frozen['limits']['output_bytes'])
        except (ValueError,OSError) as e:receipt.update(passed=False,error=str(e))
        atomic(out/'frames.json',state)
    if (root/'checks.json').is_file():receipt['checks']=json.loads((root/'checks.json').read_text())
    receipt['recorded_at']=time.time();atomic(out/'execution.json',receipt)
    if sum(p.stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:
        receipt.update(passed=False,error='Retained output budget exceeded');atomic(out/'execution.json',receipt)
    passed=receipt['passed'];summary='Animated candidate reopened and verified; exact frames rendered and encoded. Candidate is unselected.' if passed else 'Animation blocked: '+receipt['error']+'. No automatic retry.'
    details={'outcome':'completed' if passed else 'failed','execution':frozen['execution'],'summary':summary,'usage':{}}
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',{'assignment_id':frozen['assignment_id'],'summary':summary,'decision':'delivered' if passed else 'blocked','instruction':'','checks':[{'criterion':1,'passed':passed,'evidence':'delivery/frames.json and delivery/execution.json'}]})
    return details
