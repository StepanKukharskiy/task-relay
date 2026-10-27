"""Formatting-sensitive source identity, with no image bytes or network."""
import hashlib,json,unittest,zipfile,io
from orchestrator.browser_images import fetch_bundle,SCHEMA

class Tests(unittest.TestCase):
    def value(self):
        return {'schema':SCHEMA,'job':'fixture','subjects':[{'id':'missing','label':'Missing','query':'Fixture'}],'candidates':[]}
    def test_exact_original_bytes_and_canonical_hash_are_distinct_and_explicit(self):
        value=self.value();text=json.dumps(value,indent=4)+'\n'
        raw,manifest=fetch_bundle(value,source_text=text)
        self.assertEqual(manifest['source_manifest_sha256'],hashlib.sha256(text.encode()).hexdigest())
        self.assertNotEqual(manifest['source_manifest_sha256'],manifest['source_manifest_canonical_sha256'])
        self.assertEqual(manifest['source_manifest_hash_basis'],'exact-input-utf8-bytes')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertEqual(json.loads(z.read('manifest.json')),manifest)
    def test_changed_input_text_is_rejected_before_fetch(self):
        value=self.value();other={**value,'job':'other'};calls=[]
        with self.assertRaisesRegex(ValueError,'differs'):
            fetch_bundle(value,source_text=json.dumps(other),fetch=lambda *args:calls.append(args))
        self.assertEqual(calls,[])
    def test_legacy_value_only_call_labels_its_canonical_basis(self):
        value=self.value();_,manifest=fetch_bundle(value)
        self.assertEqual(manifest['source_manifest_sha256'],hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest())
        self.assertEqual(manifest['source_manifest_hash_basis'],'json.dumps(parsed-input,sort_keys=True)-utf8')
