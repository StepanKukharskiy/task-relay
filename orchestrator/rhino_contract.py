# -*- coding: utf-8 -*-
"""Direct Rhino modeling contract. Grasshopper execution is deliberately absent."""
import math
import uuid

try:
    STRING_TYPES = (str, unicode)
    INTEGER_TYPES = (int, long)
except NameError:
    STRING_TYPES = (str,)
    INTEGER_TYPES = (int,)
NUMBER_TYPES = INTEGER_TYPES + (float,)

def finite(value):return not math.isnan(value) and not math.isinf(value)

MEDIA = 'application/vnd.rhino'
DESCRIPTION = {
    'mode': 'create or edit; create has scene_sha256=null and no .3dm input',
    'units': 'Millimeters, Centimeters, Meters, Inches or Feet; edits preserve source units',
    'changed_objects': '0–100 unique existing object UUIDs permitted to change or be deleted',
    'allow_additions': 'boolean; additions require true',
    'expected_object_count': 'exact integer 1–5000 after reopening',
    'expected_dimensions': 'nonempty map of unique final object name to world bounding-box [x,y,z]; finite 0–1000000',
    'preview': 'resolution [width,height], each 64–1024; optional named_view restores that exact saved camera (use a Top orthographic view for drawings); otherwise shaded parallel perspective',
    'script_max_bytes': 100000,
    'output_checks': 'rhino.run_python delivery/checks.json is the verification REPORT (before, after, errors, passed), not the input checks specification. Validate the exact INPUT checks JSON selected by checks_sha256 with validate_checks; evaluate the output report against that input and execution receipt. Do not apply validate_checks to delivery/checks.json or replace that report with the input specification.',
    'expected_named_views': 'Optional list of 1–10 distinct named views required after reopening; declare the intended render camera when preparing a rendered model',
    'script_api': 'Rhino 7 uses IronPython 2.7; Rhino 8 uses CPython 3; Rhino, rhinoscriptsyntax, scriptcontext and doc supplied. The assigned doc is HEADLESS: doc.Views.ActiveView is None. Modify doc; Relay saves it. No interactive prompts.',
    'camera_api': 'Rhino.Display.RhinoViewport uses SetCameraLocation(Point3d, bool updateTargetLocation) and SetCameraDirection(Vector3d, bool updateTargetLocation): both require two arguments. CameraLocation and CameraDirection are read-only properties; do not assign them. CameraUp is writable. Rhino.DocObjects.ViewportInfo is a different type with different overloads. Verify the receiver type, not just the method name. Reference: https://mcneel.github.io/rhinocommon-api-docs/api/RhinoCommon/html/M_Rhino_Display_RhinoViewport_SetCameraLocation.htm',
    'named_view_example': 'from System.Drawing import Size\nvp = Rhino.Display.RhinoViewport()\nvp.Size = Size(1024,832)\nvp.SetProjection(Rhino.Display.DefinedViewportProjection.Top,"Drawing",False)\nvp.ZoomBoundingBox(Rhino.Geometry.BoundingBox(Rhino.Geometry.Point3d(-1,-1,-1),Rhino.Geometry.Point3d(11,9,1)))\nview = Rhino.DocObjects.ViewInfo(vp)\nview.Name = "Drawing"\nif doc.NamedViews.Add(view) < 0: raise ValueError("Cannot save named view")\n# Use the actual drawing bounds plus margins; never access an active UI viewport.',
    'scope': 'Geometry/attributes of untouched objects, units, tolerance, layers and materials are preserved on edits. Blocks, worksessions, external textures and custom user data are unsupported. New/deleted objects must be declared. Preview is a viewport capture, not a production render. Grasshopper is paused.',
}


