"""Small controlled runtime/queue failures; no network or generated media."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from task_relay import runtime_snapshot as snapshots,native_code_host,code_runtime,runtime_process
from orchestrator import review_recovery,contracts as c
from orchestrator.runtime import Runtime
from tests import test_job_owner_loop as fixture

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.source=self.root/'source';self.source.mkdir();(self.source/'python').write_text('binary fixture');(self.source/'module.py').write_text('old library')
    def test_upstream_replacement_and_restart_keep_exact_private_files(self):
        receipt=snapshots.capture(self.source,self.root/'pin')
        (self.source/'module.py').write_text('new library');(self.source/'python').write_text('new binary')
        root=snapshots.verify(json.loads(json.dumps(receipt)))
        self.assertEqual((root/'module.py').read_text(),'old library')
        self.assertNotEqual((root/'python').stat().st_ino,(self.source/'python').stat().st_ino)
        self.assertEqual(snapshots.capture(self.source,self.root/'pin'),receipt)
    def test_modified_or_added_snapshot_file_and_manifest_are_refused(self):
        receipt=snapshots.capture(self.source,self.root/'pin');root=Path(receipt['root'])
        p=root/'module.py';p.chmod(0o600);p.write_text('tamper')
        with self.assertRaisesRegex(ValueError,'files changed'):snapshots.verify(receipt)
        p.write_text('old library');(root/'added.py').write_text('extra')
        with self.assertRaisesRegex(ValueError,'files changed'):snapshots.verify(receipt)
        (root/'added.py').unlink();(root.parent/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest changed'):snapshots.verify(receipt)
    def test_absolute_internal_links_relocate_external_links_refuse(self):
        (self.source/'alias').symlink_to(self.source/'python')
        r=snapshots.capture(self.source,self.root/'pin');self.assertEqual((Path(r['root'])/'alias').read_text(),'binary fixture')
        (self.source/'outside').symlink_to('/etc/hosts')
        with self.assertRaisesRegex(ValueError,'escapes'):snapshots.capture(self.source,self.root/'bad')
        self.assertFalse((self.root/'bad').exists())
    def test_missing_external_packaging_link_is_inert_and_later_appearance_refuses(self):
        target=self.root/'absent';(self.source/'packaging-link').symlink_to(target)
        receipt=snapshots.capture(self.source,self.root/'pin');snapshots.verify(receipt)
        target.write_text('external data now exists')
        with self.assertRaisesRegex(ValueError,'escapes'):snapshots.verify(receipt)
    def test_source_change_during_copy_is_never_admitted(self):
        original=snapshots.shutil.copytree
        def change(*args,**kwargs):
            result=original(*args,**kwargs);(self.source/'module.py').write_text('changed during copy');return result
        with patch.object(snapshots.shutil,'copytree',side_effect=change):
            with self.assertRaisesRegex(ValueError,'changed during'):snapshots.capture(self.source,self.root/'pin')
        self.assertFalse((self.root/'pin').exists())
    def test_pinned_receipt_survives_ambient_identity_change_but_not_tamper(self):
        receipt=snapshots.capture(self.source,self.root/'pin');root=Path(receipt['root'])
        runtime=dict(adapter='macos-seatbelt-v1',adapter_sha256=snapshots.sha(native_code_host.__file__),process_policy_sha256=snapshots.sha(runtime_process.__file__),python=str(root/'python'),python_sha256=snapshots.sha(root/'python'),read_roots=[str(root)],snapshot=receipt)
        settings=self.root/'code.json';settings.write_text(json.dumps(dict(version=1,id=c.digest(runtime),runtime=runtime,enabled=True,tools={})))
        with patch.object(code_runtime,'path',return_value=settings),patch.object(native_code_host,'identity',side_effect=AssertionError('mutable runtime must not be consulted')):
            self.assertEqual(code_runtime.available(c.digest(runtime))['runtime'],runtime)
            with self.assertRaisesRegex(ValueError,'runtime changed'):code_runtime.available('another-id')
            p=root/'python';p.chmod(0o600);p.write_text('changed')
            with self.assertRaisesRegex(ValueError,'files changed'):code_runtime.available(c.digest(runtime))

class ReviewTests(unittest.TestCase):
    from tests.test_browser_fallback_lifecycle import retain_evidence as tearDown
    setUp=fixture.Tests.setUp
    create=fixture.Tests.create
    invoke=fixture.Tests.invoke
    delegate=fixture.Tests.delegate
    batch=fixture.Tests.batch
    def blocked(self):
        self.create();self.rt.tick('job');self.delegate(self.batch());self.rt.tick('job')
        self.factory.finish(self.rt.task('job','v1')['latest'])
        self.factory.available=lambda backend:(_ for _ in ()).throw(ValueError('temporary exact runtime unavailable'))
        self.rt.tick('job')
        task=dict(self.rt.task('job','v1_review'));self.assertEqual(task['status'],'blocked');self.assertEqual(task['attempts'],0)
        self.factory.available=lambda backend:None
        return task
    def test_restart_reuses_gate_candidate_and_allowances_without_duplicate_dispatch(self):
        before=self.blocked();candidate=self.rt.task('job','v1')['latest'];spec=self.rt.spec(before);calls=list(self.factory.calls)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.rt.tick('job');review=self.rt.task('job','v1_review')
        self.assertEqual(review['assignment'],before['assignment']);self.assertEqual(self.rt.spec(review),spec)
        self.assertEqual(review['attempts'],1);self.assertEqual(self.rt.task('job','v1')['latest'],candidate)
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(self.factory.calls.count(review['latest']),1)
        self.factory.finish(review['latest'],decision='accept');self.rt.tick('job')
        self.assertEqual(self.rt.task('job','v1')['status'],'completed')
        self.assertTrue(set(calls)<=set(self.factory.calls))
    def test_atomic_rollback_and_disabled_dispatch_do_not_requeue(self):
        self.blocked()
        with self.assertRaisesRegex(ValueError,'rollback'):
            with self.rt.transaction():review_recovery.requeue(self.rt,'job');raise ValueError('rollback')
        self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
        self.rt.tick('job',dispatch=False);self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
    def test_changed_candidate_bytes_or_assignment_cannot_recover(self):
        before=self.blocked();artifact=self.rt.output('job','v1','report.txt');p=Path(artifact['blob']);p.chmod(0o600);p.write_text('tampered')
        review_recovery.requeue(self.rt,'job');self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
    def test_changed_assignment_and_started_semantic_review_are_not_requeued(self):
        before=self.blocked();spec=self.rt.spec(before);changed=copy.deepcopy(spec);changed['instruction']+=' changed'
        with self.rt.transaction():self.rt.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(c.encoded(changed),before['assignment']))
        review_recovery.requeue(self.rt,'job');self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
        with self.rt.transaction():self.rt.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(c.encoded(spec),before['assignment']))
        self.rt.tick('job');aid=self.rt.task('job','v1_review')['latest']
        self.factory.finish(aid,decision='blocked');self.rt.tick('job');calls=list(self.factory.calls)
        review_recovery.requeue(self.rt,'job');self.assertEqual(calls,self.factory.calls)
        self.assertEqual(self.rt.task('job','v1_review')['latest'],aid)
    def test_unknown_effect_or_terminal_owner_forbids_recovery(self):
        self.blocked();owner=self.rt.task('job','owner')
        with self.rt.transaction():self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(owner['latest'],))
        review_recovery.requeue(self.rt,'job');self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
        with self.rt.transaction():
            self.rt.db.execute("UPDATE production_attempts SET state='completed' WHERE id=?",(owner['latest'],))
            self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='job' AND id='owner'")
        review_recovery.requeue(self.rt,'job');self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
    def test_original_no_proof_failures_and_used_review_slots_stay_blocked(self):
        self.blocked()
        with self.rt.transaction():self.rt.db.execute("UPDATE production_events SET data=? WHERE kind='capability_unavailable'",(json.dumps(dict(reason='historical bare error')),))
        review_recovery.requeue(self.rt,'job');self.assertEqual(self.rt.task('job','v1_review')['status'],'blocked')
    def test_readmission_is_bounded_and_preserves_original_failure_events(self):
        before=self.blocked();spec=self.rt.spec(before)
        for index in range(spec['max_attempts']+1):
            review_recovery.requeue(self.rt,'job')
            task=self.rt.task('job','v1_review')
            self.assertEqual(task['status'],'queued' if index<spec['max_attempts'] else 'blocked')
            if index==spec['max_attempts']:break
            proof=json.loads(self.rt.db.execute("SELECT data FROM production_events WHERE kind='capability_unavailable' ORDER BY id DESC").fetchone()[0])
            with self.rt.transaction():
                self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='job' AND id='v1_review'")
                self.rt.event('job','v1_review',None,'capability_unavailable',proof)
        self.assertEqual(self.rt.task('job','v1_review')['attempts'],0)

if __name__=='__main__':unittest.main()
