"""Fixed Blender-side transform animation, independent reopen checks and frame render."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_edit_worker import open_scene,self_contained,render
from blender_snapshot import snapshot,digest


def guard():
    import bpy
    self_contained()
    if len(bpy.data.scenes)!=1:raise ValueError('Select a single-scene file')
    if bpy.context.scene.rigidbody_world:raise ValueError('Rigid-body simulation is outside bounded animation v1')
    for prop in bpy.data.bl_rna.properties:
        if prop.type!='COLLECTION':continue
        for item in getattr(bpy.data,prop.identifier,[]):
            data=getattr(item,'animation_data',None)
            if data and data.drivers:raise ValueError('Driver expressions are outside bounded animation v1')
    if any(g.bl_idname=='GeometryNodeTree' for g in bpy.data.node_groups):raise ValueError('Geometry Nodes evaluation is outside bounded animation v1')
    for o in bpy.data.objects:
        if any(m.type in ('MESH_CACHE','MESH_SEQUENCE_CACHE','FLUID','CLOTH','SOFT_BODY','PARTICLE_SYSTEM','OCEAN') for m in o.modifiers):raise ValueError('Simulation/cache modifiers are outside bounded animation v1')
    for material in bpy.data.materials:
        if material.node_tree and any(n.bl_idname=='ShaderNodeScript' for n in material.node_tree.nodes):raise ValueError('OSL scripts are outside bounded animation v1')


def expected(keys,frame):
    if frame<=keys[0]['frame']:return keys[0]['value']
    for a,b in zip(keys,keys[1:]):
        if frame<=b['frame']:
            t=(frame-a['frame'])/(b['frame']-a['frame'])
            return [x+(y-x)*t for x,y in zip(a['value'],b['value'])]
    return keys[-1]['value']


def main():
    import bpy
    mode,source,root,frame=sys.argv[sys.argv.index('--')+1:];root=Path(root)
    m=json.loads((root/'manifest.json').read_text());scene_path=root/'candidate.blend'
    open_scene(source if mode=='build' else scene_path);guard();scene=bpy.context.scene
    camera=bpy.data.objects.get(m['camera'])
    if not camera or camera.type!='CAMERA':raise ValueError('Selected camera is missing')
    if mode=='build':
        original_frame=scene.frame_current
        before=snapshot()
        changed={t['object'] for t in m['tracks']}
        for name in changed:
            o=bpy.data.objects.get(name)
            if not o or o.parent or o.children or o.constraints or o.animation_data:raise ValueError('Tracks need existing unparented, unconstrained objects without prior animation: '+name)
        bpy.context.preferences.edit.keyframe_new_interpolation_type='LINEAR'
        for t in m['tracks']:
            o=bpy.data.objects[t['object']]
            if t['property']=='rotation_euler' and o.rotation_mode not in ('XYZ','XZY','YXZ','YZX','ZXY','ZYX'):raise ValueError('Euler track requires an Euler rotation mode')
            for key in t['keys']:
                setattr(o,t['property'],key['value'])
                if not o.keyframe_insert(data_path=t['property'],frame=key['frame']):raise ValueError('Keyframe insertion failed')
        scene.frame_start=m['frame_start'];scene.frame_end=m['frame_end'];scene.render.fps=m['fps'];scene.render.fps_base=1
        scene.camera=camera
        scene.frame_set(original_frame);bpy.context.view_layer.update()
        after=snapshot()
        # Compare underlying geometry/materials and all unedited object state at the same frame.
        for state in (before,after):
            state.pop('dimensions',None)
            for name in changed:state['objects'][name].pop('matrix_world',None)
            state['camera']=m['camera']
        if digest(before)!=digest(after):raise ValueError('Unexpected changes outside declared transforms/camera selection')
        (root/'checks.json').write_text(json.dumps({'passed':False,'preservation':after,'original_frame':original_frame,'changed_objects':sorted(changed)}))
        bpy.ops.wm.save_as_mainfile(filepath=str(scene_path),check_existing=False)
    elif mode=='verify':
        evidence=json.loads((root/'checks.json').read_text())
        scene.frame_set(evidence['original_frame']);after=snapshot();after.pop('dimensions',None)
        for name in evidence['changed_objects']:after['objects'][name].pop('matrix_world',None)
        if digest(after)!=digest(evidence['preservation']):raise ValueError('Candidate preservation differs after reopen')
        if (scene.frame_start,scene.frame_end,scene.render.fps,scene.render.fps_base)!=(m['frame_start'],m['frame_end'],m['fps'],1):raise ValueError('Frame range/FPS mismatch')
        for f in range(m['frame_start'],m['frame_end']+1):
            scene.frame_set(f)
            for t in m['tracks']:
                actual=getattr(bpy.data.objects[t['object']],t['property'])
                if any(abs(a-b)>max(1e-4,abs(b)*1e-5) for a,b in zip(actual,expected(t['keys'],f))):raise ValueError('Transform interpolation differs at frame '+str(f))
        evidence.update(passed=True,verified_frames=m['frame_end']-m['frame_start']+1,
            scope='Independent reopen; frame range/FPS; declared transform interpolation at every requested frame; scoped scene snapshot preservation. No general animation semantic or visual acceptance.')
        (root/'checks.json').write_text(json.dumps(evidence))
    elif mode=='frame':
        f=int(frame)
        if not m['frame_start']<=f<=m['frame_end']:raise ValueError('Frame outside approved range')
        scene.frame_set(f);scene.render.film_transparent=False
        scene.render.use_file_extension=True;scene.render.image_settings.color_mode='RGB';scene.render.image_settings.color_depth='8'
        scene.cycles.seed=0;scene.cycles.use_animated_seed=False
        render(root/f'frames/{f:06d}.png',m)
    else:raise ValueError('Unknown animation operation')
    print('RELAY_ANIMATION_OK',flush=True)

if __name__=='__main__':main()
