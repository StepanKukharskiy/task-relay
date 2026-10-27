"""Procedural output checks for any file deliverable; reviews own semantic correctness."""
import json
import re

CHECKS={'nonempty','utf8','json','fenced_code'}


def validate_assignment(assignment):
    contracts=assignment.get('output_contracts',[])
    if not isinstance(contracts,list) or len(contracts)>len(assignment['outputs']):
        raise ValueError('Invalid output contracts.')
    seen=set()
    for value in contracts:
        if (not isinstance(value,dict) or set(value) not in ({'path','format','checks'}, {'version','path','format','checks','validation'})
            or not isinstance(value['path'],str) or value['path'] in seen
            or not isinstance(value['format'],str) or not re.fullmatch(r'(?:\.[a-zA-Z0-9][a-zA-Z0-9.]{0,18})?',value['format'])
            or value['format'] and not value['path'].lower().endswith(value['format'].lower())
            or assignment.get('review_of') or value['path'] not in {o['path'] for o in assignment['outputs']}
            or not isinstance(value['checks'],list) or any(not isinstance(c,str) or c not in CHECKS for c in value['checks'])
            or len(set(value['checks']))!=len(value['checks'])):
            raise ValueError('Invalid declared output contract.')
        if 'version' in value:
            validation=value['validation']
            if (type(value['version']) is not int or value['version']!=2 or not assignment.get('execution')
                or not isinstance(validation,list) or len(validation)>6
                or any(not isinstance(c,str) or not c.strip() or len(c)>300 for c in validation)):
                raise ValueError('Invalid declared semantic output validation.')
        seen.add(value['path'])


def review_criteria(assignment):
    """Required semantic checks supplement, never replace, operation receipts."""
    criteria=list(assignment['criteria'])
    for value in assignment.get('output_contracts',[]):
        for criterion in value.get('validation',[]):
            if criterion not in criteria:criteria.append(criterion)
    return criteria


def check_delivery(assignment,read):
    validate_assignment(assignment)
    for value in assignment.get('output_contracts',[]):
        raw=read(value['path']);checks=value['checks']
        if 'nonempty' in checks and not raw.strip():raise ValueError('A requested output is empty: '+value['path'])
        if set(checks)&{'utf8','json','fenced_code'}:
            try:text=raw.decode('utf-8-sig')
            except UnicodeError:raise ValueError('A requested text output is not UTF-8: '+value['path']) from None
            if 'nonempty' in checks and not text.strip():raise ValueError('A requested text output is empty: '+value['path'])
            if 'json' in checks:
                try:json.loads(text)
                except ValueError:raise ValueError('A requested output is not valid JSON: '+value['path']) from None
            if 'fenced_code' in checks and not any(m[2].strip() for m in re.finditer(r'^(`{3,}|~{3,})[^\n]*\n([\s\S]*?)^\1[ \t]*$',text,re.M)):
                raise ValueError('A requested output lacks a complete nonempty code example: '+value['path'])


def bind_review_criteria(tasks):
    """Compile inherited checks and retain every proposed extra review requirement."""
    import copy
    by_id={t['id']:t for t in tasks};receipts=[]
    for review in tasks:
        producer=by_id.get(review.get('review_of'))
        if not producer or any(k in review for k in ('source_fidelity','design_review','research_audit')):continue
        before=copy.deepcopy(review['criteria'])
        extra=[c for c in before if c not in review_criteria(producer)]
        if extra:
            if producer.get('execution'):
                path=producer['outputs'][0]['path']
                contract=next((c for c in producer.get('output_contracts',[]) if c['path']==path),None)
                if contract is None:
                    contract={'version':2,'path':path,'format':'','checks':[],'validation':[]}
                    producer.setdefault('output_contracts',[]).append(contract)
                contract.setdefault('version',2);contract.setdefault('validation',[])
                for check in extra:
                    if check not in contract['validation']:contract['validation'].append(check)
            else:
                producer['criteria'].extend(extra)
        review['criteria']=review_criteria(producer)
        if review['criteria']!=before:
            receipts.append({'task':review['id'],'producer':producer['id'],'before':before,
                             'value':copy.deepcopy(review['criteria']),
                             'reason':'inherit exact producer checks; preserve every proposed extra review check'})
    return receipts
