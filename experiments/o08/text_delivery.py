"""Candidate text.delivery-check v1; read-only, experimental, never an approval."""
import hashlib
import json
from pathlib import Path
import re
import stat

NAME='text.delivery-check'
VERSION=1
MAX_BYTES=2_000_000


def contract(value):
    if not isinstance(value,dict) or set(value)!={'version','assignment_id','inputs','outputs','output_bytes'}:
        raise ValueError('Unsupported request fields')
    if type(value['version']) is not int or value['version']!=VERSION:raise ValueError('Unsupported version')
    if not isinstance(value['assignment_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value['assignment_id']):raise ValueError('Invalid assignment identity')
    if type(value['output_bytes']) is not int or not 1<=value['output_bytes']<=MAX_BYTES:raise ValueError('Unsupported byte budget')
    paths=set()
    for kind,maximum,keys in [('inputs',20,{'path','sha256'}),('outputs',10,{'path','format','assignment_identity'})]:
        entries=value[kind]
        if not isinstance(entries,list) or not 1<=len(entries)<=maximum:raise ValueError('Unsupported file count')
        for entry in entries:
            if not isinstance(entry,dict) or set(entry)!=keys:raise ValueError('Unsupported file declaration')
            path=entry['path']
            if not isinstance(path,str) or not path or len(path)>512 or '\\' in path or path.startswith('/') or any(x in ('','..','.') for x in path.split('/')) or path.split('/')[0]=='.relay':raise ValueError('Unsupported path')
            if path in paths:raise ValueError('Duplicate input/output path')
            paths.add(path)
            if kind=='inputs':
                if not isinstance(entry['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',entry['sha256']):raise ValueError('Invalid SHA-256')
            elif entry['format'] not in ('text','json') or type(entry['assignment_identity']) is not bool or (entry['assignment_identity'] and entry['format']!='json'):
                raise ValueError('Unsupported output format or identity check')
    return value


def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    def invalid(_):raise ValueError('Nonfinite JSON value')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=invalid)


def read(root,path):
    current=Path(root).absolute()
    for ancestor in (current,*current.parents):
        if ancestor.is_symlink():raise OSError('Symlink workspace')
    for part in path.split('/'):
        current=current/part
        if current.is_symlink():raise OSError('Symlink input/output')
    info=current.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise OSError('Expected a regular unlinked file')
    with current.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise OverflowError('File exceeds supported size')
    return raw


def check(root,request):
    result={'procedure':NAME,'version':VERSION,'decision':'unsupported','issues':[],'files':[],
            'scope':'Mechanical text delivery checks only; semantic review and user selection remain separate.'}
    try:contract(request)
    except (ValueError,TypeError) as exc:
        result['issues'].append({'code':'contract','detail':str(exc)});return result
    total={'inputs':0,'outputs':0}
    for kind in ('inputs','outputs'):
        for item in request[kind]:
            path=item['path']
            try:raw=read(root,path)
            except OverflowError:
                result['issues'].append({'code':'unsupported_size','path':path});continue
            except OSError:
                result['issues'].append({'code':'file','path':path});continue
            total[kind]+=len(raw)
            digest=hashlib.sha256(raw).hexdigest()
            result['files'].append({'path':path,'sha256':digest,'bytes':len(raw)})
            if kind=='inputs' and digest!=item['sha256']:result['issues'].append({'code':'hash','path':path,'expected':item['sha256'],'observed':digest})
            try:text=raw.decode('utf-8')
            except UnicodeError:
                result['issues'].append({'code':'utf8','path':path});continue
            if kind=='inputs':continue
            if not text.strip():result['issues'].append({'code':'empty','path':path})
            if item['format']=='json':
                try:data=strict_json(text)
                except (ValueError,RecursionError):result['issues'].append({'code':'json','path':path});continue
                if item['assignment_identity'] and (not isinstance(data,dict) or data.get('assignment_id')!=request['assignment_id']):
                    result['issues'].append({'code':'identity','path':path})
    if total['inputs']>MAX_BYTES:result['issues'].append({'code':'unsupported_size','path':'inputs'})
    if total['outputs']>request['output_bytes']:result['issues'].append({'code':'output_budget','path':'outputs'})
    result['decision']='unsupported' if any(x['code']=='unsupported_size' for x in result['issues']) else ('reject' if result['issues'] else 'pass')
    return result


if __name__=='__main__':
    import sys
    print(json.dumps(check(sys.argv[1],json.loads(Path(sys.argv[2]).read_text())),indent=2))
