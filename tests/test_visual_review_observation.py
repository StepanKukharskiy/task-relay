"""Exact render lineage and received model pixels, using tiny saved fixtures."""
import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
import struct
import zlib
import io
from pathlib import Path
from types import SimpleNamespace

from orchestrator import job_owner,visual_files
from orchestrator.workers import atomic
from tests.test_browser_screenshots import png


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.raw=png();self.digest=hashlib.sha256(self.raw).hexdigest()
        body=b'fixture\x00second page';kind=b'tEXt'
        self.second=self.raw[:-12]+struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)+self.raw[-12:]

    def test_declared_draft_preview_is_version_bound_and_cannot_read_other_files(self):
        files=SimpleNamespace(inputs={},outputs={'draft.png'},written={'draft.png':len(self.raw)},read_bytes=lambda path:self.raw)
        value=visual_files.read(files,dict(path='draft.png',members=[]))
        self.assertEqual(value['images'][0]['sha256'],self.digest)
        files.read_bytes=lambda path:self.second
        changed=visual_files.read(files,dict(path='draft.png',members=[]))
        self.assertNotEqual(changed['images'][0]['sha256'],self.digest)
        with self.assertRaisesRegex(ValueError,'assigned input or saved declared draft'):
            visual_files.read(files,dict(path='unrelated.png',members=[]))
        self.assertEqual(visual_files.confirmed_pixels(self.root),set())

    def request(self,provider='gemini',received=True,pixels=None):
        encoded=base64.b64encode(self.raw if pixels is None else pixels).decode()
        if provider=='gemini':payload={'contents':[{'role':'user','parts':[{'inlineData':{'mimeType':'image/png','data':encoded}}]}]}
        elif provider=='openai':payload={'input':[{'role':'user','content':[{'type':'input_image','image_url':'data:image/png;base64,'+encoded}]}]}
        else:payload={'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+encoded}}]}]}
        atomic(self.root/'api-01.request.json',dict(provider=provider,payload=payload))
        if received:atomic(self.root/'api-01.response.json',{'fixture':'confirmed response'})

    def test_only_actual_received_image_parts_establish_observation(self):
        self.request(received=False)
        atomic(self.root/'tool-01-01.json',dict(name='image_view',arguments={'path':'render.zip'},result={'images':[{'sha256':self.digest}]}))
        self.assertEqual(visual_files.confirmed_pixels(self.root),set())
        for provider in ('gemini','openai','openrouter','groq','deepseek'):
            with self.subTest(provider=provider):
                self.request(provider);self.assertEqual(visual_files.confirmed_pixels(self.root),{self.digest})
        record=json.loads((self.root/'api-01.request.json').read_text())
        record['payload']={'messages':[{'role':'user','content':json.dumps(record['payload'])}]}
        atomic(self.root/'api-01.request.json',record)
        self.assertEqual(visual_files.confirmed_pixels(self.root),set())

    def large_image(self,kind='PNG',size=(2899,3624)):
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',size,'#407050').save(out,format=kind)
        return out.getvalue()

    def test_large_source_preview_preserves_original_identity_and_render_review(self):
        raw=self.large_image();source=hashlib.sha256(raw).hexdigest()
        values=list(self.lineage());archive=self.root/'render.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('slides/1.png',raw)
        original=archive.read_bytes();digest=hashlib.sha256(original).hexdigest()
        artifact=values[0].artifact('render');artifact['sha256']=digest;values[2]['inputs'][0]['sha256']=digest
        files=SimpleNamespace(inputs={'render.zip':dict(sha256=digest)},outputs=set(),written={},read_bytes=lambda _:original)
        result=visual_files.read(files,dict(path='render.zip',members=['slides/1.png']))
        detail=result['images'][0];pixels=result['_pixels'][0]
        self.assertEqual(detail['source_sha256'],source)
        self.assertEqual(detail['source_dimensions'],[2899,3624])
        self.assertEqual(detail['transformation'],'bounded-inspection-preview-v1')
        self.assertEqual(max(detail['width'],detail['height']),2048)
        self.assertAlmostEqual(detail['width']/detail['height'],2899/3624,places=3)
        self.assertEqual(archive.read_bytes(),original)
        self.assertNotEqual(detail['sha256'],source)
        self.request(received=False,pixels=pixels)
        atomic(self.root/'tool-01-00.json',dict(name='image_view',result={'images':[detail]}))
        self.assertFalse(job_owner.inspected_render(*values))
        self.request(pixels=pixels)
        self.assertTrue(job_owner.inspected_render(*values))
        # Unrelated pixels cannot satisfy the exact source's preview requirement.
        self.request(pixels=self.raw)
        self.assertFalse(job_owner.inspected_render(*values))

    def test_large_jpeg_and_direct_png_use_same_preview_as_zip(self):
        for kind,name in [('PNG','photo.png'),('JPEG','photo.jpg')]:
            with self.subTest(kind=kind):
                raw=self.large_image(kind);digest=hashlib.sha256(raw).hexdigest()
                files=SimpleNamespace(inputs={name:dict(sha256=digest)},outputs=set(),written={},read_bytes=lambda _:raw)
                direct=visual_files.read(files,dict(path=name,members=[]))
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w') as z:z.writestr(name,raw)
                bundle=stream.getvalue();files.inputs={'photos.zip':dict(sha256=hashlib.sha256(bundle).hexdigest())};files.read_bytes=lambda _:bundle
                zipped=visual_files.read(files,dict(path='photos.zip',members=[name]))
                self.assertEqual(direct['_pixels'],zipped['_pixels'])
                self.assertEqual(direct['images'][0]['source_sha256'],digest)

    def test_resized_source_selection_requires_confirmed_preview_not_just_receipt(self):
        from contextlib import contextmanager
        from orchestrator.visual_selection import verify_observations
        raw=self.large_image();digest=hashlib.sha256(raw).hexdigest()
        files=SimpleNamespace(inputs={'photo.png':dict(sha256=digest)},outputs=set(),written={},read_bytes=lambda _:raw)
        result=visual_files.read(files,dict(path='photo.png',members=[]))
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE production_attempts (id TEXT, session TEXT)')
        db.execute('INSERT INTO production_attempts VALUES (?,?)',('a',json.dumps({'control':str(self.root)})))
        @contextmanager
        def connection(**kwargs):yield db
        store=SimpleNamespace(attempt='a',connection=connection)
        document=dict(parameters={'selection_policy':'visual'},items=[dict(options=[dict(selection=dict(photo_sha256=digest,reference_sha256=digest))])])
        atomic(self.root/'tool-01-00.json',dict(name='image_view',result={'images':result['images']}))
        self.request(received=False,pixels=result['_pixels'][0])
        with self.assertRaisesRegex(ValueError,'not confirmed'):verify_observations(store,document)
        self.request(pixels=result['_pixels'][0]);verify_observations(store,document)
        document['items'][0]['options'][0]['selection']['photo_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'not confirmed'):verify_observations(store,document)

    def test_converted_preview_fits_single_allowance_and_batch_keeps_same_limit(self):
        from PIL import Image
        import random
        from orchestrator.image_representation import inspection_preview
        out=io.BytesIO();Image.frombytes('RGB',(2000,2000),random.Random(7).randbytes(12_000_000)).save(out,format='JPEG')
        raw=out.getvalue();data,detail=inspection_preview(raw,'noise.jpg')
        self.assertLessEqual(len(data),10_000_000)
        self.assertEqual(detail['transformation'],'bounded-inspection-preview-v1')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('a.jpg',raw);z.writestr('b.jpg',raw)
        bundle=stream.getvalue();files=SimpleNamespace(inputs={'photos.zip':dict(sha256=hashlib.sha256(bundle).hexdigest())},outputs=set(),written={},read_bytes=lambda _:bundle)
        with self.assertRaisesRegex(ValueError,'preview pack'):
            visual_files.read(files,dict(path='photos.zip',members=['a.jpg','b.jpg']))

    def test_preview_does_not_bypass_source_corruption_size_or_static_limits(self):
        from PIL import Image
        from orchestrator.image_representation import inspection_preview
        corrupt=bytearray(self.large_image());corrupt[-5]^=1
        with self.assertRaises((ValueError,SyntaxError,OSError)):inspection_preview(bytes(corrupt),'photo.png')
        with self.assertRaisesRegex(ValueError,'oversized'):
            inspection_preview(self.large_image(size=(5000,4001)),'photo.png')
        with self.assertRaisesRegex(ValueError,'oversized'):
            inspection_preview(self.large_image('JPEG',size=(4001,4000)),'photo.jpg')
        with self.assertRaisesRegex(ValueError,'allowance'):
            inspection_preview(b'x'*10_000_001,'photo.png')
        out=io.BytesIO();first=Image.new('RGB',(4097,1),'red');second=Image.new('RGB',(4097,1),'blue')
        first.save(out,format='PNG',save_all=True,append_images=[second],duration=1)
        with self.assertRaisesRegex(ValueError,'static'):
            inspection_preview(out.getvalue(),'photo.png')

    def lineage(self,source='candidate',extra_page=False):
        archive=self.root/'render.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('slides/1.png',self.raw)
            if extra_page:z.writestr('slides/2.png',self.second)
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        artifact=dict(id='render',run='job',task='renderer',attempt='render-attempt',path='render.zip',sha256=digest,blob=str(archive))
        candidate=dict(id='candidate',attempt='candidate-attempt',sha256='candidate-hash')
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;self.addCleanup(db.close)
        db.execute('CREATE TABLE production_attempts (id TEXT, frozen TEXT)')
        db.execute('INSERT INTO production_attempts VALUES (?,?)',('render-attempt',json.dumps({'inputs':[{'artifact':source,'sha256':'candidate-hash'}]})))
        task=dict(status='completed',latest='render-attempt')
        rt=SimpleNamespace(db=db,artifact=lambda _:artifact,task=lambda *_:task,spec=lambda _:dict(execution={'capability':'pptx.render'},outputs=[dict(path='render.zip',media_type='application/zip')]))
        attempt=dict(run='job',session=json.dumps({'control':str(self.root)}))
        frozen=dict(inputs=[dict(artifact='render',path='render.zip',sha256=digest,visual_reference=True)])
        return rt,attempt,frozen,candidate

    def test_exact_candidate_and_all_pages_must_reach_reviewer(self):
        values=self.lineage();self.assertFalse(job_owner.inspected_render(*values))
        self.request();self.assertTrue(job_owner.inspected_render(*values))
        self.assertFalse(job_owner.inspected_render(*self.lineage(source='different-version')))
        values=self.lineage(extra_page=True);self.assertFalse(job_owner.inspected_render(*values))
        # The second page must be in a confirmed request, not just a tool receipt.
        (self.root/'api-01.request.json').rename(self.root/'api-02.request.json')
        (self.root/'api-01.response.json').rename(self.root/'api-02.response.json')
        self.request(pixels=self.second)
        self.assertTrue(job_owner.inspected_render(*values))

    def test_pdf_sibling_of_exact_render_and_changed_render_bytes(self):
        values=list(self.lineage());self.request()
        values[-1]=dict(id='preview-pdf',attempt='render-attempt',sha256='pdf-hash')
        self.assertTrue(job_owner.inspected_render(*values))
        (self.root/'render.zip').write_bytes(b'changed after review')
        with self.assertRaisesRegex(ValueError,'evidence changed'):job_owner.inspected_render(*values)
