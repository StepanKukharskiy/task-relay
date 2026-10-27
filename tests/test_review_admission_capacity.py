"""Unstarted evidence reviewers recover within their saved scope, without replay."""
import copy,json,unittest
from unittest.mock import patch
from orchestrator import evidence_context,execution,executors
from task_relay import input_preflight_recovery as recovery,review_budget_recovery as budgets
from tests.test_evidence_context import PipelineTests
from tests import test_pipelines

class Tests(PipelineTests):
    # Exercise the shared pipeline fixture without inheriting its unrelated test.
    test_both_stage_binding_forms_resume_only_unchanged_authorized_graph=None
    test_admission_uses_original_session_attempts_and_controller_resumes_after_restart=None

    def stopped(self,ceiling=24,explicit=None):
        # Small fixture; cap actual transport capacity, not just preferred page
        # size, so adaptive reads cannot fit the existing 12 requests.
        self.batch=patch.object(evidence_context,'BATCH_BYTES',4608);self.batch.start();self.addCleanup(self.batch.stop)
        envelope=patch.object(evidence_context,'ENVELOPE_BYTES',executors.MAX_INPUT_BYTES-4608)
        envelope.start();self.addCleanup(envelope.stop)
        raw,aid=self.prepared()
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        value=json.loads(self.state.db.execute("SELECT plan FROM production_runs WHERE id='demo'").fetchone()[0])
        scope=dict(connector_companions_version=1,planner_budget_binding_version=2,delivery_completion_policy_version=1,
                   graph_operations=[dict(id='web.sources.rendered',saved_evidence=dict(kind='pages'),output_bytes=3000000)])
        options=dict(limits=dict(tool_calls=ceiling,provider_requests=ceiling,seconds=1800))
        if explicit is not None:
            t=self.rt.task('demo','review');spec=self.rt.spec(t);spec['limits']['provider_requests']=explicit
            self.state.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),t['assignment']))
            value['tasks'][1]=spec
            self.state.db.execute("UPDATE production_runs SET plan=? WHERE id='demo'",(json.dumps(value),))
        p=self.create([self.stage(route='production',caps=['web.sources.rendered']),self.stage('finish')])
        from task_relay import completion_recovery
        c=self.state.db
        c.execute("INSERT INTO production_plans(id,request_id,channel,request,options,context,context_hash,provider,model,status,plan,run,token,expires,created) VALUES ('saved',2,?,'Exact request',?,?,'fixture','fixture','fixture','started',?,'demo','fixture',9999999999,1)",(p['channel'],json.dumps(options),json.dumps(scope),json.dumps(value)))
        c.execute('INSERT INTO completion_recovery_grants VALUES (?,?,?)',(p['id'],'Original complete-delivery grant',json.dumps(completion_recovery.DELIVERY_POLICY)))
        c.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
        c.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='plan_production',target='saved',error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='outline'",(p['id'],))
        c.commit();return p,aid

    def test_reconcile_restart_dispatches_first_review_once_and_preserves_history(self):
        p,aid=self.stopped();c=self.state.db
        before=[tuple(r) for r in c.execute('SELECT * FROM production_attempts')]
        from task_relay import production_control
        digest=production_control.runtime_digest(self.rt,'demo')
        original=dict(self.rt.task('demo','review'));calls=list(self.factory.calls)
        recovery.reconcile(self.state);recovery.reconcile(self.state)
        self.assertEqual(self.step(p,'outline')['status'],'running')
        task=self.rt.task('demo','review');self.assertEqual(task['attempts'],0)
        self.assertNotEqual(task['assignment'],original['assignment']);self.assertEqual(calls,self.factory.calls)
        self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM production_attempts')])
        self.assertEqual(production_control.runtime_digest(self.rt,'demo'),digest)
        from orchestrator.runtime import Runtime
        rt=Runtime(self.rt.root,connection=c,factory=self.factory)
        rt.tick('demo');self.assertEqual(rt.task('demo','review')['attempts'],1)
        self.assertEqual(rt.task('demo','produce')['latest'],aid);self.assertEqual(len(self.factory.calls),2)
        rt.tick('demo');self.assertEqual(len(self.factory.calls),2)
        self.factory.finish(rt.task('demo','review')['latest'],decision='accept');rt.tick('demo')
        self.assertEqual(rt.status('demo')['status'],'completed')

    def test_small_explicit_ceiling_keeps_hold_without_spending_attempt(self):
        p,aid=self.stopped(ceiling=5);recovery.reconcile(self.state)
        self.assertEqual(self.step(p,'outline')['status'],'blocked');self.assertEqual(len(self.factory.calls),1)

    def test_explicit_worker_requests_are_preserved(self):
        p,aid=self.stopped(explicit=5);recovery.reconcile(self.state)
        self.assertEqual(self.step(p,'outline')['status'],'blocked');self.assertEqual(len(self.factory.calls),1)

    def test_changed_authority_after_commit_blocks_dispatch(self):
        p,aid=self.stopped();recovery.reconcile(self.state)
        self.assertEqual(self.rt.task('demo','review')['status'],'queued')
        with self.state.db:self.state.db.execute("UPDATE production_plans SET options='{}' WHERE id='saved'")
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        self.assertEqual(len(self.factory.calls),1)

    def test_rollback_and_changed_candidate_preserve_hold(self):
        p,aid=self.stopped();planner=self.state.db.execute("SELECT * FROM production_plans WHERE id='saved'").fetchone()
        before=self.rt.task('demo','review')['assignment']
        with self.assertRaisesRegex(ValueError,'rollback'):
            with self.rt.transaction():
                self.assertEqual(len(recovery.requeue(self.rt,'demo',planner)),1);raise ValueError('rollback')
        self.assertEqual(self.rt.task('demo','review')['assignment'],before)
        from pathlib import Path
        artifact=self.rt.output('demo','produce','delivery/source-pack.json');blob=Path(artifact['blob']);blob.chmod(0o600);blob.write_text('changed')
        recovery.reconcile(self.state);self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        self.assertEqual(len(self.factory.calls),1)

    def test_missing_provider_budget_reserves_both_dimensions_for_all_file_workers(self):
        for backend in executors.FILE_TYPES:
            with self.subTest(backend=backend):
                from tests.test_gemini_executor import graph
                value=graph();value['backend']={'type':backend,'model':'fixture'}
                value['tasks'][0]['execution']={'capability':'fixture.pages','parameters':{}}
                review=value['tasks'][1];review.pop('backend',None);review.pop('worker',None)
                review['limits']=dict(tool_calls=5,seconds=300,output_bytes=10000)
                scope=dict(connector_companions_version=1,planner_budget_binding_version=2,delivery_completion_policy_version=1,graph_operations=[dict(id='fixture.pages',saved_evidence=dict(kind='pages'))])
                budgets.budgets(value,scope,dict(limits=dict(tool_calls=24,seconds=600)))
                self.assertEqual(review['limits']['tool_calls'],24);self.assertEqual(review['limits']['provider_requests'],24)
