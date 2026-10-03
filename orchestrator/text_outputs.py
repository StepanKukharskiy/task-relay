"""Procedural file checks; semantic correctness stays with independent review."""
import re


def validate_assignment(assignment):
    value=assignment.get('text_output')
    if value is None:return
    if (not isinstance(value,dict) or set(value)!={'path','code_examples'}
            or not isinstance(value['path'],str) or not value['path'].lower().endswith('.md')
            or type(value['code_examples']) is not bool or assignment.get('review_of')
            or value['path'] not in {o['path'] for o in assignment['outputs']}):
        raise ValueError('Invalid Markdown article output contract.')


def check_delivery(assignment,read):
    validate_assignment(assignment)
    value=assignment.get('text_output')
    if value is None:return
    try:text=read(value['path']).decode('utf-8-sig')
    except UnicodeError:raise ValueError('The article file must be UTF-8 Markdown.') from None
    if not text.strip():raise ValueError('The requested article file is empty.')
    if value['code_examples'] and not any(m[2].strip() for m in re.finditer(
            r'^(`{3,}|~{3,})[^\n]*\n([\s\S]*?)^\1[ \t]*$',text,re.M)):
        raise ValueError('The requested article is missing a complete fenced code example.')
