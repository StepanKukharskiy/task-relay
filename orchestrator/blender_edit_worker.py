"""Fixed lifecycle around an explicitly approved host script; this is not a sandbox."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_snapshot import snapshot,compare,dimension_warnings

def open_scene(path):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False,use_scripts=False)
    if bpy.context.preferences.filepaths.use_scripts_auto_execute:raise ValueError('Embedded auto-execution is enabled')

def self_contained():
    import bpy
    if bpy.data.libraries:raise ValueError('Linked libraries require a selected dependency bundle; deferred to B03')
    for i in bpy.data.images:
        if i.source not in ('GENERATED','VIEWER') and not (i.packed_file or i.packed_files):
            raise ValueError('Unpacked image dependency: '+i.name)
    for group in (bpy.data.movieclips,bpy.data.sounds,bpy.data.fonts,bpy.data.volumes,bpy.data.cache_files):
        for i in group:
            p=getattr(i,'filepath','')
            if p and p!='<builtin>' and not getattr(i,'packed_file',None):raise ValueError('External dependency: '+i.name)
    editor=bpy.context.scene.sequence_editor
    if editor:
        strips=getattr(editor,'strips',getattr(editor,'sequences',None))
        if strips is None or len(strips):raise ValueError('Sequence-editor dependencies are outside this editing slice')

def render(path,preview):
    import bpy
    scene=bpy.context.scene
    camera=bpy.data.objects.get(preview['camera'])
    if not camera or camera.type!='CAMERA':raise ValueError('Selected preview camera is missing')
    scene.camera=camera;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=preview['samples']
    scene.render.resolution_x,scene.render.resolution_y=preview['resolution'];scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.filepath=str(path)
    scene.render.use_compositing=False;scene.render.use_sequencer=False
    bpy.ops.render.render(write_still=True)

def main():
    import bpy
    mode,source,script,contract,out=sys.argv[sys.argv.index('--')+1:]
    out=Path(out);checks=json.loads(Path(contract).read_text())
    open_scene(out/'candidate.blend' if mode=='verify' else source)
    self_contained()
    if mode=='before':
        before=snapshot()
        if set(checks['changed_objects'])-before['objects'].keys():raise ValueError('Requested object missing')
        (out/'checks.json').write_text(json.dumps({'before':before,'passed':False,'phase':'before'},allow_nan=False))
        render(out/'before.png',checks['preview'])
    elif mode=='edit':
        code=Path(script).read_text()
        exec(compile(code,script,'exec'),{'__name__':'__main__','__file__':script,'bpy':bpy})
        bpy.context.view_layer.update()
        self_contained()
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'candidate.blend'),check_existing=False)
    elif mode=='verify':
        evidence=json.loads((out/'checks.json').read_text());after=snapshot()
        errors=compare(evidence['before'],after,checks)
        evidence.update(after=after,passed=not errors,errors=errors,warnings=dimension_warnings(after,checks),phase='verified',
            scope='Object names, collection membership, active frame, mesh vertices/topology/UVs, transforms, modifier/constraint scalar settings, camera scalar properties, material/node/socket properties. Not full Blender semantic equivalence.')
        (out/'checks.json').write_text(json.dumps(evidence,allow_nan=False))
        if errors:raise ValueError('; '.join(errors))
        render(out/'after.png',checks['preview'])
    else:raise ValueError('Unknown mode')
    print('RELAY_EDIT_'+mode.upper()+'_OK',flush=True)

if __name__=='__main__':main()
