"""Generic crop → browser upload and retained-photo replacement boundaries."""
import copy, hashlib, io, json, sqlite3, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from orchestrator import image_crop, image_sources, execution
from orchestrator.browser_contract import upload_media
from task_relay.general_browser import PlaywrightDriver
from tests.test_image_sources import bundle

class Tests(unittest.TestCase):
    def test_late_upload_redirect_is_followed_once_without_resubmission(self):
        driver=PlaywrightDriver.__new__(PlaywrightDriver);page=object()
        driver.page=lambda tab:page;driver.policy=dict(origins=['https://example.test'])
        driver.redirects={page:'https://example.test/results'};driver.goto=Mock()
        driver.settle_redirect('tab');driver.settle_redirect('tab')
        driver.goto.assert_called_once_with(page,'https://example.test/results')
        driver.redirects[page]='https://outside.test/results'
        with self.assertRaises(ValueError):driver.settle_redirect('tab')
        self.assertEqual(driver.goto.call_count,1)

    def test_crop_preserves_exact_pixels_and_upload_media(self):
        image=Image.new('RGB',(8,6),'red');image.putpixel((3,2),(0,0,255))
        stream=io.BytesIO();image.save(stream,format='PNG');raw=stream.getvalue()
        data,receipt=image_crop.crop(raw,'image/png',[2,1,4,3])
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.size,(4,3));self.assertEqual(result.getpixel((1,1)),(0,0,255,255))
        self.assertEqual(receipt['source_sha256'],hashlib.sha256(raw).hexdigest());self.assertFalse(receipt['acceptance'])
        files=Mock();files.inputs={'crop.png':dict(path='crop.png',media_type='image/png',sha256=hashlib.sha256(data).hexdigest())};files.read_bytes.return_value=data
        driver=PlaywrightDriver.__new__(PlaywrightDriver);driver.navigation_blocks={};driver.redirects={};driver.managed_page=lambda tab:'page'
        element=Mock();element.evaluate.return_value=True
        driver.interact('tab',element,'upload',{'path':'crop.png'},files)
        sent=element.set_input_files.call_args.args[0];self.assertEqual(sent['mimeType'],'image/png');self.assertEqual(sent['buffer'],data)
        files.inputs['crop.png']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'version'):driver.interact('tab',element,'upload',{'path':'crop.png'},files)
        self.assertEqual(element.set_input_files.call_count,1)
        files.inputs['crop.png']['sha256']=hashlib.sha256(data).hexdigest()
        element.evaluate.side_effect=[True,False]
        chooser=Mock();event=Mock();event.value=chooser
        from contextlib import nullcontext
        page=Mock();page.expect_file_chooser.return_value=nullcontext(event);driver.page=lambda tab:page
        driver.interact('tab',element,'upload',{'path':'crop.png'},files)
        self.assertEqual(chooser.set_files.call_args.args[0],sent)

    def test_invalid_crop_and_ungranted_binary_formats_fail(self):
        from tests.test_general_browser import policy
        from orchestrator.browser_contract import validate
        validate(policy(image_sources=[dict(path='sources.json',subjects=[dict(id='basket',label='Basket',query='Basket, 21.5" x 13.5"')])]))
        raw=bundle()[0]
        for region in ([0,0,0,1],[0,0,True,1],[-1,0,1,1]):
            with self.assertRaises(ValueError):image_crop.crop(raw,'image/png',region)
        with self.assertRaises(ValueError):upload_media(dict(path='input.zip',media_type='application/zip'),raw)
        source=io.BytesIO();Image.new('RGB',(4,4),'green').save(source,format='PNG')
        for media,region in [('image/jpeg',[0,0,1,1]),('image/png',[3,3,2,2])]:
            with self.assertRaises(ValueError):image_crop.crop(source.getvalue(),media,region)

    def test_replacements_retain_rejected_pixels_without_using_them(self):
        original,_=bundle();rejected=image_sources.revise_bundle(original,{'oak':'Wrong object'})
        replacement,_=bundle()
        merged,manifest=image_sources.merge_bundles([rejected,replacement])
        images,_,_=image_sources.unpack(merged)
        self.assertEqual(set(images),{'images/oak.jpg'});self.assertEqual(manifest['coverage']['found'],1)
        history=manifest['retained_evidence'][0];self.assertEqual(history['subject'],image_sources.unpack(original)[2]['subjects'][0])
        retained='history/'+hashlib.sha256(rejected).hexdigest()+'/images/oak.jpg'
        with zipfile.ZipFile(io.BytesIO(merged)) as archive,zipfile.ZipFile(io.BytesIO(original)) as before:
            self.assertEqual(archive.read(retained),before.read('images/oak.jpg'))
            damaged=io.BytesIO()
            with zipfile.ZipFile(damaged,'w') as out:
                for n in archive.namelist():out.writestr(n,b'corrupt' if n==retained else archive.read(n))
        with self.assertRaises(ValueError):image_sources.unpack(damaged.getvalue())
        again,_=image_sources.merge_bundles([merged,replacement])
        self.assertEqual(image_sources.unpack(again)[2]['retained_evidence'],manifest['retained_evidence'])

    def test_registered_crop_runs_through_shared_controller(self):
        from orchestrator.runtime import Runtime
        from tests.test_operation_adapters import assignment
        from tests.test_orchestrator import FakeFactory
        from orchestrator.step_runner import execute
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();p=root/'source.png';Image.new('RGB',(8,8),'blue').save(p)
            factory=FakeFactory();rt=Runtime(root/'runtime',factory)
            try:
                aid=rt.register(p,'Exact visual reference')
                t=assignment('images.crop',dict(region=[1,1,4,4]),[dict(artifact=aid,path='source.png',media_type='image/png',purpose='Reference',authority='User reference')])
                t['outputs'][0].update(path='crop.png',media_type='image/png')
                rt.create(dict(id='crop',brief='Crop reference',backend=dict(type='codex-cli',model='fixture',reasoning='low'),tasks=[t]));rt.tick('crop')
                attempt=rt.task('crop','produce')['latest'];frozen=factory.sessions[attempt]['frozen'];control=root/'control';control.mkdir()
                execute(frozen,control)
                self.assertEqual(Image.open(Path(frozen['workspace'])/'crop.png').size,(4,4))
                self.assertFalse(json.loads((control/'operation.json').read_text())['validation']['acceptance'])
            finally:rt.close()
