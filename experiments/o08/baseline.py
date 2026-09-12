"""Strong ordinary-script baseline with the same declared mechanical checks.

No model or lifecycle record is needed. Request validation is shared to avoid
handicapping baseline scope; file reads and result checks are independent.
"""
import hashlib
import json
from pathlib import Path
import stat
from experiments.o08.text_delivery import contract,MAX_BYTES


def check(root,request):
    try:contract(request)
    except (ValueError,TypeError):return {'decision':'unsupported','issues':[{'code':'contract'}],'files':[]}
    root=Path(root).absolute();issues=[];files=[];totals=[0,0]
    for group,items in enumerate((request['inputs'],request['outputs'])):
        for item in items:
            rel=item['path'];p=root/rel
            try:
                if any(part.is_symlink() for part in (p,*p.parents)):raise OSError()
                metadata=p.stat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1:raise OSError()
                with p.open('rb') as f:raw=f.read(MAX_BYTES+1)
            except OSError:issues.append({'code':'file','path':rel});continue
            if len(raw)>MAX_BYTES:issues.append({'code':'unsupported_size','path':rel});continue
            totals[group]+=len(raw);digest=hashlib.sha256(raw).hexdigest()
            files.append(dict(path=rel,sha256=digest,bytes=len(raw)))
            if group==0 and digest!=item['sha256']:issues.append({'code':'hash','path':rel})
            try:text=raw.decode('utf-8')
            except UnicodeError:issues.append({'code':'utf8','path':rel});continue
            if group==0:continue
            if not text.strip():issues.append({'code':'empty','path':rel})
            if item['format']=='json':
                def pairs(entries):
                    if len(dict(entries))!=len(entries):raise ValueError('Duplicate')
                    return dict(entries)
                def nonfinite(_):raise ValueError('Nonfinite')
                try:value=json.loads(text,object_pairs_hook=pairs,parse_constant=nonfinite)
                except (ValueError,RecursionError):issues.append({'code':'json','path':rel});continue
                if item['assignment_identity'] and (type(value)!=dict or value.get('assignment_id')!=request['assignment_id']):issues.append({'code':'identity','path':rel})
    if totals[0]>MAX_BYTES:issues.append({'code':'unsupported_size','path':'inputs'})
    if totals[1]>request['output_bytes']:issues.append({'code':'output_budget','path':'outputs'})
    codes={i['code'] for i in issues}
    return dict(decision='unsupported' if 'unsupported_size' in codes else ('reject' if codes else 'pass'),issues=issues,files=files)
