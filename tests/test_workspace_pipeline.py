"""Parent job projection, real recovery lineage and exact deletion; text only."""
import json
import unittest
from task_relay import desktop_workspace as workspace, job_delete, pipeline_lineage, workflow_usage
from tests import test_desktop_workspace as fixtures
from tests.test_orchestrator import pair

PID='pipe-'+'c'*24


class Tests(unittest.TestCase):
    setUp=fixtures.WorkspaceTests.setUp

    def parent(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO relay_pipelines VALUES (?,1,'Exact user objective','One parent job','{}','desktop','fixture','fixture','active',10)",(PID,))
            self.state.db.execute("""INSERT INTO production_plans(id,request_id,channel,request,options,context,context_hash,provider,model,status,token,expires,created,run)
                VALUES ('original-plan',2,'desktop','Original stage','{}','{}','hash','fixture','fixture','started','token',0,11,'demo')""")
            self.state.db.execute("INSERT INTO relay_pipeline_steps(pipeline,position,id,status,request_id,target_kind,target) VALUES (?,0,'write','running',2,'plan_production','original-plan')",(PID,))
            self.state.db.execute("INSERT INTO relay_pipeline_steps(pipeline,position,id,status) VALUES (?,1,'deliver','pending')",(PID,))
            self.state.db.execute("INSERT INTO relay_pipeline_requests VALUES (2,?,'write','{}')",(PID,))

    def recovered(self):
        self.parent()
        value=pair(max_attempts=1);value['id']='successor';self.rt.create(value)
        self.rt.tick('successor')
        self.factory.finish(self.rt.task('successor','produce')['latest']);self.rt.tick('successor')
        self.factory.finish(self.rt.task('successor','review')['latest'],decision='accept');self.rt.tick('successor')
        with self.state.db:
            self.state.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='demo'")
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target='successor',status='completed',request_id=3 WHERE pipeline=? AND id='write'",(PID,))
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='skipped' WHERE pipeline=? AND id='deliver'",(PID,))
            self.state.db.execute("UPDATE relay_pipelines SET status='completed' WHERE id=?",(PID,))
            self.state.db.execute("INSERT INTO completion_recovery_grants VALUES (?,'Original authorization','{}')",(PID,))
            self.state.db.execute("INSERT INTO completion_recoveries VALUES (?,'write','demo',1,3,'{}')",(PID,))
            self.state.db.execute("INSERT INTO relay_pipeline_events(pipeline,step,kind,detail,created) VALUES (?,'write','registered_revision_queued',?,12)",(PID,json.dumps(dict(parent='demo',successor='successor'))))
            self.state.db.execute("INSERT INTO relay_pipeline_events(pipeline,kind,detail,created) VALUES (?,'completed','{}',13)",(PID,))

    def test_graph_reuses_exact_execution_and_does_not_invent_pending_nodes(self):
        self.parent()
        before=self.state.db.total_changes;calls=list(self.factory.calls)
        view=workspace.pipeline_detail(PID,self.paths)
        graph=view['stages'][0]['execution']
        self.assertEqual(graph['name'],'demo')
        self.assertEqual([t['id'] for t in graph['tasks']],['produce','review'])
        self.assertEqual(graph['tasks'][1]['planned_inputs'],workspace.detail('demo',self.paths)['tasks'][1]['planned_inputs'])
        self.assertIsNone(view['stages'][1]['execution'])
        self.assertEqual(self.state.db.total_changes,before)
        self.assertEqual(self.factory.calls,calls)

    def test_durable_hold_explanation_tracks_exact_owner_and_clears_on_successor(self):
        from task_relay import workflow_state
        self.parent()
        with self.state.db:
            p=self.state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(PID,)).fetchone()
            s=self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id='write'",(PID,)).fetchone()
            self.state.db.execute('BEGIN IMMEDIATE')
            workflow_state.decision(self.state,p,s,'capacity_exhausted','Whole review needs more than its saved allowance.','partition_or_review_authorization')
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='write'",(PID,))
            workflow_state.refresh(self.state,PID)
        view=workspace.pipeline_detail(PID,self.paths)
        self.assertEqual(view['stages'][0]['lifecycle']['phase'],'held')
        self.assertIn('Whole review',view['stages'][0]['lifecycle']['reason'])
        with self.state.db:self.state.db.execute("UPDATE relay_pipeline_steps SET target='different' WHERE pipeline=? AND id='write'",(PID,))
        self.assertIsNone(workspace.pipeline_detail(PID,self.paths)['stages'][0]['lifecycle'])

    def test_parent_replaces_old_blocked_plans_and_successors_in_jobs_and_review(self):
        self.recovered()
        before=self.state.db.total_changes;calls=list(self.factory.calls)
        result=workspace.jobs(paths=self.paths)
        self.assertEqual([(r['kind'],r['id'],r['status']) for r in result['items']],[('pipeline',PID,'completed')])
        self.assertEqual(result['review_total'],0)
        self.assertEqual(result['review_items'],[])
        self.assertEqual(self.state.db.total_changes,before);self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')

    def test_detail_distinguishes_created_reviewers_from_planned_tasks(self):
        self.parent()
        with self.state.db:
            self.state.db.execute("UPDATE relay_pipeline_steps SET result='Saved native result' WHERE pipeline=? AND id='deliver'",(PID,))
        view=workspace.pipeline_detail(PID,self.paths)
        self.assertEqual(view['stats']['workers_created'],0)
        self.assertEqual(view['stats']['reviewers_created'],0)
        self.assertEqual(view['stages'][0]['tasks'][1]['review_of'],'produce')
        self.assertEqual(view['stages'][1]['tasks'],[])
        self.rt.tick('demo')
        view=workspace.pipeline_detail(PID,self.paths)
        self.assertEqual(view['stats']['workers_created'],1)
        self.assertEqual(view['stats']['running'],1)
        self.assertEqual(view['stats']['reviewers_created'],0)

    def test_recovery_history_stats_and_accounting_share_membership(self):
        self.recovered()
        view=workspace.pipeline_detail(PID,self.paths)
        self.assertEqual(view['stats']['workers_created'],2)
        self.assertEqual(view['stats']['reviewers_created'],1)
        self.assertEqual(view['stats']['tasks_completed'],2)
        self.assertEqual(view['stats']['running'],0)
        self.assertEqual(view['stats']['runs'],2)
        self.assertEqual({r['id'] for r in view['runs'] if not r['current']},{'demo'})
        self.assertEqual(set(view['usage']['runs']),pipeline_lineage.collect(self.state.db,PID)['runs'])
        self.assertGreater(view['usage']['totals']['total_tokens']['unknown_records'],0)
        self.assertEqual(view['usage']['finished_at'],13)

    def test_activity_uses_receipts_and_reports_stale_controller(self):
        self.parent();self.rt.tick('demo')
        view=workspace.pipeline_detail(PID,self.paths)
        self.assertEqual([a['task'] for a in view['activity']['attempts']],['produce'])
        self.assertTrue(view['activity']['attempts'][0]['current'])
        self.assertFalse(view['activity']['controller_fresh'])
        self.assertEqual(self.factory.calls.__len__(),1)
        with self.state.db:
            self.state.db.execute("UPDATE relay_pipeline_steps SET target=NULL,target_kind=NULL WHERE pipeline=? AND id='write'",(PID,))
        view=workspace.pipeline_detail(PID,self.paths)
        self.assertEqual(len(view['activity']['attempts']),1)
        self.assertFalse(view['activity']['attempts'][0]['current'],'An older live worker must not disappear when the stage head changes')

    def test_registered_connector_does_not_display_the_default_agent_model(self):
        self.parent()
        row=self.state.db.execute("SELECT a.id,a.spec FROM production_assignments a JOIN production_tasks t ON t.assignment=a.id WHERE t.run='demo' AND t.id='produce'").fetchone()
        spec=json.loads(row['spec']);spec['execution']=dict(capability='text.bundle',version=1,parameters={})
        with self.state.db:self.state.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),row['id']))
        view=workspace.pipeline_detail(PID,self.paths)
        connector=view['stages'][0]['tasks'][0]
        self.assertEqual(connector['operation'],'text.bundle')
        self.assertNotIn('model',connector['backend'])
        self.assertEqual(connector['backend']['type'],'Registered procedure')
        self.assertEqual(self.factory.calls,[])

    def test_review_count_includes_jobs_outside_first_page(self):
        with self.state.db:
            for i in range(45):
                self.state.db.execute("INSERT INTO relay_pipelines VALUES (?,?,?,?,'{}','desktop','fixture','fixture',?,?)",
                    ('pipe-'+format(i,'024x'),i+100,'Exact','Parent '+str(i),'blocked' if i==0 else 'completed',i+20))
        result=workspace.jobs(paths=self.paths)
        self.assertEqual(result['review_total'],1)
        self.assertEqual(len(result['review_items']),1)
        self.assertNotIn(result['review_items'][0]['id'],{i['id'] for i in result['items']})

    def test_delete_preview_contains_prior_runs_and_recovery_receipts(self):
        self.recovered()
        with self.state.db:
            self.state.db.execute("INSERT INTO desktop_plan_requests VALUES ('original-intake',1,'Exact user objective',NULL,NULL,'handled',NULL,1)")
        review=job_delete.preview(PID,self.paths)
        self.assertEqual(set(review['runs']),{'demo','successor'})
        self.assertEqual(review['counts']['completion_recoveries'],1)
        self.assertEqual(review['counts']['completion_recovery_grants'],1)
        self.assertEqual(review['blockers'],[])
        result=job_delete.delete(PID,review['digest'],self.paths)
        self.assertEqual(result['status'],'complete')
        for table in ('production_runs','production_attempts','completion_recoveries','completion_recovery_grants'):
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(workspace.jobs(paths=self.paths)['items'],[])
        self.assertEqual(self.state.db.execute("SELECT status FROM desktop_plan_requests WHERE request_id='original-intake'").fetchone()[0],'deleted')

    def test_delete_refuses_shared_recovery_and_uncertain_attempts(self):
        self.recovered()
        with self.state.db:
            self.state.db.execute("INSERT INTO completion_recoveries VALUES ('foreign','write','demo',1,4,'different')")
            self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE task='review'")
        review=job_delete.preview(PID,self.paths)
        self.assertIn('Another pipeline uses this recovery history.',review['blockers'])
        self.assertIn('A worker is running, stopping or has an uncertain outcome.',review['blockers'])
        with self.assertRaises(job_delete.JobDeleteError):job_delete.delete(PID,review['digest'],self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)
