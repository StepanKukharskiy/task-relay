"""Hash-bound compatible rendering of an exact native PPTX for independent review."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import zipfile

MIME='application/vnd.openxmlformats-officedocument.presentationml.presentation'
OUTPUTS={'delivery/preview.pdf':'application/pdf','delivery/slide-previews.zip':'application/zip','delivery/render.json':'application/json'}


def evidence_views(rt,items):
    """Existing registered renders expose exact PDF/deck evidence as page pixels.

    Never substitute another version or import a sibling outside assigned scope.
    The completed native receipt binds both output hashes and the source candidate.
    """
    sources={i['artifact']:i for i in items if i.get('artifact')};result={}
    for aid,item in sources.items():
        if item.get('media_type')!='application/zip':continue
        artifact=rt.artifact(aid)
        row=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(artifact['attempt'],)).fetchone()
        if not row:continue
        frozen=json.loads(row['frozen']);receipt=json.loads(row['receipt'] or '{}')
        if frozen.get('work_tools'):
            from .worker_tools import inspection_evidence
            proof=inspection_evidence(rt,row,'pptx.render')
            if proof is None:continue
        else:
            if frozen.get('execution',{}).get('capability')!='pptx.render' or row['state']!='completed':continue
            op=receipt.get('operation',{});proof=op.get('validation',{})
            if op.get('outcome')!='completed':continue
        if proof.get('outputs',{}).get(artifact['path'],{}).get('sha256')!=artifact['sha256']:continue
        if hashlib.sha256(Path(artifact['blob']).read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('Saved render representation changed')
        for ident,source in sources.items():
            value=rt.artifact(ident)
            same_output=(value['attempt']==artifact['attempt'] and
                proof.get('outputs',{}).get(value['path'],{}).get('sha256')==value['sha256'])
            exact_candidate=proof.get('candidate_artifact')==ident and proof.get('candidate_sha256')==value['sha256']
            if proof.get('candidate_path'):
                exact_candidate=(value['attempt']==artifact['attempt'] and value['path']==proof['candidate_path'] and value['sha256']==proof['candidate_sha256'])
            if not (same_output or exact_candidate) or source.get('media_type') not in (MIME,'application/pdf'):continue
            if hashlib.sha256(Path(value['blob']).read_bytes()).hexdigest()!=value['sha256']:raise ValueError('Saved render source changed')
            result[source['path']]=dict(tool='image_view',path=item['path'],proof=dict(
                artifact=ident,sha256=value['sha256'],representation=aid,representation_sha256=artifact['sha256'],
                renderer_attempt=artifact['attempt'],candidate_artifact=proof.get('candidate_artifact'),candidate_path=proof.get('candidate_path'),candidate_sha256=proof['candidate_sha256']))
    return result


def execute(frozen,control):
    from task_relay import presentation_host
    from .runtime import safe_file,file_hash
    from .workers import atomic
    from . import contracts as c
    binding=frozen['presentation_runtime'];presentation_host.verify(binding)
    workspace=Path(frozen['workspace']);source=frozen['inputs'][0]
    path=safe_file(workspace,source['path'])
    if file_hash(path)!=source['sha256']:raise ValueError('Presentation candidate changed before rendering')
    with zipfile.ZipFile(path) as package:
        pages=[n for n in package.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml') and '/' not in n[len('ppt/slides/'):]]
    if not 1<=len(pages)<=100:raise ValueError('Presentation preview supports 1–100 bounded slides')
    deadline=time.monotonic()+frozen['limits']['seconds'];started=time.time();receipts=[]
    with tempfile.TemporaryDirectory(prefix='relay-presentation-') as tmp:
        directory=Path(tmp);copy=directory/'candidate.pptx';copy.write_bytes(path.read_bytes());output=directory/'preview';output.mkdir()
        tools=binding['tools']
        pdf=output/'candidate.pdf'
        renderers=[tools['soffice'],*binding.get('alternatives',[])]
        for index,renderer in enumerate(renderers):
            if pdf.exists():pdf.unlink()
            command=[renderer['path'],'--headless','-env:UserInstallation='+(directory/('profile-'+str(index))).as_uri(),'--convert-to','pdf','--outdir',str(output),str(copy)]
            try:
                receipts.append(presentation_host.invoke(command,min(90,deadline-time.monotonic()-30),cwd=tmp))
                if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):raise ValueError('Renderer produced no valid PDF')
            except (ValueError,OSError) as exc:
                receipts.append(dict(getattr(exc,'receipt',dict(command=command,exit_code=None)),error=str(exc)))
                atomic(Path(control)/'presentation-render.json',dict(candidate_sha256=source['sha256'],commands=receipts,complete=False))
                if index+1==len(renderers):raise
            else:break
        if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):raise ValueError('Renderer produced no valid PDF')
        receipts.append(presentation_host.invoke([tools['pdftoppm']['path'],'-png','-r','96',str(pdf),str(output/'slide')],
            deadline-time.monotonic(),cwd=tmp))
        previews=sorted(output.glob('slide-*.png'))
        if len(previews)!=len(pages):raise ValueError('Rendered page count differs from candidate slide count')
        from .browser_contract import png_info
        records=[];buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_STORED) as archive:
            for number,png in enumerate(previews,1):
                raw=png.read_bytes();info=png_info(raw);name=f'slide-{number:03d}.png';archive.writestr(name,raw)
                records.append(dict(slide=number,path=name,sha256=hashlib.sha256(raw).hexdigest(),**info))
        content={'delivery/preview.pdf':pdf.read_bytes(),'delivery/slide-previews.zip':buffer.getvalue()}
        report=dict(version=1,kind='compatible-presentation-render',candidate_sha256=source['sha256'],
                    candidate_artifact=source['artifact'],renderer=binding,slide_count=len(pages),pages=records,commands=receipts,
                    started_at=started,finished_at=time.time(),visual_review=False,
                    limitations=['Compatible LibreOffice opening/rendering; no PowerPoint or Keynote compatibility claim.','Layout and source correspondence require independent inspection.'])
        report['outputs']={name:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for name,raw in content.items()}
        content['delivery/render.json']=(c.encoded(report)+'\n').encode()
        if sum(map(len,content.values()))>frozen['limits']['output_bytes']:raise ValueError('Presentation previews exceed output limit')
        if file_hash(path)!=source['sha256']:raise ValueError('Presentation source changed during rendering')
        for name,raw in content.items():
            target=workspace/name;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
        details=dict(outcome='completed',execution=frozen['execution'],validation=report,usage={},output_sha256=report['outputs']['delivery/preview.pdf']['sha256'])
        atomic(Path(control)/'operation.json',details)
        atomic(workspace/'.relay/result.json',dict(assignment_id=frozen['assignment_id'],summary='Exact PPTX opened and all slides rendered by compatible application.',
            decision='delivered',instruction='',checks=[dict(criterion=1,passed=True,evidence=c.encoded(report['outputs']))]))
        return details
