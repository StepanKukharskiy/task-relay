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
        if (not isinstance(value,dict) or set(value)!={'path','format','checks'}
            or not isinstance(value['path'],str) or value['path'] in seen
            or not isinstance(value['format'],str) or not re.fullmatch(r'(?:\.[a-zA-Z0-9][a-zA-Z0-9.]{0,18})?',value['format'])
            or value['format'] and not value['path'].lower().endswith(value['format'].lower())
            or assignment.get('review_of') or value['path'] not in {o['path'] for o in assignment['outputs']}
            or not isinstance(value['checks'],list) or any(not isinstance(c,str) or c not in CHECKS for c in value['checks'])
            or len(set(value['checks']))!=len(value['checks'])):
            raise ValueError('Invalid declared output contract.')
        seen.add(value['path'])


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
