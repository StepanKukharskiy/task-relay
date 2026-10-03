"""Require intent-specific evidence, without treating model judgment as human approval."""
import json
import re

CRITERION='Compare the candidate against every active design intent entry; distinguish preparation evidence from observed geometry.'


def validate_assignment(task):
    p=task['design_review']
    if (not task.get('review_of') or not isinstance(p,dict)
        or set(p)!={'version','sha256','phase','entries','criterion'} or type(p['version']) is not int or p['version']!=1
        or p['phase'] not in ('preparation','output') or not isinstance(p['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',p['sha256'])
        or type(p['criterion']) is not int or not 1<=p['criterion']<=len(task['criteria'])
        or task['criteria'][p['criterion']-1]!=CRITERION or not isinstance(p['entries'],list) or not p['entries']):
        raise ValueError('Invalid frozen design review.')
    ids=[e['id'] for e in p['entries']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate design review entry.')
    from .contracts import digest
    record=task.get('design_intent_state',{})
    if (record.get('sha256')!=p['sha256'] or digest({k:v for k,v in record.items() if k!='sha256'})!=p['sha256']
        or [e for e in record['entries'] if e['id'] not in record['superseded']]!=p['entries']):
        raise ValueError('Design review is not bound to its exact intent version.')


def validate_report(result, frozen):
    if 'design_review' not in frozen or result['decision']!='accept':return
    validate_assignment(frozen);p=frozen['design_review']
    try:data=json.loads(result['checks'][p['criterion']-1]['evidence'])
    except (ValueError,TypeError,KeyError,IndexError):raise ValueError('Design acceptance requires structured per-entry evidence.') from None
    if (not isinstance(data,dict) or set(data)!={'intent_sha256','phase','observations'}
        or data['intent_sha256']!=p['sha256'] or data['phase']!=p['phase']):
        raise ValueError('Design evidence does not match the frozen intent or review phase.')
    expected={e['id'] for e in p['entries']};seen=set()
    observations=data['observations']
    if not isinstance(observations,list) or len(observations)!=len(expected):raise ValueError('Every design entry needs independent evidence.')
    for item in observations:
        if (not isinstance(item,dict) or set(item)!={'id','status','evidence'}
            or not isinstance(item['id'],str) or item['id'] not in expected or item['id'] in seen
            or item['status'] not in ('supported','concern','unverified')
            or not isinstance(item['evidence'],str) or not item['evidence'].strip() or len(item['evidence'])>12000):
            raise ValueError('Invalid or duplicate design observation.')
        seen.add(item['id'])
        if item['status']!='supported':
            from .outcomes import quality
            finding=quality('design_intent_'+item['status'],'Design intent '+item['id']+': '+item['status']+'.',item['evidence'][:3900])
            if finding not in result.setdefault('findings',[]):result['findings'].append(finding)
