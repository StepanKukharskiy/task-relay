# -*- coding: utf-8 -*-
"""Dependency-free contract shared by Rhino 7 IronPython and Rhino 8 CPython."""
from __future__ import unicode_literals

try:
    STRING_TYPES = (str, unicode)
    INTEGER_TYPES = (int, long)
except NameError:
    STRING_TYPES = (str,)
    INTEGER_TYPES = (int,)

MEDIA = 'application/vnd.grasshopper'
DESCRIPTION = {
    'mode': 'create only; scene_sha256 must be null. Existing definitions are not edited.',
    'version': 1,
    'expected_object_count': 'Exact count of document objects (including groups, sliders and panels), integer 1–1000.',
    'expected_outputs': 'List of 1–100 checks: {"object": "unique object NickName", "output": 0, "count": 1}. Output is a zero-based component output index; standalone parameters use 0. Count is the exact VolatileDataCount after each independent reopen/solve.',
    'script_api': 'Rhino 7 uses IronPython 2.7; Rhino 8 uses CPython 3. Author for the selected interpreter; Rhino 7 scripts cannot use Python 3 syntax or pathlib. Add a UTF-8 encoding declaration for non-ASCII source and use Unicode object names. Embedded legacy GhPython component code uses IronPython 2.7 on both versions. Supplied globals: Grasshopper, Rhino, System, ghdoc (new GH_Document), doc (headless RhinoDoc), workspace (input root). Add objects to ghdoc; Relay solves, saves and disposes it. Installed Grasshopper.dll, GH_IO.dll and GhPython.gha are loaded. Embed Python/template data in the graph; no external dependencies, baking, UI, timers, scheduled solutions or network work. Do not replace supplied documents, save outputs or change global solver settings.',
    'script_max_bytes': 100000,
    'verification': 'SaveQuiet writes genuine candidate.gh and candidate.ghx. Both independently reopen and solve; compare object identities/types, names and wire topology, runtime errors and exact declared output counts. Runtime warnings require review. These checks do not prove geometric fidelity, portability or visual quality.',
    'permissions': 'Exact-script host approval includes execution of embedded components during build and both verification solves. Normal host permissions, not an OS sandbox. Candidate creation is not selection.',
}


def validate_checks(value):
    if not isinstance(value, dict) or set(value) != {'version', 'mode', 'expected_object_count', 'expected_outputs'}:
        raise ValueError('Use the exact Grasshopper checks schema')
    if type(value['version']) not in INTEGER_TYPES or value['version'] != 1 or value['mode'] != 'create':
        raise ValueError('Grasshopper supports version 1 create only')
    if type(value['expected_object_count']) not in INTEGER_TYPES or not 1 <= value['expected_object_count'] <= 1000:
        raise ValueError('Grasshopper object count must be 1–1000')
    outputs = value['expected_outputs']
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 100:
        raise ValueError('Declare 1–100 Grasshopper output checks')
    seen = set()
    for item in outputs:
        if not isinstance(item, dict) or set(item) != {'object', 'output', 'count'}:
            raise ValueError('Use object/output/count for each Grasshopper output check')
        if not isinstance(item['object'], STRING_TYPES) or not 1 <= len(item['object']) <= 200:
            raise ValueError('Use an exact unique Grasshopper object NickName')
        for key, maximum in (('output', 99), ('count', 100000)):
            if type(item[key]) not in INTEGER_TYPES or not 0 <= item[key] <= maximum:
                raise ValueError('Invalid Grasshopper output index/count')
        identity = (item['object'], item['output'])
        if identity in seen:
            raise ValueError('Duplicate Grasshopper output check')
        seen.add(identity)
    return value


def evaluate(snapshot, checks, baseline=None):
    errors = list(snapshot['errors'])
    if len(snapshot['graph']) != checks['expected_object_count']:
        errors.append('Unexpected Grasshopper object count')
    if baseline is not None and snapshot['graph'] != baseline['graph']:
        errors.append('Saved Grasshopper graph differs from the authored graph')
    for expected in checks['expected_outputs']:
        matches = [key for key, obj in snapshot['graph'].items() if obj['nickname'] == expected['object']]
        if len(matches) != 1:
            errors.append('Missing or ambiguous Grasshopper object: ' + expected['object'])
            continue
        outputs = snapshot['outputs'][matches[0]]
        index = expected['output']
        if index >= len(outputs) or outputs[index] != expected['count']:
            errors.append('Unexpected Grasshopper output count: ' + expected['object'] + '/' + str(index))
    return errors
