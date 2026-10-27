"""Observed alternative reads, no live network or provider calls."""
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import web_sources

class Session:
    calls=[]
    def __init__(self,*_):pass
    def search(self,query):
        return dict(queries=[query],retrieved_at=1,sources=[dict(url='https://store.example/'+str(i)) for i in range(3)])
    def fetch(self,url,*_,**kwargs):
        self.calls.append(url)
        if url.endswith(('0','1')):raise ValueError('HTTP 403')
        return dict(url=url,requested_url=url,title='Real product page',text='Price USD 100',retrieved_at=2,sha256='a'*64,content_type='text/html',total_characters=13,next_offset=None)

class Tests(unittest.TestCase):
    def test_observed_publishers_share_capacity_after_failure(self):
        import json
        class Diverse(Session):
            def search(self,query):return dict(queries=[query],retrieved_at=1,sources=[dict(url=u) for u in ('https://store.example/0','https://store.example/1','https://other.example/2')])
        Session.calls=[]
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.Session',Diverse):
            raw,_=web_sources.collect(['exact subject'],[],'test',root,dict(models=dict(text='test')))
        self.assertEqual(Session.calls[:2],['https://store.example/0','https://other.example/2'])
        self.assertEqual(json.loads(raw)['entries'][0]['retrievals'][0]['outcome'],'failed')

    def test_fallback_preserves_long_constraints_and_uses_observed_exclusions(self):
        from orchestrator.collection_core import fallback_queries
        subject=dict(id='part',queries=['specified component below USD 200'],required_options=2)
        result=fallback_queries([subject],[dict(item='part',shortfall=2)],subject['queries'],suffix=' current information',avoid={'part':['failed.example']})
        self.assertEqual(result[0]['queries'],['specified component below USD 200 -site:failed.example current information'])
        subject['queries']=['x'*245+' USD']
        self.assertEqual(fallback_queries([subject],[dict(item='part',shortfall=2)],subject['queries'],suffix=' additional details'),[])

    def test_failed_observed_pages_use_next_candidate_and_keep_failures(self):
        import json
        Session.calls=[]
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.Session',Session):
            raw,_=web_sources.collect(['yellow sofa US'],['store.example'],'test',root,dict(models=dict(text='test')))
        entry=json.loads(raw)['entries'][0]
        self.assertEqual(Session.calls,['https://store.example/0','https://store.example/1','https://store.example/2'])
        self.assertEqual(len(entry['errors']),2);self.assertEqual(entry['status'],'source_fetched')
        self.assertEqual(entry['fallback_reads'][0]['url'],'https://store.example/2')
        self.assertIn('candidates',json.loads(raw)['interpretation'])

    def test_twenty_query_legacy_batch_stays_in_original_read_allocation(self):
        Session.calls=[]
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.Session',Session):
            web_sources.collect(['query '+str(i) for i in range(20)],['store.example'],'test',root,dict(models=dict(text='test')))
        self.assertEqual(len(Session.calls),40)

    def test_prepared_third_successful_page_is_not_labeled_a_failure_fallback(self):
        import json
        class Successful(Session):
            def fetch(self,url,*_,**kwargs):
                return dict(url=url,requested_url=url,title='Product page',text='USD 100',retrieved_at=2,sha256='a'*64,content_type='text/html',total_characters=7,next_offset=None)
        spec=dict(path='queries.json',sha256='a'*64,data=dict(version=1,targets=[dict(id='F01',queries=['yellow sofa US'],required_options=3)]))
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.Session',Successful):
            raw,_=web_sources.collect(['yellow sofa US'],['store.example'],'test',root,dict(models=dict(text='test')),prepared_spec=spec)
        entry=json.loads(raw)['entries'][0]
        self.assertEqual(len(entry['pages']),3)
        self.assertEqual(entry['errors'],[])
        self.assertEqual(entry['fallback_reads'],[])

    def test_eighteen_prepared_queries_use_registered_eighty_request_allocation(self):
        import json
        Session.calls=[];queries=['item '+str(i) for i in range(18)]
        spec=dict(path='queries.json',sha256='a'*64,data=dict(version=1,targets=[dict(id=str(i),queries=[q],required_options=3) for i,q in enumerate(queries)]))
        class Unique(Session):
            def search(self,query):
                return dict(queries=[query],retrieved_at=1,sources=[dict(url='https://store.example/'+query.replace(' ','-')+'/'+str(i)) for i in range(3)])
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.Session',Unique):
            raw,_=web_sources.collect(queries,['store.example'],'test',root,dict(models=dict(text='test')),prepared_spec=spec)
        entries=json.loads(raw)['entries'];self.assertEqual(len(Session.calls),54);self.assertLessEqual(18+len(Session.calls),80)
        # Unused allocation rolls forward, but these queries each expose only
        # three literal URLs. A larger remaining allowance is not another read.
        self.assertTrue(all(e['read_allocation']['limit']>=3 and e['read_allocation']['submitted']==3 and len(e['pages'])==1 and len(e['errors'])==2 for e in entries))
