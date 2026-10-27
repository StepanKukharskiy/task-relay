"""Conversation -> existing canvas compiler -> image bundle -> gallery, offline."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from task_relay import persistent_jobs as jobs,request_contract as intake,orchestrator_files
from tests import test_desktop_workspace as workspace_fixture
from tests.test_image_sources import page,photo


def fixture():
    scope=dict(mode='new_work',delivery='artifacts',reason='The user requests sourced photographs.',outcomes=[
        dict(id='pictures',description='Show Volvo 940 and 740 images with sources and disclose gaps.',kind='result',count=1,format='',checks=[],validation=[])])
    nodes=[dict(schema_version=3,id='photos',operation='images.collect',objective='Acquire Volvo 940 and 740 photographs',
        inputs=dict(subjects={'value':[dict(id='volvo-940',label='Volvo 940',query='Volvo 940'),dict(id='volvo-740',label='Volvo 740',query='Volvo 740')]})),
        dict(schema_version=3,id='gallery',operation='images.gallery',objective='Show all acquired photographs and missing subjects',
             inputs=dict(photos={'task':'photos','output':'result'}))]
    return scope,dict(kind='execute_work',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=nodes),outputs=dict(pictures=dict(task='gallery',output='result')))


class Routing(unittest.TestCase):
    def test_artifacts_cannot_be_erased_by_answer_repair_or_text_worker(self):
        c,a=fixture();bad={**c,'mode':'answer'}
        with self.assertRaises(ValueError):intake.load(json.dumps(bad),recover_answer=True)
        with self.assertRaisesRegex(ValueError,'registered workflow'):
            intake.route(dict(request_contract=c,action=dict(kind='execute_work',public_read=True,review='owner',artifact_ids=[])))
        for mode in ('answer','clarify'):
            text=dict(mode=mode,delivery='inline_text',reason='Discuss image techniques; no pictures requested',outcomes=[])
            self.assertIsNone(intake.route(dict(request_contract=text,action=None))['action'])
        historical=dict(mode='answer',reason='Saved status',outcomes=[])
        self.assertEqual(intake.load(json.dumps(historical)),historical)

    def test_ports_scope_and_authority_checked_before_admission(self):
        c,a=fixture();self.assertTrue(jobs.validate_graph(a,c)['ready'])
        for variant in ('port','missing','paid','artifact','scope','duplicate'):
            bad=copy.deepcopy(a);scope=copy.deepcopy(c)
            if variant=='port':bad['workflow']['tasks'][1]['inputs']['photos']['output']='invented'
            if variant=='missing':bad['outputs']={}
            if variant=='paid':bad['workflow']['tasks'][0]['operation']='gemini.image'
            if variant=='artifact':bad['workflow']['tasks'][1]['inputs']['photos']={'artifact':'unselected'}
            if variant=='scope':scope.update(mode='answer',outcomes=[])
            if variant=='duplicate':
                scope['outcomes'].append({**scope['outcomes'][0],'id':'second'})
                bad['outputs']['second']=copy.deepcopy(bad['outputs']['pictures'])
            with self.subTest(variant=variant),self.assertRaises(ValueError):jobs.validate_graph(bad,scope)

    def test_registered_gallery_previous_capture_keeps_explicit_report(self):
        from orchestrator.operation_definition import definition,matches_capture
        from orchestrator.contracts import digest
        from orchestrator.owner_intents import REF
        old=definition('images.gallery');old['defaults']={}
        old['description']='Export every acquired image and the advisory report as a self-contained HTML gallery.'
        old['inputs']['properties']['recommendations']=copy.deepcopy(REF)
        old['inputs']['required'].append('recommendations')
        self.assertTrue(matches_capture('images.gallery',digest(old),{'inputs':{'recommendations':{'task':'advice','output':'result'}}}))
        self.assertFalse(matches_capture('images.gallery',digest(old),{'inputs':{}}))
        from orchestrator import execution
        # Direct registered calls may omit the optional field, not only use the
        # node compiler's explicit null default. Required photos still bind.
        a=dict(execution=dict(parameters={'photos':'photos.zip'}),inputs=[dict(path='photos.zip',media_type='application/zip')])
        execution.adapter('images.gallery').validate(a,execution.REGISTRY['images.gallery'])
        a['execution']['parameters']['photos']=None
        with self.assertRaises(ValueError):execution.adapter('images.gallery').validate(a,execution.REGISTRY['images.gallery'])

    def test_invalid_handoff_gets_existing_bounded_correction_without_reads(self):
        c,a=fixture();bad=copy.deepcopy(a);bad['workflow']['tasks'][1]['inputs']['photos']['output']='invented'
        def response(action):return dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(text=json.dumps(dict(answer='Preparing images',action=action)))]))])
        client=Mock();client.request.side_effect=[response(bad),response(a)]
        request=dict(systemInstruction={'parts':[{'text':'Fixture'}]},contents=[{'role':'user','parts':[{'text':'Show Volvo 940 and 740 photos'}]}],generationConfig={})
        with tempfile.TemporaryDirectory() as folder:
            receipt=Path(folder)/'receipt.json'
            result=json.loads(orchestrator_files.run('gemini',client,'fixture',request,[],receipt,frozen_intake=c))
            self.assertEqual(result['action'],a);self.assertEqual(client.request.call_count,2)
            journal=json.loads(receipt.read_text());self.assertIn('routing_correction',journal[0])
            self.assertFalse(any(turn.get('reads') for turn in journal))


class Composed(unittest.TestCase):
    def setUp(self):
        self.f=workspace_fixture.WorkspaceTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c,self.a=fixture()

    def admit(self):
        with patch('orchestrator.executors.available'),patch('orchestrator.execution.available'):
            return jobs.enqueue_graph(self.f.state,dict(id=123,prompt='Show Volvo 940 and 740 photos'),self.a,{'request_contract':self.c})

    def native(self,tid):
        from orchestrator import step_runner
        self.f.rt.tick('work-123');aid=self.f.rt.task('work-123',tid)['latest']
        session=self.f.factory.sessions[aid];control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
        result=step_runner.execute(session['frozen'],control)
        self.assertEqual(result['outcome'],'completed',result)
        session['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.f.rt.tick('work-123');return session['frozen']

    def test_compiled_nodes_acquire_literal_urls_and_display_partial_without_review(self):
        from orchestrator import image_sources
        from task_relay import orchestrator_chat,conversation_flow,desktop_workspace
        orchestrator_chat.initialize(self.f.state.db)
        self.f.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,status,created) VALUES (123,'Show Volvo 940 and 740 photos','gemini','fixture','answered',1)")
        self.f.state.db.commit()
        self.admit();self.assertIn('already saved',self.admit())
        self.assertEqual(self.f.rt.db.execute("SELECT count(*) FROM production_attempts WHERE run='work-123'").fetchone()[0],0)
        self.assertEqual([t['id'] for t in self.f.rt.status('work-123')['tasks']],['photos','gallery'])
        calls=[]
        def fetch(url,*args):
            calls.append(url)
            if 'api.php' in url:
                p=page();p['title']='File:Volvo 940.jpg';i=p['imageinfo'][0]
                i['extmetadata']['ImageDescription']['value']='Volvo 940'
                i['url']='https://upload.wikimedia.org/wikipedia/commons/a/ab/Volvo_940.jpg'
                i['descriptionurl']='https://commons.wikimedia.org/wiki/File:Volvo_940.jpg'
                return json.dumps({'query':{'pages':{'1':p} if '940' in url else {}}}).encode(),'application/json',url
            return photo(),'image/jpeg',url
        with patch.object(image_sources,'download',side_effect=fetch):frozen=self.native('photos')
        self.native('gallery')
        status=self.f.rt.status('work-123');self.assertEqual(status['status'],'completed')
        self.assertEqual(frozen['max_attempts'] if 'max_attempts' in frozen else self.f.rt.spec(self.f.rt.task('work-123','photos'))['max_attempts'],1)
        artifacts=self.f.rt.db.execute("SELECT * FROM production_artifacts WHERE run='work-123'").fetchall()
        bundle=next(r for r in artifacts if r['path'].endswith('.zip'));html=next(r for r in artifacts if r['path'].endswith('.html'))
        images,credits,manifest=image_sources.unpack(Path(bundle['blob']).read_bytes())
        self.assertEqual(list(images.values()),[photo()]);self.assertEqual(manifest['coverage']['missing'],1)
        self.assertIn('https://upload.wikimedia.org/wikipedia/commons/a/ab/Volvo_940.jpg',calls)
        text=Path(html['blob']).read_text();self.assertIn('Volvo 740',text);self.assertIn('data:image/',text)
        self.assertFalse(any(t.get('review_of') for t in status['tasks']))
        view=desktop_workspace.chat_detail('123',self.f.paths)
        self.assertEqual(len(view['flow']['stages'][0]['execution']['tasks']),2)
        self.assertEqual(view['flow']['status'],'completed')
        visible=desktop_workspace.jobs(paths=self.f.paths)['items']
        self.assertFalse(any(i['id']=='work-123' for i in visible))
        self.assertEqual(next(i for i in visible if i['id']=='123')['status'],'completed')
        self.assertEqual(self.f.rt.db.execute("SELECT count(*) FROM production_attempts WHERE run='work-123'").fetchone()[0],2)

    def test_transaction_failure_rolls_back_graph_and_no_replay_dispatch(self):
        self.f.state.db.execute("CREATE TRIGGER fail_graph BEFORE INSERT ON production_events WHEN NEW.kind='conversation_graph_bound' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        self.f.state.db.commit()
        with self.assertRaises(Exception):self.admit()
        self.assertIsNone(self.f.state.db.execute("SELECT id FROM production_runs WHERE id='work-123'").fetchone())
        self.assertFalse(self.f.factory.calls)


class ConversationAdmission(unittest.TestCase):
    def test_explicit_followup_dispatches_graph_in_same_job_preserving_failure(self):
        from tests import test_conversation_messages as messages,test_shared_orchestrator as shared
        from task_relay import orchestrator_chat as chat,desktop_workspace,conversation_flow
        f=messages.Messages();f.setUp();self.addCleanup(f.doCleanups)
        f.root();f.send('Show Volvo 940 and 740 images');child=f.admit()
        c,a=fixture();reply=dict(answer='Acquiring the requested images.',action=a,request_contract=c,
            work_status='respond',answer_basis='proposed_work',claim_sources=[],next_options=[])
        snapshot={'capabilities':shared.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}
        generator=Mock(return_value=json.dumps(reply))
        with patch.object(chat,'snapshot',return_value=snapshot),patch.object(chat.gemini,'DATA',f.paths.data),patch('orchestrator.executors.available'),patch('orchestrator.execution.available'):
            worker=chat.Worker(f.state,generator=generator);worker.tick();worker.tick()
        generator.assert_called_once()
        row=f.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(child['id'],)).fetchone()
        self.assertEqual(row['status'],'answered',row['answer'])
        view=desktop_workspace.chat_detail('41',f.paths)
        self.assertEqual(len(view['flow']['stages'][-1]['execution']['tasks']),2)
        self.assertEqual(conversation_flow.summary(f.state.db,41)['status'],'active')
        self.assertEqual(desktop_workspace.jobs(paths=f.paths)['total'],1)
        self.assertEqual(dict(f.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=41').fetchone()),f.original)


if __name__=='__main__':unittest.main()
