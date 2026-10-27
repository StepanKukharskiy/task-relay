import hashlib,io,json,time,unittest,zipfile
from unittest.mock import patch
from PIL import Image
from orchestrator import browser_images,image_sources

def photo(animated=False):
 im=Image.new('RGBA',(140,120),(210,140,30,255));im.paste((20,40,150,100),(20,20,90,90));b=io.BytesIO()
 if animated:im.save(b,format='WEBP',save_all=True,append_images=[Image.new('RGBA',im.size,(50,200,30,255))],duration=100,loop=0,lossless=True)
 else:im.save(b,format='WEBP',lossless=True)
 return b.getvalue()

def manifest():
 return {'schema':browser_images.SCHEMA,'job':'test','subjects':[{'id':'chair-a','label':'Documented upholstered chair','query':'Upholstered chair'}],'candidates':[{'subject':'chair-a','title':'Documented upholstered chair','source_url':'https://example.com/chair','observed_url':'https://example.com/chair','download_url':'https://example.com/chair.webp','observation':'obs1','action_id':'call1'}]}

def rewrite(raw,change):
 with zipfile.ZipFile(io.BytesIO(raw)) as z:files={n:z.read(n) for n in z.namelist()}
 m=json.loads(files['manifest.json']);change(files,m);files['manifest.json']=json.dumps(m).encode();b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  for n,data in files.items():z.writestr(n,data)
 return b.getvalue()

class WebPPhotoConversion(unittest.TestCase):
 def bundle(self,raw=None):
  original=raw or photo();return browser_images.fetch_bundle(manifest(),fetch=lambda *args:(original,'image/webp','https://example.com/chair.webp'))
 def test_static_webp_preserves_source_bytes_and_pixels(self):
  original=photo();raw,m=self.bundle(original);images,credits,_=image_sources.unpack(raw);s=m['subjects'][0];self.assertEqual(s['media_type'],'image/png');self.assertEqual(s['source_original']['sha256'],hashlib.sha256(original).hexdigest())
  with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertEqual(z.read(s['source_original']['path']),original)
  with Image.open(io.BytesIO(original)) as before,Image.open(io.BytesIO(images[s['path']])) as after:self.assertEqual(before.convert('RGBA').tobytes(),after.convert('RGBA').tobytes())
 def test_oversized_conversion_gets_bounded_preview_with_verified_original(self):
  import random
  rng=random.Random(42);im=Image.frombytes('RGB',(180,180),rng.randbytes(180*180*3));b=io.BytesIO();im.save(b,format='WEBP',quality=20);original=b.getvalue()
  self.assertLess(len(original),40000)
  with patch.object(image_sources,'MAX_IMAGE_BYTES',40000):
   raw,m=self.bundle(original);self.assertEqual(m['coverage']['found'],1);s=m['subjects'][0]
   self.assertEqual(s['source_original']['transformation'],'bounded-preview-v1-webp-to-png')
   images,_,_=image_sources.unpack(raw);self.assertLessEqual(len(images[s['path']]),40000)
   with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertEqual(z.read(s['source_original']['path']),original)
   with Image.open(io.BytesIO(images[s['path']])) as preview:self.assertLess(preview.width,180)
   def change(files,m):
    s=m['subjects'][0]
    with Image.open(io.BytesIO(files[s['path']])) as picture:
     picture=picture.convert('RGB');picture.putpixel((0,0),(0,0,0));out=io.BytesIO();picture.save(out,format='PNG')
    files[s['path']]=out.getvalue();s['sha256']=hashlib.sha256(out.getvalue()).hexdigest();s['bytes']=len(out.getvalue())
   with self.assertRaisesRegex(ValueError,'pixels differ'):image_sources.unpack(rewrite(raw,change))
 def test_static_avif_uses_same_verified_representation_contract(self):
  import random
  rng=random.Random(43);im=Image.frombytes('RGB',(180,180),rng.randbytes(180*180*3));b=io.BytesIO();im.save(b,format='AVIF',quality=20);original=b.getvalue()
  with patch.object(image_sources,'MAX_IMAGE_BYTES',40000):
   raw,m=browser_images.fetch_bundle(manifest(),fetch=lambda *args:(original,'image/avif','https://example.com/chair.avif'))
   self.assertEqual(m['coverage']['found'],1);s=m['subjects'][0];self.assertEqual(s['source_original']['transformation'],'bounded-preview-v1-avif-to-png')
   image_sources.unpack(raw)
   with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertEqual(z.read(s['source_original']['path']),original)
 def test_original_tamper_is_rejected(self):
  raw,_=self.bundle();bad=rewrite(raw,lambda files,m:files.__setitem__('originals/chair-a.webp',b'changed'))
  with self.assertRaisesRegex(ValueError,'Source-original hash'):image_sources.unpack(bad)
 def test_rehashed_changed_pixels_do_not_pass(self):
  raw,_=self.bundle()
  def change(files,m):
   b=io.BytesIO();Image.new('RGBA',(140,120),(1,2,3,255)).save(b,format='PNG');s=m['subjects'][0];files[s['path']]=b.getvalue();s['sha256']=hashlib.sha256(b.getvalue()).hexdigest()
  with self.assertRaisesRegex(ValueError,'pixels differ'):image_sources.unpack(rewrite(raw,change))
 def test_animated_webp_remains_explicit_gap(self):
  raw,m=self.bundle(photo(True));self.assertEqual(m['coverage']['found'],0);self.assertIn('Animated WebP',m['subjects'][0]['reason']);self.assertNotIn('source_original',m['subjects'][0])
 def test_undeclared_original_is_rejected(self):
  raw,_=self.bundle();bad=rewrite(raw,lambda files,m:files.__setitem__('originals/extra.webp',photo()))
  with self.assertRaisesRegex(ValueError,'Undeclared'):image_sources.unpack(bad)
 def test_transport_webp_allowance_is_explicit(self):
  class Response:
   status=200
   def __init__(self):self.raw=photo()
   def getheader(self,key,default=None):return {'Content-Type':'image/webp','Content-Length':str(len(self.raw))}.get(key,default)
   def read1(self,n):data=self.raw[:n];self.raw=self.raw[n:];return data
  class Connection:
   sock=None
   def __init__(self,*args):self.response=Response()
   def request(self,*args,**kwargs):pass
   def getresponse(self):return self.response
   def close(self):pass
  with patch('task_relay.orchestrator_web.public_addresses',return_value=['93.184.216.34']),patch('task_relay.orchestrator_web.PublicHTTPS',Connection):
   with self.assertRaisesRegex(ValueError,'unsupported content'):image_sources.download('https://example.com/chair.webp',3000000,time.monotonic()+20,allowed_hosts={'example.com'})
   raw,mime,url=image_sources.download('https://example.com/chair.webp',3000000,time.monotonic()+20,allowed_hosts={'example.com'},media_types=('image/webp',));self.assertEqual(mime,'image/webp');self.assertTrue(raw)

if __name__=='__main__':unittest.main()
