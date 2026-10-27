"""Bounded structural edits against an immutable received proposal."""
import copy,json,re
from orchestrator import contracts as c

VERSION=1


def parts(field):
    if not isinstance(field,str) or not re.fullmatch(r'\$(?:\.[A-Za-z_][A-Za-z_0-9-]*|\[\d+\])+',field):return None
    values=[int(index) if index else key for key,index in re.findall(r'\.([A-Za-z_][A-Za-z_0-9-]*)|\[(\d+)\]',field)]
    return values if len(values)>=2 else None


def prepare(payload,previous,detail):
    path=parts((detail or {}).get('field'))
    if payload.get('planner_correction_version')!=VERSION or not isinstance(previous,dict) or not path:return None
    # A correction is available only when its parent exists in the saved reply.
    parent=previous
    try:
        for key in path[:-1]:parent=parent[key]
        if not isinstance(parent,(dict,list)):return None
        if isinstance(parent,list) and (type(path[-1]) is not int or not 0<=path[-1]<len(parent)):return None
    except (KeyError,IndexError,TypeError):return None
    from .planning_contract import obj
    contract=dict(version=VERSION,base_sha256=c.digest(previous),path=path,
        field=detail['field'],instruction='Return only this bounded correction. Preserve the saved proposal. Set replaces/adds this exact field; remove deletes it. value_json is a JSON string for the replacement, or null encoded as a string for remove. The whole corrected proposal must still pass every frozen rule.')
    payload['structural_correction']['patch_contract']=contract
    payload['response_contract']=dict(version=1,schema=obj(dict(base_sha256={'type':'string','enum':[contract['base_sha256']]},
        action={'type':'string','enum':['set','remove']},value_json={'type':'string'}),['base_sha256','action','value_json']))
    payload['planner_instructions']+='\nThe structural_correction.patch_contract replaces the response shape for this one call. Return only response_contract.schema; do not regenerate the plan.'
    return contract


def apply(raw,previous,contract):
    if len(raw.encode())>32000:raise ValueError('Structural correction exceeds 32 KB')
    patch=json.loads(raw)
    if (not isinstance(patch,dict) or set(patch)!={'base_sha256','action','value_json'}
            or patch['base_sha256']!=contract['base_sha256'] or c.digest(previous)!=contract['base_sha256']
            or patch['action'] not in ('set','remove') or not isinstance(patch['value_json'],str)):
        raise ValueError('Structural correction differs from its exact saved base or contract')
    value=json.loads(patch['value_json']);updated=copy.deepcopy(previous);parent=updated
    for key in contract['path'][:-1]:parent=parent[key]
    key=contract['path'][-1]
    if patch['action']=='remove':
        if value is not None:raise ValueError('Remove correction must encode null')
        del parent[key]
    else:parent[key]=value
    return updated,dict(version=VERSION,base_sha256=contract['base_sha256'],field=contract['field'],
        patch_sha256=c.digest(patch),result_sha256=c.digest(updated))
