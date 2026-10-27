"""Explicit, bounded abandonment of tool-free timed-out generations.

The remote generation and its usage remain unknown. Only a new generation from
confirmed local history is authorized; no external action is replayed.
"""
import hashlib
import json
from pathlib import Path

from . import contracts as c, executors
from .workers import atomic


def validate(policy):
    if (not isinstance(policy,dict) or set(policy)!={'version','max_retries'}
            or type(policy['version']) is not int or policy['version']!=1
            or type(policy['max_retries']) is not int or not 1<=policy['max_retries']<=2):
        raise ValueError('Generation recovery requires an explicit allowance of 1–2 timed-out generations')
    return policy


def eligible(backend,request,outcome):
    if backend.get('type') not in (*executors.FILE_TYPES,*executors.CODE_TYPES):return False
    provider=executors.provider_for(backend);payload=request.get('payload',{})
    if (request.get('provider')!=provider or request.get('model')!=backend['model']
            or outcome.get('outcome')!='uncertain' or outcome.get('http_status') is not None
            or outcome.get('provider_error',{}).get('failure_kind')!='timeout'):return False
    tools=payload.get('tools')
    if not isinstance(tools,list) or not tools:return False
    if provider=='gemini':
        return (request.get('endpoint')=='models/'+backend['model']+':generateContent'
                and all(isinstance(t,dict) and set(t)=={'functionDeclarations'} and isinstance(t['functionDeclarations'],list) for t in tools))
    if any(not isinstance(t,dict) or t.get('type')!='function' for t in tools):return False
    if provider=='openai':return request.get('endpoint')=='responses' and payload.get('store') is False and not payload.get('background')
    return request.get('endpoint')=='chat/completions' and payload.get('stream') is False


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def record(control,stem,frozen,number,used,remaining_seconds):
    """Called synchronously after timeout, before considering another request."""
    policy=frozen.get('generation_recovery')
    if not policy:return False
    validate(policy);control=Path(control)
    request=control/(stem+'.request.json');outcome=control/(stem+'.outcome.json')
    if (used>=policy['max_retries'] or number>=executors.request_limit(frozen)
            or remaining_seconds<=2 or (control/'cancel.json').exists()
            or any(not p.with_name('outcome.json').exists() for p in control.glob('code-*/intent.json'))
            or not eligible(frozen['backend'],json.loads(request.read_text()),json.loads(outcome.read_text()))):return False
    atomic(control/(stem+'.recovery.json'),dict(kind='authorized_generation_timeout',version=1,
        assignment_id=frozen['assignment_id'],policy_sha256=c.digest(policy),request_sha256=sha(request),
        outcome_sha256=sha(outcome),retry_ordinal=used+1,request_number=number,
        remaining_requests=executors.request_limit(frozen)-number,executed_calls=0,
        remote_generation='unknown',provider_usage='unknown',continued=True))
    return True


def abandoned(control,stem,session,ordinal):
    """Verify the receipt against the trusted dispatch grant and exact journals."""
    control=Path(control)
    try:
        policy=validate(session.get('generation_recovery'))
        request=control/(stem+'.request.json');outcome=control/(stem+'.outcome.json')
        saved=json.loads((control/(stem+'.recovery.json')).read_text())
        number=int(stem.removeprefix('api-'));limit=session['provider_requests']
        return (1<=ordinal<=policy['max_retries'] and 1<=number<limit
            and saved==dict(kind='authorized_generation_timeout',version=1,
                assignment_id=session['id'],policy_sha256=c.digest(policy),request_sha256=sha(request),
                outcome_sha256=sha(outcome),retry_ordinal=ordinal,request_number=number,
                remaining_requests=limit-number,executed_calls=0,
                remote_generation='unknown',provider_usage='unknown',continued=True)
            and eligible(session['backend'],json.loads(request.read_text()),json.loads(outcome.read_text())))
    except (OSError,ValueError,TypeError,KeyError):return False
