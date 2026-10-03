"""Controlled local jobs: exact review, atomic receipts and no remote delivery."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from task_relay.bridge import State, Bridge, process_desktop, service_transport, service_config, BridgeError
from task_relay.relay_paths import Paths
from task_relay import desktop_workspace as workspace, desktop_plans, production_control as pc, relay_channels
from orchestrator.runtime import Runtime
from tests.test_orchestrator import pair, FakeFactory


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.paths = Paths(self.root/'app',self.root/'data',self.root/'workspaces',self.root/'generated')
        self.state = State(self.paths.state); self.addCleanup(self.state.db.close)
        self.factory = FakeFactory()
        self.rt = Runtime(pc.root(self.state), factory=self.factory, connection=self.state.db)
        self.rt.create(pair(gate='Select exact text', max_attempts=1))
        with self.state.db:
            relay_channels.bind(self.state,'production','demo','desktop')
            self.state.put('production-enabled:demo',pc.runtime_digest(self.rt,'demo'))
            self.state.put('health:desktop-plans',{'interface_version':1,'last_success':time.time()})
            self.state.put('production-planner-policy',{'backend':pair()['backend']})

    def ready(self):
        for _ in range(20):
            self.rt.tick('demo')
            running=[a for a in self.state.db.execute("SELECT id,state FROM production_attempts WHERE run='demo' AND state='running'")]
            for row in running:
                self.factory.finish(row['id'],decision='accept' if self.state.db.execute('SELECT task FROM production_attempts WHERE id=?',(row['id'],)).fetchone()[0]=='review' else 'delivered')
            if self.rt.task('demo','produce')['status']=='awaiting_user': break
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        return workspace.detail('demo',self.paths)

    def choose(self,view,request_id=None,note='  I select this exact text.\n'):
        return workspace.decide('demo','select',view['review_digest'],request_id or str(uuid.uuid4()),view['selection_groups'][0]['id'],note,self.paths)

    def test_local_selection_needs_no_messenger_delivery_and_lost_reply_cannot_duplicate_it(self):
        view=self.ready();self.assertTrue(view['selection_groups']);ident=str(uuid.uuid4())
        self.choose(view,ident);self.choose(view,ident)
        decisions=self.state.db.execute('SELECT * FROM production_decisions').fetchall()
        self.assertEqual(len(decisions),1);self.assertEqual(decisions[0]['note'],'  I select this exact text.\n')
        self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(workspace.jobs(paths=self.paths)['items'][0]['status'],'completed')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_workspace_commands').fetchone()[0],1)
        notice=self.state.db.execute("SELECT id FROM outbox WHERE id LIKE 'production:demo:desktop-action:%'").fetchone()[0]
        self.assertEqual(relay_channels.event_channel(self.state,notice),'desktop')
        self.assertIsNone(self.state.get('chat_id'))
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'different decision'):
            self.choose(view,ident,note='Different note')

    def test_stale_selection_and_changed_blob_never_accept_outputs(self):
        view=self.ready()
        with self.state.db:self.state.put('production-control-epoch:demo',1)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed'):self.choose(view)
        current=workspace.detail('demo',self.paths)
        artifact=current['selection_groups'][0]['members'][0]['id']
        blob=Path(workspace.artifact_path(artifact,self.paths)['path']);blob.chmod(0o600);blob.write_text('changed fixture')
        with self.assertRaisesRegex(ValueError,'changed'):self.choose(current)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_workspace_commands').fetchone()[0],0)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed'):workspace.artifact_path(artifact,self.paths)

    def test_shared_job_selection_and_cancel_keep_delivery_ownership(self):
        with self.state.db:
            self.state.db.execute("UPDATE relay_channel_bindings SET channel='messages' WHERE entity='demo'")
        view=self.ready()
        self.assertFalse(view['local']);self.assertTrue(view['controllable'])
        self.assertTrue(view['selection_groups'])
        self.choose(view)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],1)
        self.assertEqual(workspace.detail('demo',self.paths)['channel'],'messages')
        self.assertEqual(len(self.factory.calls),2)

    def test_cancel_remove_and_restore_shared_job_retain_records_and_deduplicate(self):
        with self.state.db:
            self.state.db.execute("UPDATE relay_channel_bindings SET channel='telegram' WHERE entity='demo'")
        view=workspace.detail('demo',self.paths)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'no longer available'):
            workspace.decide('demo','archive',view['review_digest'],str(uuid.uuid4()),paths=self.paths)
        workspace.decide('demo','cancel',view['review_digest'],str(uuid.uuid4()),paths=self.paths)
        current=workspace.detail('demo',self.paths);ident=str(uuid.uuid4())
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed'):
            workspace.decide('demo','archive',view['review_digest'],ident,paths=self.paths)
        first=workspace.decide('demo','archive',current['review_digest'],ident,paths=self.paths)
        self.assertEqual(workspace.decide('demo','archive',current['review_digest'],ident,paths=self.paths),first)
        self.assertEqual(workspace.jobs(paths=self.paths)['total'],0)
        removed=workspace.jobs(paths=self.paths,include_archived=True)['items'][0]
        self.assertTrue(removed['archived'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        current=workspace.detail('demo',self.paths)
        workspace.decide('demo','restore',current['review_digest'],str(uuid.uuid4()),paths=self.paths)
        self.assertEqual(workspace.jobs(paths=self.paths)['total'],1)
        self.assertEqual(workspace.detail('demo',self.paths)['channel'],'telegram')
        self.assertEqual(self.factory.calls,[])

    def test_cancelled_job_with_unresolved_attempt_cannot_be_removed(self):
        self.rt.tick('demo')
        view=workspace.detail('demo',self.paths)
        workspace.decide('demo','cancel',view['review_digest'],str(uuid.uuid4()),paths=self.paths)
        current=workspace.detail('demo',self.paths)
        self.assertNotIn('archive',current['controls'])
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'no longer available'):
            workspace.decide('demo','archive',current['review_digest'],str(uuid.uuid4()),paths=self.paths)
        self.assertEqual(workspace.jobs(paths=self.paths)['total'],1)

    def test_workflow_stage_can_be_cancelled_but_not_resumed_before_target_updates(self):
        with self.state.db:
            self.state.db.execute("""INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,token,expires,created,run)
                VALUES ('owned-plan',999,'desktop','Exact stage','{}','{}','hash','test','test','started','token',0,0,'demo')""")
            self.state.db.execute("INSERT INTO relay_pipeline_steps (pipeline,position,id,status,target_kind,target) VALUES ('pipeline',0,'stage','running','plan_production','owned-plan')")
        view=workspace.detail('demo',self.paths)
        self.assertFalse(view['controllable']);self.assertIn('workflow',view['control_error'])
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'workflow'):
            workspace.decide('demo','resume',view['review_digest'],str(uuid.uuid4()),paths=self.paths)
        workspace.decide('demo','cancel',view['review_digest'],str(uuid.uuid4()),paths=self.paths)
        self.assertEqual(self.rt.status('demo')['status'],'cancelled')
        self.assertEqual(self.state.db.execute('SELECT target FROM relay_pipeline_steps').fetchone()[0],'owned-plan')
        current=workspace.detail('demo',self.paths)
        workspace.decide('demo','archive',current['review_digest'],str(uuid.uuid4()),paths=self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipeline_steps').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def test_inspection_does_not_initialize_or_dispatch_a_runtime(self):
        with patch('orchestrator.storage.initialize',side_effect=AssertionError('Inspection tried migration')):
            view=workspace.detail('demo',self.paths)
        self.assertEqual(view['name'],'demo');self.assertEqual(self.factory.calls,[])

    def test_workflow_keeps_frozen_inputs_separate_from_changed_planned_inputs(self):
        view = self.ready()
        reviewer = next(t for t in view['tasks'] if t['id'] == 'review')
        source = reviewer['recorded_inputs'][0]
        self.assertEqual(source['file']['id'], source['artifact'])
        self.assertEqual(source['file']['sha256'], source['sha256'])
        assignment = self.state.db.execute("SELECT a.id,a.spec FROM production_assignments a JOIN production_tasks t ON t.assignment=a.id WHERE t.run='demo' AND t.id='review'").fetchone()
        spec = json.loads(assignment['spec'])
        spec['inputs'][0]['purpose'] = 'Changed planned context'
        with self.state.db:
            self.state.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),assignment['id']))
        calls = len(self.factory.calls)
        current = workspace.detail('demo', self.paths)
        reviewer = next(t for t in current['tasks'] if t['id'] == 'review')
        self.assertEqual(reviewer['recorded_inputs'][0], source)
        self.assertEqual(reviewer['planned_inputs'][0]['purpose'], 'Changed planned context')
        self.assertEqual(reviewer['backend'], pair()['backend'])
        self.assertEqual(len(self.factory.calls), calls)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0], 0)

    def test_workflow_does_not_link_a_frozen_input_to_a_different_registered_version(self):
        view = self.ready()
        reviewer = next(t for t in view['tasks'] if t['id'] == 'review')
        original = reviewer['recorded_inputs'][0]
        with self.state.db:
            self.state.db.execute('UPDATE production_artifacts SET sha256=? WHERE id=?',('f'*64,original['artifact']))
        current = workspace.detail('demo', self.paths)
        source = next(t for t in current['tasks'] if t['id'] == 'review')['recorded_inputs'][0]
        self.assertIsNone(source['file'])
        self.assertEqual(source['sha256'], original['sha256'])

    def test_pause_and_resume_keep_current_authorization_and_deduplicate_receipt(self):
        view=workspace.detail('demo',self.paths);ident=str(uuid.uuid4())
        workspace.decide('demo','pause',view['review_digest'],ident,paths=self.paths)
        workspace.decide('demo','pause',view['review_digest'],ident,paths=self.paths)
        paused=workspace.detail('demo',self.paths);self.assertEqual(paused['status'],'paused')
        workspace.decide('demo','resume',paused['review_digest'],str(uuid.uuid4()),paths=self.paths)
        self.assertEqual(self.rt.status('demo')['status'],'active');self.assertEqual(len(self.factory.calls),0)
        self.assertEqual(self.state.get('production-enabled:demo'),pc.runtime_digest(self.rt,'demo'))

    def test_attachments_and_exact_text_survive_original_change_and_retry(self):
        source=self.root/'source.md';source.write_text('Original source')
        ident=str(uuid.uuid4());goal='  Write a brief.\n';constraints=' Keep its meaning.  '
        desktop_plans.create(goal,constraints,None,None,ident,self.paths,files=[str(source)])
        row=self.state.db.execute('SELECT * FROM desktop_plan_inputs').fetchone();manifest=json.loads(row['manifest'])
        source.write_text('Changed original')
        desktop_plans.create(goal,constraints,None,None,ident,self.paths,files=[str(source)])
        self.assertEqual(Path(manifest[0]['path']).read_text(),'Original source')
        self.assertEqual(row['goal'],goal);self.assertEqual(row['constraints_text'],constraints)
        from orchestrator.worker_capabilities import entry
        with patch('task_relay.orchestrator_chat.provider',return_value=('openai','fixture-model')),patch('orchestrator.executors.available'),patch('orchestrator.worker_capabilities.capture',return_value=[entry(pair()['backend'])]):
            desktop_plans.process_requests(self.state)
        receipt=self.state.db.execute('SELECT status,result FROM desktop_plan_requests').fetchone()
        self.assertEqual(receipt['status'],'accepted',receipt['result'])
        payload=json.loads(self.state.db.execute('SELECT context FROM production_plans').fetchone()[0])
        self.assertTrue(any(s['sha256']==manifest[0]['sha256'] and s['bytes']==manifest[0]['bytes'] for s in payload['sources']))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],1)
        self.assertEqual(workspace.request_detail(ident,self.paths)['prompt'],goal+'\n\nConstraints and boundaries:\n'+constraints)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'different files'):
            desktop_plans.create(goal,constraints,None,None,ident,self.paths,files=[])

    def test_local_worker_does_not_need_or_poll_a_messenger(self):
        transport=service_transport({'token':None},None,lambda *_:self.fail('Remote transport constructed'))
        with self.assertRaises(BridgeError):transport.call('getUpdates')
        bridge=Bridge(self.state,transport,{'token':None})
        with patch('task_relay.desktop_tasks.process_commands') as tasks,patch('task_relay.desktop_plans.process_requests') as plans:
            process_desktop(bridge)
            tasks.assert_called_once_with(bridge);plans.assert_called_once_with(self.state)
        with patch('task_relay.bridge.DATA',self.root/'no-config'),patch('task_relay.bridge.read_config',side_effect=AssertionError('Remote credential read')):
            self.assertIsNone(service_config()['token'])

    def test_next_stage_carries_exact_selected_versions_and_waits_for_its_own_start(self):
        view=self.ready();self.choose(view)
        request=str(uuid.uuid4())
        desktop_plans.create('  Add a short conclusion.\n','Keep the selected text.',None,None,request,self.paths,previous_run='demo')
        from orchestrator.worker_capabilities import entry
        with patch('task_relay.orchestrator_chat.provider',return_value=('openai','fixture-model')),patch('orchestrator.executors.available'),patch('orchestrator.worker_capabilities.capture',return_value=[entry(pair()['backend'])]):
            desktop_plans.process_requests(self.state)
        receipt=self.state.db.execute('SELECT status,result FROM desktop_plan_requests WHERE request_id=?',(request,)).fetchone()
        self.assertEqual(receipt['status'],'accepted',receipt['result'])
        row=self.state.db.execute('SELECT * FROM production_plans').fetchone()
        self.assertEqual(row['channel'],'desktop');self.assertTrue(json.loads(row['options'])['planning_only'])
        payload=json.loads(row['context']);selected=view['selection_groups'][0]['members'][0]
        self.assertTrue(any(s['artifact']==selected['id'] and s['sha256']==selected['sha256'] for s in payload['sources']))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(len(self.factory.calls),2)


if __name__=='__main__':unittest.main()
