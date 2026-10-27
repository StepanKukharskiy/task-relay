"""Deterministic receipt reuse never reuses semantic acceptance."""
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import verification as v
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from tests.test_orchestrator import FakeFactory,pair


class Receipts(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close);v.initialize(self.db);self.db.commit()

    def check(self,raw=b'{"value":1}',**kwargs):
        with transaction(self.db):return v.verify(self.db,'json.structure',raw,code={'version':'fixture'},**kwargs)

    def test_exact_reuse_and_bytes_parameters_code_invalidation(self):
        first=self.check()
        with patch.object(v,'evaluate',side_effect=AssertionError('Must reuse')):
            second=self.check()
        self.assertEqual(first['receipt'],second['receipt']);self.assertTrue(second['reused'])
        self.assertNotEqual(self.check(b'{"value":2}')['receipt'],first['receipt'])
        self.assertFalse(self.check(parameters={'unexpected':True})['passed'])
        with transaction(self.db):changed=v.verify(self.db,'json.structure',b'{"value":1}',code={'version':'new'})
        self.assertFalse(changed['reused'])

    def test_corrupted_receipt_is_recomputed_and_failed_check_never_passes(self):
        first=self.check()
        with self.db:self.db.execute("UPDATE production_verifications SET result='{}' WHERE id=?",(first['receipt'],))
        next_check=self.check();self.assertFalse(next_check['reused']);self.assertNotEqual(first['receipt'],next_check['receipt'])
        bad=self.check(b'{"a":1,"a":2}');self.assertFalse(bad['passed'])
        self.assertEqual(self.check(b'{"a":1,"a":2}')['receipt'],bad['receipt'])

    def test_receipts_roll_back_with_failed_dispatch_intent(self):
        with self.assertRaisesRegex(ValueError,'rollback'):
            with transaction(self.db):
                v.verify(self.db,'json.structure',b'{}',code={})
                raise ValueError('rollback')
        self.assertEqual(self.db.execute('SELECT count(*) FROM production_verifications').fetchone()[0],0)

    def test_changes_are_structural_and_never_approval(self):
        old=b'{"slides":[{"text":"old","image":"same.png"},{"text":"unchanged"}]}'
        new=old.replace(b'old',b'new')
        result=v.json_changes(old,new)
        self.assertEqual(result['changed_json_pointers'],['/slides/0/text'])
        self.assertFalse(result['semantic_acceptance']);self.assertTrue(result['whole_candidate_review_required'])
        self.assertEqual(v.json_changes(old,b'{"slides":[]}')['changed_json_pointers'],['/slides'])
        self.assertFalse(v.json_changes(b'{"a":1,"b":1}',b'{"a":2,"b":2}',limit=1)['complete'])

    def test_image_receipt_reuse_still_invalidates_changed_pixels(self):
        from PIL import Image
        def png(color):
            out=io.BytesIO();Image.new('RGB',(2,2),color).save(out,format='PNG');return out.getvalue()
        raw=png('red')
        with transaction(self.db):first=v.verify(self.db,'image.decode',raw,code={})
        with transaction(self.db),patch.object(v,'evaluate',side_effect=AssertionError('No decode twice')):
            self.assertTrue(v.verify(self.db,'image.decode',raw,code={})['reused'])
        with transaction(self.db):changed=v.verify(self.db,'image.decode',png('blue'),code={})
        self.assertNotEqual(first['receipt'],changed['receipt'])


class Integration(unittest.TestCase):
    def test_review_rejection_then_restart_reuses_evidence_but_not_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();factory=FakeFactory();rt=Runtime(root/'runtime',factory)
            try:
                source=root/'source.json';source.write_text('{"source":"unchanged"}')
                aid=rt.register(source,'Exact source');plan=pair(max_attempts=2)
                plan['tasks'][0]['inputs']=[dict(artifact=aid,path='source.json',purpose='Source',authority='Context',media_type='application/json')]
                plan['tasks'][1]['inputs'].append(copy.deepcopy(plan['tasks'][0]['inputs'][0]))
                rt.create(plan);rt.tick('demo')
                factory.finish(rt.task('demo','produce')['latest']);rt.tick('demo')
                first=rt.task('demo','review')['latest'];packet=factory.sessions[first]['frozen']['verification']
                receipt=packet['checks'][0]['receipt'];self.assertFalse(packet['semantic_acceptance'])
                factory.finish(first,decision='revise');rt.tick('demo')
                factory.finish(rt.task('demo','produce')['latest']);rt.tick('demo')
                second=rt.task('demo','review')['latest'];self.assertNotEqual(first,second)
                current=factory.sessions[second]['frozen']['verification']
                self.assertEqual(current['checks'][0]['receipt'],receipt);self.assertTrue(current['checks'][0]['reused'])
                self.assertEqual(rt.task('demo','produce')['status'],'awaiting_review')
                rt.close();rt=Runtime(root/'runtime',factory)
                factory.finish(second,decision='accept');rt.tick('demo')
                self.assertEqual(rt.status('demo')['status'],'completed')
                self.assertEqual(rt.task('demo','review')['attempts'],2)
            finally:rt.close()
