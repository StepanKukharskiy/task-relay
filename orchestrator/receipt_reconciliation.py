"""Separate confirmed operation responses from later local cleanup failures.

Provider adapters supply correlated terminal identities and validated results.
This module never retries, infers acceptance or reconstructs a missing response.
"""
import hashlib,json
from .workers import atomic


def commit(control,request_id,terminal,result,pending=(),evidence=(),scope=None):
    if (not request_id or not isinstance(terminal,dict)
            or terminal.get('id')!=request_id
            or terminal.get('status') not in ('completed','failed','cancelled','rejected')
            or pending):
        raise ValueError('A result requires a correlated terminal with no pending effects')
    data=dict(version=1,request_id=request_id,scope=scope,terminal=terminal,result=result,
              evidence=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in evidence],
              acceptance=False,replayed=False)
    path=control/'confirmed-response.json'
    atomic(path,data)
    receipt=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    atomic(control/'confirmed-response-receipt.json',receipt)
    return receipt


def confirmed(receipt):
    if not receipt:return False
    from pathlib import Path
    path=Path(receipt['path']);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:return False
    data=json.loads(raw)
    if any(hashlib.sha256(Path(v['path']).read_bytes()).hexdigest()!=v['sha256'] for v in data.get('evidence',[])):return False
    return (data.get('version')==1 and data.get('request_id')==data.get('terminal',{}).get('id')
            and data['terminal'].get('status') in ('completed','failed','cancelled','rejected'))


def restore(control):
    receipt=json.loads((control/'confirmed-response-receipt.json').read_text())
    if not confirmed(receipt):raise ValueError('Confirmed response or its original evidence changed')
    from pathlib import Path
    return json.loads(Path(receipt['path']).read_text())


def cleanup(control,actions,receipt=None,*,preserve_error=False):
    """Attempt all cleanup, retain its diagnostics, preserve a confirmed response.

    An exception from the request body takes precedence over cleanup. Otherwise
    a cleanup error without a confirmed receipt still propagates as uncertainty.
    """
    errors=[]
    for name,action in actions:
        try:action()
        except Exception as exc:
            errors.append((name,exc))
    if not errors:return
    saved=confirmed(receipt) if receipt else False
    atomic(control/'cleanup-outcome.json',dict(version=1,
        errors=[dict(action=name,type=type(exc).__name__,message=str(exc)) for name,exc in errors],
        confirmed_response=receipt if saved else None,body_error_preserved=preserve_error,
        response_preserved=saved,replayed=False,acceptance=False))
    if not saved and not preserve_error:raise errors[0][1]
