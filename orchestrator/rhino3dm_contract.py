"""Dependency-free, data-only contract for standalone 3DM creation."""
import json
import math

MEDIA = 'application/vnd.rhino'
LIBRARY_VERSION = '8.35.0'
MAX_OBJECTS = 10000
MAX_POINTS = 200000
MAX_FACES = 400000
DESCRIPTION = '''Version 1 geometry specification:
{version:1,units:"Meters"|"Millimeters"|"Centimeters"|"Feet"|"Inches",
 tolerance:positive number,layers:[{name:string,color:[r,g,b]}],objects:[...]}.
Each object has a unique name, layer (exact declared layer name), and type:
point: {type:"point",name,layer,point:[x,y,z]}.
polyline: {type:"polyline",name,layer,points:[[x,y,z],...]}.
mesh: {type:"mesh",name,layer,vertices:[[x,y,z],...],faces:[[a,b,c] or [a,b,c,d],...]}.
Mesh face indices are zero-based; each face uses distinct indices. Repeat the
first point to close a polyline. Meshes may be open (for example terrain).
Coordinates are in the declared units, finite and within +/-10000000.
Tolerance is 0.000000001–1; it is document metadata, not permission to change geometry.
Limits across the whole model: 10000 objects, 200000 points/vertices, 400000 faces,
100 layers. Names: 1–100 characters, no controls, leading/trailing spaces or ::.
Uses rhino3dm only; creates a new version-8 .3dm. No arbitrary scripts, imported
models, Rhino commands, plugins, booleans, NURBS construction, rendering or previews.
Reopens using rhino3dm and compares geometry, names, layers, colors, units and tolerance.
Library checks do not establish native Rhino verification, design/source fidelity
or visual approval. Use rhino.* in a separately approved stage when those are needed.
'''


def load(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate geometry specification key: ' + key)
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('Invalid geometry specification fields; see rhino3dm.create geometry_schema')


def name(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 100 or value != value.strip()
            or '::' in value or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ValueError('Invalid geometry/layer name')


def point(value):
    if (not isinstance(value, list) or len(value) != 3 or any(type(n) not in (int, float)
            or not math.isfinite(n) or abs(n) > 10000000 for n in value)):
        raise ValueError('Geometry coordinates must be three bounded finite numbers')


def validate(value):
    fields(value, ('version', 'units', 'tolerance', 'layers', 'objects'))
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Unsupported geometry specification version')
    if value['units'] not in ('Meters', 'Millimeters', 'Centimeters', 'Feet', 'Inches'):
        raise ValueError('Unsupported geometry units')
    tolerance = value['tolerance']
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 1e-9 <= tolerance <= 1:
        raise ValueError('Invalid geometry tolerance')
    if not isinstance(value['layers'], list) or not 1 <= len(value['layers']) <= 100:
        raise ValueError('Expected 1–100 layers')
    layers = set()
    for layer in value['layers']:
        fields(layer, ('name', 'color')); name(layer['name'])
        if layer['name'].casefold() in layers: raise ValueError('Duplicate layer name')
        layers.add(layer['name'].casefold())
        color = layer['color']
        if not isinstance(color, list) or len(color) != 3 or any(type(n) is not int or not 0 <= n <= 255 for n in color):
            raise ValueError('Layer color must contain three RGB bytes')
    layer_names = {layer['name'] for layer in value['layers']}
    if not isinstance(value['objects'], list) or not 1 <= len(value['objects']) <= MAX_OBJECTS:
        raise ValueError('Expected 1–10000 geometry objects')
    names = set(); points = 0; faces = 0
    for obj in value['objects']:
        if not isinstance(obj, dict) or not isinstance(obj.get('type'), str):
            raise ValueError('Missing geometry type')
        kind = obj['type']
        extra = {'point': ('point',), 'polyline': ('points',), 'mesh': ('vertices', 'faces')}
        if kind not in extra: raise ValueError('Unsupported geometry type; use an explicit Rhino stage if needed')
        fields(obj, ('type', 'name', 'layer', *extra[kind])); name(obj['name']); name(obj['layer'])
        if obj['name'] in names: raise ValueError('Duplicate object name')
        names.add(obj['name'])
        if obj['layer'] not in layer_names: raise ValueError('Object refers to an undeclared layer')
        vertices = [obj['point']] if kind == 'point' else obj['points'] if kind == 'polyline' else obj['vertices']
        minimum = {'point': 1, 'polyline': 2, 'mesh': 3}[kind]
        if not isinstance(vertices, list) or not minimum <= len(vertices) <= MAX_POINTS:
            raise ValueError('Invalid geometry point count')
        points += len(vertices)
        if points > MAX_POINTS: raise ValueError('Model point limit exceeded')
        for vertex in vertices: point(vertex)
        if kind == 'polyline' and any(a == b for a, b in zip(vertices, vertices[1:])):
            raise ValueError('Polyline contains a zero-length segment')
        if kind == 'mesh':
            if not isinstance(obj['faces'], list) or not 1 <= len(obj['faces']) <= MAX_FACES:
                raise ValueError('Invalid mesh face count')
            faces += len(obj['faces'])
            if faces > MAX_FACES: raise ValueError('Model face limit exceeded')
            for face in obj['faces']:
                if (not isinstance(face, list) or len(face) not in (3, 4)
                        or any(type(i) is not int or not 0 <= i < len(vertices) for i in face)
                        or len(set(face)) != len(face)):
                    raise ValueError('Invalid mesh face indices')
    return value
