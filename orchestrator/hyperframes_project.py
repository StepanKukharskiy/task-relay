"""Shared check/snapshot/render operations for authored front-end projects."""
import html
import json
from pathlib import Path
import shutil
import stat
import time
import zipfile
from . import hyperframes_contract as contract
from .runtime import safe_file,file_hash
from .workers import atomic
from .reel_document import verify_probe
from task_relay import media_host


def available():
    from PIL import Image
    return media_host.available('project')


def inventory(folder):
    result={}
    for p in sorted(Path(folder).rglob('*')):
        if p.is_symlink():raise ValueError('Project contains a symbolic link')
        if p.is_file():
            if p.stat().st_nlink!=1:raise ValueError('Project contains a linked file')
            result[p.relative_to(folder).as_posix()]=file_hash(p)
    return result


def archive(folder,target):
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name in inventory(folder):z.write(Path(folder)/name,name)


def materialize(value,workspace,project,runtime):
    project.mkdir()
    for name,text in value['files'].items():
        target=project/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
    for name,source in value['assets'].items():
        target=project/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(safe_file(workspace,source),target)
    font=project/'assets/relay-font.ttf'
    if not font.exists():font.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(runtime['paths']['font'],font)
    atomic(project/'relay-project.json',value)
    return inventory(project)


def restore(bundle,receipt,project,maximum=75000000):
    """Consume exactly a passed preview bundle, not arbitrary ZIP executable/config files."""
    if (receipt.get('capability')!='hyperframes.preview' or receipt.get('passed') is not True
            or receipt.get('checks',{}).get('project_sha256')!=file_hash(bundle)):
        raise ValueError('Render requires the exact project ZIP from a passed preview receipt')
    expected=receipt['checks']['project_files'];project.mkdir();total=0;seen=set()
    if not isinstance(expected,dict) or not 1<=len(expected)<=82:raise ValueError('Invalid preview file inventory')
    with zipfile.ZipFile(bundle) as z:
        for item in z.infolist():
            name=item.filename
            if name!='relay-project.json':contract.path(name)
            if (item.is_dir() or name not in expected or name.casefold() in seen or item.flag_bits&1
                    or stat.S_ISLNK(item.external_attr>>16)):
                raise ValueError('Unexpected, duplicate, encrypted or linked project ZIP member')
            seen.add(name.casefold());total+=item.file_size
            if total>maximum:raise ValueError('Expanded project exceeds byte limit')
            target=project/name;target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as source,target.open('xb') as stream:
                remaining=item.file_size
                while block:=source.read(min(1024*1024,remaining+1)):
                    remaining-=len(block)
                    if remaining<0:raise ValueError('ZIP member exceeded its declared size')
                    stream.write(block)
            if file_hash(target)!=expected[name]:raise ValueError('Preview project file hash changed: '+name)
    if set(inventory(project))!=set(expected):raise ValueError('Preview project is missing files')
    value=contract.validate(contract.load((project/'relay-project.json').read_text()))
    required=set(value['files'])|set(value['assets'])|{'relay-project.json','assets/relay-font.ttf'}
    if set(expected)!=required:raise ValueError('Preview inventory differs from its authored project')
    for name,text in value['files'].items():
        if (project/name).read_bytes()!=text.encode():raise ValueError('Source in preview ZIP differs from authored manifest')
    return value


def envelope(source,target):
    """Preserve delivered source; apply resource policy only to the disposable runtime copy."""
    shutil.copytree(source,target)
    policy="default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    for path in target.rglob('*.html'):
        raw=path.read_text()
        # A policy before all author source cannot be relaxed by a later meta tag.
        path.write_text('<!DOCTYPE html><meta http-equiv="Content-Security-Policy" content="'+html.escape(policy,quote=True)+'">\n'+raw)


