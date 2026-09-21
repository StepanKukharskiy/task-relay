"""Standalone library generation; never dispatches Rhino or executes user code."""
import hashlib
import json
import math
from pathlib import Path
import time

from . import rhino3dm_contract as contract
from .runtime import file_hash, safe_file
from .workers import atomic


def available():
    try:
        import rhino3dm
    except ImportError as exc:
        raise ValueError('Standalone 3DM creation requires task-relay[rhino3dm] in the worker runtime; no Rhino fallback') from exc
    if rhino3dm.__version__ != contract.LIBRARY_VERSION:
        raise ValueError('Standalone 3DM creation requires rhino3dm==' + contract.LIBRARY_VERSION + '; no Rhino fallback')
    return rhino3dm


def xyz(p):
    return [p.X, p.Y, p.Z]


def geometry_points(geometry, kind):
    if kind == 'point': return [xyz(geometry.Location)]
    if kind == 'polyline': return [xyz(geometry.Point(i)) for i in range(geometry.PointCount)]
    return [xyz(geometry.Vertices.Point3dAt(i)) for i in range(len(geometry.Vertices))]


def verify(path, value, library):
    """Compare the saved file to requested data, including interior mesh vertices."""
    reopened = library.File3dm.Read(str(path))
    if reopened is None: raise ValueError('rhino3dm could not reopen the saved candidate')
    if (reopened.Settings.ModelUnitSystem != getattr(library.UnitSystem, value['units'])
            or reopened.Settings.ModelAbsoluteTolerance != value['tolerance']):
        raise ValueError('Saved units/tolerance differ from the geometry specification')
    layers = [{'name': layer.Name, 'color': list(layer.Color[:3])} for layer in reopened.Layers]
    if layers != value['layers']: raise ValueError('Saved layers/colors differ from the geometry specification')
    objects = list(reopened.Objects)
    if len(objects) != len(value['objects']): raise ValueError('Saved object count differs from the geometry specification')
    reports = []
    types = {'point': library.Point, 'polyline': library.PolylineCurve, 'mesh': library.Mesh}
    for saved, expected in zip(objects, value['objects']):
        geometry = saved.Geometry; attrs = saved.Attributes; kind = expected['type']
        if not isinstance(geometry, types[kind]) or not geometry.IsValid:
            raise ValueError('Invalid or unexpected saved geometry: ' + expected['name'])
        if (attrs.Name != expected['name'] or not 0 <= attrs.LayerIndex < len(layers)
                or layers[attrs.LayerIndex]['name'] != expected['layer']):
            raise ValueError('Saved object names/layers differ from the geometry specification')
        points = geometry_points(geometry, kind)
        wanted = [expected['point']] if kind == 'point' else expected['points'] if kind == 'polyline' else expected['vertices']
        relative, absolute = 1e-12, 1e-9
        if len(points) != len(wanted) or any(not math.isclose(a, b, rel_tol=relative, abs_tol=absolute)
                for p, q in zip(points, wanted) for a, b in zip(p, q)):
            raise ValueError('Saved coordinates differ from the geometry specification: ' + expected['name'])
        faces = []
        if kind == 'mesh':
            faces = [list(face[:3] if face[2] == face[3] else face) for face in geometry.Faces]
            if faces != expected['faces']: raise ValueError('Saved mesh topology differs from the geometry specification')
        reports.append(dict(name=attrs.Name, type=kind, layer=expected['layer'], points=len(points), faces=len(faces),
            bounds=[[min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]],
            max_coordinate_error=max(abs(a-b) for p,q in zip(points,wanted) for a,b in zip(p,q)),
            coordinate_comparison=dict(relative_tolerance=relative, absolute_tolerance=absolute),
            geometry_sha256=hashlib.sha256(json.dumps([points, faces], separators=(',', ':')).encode()).hexdigest()))
    return dict(passed=True, verification_engine='rhino3dm', library_version=library.__version__,
        native_rhino_verified=False, visual_review='not_performed', source_fidelity='not_verified',
        units=value['units'], tolerance=value['tolerance'], layers=layers, objects=reports,
        candidate_sha256=file_hash(path))


