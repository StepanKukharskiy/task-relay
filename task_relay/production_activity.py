"""Read-only worker activity for status cards; never a scheduling decision."""
import json
import math
import time


def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None


def usage_totals(reports):
    """Sum reported per-response fields without adding cache/reasoning subsets twice."""
    fields={'input':('input_tokens','prompt_tokens','promptTokenCount'),
            'output':('output_tokens','completion_tokens','candidatesTokenCount'),
            'cached':('cached_input_tokens','cachedContentTokenCount'),
            'reasoning':('reasoning_output_tokens','thoughtsTokenCount')}
    totals={};reported=0
    for report in reports if isinstance(reports,list) else []:
        if not isinstance(report,dict):continue
        found={}
        for name,aliases in fields.items():
            for key in aliases:
                value=_number(report.get(key))
                if value is not None:found[name]=value;break
        for name,keys,field in (('cached',('input_tokens_details','prompt_tokens_details'),'cached_tokens'),
                                ('reasoning',('output_tokens_details','completion_tokens_details'),'reasoning_tokens')):
            if name in found:continue
            for key in keys:
                nested=report.get(key)
                value=_number(nested.get(field)) if isinstance(nested,dict) else None
                if value is not None:found[name]=value;break
        if found:
            reported+=1
            for name,value in found.items():totals[name]=totals.get(name,0)+value
    return {'tokens':totals,'reported_responses':reported}


def _read(root, relative, aid):
    from orchestrator.runtime import safe_file
    try:
        path=safe_file(root,relative)
        with path.open('rb') as stream:raw=stream.read(131073)
        if len(raw)>131072:return {}
        value=json.loads(raw)
        return value if isinstance(value,dict) and value.get('token')==aid else {}
    except (OSError,ValueError):return {}


def snapshot(root, attempt, spec, backend, now=None):
    now=time.time() if now is None else now
    frozen=json.loads(attempt['frozen']) if attempt else {}
    assignment=frozen or spec
    execution=assignment.get('execution')
    if execution:
        from orchestrator.execution import REGISTRY
        capability=execution.get('capability','unknown')
        ai=REGISTRY.get(capability,{}).get('kind')=='api'
        model=execution.get('parameters',{}).get('model') if ai else None
        executor=capability;reasoning=None
    else:
        chosen=frozen.get('backend') or backend
        ai=True;model=chosen.get('model');reasoning=chosen.get('reasoning');executor=chosen.get('type')
    result={'ai':ai,'model':model,'reasoning':reasoning,'executor':executor,
            'objective':assignment.get('objective',spec.get('objective')),
            'limit_seconds':assignment.get('limits',{}).get('seconds'),
            'elapsed_seconds':None,'last_event_at':None,'heartbeat_at':None,
            'activity':None,'tool_calls':None,'usage':usage_totals([]),'usage_final':False}
    if not attempt:return result
    aid=attempt['id']
    # Use fixed paths under the runtime; do not follow provider-supplied paths.
    start=_read(root,'workers/'+aid+'/started.json',aid)
    progress=_read(root,'workers/'+aid+'/progress.json',aid)
    receipt=json.loads(attempt['receipt'] or '{}')
    if not isinstance(receipt,dict):receipt={}
    final=receipt.get('status')=='finished' or _number(receipt.get('finished')) is not None
    recorded=receipt if final else progress
    begun=_number(receipt.get('started')) or _number(start.get('started'))
    elapsed=_number(receipt.get('elapsed_seconds')) if final else None
    if elapsed is None and begun is not None and begun<=now:
        # Stopped/uncertain attempts without a finish receipt have unknown elapsed time.
        if attempt['state'] in ('launching','running','cancelling'):elapsed=now-begun
    result.update(elapsed_seconds=elapsed,tool_calls=_number(recorded.get('tool_calls')),
                  usage=usage_totals(recorded.get('usage',[])),usage_final=final)
    for key in ('last_event_at','heartbeat_at'):
        value=_number(progress.get(key))
        if value is not None and value<=now:result[key]=value
    allowed={'waiting_for_response','using_tool','running_command','searching_web','processing_response'}
    if progress.get('activity') in allowed:result['activity']=progress['activity']
    if result['last_event_at'] is None and not final:
        from orchestrator.runtime import safe_file
        try:
            events=safe_file(root,'workers/'+aid+'/events.jsonl')
            stamp=events.stat().st_mtime
            if events.stat().st_size and stamp<=now:result['last_event_at']=stamp
        except (ValueError,OSError):pass
    return result


def duration(seconds):
    value=int(max(0,seconds));minutes,seconds=divmod(value,60)
    hours,minutes=divmod(minutes,60)
    return (f'{hours}h ' if hours else '')+(f'{minutes}m ' if hours or minutes else '')+f'{seconds}s'


def lines(task, now=None):
    now=time.time() if now is None else now
    activity=task.get('activity')
    if not activity:return []
    active=task['status'] in ('running','launching','cancelling')
    text=[]
    if activity.get('objective'):
        text.append(('Relay is working on: ' if active else 'Task: ')+activity['objective'])
    prefix='Planned ' if not task.get('latest_attempt') else ''
    if activity['ai']:
        line=prefix+'AI: '+(activity.get('model') or 'model not recorded')
        if activity.get('reasoning'):line+=' · '+activity['reasoning']+' reasoning'
        if activity.get('executor'):line+=' · '+activity['executor']
        text.append(line)
    else:text.append(prefix+'Executor: '+str(activity.get('executor') or 'local operation'))
    elapsed=activity.get('elapsed_seconds');limit=activity.get('limit_seconds')
    timing=[]
    if elapsed is not None:timing.append('Elapsed: '+duration(elapsed))
    if limit is not None:timing.append('Task limit: '+duration(limit))
    if activity['ai'] and activity.get('tool_calls') is not None:timing.append(f'Tools used: {int(activity["tool_calls"])}')
    if timing:text.append(' · '.join(timing))
    if task.get('latest_attempt') and activity['ai']:
        tokens=activity['usage']['tokens']
        names={'input':'input','output':'output','cached':'cached input','reasoning':'reasoning'}
        counts=[f'{int(tokens[k]):,} {label}' for k,label in names.items() if k in tokens]
        if counts:
            text.append('Tokens reported'+(' (final)' if activity['usage_final'] else ' so far')+': '+' · '.join(counts))
        else:text.append('Tokens: '+('not reported by provider' if activity['usage_final'] else 'not reported yet'))
    stamp=activity.get('last_event_at')
    if active and stamp is not None:
        actions={'waiting_for_response':'waiting for AI response','using_tool':'using a tool',
                 'running_command':'running a command','searching_web':'searching the web',
                 'processing_response':'processing a response'}
        action=actions.get(activity.get('activity')) if activity['ai'] else None
        text.append(('Last reported action: '+action+' · ' if action else 'Last worker activity: ')+duration(now-stamp)+' ago')
    if active and activity.get('heartbeat_at') is not None and now-activity['heartbeat_at']>30:
        text.append('Worker heartbeat is stale; execution needs a status check.')
    return text
