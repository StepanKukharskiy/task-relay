"""World-coordinate measurement regressions; --native runs a tiny local lifecycle."""
import json,math,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from orchestrator.blender_snapshot import world_dimensions,dimension_warnings

class Transform:
    def __matmul__(self,p):return (10-p[1]*3,20+p[0]*2,p[2])

class WorldDimensions(unittest.TestCase):
    def object(self,points):
        self.cleared=0
        def clear():self.cleared+=1
        evaluated=NS(matrix_world=Transform(),to_mesh=lambda:NS(vertices=[NS(co=p) for p in points]),to_mesh_clear=clear)
        return NS(type='MESH',name='Fixture',evaluated_get=lambda graph:evaluated)

    def test_rotated_scaled_translated_geometry_and_units(self):
        obj=self.object([(0,0,0),(2,0,0),(0,1,0),(0,0,3)])
        self.assertEqual(world_dimensions(obj,None,.01),[.03,.03999999999999998,.03])
        self.assertEqual(self.cleared,1)

    def test_invalid_geometry_releases_evaluated_mesh(self):
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            world_dimensions(self.object([(float('inf'),0,0)]),None,1)
        self.assertEqual(self.cleared,1)

    def test_empty_and_non_geometry_have_no_fabricated_dimensions(self):
        self.assertIsNone(world_dimensions(self.object([]),None,1));self.assertEqual(self.cleared,1)
        self.assertIsNone(world_dimensions(NS(type='CAMERA'),None,1))

    def test_real_difference_is_still_reported(self):
        checks={'expected_dimensions':{'Beam':[.08,4,.08]}}
        self.assertEqual(dimension_warnings({'dimensions':{'Beam':[.08,4,.08]}},checks),[])
        self.assertEqual(len(dimension_warnings({'dimensions':{'Beam':[.08,3,.08]}},checks)),1)

SCRIPT='''import bpy,math
from mathutils import Vector
def box(name,size,rotation=(0,0,0)):
    bpy.ops.mesh.primitive_cube_add(size=2)
    obj=bpy.context.object;obj.name=name;obj.scale=tuple(v/2 for v in size)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    obj.rotation_euler=rotation;return obj
box('Y',[4,.08,.08],(0,0,math.pi/2))
box('Z',[4,.08,.08],(0,math.pi/2,0))
box('Diagonal',[4,.08,.08],(0,0,math.pi/4))
parent=bpy.data.objects.new('Parent',None);bpy.context.scene.collection.objects.link(parent)
parent.location=(7,-2,1);parent.rotation_euler.z=math.pi/2;parent.scale=(-2,3,1)
child=box('Child',[2,1,1]);child.parent=parent
mesh=bpy.data.meshes.new('Triangle');mesh.from_pydata([(0,0,0),(2,0,0),(0,1,0)],[],[(0,1,2)]);mesh.update()
tri=bpy.data.objects.new('Triangle',mesh);bpy.context.scene.collection.objects.link(tri);tri.rotation_euler.z=math.pi/4
array=box('Array',[2,2,2]);mod=array.modifiers.new('Copies','ARRAY');mod.count=2;mod.use_relative_offset=False;mod.use_constant_offset=True;mod.constant_offset_displace=(3,0,0)
bpy.ops.object.camera_add(location=(12,-15,12));cam=bpy.context.object;cam.name='Camera';cam.rotation_euler=(Vector((0,0,0))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=25;bpy.context.scene.camera=cam
bpy.ops.object.light_add(type='AREA',location=(0,0,10));bpy.context.object.name='Light';bpy.context.object.data.energy=500
'''

def native():
    root=Path(__file__).resolve().parents[1]
    exe='/Applications/Blender.app/Contents/MacOS/Blender'
    from orchestrator.blender_edit import validate_checks
    with tempfile.TemporaryDirectory(prefix='relay-world-dimensions-') as folder:
        work=Path(folder).resolve();out=work/'delivery';out.mkdir()
        bundled=work/'bundled';bundled.mkdir()
        for name in ('blender_edit_worker.py','blender_snapshot.py'):
            (bundled/name).write_bytes((root/'orchestrator'/name).read_bytes())
        script=work/'fixture.py';script.write_text(SCRIPT)
        expected={'Y':[.08,4,.08],'Z':[.08,.08,4],'Diagonal':[4.08/math.sqrt(2)]*2+[.08],
                  'Child':[3,4,1],'Triangle':[3/math.sqrt(2),2/math.sqrt(2),0],'Array':[5,2,2]}
        checks=dict(mode='create',objects=list(expected)+['Parent','Camera','Light'],expected_dimensions=expected,units='Meters',
                    changed_objects=[],preserve_other_objects=True,preserve_cameras=True,preserve_materials=True,
                    preview=dict(camera='Camera',resolution=[64,64],samples=1))
        contract=work/'checks.json';contract.write_text(json.dumps(validate_checks(checks)))
        for mode in ('before','edit','verify'):
            cmd=[exe,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(bundled/'blender_edit_worker.py'),'--',mode,'-',str(script),str(contract),str(out)]
            result=subprocess.run(cmd,capture_output=True,timeout=90)
            if result.returncode:raise AssertionError(mode+': '+result.stdout.decode()[-4000:]+result.stderr.decode()[-2000:])
            assert not (bundled/'__pycache__').exists(),'Native execution changed its bundled sources'
        evidence=json.loads((out/'checks.json').read_text())
        assert evidence['passed'] and not evidence['errors'] and not evidence['warnings'],evidence.get('warnings')
        assert evidence['after']['dimension_measurement']['basis']=='evaluated_geometry_world_axes'
        assert (out/'after.png').is_file()
        # Reopen the exact synthetic candidate, change only unit metadata in memory.
        probe=work/'units.py';probe.write_text('import sys,json,bpy\nsys.dont_write_bytecode=True\n'+
            'sys.path.insert(0,'+repr(str(root))+')\nfrom orchestrator.blender_snapshot import snapshot,dimension_warnings\n'+
            'bpy.ops.wm.open_mainfile(filepath='+repr(str(out/'candidate.blend'))+',load_ui=False,use_scripts=False)\n'+
            'bpy.context.scene.unit_settings.scale_length=.01\nr=snapshot()\n'+
            'assert abs(r["dimensions"]["Y"][1]-.04)<1e-6\n'+
            'assert len(dimension_warnings(r,{"expected_dimensions":{"Y":[.0008,.03,.0008]}}))==1\nprint("WORLD_UNITS_OK")\n')
        result=subprocess.run([exe,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(probe)],capture_output=True,timeout=60)
        assert result.returncode==0,result.stdout.decode()[-3000:]+result.stderr.decode()[-1000:]
        assert b'WORLD_UNITS_OK' in result.stdout
        print(json.dumps(dict(native_lifecycle='before/edit/save/reopen/verify/render passed',cases=list(expected),units='centimeter conversion passed',real_difference='warning retained',bundle_cache='no bytecode written in all three phases',warnings=evidence['warnings'],limits='64x64, one sample, existing worker deadlines',temporary_fixtures_removed=True)))

if __name__=='__main__':
    if '--native' in sys.argv:native()
    else:unittest.main()
