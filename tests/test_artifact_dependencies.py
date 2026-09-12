import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from orchestrator.runtime import Runtime
from orchestrator import artifact_dependencies as deps
from tests.test_orchestrator import FakeFactory, plan, task


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.factory = FakeFactory()
        self.rt = Runtime(self.root/'runtime', self.factory)

    def tearDown(self):
        self.rt.close()
        self.temp.cleanup()

    def source(self, name, content='selected geometry'):
        path = self.root/name
        path.write_text(content)
        return self.rt.register(path, 'Source version')

    def start(self, run, source, finish=True, gate=False):
        value = plan([task(inputs=[dict(artifact=source, path='source.txt',
            purpose='Selected source', authority='User-supplied context')], max_attempts=2,
            **({'user_gate': 'Choose geometry'} if gate else {}))])
        value['id'] = run
        self.rt.create(value)
        if not finish:
            return
        self.rt.tick(run)
        attempt = self.rt.task(run, 'produce')['latest']
        self.factory.finish(attempt)
        self.rt.tick(run)
        return self.rt.output(run, 'produce', 'output.txt')['id']

    def test_cross_run_chain_preserves_exact_versions_and_selection_scope(self):
        source = self.source('scene.txt')
        candidate = self.start('edit', source, gate=True)
        self.rt.select('edit', 'produce', candidate, 'Choose geometry', 'Use this shape')
        render = self.start('render', candidate)
        slides = self.start('slides', render)
        before = self.rt.db.total_changes
        lineage = self.rt.artifact_lineage(slides)
        self.assertEqual({a['id'] for a in lineage['artifacts']}, {source,candidate,render,slides})
        selected = next(a for a in lineage['artifacts'] if a['id'] == candidate)
        self.assertEqual(selected['selections'][0]['purpose'], 'Choose geometry')
        self.assertFalse(next(a for a in lineage['artifacts'] if a['id'] == render)['selections'])
        impact = self.rt.artifact_impact(candidate)
        self.assertEqual({a['id'] for a in impact['potentially_affected_outputs']}, {render,slides})
        self.assertEqual(self.rt.db.total_changes, before)
        self.assertFalse(impact['truncated'])
        self.assertEqual(impact['gaps'], [])

    def test_same_bytes_and_filename_do_not_merge_unrelated_versions(self):
        first = self.source('scene.txt')
        second = self.source('scene.txt')
        a = self.start('a', first)
        self.start('b', second)
        calls = list(self.factory.calls)
        report = self.rt.artifact_impact(first, second)
        self.assertTrue(report['same_content'])
        self.assertEqual([v['id'] for v in report['potentially_affected_outputs']], [a])
        self.assertEqual(self.factory.calls, calls)
        self.assertFalse(report['replacement']['selections'])
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0], 0)

    def test_running_and_uncertain_consumers_without_outputs_are_reported(self):
        source = self.source('input.txt')
        self.start('running', source, finish=False)
        self.rt.tick('running')
        self.start('uncertain', source, finish=False)
        session = self.rt.claim('uncertain')
        self.factory.sessions[session['id']]['status'] = {'status':'uncertain', 'reason':'No receipt'}
        self.rt.tick('uncertain')
        self.start('queued', source, finish=False)
        before = list(self.factory.calls)
        report = self.rt.artifact_impact(source)
        self.assertEqual({a['run'] for a in report['recorded_consumers']}, {'running','uncertain'})
        self.assertEqual(next(a for a in report['recorded_consumers'] if a['run']=='uncertain')['state'], 'uncertain')
        self.assertEqual([a['run'] for a in report['queued_explicit_inputs']], ['queued'])
        self.assertEqual(report['potentially_affected_outputs'], [])
        self.assertEqual(before, self.factory.calls)

    def test_revision_and_restart_do_not_rewrite_old_provenance(self):
        source = self.source('input.txt')
        old = self.start('edit', source)
        previous = self.rt.artifact_lineage(old)
        self.rt.revise('edit', 'produce', 'Change the design')
        self.rt.close()
        self.rt = Runtime(self.root/'runtime', self.factory)
        self.assertEqual(self.rt.artifact_lineage(old), previous)
        queued = self.rt.artifact_impact(old)['queued_explicit_inputs']
        self.assertEqual([a['run'] for a in queued], ['edit'])
        self.rt.tick('edit')
        self.factory.finish(self.rt.task('edit','produce')['latest'])
        self.rt.tick('edit')
        new = self.rt.output('edit','produce','output.txt')['id']
        self.assertEqual({a['id'] for a in self.rt.artifact_lineage(new)['artifacts']}, {old,new,source})

    def test_truncated_graph_never_claims_complete_impact(self):
        source = self.source('input.txt')
        for i in range(4):
            self.start('consumer'+str(i), source)
        report = self.rt.artifact_impact(source, limit=2)
        self.assertTrue(report['truncated'])
        self.assertEqual(len(report['potentially_affected_outputs']), 1)

    def test_missing_or_changed_frozen_hash_is_an_evidence_gap(self):
        source = self.source('input.txt')
        output = self.start('edit',source)
        attempt = self.rt.task('edit','produce')['latest']
        row = self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(attempt,)).fetchone()
        frozen = json.loads(row['frozen'])
        frozen['inputs'][0]['sha256'] = '0'*64
        # Simulate incomplete/corrupt historical evidence, never repair it during a read.
        self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),attempt))
        self.assertTrue(self.rt.artifact_lineage(output)['gaps'])

    def test_from_task_edges_follow_claimed_version(self):
        value = plan([task('first'),task('second',dependencies=['first'], inputs=[
            dict(from_task='first',output='output.txt',path='input.txt',purpose='Source',authority='Candidate')])])
        self.rt.create(value)
        self.rt.tick('demo')
        self.factory.finish(self.rt.task('demo','first')['latest'])
        self.rt.tick('demo')
        self.factory.finish(self.rt.task('demo','second')['latest'])
        self.rt.tick('demo')
        first = self.rt.output('demo','first','output.txt')['id']
        second = self.rt.output('demo','second','output.txt')['id']
        self.assertEqual({a['id'] for a in self.rt.artifact_lineage(second)['artifacts']},{first,second})

    def test_cli_read_does_not_dispatch(self):
        source = self.source('input.txt')
        output = self.start('edit', source)
        result = subprocess.run([sys.executable,'-m','orchestrator','--root',str(self.rt.root),
            'artifact-impact',source,'--replacement',output],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout)['replacement']['id'],output)
        self.assertEqual(len(self.factory.calls),1)

    def test_bad_identity_and_limit_rejected(self):
        source = self.source('input.txt')
        for call in (lambda:self.rt.artifact_lineage('missing'),
                     lambda:self.rt.artifact_impact(source,'missing'),
                     lambda:self.rt.artifact_impact(source,source),
                     lambda:self.rt.artifact_lineage(source,201)):
            with self.assertRaises(ValueError):call()

    def test_read_inside_transaction_does_not_commit_pending_user_decision(self):
        source = self.source('input.txt')
        candidate = self.start('edit',source,gate=True)
        with self.assertRaisesRegex(ValueError,'roll back'):
            with self.rt.transaction():
                self.rt.select('edit','produce',candidate,'Choose geometry','Selected for this purpose')
                self.assertTrue(self.rt.artifact_lineage(candidate)['artifacts'][0]['selections'])
                raise ValueError('roll back')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        self.assertEqual(self.rt.task('edit','produce')['status'],'awaiting_user')


if __name__ == '__main__':
    unittest.main()
