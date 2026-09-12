"""Fixed Blender asset append/pack and independent portable-candidate verification."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_edit_worker import open_scene,self_contained,render
from blender_snapshot import snapshot,digest

def image_hash(image):
    if not image.packed_file:raise ValueError('Image was not packed: '+image.name)
    return hashlib.sha256(image.packed_file.data).hexdigest()

def clear_local_library_metadata():
    import bpy
    if not bpy.data.libraries:return
    for prop in bpy.data.bl_rna.properties:
        if prop.type=='COLLECTION':
            for item in getattr(bpy.data,prop.identifier):
                if getattr(item,'library',None):raise ValueError('Persistent/nested linked datablock is unsupported: '+item.name)
    # Blender keeps weak append provenance in a Library ID even for local assets.
    # Remove that record only after proving no datablock depends on a library.
    for library in list(bpy.data.libraries):bpy.data.libraries.remove(library)

def pack_images(root,manifest):
    import bpy
    # These can hide file references outside the supported image/library manifest.
    for group in getattr(bpy.data,'node_groups',[]):
        if group.bl_idname=='GeometryNodeTree':raise ValueError('Geometry Nodes dependency bundles are not supported in this version')
    for material in getattr(bpy.data,'materials',[]):
        if material.node_tree and any(n.bl_idname=='ShaderNodeScript' for n in material.node_tree.nodes):raise ValueError('External shader scripts are outside the asset bundle scope')
    for obj in getattr(bpy.data,'objects',[]):
        if any(m.type in ('MESH_CACHE','MESH_SEQUENCE_CACHE','FLUID','CLOTH','SOFT_BODY','PARTICLE_SYSTEM','OCEAN') for m in obj.modifiers):raise ValueError('Simulation/cache dependencies are outside the asset bundle scope')
    allowed={str((root/f['path']).resolve()):f for f in manifest['files'] if f['kind']=='image'}
    records={}
    clear_local_library_metadata()
    for image in bpy.data.images:
        if image.source in ('GENERATED','VIEWER'):continue
        if image.source!='FILE':raise ValueError('Only single-file image textures are supported')
        if image.packed_file:
            records[image.name]={'sha256':image_hash(image),'origin':'already packed'};continue
        source=Path(bpy.path.abspath(image.filepath,library=image.library)).resolve()
        f=allowed.get(str(source))
        if not f:raise ValueError('Unselected external image: '+image.name+' '+str(source))
        if hashlib.sha256(source.read_bytes()).hexdigest()!=f['sha256']:raise ValueError('Image source changed')
        image.filepath=str(source);image.reload()
        # reload invalidates Blender's lazy image buffer; accessing pixels loads it.
        if len(image.pixels)<4 or not image.has_data:raise ValueError('Image cannot be decoded: '+image.name)
        if image.size[0]*image.size[1]>16777216:raise ValueError('Texture exceeds 16 megapixels')
        image.pack()
        if image_hash(image)!=f['sha256']:raise ValueError('Packed image bytes differ from selected version')
        records[image.name]={'sha256':f['sha256'],'origin':f['path']}
    self_contained()
    return records

def load_meshes(path,names):
    import bpy
    with bpy.data.libraries.load(str(path),link=False) as (available,target):
        if set(names)-set(available.objects):raise ValueError('Named library object is missing')
        # Blender replaces this list's names with datablock objects on exit.
        target.objects=list(names)
    if any(not obj or obj.type!='MESH' or obj.name!=name for obj,name in zip(target.objects,names)):
        raise ValueError('Only exact named mesh objects can be appended')
    return target.objects

def build(root,out,manifest):
    import bpy
    open_scene(root/manifest['scene'])
    initial_images=pack_images(root,manifest)
    before=snapshot();appended=[];bindings=[];modified_materials=set()
    for item in manifest['imports']:
        if item['type']=='append_objects':
            if any(n in bpy.data.objects for n in item['names']):raise ValueError('An imported name already exists; no silent renaming')
            objects=load_meshes(root/item['library'],item['names'])
            collection=bpy.data.collections.get(item['collection'])
            if collection is None:
                collection=bpy.data.collections.new(item['collection']);bpy.context.scene.collection.children.link(collection)
            for obj,name in zip(objects,item['names']):
                collection.objects.link(obj);appended.append(name)
        else:
            material=bpy.data.materials.get(item['material'])
            node=material.node_tree.nodes.get(item['node']) if material and material.node_tree else None
            if not node or node.bl_idname!='ShaderNodeTexImage':raise ValueError('Selected material Image Texture node is missing')
            if item['image_name'] in bpy.data.images:raise ValueError('Image name already exists; choose an explicit new name')
            image=bpy.data.images.load(str(root/item['file']),check_existing=False);image.name=item['image_name']
            node.image=image;modified_materials.add(material.name)
            bindings.append({'material':material.name,'node':node.name,'image':image.name,'file':item['file']})
    bpy.context.view_layer.update()
    packed=pack_images(root,manifest)
    for name,record in initial_images.items():
        if name in packed and record['sha256']==packed[name]['sha256']:packed[name]=record
    # Blender does not retain unused datablocks without a fake user on save.
    packed={name:record for name,record in packed.items() if bpy.data.images[name].users or bpy.data.images[name].use_fake_user}
    after=snapshot()
    if set(after['objects'])!=set(before['objects'])|set(appended):raise ValueError('Append brought unexpected objects/dependencies')
    for name,value in before['objects'].items():
        if digest(value)!=digest(after['objects'][name]):raise ValueError('Existing object changed: '+name)
    for name,value in before['materials'].items():
        if name not in modified_materials and digest(value)!=digest(after['materials'][name]):raise ValueError('Unselected material changed: '+name)
    if before['camera']!=after['camera'] or before['frame']!=after['frame']:raise ValueError('Camera/frame changed')
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'candidate.blend'),check_existing=False)
    evidence={'passed':False,'before':before,'candidate':after,'packed_images':packed,'appended_objects':appended,
              'texture_bindings':bindings,'scope':'Exact selected assets; existing object snapshots and unselected materials preserved; all file images packed. Not full Blender semantic equivalence.'}
    (out/'checks.json').write_text(json.dumps(evidence,allow_nan=False))

def verify(root,out,manifest):
    import bpy
    open_scene(root/'candidate.blend');self_contained()
    evidence=json.loads((out/'checks.json').read_text())
    if digest(snapshot())!=digest(evidence['candidate']):raise ValueError('Reopened candidate differs from saved snapshot')
    actual={i.name:image_hash(i) for i in bpy.data.images if i.source not in ('GENERATED','VIEWER')}
    if actual!={name:p['sha256'] for name,p in evidence['packed_images'].items()}:raise ValueError('Packed image versions changed on reopen')
    for binding in evidence['texture_bindings']:
        node=bpy.data.materials[binding['material']].node_tree.nodes[binding['node']]
        if not node.image or node.image.name!=binding['image']:raise ValueError('Texture binding changed')
    render(out/'preview.png',manifest['preview'])
    evidence.update(passed=True,reopened_from=str(root/'candidate.blend'),all_images_packed=True)
    (out/'checks.json').write_text(json.dumps(evidence,allow_nan=False))

def main():
    mode,root,out=sys.argv[sys.argv.index('--')+1:];root=Path(root);out=Path(out)
    manifest=json.loads((root/'manifest.json').read_text())
    if mode=='build':build(root,out,manifest)
    elif mode=='verify':verify(root,out,manifest)
    else:raise ValueError('Unknown asset worker mode')
    print('RELAY_ASSETS_'+mode.upper()+'_OK',flush=True)

if __name__=='__main__':main()