def create(value, path, maximum):
    value = contract.validate(value); library = available(); path = Path(path)
    if path.exists() or path.is_symlink(): raise ValueError('Candidate exists; no replacement or replay')
    model = library.File3dm()
    model.ApplicationName = 'Task Relay / rhino3dm'
    model.ApplicationDetails = 'Standalone library generation; not executed or verified in Rhino.'
    model.Settings.ModelUnitSystem = getattr(library.UnitSystem, value['units'])
    model.Settings.ModelAbsoluteTolerance = value['tolerance']
    layers = {}
    for spec in value['layers']:
        layer = library.Layer(); layer.Name = spec['name']; layer.Color = (*spec['color'], 255)
        index = model.Layers.Add(layer)
        if index < 0: raise ValueError('rhino3dm failed to add layer')
        layers[spec['name']] = index
    for spec in value['objects']:
        attrs = library.ObjectAttributes(); attrs.Name = spec['name']; attrs.LayerIndex = layers[spec['layer']]
        if spec['type'] == 'point': geometry = library.Point(library.Point3d(*spec['point']))
        elif spec['type'] == 'polyline': geometry = library.PolylineCurve([library.Point3d(*p) for p in spec['points']])
        else:
            geometry = library.Mesh(); geometry.Vertices.UseDoublePrecisionVertices = True
            for p in spec['vertices']: geometry.Vertices.AddPoint3d(*p)
            for face in spec['faces']: geometry.Faces.AddFace(*face)
            geometry.Normals.ComputeNormals()
        if not geometry.IsValid: raise ValueError('Invalid generated geometry: ' + spec['name'])
        if model.Objects.Add(geometry, attrs).int == 0: raise ValueError('rhino3dm failed to add geometry')
    if not model.Write(str(path), 8): raise ValueError('rhino3dm failed to write candidate')
    if not 0 < path.stat().st_size <= maximum: raise ValueError('3DM candidate exceeds output byte limit')
    return verify(path, value, library)


def execute(frozen, control, documents):
    workspace = Path(frozen['workspace']); control = Path(control); out = workspace/'delivery'
    for name in ('rhino3dm_contract.py', 'rhino3dm_document.py'):
        if frozen['runtime_sources'].get(name) != file_hash(Path(__file__).with_name(name)):
            raise ValueError('Standalone 3DM implementation changed after dispatch was frozen')
    available()
    manifest = next(d for d,i in zip(documents, frozen['inputs']) if i['media_type'] == 'application/json')
    value = contract.validate(contract.load(manifest['text']))
    if out.exists() or out.is_symlink(): raise ValueError('3DM delivery exists; no replacement or replay')
    receipt = dict(capability='rhino3dm.create', execution_mode='standalone_library', host_execution=False,
        native_rhino_verified=False, library='rhino3dm', library_version=contract.LIBRARY_VERSION,
        assignment=frozen['assignment_id'], input_versions=[{k:i[k] for k in ('artifact','path','sha256')} for i in frozen['inputs']],
        runtime_sources={n:frozen['runtime_sources'][n] for n in ('rhino3dm_contract.py','rhino3dm_document.py')},
        limits=frozen['limits'], passed=False, selected=False)
    with (control/'rhino3dm-intent.json').open('x') as stream: json.dump(receipt, stream)
    out.mkdir(); atomic(out/'execution.json', receipt)
    try:
        checks = create(value, out/'candidate.3dm', frozen['limits']['output_bytes'])
        for item in frozen['inputs']:
            if file_hash(safe_file(workspace, item['path'])) != item['sha256']:
                raise ValueError('Standalone 3DM input changed during creation')
        atomic(out/'checks.json', checks)
        receipt.update(passed=True, candidate_sha256=checks['candidate_sha256'], recorded_at=time.time())
        atomic(out/'execution.json', receipt)
        if sum(p.stat().st_size for p in out.iterdir()) > frozen['limits']['output_bytes']:
            raise ValueError('Standalone 3DM delivery exceeds total output byte limit')
    except Exception as exc:
        receipt.update(passed=False, error=str(exc), recorded_at=time.time()); atomic(out/'execution.json', receipt)
        atomic(control/'operation.json', dict(outcome='failed', execution=frozen['execution'], reason=str(exc), usage={}, **receipt))
        raise
    summary = '3DM generated and reopened with rhino3dm; not opened or verified in Rhino. Awaiting independent review and selection.'
    details = dict(outcome='completed', execution=frozen['execution'], summary=summary, validation=checks, usage={}, **receipt)
    atomic(control/'operation.json', details)
    atomic(workspace/'.relay/result.json', dict(assignment_id=frozen['assignment_id'], summary=summary,
        decision='delivered', instruction='', checks=[dict(criterion=1, passed=True, evidence='delivery/checks.json; delivery/execution.json: '+summary)]))
    return details
