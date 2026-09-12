import copy
import unittest
from orchestrator.blender_host import scene
from tests.test_blender_operations import scene_data


def mesh_scene():
    value=scene_data();value['version']=2
    value['objects'][0].update(shape='mesh',vertices=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],
                              faces=[[0,2,1],[0,1,3],[1,2,3],[2,0,3]])
    return value


class Tests(unittest.TestCase):
    def test_new_mesh_data_keeps_primitive_contract_unchanged(self):
        self.assertEqual(scene(mesh_scene(),allow_mesh=True),mesh_scene())
        with self.assertRaises(ValueError):scene(mesh_scene())
        self.assertEqual(scene(scene_data()),scene_data())

    def test_bad_indices_nonfinite_degenerate_and_code_fields_rejected(self):
        def vertices(d,v):d['objects'][0]['vertices']=v
        changes=[lambda d:d['objects'][0].update(script='print(1)'),
                 lambda d:d['objects'][0].update(faces=[[0,1,99]]),
                 lambda d:d['objects'][0].update(faces=[[0,1,True]]),
                 lambda d:d['objects'][0].update(faces=[[0,0,1]]),
                 lambda d:vertices(d,[[0,0,0],[1,0,0],[float('nan'),1,0],[0,0,1]]),
                 lambda d:vertices(d,[[0,0,0],[1,0,0],[2,0,0],[0,0,1]])]
        for change in changes:
            d=mesh_scene();change(d)
            with self.subTest(d=d),self.assertRaises(ValueError):scene(d,allow_mesh=True)

    def test_total_vertex_limit_applies_across_objects(self):
        d=mesh_scene();d['objects'][0]['vertices']=[[0,0,0],[1,0,0],[0,1,0]]+[[0,0,1]]*59997
        d['objects']*=2
        with self.assertRaisesRegex(ValueError,'total mesh budget'):scene(d,allow_mesh=True)

    def test_open_surface_not_misrepresented_as_printable_solid(self):
        d=mesh_scene();d['objects'][0]['faces']=[[0,2,1]]
        self.assertEqual(len(scene(d,allow_mesh=True)['objects'][0]['faces']),1)

if __name__=='__main__':unittest.main()
