"""Fixed project fixtures; no generated code, providers, or live user decisions."""
import json
from pathlib import Path

CREATE = '''# -*- coding: utf-8 -*-
import Rhino
import System.Drawing
material = Rhino.DocObjects.Material()
material.Name = "Terracotta"
material.DiffuseColor = System.Drawing.Color.FromArgb(185, 85, 55)
mi = doc.Materials.Add(material)
layer = Rhino.DocObjects.Layer()
layer.Name = "Architecture"
li = doc.Layers.Add(layer)
for name, low, high in [
    ("Plinth", (-5,-4,-0.4), (5,4,0)),
    ("Tower", (-1,-1,0), (1,1,4)),
    ("Canopy", (-3,-2,4), (3,2,4.25)),
    ("Screen", (-4,1,0), (-3.8,3,2))]:
    attr = Rhino.DocObjects.ObjectAttributes()
    attr.Name = name
    attr.LayerIndex = li
    attr.MaterialIndex = mi
    attr.MaterialSource = Rhino.DocObjects.ObjectMaterialSource.MaterialFromObject
    box = Rhino.Geometry.BoundingBox(Rhino.Geometry.Point3d(*low), Rhino.Geometry.Point3d(*high))
    doc.Objects.AddBrep(Rhino.Geometry.Brep.CreateFromBox(box), attr)
for name, location in [("Overview", (13,-17,12)), ("Rear", (-13,17,10))]:
    vp = Rhino.Display.RhinoViewport()
    vp.Size = System.Drawing.Size(320,240)
    vp.ChangeToParallelProjection(True)
    vp.SetCameraLocations(Rhino.Geometry.Point3d(0,0,2), Rhino.Geometry.Point3d(*location))
    vp.ZoomBoundingBox(Rhino.Geometry.BoundingBox(Rhino.Geometry.Point3d(-6,-5,-1),Rhino.Geometry.Point3d(6,5,7)))
    view = Rhino.DocObjects.ViewInfo(vp)
    view.Name = name
    if doc.NamedViews.Add(view) < 0:raise ValueError("Cannot save camera")
'''


def contract(mode='create', changed=None, height=4, canopy=6):
    return dict(mode=mode,units='Meters',changed_objects=changed or [],allow_additions=mode=='create',
        expected_object_count=4, expected_dimensions={'Tower':[2,2,height],'Canopy':[canopy,4,.25], 'Plinth':[10,8,.4]},
        preview={'resolution':[320,240]})


def edit_script(ident, x=1, y=1, z=1):
    return '''import Rhino
import System
ident=System.Guid(%r)
transform=Rhino.Geometry.Transform.Scale(Rhino.Geometry.Plane.WorldXY, %r, %r, %r)
if not doc.Objects.Replace(ident, doc.Objects.FindId(ident).Geometry.Duplicate()):raise ValueError("Replace failed")
geometry=doc.Objects.FindId(ident).Geometry.Duplicate()
if not geometry.Transform(transform):raise ValueError("Transform failed")
if not doc.Objects.Replace(ident, geometry):raise ValueError("Replace failed")
''' % (ident,x,y,z)


def run(folder, invoke):
    from tests.test_rhino_operations import inputs, MEDIA
    from tests.test_blender_operations import operation
    from orchestrator.runtime import file_hash
    selected=[]
    def preserve():
        for value in selected:
            if file_hash(value['path'])!=value['sha256']:raise ValueError('Prior project version changed')
    def choose(name,delivery):
        preserve()
        p=delivery/'candidate.3dm'
        selected.append(dict(stage=name,path=str(p),sha256=file_hash(p),decision='Explicit fixed-fixture selection; not user acceptance'))
        (folder/'project-versions.json').write_text(json.dumps(selected,indent=2))
        return p
    def inspect(name,source):
        def prepare(rt,root):
            aid=rt.register(source,'Exact selected fixture version',path='source.3dm')
            return operation('rhino.inspect',[dict(artifact=aid,path='source.3dm',purpose='Inspect saved project',authority='Explicit fixture selection',media_type=MEDIA)])
        d=invoke(name,prepare)
        return json.loads((d/'inspection.json').read_text())
    def render(name,source,view):
        def prepare(rt,root):
            p=root/'render.json';p.write_text(json.dumps(dict(version=1,engine='rhino_render',named_view=view,resolution=[320,240])))
            args=[]
            for path,media in ((source,MEDIA),(p,'application/json')):
                aid=rt.register(path,'Selected fixture render input',path=path.name)
                args.append(dict(artifact=aid,path=path.name,purpose='Render exact saved version',authority='Explicit fixture selection',media_type=media))
            op=operation('rhino.render',args);op['execution']['parameters']={'manifest_sha256':file_hash(p)}
            return op
        invoke(name,prepare);preserve()
    source=choose('v1',invoke('project-create',lambda rt,root:inputs(rt,root,script=CREATE,contract=contract())))
    inventory=inspect('project-inspect-v1',source)
    ids={o['name']:k for k,o in inventory['objects'].items()}
    render('project-render-v1',source,'Overview')
    for stage,ident,factors,height,width in [
        ('v2',ids['Tower'],(1,1,1.25),5,6),
        ('v3',ids['Canopy'],(1.2,1,1),5,7.2),
        ('v4',ids['Tower'],(1,1,.9),4.5,7.2)]:
        if stage=='v4':
            invoke('project-rejected-edit',lambda rt,root:inputs(rt,root,source.read_bytes(),
                edit_script(ids['Screen'],z=2),contract('edit',[ids['Tower']],5,7.2)),expected_failure=True)
            preserve()
        source=choose(stage,invoke('project-edit-'+stage,lambda rt,root:inputs(rt,root,source.read_bytes(),
            edit_script(ident,*factors),contract('edit',[ident],height,width))))
        inspect('project-inspect-'+stage,source)
    render('project-render-v4-overview',source,'Overview')
    render('project-render-v4-rear',source,'Rear')
    preserve()
