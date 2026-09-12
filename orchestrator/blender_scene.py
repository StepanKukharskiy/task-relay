"""Fixed Blender-side program. All user scene data is validated by blender_host.

No user scripts, expressions, paths, imports, drivers, addons or existing blends.
Invoked only by the registered host adapter, never supplied by a model.
"""
import json
import math
from pathlib import Path
import sys


def main():
    import bpy
    from mathutils import Vector
    mode, data_path, destination = sys.argv[sys.argv.index('--')+1:]
    data=json.loads(Path(data_path).read_text());out=Path(destination)
    if mode=='build':
        bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
        for index,obj in enumerate(data['objects']):
            if obj['shape']=='cube':bpy.ops.mesh.primitive_cube_add(size=1)
            elif obj['shape']=='cylinder':bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=0.5,depth=1)
            elif obj['shape']=='mesh':
                geometry=bpy.data.meshes.new('RelayGeometry_%03d'%index)
                geometry.from_pydata(obj['vertices'],[],obj['faces']);geometry.update()
                created=bpy.data.objects.new('RelayObject_%03d'%index,geometry)
                bpy.context.collection.objects.link(created);bpy.context.view_layer.objects.active=created
            else:raise ValueError('Unsupported scene shape')
            mesh=bpy.context.object;mesh.name='RelayObject_%03d'%index
            mesh.location=obj['position'];mesh.scale=obj['size'];mesh.rotation_euler=obj['rotation']
            mat=bpy.data.materials.new('RelayMaterial_%03d'%index)
            mat.diffuse_color=(*obj['color'],1);mat.use_nodes=True
            bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(*obj['color'],1)
            bsdf.inputs['Roughness'].default_value=0.35;mesh.data.materials.append(mat)
        bpy.ops.object.camera_add(location=data['camera']['position'])
        camera=bpy.context.object;camera.name='RelayCamera'
        camera.rotation_euler=(Vector(data['camera']['target'])-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='ORTHO';camera.data.ortho_scale=data['camera']['scale'];bpy.context.scene.camera=camera
        bpy.ops.object.light_add(type='SUN',location=(20,-30,60));bpy.context.object.rotation_euler=(0.4,-0.6,-0.5)
        bpy.context.object.data.energy=3
        scene=bpy.context.scene;scene.world.color=(0.3,0.3,0.3)
        scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=data['samples']
        scene.render.resolution_x=data['resolution'][0];scene.render.resolution_y=data['resolution'][1];scene.render.resolution_percentage=100
        scene.render.image_settings.file_format='PNG';scene.render.filepath=str(out/'preview.png')
        bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
        print('RELAY_SCENE_SAVED',flush=True)
    elif mode=='verify-render':
        bpy.ops.wm.open_mainfile(filepath=str(out/'scene.blend'),load_ui=False,use_scripts=False)
        meshes=[o for o in bpy.data.objects if o.type=='MESH']
        assert len(meshes)==len(data['objects']), 'Mesh count differs from scene data'
        assert bpy.context.scene.camera is not None, 'Camera missing'
        for index,expected in enumerate(data['objects']):
            obj=bpy.data.objects['RelayObject_%03d'%index]
            for field,actual in [('position',obj.location),('size',obj.scale),('rotation',obj.rotation_euler)]:
                assert all(abs(a-b)<0.001 for a,b in zip(actual,expected[field])), 'Scene transform differs from specification'
            assert all(math.isfinite(v) for row in obj.matrix_world for v in row)
            assert len(obj.data.vertices)>0
            if expected['shape']=='mesh':
                assert len(obj.data.vertices)==len(expected['vertices']), 'Mesh vertex count differs'
                assert [list(p.vertices) for p in obj.data.polygons]==expected['faces'], 'Mesh topology differs'
                for vertex,coordinate in zip(obj.data.vertices,expected['vertices']):
                    assert all(abs(a-b)<=max(1e-5,abs(b)*2e-7) for a,b in zip(vertex.co,coordinate)), 'Mesh coordinates differ'
        print('RELAY_GEOMETRY_CHECKED',json.dumps({'objects':len(meshes),
            'vertices':sum(len(o.data.vertices) for o in meshes),'faces':sum(len(o.data.polygons) for o in meshes)}),flush=True)
        bpy.context.scene.cycles.device='CPU'
        bpy.context.scene.render.filepath=str(out/'preview.png')
        bpy.ops.render.render(write_still=True)
        print('RELAY_SCENE_VERIFIED_RENDERED',len(meshes),flush=True)
    else:raise ValueError('Unknown fixed operation mode')


if __name__=='__main__':main()
