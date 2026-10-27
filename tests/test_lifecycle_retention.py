"""Tiny offline fixtures for retirement, failure preservation and runner integration."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import lifecycle_retention as retention, qualify_lifecycle as gate


class Retention(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def run_fixture(self, name, finished, passed=True):
        root = self.root / name; root.mkdir(); retention.register(root)
        group = root / 'text-group'; (group / 'journals').mkdir(parents=True)
        (group / 'journals' / 'fixture.txt').write_text('synthetic original')
        (group / 'tests.log').write_text('OK' if passed else 'Traceback: useful failure')
        (group / 'result.json').write_text(json.dumps(dict(passed=passed)))
        evidence = {str(p.relative_to(root)): retention.sha(p) for p in group.rglob('*') if p.is_file()}
        report = dict(scope='Controlled offline shared lifecycle', finished=finished,
                      passed=passed, groups=[dict(group='text-group')], evidence=evidence)
        (root / 'report.json').write_text(json.dumps(report)); (root / 'AUDIT.md').write_text('original audit')
        retention.complete(root)
        return root

    def test_newest_failure_keeps_full_fixtures_old_logs_and_reports_survive(self):
        old = self.run_fixture('old', 1, False); newest = self.run_fixture('newest', 2, False)
        before = {p: p.read_bytes() for p in (old/'report.json', old/'AUDIT.md', old/'text-group/tests.log')}
        result = retention.prune(self.root)
        self.assertEqual(result['latest'], str(newest)); self.assertFalse((old/'text-group/journals').exists())
        self.assertTrue((newest/'text-group/journals/fixture.txt').exists())
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(retention.prune(self.root)['retired'], [])

    def test_active_interrupted_and_unregistered_directories_are_untouched(self):
        active = self.run_fixture('active', 1)
        interrupted = self.root/'interrupted'; interrupted.mkdir(); retention.register(interrupted)
        (interrupted/'unfinished.log').write_text('partial failure')
        legacy = self.run_fixture('legacy', 0); (legacy/retention.MARKER).unlink()
        self.run_fixture('latest', 2)
        with retention.lock(active/'.lifecycle.lock'):
            result = retention.prune(self.root)
        self.assertTrue((active/'text-group/journals').exists())
        self.assertTrue((legacy/'text-group/journals').exists())
        self.assertEqual((interrupted/'unfinished.log').read_text(), 'partial failure')
        self.assertGreaterEqual(len(result['skipped']), 2)

    def test_changed_receipt_or_fixture_cannot_authorize_deletion(self):
        changed = self.run_fixture('changed', 1); extra = self.run_fixture('extra', 2)
        self.run_fixture('latest', 3)
        (changed/'report.json').write_text('{}')
        (extra/'text-group/journals/unregistered.txt').write_text('unrelated user file')
        result = retention.prune(self.root)
        self.assertEqual(len(result['skipped']), 2)
        self.assertTrue((changed/'text-group/journals/fixture.txt').exists())
        self.assertTrue((extra/'text-group/journals/unregistered.txt').exists())

    def test_symlink_and_copied_marker_do_not_grant_cleanup(self):
        old = self.run_fixture('old', 1); self.run_fixture('latest', 2)
        external = self.root/'external'; external.mkdir(); (external/'keep.txt').write_text('keep')
        (old/'text-group/journals/link').symlink_to(external, target_is_directory=True)
        copied = self.root/'copied'; copied.mkdir()
        for name in (retention.MARKER, 'report.json', 'AUDIT.md'):
            (copied/name).write_bytes((old/name).read_bytes())
        result = retention.prune(self.root)
        self.assertEqual(len(result['skipped']), 2)
        self.assertEqual((external/'keep.txt').read_text(), 'keep')
        self.assertTrue((old/'text-group/journals/fixture.txt').exists())

    def test_interrupted_removal_has_durable_receipt_and_resumes(self):
        old = self.run_fixture('old', 1); latest = self.run_fixture('latest', 2)
        def partial(path):
            (path/'fixture.txt').unlink()
            raise OSError('simulated interruption')
        with patch.object(retention.shutil, 'rmtree', side_effect=partial):
            result = retention.prune(self.root)
        self.assertEqual(len(result['skipped']), 1)
        self.assertEqual(json.loads((old/retention.RETIRED).read_text())['state'], 'retiring')
        self.assertTrue((old/'text-group/tests.log').exists())
        result = retention.prune(self.root)
        self.assertEqual(len(result['retired']), 1)
        self.assertFalse((old/'text-group/journals').exists())
        self.assertTrue((latest/'text-group/journals').exists())

    def test_tampered_resume_path_cannot_escape_owned_journals(self):
        old = self.run_fixture('old', 1); self.run_fixture('latest', 2)
        with patch.object(retention.shutil, 'rmtree', side_effect=OSError('stop')):
            retention.prune(self.root)
        record = json.loads((old/retention.RETIRED).read_text())
        record['trees'] = ['../external/journals']; retention.write(old/retention.RETIRED, record)
        result = retention.prune(self.root)
        self.assertTrue(result['skipped']); self.assertTrue((old/'text-group/journals/fixture.txt').exists())


class Runner(unittest.TestCase):
    def test_completed_runner_retires_old_evidence_without_rewriting_pass_or_failure(self):
        real_run = subprocess.run
        failed = False
        # Actual local child writes tiny evidence. No orchestration/media/provider work.
        program = """import json,sys
from pathlib import Path
p=Path(sys.argv[1]); failed=sys.argv[2]=='True'
(p/'journals').mkdir();(p/'journals/data.txt').write_text('tiny fixture')
(p/'tests.log').write_text('useful traceback' if failed else 'OK')
(p/'result.json').write_text(json.dumps(dict(group='probe',passed=not failed,tests=1)))
sys.exit(1 if failed else 0)
"""
        def worker(command, **kwargs):
            return real_run([sys.executable, '-B', '-c', program, command[-1], str(failed)], **kwargs)
        with tempfile.TemporaryDirectory() as temp, patch.object(gate, 'GROUPS', {'probe':['synthetic']}), \
                patch.object(gate, 'sources', return_value={'source.py':'original'}), \
                patch.object(gate.importlib.metadata, 'version', return_value='controlled'), \
                patch.object(gate.subprocess, 'run', side_effect=worker):
            root=Path(temp).resolve(); first=root/'first'; second=root/'second'
            with patch.object(sys, 'argv', ['qualify', '--output', str(first)]):
                self.assertEqual(gate.main(), 0)
            with patch.object(sys, 'argv', ['qualify', '--verify', str(first/'report.json')]):
                self.assertEqual(gate.main(), 0)
            failed=True
            with patch.object(sys, 'argv', ['qualify', '--output', str(second)]):
                self.assertEqual(gate.main(), 1)
            self.assertTrue(json.loads((first/'report.json').read_text())['passed'])
            self.assertFalse(json.loads((second/'report.json').read_text())['passed'])
            self.assertFalse((first/'probe/journals').exists())
            self.assertTrue((second/'probe/journals/data.txt').exists())
            self.assertEqual((second/'probe/tests.log').read_text(), 'useful traceback')
            with patch.object(sys, 'argv', ['qualify', '--verify', str(first/'report.json')]):
                with self.assertRaisesRegex(ValueError, 'retired'):
                    gate.main()


if __name__ == '__main__':
    unittest.main()
