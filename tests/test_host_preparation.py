import json
import unittest
from pathlib import Path
from tests.test_orchestrator import Tests as RuntimeFixture,pair
from orchestrator.host_script import validate_script_bytes

class Tests(unittest.TestCase):
    setUp=RuntimeFixture.setUp
    tearDown=RuntimeFixture.tearDown

    def prepare(self):
        contract=self.root/'contract.json';contract.write_text('{}')
        aid=self.rt.register(contract,'Host contract')
        p=pair(gate='Select script and checks');producer,review=p['tasks']
        producer['inputs']=[dict(artifact=aid,path='operation-support/rhino.run_python/contract.json',purpose='Host contract',authority='Contract')]
        producer['outputs']=[dict(path='model.py',purpose='Host script'),dict(path='checks.json',purpose='Checks')]
        producer['selection_outputs']=['model.py','checks.json']
        review['inputs']=[dict(from_task='produce',output=o['path'],path='candidate/'+o['path'],purpose='Review',authority='Candidate') for o in producer['outputs']]
        self.rt.create(p);self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        return aid,Path(self.factory.sessions[aid]['frozen']['workspace'])

    def test_oversized_script_cannot_reach_review_and_draft_is_preserved(self):
        aid,ws=self.prepare();(ws/'model.py').write_bytes(b'#'+b' '*100000)
        self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.assertEqual(self.factory.calls,[aid])
        self.assertIsNotNone(self.rt.output('demo','produce','model.py'))
        self.assertIn('100001',self.rt.db.execute('SELECT error FROM production_attempts WHERE id=?',(aid,)).fetchone()[0])

    def test_bounded_script_can_reach_independent_review(self):
        aid,ws=self.prepare();(ws/'model.py').write_text('x = 1\n')
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_review')
        self.assertEqual(self.rt.task('demo','review')['attempts'],1)

    def test_bound_uses_encoded_bytes_and_rejects_empty_scripts(self):
        validate_script_bytes(b'#'+b' '*99999)
        for data in (b'',('é'*50001).encode()):
            with self.assertRaises(ValueError):validate_script_bytes(data)
