"""Publication failures: hidden metadata, unsafe staged bytes and omitted files."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from scripts import check_publication as check


class Tests(unittest.TestCase):
    def test_personal_paths_and_credential_signatures_are_rejected_without_echo(self):
        home=b'/'+b'Users/'+b'private-account/project'
        secret=b'AIza'+b'x'*35
        findings=check.scan('example.py',b'# '+home+b'\n# '+secret)
        kinds={f['kind'] for f in findings}
        self.assertIn('personal-home-path',kinds);self.assertIn('google-api-key',kinds)
        report=json.dumps(findings).encode()
        self.assertNotIn(home,report);self.assertNotIn(secret,report)

    def test_compressed_image_metadata_cannot_hide_a_credential(self):
        secret=b'ghp_'+b'x'*36
        body=b'Comment\0\0'+zlib.compress(secret)
        chunk=struct.pack('>I',len(body))+b'zTXt'+body+b'\0'*4
        findings=check.scan('asset.png',b'\x89PNG\r\n\x1a\n'+chunk)
        self.assertTrue(any(f['kind']=='github-token' for f in findings))
        self.assertNotIn(secret,json.dumps(findings).encode())

    def test_staged_secret_is_detected_even_when_working_file_is_clean(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'example.py'
            subprocess.run(['git','init','-q',str(root)],check=True)
            p.write_bytes(b'# '+b'sk-'+b'x'*40+b'\n')
            subprocess.run(['git','-C',str(root),'add','example.py'],check=True)
            p.write_text('# clean working source\n')
            expected={'files':[{'path':'example.py','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}]}
            with patch.object(check,'ROOT',root),patch.object(check,'inventory',return_value=expected),patch('sys.argv',['check','--staged']),contextlib.redirect_stdout(io.StringIO()) as output:
                result=check.main()
            self.assertEqual(result,1)
            kinds={f['kind'] for f in json.loads(output.getvalue())['findings']}
            self.assertIn('provider-key',kinds);self.assertIn('reviewed-source-byte-mismatch',kinds)

    def test_added_personal_report_outside_inventory_blocks_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'personal-notes.md').write_text('Development notebook\n')
            subprocess.run(['git','-C',str(root),'add','personal-notes.md'],check=True)
            with patch.object(check,'ROOT',root),patch.object(check,'inventory',return_value={'files':[]}),patch('sys.argv',['check','--staged']),contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(check.main(),1)
            self.assertIn('outside-public-inventory',{f['kind'] for f in json.loads(output.getvalue())['findings']})
