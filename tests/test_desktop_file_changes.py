"""Small file/version fixtures; inspection cannot import, select or dispatch."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from task_relay.bridge import State
from task_relay.relay_paths import Paths
from task_relay import desktop_file_changes as changes, desktop_plans, desktop_workspace, production_control as pc, relay_channels
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory, pair, plan, task


class Tests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.paths=Paths(self.root/'app',self.root/'data',self.root/'workspaces',self.root/'generated')
        self.state=State(self.paths.state);self.addCleanup(self.state.db.close)
        self.factory=FakeFactory()
        self.rt=Runtime(pc.root(self.state),factory=self.factory,connection=self.state.db)
        self.original=self.root/'original.txt';self.original.write_text('Original sentence.\n')
        self.request=str(uuid.uuid4())
        with self.state.db:self.state.put('health:desktop-plans',{'interface_version':1,'last_success':time.time()})
        desktop_plans.create('Inspect the exact original.','',None,None,self.request,self.paths,files=[str(self.original)])
        row=self.state.db.execute('SELECT * FROM desktop_plan_requests').fetchone()
        self.job=row['job_id']
        self.capture=json.loads(self.state.db.execute('SELECT manifest FROM desktop_plan_inputs').fetchone()[0])[0]
        self.source=self.rt.register(self.capture['path'],'Selected attachment',run='plan-fixture')
        value=pair(gate='Choose exact text',max_attempts=2)
        value['tasks'][0]['inputs']=[dict(artifact=self.source,path='source.txt',purpose='Original source',authority='Source context')]
        value['origin']={'job_request_id':self.job}
        self.rt.create(value)
        with self.state.db:
            relay_channels.bind(self.state,'production','demo','desktop')
            self.state.put('production-enabled:demo',pc.runtime_digest(self.rt,'demo'))
            self.state.db.execute('''INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,token,expires,run,created)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',('plan-fixture',self.job,'desktop',row['prompt'],
                json.dumps({'job_request_id':self.job}),json.dumps({'sources':[{'artifact':self.source}]}),
                'fixture','fixture','fixture','started','fixture-token',0,'demo',time.time()))

    def finish(self):
        for _ in range(15):
            self.rt.tick('demo')
            running=self.state.db.execute("SELECT id,task FROM production_attempts WHERE run='demo' AND state='running'").fetchall()
            for row in running:self.factory.finish(row['id'],decision='accept' if row['task']=='review' else 'delivered')
            if self.rt.task('demo','produce')['status']=='awaiting_user' and self.rt.task('demo','review')['status']=='completed':return
        self.fail('Fixture did not reach its pending user gate')

    def test_external_edit_diff_and_transitive_marks_preserve_frozen_input_and_pending_decision(self):
        self.finish();calls=list(self.factory.calls)
        before=self.state.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0]
        self.original.write_text('Updated sentence.\n')
        result=changes.check_sources('demo',self.paths)
        self.assertEqual(result['originals'][0]['status'],'changed')
        change=result['changes'][0]
        self.assertEqual({t['task'] for t in change['tasks']},{'produce','review'})
        comparison=changes.compare('demo',change['id'],change['new']['sha256'],self.paths)
        self.assertIn('-Original sentence.',comparison['diff']);self.assertIn('+Updated sentence.',comparison['diff'])
        self.assertEqual(Path(self.capture['path']).read_text(),'Original sentence.\n')
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')

    def test_unchanged_content_and_deleted_or_symlinked_original_are_not_claimed_updated(self):
        self.original.touch()
        result=changes.check_sources('demo',self.paths)
        self.assertEqual(result['originals'][0]['status'],'unchanged');self.assertEqual(result['changes'],[])
        self.original.unlink()
        self.assertEqual(changes.check_sources('demo',self.paths)['originals'][0]['status'],'unavailable')
        other=self.root/'other.txt';other.write_text('Other bytes')
        self.original.symlink_to(other)
        self.assertEqual(changes.check_sources('demo',self.paths)['originals'][0]['status'],'unavailable')

    def test_comparison_rejects_a_newer_external_edit_or_an_unrelated_change_identity(self):
        self.original.write_text('Second version.\n')
        change=changes.check_sources('demo',self.paths)['changes'][0]
        self.original.write_text('Third version.\n')
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'version changed'):
            changes.compare('demo',change['id'],change['new']['sha256'],self.paths)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'outside'):
            changes.compare('demo','f'*64,hashlib.sha256(b'Third version.\n').hexdigest(),self.paths)

    def test_registered_revision_pair_has_a_barrier_at_the_new_candidate(self):
        self.finish();old=self.rt.output('demo','produce','output.txt')['id']
        self.rt.revise('demo','produce','Revise the exact previous candidate.')
        self.finish();new=self.rt.output('demo','produce','output.txt')['id']
        before=list(self.factory.calls)
        view=desktop_workspace.detail('demo',self.paths)
        revision=next(c for c in view['file_changes']['items'] if c['kind']=='revision')
        self.assertEqual((revision['old']['id'],revision['new']['id']),(old,new))
        self.assertEqual(revision['tasks'],[])
        self.assertTrue(changes.compare('demo',revision['id'],paths=self.paths)['diff'])
        self.assertEqual(self.factory.calls,before)

    def test_matching_filename_and_bytes_do_not_establish_a_revision(self):
        self.finish()
        clone=self.root/'clone.txt';clone.write_text('Same named file')
        self.rt.register(clone,'Unrelated candidate',run='demo',task='produce',path='output.txt')
        self.assertEqual(desktop_workspace.detail('demo',self.paths)['file_changes']['items'],[])

    def test_explicit_replacement_preserves_exact_pair_and_existing_decisions(self):
        self.finish()
        old=self.rt.output('demo','produce','output.txt')['id']
        self.rt.select('demo','produce',old,'Choose exact text','Select the first fixture.')
        old_decision=self.state.db.execute("SELECT id FROM production_decisions WHERE run='demo'").fetchone()[0]
        candidate=plan([task(user_gate='Choose exact text')])
        candidate.update(id='replacement',origin={'job_request_id':self.job})
        self.rt.create(candidate);self.rt.tick('replacement')
        self.factory.finish(self.rt.task('replacement','produce')['latest']);self.rt.tick('replacement')
        new=self.rt.output('replacement','produce','output.txt')['id']
        self.rt.select('replacement','produce',new,'Choose exact text','Select the replacement fixture.')
        new_decision=self.state.db.execute("SELECT id FROM production_decisions WHERE run='replacement'").fetchone()[0]
        self.rt.replace_selection(old_decision,new_decision,0,'fixture-replacement','Use the exact replacement.')
        calls=list(self.factory.calls)
        replacement=next(c for c in changes.recorded(self.state,'demo') if c['kind']=='replacement')
        self.assertEqual((replacement['old']['id'],replacement['new']['id']),(old,new))
        comparison=changes.compare('demo',replacement['id'],paths=self.paths)
        self.assertEqual((comparison['old']['id'],comparison['new']['id']),(old,new))
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],2)

    def test_binary_comparison_reports_versions_without_claiming_a_text_diff(self):
        self.original.write_bytes(b'\x00updated binary')
        change=changes.check_sources('demo',self.paths)['changes'][0]
        comparison=changes.compare('demo',change['id'],change['new']['sha256'],self.paths)
        self.assertFalse(comparison['same_content']);self.assertIsNone(comparison['diff'])
        self.assertIn('unavailable',comparison['preview_note'])

    def test_atomic_save_during_inspection_cannot_report_the_replaced_path_as_stable(self):
        replacement=self.root/'replacement.txt';replacement.write_text('Replacement bytes')
        real_read=os.read;replaced=False
        def swap(fd,count):
            nonlocal replaced
            raw=real_read(fd,count)
            if not replaced:
                replaced=True;replacement.replace(self.original)
            return raw
        with patch('task_relay.desktop_file_changes.os.read',side_effect=swap):
            with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed during'):
                changes.read_version(self.original)

    def test_oversized_original_is_unavailable_and_frozen_copy_tamper_stops_comparison(self):
        self.original.write_text('Second version.\n')
        with patch.object(changes,'MAX_BYTES',5):
            self.assertEqual(changes.check_sources('demo',self.paths)['originals'][0]['status'],'unavailable')
        change=changes.check_sources('demo',self.paths)['changes'][0]
        snapshot=Path(self.capture['path']);snapshot.chmod(0o600);snapshot.write_text('Tampered snapshot')
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'version changed'):
            changes.compare('demo',change['id'],change['new']['sha256'],self.paths)


if __name__=='__main__':unittest.main()
