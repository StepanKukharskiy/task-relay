import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from task_relay import orchestrator_web as web
from orchestrator import web_sources
from tests.test_web_sources import FakeSession,CONFIG

LINK='https://vertexaisearch.cloud.google.com/grounding-api-redirect/frozen-reference'
PRODUCT='https://parts.example.com/product'


class Tests(unittest.TestCase):
    def response(self,status=200,location=None):
        r=Mock(status=status);headers={'Content-Type':'text/plain'}
        if location:headers['Location']=location
        r.getheader.side_effect=lambda k,default=None:headers.get(k,default)
        r.headers.get_content_charset.return_value='utf-8';r.read1.side_effect=[b'Actual product $99.99',b'']
        return r

    def test_grounded_wrapper_reaches_only_the_selected_public_retailer(self):
        first=self.response(302,PRODUCT);final=self.response()
        a=Mock();a.getresponse.return_value=first;b=Mock();b.getresponse.return_value=final
        with patch.object(web,'public_addresses',return_value=['93.184.216.34']),patch.object(web,'PublicHTTPS',side_effect=[a,b]):
            url,raw,_,_=web.download(LINK,allowed_hosts=['example.com'])
        self.assertEqual(url,PRODUCT);self.assertEqual(raw,b'Actual product $99.99');first.read1.assert_not_called()

    def test_redirect_to_an_unselected_domain_is_rejected_before_target_request(self):
        first=self.response(302,'https://other.example.org/product');a=Mock();a.getresponse.return_value=first
        with patch.object(web,'public_addresses',return_value=['93.184.216.34']) as dns,patch.object(web,'PublicHTTPS',return_value=a) as connect:
            with self.assertRaisesRegex(ValueError,'selected source domains'):web.download(LINK,allowed_hosts=['example.com'])
        self.assertEqual(connect.call_count,1);self.assertEqual(dns.call_count,1);first.read1.assert_not_called()

    def test_proxy_body_and_lookalike_endpoint_cannot_become_retailer_evidence(self):
        first=self.response();a=Mock();a.getresponse.return_value=first
        with patch.object(web,'public_addresses',return_value=['93.184.216.34']),patch.object(web,'PublicHTTPS',return_value=a):
            with self.assertRaisesRegex(ValueError,'no page body'):web.download(LINK,allowed_hosts=['example.com'])
        first.read1.assert_not_called()
        self.assertFalse(web.grounding_redirect('https://vertexaisearch.cloud.google.com.evil.example/grounding-api-redirect/x'))
        self.assertFalse(web.grounding_redirect('https://vertexaisearch.cloud.google.com/unrelated'))

    def test_collection_retains_wrapper_and_actual_page_without_changing_domain_grant(self):
        calls=[]
        class Wrapped(FakeSession):
            def search(self,q):return dict(sources=[dict(url=LINK,title='example.com')],queries=[q],retrieved_at=123)
            def fetch(self,url,offset,limit,allowed_hosts=None):
                calls.append((url,allowed_hosts));value=super().fetch(url,offset,limit,allowed_hosts);value['url']=PRODUCT;return value
        with tempfile.TemporaryDirectory() as temp,patch.object(web,'Session',Wrapped):
            raw,counts=web_sources.collect(['actual product'],['example.com'],'fixture-text',Path(temp),CONFIG)
        pack=json.loads(raw);self.assertEqual(counts['fetched'],1)
        self.assertEqual(pack['entries'][0]['grounding'][0]['url'],LINK)
        self.assertEqual(pack['entries'][0]['pages'][0]['url'],PRODUCT)
        self.assertEqual(pack['entries'][0]['pages'][0]['requested_url'],LINK)
        self.assertEqual(calls,[(LINK,['example.com'])])

    def test_large_html_shell_keeps_small_bounded_visible_text_and_raw_hash(self):
        import hashlib
        raw=b'<html><script>'+b'x'*1_200_000+b'</script><p>Actual product $99.99</p></html>'
        response=self.response();headers={'Content-Type':'text/html','Content-Length':str(len(raw))}
        response.getheader.side_effect=lambda k,default=None:headers.get(k,default)
        response.read1.side_effect=[raw[i:i+65536] for i in range(0,len(raw),65536)]+[b'']
        connection=Mock();connection.getresponse.return_value=response
        with tempfile.TemporaryDirectory() as temp,patch.object(web,'public_addresses',return_value=['93.184.216.34']),patch.object(web,'PublicHTTPS',return_value=connection):
            page=web.Session(Path(temp)/'receipt.json',CONFIG).fetch(PRODUCT,0,web.MAX_CHARS,allowed_hosts=['example.com'])
        self.assertIn('Actual product $99.99',page['text']);self.assertLess(len(page['text']),100)
        self.assertEqual(page['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(page['raw_bytes'],len(raw));self.assertEqual(page['raw_byte_limit'],web.MAX_HTML_BYTES)

    def test_plain_text_budget_is_preserved(self):
        response=self.response();headers={'Content-Type':'text/plain','Content-Length':str(web.MAX_BYTES+1)}
        response.getheader.side_effect=lambda k,default=None:headers.get(k,default)
        connection=Mock();connection.getresponse.return_value=response
        with patch.object(web,'public_addresses',return_value=['93.184.216.34']),patch.object(web,'PublicHTTPS',return_value=connection):
            with self.assertRaisesRegex(ValueError,'raw bytes'):web.download(PRODUCT,allowed_hosts=['example.com'])
        response.read1.assert_not_called()


if __name__=='__main__':unittest.main()