def validate_checks(value):
    fields = {'mode', 'units', 'changed_objects', 'allow_additions', 'expected_object_count', 'expected_dimensions', 'preview'}
    if not isinstance(value, dict) or set(value)-{'expected_named_views'} != fields:
        raise ValueError('Use the exact Rhino checks schema')
    if value['mode'] not in ('create', 'edit') or value['units'] not in ('Millimeters', 'Centimeters', 'Meters', 'Inches', 'Feet'):
        raise ValueError('Invalid Rhino mode or units')
    ids = value['changed_objects']
    if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(s, STRING_TYPES) for s in ids):
        raise ValueError('Declare at most 100 changed Rhino object UUIDs')
    try:
        if any(str(uuid.UUID(s)) != s for s in ids) or len(set(ids)) != len(ids):raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError('Changed objects require distinct canonical UUIDs')
    if type(value['allow_additions']) is not bool:raise ValueError('Declare whether additions are allowed')
    if value['mode'] == 'create' and (ids or not value['allow_additions']):
        raise ValueError('New models require additions and no existing changed objects')
    if type(value['expected_object_count']) not in INTEGER_TYPES or not 1 <= value['expected_object_count'] <= 5000:
        raise ValueError('Expected Rhino object count must be 1–5000')
    dims = value['expected_dimensions']
    if not isinstance(dims, dict) or not 1 <= len(dims) <= 100:
        raise ValueError('Declare final dimensions for 1–100 uniquely named objects')
    for name, vector in dims.items():
        if not isinstance(name, STRING_TYPES) or not 1 <= len(name) <= 200:raise ValueError('Invalid expected object name')
        if not isinstance(vector, list) or len(vector) != 3 or any(type(n) not in NUMBER_TYPES or not finite(n) or not 0 <= n <= 1000000 for n in vector):
            raise ValueError('Invalid expected Rhino dimensions')
    p = value['preview']
    if not isinstance(p, dict) or set(p)-{'named_view'} != {'resolution'} or not isinstance(p['resolution'], list) or len(p['resolution']) != 2 or any(type(n) not in INTEGER_TYPES or not 64 <= n <= 1024 for n in p['resolution']):
        raise ValueError('Rhino preview resolution must be 64–1024')
    if 'named_view' in p and (not isinstance(p['named_view'], STRING_TYPES) or not 1 <= len(p['named_view']) <= 200):
        raise ValueError('Select an exact existing named view for the preview')
    if 'expected_named_views' in value:
        views=value['expected_named_views']
        if (not isinstance(views,list) or not 1<=len(views)<=10 or
            any(not isinstance(n,STRING_TYPES) or not 1<=len(n)<=200 for n in views) or len(set(views))!=len(views)):
            raise ValueError('Declare 1–10 distinct expected named views')
    return value


def compare(before, after, checks):
    """Scoped preservation and final geometry checks, independently after save."""
    errors = []
    old, new = before['objects'], after['objects']
    changed = set(checks['changed_objects'])
    if changed - set(old):errors.append('Declared changed objects are absent from the source')
    if not checks['allow_additions'] and set(new) - set(old):errors.append('Undeclared object additions')
    for ident in set(old) - changed:
        if new.get(ident) != old[ident]:errors.append('Untouched object changed or missing: ' + ident)
    if checks['mode'] == 'edit':
        for key in ('units', 'tolerance', 'angle_tolerance', 'layers', 'materials', 'named_views'):
            if before[key] != after[key]:errors.append('Preserved document setting/table changed: ' + key)
    if after['units'] != checks['units']:errors.append('Unexpected model units')
    if len(new) != checks['expected_object_count']:errors.append('Unexpected final object count')
    for name, expected in checks['expected_dimensions'].items():
        matches = [o for o in new.values() if o['name'] == name]
        if len(matches) != 1:errors.append('Expected object name is missing or ambiguous: ' + name);continue
        if any(abs(a-b) > max(after['tolerance'], abs(b)*0.0001, 0.0001) for a, b in zip(matches[0]['dimensions'], expected)):
            errors.append('Unexpected dimensions: ' + name)
    if any(not o['valid'] for o in new.values()):errors.append('Candidate contains invalid geometry')
    for name in checks.get('expected_named_views',[]):
        if name not in after.get('named_views',{}):errors.append('Expected render named view is missing: '+name)
    name=checks['preview'].get('named_view')
    if name and name not in after.get('named_views',{}):errors.append('Preview named view is missing: '+name)
    return errors


RENDER_DESCRIPTION = {
    'version': 1, 'named_view': 'Exact existing named view in the selected native model',
    'resolution': '[width,height], integers 64–1024',
    'engine': 'rhino_render; built-in Rhino Render only, using the model lighting/materials and render quality',
    'scope': 'One image, no model save, no downloads or third-party renderer; 600-second total deadline. Shaded previews are not a render substitute.'}


def validate_render(value):
    if not isinstance(value,dict) or set(value)!={'version','named_view','resolution','engine'}:
        raise ValueError('Use the exact Rhino render manifest schema')
    if type(value['version']) not in INTEGER_TYPES or value['version']!=1 or value['engine']!='rhino_render':
        raise ValueError('Unsupported Rhino render version or engine')
    if not isinstance(value['named_view'],STRING_TYPES) or not 1<=len(value['named_view'])<=200:
        raise ValueError('Select an exact existing named view')
    r=value['resolution']
    if not isinstance(r,list) or len(r)!=2 or any(type(n) not in INTEGER_TYPES or not 64<=n<=1024 for n in r):
        raise ValueError('Rhino render resolution must be 64–1024')
    return value
