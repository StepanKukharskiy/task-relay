"""Fail closed on absent/mismatched evidence; measured differences need user review.

Measurements are independent worker observations, not a deterministic CAD kernel
certificate. This module verifies their binding, completeness and thresholds.
"""
import json
import math
import re

CRITERION='Verify exact source geometry; provide source fidelity evidence as required by the frozen source_fidelity contract.'

def number(value):
    try:return type(value) in (int,float) and math.isfinite(value) and value>=0
    except OverflowError:return False


def validate_metrics(checks):
    if not isinstance(checks,list) or not 1<=len(checks)<=8:raise ValueError('Declare 1–8 source fidelity error metrics.')
    names=set()
    for check in checks:
        if (not isinstance(check,dict) or set(check)!={'metric','tolerance','unit'}
            or not isinstance(check['metric'],str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',check['metric'])
            or check['metric'] in names or not number(check['tolerance'])
            or not isinstance(check['unit'],str) or not 1<=len(check['unit'])<=40):
            raise ValueError('Source fidelity metrics require distinct names, finite nonnegative tolerances and units.')
        names.add(check['metric'])


def validate_assignment(task):
    policy=task['source_fidelity']
    if (not task.get('review_of') or not isinstance(policy,dict)
        or set(policy)!={'version','phase','sources','checks','criterion'}
        or type(policy['version']) is not int or policy['version']!=1
        or policy['phase'] not in ('source_audit','comparison')
        or type(policy['criterion']) is not int or not 1<=policy['criterion']<=len(task['criteria'])):
        raise ValueError('Invalid source fidelity review contract.')
    validate_metrics(policy['checks'])
    sources=policy['sources'];seen=set();inputs={i.get('artifact') for i in task['inputs']}
    if not isinstance(sources,list) or not 1<=len(sources)<=10:raise ValueError('Source fidelity requires frozen sources.')
    for s in sources:
        if (not isinstance(s,dict) or set(s)!={'artifact','sha256'} or not isinstance(s['artifact'],str)
            or s['artifact'] not in inputs or s['artifact'] in seen or not isinstance(s['sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}',s['sha256'])):
            raise ValueError('Source fidelity input identity is invalid or missing.')
        seen.add(s['artifact'])


def instructions(policy):
    common=('\nFor criterion '+str(policy['criterion'])+', evidence must be a JSON object encoded as the evidence string, '
        'with sources exactly '+json.dumps(policy['sources'])+'. Independently read and hash these files. '
        'Record source_observations as a nonempty text entry for every source artifact ID, citing actual entity IDs, '
        'units, transforms, elevation/boundary geometry and the extraction method. Missing input/tooling means blocked. ')
    if policy['phase']=='source_audit':
        return common+'This is preparation only: audit that the script consumes the extracted geometry; do not certify the unexecuted model. Evidence keys: sources, source_observations.\n'
    return common+('Also include comparisons, one entry per frozen metric '+json.dumps(policy['checks'])+
        ', each with exactly metric, error, evidence. Error is a finite nonnegative measured error in the declared unit; '
        'evidence must describe the reproducible source/candidate measurement and actual results. Compare the saved native '
        'candidate, not merely its producer checks. Do not invent zero errors or infer fidelity from a preview, counts or bounds. '
        'If unable to measure, finish blocked. A measured exceeded tolerance is a quality concern for explicit user review; retain the measurement and report it in findings, never claim source conformity. Evidence keys: sources, source_observations, comparisons.\n')


def validate_report(result,frozen):
    if 'source_fidelity' not in frozen or result['decision']!='accept':return
    validate_assignment(frozen)
    policy=frozen['source_fidelity']
    try:data=json.loads(result['checks'][policy['criterion']-1]['evidence'])
    except (ValueError,TypeError,KeyError,IndexError):raise ValueError('Acceptance requires structured source fidelity evidence.') from None
    fields={'sources','source_observations'} | ({'comparisons'} if policy['phase']=='comparison' else set())
    if not isinstance(data,dict) or set(data)!=fields or data['sources']!=policy['sources']:
        raise ValueError('Source fidelity evidence does not match the frozen source versions.')
    # The runtime's frozen input hashes, not merely the declared policy, anchor it.
    for source in policy['sources']:
        if not any(i.get('artifact')==source['artifact'] and i.get('sha256')==source['sha256'] for i in frozen['inputs']):
            raise ValueError('Source fidelity hash differs from the delivered source input.')
    observations=data['source_observations']
    if (not isinstance(observations,dict) or set(observations)!={s['artifact'] for s in policy['sources']}
        or any(not isinstance(v,str) or not v.strip() or len(v)>12000 for v in observations.values())):
        raise ValueError('Every source requires an independently observed geometry audit.')
    if policy['phase']!='comparison':return
    comparisons=data['comparisons'];expected={c['metric']:c for c in policy['checks']};seen=set()
    if not isinstance(comparisons,list) or len(comparisons)!=len(expected):raise ValueError('Missing source geometry comparisons.')
    for item in comparisons:
        if (not isinstance(item,dict) or set(item)!={'metric','error','evidence'}
            or not isinstance(item['metric'],str) or item['metric'] not in expected or item['metric'] in seen
            or not number(item['error']) or not isinstance(item['evidence'],str) or not item['evidence'].strip()):
            raise ValueError('Source comparison requires distinct metrics and finite measured errors with evidence.')
        seen.add(item['metric'])
        if item['error']>expected[item['metric']]['tolerance']:
            from .outcomes import quality
            finding=quality('source_geometry_difference',
                'Source geometry difference: '+item['metric']+' = '+str(item['error'])+' '+expected[item['metric']]['unit']+
                '; expected at most '+str(expected[item['metric']]['tolerance'])+'.',item['evidence'][:3900]+' (full measurement in the source-fidelity review receipt)')
            if finding not in result.setdefault('findings',[]):result['findings'].append(finding)
