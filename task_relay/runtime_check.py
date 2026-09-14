"""Offline packaged-runtime check using the shipped interpreter and file tools."""
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile


PROBE = r'''
import importlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from task_relay.releases import VERSION
from task_relay import file_tools, pdf_reader
for name in ('pypdf', 'PIL', 'playwright.sync_api', 'pptx'):
    importlib.import_module(name)
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
writer = PdfWriter()
page = writer.add_blank_page(width=300, height=300)
font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
    NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
    DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
stream = DecodedStreamObject()
stream.set_data(b'BT /F1 12 Tf 10 100 Td (Packaged PDF reader verified) Tj ET')
page[NameObject('/Contents')] = writer._add_object(stream)
root = Path(sys.argv[2]).resolve()
with (root / 'fixture.pdf').open('wb') as f: writer.write(f)
result = file_tools.execute(root, 'pdf_read', json.dumps({
    'path': 'fixture.pdf', 'page': 1, 'offset': 0, 'limit': 1000, 'sha256': ''}))
if not result.get('ok') or 'Packaged PDF reader verified' not in result['pages'][0]['text']:
    raise RuntimeError('Bundled PDF read failed: ' + json.dumps(result))
print(json.dumps({'version': VERSION, 'pdf_read': True, 'dependency_imports': True}))
'''


def check_packaged(app):
    app = Path(app).resolve()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    runtime = app / 'Contents/Resources/resources/runtime'
    with tempfile.TemporaryDirectory(prefix='relay-runtime-check-') as directory:
        # No inherited data bindings or user Python packages. -B also applies to
        # the PDF child through PYTHONDONTWRITEBYTECODE so signatures stay intact.
        env = {'PATH': '/usr/bin:/bin', 'HOME': directory, 'TMPDIR': directory,
               'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([str(runtime / 'python/bin/python3'), '-I', '-B', '-c', PROBE,
                                 str(runtime / 'app'), directory], env=env,
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise ValueError('Packaged runtime check failed; do not install or publish this app.\n'
                             + result.stderr[-3000:])
        value = json.loads(result.stdout)
        if value.get('version') != info['CFBundleShortVersionString']:
            raise ValueError('Packaged Python and app versions differ.')
        return value
