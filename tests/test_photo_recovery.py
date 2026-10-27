"""Exact source ZIP union fixtures; no network or generated imagery."""
import copy
import hashlib
import io
import json
import unittest
import zipfile
from orchestrator import browser_images, image_sources
from tests.test_image_sources import photo,subject


def bundle(ids,found):
    value=dict(schema=browser_images.SCHEMA,job='original-job',subjects=[subject(i) for i in ids],candidates=[dict(subject=i,download_url='https://images.example/'+i+'.jpg',source_url='https://store.example/'+i,observed_url='https://store.example/'+i,observation='observed-'+i,action_id='action-'+i,title='Observed photo') for i in found])
    return browser_images.fetch_bundle(value,fetch=lambda url,*_: (photo(),'image/jpeg',url))[0]

class Tests(unittest.TestCase):
    def test_merge_retains_download_failure_and_truthful_review_disclosure(self):
        base=image_sources.subject_base_bundle([subject('one'),subject('two')],'a'*64)
        failed=bundle(['two'],[]);buf=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(failed)) as old,zipfile.ZipFile(buf,'w') as new:
            manifest=json.loads(old.read('manifest.json'))
            failure=dict(url='https://images.example/two.jpg',error='Unsupported image content')
            manifest['subjects'][0].update(reason='Unsupported image content',download_failures=[failure])
            new.writestr('manifest.json',json.dumps(manifest))
        failed=buf.getvalue()
        found=bundle(['one'],['one']);originals=[base,found,failed]
        raw,m=image_sources.merge_bundles(originals)
        images,credits,_=image_sources.unpack(raw)
        self.assertEqual(images,image_sources.unpack(found)[0])
        self.assertEqual(credits,image_sources.unpack(found)[1])
        missing=next(s for s in m['subjects'] if s['id']=='two')
        self.assertEqual(missing,manifest['subjects'][0])
        self.assertEqual(m['source_missing_subjects'][-1],dict(bundle_sha256=hashlib.sha256(failed).hexdigest(),subjects=manifest['subjects']))
        self.assertNotIn('contains no photos',m['review'])
        self.assertIn('require independent review',m['review'])
        self.assertEqual(m['coverage'],dict(found=1,missing=1,total=2))
        # A later failure cannot demote a found subject or replace its metadata.
        later=bundle(['one','two'],[])
        merged,m=image_sources.merge_bundles([raw,later])
        self.assertEqual(image_sources.unpack(merged)[1],credits)
        self.assertEqual(m['source_missing_subjects'][0]['subjects'],[missing])

    def test_merge_fills_gap_preserving_exact_photo_and_original_receipts(self):
        base=bundle(['one','two'],['one']);recovered=bundle(['two'],['two'])
        raw,manifest=image_sources.merge_bundles([base,recovered])
        images,credits,checked=image_sources.unpack(raw)
        self.assertTrue(checked['complete'])
        self.assertEqual(images['images/one.jpg'],image_sources.unpack(base)[0]['images/one.jpg'])
        self.assertEqual(credits['images/one.jpg'],image_sources.unpack(base)[1]['images/one.jpg'])
        self.assertEqual(manifest['source_bundle_sha256'],[hashlib.sha256(r).hexdigest() for r in (base,recovered)])
        self.assertEqual(manifest['coverage'],dict(found=2,missing=0,total=2))

    def test_matching_pixels_cannot_replace_original_observation_metadata(self):
        base=bundle(['one','two'],['one']);recovery=bundle(['one','two'],['one','two']);buf=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(recovery)) as old,zipfile.ZipFile(buf,'w') as new:
            manifest=json.loads(old.read('manifest.json'));manifest['subjects'][0]['observation']='later-observation'
            for name in old.namelist():new.writestr(name,json.dumps(manifest) if name=='manifest.json' else old.read(name))
        merged,_=image_sources.merge_bundles([base,buf.getvalue()])
        self.assertEqual(image_sources.unpack(merged)[1]['images/one.jpg']['observation'],'observed-one')

    def test_merge_rejects_subject_expansion_and_found_byte_replacement(self):
        base=bundle(['one','two'],['one'])
        with self.assertRaisesRegex(ValueError,'undeclared'):image_sources.merge_bundles([base,bundle(['three'],['three'])])
        modified=bundle(['one'],['one']);buf=io.BytesIO()
        # Changed source photo with matching internal hash is still not a missing slot.
        from PIL import Image
        pic=io.BytesIO();Image.new('RGB',(200,150),'red').save(pic,format='JPEG');data=pic.getvalue()
        with zipfile.ZipFile(io.BytesIO(modified)) as old,zipfile.ZipFile(buf,'w') as new:
            manifest=json.loads(old.read('manifest.json'));manifest['subjects'][0]['sha256']=hashlib.sha256(data).hexdigest();manifest['subjects'][0]['bytes']=len(data)
            new.writestr('manifest.json',json.dumps(manifest));new.writestr('images/one.jpg',data)
        with self.assertRaisesRegex(ValueError,'already found'):image_sources.merge_bundles([base,buf.getvalue()])
