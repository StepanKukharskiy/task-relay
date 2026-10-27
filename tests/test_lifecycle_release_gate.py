"""Negative controls for the release gate, independent of artifact acceptance."""
import copy
import io
import tempfile
from pathlib import Path
import unittest
from scripts.qualify_lifecycle import GROUPS, StrictResult, validate, sources


class Tests(unittest.TestCase):
    def test_fixture_and_packaged_asset_changes_invalidate_source_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('tests/fixtures/records.json','task_relay/assets/contract.json','orchestrator/host.rb'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('original')
                before=sources(root);self.assertIn(name,before)
                p.write_text('changed');self.assertNotEqual(sources(root),before)
    def run_case(self,case):
        return unittest.TextTestRunner(stream=io.StringIO(),resultclass=StrictResult).run(unittest.TestSuite([case]))
    def test_skips_expected_failures_empty_and_real_failures_fail_closed(self):
        class Cases(unittest.TestCase):
            def ok(self):pass
            @unittest.skip('Unavailable dependency')
            def missing(self):pass
            @unittest.expectedFailure
            def known(self):self.fail('Not qualified')
            def bad(self):self.fail('Broken boundary')
        self.assertTrue(self.run_case(Cases('ok')).gate_ok())
        for name in ('missing','known','bad'):
            self.assertFalse(self.run_case(Cases(name)).gate_ok())
        result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=StrictResult).run(unittest.TestSuite())
        self.assertFalse(result.gate_ok())
    def test_missing_group_failed_process_or_changed_source_cannot_use_receipt(self):
        current={'module.py':'a'}
        good=dict(passed=True,sources=current,matrix=GROUPS,
                  groups=[dict(group=k,passed=True,tests=1,returncode=0) for k in GROUPS])
        validate(good,current)
        for change in ('missing','exit','source','matrix'):
            bad=copy.deepcopy(good)
            if change=='missing':bad['groups'].pop()
            elif change=='exit':bad['groups'][0]['returncode']=1
            elif change=='source':bad['sources']['module.py']='b'
            else:bad['matrix'].pop(next(iter(GROUPS)))
            with self.assertRaises(ValueError):validate(bad,current)


if __name__=='__main__':unittest.main()
