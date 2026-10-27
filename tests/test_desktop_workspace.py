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

    def test_image_preview_is_exact_read_only_and_bounded(self):
        import base64
        import hashlib
        pixels = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6a3sAAAAASUVORK5CYII=')
        blob = pc.root(self.state)/'artifacts'/'preview-fixture'
        blob.parent.mkdir(parents=True, exist_ok=True); blob.write_bytes(pixels)
        sha = hashlib.sha256(pixels).hexdigest()
        with self.state.db:
            self.state.db.execute('INSERT INTO production_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
                ('preview','demo','produce',None,'image.png',str(blob),sha,len(pixels),'Image',str(blob)))
        before = list(self.state.db.iterdump())
        with patch('task_relay.workflow_files.sync', side_effect=AssertionError('Preview must not publish')):
            value = workspace.artifact_preview('preview',sha,self.paths)
        self.assertEqual(base64.b64decode(value['data_url'].split(',')[1]),pixels)
        self.assertEqual(list(self.state.db.iterdump()),before)
        with self.assertRaisesRegex(workspace.DesktopPlanError,'unavailable'):
            workspace.artifact_preview('preview','0'*64,self.paths)
        blob.write_bytes(pixels[:-1]+b'!')
        with self.assertRaisesRegex(workspace.DesktopPlanError,'changed'):
            workspace.artifact_preview('preview',sha,self.paths)
        with self.state.db:
            self.state.db.execute('UPDATE production_artifacts SET bytes=? WHERE id=?',(8*1024*1024+1,'preview'))
        with self.assertRaisesRegex(workspace.DesktopPlanError,'8 MB'):
            workspace.artifact_preview('preview',sha,self.paths)
        # Display representation fits the unchanged bridge; saved bytes do not change.
        import io, random
        from PIL import Image
        image=Image.frombytes('RGB',(500,500),random.Random(1).randbytes(500*500*3))
        buffer=io.BytesIO(); image.save(buffer,format='PNG'); original=buffer.getvalue()
        self.assertGreater(len(original),650000)
        sha=hashlib.sha256(original).hexdigest();blob.write_bytes(original)
        with self.state.db:
            self.state.db.execute('UPDATE production_artifacts SET sha256=?,bytes=? WHERE id=?',(sha,len(original),'preview'))
        preview=workspace.artifact_preview('preview',sha,self.paths)
        self.assertLess(len(json.dumps(preview)),1000000)
        self.assertEqual(blob.read_bytes(),original)
        self.assertEqual(preview['sha256'],sha)
        self.assertEqual(preview['transformation'],'display-sized preview; original unchanged')

    def test_scheduled_owner_uses_existing_service_and_desktop_channel(self):
        from task_relay import persistent_jobs
        from orchestrator import worker_capabilities
        from tests.test_job_owner_loop import BACKEND
        grant=dict(workers=[worker_capabilities.entry(BACKEND)],operations=[],deliverables={'report':'text/plain'},max_tasks=8,
            task_limits=dict(seconds=300,tool_calls=12,provider_requests=12,response_tokens=4096,output_bytes=200000),task_attempts=2,owner_turns=6)
        run=persistent_jobs.start(self.state,dict(ident='owned',request='Exact full request',backend=BACKEND,inputs=[],grant=grant))
        self.assertEqual(self.state.get('production-enabled:'+run),pc.runtime_digest(self.rt,run))
        from task_relay.result_handoff import channel_for
        self.assertEqual(channel_for(self.state,run),'desktop')
        worker=pc.Worker(self.state,runtime_factory=lambda root:self.rt)
        with patch.object(worker,'next_run',return_value=run):worker.tick();worker.tick()
        self.assertEqual(self.rt.task(run,'owner')['status'],'running')
        # Frequent activity in watched chats must not push real Relay jobs off
        # the first page, leaving no visible owner progress.
        with self.state.db:
            self.state.db.executemany('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                [(f'chat-{n}','fixture',0,'Watched chat','running',int(time.time())+100) for n in range(45)])
        view=next(i for i in workspace.jobs(paths=self.paths)['items'] if i['run']==run)
        self.assertEqual(view['status'],'active')
        self.assertEqual(workspace.jobs(paths=self.paths)['items'][0]['run'],run)
        self.assertEqual(len([x for x in self.factory.sessions.values() if x['frozen']['run']==run]),1)

    def test_owner_admission_between_status_read_and_grant_read_does_not_disable_dispatch(self):
        from task_relay import persistent_jobs
        from orchestrator import worker_capabilities,executors,contracts as c
        from orchestrator.gemini_worker import execute
        from orchestrator.workers import atomic
        from tests.test_job_owner_loop import BACKEND
        from tests.test_operation_session import Script,CONFIG
        grant=dict(workers=[worker_capabilities.entry(BACKEND)],operations=[],deliverables={'report':'text/plain'},max_tasks=8,
            task_limits=dict(seconds=300,tool_calls=12,provider_requests=12,response_tokens=4096,output_bytes=200000),task_attempts=2,owner_turns=6)
        run=persistent_jobs.start(self.state,dict(ident='concurrent-owner',request='Write a report',backend=BACKEND,inputs=[],grant=grant))
        worker=pc.Worker(self.state,runtime_factory=lambda root:self.rt)
        with patch.object(worker,'next_run',return_value=run):worker.tick()
        real_inspect=pc.inspect;committed=[]
        def interleave(*args,**kwargs):
            snapshot=real_inspect(*args,**kwargs)
            if not committed:
                aid=self.rt.task(run,'owner')['latest'];session=self.factory.sessions[aid]
                control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
                atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
                batch=[dict(id='author',objective='Write report',instruction='Use the exact request',inputs=[],
                    outputs=[dict(path='report.txt',purpose='Report',media_type='text/plain')],dependencies=[],worker=dict(requires=['files.text']))]
                execute(session['frozen'],control,Script([('job_delegate',dict(request_id='add',batch_json=c.encoded(batch)))]),lambda:(CONFIG,BACKEND))
                session['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
                committed.append(True)
            return snapshot
        with patch.object(worker,'next_run',return_value=run),patch.object(pc,'inspect',side_effect=interleave):worker.tick()
        self.assertEqual(self.state.get('production-enabled:'+run),pc.runtime_digest(self.rt,run))
        with patch.object(worker,'next_run',return_value=run):worker.tick();worker.tick()
        self.assertEqual(self.rt.task(run,'author')['status'],'running')
        self.assertFalse(self.state.db.execute("SELECT 1 FROM outbox WHERE id=?",('production:'+run+':changed',)).fetchone())

    def test_claim_rechecks_authorization_after_a_late_ungranted_graph_edit(self):
        worker=pc.Worker(self.state,runtime_factory=lambda root:self.rt);claim=self.rt.claim;edited=[]
        def late_change(run,authorize=None):
            if not edited:
                with self.rt.transaction():
                    task=self.rt.task(run,'produce');spec=self.rt.spec(task);spec['objective']='Unapproved replacement'
                    self.state.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),task['assignment']))
                edited.append(True)
            return claim(run,authorize=authorize)
        with patch.object(worker,'next_run',return_value='demo'),patch.object(self.rt,'claim',side_effect=late_change):worker.tick()
        self.assertFalse(self.state.get('production-enabled:demo'))
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_events WHERE kind='dispatch_authorization_changed'").fetchone()[0],1)

    def test_unstarted_conversation_followup_does_not_hide_unrelated_runs(self):
        from task_relay import conversation_flow
        conversation_flow.initialize(self.state.db)
        with self.state.db:
            self.state.db.execute("INSERT INTO desktop_plan_requests(request_id,job_id,prompt,status,created) VALUES ('followup',999,'Followup','planned',0)")
            self.state.db.execute("INSERT INTO conversation_followups(request_id,source_request_id,option_index,selection_digest,mode,created) VALUES ('followup',998,0,'digest','plan',0)")
            self.state.db.execute("""INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,token,expires,created)
                VALUES ('pending-followup',999,'desktop','Followup','{}','{}','hash','test','test','ready','token',0,0)""")
        jobs=workspace.jobs(paths=self.paths)['items']
        self.assertIn('demo',[item['run'] for item in jobs])
        self.assertNotIn('pending-followup',[item['id'] for item in jobs])

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
        blob=Path(self.rt.artifact(artifact)['blob']);blob.chmod(0o600);blob.write_text('changed fixture')
        with self.assertRaisesRegex(ValueError,'changed'):self.choose(current)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_workspace_commands').fetchone()[0],0)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed'):workspace.artifact_path(artifact,self.paths)

    def test_file_link_reveals_named_copy_and_preserves_user_edits(self):
        view=self.ready();artifact=view['selection_groups'][0]['members'][0]['id']
        before=self.state.db.total_changes;result=workspace.artifact_path(artifact,self.paths)
        named=Path(result['path']);original=Path(self.rt.artifact(artifact)['blob'])
        self.assertNotEqual(named,original);self.assertEqual(named.name,'output.txt')
        self.assertIn('workflows',named.parts);self.assertEqual(named.read_bytes(),original.read_bytes())
        named.write_text('My edit')
        exact=Path(workspace.artifact_path(artifact,self.paths)['path'])
        self.assertNotEqual(exact,named);self.assertEqual(exact.name,'output-registered.txt')
        self.assertEqual(named.read_text(),'My edit');self.assertEqual(exact.read_bytes(),original.read_bytes())
        self.assertEqual(self.state.db.total_changes,before)

    def test_folder_location_is_read_only_before_and_after_export(self):
        view=self.ready();artifact=view['selection_groups'][0]['members'][0]['id']
        before={str(p.relative_to(self.root)) for p in self.root.rglob('*')}
        changes=self.state.db.total_changes
        with patch('task_relay.result_handoff.snapshot',side_effect=AssertionError('Location must not build a result report')):
            location=workspace.artifact_path(artifact,self.paths,location_only=True)
        self.assertIsNone(location['path']);self.assertFalse(location['published'])
        self.assertEqual(before,{str(p.relative_to(self.root)) for p in self.root.rglob('*')})
        result=workspace.artifact_path(artifact,self.paths)
        before={str(p.relative_to(self.root)):p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(workspace.artifact_path(artifact,self.paths,location_only=True)['path'],result['path'])
        self.assertEqual(before,{str(p.relative_to(self.root)):p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()})
        Path(result['path']).write_text('User edit')
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed'):
            workspace.artifact_path(artifact,self.paths,location_only=True)
        self.assertEqual(Path(result['path']).read_text(),'User edit')
        self.assertEqual(self.state.db.total_changes,changes)

    def test_file_link_rejects_symlink_in_export_folder(self):
        view=self.ready();artifact=view['selection_groups'][0]['members'][0]['id']
        named=Path(workspace.artifact_path(artifact,self.paths)['path'])
        original=Path(self.rt.artifact(artifact)['blob']);named.unlink();named.symlink_to(original)
        with self.assertRaisesRegex(ValueError,'symbolic|symlink'):
            workspace.artifact_path(artifact,self.paths)

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
