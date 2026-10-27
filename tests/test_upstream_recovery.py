"""Consumer-defect/source-port recovery with tiny text/JSON artifacts."""
import json
import unittest
from unittest.mock import patch
from orchestrator.storage import transaction
from task_relay import upstream_recovery as upstream,completion_recovery as recovery,pipelines as pipe
from task_relay.relay_channels import ScopedState
from tests import test_delivery_completion as fixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    stage=fixtures.Tests.stage
    step=fixtures.Tests.step
    answer=fixtures.Tests.answer
    response=fixtures.Tests.response
    action=fixtures.Tests.action
    create=fixtures.Tests.create
    complete_stage=fixtures.Tests.complete_stage

    def prepare(self,empty=True,intermediate=False,code='missing_substantive_source'):
        action=self.action();action['stages'][0]['handoff']['outputs']['outline']['media_type']='application/json'
        source=self.stage('catalog',route='production');source['handoff']['outputs']['catalog']['media_type']='application/json'
        source['handoff']['inputs']=[dict(stage='outline',deliverable='outline',media_type='application/json',consumer='context')]
        action['stages'].insert(1,source)
        action['stages'][-1]['handoff']['inputs']=[dict(stage=i,deliverable=i,media_type='application/json',consumer='context') for i in ('outline','catalog')]
        action['completion']['coverage']=dict(inventory=dict(stage='outline',output='outline'),catalog=dict(stage='catalog',output='catalog'),options_per_item=3,count_policy='target')
        if intermediate:
            photos=self.stage('photos',route='production');photos['handoff']['inputs']=[dict(stage='catalog',deliverable='catalog',media_type='application/json',consumer='context')]
            action['stages'].insert(2,photos)
            action['stages'][-1]['handoff']['inputs'].append(dict(stage='photos',deliverable='photos',media_type='text/plain',consumer='context'))
        p=self.create(action=action)
        self.complete_stage(p,'outline',body=dict(items=[dict(id='F01'),dict(id='F02')]))
        options=[dict(product_url='https://store.example/existing')]
        self.source_run,_,_=self.complete_stage(p,'catalog',body=dict(items=[dict(id='F01',options=options),dict(id='F02',options=[] if empty else [dict(product_url='https://store.example/two')])]))
        if intermediate:self.complete_stage(p,'photos')
        self.consumer_run,_,review=self.complete_stage(p,'finish')
        # Script a finished consumer verdict, rather than invoking any model.
        result=dict(assignment_id=review,decision='revise',findings=[dict(category='requirements',code=code,message='A consumer lacks required content',evidence='Frozen source has an unresolved item')],instruction='Recover source evidence',checks=[],summary='Synthetic consumer finding')
        with transaction(self.state.db):
            self.rt.event(self.consumer_run,'review',review,'checks_recorded',dict(kind='model_review',result=result))
            self.state.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id='produce'",(self.consumer_run,))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='finish'",(p['id'],))
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
        return p,review

    def test_confirmed_consumer_gap_replans_only_source_and_preserves_versions(self):
        p,review=self.prepare(intermediate=True);prior=[dict(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(p['id'],))]
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')];calls=list(self.factory.calls)
        upstream.reconcile(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()[0],'active')
        catalog=self.step(p,'catalog');self.assertEqual(catalog['status'],'running');self.assertEqual(catalog['target_kind'],'plan_production')
        self.assertEqual(self.step(p,'outline')['result'],prior[0]['result']);self.assertEqual(self.step(p,'finish')['status'],'pending')
        self.assertEqual(self.step(p,'photos')['status'],'pending')
        receipt=self.state.db.execute('SELECT * FROM completion_recoveries WHERE parent=?',(self.source_run,)).fetchone()
        gap=json.loads(receipt['baseline'])['gaps'][0]
        self.assertEqual(gap['kind'],'consumer_coverage');self.assertEqual(gap['missing'],[dict(item='F02',option=1)])
        self.assertEqual(gap['consumer_review']['attempt'],review)
        archive=self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND kind='upstream_coverage_recovery'",(p['id'],)).fetchone()
        self.assertEqual(json.loads(archive[0])['prior_stages'],prior[1:])
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')],before);self.assertEqual(self.factory.calls,calls)
        upstream.reconcile(self.state);self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)

    def test_declined_source_admission_rolls_back_archive_and_state(self):
        p,_=self.prepare();before=[tuple(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps')]
        with patch.object(recovery,'begin',return_value=False):upstream.reconcile(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()[0],'blocked')
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps')],before)
        self.assertFalse(self.state.db.execute("SELECT 1 FROM production_events WHERE kind='delivery_consumer_coverage_gap'").fetchone())

    def test_target_shortfall_with_every_item_sourced_does_not_trigger_rewind(self):
        p,_=self.prepare(empty=False);upstream.reconcile(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)
        self.assertEqual(self.step(p,'finish')['status'],'blocked')

    def test_content_defect_does_not_research_unrelated_missing_targets(self):
        p,_=self.prepare(code='incorrect_specification');before=[tuple(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps')]
        upstream.reconcile(self.state)
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps')],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)

    def test_unexecuted_misdirected_recovery_restores_archived_stages_and_retains_cycle(self):
        p,_=self.prepare(intermediate=True,code='incorrect_specification')
        prior=[dict(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(p['id'],))]
        attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        with patch.object(upstream,'coverage_findings',return_value=True):upstream.reconcile(self.state)
        source=self.step(p,'catalog');plan=source['target']
        with transaction(self.state.db):
            self.state.db.execute("UPDATE production_plans SET status='blocked',error='Synthetic received proposal rejection' WHERE id=?",(plan,))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='catalog'",(p['id'],))
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
        upstream.reconcile(self.state)
        self.assertEqual([dict(r) for r in self.state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position',(p['id'],))],prior)
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')],attempts)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_plans WHERE id=?',(plan,)).fetchone()[0],'blocked')
        upstream.reconcile(self.state)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='inapplicable_upstream_recovery_restored'").fetchone()[0],1)

    def test_human_control_or_stale_candidate_keeps_original_hold(self):
        p,_=self.prepare()
        with transaction(self.state.db):ScopedState(self.state,'desktop').put('production-control-epoch:'+self.consumer_run,1)
        upstream.reconcile(self.state);self.assertEqual(self.step(p,'finish')['status'],'blocked')
        with transaction(self.state.db):
            ScopedState(self.state,'desktop').put('production-control-epoch:'+self.consumer_run,0)
            self.state.db.execute("UPDATE production_tasks SET latest='new-candidate' WHERE run=? AND id='produce'",(self.consumer_run,))
        upstream.reconcile(self.state);self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)

    def test_exhausted_original_source_cycles_roll_back_without_new_grant(self):
        p,_=self.prepare()
        with transaction(self.state.db):
            for cycle in range(1,5):self.state.db.execute('INSERT INTO completion_recoveries VALUES (?,?,?,?,?,?)',(p['id'],'catalog','old-'+str(cycle),cycle,200+cycle,'{}'))
        upstream.reconcile(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],4)
        self.assertEqual(self.step(p,'catalog')['status'],'completed');self.assertEqual(self.step(p,'finish')['status'],'blocked')
        self.assertFalse(self.state.db.execute("SELECT 1 FROM production_events WHERE kind='delivery_consumer_coverage_gap'").fetchone())


if __name__=='__main__':unittest.main()
