import copy
import json
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery, pipelines
from task_relay.relay_channels import ScopedState
from tests import test_pipelines as fixtures
from tests import test_production_planning as planning_fixtures


class Tests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    request = fixtures.Tests.request
    stage = fixtures.Tests.stage
    create = fixtures.Tests.create
    step = fixtures.Tests.step
    action = planning_fixtures.Tests.action
    row = planning_fixtures.Tests.row

    def prepare(self):
        p = self.create([self.stage(route='production'), self.stage('finish')])
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='production_run',target='parent' WHERE pipeline=? AND id='outline'", (p['id'],))
            recovery.authorize(ScopedState(self.state, p['channel']), p['id'], 'lets try')
        s = self.step(p, 'outline')
        return p, s

    def baseline(self):
        return dict(run='parent', artifacts=[], tasks=[], attempts=[],
                    gaps=[dict(kind='review_gaps', task='review', findings=[dict(code='missing_product_page')])],
                    plan=dict(tasks=[dict(backend={'type':'codex-cli'})], deliverables={'outline': {'task': 'write', 'output': 'delivery/outline.txt'}}))

    def test_confirmed_tool_budget_failure_can_split_without_replaying_or_resetting(self):
        from tests.test_orchestrator import pair
        p,s=self.prepare()
        plan=pair(max_attempts=1);plan['id']='parent'
        self.rt.create(plan);self.rt.tick('parent')
        attempt=self.rt.task('parent','produce')['latest']
        receipt=dict(status='finished',exit_code=1,reason='ValueError: Tool budget exhausted before execution.',pending_requests=[],external_outcome='no_pending_response')
        self.factory.sessions[attempt]['status']=receipt
        self.rt.tick('parent')
        baseline=recovery.snapshot(self.state,'parent')
        self.assertEqual(baseline['gaps'][0]['kind'],'split_budget')
        before=list(self.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.factory.calls,before)
        self.assertEqual(self.rt.task('parent','produce')['latest'],attempt)
        self.assertEqual(self.rt.task('parent','produce')['attempts'],1)
        with transaction(self.state.db):
            changed=dict(receipt,pending_requests=['unresolved-provider-call'])
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(changed),attempt))
        self.assertIsNone(recovery.snapshot(self.state,'parent'))

    def test_committed_recovery_survives_restart_without_duplicate_or_attempt_reset(self):
        p, s = self.prepare()
        with patch.object(recovery, 'snapshot', return_value=self.baseline()):
            with transaction(self.state.db):
                self.assertTrue(recovery.begin(self.state, p, s, 'parent'))
            queued = self.step(p, 'outline')
            self.assertEqual(queued['status'], 'queued')
            self.assertIsNone(queued['target'])
            context = pipelines.request_context(self.state, queued['request_id'])
            self.assertEqual(context['inputs']['completion_recovery']['baseline'], self.baseline())
            with transaction(self.state.db):
                self.assertFalse(recovery.begin(self.state, p, s, 'parent'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0], 0)
        self.assertEqual(self.factory.calls, [])

    def test_direct_admission_keeps_committed_target_without_second_admission(self):
        p,s=self.prepare();enqueue=pipelines.enqueue_step
        def direct(*args,**kwargs):
            enqueue(*args,**kwargs)
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='plan_production',target='confirmed-direct-plan' WHERE pipeline=? AND id=?",(p['id'],s['id']))
        with patch.object(recovery,'snapshot',return_value=self.baseline()),patch.object(pipelines,'enqueue_step',side_effect=direct),patch.object(recovery,'admit_saved_stage') as again,transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.step(p,'outline')['target'],'confirmed-direct-plan');again.assert_not_called()
        self.assertEqual(self.factory.calls,[])

    def test_detached_failed_plan_restores_only_exact_recorded_dispatch(self):
        from orchestrator.contracts import encoded,digest
        import hashlib
        p,s=self.prepare()
        with patch.object(recovery,'snapshot',return_value=self.baseline()),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        request=self.step(p,'outline')['request_id']
        plan=planning_fixtures.Tests.queue(self,99)
        baseline=self.state.db.execute('SELECT baseline FROM completion_recoveries WHERE request_id=?',(request,)).fetchone()[0]
        context=dict(completion_recovery=dict(baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest()))
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET request_id=?,channel=?,status='blocked',error='Confirmed invalid response',context=?,context_hash=? WHERE id=?",(request,p['channel'],encoded(context),digest(context),plan['id']))
            self.state.db.execute("INSERT INTO production_plan_calls(plan_id,number,request,response,usage,error,created) VALUES (?,1,'{}','{}','{}','Invalid plan',0)",(plan['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='running' WHERE pipeline=? AND id=?",(p['id'],s['id']))
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_plans')]
        recovery.reconcile_detached_admission(self.state)
        self.assertIsNone(self.step(p,'outline')['target'])
        with transaction(self.state.db):pipelines.event(self.state,p['id'],s['id'],'dispatched',dict(request_id=request,kind='plan_production',target=plan['id']))
        recovery.reconcile_detached_admission(self.state);recovery.reconcile_detached_admission(self.state)
        self.assertEqual(self.step(p,'outline')['target'],plan['id']);self.assertEqual(self.step(p,'outline')['status'],'blocked')
        self.assertEqual(before,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_plans')])
        self.assertEqual(self.factory.calls,[])

    def test_new_confirmed_baseline_of_same_run_consumes_next_cycle_without_duplicate(self):
        p,s=self.prepare();first=self.baseline();second=copy.deepcopy(first)
        second['gaps'][0]['instruction']='A later confirmed photo mismatch after preparation resumed'
        with patch.object(recovery,'snapshot',return_value=first),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM completion_recoveries')]
        with patch.object(recovery,'snapshot',return_value=second),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
            self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        rows=[tuple(r) for r in self.state.db.execute('SELECT * FROM completion_recoveries ORDER BY cycle')]
        self.assertEqual(rows[0],before[0]);self.assertEqual(len(rows),2)
        third=copy.deepcopy(second);third['gaps'][0]['instruction']='Third defect exceeds the existing two-cycle grant'
        with patch.object(recovery,'snapshot',return_value=third),transaction(self.state.db):
            self.assertFalse(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.factory.calls,[])

    def test_identity_migration_preserves_exact_receipts_and_is_idempotent(self):
        import sqlite3
        db=sqlite3.connect(':memory:')
        try:
            db.execute('CREATE TABLE completion_recoveries (pipeline TEXT NOT NULL,step TEXT NOT NULL,parent TEXT NOT NULL UNIQUE,cycle INTEGER NOT NULL,request_id INTEGER UNIQUE NOT NULL,baseline TEXT NOT NULL,PRIMARY KEY(pipeline,step,cycle))')
            original=('pipe','stage','run',1,1,'{"exact":"original bytes"}')
            db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',original)
            recovery.initialize(db);recovery.initialize(db)
            self.assertEqual(tuple(db.execute('SELECT * FROM completion_recoveries').fetchone()),original)
            db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',('pipe','stage','run',2,2,'{"exact":"later receipt"}'))
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',('pipe','stage','run',3,3,original[-1]))
        finally:db.close()

    def test_changed_failure_reconciliation_commits_before_any_dispatch(self):
        from tests.test_orchestrator import pair
        p,s=self.prepare();graph=pair(max_attempts=1);graph['id']='parent';self.rt.create(graph)
        self.rt.tick('parent');attempt=self.rt.task('parent','produce')['latest']
        self.factory.finish(attempt,decision='blocked');self.rt.tick('parent')
        first=self.baseline();second=copy.deepcopy(first);second['gaps'][0]['instruction']='Later confirmed defect'
        parent=planning_fixtures.Tests.queue(self,99)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        with patch.object(recovery,'snapshot',return_value=first),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='production_run',target='parent',error='A transport-specific failure description, not controller syntax.' WHERE pipeline=? AND id='outline'",(p['id'],))
        before=list(self.factory.calls)
        with patch.object(recovery,'snapshot',return_value=second):recovery.reconcile_changed_failures(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()[0],'active')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],2)
        self.assertEqual(self.factory.calls,before);self.assertEqual(self.rt.task('parent','produce')['attempts'],1)
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(self.step(p,'outline')['target'],)).fetchone()
        self.assertEqual(successor['status'],'queued')
        self.assertIsNone(successor['run'])
        job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(self.step(p,'outline')['request_id'],)).fetchone()
        self.assertEqual(job['status'],'answered')
        self.assertIsNone(job['response'])

    def test_changed_failure_declined_admission_keeps_owner_blocked(self):
        self.test_changed_failure_reconciliation_commits_before_any_dispatch()
        p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='production_run',target='parent',error='A transport-specific failure description, not controller syntax.' WHERE pipeline=? AND id='outline'",(p['id'],))
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM completion_recoveries')]
        with patch.object(recovery,'begin',return_value=False):recovery.reconcile_changed_failures(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()[0],'blocked')
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM completion_recoveries')],before)
        self.assertEqual(self.step(p,'outline')['status'],'blocked')

    def test_rollback_cannot_leave_a_dispatchable_request(self):
        p, s = self.prepare()
        with patch.object(recovery, 'snapshot', return_value=self.baseline()):
            with self.assertRaisesRegex(ValueError, 'rollback'):
                with transaction(self.state.db):
                    recovery.begin(self.state, p, s, 'parent')
                    raise ValueError('rollback')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0], 0)
        self.assertEqual(self.step(p, 'outline')['status'], 'running')
        self.assertEqual(self.factory.calls, [])

    def test_recovery_binds_original_helper_bytes_as_well_as_partial_outputs(self):
        p,s=self.prepare();path=self.state.media_dir.parent/'capture-helper.py'
        path.write_text('# frozen helper, not authored replacement\n')
        aid=self.rt.register(path,'Exact original helper')
        baseline=self.baseline();baseline['plan']['tasks'][0]['inputs']=[dict(artifact=aid,path='support/capture.py')]
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        context=pipelines.request_context(self.state,self.step(p,'outline')['request_id'])
        self.assertEqual([a['artifact'] for a in context['inputs']['sources']],[aid])
        self.assertEqual(__import__('pathlib').Path(context['inputs']['sources'][0]['path']).read_bytes(),path.read_bytes())

    def test_known_standalone_stage_admits_native_planning_without_interpretation(self):
        p,s=self.prepare()
        parent=planning_fixtures.Tests.queue(self,99)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        with patch.object(recovery,'snapshot',return_value=self.baseline()),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        step=self.step(p,'outline');job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(step['request_id'],)).fetchone()
        self.assertEqual(job['status'],'answered');self.assertIsNone(job['response'])
        self.assertEqual(step['status'],'running');self.assertEqual(step['target_kind'],'plan_production')
        child=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(step['target'],)).fetchone()
        opts=json.loads(child['options']);self.assertEqual(opts['limits']['tool_calls'],recovery.POLICY['tool_calls'])
        from task_relay import planning_contract
        raw=planning_fixtures.Tests.response(self)
        prepared,bindings=planning_contract.prepare(raw,json.loads(child['context']),opts)
        self.assertTrue(all(t['limits']['tool_calls']<=recovery.POLICY['tool_calls'] for t in prepared['plan']['tasks']))
        self.assertTrue(bindings);self.assertEqual(raw['plan']['tasks'][0]['limits']['tool_calls'],60)
        self.assertEqual(child['status'],'queued');self.assertEqual(child['calls'],0)
        self.assertEqual(self.factory.calls,[])

    def test_native_recovery_keeps_full_audit_without_repeating_it_in_paid_context(self):
        p,s=self.prepare()
        parent=planning_fixtures.Tests.queue(self,99)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        baseline=self.baseline()
        marker='original-frozen-audit-only'
        baseline['plan']['origin']={'audit':marker}
        baseline['plan']['tasks'][0]['instruction']=marker
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        step=self.step(p,'outline')
        saved=json.loads(self.state.db.execute('SELECT baseline FROM completion_recoveries').fetchone()[0])
        self.assertEqual(saved,baseline)
        request=self.state.db.execute('SELECT prompt FROM orchestrator_chats WHERE id=?',(step['request_id'],)).fetchone()[0]
        child=self.state.db.execute('SELECT context FROM production_plans WHERE id=?',(step['target'],)).fetchone()[0]
        self.assertNotIn(marker,request)
        self.assertNotIn(marker,child)
        brief=json.loads(child)['completion_recovery']
        self.assertEqual(brief['original_plan']['deliverables'],baseline['plan']['deliverables'])
        self.assertEqual(brief['original_plan']['tasks'][0]['backend'],{'type':'codex-cli'})
        self.assertEqual(brief['gaps'],baseline['gaps'])
        self.assertEqual(brief['baseline_sha256'],recovery.hashlib.sha256(recovery.encoded(baseline).encode()).hexdigest())
        self.assertEqual(self.factory.calls,[])

    def test_escaped_source_previews_fit_budget_without_losing_original_inputs(self):
        p,s=self.prepare();parent=planning_fixtures.Tests.queue(self,99)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        baseline=self.baseline();inputs=[];originals=[]
        for index in range(2):
            path=self.state.media_dir.parent/('escaped-'+str(index)+'.txt')
            path.write_text(chr(92)*80000)
            aid=self.rt.register(path,'Exact escaped source fixture')
            inputs.append(dict(artifact=aid,path=path.name));originals.append(path.read_bytes())
        baseline['plan']['tasks'][0]['inputs']=inputs
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        step=self.step(p,'outline')
        body=json.loads(self.state.db.execute('SELECT context FROM production_plans WHERE id=?',(step['target'],)).fetchone()[0])
        self.assertLessEqual(sum(len(recovery.encoded(t)) for t in body['source_texts']),220000)
        sources=pipelines.request_context(self.state,step['request_id'])['inputs']['sources']
        self.assertEqual([__import__('pathlib').Path(t['path']).read_bytes() for t in sources],originals)
        self.assertEqual(self.factory.calls,[])
        self.assertTrue(body['source_text_aliases'])
        by_id={s['artifact']:s for s in body['sources']}
        for alias,target in body['source_text_aliases'].items():
            self.assertEqual((by_id[alias]['sha256'],by_id[alias]['bytes']),(by_id[target]['sha256'],by_id[target]['bytes']))

    def test_recovery_keeps_archive_without_unrelated_recent_history(self):
        from task_relay import routing_inputs
        p,s=self.prepare();parent=planning_fixtures.Tests.queue(self,99)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        baseline=self.baseline();recent=[dict(id='unrelated-'+str(n),path='other.txt',purpose='Unrelated history '*400,sha256='a'*64,bytes=10,run='other',task='other',attempt='old',attempt_state='completed') for n in range(100)]
        catalog=routing_inputs.artifact_catalog
        with patch.object(routing_inputs,'artifact_catalog',side_effect=lambda state:catalog(state)+recent),patch.object(recovery,'snapshot',return_value=baseline),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        step=self.step(p,'outline')
        body=json.loads(self.state.db.execute('SELECT context FROM production_plans WHERE id=?',(step['target'],)).fetchone()[0])
        self.assertEqual(body['available_sources'],[])
        self.assertLess(len(recovery.encoded(body)),__import__('task_relay.production_planning',fromlist=['MAX_CONTEXT']).MAX_CONTEXT)
        self.assertEqual(json.loads(self.state.db.execute('SELECT baseline FROM completion_recoveries').fetchone()[0]),baseline)
        self.assertEqual(self.factory.calls,[])

    def test_missing_grant_and_uncertain_snapshot_do_not_queue(self):
        p, s = self.prepare()
        with patch.object(recovery, 'snapshot', return_value=None), transaction(self.state.db):
            self.assertFalse(recovery.begin(self.state, p, s, 'parent'))
        self.state.db.execute('DELETE FROM completion_recovery_grants');self.state.db.commit()
        with patch.object(recovery, 'snapshot', return_value=self.baseline()), transaction(self.state.db):
            self.assertFalse(recovery.begin(self.state, p, s, 'parent'))

    def test_cycle_exhaustion_preserves_original_stage(self):
        p, s = self.prepare()
        with patch.object(recovery, 'snapshot', return_value=self.baseline()), transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state, p, s, 'parent'))
            self.assertTrue(recovery.begin(self.state, p, s, 'second'))
            self.assertFalse(recovery.begin(self.state, p, s, 'third'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0], 2)

    def test_followup_plan_must_retain_delivery_review_and_fit_budget(self):
        p, s = self.prepare();baseline = self.baseline()
        with patch.object(recovery, 'snapshot', return_value=baseline), transaction(self.state.db):
            recovery.begin(self.state, p, s, 'parent')
        request = self.step(p, 'outline')['request_id']
        producer = dict(id='write', max_attempts=1, limits=dict(seconds=600, tool_calls=24), backend={'type':'codex-cli'})
        review = dict(id='review', review_of='write', max_attempts=1, limits=dict(seconds=600, tool_calls=24), backend={'type':'codex-cli'})
        plan = dict(tasks=[producer, review], deliverables=baseline['plan']['deliverables'])
        with patch.object(recovery, 'snapshot', return_value=baseline):
            recovery.check_plan(self.state, p, s, dict(request_id=request, plan=json.dumps(plan)))
            reworded=copy.deepcopy(plan);reworded['deliverables']['outline']['description']='Same checked output, clearer wording'
            recovery.check_plan(self.state,p,s,dict(request_id=request,plan=json.dumps(reworded)))
            for change, message in [('budget', 'budget'), ('review', 'review'), ('delivery', 'deliverables')]:
                changed = copy.deepcopy(plan)
                if change == 'budget':changed['tasks'][0]['limits']['tool_calls'] = 60
                if change == 'review':changed['tasks'].pop()
                if change == 'delivery':changed['deliverables'] = {}
                with self.assertRaisesRegex(ValueError, message):
                    recovery.check_plan(self.state, p, s, dict(request_id=request, plan=json.dumps(changed)))
        with patch.object(recovery, 'snapshot', return_value=None), self.assertRaisesRegex(ValueError, 'baseline changed'):
            recovery.check_plan(self.state, p, s, dict(request_id=request, plan=json.dumps(plan)))

    def test_delivery_recovery_retains_registered_local_operations_and_preview(self):
        p,s=self.prepare();baseline=self.baseline()
        for cap in ('collection.slides','pptx.create','pptx.render'):
            baseline['plan']['tasks'].append(dict(execution=dict(capability=cap)))
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(self.state.db):
            recovery.begin(self.state,p,s,'parent')
            self.state.db.execute('UPDATE completion_recovery_grants SET policy=? WHERE pipeline=?',(json.dumps(recovery.DELIVERY_POLICY),p['id']))
        request=self.step(p,'outline')['request_id'];tasks=[]
        for cap in ('collection.slides','pptx.create','pptx.render'):
            tasks.append(dict(id=cap,execution=dict(capability=cap),max_attempts=1,limits=dict(seconds=120,tool_calls=1)))
            if cap!='pptx.render':tasks.append(dict(id=cap+'-review',review_of=cap,backend={'type':'codex-cli'},max_attempts=1,limits=dict(seconds=600,tool_calls=24)))
        plan=dict(tasks=tasks,deliverables=baseline['plan']['deliverables'])
        with patch.object(recovery,'snapshot',return_value=baseline):
            recovery.check_plan(self.state,p,s,dict(request_id=request,plan=json.dumps(plan)))
            for capability in ('rhino.run_python','pptx.edit'):
                changed=copy.deepcopy(plan);changed['tasks'][0]['execution']['capability']=capability
                with self.assertRaisesRegex(ValueError,'host operations'):
                    recovery.check_plan(self.state,p,s,dict(request_id=request,plan=json.dumps(changed)))

    def test_snapshot_rejects_pending_calls_even_with_finished_receipt(self):
        # A worker exit does not prove that its remote generation finished.
        p, s = self.prepare()
        self.state.db.execute("INSERT INTO production_runs VALUES ('parent','{}','active')")
        self.state.db.execute("INSERT INTO production_tasks VALUES ('parent','write','a','blocked',1,'x')")
        self.state.db.execute("INSERT INTO production_attempts VALUES ('x','parent','write','a','blocked',NULL,?,'{}',?,NULL)",
                              (json.dumps({'backend':{'type':'codex-cli'}}), json.dumps({'status':'finished','pending_requests':[{'id':'remote'}]})))
        self.state.db.commit()
        self.assertIsNone(recovery.snapshot(self.state, 'parent'))

    def test_actual_review_gap_is_classified_only_for_the_exact_current_version(self):
        self.prepare()
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO production_runs VALUES ('parent',?,'active')", (json.dumps({'tasks':[]}),))
            self.state.db.execute("INSERT INTO production_assignments VALUES ('a','parent','review',1,?)", (json.dumps({'review_of':'write'}),))
            self.state.db.execute("INSERT INTO production_tasks VALUES ('parent','write','w','awaiting_review',1,'draft')")
            self.state.db.execute("INSERT INTO production_tasks VALUES ('parent','review','a','blocked',1,'x')")
            frozen=json.dumps({'backend':{'type':'codex-cli'},'review_target':'draft'})
            self.state.db.execute("INSERT INTO production_attempts VALUES ('x','parent','review','a','blocked',NULL,?,'{}',?,NULL)",
                                  (frozen,json.dumps({'status':'finished'})))
            result=dict(kind='model_review',result=dict(decision='blocked', findings=[dict(category='requirements',code='missing_product_page')]))
            self.state.db.execute("INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (0,'parent','review','x','checks_recorded',?)",(json.dumps(result),))
        snapshot=recovery.snapshot(self.state,'parent')
        self.assertEqual(snapshot['gaps'][0]['kind'],'review_gaps')
        self.assertFalse(snapshot['user_accepted'])
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_tasks SET latest='replacement' WHERE run='parent' AND id='write'")
        self.assertIsNone(recovery.snapshot(self.state,'parent'))

    def test_effectively_blocked_accept_review_is_recoverable_without_accepting_outputs(self):
        self.test_actual_review_gap_is_classified_only_for_the_exact_current_version()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_tasks SET latest='draft' WHERE run='parent' AND id='write'")
            result=dict(kind='model_review',result=dict(decision='accept',findings=[dict(category='requirements',code='DOWNSTREAM_PRODUCT_EVIDENCE_GAP')]))
            self.state.db.execute("UPDATE production_events SET data=? WHERE run='parent' AND attempt='x' AND kind='checks_recorded'",(json.dumps(result),))
        snapshot=recovery.snapshot(self.state,'parent')
        self.assertEqual(snapshot['gaps'][0]['findings'][0]['code'],'DOWNSTREAM_PRODUCT_EVIDENCE_GAP')
        self.assertFalse(snapshot['user_accepted'])
        self.assertEqual(self.state.db.execute("SELECT status FROM production_tasks WHERE run='parent' AND id='review'").fetchone()[0],'blocked')
        # Effective blocking findings cannot waive authorization, or reopen accepted work.
        with transaction(self.state.db):
            result['result']['findings'][0]['category']='authorization'
            self.state.db.execute("UPDATE production_events SET data=? WHERE run='parent' AND attempt='x'",(json.dumps(result),))
        self.assertIsNone(recovery.snapshot(self.state,'parent'))
        with transaction(self.state.db):
            result['result']['findings'][0]['category']='requirements'
            self.state.db.execute("UPDATE production_events SET data=? WHERE run='parent' AND attempt='x'",(json.dumps(result),))
            self.state.db.execute("UPDATE production_tasks SET status='completed' WHERE run='parent' AND id='review'")
        self.assertIsNone(recovery.snapshot(self.state,'parent'))


    def test_finished_producer_gap_can_continue_without_acceptance_or_replay(self):
        p,s=self.prepare()
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO production_runs VALUES ('parent',?,'active')", (json.dumps({'tasks':[]}),))
            self.state.db.execute("INSERT INTO production_assignments VALUES ('a','parent','write',1,?)", (json.dumps({}),))
            self.state.db.execute("INSERT INTO production_tasks VALUES ('parent','write','a','blocked',1,'x')")
            self.state.db.execute("INSERT INTO production_attempts VALUES ('x','parent','write','a','blocked',NULL,?,'{}',?,NULL)",
                                  (json.dumps({'backend':{'type':'codex-cli'}}),json.dumps({'status':'finished'})))
            report=dict(kind='worker_self_report',result=dict(assignment_id='x',decision='blocked',findings=[dict(category='requirements',code='missing_evidence')]))
            self.state.db.execute("INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (0,'parent','write','x','checks_recorded',?)",(json.dumps(report),))
        baseline=recovery.snapshot(self.state,'parent')
        self.assertEqual(baseline['gaps'][0]['kind'],'producer_gaps')
        self.assertFalse(baseline['user_accepted'])
        self.assertFalse(baseline['attempts_reset'])
        with transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        self.assertEqual(self.step(p,'outline')['status'],'queued')
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.state.db.execute("SELECT status FROM production_tasks WHERE run='parent' AND id='write'").fetchone()[0],'blocked')
        for category in ('authorization','uncertainty','quality','execution'):
            report['result']['findings'][0]['category']=category
            with transaction(self.state.db):
                self.state.db.execute("UPDATE production_events SET data=? WHERE attempt='x'",(json.dumps(report),))
            self.assertIsNone(recovery.snapshot(self.state,'parent'))
        report['result']['findings'][0]['category']='requirements'
        report['result']['assignment_id']='stale'
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_events SET data=? WHERE attempt='x'",(json.dumps(report),))
        self.assertIsNone(recovery.snapshot(self.state,'parent'))

    def standalone_parent(self):
        from tests.test_orchestrator import pair
        self.rt.create(pair(max_attempts=1));self.rt.tick('demo')
        self.factory.finish(self.rt.task('demo','produce')['latest']);self.rt.tick('demo');self.rt.tick('demo')
        aid=self.rt.task('demo','review')['latest'];self.factory.finish(aid,decision='revise')
        path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
        report=json.loads(path.read_text());report['findings']=[dict(category='integrity',code='attribution',message='Incorrect source attribution',evidence='Saved report versus source')];path.write_text(json.dumps(report));self.rt.tick('demo')
        journal=self.state.media_dir.parent/'journal.txt';journal.write_text('Exact saved runtime observation')
        self.rt.register(journal,'Runtime evidence',run='demo',path='browser-evidence/journal.txt')
        return aid

    def test_standalone_correction_commits_once_then_completes_independent_review(self):
        from task_relay import production_control as pc,relay_channels
        self.standalone_parent();before=len(self.factory.calls);baseline=recovery.snapshot(self.state,'demo')
        with transaction(self.state.db):
            self.state.put('production-control-epoch:demo',1)
            recovery.authorize_standalone_correction(ScopedState(self.state,'desktop'),'demo','lets fix it')
        recovery.advance_standalone_corrections(self.state)
        grant=self.state.db.execute('SELECT * FROM standalone_correction_grants').fetchone();child=grant['head']
        self.assertNotEqual(child,'demo');self.assertEqual(grant['cycle'],1)
        self.assertEqual(len(self.factory.calls),before) # admission never dispatches
        self.assertEqual(recovery.snapshot(self.state,'demo'),baseline)
        recovery.advance_standalone_corrections(self.state)
        self.assertEqual(self.state.db.execute('SELECT cycle FROM standalone_correction_grants').fetchone()[0],1)
        event='production:'+child+':correction-queued';self.assertEqual(relay_channels.event_channel(self.state,event),'desktop')
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.factory.finish(self.rt.task(child,'correct_report')['latest']);worker.tick()
        self.factory.finish(self.rt.task(child,'review_correction')['latest'],decision='accept');worker.tick()
        self.assertEqual(self.rt.status(child)['status'],'completed')
        self.assertEqual(recovery.snapshot(self.state,'demo'),baseline)
        self.assertEqual(len(self.factory.calls),before+2)

    def test_standalone_queue_rolls_back_plan_and_grant_together(self):
        self.standalone_parent()
        with transaction(self.state.db):recovery.authorize_standalone_correction(self.state,'demo','lets fix it')
        before=self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0]
        with patch.object(self.state,'put',side_effect=ValueError('write failed')):
            with self.assertRaisesRegex(ValueError,'write failed'):recovery.advance_standalone_corrections(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT head,cycle FROM standalone_correction_grants').fetchone()[:],('demo',0))
        recovery.advance_standalone_corrections(self.state)
        self.assertEqual(self.state.db.execute('SELECT cycle FROM standalone_correction_grants').fetchone()[0],1)

    def test_standalone_correction_rollback_control_change_and_unknown_effects(self):
        self.standalone_parent()
        with self.assertRaisesRegex(ValueError,'rollback'):
            with transaction(self.state.db):
                recovery.authorize_standalone_correction(self.state,'demo','lets fix it');raise ValueError('rollback')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM standalone_correction_grants').fetchone()[0],0)
        with transaction(self.state.db):
            recovery.authorize_standalone_correction(self.state,'demo','lets fix it')
            self.state.put('production-control-epoch:demo',1)
        recovery.advance_standalone_corrections(self.state)
        self.assertEqual(self.state.db.execute('SELECT head FROM standalone_correction_grants').fetchone()[0],'demo')
        baseline=recovery.snapshot(self.state,'demo');baseline['gaps'][0]['findings'][0]['category']='authorization'
        with self.assertRaisesRegex(ValueError,'cannot waive'):recovery.correction_plan(self.rt,baseline,'child','lets fix it')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE run='demo' AND task='review'")
        self.assertIsNone(recovery.snapshot(self.state,'demo'))


    def test_prepared_recovery_keeps_original_model_and_domains(self):
        p,s=self.prepare();baseline=self.baseline()
        source=dict(id='sources',execution=dict(capability='web.sources.prepared',parameters=dict(model='frozen-source-model',domains=['retailer.example'])),max_attempts=1,limits=dict(seconds=600,tool_calls=1))
        review=dict(id='review',review_of='sources',backend={'type':'codex-cli'},max_attempts=1,limits=dict(seconds=600,tool_calls=24))
        baseline['plan']['tasks']=[source,review]
        with patch.object(recovery,'snapshot',return_value=baseline),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'parent'))
        step=self.step(p,'outline');row={'request_id':step['request_id'],'plan':json.dumps(baseline['plan'])}
        with patch.object(recovery,'snapshot',return_value=baseline):
            recovery.check_plan(self.state,p,step,row)
            for field,value in [('model','other-model'),('domains',['other.example'])]:
                changed=copy.deepcopy(baseline['plan']);changed['tasks'][0]['execution']['parameters'][field]=value
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,'prepared-source provider or domains'):
                    recovery.check_plan(self.state,p,step,dict(request_id=step['request_id'],plan=json.dumps(changed)))



    def test_advisories_preserve_gaps_but_cannot_create_recovery_or_waive_permission(self):
        self.test_actual_review_gap_is_classified_only_for_the_exact_current_version()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_tasks SET latest='draft' WHERE run='parent' AND id='write'")
        for categories,eligible in [(['requirements','advisory'],True),(['advisory'],False),(['requirements','advisory','authorization'],False),(['requirements','advisory','uncertainty'],False)]:
            findings=[dict(category=k,code=k,message='Exact review finding',evidence='Frozen candidate') for k in categories]
            report=dict(kind='model_review',result=dict(decision='blocked',findings=findings))
            with transaction(self.state.db):
                self.state.db.execute("UPDATE production_events SET data=? WHERE run='parent' AND attempt='x'",(json.dumps(report),))
            baseline=recovery.snapshot(self.state,'parent')
            self.assertEqual(baseline is not None,eligible)
            if eligible:self.assertEqual(baseline['gaps'][0]['findings'],findings)


    def test_rejected_evidence_report_recovers_exact_candidate_without_acceptance(self):
        from tests.test_orchestrator import pair
        from task_relay import text_evidence_planning
        from pathlib import Path
        p,stage=self.prepare()
        source=self.rt.root/'source.txt';source.write_text('A supported observation.')
        aid=self.rt.register(source,'Independent observation')
        graph=pair(max_attempts=1);graph['id']='parent'
        for task in graph['tasks']:
            task['criteria']=['Verify factual accuracy against independent sources.']
            task.setdefault('inputs',[]).append(dict(artifact=aid,path='source.txt',purpose='Independent source',authority='Frozen observation'))
        text_evidence_planning.bind(graph,dict(text_evidence_policy_version=1,sources=[dict(artifact=aid,path='source.txt')]))
        self.rt.create(graph);self.rt.tick('parent')
        producer=self.rt.task('parent','produce')['latest'];self.factory.finish(producer)
        (self.factory.sessions[producer]['workspace']/'output.txt').write_text('A supported observation.')
        self.rt.tick('parent');reviewer=self.rt.task('parent','review')['latest'];self.factory.finish(reviewer,decision='accept')
        workspace=self.factory.sessions[reviewer]['workspace'];path=workspace/'.relay/result.json';report=json.loads(path.read_text())
        report['checks'][0]['evidence']=json.dumps(dict(claims=[dict(candidate_path='candidate.txt#/invented',claim='A supported observation.',verdict='supported',reason='Source agrees',supports=[dict(path='source.txt',sha256=__import__('hashlib').sha256(source.read_bytes()).hexdigest(),quote='A supported observation.')])]))
        path.write_text(json.dumps(report));self.rt.tick('parent')
        self.assertEqual(self.rt.task('parent','review')['status'],'blocked')
        baseline=recovery.snapshot(self.state,'parent');self.assertEqual(baseline['gaps'][0]['kind'],'review_format')
        before=list(self.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,stage,'parent'))
        self.assertEqual(self.factory.calls,before)
        self.assertEqual(self.rt.task('parent','produce')['latest'],producer)
        self.assertEqual(self.rt.task('parent','review')['latest'],reviewer)
        self.assertFalse(baseline['user_accepted'])

    def test_rejected_typed_decision_recovers_without_replaying_source_or_accepting(self):
        from tests.test_orchestrator import pair
        p,stage=self.prepare();graph=pair(max_attempts=1);graph['id']='parent'
        self.rt.create(graph);self.rt.tick('parent')
        producer=self.rt.task('parent','produce')['latest'];self.factory.finish(producer)
        self.rt.tick('parent');reviewer=self.rt.task('parent','review')['latest'];self.factory.finish(reviewer,decision='accept')
        path=self.factory.sessions[reviewer]['workspace']/'.relay/result.json'
        path.write_text(json.dumps(dict(summary='Recorded partial coverage.',decision='accept',instruction='',findings=[],
                                       checks={'c1':dict(passed=False,evidence='The old criterion is unmet.')})))
        self.rt.tick('parent')
        self.assertEqual(self.rt.task('parent','review')['status'],'blocked')
        baseline=recovery.snapshot(self.state,'parent');self.assertEqual(baseline['gaps'][0]['kind'],'review_format')
        self.assertIn('Do not retain an acceptance decision',baseline['gaps'][0]['instruction'])
        before=list(self.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,stage,'parent'))
        self.assertEqual(self.factory.calls,before)
        self.assertEqual(self.rt.task('parent','review')['latest'],reviewer)
        self.assertEqual(self.rt.task('parent','produce')['latest'],producer)
        self.assertFalse(baseline['user_accepted'])

if __name__ == '__main__':unittest.main()
