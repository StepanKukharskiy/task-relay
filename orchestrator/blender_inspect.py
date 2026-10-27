"""Fixed Blender-side native-scene inventory. No user Python or save/render operations."""
import hashlib
import json
from pathlib import Path
import sys


def export_geometry(source,path):
    """Exact evaluated world meshes; shared geometry handoff, never inferred from pixels."""
    import bpy, math, hashlib
    objects=[];total=0;faces=0
    graph=bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH' or obj.hide_render:continue
        evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh()
        try:
            total+=len(mesh.vertices);faces+=len(mesh.polygons)
            if faces>200000:raise ValueError('Geometry handoff exceeds 200000 faces')
            if total>100000:raise ValueError('Geometry handoff exceeds 100000 vertices')
            vertices=[list(evaluated.matrix_world@v.co) for v in mesh.vertices]
            if any(not math.isfinite(n) for v in vertices for n in v):raise ValueError('Nonfinite geometry')
            objects.append(dict(name=obj.name,vertices=vertices,faces=[list(p.vertices) for p in mesh.polygons]))
        finally:evaluated.to_mesh_clear()
    value=dict(version=1,units='Meters' if bpy.context.scene.unit_settings.system=='METRIC' and bpy.context.scene.unit_settings.scale_length==1 else 'Blender units',
               source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),objects=objects)
    raw=json.dumps(value,allow_nan=False).encode()
    if len(raw)>10000000:raise ValueError('Geometry handoff exceeds 10 MB')
    path.write_bytes(raw)

def main():
    import bpy
    args=sys.argv[sys.argv.index('--')+1:];source,destination=args[:2]
    geometry=args[2] if len(args)==3 else None
    bpy.ops.wm.open_mainfile(filepath=source,load_ui=False,use_scripts=False)
    if len(bpy.data.objects)>5000:raise ValueError('Scene exceeds the 5000-object inspection limit')
    scene=bpy.context.scene
    objects=[]
    for obj in bpy.data.objects:
        value={'name':obj.name,'type':obj.type,'location':list(obj.location),'rotation_euler':list(obj.rotation_euler),
               'scale':list(obj.scale),'dimensions':list(obj.dimensions),'matrix_world':[list(row) for row in obj.matrix_world],
               'parent':obj.parent.name if obj.parent else None,
               'collections':sorted(c.name for c in obj.users_collection),
               'materials':[s.material.name if s.material else None for s in obj.material_slots],
               'modifiers':[{'name':m.name,'type':m.type} for m in obj.modifiers]}
        if obj.type=='MESH':value['geometry']={'vertices':len(obj.data.vertices),'edges':len(obj.data.edges),'polygons':len(obj.data.polygons)}
        if obj.type=='CAMERA':value['camera']={'type':obj.data.type,'lens':obj.data.lens,'ortho_scale':obj.data.ortho_scale,
                                              'clip_start':obj.data.clip_start,'clip_end':obj.data.clip_end}
        objects.append(value)
    dependencies=[]
    for image in bpy.data.images:
        if image.source in ('GENERATED','VIEWER'):continue
        dependencies.append({'kind':'image','name':image.name,'path':image.filepath,
            'resolved_path':bpy.path.abspath(image.filepath,library=image.library),
            'packed':bool(image.packed_file or image.packed_files),'included_in_bundle':False})
    for library in bpy.data.libraries:
        dependencies.append({'kind':'library','name':library.name,'path':library.filepath,
            'resolved_path':bpy.path.abspath(library.filepath),'packed':bool(getattr(library,'packed_file',None)),
            'included_in_bundle':False})
    for collection in (bpy.data.movieclips,bpy.data.sounds,bpy.data.fonts):
        for item in collection:
            if not item.filepath or item.filepath=='<builtin>':continue
            dependencies.append({'kind':item.bl_rna.identifier,'name':item.name,'path':item.filepath,
                'resolved_path':bpy.path.abspath(item.filepath,library=item.library),
                'packed':bool(getattr(item,'packed_file',None)),'included_in_bundle':False})
    inventory={'blender_version':bpy.app.version_string,'source_copy':source,'active_scene':scene.name,
        'collections':[{'name':c.name,'objects':sorted(o.name for o in c.objects),
                        'children':sorted(child.name for child in c.children)} for c in bpy.data.collections],
        'objects':objects,'materials':[{'name':m.name,'diffuse_color':list(m.diffuse_color),
            'node_types':[n.bl_idname for n in m.node_tree.nodes] if m.node_tree else []} for m in bpy.data.materials],
        'spatial':{'native_system':scene.unit_settings.system,'native_length_unit':scene.unit_settings.length_unit,'meters_per_coordinate':scene.unit_settings.scale_length if scene.unit_settings.system!='NONE' else None,'declared_json':scene.get('TaskRelay.Spatial') if isinstance(scene.get('TaskRelay.Spatial'),str) else None},
        'camera':scene.camera.name if scene.camera else None,
        'render':{'engine':scene.render.engine,'resolution':[scene.render.resolution_x,scene.render.resolution_y],
                  'percentage':scene.render.resolution_percentage,'fps':scene.render.fps,'fps_base':scene.render.fps_base,
                  'frame_start':scene.frame_start,'frame_end':scene.frame_end,'frame_current':scene.frame_current},
        'dependencies':dependencies,
        'embedded_texts':[{'name':t.name,'bytes':len(t.as_string().encode()),
            'sha256':hashlib.sha256(t.as_string().encode()).hexdigest(),'use_module':t.use_module} for t in bpy.data.texts],
        'auto_scripts_enabled':bool(bpy.context.preferences.filepaths.use_scripts_auto_execute),
        'limitations':['Inventory only; no editing, rendering, asset import or Python execution requested.',
            'Dependency references are reported, not a complete portable bundle or proof of missing assets.',
            'Opening the selected native file uses host permissions and may resolve linked libraries.']}
    if inventory['auto_scripts_enabled']:raise ValueError('Embedded auto-execution must be disabled')
    data=json.dumps(inventory,ensure_ascii=False,allow_nan=False,indent=2).encode()
    if len(data)>1800000:raise ValueError('Complete scene inventory exceeds 1.8 MB; no truncated inventory returned')
    with Path(destination).open('xb') as stream:stream.write(data)
    if geometry:export_geometry(source,Path(geometry))
    print('RELAY_INSPECTION_WRITTEN',len(objects),flush=True)


if __name__=='__main__':main()
