from email.message import Message
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch,Mock

import orchestrator_web as web
import orchestrator_files as loop
import gemini


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.receipt=Path(self.temp.name)/'turn.json'
        self.session=web.Session(self.receipt,{'api_key':'do-not-save','models':{'text':'test-model'}})

    def tearDown(self):self.temp.cleanup()

    def call(self,name,**args):return self.session.execute({'name':name,'arguments':json.dumps(args)})

    def test_public_url_and_dns_policy(self):
        for url in ('file:///tmp/file','http://example.com','https://user:password@example.com',
                    'https://127.0.0.1','https://[::1]','https://192.168.0.1','https://169.254.169.254',
                    'https://example.local','https://224.0.0.1','https://[2002:7f00:1::]',
                    'https://example.com:8080','https://example.com/\r\nHeader:value'):
            with self.subTest(url=url),self.assertRaises(ValueError):web.public_url(url)
        self.assertEqual(web.public_url('https://EXAMPLE.com/test#part'),'https://example.com/test')
        records=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443)),
                 (socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))]
        with patch.object(socket,'getaddrinfo',return_value=records):
            with self.assertRaises(ValueError):web.public_addresses('example.com')

    def test_redirect_rechecks_address_and_uses_pinned_connection(self):
        response=Mock(status=302)
        response.getheader.side_effect=lambda name,default=None:'https://127.0.0.1/private' if name=='Location' else default
        connection=Mock();connection.getresponse.return_value=response
        with patch.object(web,'public_addresses',return_value=['93.184.216.34']),patch.object(web,'PublicHTTPS',return_value=connection) as factory:
            with self.assertRaises(ValueError):web.download('https://example.com')
        self.assertEqual(factory.call_args.args[:2],('example.com','93.184.216.34'))
        self.assertEqual(factory.call_count,1);connection.close.assert_called_once()
        self.assertNotIn('Authorization',connection.request.call_args.kwargs['headers'])

    def test_page_cache_pagination_html_filter_and_saved_hash(self):
        raw=b'<html><title>Source</title><script>secret script</script><style>style text</style><p>Hello world</p><a href="/paper">Paper</a></html>'
        with patch.object(web,'download',return_value=('https://example.com/',raw,'text/html','utf-8')) as download:
            a=self.call('web_fetch',url='https://example.com/',offset=0,limit=8)
            b=self.call('web_fetch',url='https://example.com/',offset=8,limit=24000)
        self.assertEqual(download.call_count,1)
        self.assertEqual(a['next_offset'],8)
        combined=a['text']+b['text'];self.assertIn('Hello world',combined)
        self.assertNotIn('secret script',combined);self.assertNotIn('style text',combined)
        self.assertEqual(a['links'],['https://example.com/paper'])
        saved=json.loads((self.session.root/'page-1.json').read_text())
        self.assertEqual(saved['sha256'],a['sha256']);self.assertEqual(saved['text'],combined)

    def grounded(self):
        return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'A sourced synthesis.'}]},
            'groundingMetadata':{'webSearchQueries':['agent history'],'groundingChunks':[{'web':{'uri':'https://example.com/paper','title':'Original paper'}}],
                'groundingSupports':[{'segment':{'text':'A sourced synthesis.'},'groundingChunkIndices':[0]}],
                'searchEntryPoint':{'renderedContent':'<style>.x { color: blue; }</style><a href="https://www.google.com/search?q=agents">Search</a>'}}}]}

    def test_grounding_required_receipts_suggestions_and_search_budget(self):
        with patch.object(gemini,'Client') as client:
            client.return_value.request.return_value={'candidates':[{'content':{'parts':[{'text':'Unsupported answer'}]}}]}
            self.assertFalse(self.call('web_search',query='agent history')['ok'])
            client.return_value.request.return_value=self.grounded()
            result=self.call('web_search',query='agent history primary paper')
            self.assertTrue(result['ok']);self.assertTrue(result['summary_is_synthesis'])
            self.assertEqual(result['sources'][0]['title'],'Original paper')
            report=(self.session.root/'web-report.html').read_text()
            self.assertIn('Google Search suggestions',report);self.assertIn('srcdoc=',report)
            self.assertNotIn('do-not-save',(self.session.root/'search-2.json').read_text())
            self.assertFalse(self.call('web_search',query='more')['ok'])
            self.assertEqual(client.return_value.request.call_count,2)

    def test_uncertain_search_is_not_automatically_repeated(self):
        with patch.object(gemini,'Client') as client:
            client.return_value.request.side_effect=gemini.ProviderError('timeout',uncertain=True)
            self.assertFalse(self.call('web_search',query='history')['ok'])
            again=self.call('web_search',query='history')
            self.assertIn('uncertain',again['error']);self.assertEqual(client.return_value.request.call_count,1)
        self.assertEqual(json.loads((self.session.root/'search-1.json').read_text())['status'],'uncertain')

    def test_fetch_remains_available_without_search_credentials(self):
        session=web.Session(self.receipt)
        self.assertEqual([d['name'] for d in session.definitions()],['web_fetch'])
        self.assertFalse(session.execute({'name':'web_search','arguments':'{"query":"test"}'})['ok'])
        self.assertEqual([d['name'] for d in loop.definitions([],session)],['web_fetch'])

    def test_one_search_evidence_document_is_queued_on_the_answer(self):
        from bridge import State
        state=State(Path(self.temp.name)/'state.sqlite');job={'id':73}
        with patch.object(gemini,'DATA',Path(self.temp.name)):
            receipt=gemini.DATA/'orchestrator-reads'/(hashlib.sha256(b'73').hexdigest()+'.json')
            session=web.Session(receipt,{'api_key':'test'})
            with state.db:web.queue_report(state,job,'orchestrator:73')
            self.assertEqual(state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0],0)
            with patch.object(gemini,'Client') as client:
                client.return_value.request.return_value=self.grounded()
                self.assertTrue(session.execute({'name':'web_search','arguments':'{"query":"agent history"}'})['ok'])
            with state.db:
                web.queue_report(state,job,'orchestrator:73');web.queue_report(state,job,'orchestrator:73')
            rows=state.db.execute('SELECT * FROM media_outbox').fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['event_id'],'orchestrator:73')
            self.assertTrue(Path(rows[0]['path']).is_file())
        state.db.close()

    def test_web_loop_all_provider_formats_without_project(self):
        for provider in ('gemini','openai','qwen','deepseek','openrouter'):
            with self.subTest(provider=provider):
                session=web.Session(self.receipt)
                arguments={'url':'https://example.com/','offset':0,'limit':100}
                final=json.dumps({'answer':'Source: https://example.com/','action':None})
                if provider=='gemini':
                    responses=[{'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':'web_fetch','args':arguments}}]}}]},
                               {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':final}]}}]}]
                    request={'generationConfig':{},'systemInstruction':{'parts':[{'text':'Answer'}]},'contents':[]}
                elif provider=='openai':
                    responses=[{'status':'completed','output':[{'type':'function_call','call_id':'c','name':'web_fetch','arguments':json.dumps(arguments)}]},
                               {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':final}]}]}]
                    request={'instructions':'Answer','input':[]}
                else:
                    responses=[{'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'c','type':'function','function':{'name':'web_fetch','arguments':json.dumps(arguments)}}]}}]},
                               {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':final}}]}]
                    request={'messages':[{'role':'system','content':'Answer'}]}
                client=Mock();client.request.side_effect=responses
                with patch.object(web,'download',return_value=('https://example.com/',b'Public source','text/plain','utf-8')):
                    result=loop.run(provider,client,'test',request,[],self.receipt,session)
                self.assertIsNone(json.loads(result)['action'])
                self.assertEqual(json.loads(self.receipt.read_text())[0]['reads'][0]['result']['text'],'Public source')

    def test_oversized_page_is_rejected_before_body_read(self):
        response=Mock(status=200)
        values={'Content-Type':'text/html','Content-Length':str(web.MAX_BYTES+1)}
        response.getheader.side_effect=lambda name,default=None:values.get(name,default)
        connection=Mock();connection.getresponse.return_value=response
        with patch.object(web,'public_addresses',return_value=['93.184.216.34']),patch.object(web,'PublicHTTPS',return_value=connection):
            with self.assertRaisesRegex(ValueError,'1 MB'):web.download('https://example.com')
        response.read1.assert_not_called()


if __name__=='__main__':unittest.main()
