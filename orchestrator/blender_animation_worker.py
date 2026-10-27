"""Fixed Blender-side transform animation, independent reopen checks and frame render."""
import json
import hashlib
import os
from pathlib import Path
import struct
import sys
import time
import zlib
import base64
sys.dont_write_bytecode=True
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


def save_progress(root,state):
    """Small durable intent/receipt; archive packaging belongs to the host."""
    temp=root/'frames.tmp'
    with temp.open('w') as stream:
        json.dump(state,stream);stream.flush();os.fsync(stream.fileno())
    temp.replace(root/'frames.json')


def compact_png(path,resolution):
    """Lossless samples/colour; move nonvisual text chunks into the frame receipt."""
    data=path.read_bytes()
    if len(data)<33 or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid frame PNG')
    chunks=[];compressed=[];offset=8
    while offset<len(data):
        if offset+12>len(data):raise ValueError('Truncated PNG chunk')
        size=struct.unpack('>I',data[offset:offset+4])[0];end=offset+12+size
        if end>len(data):raise ValueError('Truncated PNG chunk')
        kind=data[offset+4:offset+8];body=data[offset+8:end-4]
        if zlib.crc32(kind+body)!=struct.unpack('>I',data[end-4:end])[0]:raise ValueError('PNG checksum mismatch')
        chunks.append((kind,data[offset:end]));offset=end
        if kind==b'IDAT':compressed.append(body)
    if chunks[0][0]!=b'IHDR' or chunks[-1][0]!=b'IEND':raise ValueError('Invalid PNG structure')
    width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',data[16:29])
    if [width,height]!=resolution or (depth,color,compression,filtering,interlace)!=(8,2,0,0,0):
        raise ValueError('Expected noninterlaced RGB8 frame')
    expected=height*(1+width*3);decoder=zlib.decompressobj()
    samples=decoder.decompress(b''.join(compressed),expected+1)
    if len(samples)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Invalid PNG sample payload')
    packed=zlib.compress(samples,6);kind=b'IDAT'
    replacement=struct.pack('>I',len(packed))+kind+packed+struct.pack('>I',zlib.crc32(kind+packed))
    result=bytearray(data[:8]);written=False;metadata=[]
    for kind,raw in chunks:
        if kind==b'IDAT':
            if not written:result.extend(replacement);written=True
        elif kind in (b'tEXt',b'zTXt',b'iTXt'):metadata.append(base64.b64encode(raw).decode('ascii'))
        else:result.extend(raw)
    # Never trade more bytes for recompression. No resizing, quantization or sample changes.
    if len(result)<len(data):
        temp=path.with_suffix('.compact.tmp')
        with temp.open('xb') as stream:
            stream.write(result);stream.flush();os.fsync(stream.fileno())
        temp.replace(path)
        return metadata
    return []


def render_frames(root,m,render_frame,clock=None):
    clock=clock or time.monotonic
    batch=json.loads((root/'batch.json').read_text())
    raw=(root/'frames.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=batch['state_sha256']:
        raise ValueError('Frame ledger changed before render')
    state=json.loads(raw)
    if set(state['frames'])!={str(f) for f in range(m['frame_start'],m['frame_end']+1)}:
        raise ValueError('Frame scope differs')
    retained=sum((root/p).stat().st_size for p in ('candidate.blend','checks.json','frames.json'))
    seen=set()
    for f,row in state['frames'].items():
        if row['path']!=f'frames/{int(f):06d}.png':raise ValueError('Frame path differs')
        if row['state'] not in ('completed','pending'):raise ValueError('Unresolved frame intent')
        if row['state']=='completed' and (state.get('version')!=2 or row['sha256'] not in seen):
            retained+=(root/row['path']).stat().st_size;seen.add(row['sha256'])
    for f in range(m['frame_start'],m['frame_end']+1):
        row=state['frames'][str(f)]
        if row['state']=='completed':continue
        if clock()>=batch['deadline']:raise ValueError('Time budget exhausted between frames')
        path=root/row['path']
        if path.exists() or path.is_symlink():raise ValueError('Frame output exists; no replay')
        row.update(state='in_progress',attempt=batch['assignment']);save_progress(root,state)
        metadata=render_frame(f,path)
        if path.is_symlink() or not path.is_file():raise ValueError('Frame output is not a regular file')
        data=path.read_bytes()
        if len(data)<24 or data[:8]!=b'\x89PNG\r\n\x1a\n' or struct.unpack('>II',data[16:24])!=tuple(m['resolution']):
            raise ValueError('Frame PNG dimensions/signature mismatch')
        digest=hashlib.sha256(data).hexdigest()
        if state.get('version')!=2 or digest not in seen:retained+=len(data)
        if retained>batch['retained_bytes']:raise ValueError('Checkpoint retained-byte budget exceeded')
        seen.add(digest)
        row.update(state='completed',sha256=digest)
        if metadata:row['png_text']=metadata
        save_progress(root,state)
        print('RELAY_ANIMATION_FRAME '+str(f),flush=True)


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
    elif mode=='frames':
        scene.render.film_transparent=False
        scene.render.use_file_extension=True;scene.render.image_settings.color_mode='RGB';scene.render.image_settings.color_depth='8'
        scene.cycles.seed=0;scene.cycles.use_animated_seed=False
        scene.render.use_persistent_data=True
        def render_frame(f,path):
            scene.frame_set(f)
            render(path,m)
            return compact_png(path,m['resolution'])
        render_frames(root,m,render_frame)
    else:raise ValueError('Unknown animation operation')
    print('RELAY_ANIMATION_OK',flush=True)

if __name__=='__main__':main()
