"""Shared admission and paired reader regressions; synthetic transports only."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import source_fallback as f,subject_contract
from orchestrator.runtime_outcomes import UncertainOperation
from tests.test_evidence_workload import pack,page

class Boundary(unittest.TestCase):
    def test_inventory_rejects_freeform_unsealed_tampered_and_duplicate_inputs(self):
        with self.assertRaisesRegex(ValueError,'Prepare collection.subjects'):subject_contract.validate_input({'inventory':[{'name':'Chair'}]})
        p=dict(source_path='input.txt',summary_path='summary.md',max_records=2,fields=[])
        ctx=dict(source=dict(path='input.txt',sha256='a'*64,media_type='text/plain'),text='Chair')
        r=dict(kind='item',slot=1,label='Chair',attributes={},quote='Chair',bbox=None,notes='')
        doc=subject_contract.document([r],p,ctx)
        with self.assertRaisesRegex(ValueError,'not sealed'):subject_contract.validate_input(doc)
        doc=subject_contract.document([r,dict(kind='end',count=1,notes='Known scope')],p,ctx)
        self.assertEqual(subject_contract.validate_input(doc),doc)
        doc['items'][0]['label']='Uncommitted change'
        with self.assertRaises(ValueError):subject_contract.validate_input(doc)
        with self.assertRaisesRegex(ValueError,'Duplicate'):subject_contract.validate_input({'items':[{'id':'a'},{'id':'a'}]})
        self.assertEqual(subject_contract.validate_input({'items':[{'id':'a'}]}),{'items':[{'id':'a'}]})

    def source(self):return pack([dict(query='subject',target_ids=['A'],grounding=[dict(url='https://shop.example/product')],pages=[])])
    def captured(self,url,*_):return dict(page(url,'Product'),capture_method='direct-public-http',images=[dict(url='https://shop.example/image.jpg',basis='observed-page-metadata')])

    def test_http_failure_then_render_uses_two_total_reads_and_reuses_exact_outcomes(self):
        source=self.source()
        with tempfile.TemporaryDirectory() as root,patch('task_relay.source_browser.read_http',side_effect=ValueError('HTTP 429')) as direct,patch('task_relay.source_browser.render',side_effect=self.captured) as render:
            raw,v=f.collect(source,[],2,root)
            self.assertEqual((direct.call_count,render.call_count),(1,1))
            out=json.loads(raw);self.assertEqual([r['reader'] for r in out['rendered_fallback']['reads']],['http','rendered'])
            self.assertEqual((v['unavailable'],v['rendered']),(1,1));self.assertTrue(f.extends(source,out))
            self.assertEqual(f.collect(source,[],2,root)[0],raw)
            self.assertEqual((direct.call_count,render.call_count),(1,1))
            self.assertEqual(f.candidates(out,[],adaptive=True),[])

    def test_one_read_limit_does_not_hide_a_second_transport_and_continuation_keeps_ceiling(self):
        with tempfile.TemporaryDirectory() as root,patch('task_relay.source_browser.read_http',side_effect=ValueError('HTTP 429')) as direct,patch('task_relay.source_browser.render',side_effect=self.captured) as render:
            out=json.loads(f.collect(self.source(),[],1,Path(root)/'first')[0]);self.assertEqual(render.call_count,0)
            resumed=json.loads(f.collect(out,[],1,Path(root)/'next')[0])
            self.assertEqual((direct.call_count,render.call_count),(1,1));self.assertEqual(len(resumed['rendered_fallback']['reads']),2)

    def test_render_failure_can_use_untried_http_without_repeating_guard_failure(self):
        source=self.source();source['rendered_fallback']=dict(reads=[dict(url='https://shop.example/product',outcome='unavailable',reader='rendered',reason='Invalid InterceptionId')])
        with tempfile.TemporaryDirectory() as root,patch('task_relay.source_browser.read_http',side_effect=self.captured) as direct,patch('task_relay.source_browser.render',side_effect=AssertionError('No replay')):
            out=json.loads(f.collect(source,[],1,root)[0]);self.assertEqual(direct.call_count,1)
            self.assertEqual(out['rendered_fallback']['reads'][0],source['rendered_fallback']['reads'][0])

    def test_saved_http_pixels_are_not_refetched_and_uncertainty_stops_both_methods(self):
        source=self.source();source['entries'][0]['pages']=[self.captured('https://shop.example/product')]
        self.assertEqual(f.candidates(source,[],adaptive=True),[])
        with tempfile.TemporaryDirectory() as root,patch('task_relay.source_browser.read_http',side_effect=UncertainOperation('Unknown read')) as direct,patch('task_relay.source_browser.render',side_effect=AssertionError('No uncertain fallback')):
            with self.assertRaises(UncertainOperation):f.collect(self.source(),[],2,root)
            with self.assertRaises(UncertainOperation):f.collect(self.source(),[],2,root)
            self.assertEqual(direct.call_count,1)

    def test_http_adapter_retains_original_receipt_and_refuses_missing_or_changed_bytes(self):
        from task_relay.source_browser import read_http
        raw=b'<html><title>Product</title><body>Observed product<img src="/item.jpg"></body></html>'
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.download',return_value=('https://shop.example/product',raw,'text/html','utf-8')) as read:
            a=read_http('https://shop.example/product',[],root);self.assertEqual(a['images'][0]['url'],'https://shop.example/item.jpg')
            self.assertEqual(read_http('https://shop.example/product',[],root),a);self.assertEqual(read.call_count,1)
            (Path(root)/'http/page-1.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):read_http('https://shop.example/product',[],root)
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'http-intent.json').write_text(json.dumps(dict(url='https://shop.example/product',domains=[],reader='http')))
            with self.assertRaises(UncertainOperation):read_http('https://shop.example/product',[],root)

    def test_pending_http_receipt_blocks_cancellation_and_another_reader(self):
        from orchestrator.operation_inspection import rendered
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'render-1';p.mkdir();(p/'http-intent.json').write_text('{}')
            state={};rendered(Path(root),state,{})
            self.assertEqual(state['status'],'uncertain')
            (Path(root)/'cancel.json').write_text('{}')
            with self.assertRaises(UncertainOperation):f.check_cancel(Path(root))
