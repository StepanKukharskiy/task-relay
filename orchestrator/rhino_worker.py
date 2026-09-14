# -*- coding: utf-8 -*-
"""Fixed Rhino worker shared by Rhino 7 IronPython and Rhino 8 CPython."""
from __future__ import print_function
import hashlib
import json
import os
import io
import time
import traceback


def write(path, value, limit=1800000):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    if len(data) > limit:raise ValueError('Rhino evidence exceeds its complete-inventory limit')
    descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:stream.write(data)


def read_text(path):
    with io.open(str(path), 'r', encoding='utf-8') as stream:return stream.read()


def file_hash(path):
    with open(str(path), 'rb') as stream:return hashlib.sha256(stream.read()).hexdigest()


def load_code(path):
    # Let each interpreter honor the source encoding declaration. Python 2
    # rejects encoding declarations when compile() receives decoded Unicode.
    with open(path, 'rb') as stream:return compile(stream.read(), path, 'exec')


def xyz(point):return [float(point.X), float(point.Y), float(point.Z)]


def fingerprint(value):
    import Rhino
    options = Rhino.FileIO.SerializationOptions()
    return hashlib.sha256(value.ToJSON(options).encode('utf-8')).hexdigest()


def material_state(material):
    # Raw material archives include runtime RDK state which changes on an
    # otherwise unchanged save. Compare explicit native material properties.
    result = dict(name=material.Name or '')
    for key in ('DiffuseColor','AmbientColor','EmissionColor','SpecularColor','ReflectionColor','TransparentColor'):
        result[key] = int(getattr(material,key).ToArgb())
    for key in ('Reflectivity','Transparency','Shine','IndexOfRefraction','ReflectionGlossiness','RefractionGlossiness','FresnelIndexOfRefraction'):
        result[key] = float(getattr(material,key))
    for key in ('FresnelReflections','DisableLighting'):
        result[key] = bool(getattr(material,key))
    strings = material.GetUserStrings()
    result['user_strings'] = {key:strings[key] for key in strings.AllKeys}
    return result


def snapshot(doc):
    import Rhino
    objects = {}
    dependencies = []
    # The ObjectType overload omits hidden objects. Verification inventories the
    # saved document, including analytical geometry on hidden or locked layers.
    settings = Rhino.DocObjects.ObjectEnumeratorSettings()
    settings.NormalObjects = True
    settings.HiddenObjects = True
    settings.LockedObjects = True
    settings.ActiveObjects = True
    settings.ReferenceObjects = True
    settings.DeletedObjects = False
    settings.IdefObjects = False
    settings.VisibleFilter = False
    settings.IncludeLights = True
    for obj in doc.Objects.GetObjectList(settings):
        if obj.IsDeleted:continue
        if len(objects) >= 5000:raise ValueError('Rhino inventory exceeds 5000 objects')
        geo, attr = obj.Geometry, obj.Attributes
        box = geo.GetBoundingBox(True)
        if not box.IsValid:raise ValueError('Object has no valid bounding box')
        objects[str(obj.Id)] = dict(name=attr.Name or '', type=str(obj.ObjectType),
            valid=bool(geo.IsValid), bbox=[xyz(box.Min), xyz(box.Max)], dimensions=xyz(box.Diagonal),
            geometry_sha256=fingerprint(geo), attributes_sha256=fingerprint(attr),
            layer_index=attr.LayerIndex, material_index=attr.MaterialIndex)
        if obj.IsReference or obj.ObjectType == Rhino.DocObjects.ObjectType.InstanceReference:
            dependencies.append(dict(kind='reference_or_block', object=str(obj.Id)))
        if geo.UserData.Count or attr.UserData.Count:
            dependencies.append(dict(kind='custom_user_data', object=str(obj.Id)))
    materials = {}
    for mat in doc.Materials:
        if mat.IsDeleted:continue
        materials[str(mat.Id)] = material_state(mat)
        for texture in mat.GetTextures():
            if texture.FileName:dependencies.append(dict(kind='texture', path=texture.FileName))
    layers = {str(layer.Id):fingerprint(layer) for layer in doc.Layers if not layer.IsDeleted}
    views = {v.Name:dict(camera=xyz(v.Viewport.CameraLocation), target=xyz(v.Viewport.TargetPoint),
                        direction=xyz(v.Viewport.CameraDirection), up=xyz(v.Viewport.CameraUp),
                        parallel=bool(v.Viewport.IsParallelProjection),
                        frustum=[v.Viewport.FrustumLeft,v.Viewport.FrustumRight,v.Viewport.FrustumBottom,
                                 v.Viewport.FrustumTop,v.Viewport.FrustumNear,v.Viewport.FrustumFar]) for v in doc.NamedViews}
    if any(not d.IsDeleted for d in doc.InstanceDefinitions):dependencies.append(dict(kind='instance_definitions'))
    return dict(objects=objects, units=str(doc.ModelUnitSystem), tolerance=doc.ModelAbsoluteTolerance,
                angle_tolerance=doc.ModelAngleToleranceRadians, layers=layers, materials=materials,
                named_views=views, dependencies=dependencies, rhino_version=str(Rhino.RhinoApp.Version),
                limitations=['Scoped geometry/attribute and table snapshots, not full Rhino semantic equivalence.',
                            'Native input loads with host permissions; dependency discovery is not filesystem isolation.',
                            'Grasshopper is not invoked.'])


