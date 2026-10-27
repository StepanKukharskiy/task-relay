"""Bounded, read-only evidence of failed registered work, never delivery authority."""
import hashlib
import json
from pathlib import Path
from . import contracts as c

OUTPUT = dict(path='outputs/work-diagnostics.json', media_type='application/json',
              purpose='Code-owned operation diagnostics; partial files are not accepted outputs')


def capture(folder, sub, operation, error, maximum):
    """Only exact declared outputs and fixed execution journals can enter a capsule."""
    from .runtime import safe_file
    result = dict(operation=operation, error=str(error), assignment_sha256=c.digest(sub),
                  execution=sub['execution'], inputs=sub['inputs'], files=[])
    candidates = [('control', name) for name in ('operation.json', 'runtime.log')]
    candidates += [('workspace', o['path']) for o in sub['outputs']]
    text_left = max(0, maximum // 2)
    for origin, path in candidates:
        root = folder if origin == 'control' else folder/'workspace'
        try:
            file = safe_file(root, path)
        except (ValueError, OSError):
            result['files'].append(dict(origin=origin, path=path, available=False))
            continue
        # Stream hashing avoids loading a large failed native file into memory.
        digest=hashlib.sha256();size=0;prefix=b''
        with file.open('rb') as stream:
            while chunk := stream.read(65536):
                digest.update(chunk);size+=len(chunk)
                if len(prefix)<min(16384,text_left):prefix+=(chunk[:min(16384,text_left)-len(prefix)])
        item=dict(origin=origin,path=path,available=True,bytes=size,sha256=digest.hexdigest())
        try:
            text=prefix.decode('utf-8')
            # An incomplete final codepoint does not authorize binary-to-text coercion.
            if b'\x00' in prefix:raise UnicodeError('binary')
            item.update(text=text,truncated=len(prefix)<size);text_left-=len(prefix)
        except UnicodeError:item['representation']='identity-only; binary or non-UTF-8 bytes'
        result['files'].append(item)
    return result


def verify(folder, detail):
    from .runtime import safe_file,file_hash
    root=folder/'workspace'
    assignment=root/'.relay/ASSIGNMENT.json'
    if root.is_symlink() or assignment.parent.is_symlink() or assignment.is_symlink():
        raise ValueError('Diagnostic assignment is linked')
    sub=json.loads(assignment.read_text())
    if c.digest(sub)!=detail['assignment_sha256']:raise ValueError('Diagnostic assignment changed')
    allowed={('control','operation.json'),('control','runtime.log')}
    allowed|={('workspace',o['path']) for o in sub['outputs']}
    for item in detail['files']:
        if (item['origin'],item['path']) not in allowed:raise ValueError('Diagnostic path exceeds operation scope')
        if not item['available']:continue
        file=safe_file(folder if item['origin']=='control' else folder/'workspace',item['path'])
        if file.stat().st_size!=item['bytes'] or file_hash(file)!=item['sha256']:
            raise ValueError('Committed diagnostic evidence changed')


def document(frozen, receipts):
    entries=[]
    for folder,intent,receipt in receipts:
        if not receipt.get('diagnostics'):continue
        verify(folder,receipt['diagnostics'])
        entries.append(dict(version=folder.name,step=intent['step'],request_key=intent['request_key'],
                            status=receipt['status'],effect='confirmed',**receipt['diagnostics']))
    preparation=frozen.get('operation_contract')
    schema=None
    if preparation and preparation['id']=='operation.preparation':
        from .prepared_contract import definition
        schema=definition(preparation['parameters'])['schema']
    return dict(version=1,assignment=frozen['assignment_id'],binding=c.digest(frozen),
                preparation_contract=preparation,preparation_schema=schema,
                authority='Diagnostic evidence only; no acceptance, replay permission or additional authority.',
                failures=entries)


def encoded(frozen, receipts):
    return (c.encoded(document(frozen,receipts))+'\n').encode()


def verify_projection(frozen, control):
    """Read-only collection check before a diagnostic artifact can be handed off."""
    if not frozen.get('work_tools',{}).get('diagnostics'):return
    from .runtime import safe_file
    receipts=[]
    for folder in sorted((Path(control)/'work-operations').iterdir()):
        if not (folder/'outcome.json').exists():continue
        intent=json.loads((folder/'intent.json').read_text())
        if intent['binding']!=c.digest(frozen):raise ValueError('Diagnostic journal belongs to another assignment')
        receipts.append((folder,intent,json.loads((folder/'outcome.json').read_text())))
    actual=safe_file(Path(frozen['workspace']),OUTPUT['path']).read_bytes()
    if actual!=encoded(frozen,receipts):raise ValueError('Diagnostic projection differs from committed evidence')
