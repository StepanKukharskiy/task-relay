"""Dependency-free SketchUp v1 preparation and independent snapshot checks."""
import math

MEDIA = 'application/vnd.sketchup.skp'
DESCRIPTION = {
    'version': 1, 'mode': 'create or edit',
    'changed_entities': 'Distinct top-level persistent ID strings allowed to change; empty for create',
    'allow_additions': 'boolean; true for create',
    'expected_entity_count': 'Exact final top-level entity count, 1–5000',
    'expected_dimensions_mm': 'Map of unique top-level group/component names to [x,y,z] dimensions in millimeters, 1–100 entries. Differences require user preview review; missing/invalid evidence fails.',
    'preview': {'resolution': '[width,height], integers 64–1024'},
    'scope': 'Plain edges/faces/groups/components, bounded to 5000 total entities and 100000 face/edge points. '
             'No textures, images, external definitions or unsupported entity types. Edits compare recorded options, '
             'tag/material properties, scene cameras/attributes, active camera and untouched geometry; this is not full document equivalence. '
             'SketchUp internal lengths are inches; checks use millimeters. '
             'Script receives model = Sketchup.active_model. Save/reopen/preview is performed by Relay.'}


def validate_checks(value):
    fields = {'version','mode','changed_entities','allow_additions','expected_entity_count','expected_dimensions_mm','preview'}
    if not isinstance(value, dict) or set(value) != fields or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Use the exact SketchUp v1 checks schema')
    if value['mode'] not in ('create','edit') or type(value['allow_additions']) is not bool:
        raise ValueError('Invalid SketchUp mode or additions policy')
    ids = value['changed_entities']
    if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) or not i.isascii() or not i.isdigit() for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Declare distinct SketchUp persistent ID strings')
    if value['mode']=='create' and (ids or not value['allow_additions']):
        raise ValueError('New models require additions and no changed source entities')
    if type(value['expected_entity_count']) is not int or not 1<=value['expected_entity_count']<=5000:
        raise ValueError('Expected entity count must be 1–5000')
    dims = value['expected_dimensions_mm']
    if not isinstance(dims,dict) or not 1<=len(dims)<=100:
        raise ValueError('Declare dimensions for 1–100 uniquely named groups/components')
    for name, vector in dims.items():
        if not isinstance(name,str) or not 1<=len(name)<=200 or not isinstance(vector,list) or len(vector)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1e9 for n in vector):
            raise ValueError('Invalid SketchUp dimensions in millimeters')
    p=value['preview']
    if not isinstance(p,dict) or set(p)!={'resolution'} or not isinstance(p['resolution'],list) or len(p['resolution'])!=2 or any(type(n) is not int or not 64<=n<=1024 for n in p['resolution']):
        raise ValueError('SketchUp preview resolution must be 64–1024')
    return value


def compare(before, after, checks):
    validate_checks(checks)
    errors=[]; old=before['entities']; new=after['entities']; changed=set(checks['changed_entities'])
    if changed-set(old): errors.append('Declared changed entities are absent from source')
    if not checks['allow_additions'] and set(new)-set(old): errors.append('Undeclared entity additions')
    if checks['mode']=='edit':
        for ident in set(old)-changed:
            if old[ident]!=new.get(ident): errors.append('Untouched entity changed or missing: '+ident)
        if before['document']!=after['document']: errors.append('Preserved document settings/tables changed')
    if len(new)!=checks['expected_entity_count']: errors.append('Unexpected final entity count')
    for name, expected in checks['expected_dimensions_mm'].items():
        matches=[v for v in new.values() if v.get('name')==name and v.get('type') in ('Group','ComponentInstance')]
        if len(matches)!=1: errors.append('Missing or ambiguous named group/component: '+name); continue
        actual=matches[0].get('dimensions_mm',[])
        if len(actual)!=3 or any(not math.isfinite(a) or a<0 for a in actual):
            errors.append('Missing or invalid dimension measurement: '+name)
    return errors


def dimension_warnings(after,checks):
    warnings=[]
    for name,expected in checks['expected_dimensions_mm'].items():
        matches=[v for v in after['entities'].values() if v.get('name')==name and v.get('type') in ('Group','ComponentInstance')]
        if len(matches)!=1:continue
        actual=matches[0].get('dimensions_mm',[])
        if len(actual)!=3 or any(not math.isfinite(a) or a<0 for a in actual):continue
        if any(abs(a-b)>max(.01,abs(b)*.0001) for a,b in zip(actual,expected)):
            warnings.append(f'{name}: measured dimensions {actual}; expected {expected} mm.')
    return warnings
