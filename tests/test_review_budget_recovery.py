"""Small saved-page fixtures; no browser, provider or host operation dispatch."""
import copy,json,unittest
from unittest.mock import patch
from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery,review_budget_recovery as review
from task_relay.relay_channels import ScopedState
from tests import test_completion_recovery as fixtures
from tests import test_production_planning as planning
from tests.test_orchestrator import pair

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    stage=fixtures.Tests.stage
    create=fixtures.Tests.create
    step=fixtures.Tests.step
    action=fixtures.Tests.action
    row=fixtures.Tests.row
    prepare=fixtures.Tests.prepare

    def stopped(self):
        p,s=self.prepare();graph=pair(max_attempts=1);graph['id']='parent'
        graph['tasks'][1]['limits']=dict(seconds=300,tool_calls=6,output_bytes=100000)
        self.rt.create(graph);self.rt.tick('parent');source=self.rt.task('parent','produce')['latest']
        self.factory.finish(source);self.rt.tick('parent');aid=self.rt.task('parent','review')['latest']
        native=self.state.db.execute('SELECT frozen,receipt FROM production_attempts WHERE id=?',(source,)).fetchone()
        f=json.loads(native['frozen']);f['execution']=dict(capability='web.sources.prepared')
        artifact=self.state.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(source,)).fetchone()
        done=json.loads(native['receipt']);done['operation']=dict(output_sha256=artifact['sha256'])
        self.state.db.execute('UPDATE production_attempts SET frozen=?,receipt=? WHERE id=?',(json.dumps(f),json.dumps(done),source));self.state.db.commit()
        self.factory.sessions[aid]['workspace'].joinpath('review.md').write_text('Unaccepted retained local draft')
        self.factory.sessions[aid]['status']=dict(status='finished',token=aid,exit_code=-15,reason='tool_limit',tool_calls=7,usage=[])
        self.rt.tick('parent')
        self.state.db.execute('UPDATE completion_recovery_grants SET policy=? WHERE pipeline=?',(recovery.encoded(recovery.DELIVERY_POLICY),p['id']));self.state.db.commit()
        return p,s,source,aid

    def test_continues_exact_review_after_commit_without_research_or_acceptance(self):
        p,s,source,aid=self.stopped();before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone());calls=list(self.factory.calls)
        chats=self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(calls,self.factory.calls);self.assertEqual(self.rt.task('parent','review')['attempts'],1)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()),before)
        self.assertEqual(self.rt.task('parent','produce')['status'],'awaiting_review')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],chats)
        self.rt.tick('parent');new=self.rt.task('parent','review')['latest'];self.assertNotEqual(aid,new)
        frozen=self.factory.sessions[new]['frozen'];self.assertEqual(frozen['review_target'],source)
        self.assertEqual(frozen['limits']['tool_calls'],24);self.assertEqual(frozen['limits']['seconds'],600)
        self.assertEqual(self.rt.task('parent','produce')['attempts'],1);self.assertEqual(self.rt.task('parent','review')['attempts'],2)
        drafts=[i for i in frozen['inputs'] if i.get('previous_delivery')];self.assertEqual(len(drafts),1)
        self.assertEqual((self.factory.sessions[new]['workspace']/drafts[0]['path']).read_text(),'Unaccepted retained local draft')
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        self.factory.finish(new,decision='accept');self.rt.tick('parent');self.assertEqual(self.rt.status('parent')['status'],'completed')

    def test_unknown_stale_non_native_or_pending_receipts_cannot_continue(self):
        p,s,source,aid=self.stopped();row=self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone();f=json.loads(row['frozen']);done=json.loads(row['receipt'])
        for alteration in [dict(reason='cancelled'),dict(exit_code=-1),dict(pending_requests=['uncertain']),dict(tool_calls=6),dict(token='other'),dict(cleanup_error='not stopped')]:
            with self.subTest(alteration=alteration),transaction(self.state.db):
                self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps({**done,**alteration}),aid))
                self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(done),aid))
        for alteration in [dict(review_target='stale'),dict(browser={'profile':'managed'}),dict(execution={'capability':'pptx.create'}),dict(computer={'host':'mac'})]:
            with self.subTest(alteration=alteration),transaction(self.state.db):
                self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps({**f,**alteration}),aid))
                self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(f),aid))
        native=json.loads(self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(source,)).fetchone()[0]);native['execution']['capability']='pptx.create'
        with transaction(self.state.db):
            self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(native),source))
            self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.rt.task('parent','review')['attempts'],1)

    def test_reopens_first_known_budget_stop_and_remains_idempotent(self):
        p,s,source,aid=self.stopped();parent=planning.Tests.queue(self,99)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='plan_production',target=?,error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='outline'",(parent['id'],p['id']))
        before=list(self.factory.calls);recovery.reconcile_changed_failures(self.state);recovery.reconcile_changed_failures(self.state)
        self.assertEqual(before,self.factory.calls);self.assertEqual(self.step(p,'outline')['status'],'running')
        self.assertEqual(self.rt.task('parent','review')['status'],'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)

    def test_rollback_exhausted_cycle_and_changed_scope_do_not_dispatch(self):
        p,s,source,aid=self.stopped();calls=list(self.factory.calls)
        with self.assertRaisesRegex(ValueError,'rollback'):
            with transaction(self.state.db):
                self.assertTrue(recovery.begin(self.state,p,s,'parent'));raise ValueError('rollback')
        self.assertEqual(self.rt.task('parent','review')['status'],'blocked');self.assertEqual(calls,self.factory.calls)
        with transaction(self.state.db):
            for cycle in range(4):self.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',(p['id'],s['id'],'prior-'+str(cycle),cycle+1,100+cycle,'{}'))
            self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        with transaction(self.state.db):self.state.db.execute('DELETE FROM completion_recoveries')
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        task=self.rt.task('parent','review');spec=self.rt.spec(task);spec['criteria'].append('Changed authorization')
        with transaction(self.state.db):
            assignment=self.rt.new_assignment('parent',spec)
            self.state.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?',(assignment,'parent','review'))
        self.rt.tick('parent');self.assertEqual(self.rt.task('parent','review')['status'],'blocked');self.assertEqual(calls,self.factory.calls)

    def test_planner_reserves_finalization_within_frozen_allowance_only(self):
        plan=pair(max_attempts=1);plan['tasks'][0]['execution']={'capability':'fixture.read'}
        plan['tasks'][1]['limits']=dict(tool_calls=6,seconds=300,output_bytes=100000)
        scope=dict(connector_companions_version=1,planner_budget_binding_version=2,graph_operations=[dict(id='fixture.read',saved_evidence=dict(kind='pages'))])
        options=dict(limits=dict(tool_calls=15,seconds=450))
        self.assertEqual(len(review.budgets(plan,scope,options)),2)
        self.assertEqual(plan['tasks'][1]['limits']['tool_calls'],15);self.assertEqual(plan['tasks'][1]['limits']['seconds'],450)
        self.assertEqual(review.budgets(plan,scope,options),[])
        self.assertEqual(review.budgets(plan,{},options),[])

    def test_committed_receipt_change_blocks_dispatch(self):
        p,s,source,aid=self.stopped();calls=list(self.factory.calls)
        with transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
            done=json.loads(self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(aid,)).fetchone()[0]);done['tool_calls']=8
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(done),aid))
        self.rt.tick('parent');self.assertEqual(calls,self.factory.calls);self.assertEqual(self.rt.task('parent','review')['status'],'blocked')

    def test_changed_owner_control_does_not_reopen_blocked_workflow(self):
        p,s,source,aid=self.stopped()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='outline'",(p['id'],))
            ScopedState(self.state,p['channel']).put('production-control-epoch:parent',1)
        recovery.reconcile_changed_failures(self.state)
        self.assertEqual(self.step(p,'outline')['status'],'blocked');self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)
