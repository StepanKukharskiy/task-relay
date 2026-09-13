"""Coverage drift and option boundaries for the Blender qualification command."""
import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from orchestrator import execution
from orchestrator.blender_host import scene
from orchestrator.blender_animation import validate as animation
from orchestrator.blender_snapshot import snapshot, compare
from tests.test_blender_operations import scene_data
from tests.test_blender_pipeline_live import COVERAGE


class Tests(unittest.TestCase):
    def test_registered_capabilities_versions_and_parameters_have_qualification(self):
        expected={
            'blender.startup':set(),'blender.scene':set(),'blender.mesh_scene':set(),'blender.inspect':set(),
            'blender.run_python':{'scene_sha256','script_sha256','checks_sha256','permissions'},
            'blender.import_asset':{'manifest_sha256'},'blender.animate':{'manifest_sha256'}}
        actual={k:v for k,v in execution.REGISTRY.items() if k.startswith('blender.')}
        self.assertEqual(set(actual),set(COVERAGE))
        self.assertEqual(set(actual),set(expected))
        for name,spec in actual.items():
            self.assertEqual(spec['version'],1,'Update qualification for a new operation version')
            self.assertEqual(set(spec['parameters']),expected[name])

    def test_scene_numeric_extremes_validated_without_large_renders(self):
        data=scene_data();data['objects']*=500
        for upper in (False,True):
            d=copy.deepcopy(data)
            d['resolution']=[1600,1600] if upper else [64,64];d['samples']=32 if upper else 1
            d['camera']['scale']=10000 if upper else .1
            for obj in d['objects']:
                obj.update(position=[10000 if upper else -10000]*3,
                           size=[10000 if upper else .001]*3,
                           rotation=[100 if upper else -100]*3,color=[1 if upper else 0]*3)
            scene(d)
        changes=[('position',10001),('position',-10001),('size',0),('size',10001),
                 ('rotation',101),('rotation',-101),('color',1.01),('color',-.01)]
        for field,n in changes:
            with self.subTest(field=field,n=n):
                d=scene_data();d['objects'][0][field]=[n]*3
                with self.assertRaises(ValueError):scene(d)
        for field,n in [('samples',0),('samples',33),('resolution',[63,64]),('resolution',[1601,64])]:
            d=scene_data();d[field]=n
            with self.subTest(field=field,n=n),self.assertRaises(ValueError):scene(d)

    def test_animation_option_limits_without_rendering_maximum_workload(self):
        m=dict(version=1,scene_sha256='a'*64,mode='final',frame_start=1,frame_end=120,fps=60,
               camera='Camera',resolution=[1024,1024],samples=16,tracks=[])
        for i in range(20):
            frames=list(range(1,20))+[120]
            m['tracks'].append(dict(object='Object'+str(i),property=('location','rotation_euler','scale')[i%3],
                                   keys=[dict(frame=f,value=[1,1,1]) for f in frames]))
        animation(m)
        for key,value in [('tracks',m['tracks']+[m['tracks'][0]]),('frame_end',121),('fps',61),('samples',17),('resolution',[1026,1024])]:
            d=copy.deepcopy(m);d[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):animation(d)
        m.update(mode='preview',resolution=[512,512],samples=4)
        animation(m)
        m['resolution']=[513,512]
        with self.assertRaises(ValueError):animation(m)

    def test_unused_material_disappearing_on_reopen_is_not_a_scene_change(self):
        def material(name,users,fake=False):
            return NS(name=name,users=users,use_fake_user=fake,node_tree=None,roughness=.5,
                      bl_rna=NS(properties=[NS(identifier='roughness',type='FLOAT',is_array=False)]))
        orphan=material('Unused default',0);used=material('Used',1);retained=material('Retained',0,True)
        materials=[orphan,used,retained]
        bpy=NS(data=NS(objects=[],materials=materials,collections=[]),context=NS(scene=NS(camera=None,frame_current=1)))
        checks=dict(changed_objects=[],preserve_other_objects=True,preserve_cameras=True,
                    preserve_materials=True,expected_dimensions={})
        with patch.dict('sys.modules',{'bpy':bpy}):
            before=snapshot();materials.remove(orphan)
            self.assertEqual(compare(before,snapshot(),checks),[])
            self.assertEqual(set(before['materials']),{'Used','Retained'})
            used.roughness=.7
            self.assertIn('Material properties or node graphs changed',compare(before,snapshot(),checks))
            used.roughness=.5;materials.remove(retained)
            self.assertIn('Material properties or node graphs changed',compare(before,snapshot(),checks))


if __name__=='__main__':unittest.main()
