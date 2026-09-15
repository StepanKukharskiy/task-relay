import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from orchestrator import contracts as c
from orchestrator.runtime import Runtime,file_hash
from orchestrator.step_runner import execute
from orchestrator.blender_assets import validate,extract_bundle,bind_registered
from tests.test_blender_operations import operation
from tests.test_orchestrator import FakeFactory,plan

def inputs(rt,root):
    selected=[];files=[]
    for name,data,kind,media in [('source.blend',b'\xffnative','scene','application/x-blender'),('texture.png',b'\x89PNG\r\n\x1a\n\xfftexture','image','image/png')]:
        p=root/name;p.write_bytes(data);aid=rt.register(p,'Selected '+name,path=name)
        selected.append(dict(artifact=aid,path=name,purpose='Exact '+name,authority='User selection',media_type=media))
        files.append(dict(path='source/'+name,sha256=file_hash(p),kind=kind,provenance=dict(source='Fixture '+name,license=None)))
    manifest=dict(version=1,scene='source/source.blend',files=files,imports=[],preview=dict(camera='Camera',resolution=[64,64],samples=1))
    p=root/'assets.json';p.write_text(json.dumps(manifest));aid=rt.register(p,'Exact import manifest',path=p.name)
    selected.append(dict(artifact=aid,path=p.name,purpose='Approved import scope',authority='Explicit files and modes',media_type='application/json'))
    op=operation('blender.import_asset',selected);op['execution']['parameters']={'manifest_sha256':file_hash(p)}
    return op,manifest

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.fake=FakeFactory();self.rt=Runtime(self.root/'runtime',self.fake)
        self.app=patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture'));self.app.start()
        self.op,self.manifest=inputs(self.rt,self.root)
    def tearDown(self):self.app.stop();self.rt.close();self.tmp.cleanup()
    def frozen(self):
        self.rt.create(plan([self.op]));self.rt.tick('demo');a=self.fake.sessions[self.rt.task('demo','app')['latest']]
        control=Path(a['session']['control']);control.mkdir(parents=True)
        return a['frozen'],control
    def fake_run(self,argv,**kwargs):
        mode=argv[argv.index('--')+1];root=Path(argv[-2]);out=Path(argv[-1])
        if mode=='build':
            (root/'candidate.blend').write_bytes(b'packed candidate');(out/'checks.json').write_text(json.dumps({'passed':False}))
        else:
            self.assertFalse((root.parent/'asset-stage').exists())
            self.assertTrue((root/'source/texture.png').is_file())
            (out/'checks.json').write_text(json.dumps({'passed':True}))
            (out/'preview.png').write_bytes(b'\x89PNG\r\n\x1a\npreview')
        return subprocess.CompletedProcess(argv,0,('RELAY_ASSETS_'+mode.upper()+'_OK').encode(),b'')
    def test_binary_assets_bundle_relocation_lineage_and_no_replay(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_assets.subprocess.run',side_effect=self.fake_run) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
            with self.assertRaises(ValueError):execute(frozen,control)
            self.assertEqual(run.call_count,2)
        out=Path(frozen['workspace'])/'delivery';manifest=json.loads((out/'manifest.json').read_text())
        self.assertEqual(manifest['request']['files'],self.manifest['files']);self.assertFalse(manifest['selected'])
        with zipfile.ZipFile(out/'bundle.zip') as z:self.assertEqual(z.read('source/texture.png'),(self.root/'texture.png').read_bytes())
    def test_manifest_rejects_traversal_collisions_and_unsupported_modes(self):
        for path in ('../outside.png','/abs.png','C:/file.png','source/CON.png','candidate.blend','source\\texture.png'):
            m=copy.deepcopy(self.manifest);m['files'][1]['path']=path
            with self.assertRaises(ValueError):validate(m)
        m=copy.deepcopy(self.manifest);m['files'][1]['path']='SOURCE/SOURCE.BLEND'
        with self.assertRaises(ValueError):validate(m)
        m=copy.deepcopy(self.manifest);m['imports']=[{'type':'link'}]
        with self.assertRaisesRegex(ValueError,'Unsupported import'):validate(m)
    def test_missing_or_changed_selected_assets_stop_before_host(self):
        frozen,control=self.frozen();frozen['inputs'][1]['sha256']='0'*64
        with patch('orchestrator.blender_assets.subprocess.run') as run:
            with self.assertRaises(ValueError):execute(frozen,control)
            run.assert_not_called()
    def test_manifest_hash_mismatch_fails_preflight(self):
        self.op['execution']['parameters']['manifest_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'manifest hash'):bind_registered(self.rt,self.op)
    def test_future_asset_input_is_not_approved_by_initial_plan(self):
        a=copy.deepcopy(self.op);a['inputs'][0].pop('artifact');a['inputs'][0].update(from_task='producer',output='scene.blend')
        with self.assertRaisesRegex(ValueError,'already registered'):c.assignment(a)
    def test_timeout_keeps_receipt_without_verification_retry(self):
        frozen,control=self.frozen()
        with patch('orchestrator.blender_assets.subprocess.run',side_effect=subprocess.TimeoutExpired([],1,output=b'partial')) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(run.call_count,1)
        receipt=json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text());self.assertTrue(receipt['runs'][0]['timeout'])
    def test_source_mutation_during_build_blocks_bundle(self):
        frozen,control=self.frozen()
        def changed(argv,**kwargs):
            r=self.fake_run(argv,**kwargs);(Path(argv[-2])/'source/texture.png').write_bytes(b'changed');return r
        with patch('orchestrator.blender_assets.subprocess.run',side_effect=changed) as run:
            self.assertEqual(execute(frozen,control)['outcome'],'failed');self.assertEqual(run.call_count,1)
    def test_extraction_rejects_traversal(self):
        archive=self.root/'bad.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape',b'data')
        with self.assertRaises(ValueError):extract_bundle(archive,self.root/'extract',{'../escape':'0'*64},1000)
        self.assertFalse((self.root/'escape').exists())
    def test_extraction_rejects_changed_bytes_extra_entries_and_links(self):
        import hashlib
        expected={'file.png':hashlib.sha256(b'original').hexdigest()}
        for n,mode in enumerate(('bytes','extra','link')):
            archive=self.root/('bad-'+mode+'.zip')
            with zipfile.ZipFile(archive,'w') as z:
                if mode=='link':
                    info=zipfile.ZipInfo('file.png');info.external_attr=(0o120777<<16);z.writestr(info,b'original')
                else:z.writestr('file.png',b'changed' if mode=='bytes' else b'original')
                if mode=='extra':z.writestr('extra',b'unlisted')
            with self.assertRaises(ValueError):extract_bundle(archive,self.root/('extract-'+str(n)),expected,1000)
    def test_lazy_image_buffer_loads_before_packing_selected_bytes(self):
        from orchestrator.blender_assets_worker import pack_images
        texture_path=self.root/'texture.png'
        class Image:
            name='Fixture';source='FILE';library=None;packed_file=None;has_data=False;size=(2,2)
            filepath=str(texture_path)
            def reload(self):self.has_data=False
            @property
            def pixels(self):self.has_data=True;return [0,0,0,1]
            def pack(self):self.packed_file=SimpleNamespace(data=texture_path.read_bytes())
        image=Image();bpy=SimpleNamespace(data=SimpleNamespace(libraries=[],images=[image]),path=SimpleNamespace(abspath=lambda path,library=None:path))
        manifest=copy.deepcopy(self.manifest);manifest['files'][1]['path']='texture.png'
        with patch.dict('sys.modules',{'bpy':bpy}),patch('orchestrator.blender_assets_worker.self_contained'):
            records=pack_images(self.root,manifest)
        self.assertEqual(records['Fixture']['sha256'],file_hash(texture_path));self.assertTrue(image.has_data)
    def test_library_loader_preserves_selected_names_when_blender_mutates_target_list(self):
        from orchestrator.blender_assets_worker import load_meshes
        names=['Library Mesh'];target=SimpleNamespace(objects=[])
        class Load:
            def __enter__(self):return SimpleNamespace(objects=list(names)),target
            def __exit__(self,*args):target.objects[:]=[SimpleNamespace(name=n,type='MESH') for n in target.objects]
        bpy=SimpleNamespace(data=SimpleNamespace(libraries=SimpleNamespace(load=lambda *a,**k:Load())))
        with patch.dict('sys.modules',{'bpy':bpy}):objects=load_meshes('selected.blend',names)
        self.assertEqual(names,['Library Mesh']);self.assertEqual(objects[0].name,'Library Mesh')
    def test_append_metadata_can_be_cleared_but_live_library_dependencies_cannot(self):
        from orchestrator.blender_assets_worker import clear_local_library_metadata
        library=SimpleNamespace(name='selected.blend');libraries=[library]
        obj=SimpleNamespace(name='Linked Mesh',library=library)
        bpy=SimpleNamespace(data=SimpleNamespace(libraries=libraries,objects=[obj],bl_rna=SimpleNamespace(properties=[SimpleNamespace(type='COLLECTION',identifier='objects')])))
        with patch.dict('sys.modules',{'bpy':bpy}):
            with self.assertRaisesRegex(ValueError,'linked datablock'):clear_local_library_metadata()
            self.assertEqual(libraries,[library])
            obj.library=None;clear_local_library_metadata();self.assertEqual(libraries,[])
    def test_untracked_geometry_node_dependencies_are_rejected(self):
        from orchestrator.blender_assets_worker import pack_images
        bpy=SimpleNamespace(data=SimpleNamespace(node_groups=[SimpleNamespace(bl_idname='GeometryNodeTree')]))
        with patch.dict('sys.modules',{'bpy':bpy}):
            with self.assertRaisesRegex(ValueError,'Geometry Nodes'):pack_images(self.root,self.manifest)
    def test_runtime_drift_stops_before_host(self):
        frozen,control=self.frozen();frozen['runtime_sources']['blender_assets_worker.py']='changed'
        with patch('orchestrator.blender_assets.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'implementation changed'):execute(frozen,control)
            run.assert_not_called()

if __name__=='__main__':unittest.main()