def preview(candidate, destination, resolution, named_view=None):
    import Rhino
    import System.Drawing
    # Open the saved file in the owned process, never an existing user's document.
    opened = Rhino.RhinoDoc.Open(str(candidate))
    doc = opened[0] if isinstance(opened, tuple) else opened
    if doc is None:raise ValueError('Cannot open saved candidate for viewport capture')
    # macOS does not reliably capture a newly added synthetic view. Use a native
    # document layout and its existing Perspective view instead.
    doc.Views.FourViewLayout(True)
    view = doc.Views.Find('Perspective', False) or doc.Views.ActiveView
    if view is None:raise ValueError('Cannot find Rhino preview view')
    doc.Views.ActiveView = view
    view.Maximized = True
    vp = view.ActiveViewport
    if named_view:
        index = doc.NamedViews.FindByName(named_view)
        if index < 0 or not doc.NamedViews.Restore(index, vp):
            raise ValueError('Cannot restore selected preview named view: ' + named_view)
    else:
        vp.ChangeToParallelProjection(True)
        vp.SetCameraDirection(Rhino.Geometry.Vector3d(-1, 1, -0.75), True)
    vp.DisplayMode = Rhino.Display.DisplayModeDescription.FindByName('Shaded')
    if not named_view:vp.ZoomExtents()
    view.Redraw()
    # A view created during startup has not yet received a native paint event.
    # Pump Rhino's UI before the single capture; this never reruns the model script.
    paint_deadline = time.time()+1
    while time.time() < paint_deadline:
        Rhino.RhinoApp.Wait()
        time.sleep(.02)
    capture = Rhino.Display.ViewCapture()
    capture.Width, capture.Height = resolution
    capture.DrawGrid = False
    capture.DrawAxes = False
    bitmap = capture.CaptureToBitmap(view)
    if bitmap is None:raise ValueError('Rhino viewport capture failed')
    try:bitmap.Save(str(destination), System.Drawing.Imaging.ImageFormat.Png)
    finally:bitmap.Dispose()


