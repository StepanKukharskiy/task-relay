"""Checks for unrestricted, exactly approved standalone rhino3dm Python."""
import math
import uuid

DESCRIPTION = '''Standalone CPython/rhino3dm; the full installed Python API is exposed.
The reviewed script receives rhino3dm, model (File3dm, new or read from the selected
source), input_paths (declared workspace path -> absolute path), and workspace.
Modify model or replace it with another File3dm. Relay saves model after the script
returns and reopens it in a separate Python process. No geometry-type whitelist.
Library features are not RhinoCommon commands, native rendering or Rhino plugins.
Use application/octet-stream for additional binary assets/models; the single
application/vnd.rhino input is the primary edit source. Context text and images
are also allowed. All inputs, exact script, checks, runtime and limits are approved.
Python has normal filesystem/network permissions, not an OS sandbox. Reviewed
code must not launch native apps or contact paid/external services without the
corresponding separately authorized scope. No automatic fallback or replay.
Checks JSON fields (all required):
{version:1,mode:"create"|"edit",file_version:integer 2..8,
 expected_units:UnitSystem enum name or null,expected_object_count:integer 0..100000 or null,
 required_objects:[unique object names],preserve_objects:[exact source object UUIDs],
 expected_dimensions:{unique object name:[x,y,z]}}.
file_version is explicit; 7 writes a Rhino 7-compatible archive, 8 writes Rhino 8.
This is the file format version, not the installed library or Python version.
required_objects must resolve unambiguously; preserve_objects is empty for create.
Preserved objects retain geometry and encoded attributes; other edits are governed
by the exact reviewed script. Unspecified document tables/settings are not certified
unchanged. No automatic assurance for opaque plugin data or external dependencies.
Integrity checks include valid geometry/attributes, matching before-save vs reopened
objects, target archive version, document units/tolerance and strings. Serialization
changes on downsave require explicit user review; missing/invalid geometry or failed
preservation blocks. Dimension differences require user review, not automatic acceptance.
Reopen checks are library verification only, not native Rhino or visual/source-fidelity approval.
The result model, model.py, checks.json and execution.json must be reviewed and selected.
'''


def validate_checks(value):
    required={'version','mode','file_version','expected_units','expected_object_count',
              'required_objects','preserve_objects','expected_dimensions'}
    if not isinstance(value,dict) or set(value)!=required:
        raise ValueError('Use the exact rhino3dm.run_python checks schema')
    if type(value['version']) is not int or value['version']!=1 or value['mode'] not in ('create','edit'):
        raise ValueError('Invalid standalone library checks version/mode')
    if type(value['file_version']) is not int or not 2<=value['file_version']<=8:
        raise ValueError('Choose an explicit .3dm file version from 2 through 8 (7 for Rhino 7)')
    units=value['expected_units']
    if units is not None and (not isinstance(units,str) or not units.isidentifier() or units.startswith('_')):
        raise ValueError('Expected units must be a UnitSystem name or null')
    count=value['expected_object_count']
    if count is not None and (type(count) is not int or not 0<=count<=100000):
        raise ValueError('Expected object count must be 0–100000 or null')
    for key in ('required_objects','preserve_objects'):
        names=value[key]
        if (not isinstance(names,list) or len(names)>10000 or any(not isinstance(n,str) or not 1<=len(n)<=200 for n in names)
                or len(set(names))!=len(names)):
            raise ValueError('Invalid or duplicate '+key)
    for ident in value['preserve_objects']:
        try:
            if str(uuid.UUID(ident))!=ident:raise ValueError('Noncanonical UUID')
        except ValueError:raise ValueError('preserve_objects requires exact lowercase source UUIDs') from None
    if value['mode']=='create' and value['preserve_objects']:
        raise ValueError('A new model has no source objects to preserve')
    dimensions=value['expected_dimensions']
    if not isinstance(dimensions,dict) or len(dimensions)>10000:
        raise ValueError('Invalid expected dimensions')
    for name,dims in dimensions.items():
        if (not isinstance(name,str) or not 1<=len(name)<=200 or not isinstance(dims,list) or len(dims)!=3
                or any(type(n) not in (int,float) or not math.isfinite(n) or n<0 for n in dims)):
            raise ValueError('Invalid expected object dimensions')
    return value