def sheet(paths,target,labels):
    from PIL import Image,ImageDraw,ImageOps
    columns=min(4,len(paths));tile=(240,450);rows=(len(paths)+columns-1)//columns
    result=Image.new('RGB',(columns*tile[0],rows*tile[1]),'#202020');draw=ImageDraw.Draw(result)
    for i,path in enumerate(paths):
        with Image.open(path) as im:thumb=ImageOps.contain(im.convert('RGB'),(240,420))
        x=(i%columns)*240;y=(i//columns)*450
        result.paste(thumb,(x+(240-thumb.width)//2,y));draw.text((x+6,y+426),labels[i],fill='white')
    result.save(target)


def run_project(value,source,work,out,runtime,seconds,maximum,*,render=False):
    from PIL import Image
    before=inventory(source);deadline=time.monotonic()+seconds;count=0
    project=work/'runtime-project';envelope(source,project);paths=runtime['paths']
    def run(command):
        nonlocal count
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('HyperFrames deadline exhausted')
        count+=1
        return media_host.run(runtime,work/('command-'+str(count)),command,work,remaining,max(50000000,maximum*3),output_root=out,isolated=True)
    base=[paths['node'],paths['hyperframes']]
    check=run([*base,'check',str(project),'--at',','.join(map(str,value['samples']))])
    # Full diagnostics survive even when the returned model-facing summary is bounded.
    (work/'check.log').write_text(check)
    frames=work/'frames';frames.mkdir()
    if render:
        run([*base,'render',str(project),'--fps',str(value['fps']),'--quality','delivery','--strict','--workers','1','--low-memory-mode','--output',str(out/'reel.mp4')])
        probe=json.loads(run([paths['ffprobe'],'-v','error','-show_streams','-show_format','-of','json',str(out/'reel.mp4')]))
        checks=verify_probe(probe,{**value,'audio':'present' if value['audio'] else None,'scenes':[{'duration':value['duration']}]})
        for i,t in enumerate(value['samples']):
            run([paths['ffmpeg'],'-v','error','-nostdin','-ss',str(t),'-i',str(out/'reel.mp4'),'-frames:v','1','-threads','1',str(frames/f'frame-{i:03}.png')])
    else:
        run([*base,'snapshot',str(project),'--at',','.join(map(str,value['samples'])),'--no-end','--describe','false','--output',str(frames)])
        checks={'check_passed':True,'width':value['width'],'height':value['height'],'fps':value['fps'],'duration':value['duration']}
    images=sorted(frames.rglob('*.png'))
    if len(images)!=len(value['samples']):raise ValueError('Snapshot count differs from the declared sample times')
    for image in images:
        with Image.open(image) as im:
            if im.size!=(value['width'],value['height']):raise ValueError('Preview/render sample dimensions differ from the project')
            im.verify()
    sheet(images,out/'contact-sheet.png',[str(t)+'s' for t in value['samples']])
    if not render:archive(frames,out/'frames.zip')
    if inventory(source)!=before:raise ValueError('Authored source changed during execution')
    checks.update(sample_times=value['samples'],project_files=before,visual_review='not_performed',
        check_log=check[-12000:],source_policy='Authored source preserved; disposable runtime HTML has an added resource policy.')
    return checks


def execute(frozen,control,documents):
    workspace=Path(frozen['workspace']);control=Path(control);out=workspace/'delivery';cap=frozen['execution']['capability']
    for module in (contract,__import__(__name__,fromlist=['']),media_host):
        key=('task_relay/' if module is media_host else '')+Path(module.__file__).name
        if frozen['runtime_sources'].get(key)!=file_hash(Path(module.__file__)):raise ValueError('HyperFrames implementation changed after dispatch')
    runtime=available()
    if runtime!=frozen.get('media_runtime'):raise ValueError('HyperFrames runtime changed after dispatch')
    if out.exists() or out.is_symlink():raise ValueError('Delivery exists; no replacement or replay')
    receipt=dict(capability=cap,assignment=frozen['assignment_id'],passed=False,selected=False,runtime=runtime,
        implementation=media_host.implementation(),input_versions=[{k:i[k] for k in ('artifact','path','sha256')} for i in frozen['inputs']],limits=frozen['limits'])
    with (control/'hyperframes-intent.json').open('x') as stream:json.dump(receipt,stream)
    out.mkdir();work=control/'hyperframes-work';work.mkdir();source=work/'source'
    atomic(out/'verification.json',receipt)
    try:
        if cap=='hyperframes.preview':
            manifest=next(d for d,i in zip(documents,frozen['inputs']) if i['media_type']=='application/json')
            value=contract.validate(contract.load(manifest['text']),{i['path']:i['media_type'] for i in frozen['inputs']})
            materialize(value,workspace,source,runtime)
            (out/'project.json').write_text(manifest['text'],encoding='utf-8')
            archive(source,out/'project.zip')
        else:
            params=frozen['execution']['parameters']
            bundle=next(i for i in frozen['inputs'] if i['media_type']=='application/zip')
            preview=next(i for i in frozen['inputs'] if i['media_type']=='application/json')
            if bundle['sha256']!=params['project_sha256'] or preview['sha256']!=params['preview_sha256']:
                raise ValueError('Render input hashes differ from the exact approved project and preview')
            prior=json.loads(safe_file(workspace,preview['path']).read_text())
            if prior.get('runtime')!=runtime or prior.get('implementation')!=media_host.implementation():
                raise ValueError('Preview used a different runtime/implementation; preview this source again before rendering')
            value=restore(safe_file(workspace,bundle['path']),prior,source)
            shutil.copyfile(safe_file(workspace,bundle['path']),out/'project.zip')
            receipt['preview_sha256']=preview['sha256']
        checks=run_project(value,source,work,out,runtime,frozen['limits']['seconds'],frozen['limits']['output_bytes'],render=cap=='hyperframes.render')
        for item in frozen['inputs']:
            if file_hash(safe_file(workspace,item['path']))!=item['sha256']:raise ValueError('HyperFrames input changed during execution')
        checks['project_sha256']=file_hash(out/'project.zip')
        checks['output_hashes']={p.name:file_hash(p) for p in out.iterdir() if p.name!='verification.json'}
        receipt.update(passed=True,checks=checks,recorded_at=time.time());atomic(out/'verification.json',receipt)
        if sum(p.stat().st_size for p in out.iterdir())>frozen['limits']['output_bytes']:raise ValueError('HyperFrames delivery exceeds its byte budget')
    except Exception as exc:
        receipt.update(passed=False,error=str(exc),recorded_at=time.time());atomic(out/'verification.json',receipt)
        atomic(control/'operation.json',dict(outcome='failed',reason=str(exc),usage={},**receipt));raise
    summary=cap+' completed for the exact authored project; independent review and human selection remain required.'
    details=dict(outcome='completed',summary=summary,execution=frozen['execution'],usage={},**receipt)
    atomic(control/'operation.json',details)
    atomic(workspace/'.relay/result.json',dict(assignment_id=frozen['assignment_id'],summary=summary,decision='delivered',instruction='',
        checks=[dict(criterion=1,passed=True,evidence='delivery/verification.json: '+summary)]))
    return details