def render(request):
    import Rhino
    import System
    import System.Drawing
    from rhino_contract import validate_render
    manifest = validate_render(json.loads(read_text(request['manifest'])))
    source_hash = file_hash(request['source'])
    inspected = Rhino.RhinoDoc.OpenHeadless(request['source'])
    if inspected is None:raise ValueError('Cannot inspect selected render source')
    try:
        if snapshot(inspected)['dependencies']:raise ValueError('Render requires a self-contained source model')
    finally:inspected.Dispose()
    opened = Rhino.RhinoDoc.Open(request['source'])
    doc = opened[0] if isinstance(opened, tuple) else opened
    if doc is None:raise ValueError('Cannot open selected render model')
    index = doc.NamedViews.FindByName(manifest['named_view'])
    if index < 0:raise ValueError('Selected render named view does not exist')
    doc.Views.FourViewLayout(True)
    view = doc.Views.Find('Perspective', False) or doc.Views.ActiveView
    if view is None:raise ValueError('No native render viewport')
    doc.Views.ActiveView = view
    if not doc.NamedViews.Restore(index, view.ActiveViewport):raise ValueError('Cannot restore selected named view')
    settings = doc.RenderSettings
    settings.UseViewportSize = False
    settings.ImageSize = System.Drawing.Size(*manifest['resolution'])
    settings.RenderSource = Rhino.Render.RenderSettings.RenderingSources.NamedView
    settings.NamedView = manifest['named_view']
    doc.RenderSettings = settings
    renderer = Rhino.PlugIns.PlugIn.IdFromName('Rhino Render')
    if renderer == System.Guid.Empty:raise ValueError('Built-in Rhino Render is unavailable')
    previous = Rhino.Render.Utilities.DefaultRenderPlugInId
    destination = os.path.join(request['out'], 'render.png')
    if any(c in destination for c in ('"', '\n', '\r')):raise ValueError('Unsupported render destination')
    commands = []
    try:
        Rhino.Render.Utilities.SetDefaultRenderPlugIn(renderer)
        for command in ('_Render', '_-SaveRenderWindowAs "'+destination+'" _Enter', '_CloseRenderWindow'):
            ok = bool(Rhino.RhinoApp.RunScript(doc.RuntimeSerialNumber, command, False))
            commands.append(dict(command=command, passed=ok))
            if not ok:raise ValueError('Rhino render command failed: '+command)
        if not os.path.isfile(destination):raise ValueError('Rhino Render did not save the requested PNG')
        if file_hash(request['source']) != source_hash:raise ValueError('Render source changed')
        write(os.path.join(request['out'], 'checks.json'), dict(passed=True, engine='rhino_render',
            manifest=manifest, source_sha256=source_hash, render_sha256=file_hash(destination), commands=commands))
        return dict(render_sha256=file_hash(destination), engine='rhino_render')
    finally:
        Rhino.Render.Utilities.SetDefaultRenderPlugIn(previous)


