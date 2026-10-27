import base64
import hashlib
import io
import json
import random
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tests import test_desktop_workspace as fixture
from task_relay import desktop_workspace as workspace, production_control as pc


class HtmlPreviewTests(unittest.TestCase):
    def setUp(self):
        fixture.WorkspaceTests.setUp(self)

    def save(self, content, name='gallery.html'):
        blob=pc.root(self.state)/'artifacts'/'html-preview'
        blob.parent.mkdir(parents=True,exist_ok=True);blob.write_bytes(content)
        sha=hashlib.sha256(content).hexdigest()
        with self.state.db:
            self.state.db.execute('INSERT OR REPLACE INTO production_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
                ('html','demo','produce',None,name,str(blob),sha,len(content),'Gallery',str(blob)))
        return blob,sha

    def test_gallery_preview_is_exact_bounded_and_read_only(self):
        image=Image.frombytes('RGB',(900,900),random.Random(7).randbytes(900*900*3))
        buf=io.BytesIO();image.save(buf,format='PNG')
        data=base64.b64encode(buf.getvalue()).decode()
        content=('<html><style>.grid{display:grid}</style><main><h1>Volvo</h1><img alt="740" src="data:image/png;base64,'+data+'"><p>Buying details unknown</p></main></html>').encode()
        blob,sha=self.save(content);before=list(self.state.db.iterdump())
        with patch('task_relay.workflow_files.sync',side_effect=AssertionError('No publication')):
            value=workspace.artifact_preview('html',sha,self.paths)
        self.assertEqual(value['sha256'],sha);self.assertEqual(value['media_type'],'text/html')
        self.assertIn('Volvo',value['html']);self.assertIn('Buying details unknown',value['html'])
        self.assertIn('data:image/jpeg;base64,',value['html']);self.assertLess(len(json.dumps(value).encode()),1000000)
        self.assertEqual(blob.read_bytes(),content);self.assertEqual(list(self.state.db.iterdump()),before)
        with self.assertRaisesRegex(workspace.DesktopPlanError,'unavailable'):workspace.artifact_preview('html','0'*64,self.paths)
        blob.write_bytes(content+b'!')
        with self.assertRaisesRegex(workspace.DesktopPlanError,'changed'):workspace.artifact_preview('html',sha,self.paths)

    def test_html_is_inert_and_does_not_fetch_external_resources(self):
        _,sha=self.save(b'''<meta http-equiv="refresh" content="0;url=https://evil.test"><base href="file:///">
        <script>window.__TAURI__.invoke('bad')</script><iframe src="https://evil.test"></iframe>
        <svg onload="bad()"><script>bad()</script></svg><link rel="stylesheet" href="https://evil.test">
        <style>body{background:url(https://evil.test)}</style><p style="color:red" onclick="bad()">Saved text</p><a href="https://source.test">Source page</a>
        <img src="https://evil.test/pixel"><img src="file:///private/key"><img src="data:image/svg+xml;base64,AAAA">''')
        value=workspace.artifact_preview('html',sha,self.paths);html=value['html']
        for absent in ('<script','<iframe','<svg','<link','<base','onclick','http-equiv="refresh"','src="https:','src="file:','href=','__TAURI__'):
            self.assertNotIn(absent,html)
        self.assertIn('Content-Security-Policy',html);self.assertIn('default-src',html)
        self.assertIn('Saved text',html);self.assertIn('https://source.test',html)
        self.assertNotIn('color:red',html);self.assertNotIn('evil.test',html)
        from task_relay.html_preview import STYLE, STYLE_HASH
        self.assertEqual(html.count('<style>'),1);self.assertIn('<style>'+STYLE+'</style>',html)
        app_html=(Path(__file__).parents[1]/'task_relay/assets/companion.html').read_text()
        self.assertIn("style-src 'self' 'sha256-"+STYLE_HASH+"'",app_html)
        self.assertNotIn("'unsafe-inline'",app_html)

    def test_oversized_text_and_invalid_encoding_fail_without_truncating(self):
        for content in (b'<p>'+b'x'*200001+b'</p>', b'\xff'):
            _,sha=self.save(content)
            with self.assertRaisesRegex(workspace.DesktopPlanError,'Cannot preview'):workspace.artifact_preview('html',sha,self.paths)

    def test_markdown_preview_preserves_exact_text_and_is_bounded(self):
        raw=('# Saved report\n\n**Bold**\n\n| A | B |\n|---|---|\n| 1 | 2 |\n'+('text '*9000)).encode()
        blob,sha=self.save(raw,'report.md');before=list(self.state.db.iterdump())
        value=workspace.artifact_preview('html',sha,self.paths)
        self.assertEqual(value['media_type'],'text/markdown');self.assertEqual(value['text'],raw.decode()[:40000]);self.assertTrue(value['truncated'])
        self.assertEqual(blob.read_bytes(),raw);self.assertEqual(list(self.state.db.iterdump()),before)
        with self.assertRaisesRegex(workspace.DesktopPlanError,'unavailable'):workspace.artifact_preview('html','bad',self.paths)
        _,sha=self.save(b'\xff','bad.md')
        with self.assertRaisesRegex(workspace.DesktopPlanError,'UTF-8'):workspace.artifact_preview('html',sha,self.paths)

    def test_pdf_preview_real_pages_without_execution_or_file_mutation(self):
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=400,height=200);writer.add_blank_page(width=200,height=400)
        out=io.BytesIO();writer.write(out);raw=out.getvalue();blob,sha=self.save(raw,'report.pdf')
        before=list(self.state.db.iterdump())
        for page in (1,2):
            value=workspace.artifact_preview('html',sha,self.paths,page=page)
            self.assertEqual((value['page'],value['pages']),(page,2));self.assertEqual(value['media_type'],'application/pdf')
            image=Image.open(io.BytesIO(base64.b64decode(value['data_url'].split(',')[1])))
            self.assertLessEqual(max(image.size),1280)
            self.assertEqual(image.width>image.height,page==1)
        self.assertEqual(blob.read_bytes(),raw);self.assertEqual(list(self.state.db.iterdump()),before)
        for page in (0,3,True,'1'):
            with self.subTest(page=page),self.assertRaises(ValueError):workspace.artifact_preview('html',sha,self.paths,page=page)
