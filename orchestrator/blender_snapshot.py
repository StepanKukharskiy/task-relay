"""Blender-side, explicitly scoped semantic snapshots for candidate comparisons."""
import hashlib
import json
import math

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def properties(value):
    result={}
    for prop in value.bl_rna.properties:
        key=prop.identifier
        if key in ('rna_type','name','name_full','is_updated','is_updated_data','is_updated_transform',
                   'session_uid','users','tag','is_evaluated','original'):continue
        if prop.type not in ('BOOLEAN','INT','FLOAT','STRING','ENUM','POINTER'):continue
        try:
            v=getattr(value,key)
            if prop.type=='POINTER':v=v.name if v and hasattr(v,'name') else None
            elif getattr(prop,'is_array',False):v=list(v)
            elif isinstance(v,set):v=sorted(v)
            json.dumps(v,allow_nan=False)
            result[key]=v
        except (AttributeError,TypeError,ValueError):continue
    return result

def world_dimensions(obj,graph,meters_per_unit):
    """Tight world-axis extents of evaluated geometry, expressed in meters.

    Object.dimensions retains the object's local axes. Transforming its bounding
    box also overestimates rotated non-box geometry, so measure actual evaluated
    vertices, including modifiers and parent transforms, instead.
    """
    if obj.type not in ('MESH','CURVE','SURFACE','FONT','META'):return None
    evaluated=obj.evaluated_get(graph)
    mesh=evaluated.to_mesh()
    try:
        if mesh is None or not mesh.vertices:return None
        if len(mesh.vertices)>1000000:raise ValueError('Evaluated mesh exceeds one million vertices')
        low=[math.inf]*3;high=[-math.inf]*3
        for vertex in mesh.vertices:
            point=evaluated.matrix_world @ vertex.co
            for axis in range(3):
                value=float(point[axis])*meters_per_unit
                if not math.isfinite(value):raise ValueError('Nonfinite world geometry: '+obj.name)
                low[axis]=min(low[axis],value);high[axis]=max(high[axis],value)
        return [high[i]-low[i] for i in range(3)]
    finally:evaluated.to_mesh_clear()

def snapshot():
    import bpy
    if len(bpy.data.objects)>5000:raise ValueError('Scene exceeds the 5000-object limit')
    bpy.context.view_layer.update()
    graph=bpy.context.evaluated_depsgraph_get()
    scene=bpy.context.scene
    meters=float(scene.unit_settings.scale_length)
    if not math.isfinite(meters) or meters<=0:raise ValueError('Invalid scene unit scale')
    objects={}
    for o in bpy.data.objects:
        data={'type':o.type,'matrix_world':[list(r) for r in o.matrix_world],
              'parent':o.parent.name if o.parent else None,'collections':sorted(c.name for c in o.users_collection),
              'materials':[s.material.name if s.material else None for s in o.material_slots],
              'modifiers':[properties(m) for m in o.modifiers],
              'constraints':[properties(c) for c in o.constraints],
              'hide_render':o.hide_render,'hide_viewport':o.hide_viewport}
        if o.type=='MESH':
            mesh=o.data
            if len(mesh.vertices)>1000000:raise ValueError('Mesh exceeds one million vertices')
            data['mesh_hash']=digest({'vertices':[list(v.co) for v in mesh.vertices],
                'edges':[list(e.vertices) for e in mesh.edges],
                'polygons':[(list(p.vertices),p.material_index,p.use_smooth) for p in mesh.polygons],
                'uv_layers':[(u.name,[list(v.uv) for v in u.data]) for u in mesh.uv_layers]})
        elif o.data:data['data']=properties(o.data)
        objects[o.name]=data
    materials={}
    for m in bpy.data.materials:
        # Unused, non-retained datablocks disappear on save/reopen (including
        # Blender's default Material after a generated scene deletes the cube).
        # They are not part of the persisted candidate's material contract.
        if m.users == 0 and not m.use_fake_user:continue
        data={'properties':properties(m)}
        if m.node_tree:
            data['nodes']=[{'name':n.name,'type':n.bl_idname,'properties':properties(n),
                'inputs':[(s.identifier,properties(s).get('default_value')) for s in n.inputs]} for n in m.node_tree.nodes]
            data['links']=sorted((l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in m.node_tree.links)
        materials[m.name]=data
    dimensions={}
    for obj in bpy.data.objects:
        value=world_dimensions(obj,graph,meters)
        if value is not None:dimensions[obj.name]=value
    return {'objects':objects,'materials':materials,'camera':scene.camera.name if scene.camera else None,
            'dimensions':dimensions,
            'dimension_measurement':{'version':2,'basis':'evaluated_geometry_world_axes','units':'Meters','meters_per_scene_unit':meters},
            'collections':{c.name:sorted(o.name for o in c.objects) for c in bpy.data.collections},
            'frame':scene.frame_current}

def compare(before,after,checks):
    errors=[];changed=set(checks['changed_objects'])
    if set(before['objects'])!=set(after['objects']):errors.append('Object names/count changed')
    for name in changed:
        if name not in before['objects'] or name not in after['objects']:errors.append('Missing requested object: '+name)
    for name,obj in before['objects'].items():
        if name in after['objects'] and ((checks['preserve_other_objects'] and name not in changed) or (checks['preserve_cameras'] and obj['type']=='CAMERA')):
            if obj!=after['objects'][name]:errors.append('Preservation failed for object: '+name)
    if checks['preserve_cameras'] and before['camera']!=after['camera']:errors.append('Active camera changed')
    # The baseline is loaded from JSON, which turns tuple-valued socket/link
    # records into lists. Compare their canonical data, not Python containers.
    if checks['preserve_materials'] and digest(before['materials'])!=digest(after['materials']):errors.append('Material properties or node graphs changed')
    if before['collections']!=after['collections']:errors.append('Collection membership changed')
    if before['frame']!=after['frame']:errors.append('Active frame changed')
    for name,expected in checks['expected_dimensions'].items():
        actual=after['dimensions'].get(name)
        if actual is None or len(actual)!=3 or any(not math.isfinite(a) or a<0 for a in actual):
            errors.append('Missing or invalid dimension measurement: '+name)
    return errors

def dimension_warnings(after,checks):
    warnings=[]
    for name,expected in checks['expected_dimensions'].items():
        actual=after['dimensions'].get(name)
        if actual is None or len(actual)!=3 or any(not math.isfinite(a) or a<0 for a in actual):continue
        if any(abs(a-b)>max(1e-4,abs(b)*1e-4) for a,b in zip(actual,expected)):
            warnings.append(f'{name}: measured dimensions {actual}; expected {expected} (world axes, meters).')
    return warnings
