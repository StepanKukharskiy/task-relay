"""Discover and invoke compatible presentation tools through the host boundary."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


def discover(required=None):
    if sys.platform not in ('darwin','linux','win32'):
        raise ValueError('No compatible presentation renderer on this host')
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override'
    candidates={
        'soffice':[os.environ.get('TASK_RELAY_SOFFICE'),shutil.which('soffice'),shutil.which('libreoffice'),
                   str(bundled/'soffice'),'/Applications/LibreOffice.app/Contents/MacOS/soffice',
                   '/Applications/LibreOfficeDev.app/Contents/MacOS/soffice'],
        'pdftoppm':[os.environ.get('TASK_RELAY_PDFTOPPM'),shutil.which('pdftoppm'),str(bundled/'pdftoppm')]}
    tools={}
    alternatives=[]
    for name,paths in candidates.items():
        if required is not None and name not in required:continue
        found=[]
        for value in paths:
            if value and Path(value).is_file() and os.access(value,os.X_OK):
                path=Path(value).absolute()
                if str(path) not in {p['path'] for p in found}:found.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        if found:tools[name]=found[0]
        if name=='soffice':alternatives=found[1:2]
        if name not in tools:raise ValueError('Compatible presentation preview requires '+name+'; no tool was installed or launched')
    return {'platform':sys.platform,'tools':tools,'alternatives':alternatives,'basis':'available-executable-presence; actual opening requires execution'}


def verify(binding):
    if binding.get('platform')!=sys.platform:raise ValueError('Presentation host changed after dispatch')
    for tool in [*binding['tools'].values(),*binding.get('alternatives',[])]:
        if not os.access(tool['path'],os.X_OK) or hashlib.sha256(Path(tool['path']).read_bytes()).hexdigest()!=tool['sha256']:
            raise ValueError('Presentation renderer changed after dispatch')


class RenderFailure(ValueError):
    def __init__(self,message,receipt):super().__init__(message);self.receipt=receipt


def invoke(command,timeout,*,cwd):
    from .host import HOST
    if timeout<=0:raise ValueError('Presentation render deadline exhausted')
    process=HOST.spawn(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:out,err=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        HOST.stop_tree(process);raise RenderFailure('Owned presentation renderer exceeded its deadline',dict(command=command,exit_code=None,owned_process_stopped=True,reason='deadline'))
    receipt={'command':command,'exit_code':process.returncode,'stdout':out.decode(errors='replace')[-4000:],
             'stderr':err.decode(errors='replace')[-4000:]}
    if process.returncode:raise RenderFailure('Presentation renderer failed: '+str(process.returncode)+' '+receipt['stderr'][:800],receipt)
    return receipt


def preview_pdf_page(content,page=1):
    """Display-only raster of one saved PDF page; no scripts or document writes."""
    import base64,io,tempfile
    from pypdf import PdfReader
    from PIL import Image
    if type(page) is not int or page<1:raise ValueError('Choose a positive PDF page number')
    reader=PdfReader(io.BytesIO(content))
    if reader.is_encrypted:raise ValueError('Encrypted PDF cannot be previewed')
    count=len(reader.pages)
    if page>count or count>500:raise ValueError('PDF preview supports 1–500 pages')
    binding=discover(required={'pdftoppm'});verify(binding)
    with tempfile.TemporaryDirectory(prefix='relay-pdf-preview-') as tmp:
        folder=Path(tmp);source=folder/'saved.pdf';source.write_bytes(content)
        invoke([binding['tools']['pdftoppm']['path'],'-f',str(page),'-l',str(page),
            '-singlefile','-scale-to','1280','-jpeg',str(source),str(folder/'page')],20,cwd=tmp)
        with Image.open(folder/'page.jpg') as image:
            image.thumbnail((1280,1280));out=io.BytesIO();image.convert('RGB').save(out,format='JPEG',quality=75)
        data=out.getvalue()
        if len(data)>650000:raise ValueError('PDF page exceeds inline preview size')
    return dict(media_type='application/pdf',page=page,pages=count,
        data_url='data:image/jpeg;base64,'+base64.b64encode(data).decode(),
        transformation='Read-only page preview; original PDF unchanged.')
