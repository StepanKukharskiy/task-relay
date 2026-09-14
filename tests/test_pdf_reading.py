import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
from task_relay import file_tools, capabilities


def pdf(texts, encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
                DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(('BT /F1 12 Tf 10 100 Td (' + text + ') Tj ET').encode())
            page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('test-password')
    out = io.BytesIO(); writer.write(out); return out.getvalue()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root/'brief.pdf'
        self.path.write_bytes(pdf(['First page requirements', 'Second page deadline']))

    def tearDown(self):
        self.temp.cleanup()

    def read(self, **args):
        return file_tools.execute(self.root, 'pdf_read', json.dumps(dict(
            {'path':'brief.pdf','page':1,'offset':0,'limit':24000,'sha256':''}, **args)))

    def test_reads_real_pdf_with_page_citations_and_exact_version(self):
        result = self.read()
        self.assertTrue(result['ok'],result)
        self.assertEqual([r['page'] for r in result['pages']], [1,2])
        self.assertIn('requirements',result['pages'][0]['text'])
        self.assertIn('deadline',result['pages'][1]['text'])
        self.assertEqual(result['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertIsNone(result['next_page'])

    def test_character_continuation_loses_no_text_and_rejects_changed_version(self):
        full = ''.join(r['text'] for r in self.read()['pages'])
        result = self.read(limit=7); parts=[]
        digest = result['sha256']
        while True:
            parts.extend(r['text'] for r in result['pages'])
            if result['next_page'] is None:break
            result = self.read(page=result['next_page'],offset=result['next_offset'],limit=7,sha256=digest)
            self.assertTrue(result['ok'],result)
        self.assertEqual(''.join(parts),full)
        self.path.write_bytes(pdf(['Replacement source']))
        changed = self.read(sha256=digest)
        self.assertFalse(changed['ok']);self.assertIn('changed',changed['error'])
        self.assertNotIn('Replacement',json.dumps(changed))

    def test_page_batch_and_empty_pages_are_explicit(self):
        self.path.write_bytes(pdf(['']*9))
        first = self.read();self.assertEqual(len(first['pages']),8)
        self.assertEqual(first['next_page'],9)
        self.assertTrue(all(r['no_extractable_text'] for r in first['pages']))
        self.assertIn('OCR',first['limitations'])
        last=self.read(page=9,sha256=first['sha256']);self.assertIsNone(last['next_page'])

    def test_encrypted_malformed_and_out_of_range_documents(self):
        self.assertFalse(self.read(page=3)['ok'])
        self.path.write_bytes(pdf(['Private'],encrypted=True))
        result=self.read();self.assertFalse(result['ok']);self.assertIn('Encrypted',result['error'])
        self.path.write_bytes(b'%PDF-1.7\nbroken')
        result=self.read();self.assertFalse(result['ok']);self.assertIn('failed',result['error'])

    def test_scope_and_file_limit_apply_before_parser_launch(self):
        (self.root/'link.pdf').symlink_to(self.path)
        with patch('task_relay.file_tools.subprocess.run') as run:
            for path in ('../brief.pdf','link.pdf'):
                self.assertFalse(self.read(path=path)['ok'])
            with self.path.open('wb') as stream:stream.truncate(20_000_001)
            self.assertFalse(self.read()['ok'])
            run.assert_not_called()

    def test_timeout_is_reported_without_retry(self):
        with patch('task_relay.file_tools.subprocess.run',side_effect=subprocess.TimeoutExpired('reader',15)) as run:
            result=self.read()
        self.assertFalse(result['ok']);self.assertIn('15 seconds',result['error'])
        self.assertEqual(run.call_count,1)

    def test_missing_packaged_reader_returns_actionable_tool_error(self):
        import builtins
        original = builtins.__import__
        def missing(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 1 and 'pdf_reader' in fromlist:
                raise ImportError('missing module in /private/runtime')
            return original(name, globals, locals, fromlist, level)
        with patch('builtins.__import__', side_effect=missing), \
                patch('task_relay.file_tools.subprocess.run') as run:
            result = self.read()
        self.assertFalse(result['ok'])
        self.assertIn('missing its PDF reader', result['error'])
        self.assertIn('restart Relay', result['error'])
        self.assertNotIn('/private/runtime', str(result))
        run.assert_not_called()

    def test_shared_orchestrator_route_reads_pdf_under_known_root(self):
        call={'name':'pdf_read','arguments':json.dumps({'project':str(self.root),'path':'brief.pdf',
            'page':1,'offset':0,'limit':24000,'sha256':''})}
        result=capabilities.read([str(self.root)],call)
        self.assertTrue(result['ok'],result)
        self.assertIn('deadline',result['pages'][1]['text'])
        self.assertFalse(capabilities.read([],call)['ok'])

    def test_conversation_pdf_read_is_journaled_before_answer(self):
        from task_relay import orchestrator_files
        args={'project':str(self.root),'path':'brief.pdf','page':1,'offset':0,'limit':24000,'sha256':''}
        responses=iter([
            {'candidates':[{'content':{'role':'model','parts':[{'functionCall':{'name':'pdf_read','args':args}}]},'finishReason':'STOP'}]},
            {'candidates':[{'content':{'role':'model','parts':[{'text':json.dumps({'answer':'Deadline: brief.pdf, page 2.','action':None})}]},'finishReason':'STOP'}]}])
        requests=[]
        class Client:
            def request(inner, endpoint, request):
                requests.append(json.loads(json.dumps(request)));return next(responses)
        receipt=self.root/'reads.json'
        request={'contents':[],'generationConfig':{},'systemInstruction':{'parts':[{'text':'Return JSON'}]}}
        raw=orchestrator_files.run('gemini',Client(),'test',request,[str(self.root)],receipt)
        self.assertIsNone(json.loads(raw)['action'])
        self.assertIn('Second page deadline',json.dumps(requests[-1]))
        saved=json.loads(receipt.read_text())[0]['reads'][0]['result']
        self.assertEqual(saved['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(saved['pages'][1]['page'],2)


if __name__ == '__main__':unittest.main()
