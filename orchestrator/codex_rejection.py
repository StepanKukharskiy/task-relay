"""Read-only proof of a terminal CLI provider rejection, shared by transports.

A process exit or error message alone proves nothing. Require the dispatched
thread/turn, a non-retrying structured client error and its matching failed
terminal event, with no executed or requested tool in that session. Raw journals
remain immutable. Usage is deliberately not inferred from rejection.
"""
import hashlib
import json
from pathlib import Path

CLIENT_ERRORS=frozenset((400,401,402,403,404,405,422,429))


def generation_unavailable(control, thread, turn):
    """Prove failed generation after local tools or before any search tool.

    The caller has received the terminal event with no pending tool response.
    Match every prior dynamic request to its exact sent response. Started native/server
    tools, permissions, missing replies and ambiguous terminals stay uncertain.
    """
    from .codex_transport import PASSIVE_ITEMS
    try:
        data={name:(Path(control)/name).read_bytes() for name in ('codex-sent.jsonl','codex-events.jsonl')}
        if any(len(value)>20_000_000 for value in data.values()):return None
        sent=[json.loads(line) for line in data['codex-sent.jsonl'].splitlines()]
        events=[json.loads(line) for line in data['codex-events.jsonl'].splitlines()]
        starts=[s for s in sent if s.get('method')=='thread/start']
        if len(starts)!=1:return None
        start=starts[0];params=start['params']
        search_only=params['config'].get('web_search')=='live' and params['dynamicTools']==[]
        if not search_only and params['config'].get('web_search')!='disabled':return None
        names={t['name'] for t in params['dynamicTools'] if t.get('type')=='function'}
        if not search_only and (not names or len(names)!=len(params['dynamicTools'])):return None
        replies=[e for e in events if e.get('id')==start['id'] and 'result' in e]
        if len(replies)!=1 or replies[0]['result']['thread']['id']!=thread:return None
        turns=[s for s in sent if s.get('method')=='turn/start' and s['params']['threadId']==thread]
        matches=[s for s in turns if any(e.get('id')==s['id'] and e.get('result',{}).get('turn',{}).get('id')==turn for e in events)]
        if len(matches)!=1 or matches[0]['params']['model']!=params['model']:return None
        allowed_items=PASSIVE_ITEMS if search_only else PASSIVE_ITEMS|{'dynamicToolCall'}
        errors=[];terminals=[];seen=set();calls=[]
        for event in events:
            method=event.get('method');p=event.get('params',{})
            if method and 'id' in event:
                if (method!='item/tool/call' or p.get('threadId')!=thread or p.get('namespace') is not None
                        or p.get('tool') not in names or not isinstance(p.get('arguments'),dict)):return None
                identity=p['callId']
                if identity in seen:return None
                seen.add(identity)
                answers=[s for s in sent if s.get('id')==event['id'] and not s.get('method')]
                if len(answers)!=1 or answers[0].get('result',{}).get('success') is not True:return None
                if not isinstance(answers[0]['result'].get('contentItems'),list):return None
                calls.append(identity)
            if method in ('item/started','item/completed'):
                if p.get('threadId')!=thread or p.get('item',{}).get('type') not in allowed_items:return None
            if method=='error' and p.get('turnId')==turn:
                if p.get('threadId')!=thread or type(p.get('willRetry')) is not bool:return None
                errors.append(p)
            if method=='turn/completed' and p.get('turn',{}).get('id')==turn:
                if p.get('threadId')!=thread:return None
                terminals.append(p['turn'])
        if not errors or len(terminals)!=1:return None
        if errors[-1]['willRetry'] is not False or any(e['willRetry'] is not True for e in errors[:-1]):return None
        error=errors[-1]['error']
        terminal=terminals[0]
        if terminal.get('status')!='failed' or terminal.get('error')!=error:return None
        info=error.get('codexErrorInfo')
        limited=(isinstance(info,dict) and set(info)=={'responseTooManyFailedAttempts'}
                 and info['responseTooManyFailedAttempts'].get('httpStatusCode') in (429,503))
        if info!='serverOverloaded' and not limited:return None
        if any(i.get('type') not in allowed_items for i in terminal.get('items',[])):return None
        limits=[e.get('params',{}).get('rateLimits',{}) for e in events if e.get('method')=='account/rateLimits/updated']
        latest=limits[-1] if limits else {}
        exhausted=bool(latest.get('rateLimitReachedType') or latest.get('spendControlReached') or any(
            (latest.get(k) or {}).get('usedPercent',0)>=100 for k in ('primary','secondary')))
        status=info['responseTooManyFailedAttempts']['httpStatusCode'] if limited else 'serverOverloaded'
        return dict(version=1,status=status,quota_exhausted=exhausted,
            retry_exhausted=limited,failure_kind='rate_limited' if status==429 else 'service_unavailable',scope='before_search' if search_only else 'next_generation_only',
            thread=thread,turn=turn,model=params['model'],terminal=True,acknowledged_calls=calls,
            detail=error,internal_retry_notifications=len(errors)-1,external_outcome='rejected',usage=None,
            journals={name:hashlib.sha256(value).hexdigest() for name,value in data.items()})
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def proof(control):
    from .codex_transport import PASSIVE_ITEMS
    root=Path(control)
    try:
        data={name:(root/name).read_bytes() for name in ('codex-sent.jsonl','codex-events.jsonl')}
        if any(len(value)>20_000_000 for value in data.values()):return None
        sent=[json.loads(line) for line in data['codex-sent.jsonl'].splitlines()]
        events=[json.loads(line) for line in data['codex-events.jsonl'].splitlines()]
        if any(not isinstance(e,dict) for e in sent+events):return None
        starts=[s for s in sent if s.get('method')=='thread/start']
        turns=[s for s in sent if s.get('method')=='turn/start']
        if len(starts)!=1 or len(turns)!=1:return None
        def response(ident,key):
            matches=[e['result'][key]['id'] for e in events if e.get('id')==ident and key in e.get('result',{})]
            return matches[0] if len(matches)==1 else None
        thread=response(starts[0]['id'],'thread');turn=response(turns[0]['id'],'turn')
        if not thread or not turn or turns[0]['params']['threadId']!=thread:return None
        errors=[];terminals=[]
        for event in events:
            method=event.get('method');params=event.get('params',{})
            if method and 'id' in event:return None  # No dynamic tool/permission request.
            if method in ('item/started','item/completed'):
                if params.get('threadId')!=thread or params.get('turnId')!=turn:return None
                if params.get('item',{}).get('type') not in PASSIVE_ITEMS:return None
            if method=='error':
                if params.get('threadId')!=thread or params.get('turnId')!=turn or type(params.get('willRetry')) is not bool:return None
                errors.append(params)
            if method=='turn/completed':
                if params.get('threadId')!=thread or params.get('turn',{}).get('id')!=turn:return None
                terminals.append(params['turn'])
        if not errors or len(terminals)!=1:return None
        if errors[-1]['willRetry'] is not False or any(e['willRetry'] is not True for e in errors[:-1]):return None
        terminal=terminals[0]
        failure=errors[-1]['error']
        if terminal.get('status')!='failed' or terminal.get('error')!=failure:return None
        if any(i.get('type') not in PASSIVE_ITEMS for i in terminal.get('items',[])):return None
        info=failure.get('codexErrorInfo')
        exhausted=isinstance(info,dict) and set(info)=={'responseTooManyFailedAttempts'}
        if exhausted:
            status=info['responseTooManyFailedAttempts'].get('httpStatusCode')
            error=dict(status=status,error=failure)
        else:error=json.loads(failure['message'])
        if type(error.get('status')) is not int or error['status'] not in CLIENT_ERRORS:return None
        detail=error.get('error')
        if not isinstance(detail,dict) or not isinstance(detail.get('message'),str):return None
        return dict(version=1,thread=thread,turn=turn,model=starts[0]['params']['model'],status=error['status'],
            detail=detail,external_outcome='rejected',usage=None,terminal=True,scope='before_tools',
            retry_exhausted=exhausted,internal_retry_notifications=len(errors)-1,
            journals={name:hashlib.sha256(value).hexdigest() for name,value in data.items()})
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None
