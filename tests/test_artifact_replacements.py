import copy
import json
from pathlib import Path
import tempfile
import unittest
from orchestrator.runtime import Runtime
from orchestrator import artifact_replacements as ar
from tests.test_orchestrator import FakeFactory,plan,task

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.factory=FakeFactory();self.rt=Runtime(self.root/'runtime',self.factory)
    def tearDown(self):self.rt.close();self.tmp.cleanup()
    def make(self,run,inputs=(),selected=True,job='job-one',finish=True,purpose='Choose model'):
        value=plan([task(inputs=[dict(artifact=a,path=str(i)+'.txt',purpose='Exact source',authority='Declared context') for i,a in enumerate(inputs)],user_gate=purpose)])
        value.update(id=run,origin={'job_request_id':job});self.rt.create(value);self.rt.tick(run)
        if not finish:return None,None
        self.factory.finish(self.rt.task(run,'produce')['latest']);self.rt.tick(run)
        a=self.rt.output(run,'produce','output.txt')['id']
        if not selected:return a,None
        self.rt.select(run,'produce',a,purpose,'Exact user choice')
        d=self.rt.db.execute('SELECT id FROM production_decisions WHERE run=?',(run,)).fetchone()[0]
        return a,d
    def outdated(self,run='old'):
        return {r['artifact'] for r in ar.view(self.rt.db,run)['outdated_outputs']}
    def test_branching_scope_barrier_and_reversal_preserve_history(self):
        old,a=self.make('old');new,b=self.make('new',[old]);render,_=self.make('render',[old]);slides,_=self.make('slides',[render]);fresh,_=self.make('fresh',[new]);other,_=self.make('other',[old],job='other')
        calls=list(self.factory.calls)
        preview=ar.preview(self.rt,a,b);self.assertEqual(preview['affected_count'],3)
        self.assertEqual(self.outdated(),set())
        self.rt.replace_selection(a,b,0,'first','Use new model')
        self.assertEqual(self.outdated(),{old,render,slides});self.assertNotIn(new,self.outdated());self.assertNotIn(fresh,self.outdated());self.assertNotIn(other,self.outdated())
        self.assertEqual(self.factory.calls,calls)
        self.rt.replace_selection(b,a,1,'reverse','Return to original model')
        self.assertEqual(self.outdated(),{new,fresh})
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],6)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],2)
    def test_late_results_and_restart_receive_validity_without_new_dispatch(self):
        old,a=self.make('old');new,b=self.make('new',[old]);self.make('late',[old],finish=False)
        attempt=self.rt.task('late','produce')['latest'];calls=list(self.factory.calls)
        self.rt.replace_selection(a,b,0,'replace','Use new model')
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory)
        self.factory.finish(attempt);self.rt.tick('late')
        late=self.rt.output('late','produce','output.txt')['id']
        self.assertIn(late,self.outdated());self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.task('late','produce')['status'],'awaiting_user')
        count=self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='artifact_validity_changed'").fetchone()[0]
        with self.rt.transaction():ar.refresh(self.rt,ar.scope(self.rt.db,'late'))
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='artifact_validity_changed'").fetchone()[0],count)
    def test_duplicate_receipt_stale_revision_and_rollback(self):
        old,a=self.make('old');new,b=self.make('new',[old])
        with self.assertRaisesRegex(ValueError,'abort'):
            with self.rt.transaction():
                self.rt.replace_selection(a,b,0,'rollback','Use new');raise ValueError('abort')
        self.assertEqual(self.outdated(),set());self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_replacement_heads').fetchone()[0],0)
        self.rt.replace_selection(a,b,0,'once','Use new');self.rt.replace_selection(a,b,0,'once','Use new')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],1)
        with self.assertRaises(ValueError):self.rt.replace_selection(b,a,1,'once','Different identity')
        self.rt.replace_selection(b,a,1,'back','Reverse')
        with self.assertRaisesRegex(ValueError,'state changed'):self.rt.replace_selection(a,b,0,'stale','Use new')
    def test_unselected_cross_job_and_different_purpose_are_rejected(self):
        old,a=self.make('old');candidate,_=self.make('draft',selected=False);_,b=self.make('other',job='different');_,c=self.make('purpose',purpose='Choose texture')
        for target in (candidate,b,c):
            with self.assertRaises(ValueError):ar.preview(self.rt,a,target)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)
    def test_content_tamper_stops_without_partial_replacement(self):
        old,a=self.make('old');new,b=self.make('new',[old]);path=Path(self.rt.artifact(new)['blob']);path.chmod(0o600);path.write_text('changed')
        with self.assertRaisesRegex(ValueError,'content changed'):self.rt.replace_selection(a,b,0,'replace','Use new')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_replacement_heads').fetchone()[0],0)
    def test_multiple_histories_cannot_absorb_each_others_decisions(self):
        _,a=self.make('a');_,b=self.make('b');_,c=self.make('c');_,d=self.make('d')
        self.rt.replace_selection(a,b,0,'ab','Use b');self.rt.replace_selection(c,d,0,'cd','Use d')
        with self.assertRaisesRegex(ValueError,'another replacement history'):self.rt.replace_selection(b,d,1,'bd','Use d')

    def test_dependency_leaving_and_returning_to_job_keeps_scope(self):
        old,a=self.make('old');new,b=self.make('new')
        external,_=self.make('external',[old],job='other')
        returned,_=self.make('returned',[external])
        self.rt.replace_selection(a,b,0,'replace','Use new')
        self.assertEqual(self.outdated(),{old,returned})
        self.assertEqual(ar.view(self.rt.db,'external')['outdated_outputs'],[])

if __name__=='__main__':unittest.main()
