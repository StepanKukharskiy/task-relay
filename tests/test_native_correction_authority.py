"""Controller authorization across a native correction; tiny scripted artifacts."""
import copy,json,unittest
from unittest.mock import patch
from orchestrator import corrections,execution,contracts as c
from orchestrator.storage import transaction
from task_relay import production_control as pc,completion_recovery
from tests import test_production_planning as fixtures
from tests.test_corrections import graph,CorrectionFactory

class Tests(unittest.TestCase):
    tearDown=fixtures.Tests.tearDown

    def setUp(self):
        fixtures.Tests.setUp(self)
        availability=patch.object(execution,'available');availability.start();self.addCleanup(availability.stop)
        # Document/data validation has separate native-chain coverage. Keep
        # this controller fixture text-only, with no media or provider work.
        for target in ('orchestrator.sourcing_slides.build','task_relay.external_evidence.recorded_sources'):
            seam=patch(target,return_value=True);seam.start();self.addCleanup(seam.stop)
        self.factory=CorrectionFactory();self.rt.factory=self.factory
        value=graph();value['id']='layout';author=value['tasks'][0];author.pop('tools',None)
        params=dict(inventory_path='inventory.json',catalog_path='catalog.json',source_pack_path='source-pack.json',image_path='room.png',photos_path=None,title='Synthetic layout',layout='standard')
        author.update(role='procedure',execution=dict(capability='sourcing.slides',version=1,parameters=params),criteria=execution.REGISTRY['sourcing.slides']['criteria'].copy(),max_attempts=2)
        author['inputs']=[]
        for name in ('inventory.json','catalog.json','source-pack.json','room.png'):
            p=self.rt.root/name;p.write_text('{}')
            author['inputs'].append(dict(artifact=self.rt.register(p,'Synthetic bound input'),path=name,purpose='Exact fixture',authority='Fixture',media_type='image/png' if name.endswith('.png') else 'application/json'))
        value['tasks'][1]['criteria']=author['criteria'].copy()
        value['tasks'][2].pop('user_gate',None);value['tasks'][2].pop('review_correction',None)
        corrections.compile(value['tasks'],sourcing_layout=True)
        value=c.plan(value)
        # This tiny fixture fits the existing 24-call recovery grant. A larger
        # original allowance must now be held rather than silently reduced.
        for task in value['tasks']:
            if not task.get('execution'):task['limits']['tool_calls']=24
        if self._testMethodName.startswith('test_capacity_'):
            for task in value['tasks']:
                if not task.get('execution'):task['limits'].update(seconds=1800 if self._testMethodName.endswith('exhaustion') else 855,tool_calls=23)
        self.rt.create(value);self.initial=pc.runtime_digest(self.rt,'layout')
        with transaction(self.state.db):self.state.put('production-enabled:layout',self.initial)
        self.worker=pc.Worker(self.state,lambda _:self.rt)
        self.worker.tick()

    def finish(self,tid,decision='delivered',worker=True,category='requirements',code='layout_readability'):
        aid=self.rt.task('layout',tid)['latest'];self.assertIsNotNone(aid)
        self.factory.finish(aid,decision=decision)
        if decision=='revise':
            path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
            result=json.loads(path.read_text());result['findings']=[dict(category=category,code=code,message='Observed candidate defect',evidence='Exact synthetic candidate')]
            path.write_text(json.dumps(result))
        if tid in ('produce','deck'):self.factory.sessions[aid]['status']['operation']=dict(outcome='completed')
        if worker:self.worker.tick()
        else:self.rt.tick('layout')
        return aid

    def correct(self):
        self.finish('produce');self.finish('review','accept');self.finish('deck');self.finish('final','revise')
        self.assertEqual(self.rt.spec(self.rt.task('layout','produce'))['execution']['parameters']['layout'],'readable')

    def bind_owner(self):
        raw=self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',('layout',)).fetchone()[0]
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO production_plans(id,request_id,channel,request,options,context,context_hash,provider,model,status,plan,plan_hash,token,expires,created,run) VALUES ('layout-plan',99,'desktop','Synthetic authorized file delivery','{}','{}',?,'gemini','fixture','started',?,?,'fixture',1000,0,'layout')",(c.digest({}),raw,c.digest(json.loads(raw))))
            if self._testMethodName.startswith('test_capacity_'):
                options=dict(limits=dict(seconds=600 if self._testMethodName.endswith('ceiling') else 1800,tool_calls=60,output_bytes=100000000))
                self.state.db.execute("UPDATE production_plans SET options=? WHERE id='layout-plan'",(c.encoded(options),))
            self.state.db.execute("INSERT INTO relay_pipelines VALUES ('layout-pipe',99,'Synthetic delivery','Fixture','{}','desktop','gemini','fixture','active',0)")
            self.state.db.execute("INSERT INTO relay_pipeline_steps(pipeline,position,id,status,target_kind,target) VALUES ('layout-pipe',0,'deck','running','plan_production','layout-plan')")
            self.state.db.execute('INSERT INTO completion_recovery_grants VALUES (?,?,?)',('layout-pipe','Synthetic delivery',c.encoded(completion_recovery.DELIVERY_POLICY)))

    def test_controller_retains_grant_and_dispatches_corrected_review(self):
        self.correct();self.assertEqual(pc.runtime_digest(self.rt,'layout'),self.initial)
        self.finish('produce');self.worker.tick()
        self.assertEqual(self.rt.task('layout','review')['attempts'],2)
        self.assertTrue(self.state.get('production-enabled:layout'))
        self.assertFalse(self.state.db.execute("SELECT 1 FROM outbox WHERE id='production:layout:changed'").fetchone())

    def test_factual_specification_defect_does_not_spend_layout_attempt(self):
        first=self.finish('produce');self.finish('review','revise',category='integrity')
        task=self.rt.task('layout','produce')
        self.assertEqual((task['status'],task['attempts'],task['latest']),('blocked',1,first))
        self.assertEqual(self.rt.task('layout','deck')['attempts'],0)
        self.assertFalse(self.state.db.execute("SELECT 1 FROM production_events WHERE kind='native_specification_correction_scheduled'").fetchone())
        baseline=completion_recovery.snapshot(self.state,'layout')
        self.assertEqual(baseline['gaps'][0]['candidate_task'],'produce')
        self.assertEqual(baseline['gaps'][0]['task'],'review')
        calls=list(self.factory.calls)
        self.assertEqual(completion_recovery.snapshot(self.state,'layout'),baseline)
        self.assertEqual(self.factory.calls,calls)
        latest=self.rt.task('layout','review')['latest']
        with transaction(self.state.db):
            row=self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(latest,)).fetchone()
            frozen=json.loads(row[0]);frozen['review_target']='stale-candidate'
            self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(c.encoded(frozen),latest))
        self.assertIsNone(completion_recovery.snapshot(self.state,'layout'))

    def test_factual_final_defect_keeps_exact_candidate_without_layout_replay(self):
        first=self.finish('produce');self.finish('review','accept');deck=self.finish('deck')
        self.finish('final','revise',category='requirements',code='wrong_count')
        self.assertEqual(self.rt.task('layout','produce')['latest'],first)
        self.assertEqual(self.rt.task('layout','produce')['attempts'],1)
        self.assertEqual(self.rt.task('layout','deck')['latest'],deck)
        self.assertEqual(self.rt.task('layout','deck')['status'],'blocked')
        baseline=completion_recovery.snapshot(self.state,'layout')
        self.assertEqual(baseline['gaps'][0]['candidate_task'],'deck')
        with transaction(self.state.db):
            row=self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(deck,)).fetchone()
            receipt=json.loads(row[0]);receipt['pending_requests']=['unknown-effect']
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded(receipt),deck))
        self.assertIsNone(completion_recovery.snapshot(self.state,'layout'))

    def data_revision(self):
        from task_relay import registered_revision
        self.finish('produce');self.finish('review','revise',category='integrity')
        baseline=completion_recovery.snapshot(self.state,'layout');self.bind_owner()
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',('layout-pipe','deck','layout',1,-900,c.encoded(baseline)))
            before=list(self.factory.calls)
            self.assertTrue(registered_revision.queue(self.state,self.rt,dict(id='layout-pipe',channel='desktop'),dict(id='deck'),baseline,1))
            self.assertEqual(self.factory.calls,before)
        step=self.state.db.execute("SELECT target FROM relay_pipeline_steps WHERE pipeline='layout-pipe'").fetchone()
        return step[0],baseline

    def test_native_data_correction_reuses_candidate_then_reviews_and_delivers(self):
        run,baseline=self.data_revision();old=[tuple(r) for r in self.state.db.execute("SELECT * FROM production_attempts WHERE run='layout'")]
        self.rt.tick(run)
        for tid,decision in [('produce','delivered'),('review','accept'),('deck','delivered'),('final','accept')]:
            attempt=self.rt.task(run,tid)['latest'];self.assertIsNotNone(attempt)
            self.factory.finish(attempt,decision=decision)
            if tid=='deck':self.factory.sessions[attempt]['status']['operation']=dict(outcome='completed')
            self.rt.tick(run)
        self.assertEqual(self.rt.status(run)['status'],'completed')
        author=self.rt.spec(self.rt.task(run,'produce'))
        self.assertNotIn('execution',author)
        previous=next(t['latest'] for t in baseline['tasks'] if t['id']=='produce')
        self.assertTrue(any(self.rt.artifact(i['artifact'])['attempt']==previous for i in author['inputs']))
        self.assertEqual([tuple(r) for r in self.state.db.execute("SELECT * FROM production_attempts WHERE run='layout'")],old)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)

    def test_capacity_reservation_survives_restart_and_delivers(self):
        from orchestrator.runtime import Runtime
        from task_relay import registered_revision
        run,baseline=self.data_revision()
        old=[tuple(r) for r in self.state.db.execute("SELECT * FROM production_attempts WHERE run='layout'")]
        plan=json.loads(self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
        capacity=plan['origin']['registered_revision']['capacity']
        self.assertEqual(capacity['reserved_slots'],7)
        self.assertLessEqual(sum(t['limits']['seconds'] for t in plan['tasks']),8*600)
        self.assertEqual([t['limits']['seconds'] for t in plan['tasks'] if not t.get('execution')],[855]*3)
        self.rt=Runtime(self.rt.root,self.factory,connection=self.state.db)
        registered_revision.validate_dispatch(self.rt,plan)
        self.rt.tick(run)
        for tid,decision in [('produce','delivered'),('review','accept'),('deck','delivered'),('final','accept')]:
            attempt=self.rt.task(run,tid)['latest'];self.assertIsNotNone(attempt)
            self.factory.finish(attempt,decision=decision)
            if tid=='deck':self.factory.sessions[attempt]['status']['operation']=dict(outcome='completed')
            self.rt.tick(run)
        self.assertEqual(self.rt.status(run)['status'],'completed')
        self.assertEqual([tuple(r) for r in self.state.db.execute("SELECT * FROM production_attempts WHERE run='layout'")],old)

    def test_capacity_changed_authority_stops_before_dispatch(self):
        run,_=self.data_revision()
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET options='{}' WHERE id='layout-plan'")
        before=list(self.factory.calls);self.rt.tick(run)
        self.assertEqual(self.factory.calls,before)
        self.assertEqual(self.rt.task(run,'produce')['attempts'],0)
        self.assertEqual(self.rt.task(run,'produce')['status'],'blocked')

    def test_capacity_respects_original_ceiling(self):
        before=self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'original admitted'):
            self.data_revision()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)

    def test_capacity_respects_total_reserve_exhaustion(self):
        before=self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'total existing recovery reserve'):
            self.data_revision()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)

    def test_changed_review_proof_holds_data_revision_before_dispatch(self):
        run,_=self.data_revision()
        with transaction(self.state.db):
            row=self.state.db.execute("SELECT id,data FROM production_events WHERE kind='checks_recorded' AND task='review' ORDER BY id DESC LIMIT 1").fetchone()
            value=json.loads(row['data']);value['result']['instruction']='Changed review instruction'
            self.state.db.execute('UPDATE production_events SET data=? WHERE id=?',(c.encoded(value),row['id']))
        calls=list(self.factory.calls);self.rt.tick(run)
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.task(run,'produce')['attempts'],0)
        self.assertEqual(self.rt.task(run,'produce')['status'],'blocked')

    def derived_revision(self,preparation=False):
        from task_relay import registered_revision
        run,_=self.data_revision();self.rt.tick(run)
        sequence=([('produce','delivered'),('review','revise')] if preparation else
                  [('produce','delivered'),('review','accept'),('deck','delivered'),('final','revise')])
        for tid,decision in sequence:
            aid=self.rt.task(run,tid)['latest'];self.factory.finish(aid,decision=decision)
            if tid=='deck':self.factory.sessions[aid]['status']['operation']=dict(outcome='completed')
            if decision=='revise':
                p=self.factory.sessions[aid]['workspace']/'.relay/result.json';v=json.loads(p.read_text())
                v['findings']=[dict(category='integrity',code='unsupported_label',message='Qualify label in prepared data',evidence='Exact rendered candidate')];p.write_text(json.dumps(v))
            self.rt.tick(run)
        baseline=completion_recovery.snapshot(self.state,run)
        self.assertIsNotNone(baseline)
        evidence=registered_revision.proof(self.rt,baseline);self.assertIsNotNone(evidence)
        return run,baseline,evidence

    def test_rejected_corrected_data_reuses_latest_version_before_native_dispatch(self):
        from task_relay import registered_revision
        run,baseline,evidence=self.derived_revision(preparation=True)
        self.assertEqual(evidence['candidate']['artifact'],self.rt.output(run,'produce','slides.json')['id'])
        self.assertEqual(self.rt.task(run,'deck')['attempts'],0)
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',('layout-pipe','deck',run,2,-901,c.encoded(baseline)))
            self.assertTrue(registered_revision.queue(self.state,self.rt,dict(id='layout-pipe',channel='desktop'),dict(id='deck'),baseline,2))
        successor=self.state.db.execute("SELECT target FROM relay_pipeline_steps WHERE pipeline='layout-pipe'").fetchone()[0]
        self.rt.tick(successor)
        self.assertEqual(self.rt.task(successor,'produce')['attempts'],1)
        self.assertEqual(self.rt.task(successor,'deck')['attempts'],0)

    def test_final_artifact_revision_returns_to_exact_prepared_data_and_delivers(self):
        from task_relay import registered_revision
        run,baseline,evidence=self.derived_revision()
        self.assertEqual(evidence['candidate']['artifact'],self.rt.output(run,'produce','slides.json')['id'])
        history=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(run,))]
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',('layout-pipe','deck',run,2,-901,c.encoded(baseline)))
            self.assertTrue(registered_revision.queue(self.state,self.rt,dict(id='layout-pipe',channel='desktop'),dict(id='deck'),baseline,2))
        successor=self.state.db.execute("SELECT target FROM relay_pipeline_steps WHERE pipeline='layout-pipe'").fetchone()[0]
        self.rt.tick(successor)
        for tid,decision in [('produce','delivered'),('review','accept'),('deck','delivered'),('final','accept')]:
            aid=self.rt.task(successor,tid)['latest'];self.assertIsNotNone(aid);self.factory.finish(aid,decision=decision)
            if tid=='deck':self.factory.sessions[aid]['status']['operation']=dict(outcome='completed')
            self.rt.tick(successor)
        self.assertEqual(self.rt.status(successor)['status'],'completed')
        self.assertEqual(history,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(run,))])
        for tid in ('review','final'):
            self.assertTrue(any(i.get('artifact')==evidence['feedback'][0]['artifact'] for i in self.rt.spec(self.rt.task(successor,tid))['inputs']))

    def test_derived_revision_refuses_uncertain_native_effect(self):
        from task_relay import registered_revision
        run,baseline,_=self.derived_revision()
        aid=self.rt.task(run,'deck')['latest']
        with transaction(self.state.db):
            r=json.loads(self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(aid,)).fetchone()[0]);r['pending_requests']=['uncertain']
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded(r),aid))
        self.assertIsNone(registered_revision.proof(self.rt,baseline))

    def test_disabled_legacy_grant_restores_only_proved_original_scope(self):
        self.correct();aid=self.rt.task('layout','produce')['latest'];self.factory.finish(aid)
        self.factory.sessions[aid]['status']['operation']=dict(outcome='completed')
        self.rt.tick('layout',dispatch=False);self.bind_owner()
        with transaction(self.state.db):self.state.put('production-enabled:layout',False)
        calls=list(self.factory.calls);before=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        pc.reconcile_native_layout(self.state,self.rt)
        self.assertEqual(self.state.get('production-enabled:layout'),self.initial)
        self.assertEqual(self.factory.calls,calls);self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')],before)
        pc.reconcile_native_layout(self.state,self.rt)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_events WHERE kind='native_correction_scheduling_resumed'").fetchone()[0],1)

    def test_unrelated_parameter_change_and_missing_receipt_do_not_normalize(self):
        self.correct();task=self.rt.task('layout','produce');spec=self.rt.spec(task)
        spec['execution']['parameters']['title']='Unapproved new title'
        with self.rt.transaction():
            aid=self.rt.new_assignment('layout',spec);self.rt.db.execute("UPDATE production_tasks SET assignment=? WHERE run='layout' AND id='produce'",(aid,))
        self.assertNotEqual(pc.runtime_digest(self.rt,'layout'),self.initial)
        spec['execution']['parameters']['title']='Synthetic layout'
        with self.rt.transaction():
            aid=self.rt.new_assignment('layout',spec);self.rt.db.execute("UPDATE production_tasks SET assignment=? WHERE run='layout' AND id='produce'",(aid,))
            self.rt.db.execute("DELETE FROM production_events WHERE kind='native_sourcing_correction_scheduled'")
        self.assertNotEqual(pc.runtime_digest(self.rt,'layout'),self.initial)

    def test_human_control_keeps_disabled_grant_held(self):
        self.correct();aid=self.rt.task('layout','produce')['latest'];self.factory.finish(aid)
        self.factory.sessions[aid]['status']['operation']=dict(outcome='completed');self.rt.tick('layout',dispatch=False);self.bind_owner()
        with transaction(self.state.db):
            self.state.put('production-enabled:layout',False);self.state.put('production-control-epoch:layout',1)
        pc.reconcile_native_layout(self.state,self.rt);self.assertFalse(self.state.get('production-enabled:layout'))

if __name__=='__main__':unittest.main()