def perform(request):
    import Rhino
    import scriptcontext
    import rhinoscriptsyntax
    from rhino_contract import validate_checks, compare
    mode, out = request['mode'], request['out']
    if int(Rhino.RhinoApp.Version.Major) != request['rhino_major']:
        raise ValueError('Rhino runtime version differs from the frozen application')
    if mode == 'startup':
        return {'rhino_version':str(Rhino.RhinoApp.Version), 'python_version':__import__('sys').version}
    if mode == 'render':return render(request)
    if mode == 'inspect':
        doc = Rhino.RhinoDoc.OpenHeadless(request['source'])
        if doc is None:raise ValueError('Cannot open selected Rhino model')
        try:write(os.path.join(out, 'inspection.json'), snapshot(doc))
        finally:doc.Dispose()
        return {}
    checks = validate_checks(json.loads(read_text(request['checks'])))
    source = request.get('source')
    if (checks['mode'] == 'edit') != bool(source):raise ValueError('Rhino mode/source mismatch')
    if mode == 'before':
        doc = Rhino.RhinoDoc.OpenHeadless(source) if source else Rhino.RhinoDoc.CreateHeadless(None)
        if doc is None:raise ValueError('Cannot create/open modeling document')
        try:
            if not source:doc.ModelUnitSystem = getattr(Rhino.UnitSystem, checks['units'])
            load_code(request['script'])
            before = snapshot(doc)
            if before['dependencies']:raise ValueError('Rhino editing requires a self-contained model without blocks or custom user data')
            if before['units'] != checks['units']:raise ValueError('Edit must preserve the selected model units')
            if set(checks['changed_objects']) - set(before['objects']):raise ValueError('Changed object UUID absent from source')
            write(request['baseline'], before)
        finally:doc.Dispose()
        return {}
    if mode == 'model':
        doc = Rhino.RhinoDoc.OpenHeadless(source) if source else Rhino.RhinoDoc.CreateHeadless(None)
        if doc is None:raise ValueError('Cannot create/open modeling document')
        original = scriptcontext.doc
        try:
            if not source:doc.ModelUnitSystem = getattr(Rhino.UnitSystem, checks['units'])
            scriptcontext.doc = doc
            code = load_code(request['script'])
            namespace = dict(__name__='__main__', __file__=request['script'], Rhino=Rhino,
                             rhinoscriptsyntax=rhinoscriptsyntax, scriptcontext=scriptcontext, doc=doc)
            eval(code, namespace)
            if scriptcontext.doc != doc:raise ValueError('Modeling script replaced the assigned document context')
            if snapshot(doc)['dependencies']:raise ValueError('Unsupported model dependencies')
            options = Rhino.FileIO.FileWriteOptions()
            options.FileVersion = request['rhino_major']
            if not doc.Write3dmFile(str(os.path.join(out, 'candidate.3dm')), options):raise ValueError('Rhino native save failed')
        finally:
            scriptcontext.doc = original
            doc.Dispose()
        return {}
    if mode == 'verify':
        candidate = os.path.join(out, 'candidate.3dm')
        doc = Rhino.RhinoDoc.OpenHeadless(str(candidate))
        if doc is None:raise ValueError('Cannot independently reopen saved Rhino candidate')
        try:after = snapshot(doc)
        finally:doc.Dispose()
        before = json.loads(read_text(request['baseline']))
        errors = compare(before, after, checks)
        if after['dependencies']:errors.append('Candidate has unsupported dependencies')
        write(os.path.join(out, 'checks.json'), dict(before=before, after=after, errors=errors, passed=not errors))
        if errors:raise ValueError('; '.join(errors))
        preview(candidate, os.path.join(out, 'preview.png'), checks['preview']['resolution'], checks['preview'].get('named_view'))
        return {'candidate_sha256':file_hash(candidate)}
    raise ValueError('Unknown Rhino worker phase')


def main(request_path, exit_process=None):
    import System
    request_path = str(request_path)
    request = json.loads(read_text(request_path))
    pid = int(System.Diagnostics.Process.GetCurrentProcess().Id)
    owner_path = os.path.splitext(request_path)[0]+'.owner.json'
    deadline = time.time()+10
    while not os.path.exists(owner_path) and time.time() < deadline:time.sleep(.02)
    owner = json.loads(read_text(owner_path))
    # Do not even exit a process if the launch was forwarded to an existing Rhino.
    if owner != {'pid':pid, 'token':request['token']}:
        raise ValueError('Rhino startup was not received by the owned process')
    # Confirm owned startup before potentially lengthy modeling or rendering.
    write(os.path.splitext(request_path)[0]+'.started.json',
          dict(pid=pid, token=request['token'], mode=request['mode']), 200000)
    result = dict(pid=pid, token=request['token'], mode=request['mode'], passed=False)
    try:
        result['details'] = perform(request)
        result['passed'] = True
    except BaseException:
        result['error'] = traceback.format_exc()[-16000:]
    write(os.path.splitext(request_path)[0]+'.result.json', result, 200000)
    # This is only the process whose PID was committed by our launch adapter.
    (exit_process or System.Environment.Exit)(0 if result['passed'] else 1)
