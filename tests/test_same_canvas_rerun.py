"""Same canvas versions over the existing compiler, admission and Runtime."""
import copy,json,sqlite3,uuid,unittest
from unittest.mock import patch
from tests.test_desktop_workspace import WorkspaceTests
from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts,desktop_node_files as files,desktop_workspace as workspace
from orchestrator import executors

class SameCanvas(unittest.TestCase):
    def setUp(self):
        WorkspaceTests.setUp(self)
        def database(writable=False):
            db=sqlite3.connect(str(self.paths.state) if writable else self.paths.state.as_uri()+'?mode=ro',uri=not writable);db.row_factory=sqlite3.Row;return db
        for p in (patch.object(runs,'PATHS',self.paths),patch.object(drafts,'PATHS',self.paths),patch.object(files,'PATHS',self.paths),patch.object(runs,'_database',database),patch.object(files,'_database',database),patch.object(executors,'available')):
            p.start();self.addCleanup(p.stop)
        def node(id,prompt,inputs):
            return dict(schema_version=3,id=id,operation='model',objective=prompt,inputs=inputs,
                input_definitions={k:dict(type='artifact',label='Source text',media_type='text/plain',required=True) for k in inputs},
                outputs=[dict(name='text',media_type='text/plain',purpose='Generated text')],model=dict(provider='codex',id='gpt-6.1-sol'))
        w=dict(schema_version=1,kind='workflow',inputs={},tasks=[node('first','First',{}),node('second','Second',{'source':{'task':'first','output':'text'}})])
        self.saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='One canvas',workflow=w))
        req=dict(id=self.saved['id'],revision=self.saved['revision'],values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req);self.run=runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=False))['run']
        for tid in ('first','second'):
            self.rt.tick(self.run);self.factory.finish(self.rt.task(self.run,tid)['latest']);self.rt.tick(self.run)
        self.attempt=self.rt.task(self.run,'second')['latest']
        self.original=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))]
    def command(self,prompt='New prompt'):
        saved=runs.save_node_prompt(dict(run=self.run,task='second',attempt=self.attempt,prompt=prompt))
        req=dict(run=self.run,task='second',attempt=self.attempt,revision=saved['revision'],request_id=str(uuid.uuid4()))
        checked=runs.preview(req)
        return dict(**req,fingerprint=checked['fingerprint'],allow_paid=False),checked
    def test_composed_same_canvas_versions_restart_and_original_preserved(self):
        before=[i['id'] for i in workspace.jobs(paths=self.paths)['items']]
        cmd,p=self.command();self.assertEqual([t['id'] for t in p['plan']['tasks']],['second'])
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_attempts WHERE run=?',(self.run,)).fetchone()[0],2)
        receipt=runs.start(cmd);self.assertEqual(receipt['canvas_run'],self.run)
        self.assertTrue(runs.start(cmd)['reused'])
        view=workspace.detail(self.run,self.paths)
        self.assertIn(receipt['run'],view['executing_runs'])
        self.assertEqual(next(i for i in workspace.jobs(paths=self.paths)['items'] if i['id']==self.run)['status'],'active')
        self.rt.tick(receipt['run']);a=self.rt.task(receipt['run'],'second')['latest']
        new=self.factory.sessions[a]['frozen'];old=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(self.attempt,)).fetchone()[0])
        self.assertEqual(new['inputs'][0]['artifact'],old['inputs'][0]['artifact'])
        self.assertEqual(new['inputs'][0]['sha256'],old['inputs'][0]['sha256'])
        self.factory.finish(a);self.rt.tick(receipt['run'])
        view=workspace.detail(self.run,self.paths);second=next(t for t in view['tasks'] if t['id']=='second')
        self.assertEqual(view['name'],self.run);self.assertEqual(view['status'],'completed')
        self.assertEqual(second['objective'],'New prompt');self.assertEqual(len(second['versions']),2)
        self.assertNotEqual(second['versions'][0]['files'][0]['id'],second['versions'][1]['files'][0]['id'])
        self.assertEqual(before,[i['id'] for i in workspace.jobs(paths=self.paths)['items']])
        self.assertEqual(self.original,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])
        self.assertEqual(len(self.factory.calls),3)
        artifact=second['versions'][-1]['files'][0]
        discussion=runs.result_chat(dict(run=receipt['run'],task='second',attempt=a,mode='chat',
            request_id=str(uuid.uuid4()),artifact=artifact['id'],sha256=artifact['sha256'],operation=None,question='Explain this version'))
        self.assertEqual(runs.result_chats(self.state.db,self.run)[0]['run'],discussion['run'])
        # New reads reconstruct versions from durable events; next edit uses version2.
        self.attempt=a;cmd,_=self.command('Third version');third=runs.start(cmd)
        self.assertEqual(third['canvas_run'],self.run)
        self.assertEqual(len(runs.node_versions(self.state.db,self.run,'second')),2)
    def test_stale_prompt_and_running_version_cannot_submit_again(self):
        cmd,_=self.command();self.command('Changed again')
        with self.assertRaisesRegex(ValueError,'Prompt changed'):runs.start(cmd)
        cmd,_=self.command();receipt=runs.start(cmd)
        with self.assertRaisesRegex(ValueError,'version changed|finish'):
            self.command('Duplicate while queued')
        self.rt.tick(receipt['run']);a=self.rt.task(receipt['run'],'second')['latest']
        self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(a,))
        self.state.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run=?",(receipt['run'],));self.state.db.commit();self.attempt=a
        with self.assertRaisesRegex(ValueError,'uncertain'):self.command('No replay')
    def test_atomic_version_admission_and_exact_retry(self):
        cmd,_=self.command()
        with patch('task_relay.relay_channels.bind',side_effect=ValueError('interrupted')):
            with self.assertRaisesRegex(ValueError,'interrupted'):runs.start(cmd)
        self.assertEqual(runs.node_versions(self.state.db,self.run,'second'),[])
        receipt=runs.start(cmd);self.assertTrue(runs.start(cmd)['reused'])
        with self.assertRaisesRegex(ValueError,'another command'):runs.start(dict(cmd,allow_paid=True))
        self.assertEqual(runs.node_versions(self.state.db,self.run,'second'),[receipt['run']])
    def test_changed_input_bytes_fail_without_execution(self):
        cmd,p=self.command();a=self.rt.artifact(p['plan']['tasks'][0]['inputs'][0]['artifact'])
        from pathlib import Path
        Path(a['blob']).chmod(0o600);Path(a['blob']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):runs.start(cmd)
        self.assertEqual(runs.node_versions(self.state.db,self.run,'second'),[])


class EditableWorkflow(SameCanvas):
    def test_native_freshness_ignores_title_but_tracks_prompt_and_settings(self):
        from orchestrator import node_spec
        n=dict(schema_version=3,id='image',operation='gemini.image',objective='Cup image',
            inputs={k:{'value':v} for k,v in dict(prompt='A cup',model='gemini-3.1-flash-image',aspect_ratio='1:1',max_output_tokens=4096).items()})
        w=dict(schema_version=1,kind='workflow',inputs={},tasks=[n])
        saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Native fixture',workflow=w))
        req=dict(id=saved['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
        # Admission only, with host availability mocked; never tick or call Gemini.
        with patch('orchestrator.execution.available'):
            checked=runs.preview(req)
            run=runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=True))['run']
        record=runs.read_canvas({'run':run})
        def outdated(node):
            graph=node_spec.resolve_workflow(dict(w,tasks=[node]))
            return runs.canvas_result_outdated(self.rt,record,graph,graph['tasks'][0],dict(run=run,task='image'))
        self.assertFalse(outdated(n))
        renamed=copy.deepcopy(n);renamed['objective']='Different display title'
        self.assertFalse(outdated(renamed))
        for key,value in [('prompt','Blue cup'),('aspect_ratio','16:9'),('model','gemini-2.5-flash-image'),('max_output_tokens',2048)]:
            changed=copy.deepcopy(n);changed['inputs'][key]={'value':value}
            self.assertTrue(outdated(changed),key)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts WHERE run=?',(run,)).fetchone()[0],0)

    def test_freshness_compares_named_values_model_and_exact_bound_output(self):
        def status():
            return {t['id']:t for t in workspace.detail(self.run,self.paths)['tasks']}
        def edit(change):
            record=runs.read_canvas({'run':self.run});workflow=copy.deepcopy(record['workflow'])
            change(workflow)
            return runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        self.assertFalse(status()['second']['outdated'])
        cmd,_=self.canvas_command('second')
        receipt=runs.start(cmd);self.complete(receipt,['second'])
        self.assertFalse(status()['second']['outdated'],'wire and scoped artifact binding are equivalent')
        # Merely editing the producing draft doesn't change its saved output.
        edit(lambda w:w['tasks'][0].update(objective='Unexecuted upstream edit'))
        self.assertTrue(status()['first']['outdated'])
        self.assertFalse(status()['second']['outdated'])
        edit(lambda w:w['tasks'][1]['model'].update(reasoning='low'))
        self.assertTrue(status()['second']['outdated'])
        edit(lambda w:w['tasks'][1]['model'].pop('reasoning'))
        self.assertFalse(status()['second']['outdated'])
        def add_value(w):
            n=w['tasks'][1];n['inputs']['length']={'value':'Short'}
            n['input_definitions']['length']=dict(type='string',label='Length',required=True)
        edit(add_value)
        self.assertTrue(status()['second']['outdated'])
        cmd,_=self.canvas_command('second');receipt=runs.start(cmd);self.complete(receipt,['second'])
        self.assertFalse(status()['second']['outdated'])
        edit(lambda w:w['tasks'][1]['inputs']['length'].update(value='Long'))
        self.assertTrue(status()['second']['outdated'])

    def canvas_command(self,scope='all',prompt=None,tid='first'):
        record=runs.read_canvas({'run':self.run})
        if prompt:
            workflow=copy.deepcopy(record['workflow'])
            next(t for t in workflow['tasks'] if t['id']==tid)['objective']=prompt
            record=runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        req=dict(canvas=self.run,revision=record['revision'],scope=scope,values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req)
        return dict(**req,fingerprint=checked['fingerprint'],allow_paid=False),checked

    def complete(self,receipt,tids):
        for tid in tids:
            self.rt.tick(receipt['run'])
            a=self.rt.task(receipt['run'],tid)['latest']
            self.factory.finish(a);self.rt.tick(receipt['run'])

    def test_first_only_then_second_uses_new_input_and_full_graph_runs_in_order(self):
        before=[i['id'] for i in workspace.jobs(paths=self.paths)['items']]
        cmd,p=self.canvas_command('first','Changed first')
        self.assertEqual([t['id'] for t in p['plan']['tasks']],['first'])
        first=runs.start(cmd);self.complete(first,['first'])
        view=workspace.detail(self.run,self.paths)
        self.assertTrue(next(t for t in view['tasks'] if t['id']=='second')['outdated'])
        cmd,p=self.canvas_command('second')
        self.assertEqual([t['id'] for t in p['plan']['tasks']],['second'])
        a=self.rt.output(first['run'],'first','outputs/text.txt')
        self.assertEqual(p['plan']['tasks'][0]['inputs'][0]['artifact'],a['id'])
        second=runs.start(cmd);self.complete(second,['second'])
        self.assertFalse(next(t for t in workspace.detail(self.run,self.paths)['tasks'] if t['id']=='second')['outdated'])
        cmd,p=self.canvas_command('all','Third first')
        self.assertEqual([t['id'] for t in p['plan']['tasks']],['first','second'])
        self.assertNotIn('artifact',p['plan']['tasks'][1]['inputs'][0])
        whole=runs.start(cmd);self.complete(whole,['first','second'])
        last=self.rt.task(whole['run'],'second')['latest'];frozen=self.factory.sessions[last]['frozen']
        self.assertEqual(frozen['inputs'][0]['artifact'],self.rt.output(whole['run'],'first','outputs/text.txt')['id'])
        view=workspace.detail(self.run,self.paths)
        self.assertEqual([len(t['versions']) for t in view['tasks']],[3,3])
        self.assertEqual(self.original,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])
        self.assertTrue(runs.start(cmd)['reused'])
        self.assertEqual([i['id'] for i in workspace.jobs(paths=self.paths)['items']],before)

    def test_saved_definition_stale_preview_and_uncertain_execution_reject(self):
        cmd,_=self.canvas_command('all')
        self.canvas_command('first','Saved elsewhere')
        with self.assertRaisesRegex(ValueError,'Canvas changed'):runs.start(cmd)
        cmd,_=self.canvas_command('first')
        receipt=runs.start(cmd)
        with self.assertRaisesRegex(ValueError,'running or uncertain'):self.canvas_command()
        self.rt.tick(receipt['run']);a=self.rt.task(receipt['run'],'first')['latest']
        self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(a,))
        self.state.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run=?",(receipt['run'],));self.state.db.commit()
        with self.assertRaisesRegex(ValueError,'running or uncertain'):self.canvas_command('second')
        record=runs.read_canvas({'run':self.run})
        replacement=copy.deepcopy(record['workflow']['tasks'][0]);replacement['id']='replacement'
        workflow=dict(record['workflow'],tasks=[replacement])
        runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        with self.assertRaisesRegex(ValueError,'running or uncertain'):self.canvas_command()

    def test_input_version_changes_between_preview_and_submission(self):
        second,_=self.canvas_command('second')
        first,_=self.canvas_command('first')
        receipt=runs.start(first);self.complete(receipt,['first'])
        with self.assertRaisesRegex(ValueError,'configuration changed'):runs.start(second)
        self.assertEqual(runs.node_versions(self.state.db,self.run,'second'),[])

    def test_canvas_admission_rollback_and_exact_retry(self):
        cmd,_=self.canvas_command()
        with patch('task_relay.relay_channels.bind',side_effect=ValueError('interrupted')):
            with self.assertRaisesRegex(ValueError,'interrupted'):runs.start(cmd)
        self.assertEqual(runs.node_versions(self.state.db,self.run,'first'),[])
        r=runs.start(cmd);self.assertEqual(runs.start(cmd)['canvas_run'],self.run)
        with self.assertRaisesRegex(ValueError,'another command'):runs.start(dict(cmd,scope='first'))

    def test_canonical_input_bytes_are_rechecked(self):
        cmd,p=self.canvas_command('second')
        artifact=self.rt.artifact(p['plan']['tasks'][0]['inputs'][0]['artifact'])
        from pathlib import Path
        Path(artifact['blob']).chmod(0o600);Path(artifact['blob']).write_text('tampered')
        with self.assertRaisesRegex(ValueError,'bytes changed'):runs.start(cmd)
        self.assertEqual(runs.node_versions(self.state.db,self.run,'second'),[])

    def test_adding_node_saves_same_document_and_single_node_requires_completed_input(self):
        record=runs.read_canvas({'run':self.run});workflow=copy.deepcopy(record['workflow'])
        third=copy.deepcopy(workflow['tasks'][1]);third['id']='third';third['inputs']['source']['task']='second';workflow['tasks'].append(third)
        saved=runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        self.assertEqual(runs.read_canvas({'run':self.run})['workflow'],workflow)
        cmd,p=self.canvas_command('third');self.assertEqual([t['id'] for t in p['plan']['tasks']],['third'])
        receipt=runs.start(cmd);self.complete(receipt,['third'])
        self.assertEqual(len(workspace.detail(self.run,self.paths)['tasks']),3)
        cmd,p=self.canvas_command('third')
        self.assertEqual(p['plan']['tasks'][0]['inputs'][0]['artifact'],self.rt.output(self.run,'second','outputs/text.txt')['id'])

    def test_incomplete_native_node_reopens_and_does_not_block_other_node(self):
        record=runs.read_canvas({'run':self.run});workflow=copy.deepcopy(record['workflow'])
        workflow['tasks'].append(dict(schema_version=3,id='mesh',operation='blender.mesh_scene',
            objective='Create cup mesh',inputs={}))
        saved=runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        self.assertIn('mesh.files',saved['missing_inputs'])
        view=workspace.detail(self.run,self.paths)
        self.assertEqual(view['status'],'draft')
        mesh=next(t for t in view['tasks'] if t['id']=='mesh')
        self.assertEqual(mesh['status'],'draft')
        self.assertTrue(any(p['media_type']=='application/x-blender' for p in mesh['planned_outputs']))
        self.assertEqual(next(p for p in mesh['planned_outputs'] if p['path']=='scene')['label'],'Blender model')
        self.assertEqual(next(p for p in mesh['planned_outputs'] if p['path']=='preview')['label'],'Render preview')
        for scope in ('mesh','all'):
            with self.subTest(scope=scope),self.assertRaisesRegex(ValueError,'missing files|required inputs|Missing inputs'):
                self.canvas_command(scope)
        cmd,p=self.canvas_command('second')
        self.assertEqual([t['id'] for t in p['plan']['tasks']],['second'])
        receipt=runs.start(cmd);self.complete(receipt,['second'])
        self.assertEqual(next(t for t in workspace.detail(self.run,self.paths)['tasks'] if t['id']=='mesh')['status'],'draft')
        self.assertEqual(self.original,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts WHERE run=?',(self.run,))])

    def test_selected_geometry_retains_consumer_schema_and_exact_saved_input(self):
        from tests.test_canvas_schema_handoff import workflow as geometry_workflow
        record=runs.read_canvas({'run':self.run});workflow=copy.deepcopy(record['workflow'])
        model,build=geometry_workflow()['tasks']
        model['inputs']={'brief':{'task':'second','output':'text'}}
        model['input_definitions']={'brief':dict(type='artifact',media_type='text/plain',label='Brief',required=True)}
        workflow['tasks'] += [model,build,dict(schema_version=3,id='unfinished',
            operation='blender.mesh_scene',objective='Unrelated draft',inputs={})]
        runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        cmd,p=self.canvas_command('geometry')
        self.assertEqual([t['id'] for t in p['plan']['tasks']],['geometry'])
        task=p['plan']['tasks'][0]
        self.assertEqual(task['operation_contract']['parameters']['target'],'blender.mesh_scene')
        self.assertEqual(task['inputs'][0]['artifact'],self.rt.output(self.run,'second','outputs/text.txt')['id'])
        # Admission recompiles the same connected contract under its transaction.
        receipt=runs.start(cmd)
        self.assertEqual([r[0] for r in self.state.db.execute(
            'SELECT id FROM production_tasks WHERE run=?',(receipt['run'],))],['geometry'])
        self.rt.tick(receipt['run'])
        with patch('task_relay.production_control.review_resume_digest',
                   side_effect=AssertionError('Canvas must not use legacy review resume')):
            view=workspace.detail(self.run,self.paths)
        self.assertEqual(view['status'],'active')
        self.assertIn(receipt['run'],view['executing_runs'])
        self.assertEqual(next(t for t in view['tasks'] if t['id']=='unfinished')['status'],'draft')

    def test_missing_workflow_value_is_draft_but_selected_node_stays_strict(self):
        record=runs.read_canvas({'run':self.run});workflow=copy.deepcopy(record['workflow'])
        workflow['inputs']['url']=dict(type='string',required=True,label='Article URL')
        workflow['tasks'].append(dict(schema_version=3,id='fetch',operation='web.fetch',
            objective='Read article',inputs={'url':{'workflow':'url'}}))
        runs.save_canvas(dict(run=self.run,revision=record['revision'],title=record['title'],workflow=workflow))
        self.assertEqual(workspace.detail(self.run,self.paths)['status'],'draft')
        self.assertEqual(len(self.canvas_command('second')[1]['plan']['tasks']),1)
        for scope in ('fetch','all'):
            with self.subTest(scope=scope),self.assertRaises(ValueError):self.canvas_command(scope)

    def test_legacy_result_continuation_imports_real_producer_as_editable_node(self):
        a=self.rt.output(self.run,'second','outputs/text.txt')
        draft=runs.result_draft(dict(run=self.run,task='second',attempt=self.attempt,mode='input',
            request_id=str(uuid.uuid4()),artifact=a['id'],sha256=a['sha256'],operation='model',question=''))
        w=copy.deepcopy(draft['workflow']);w['tasks'][0]['objective']='Adjust'
        saved=drafts.dispatch('node-draft-save',dict(id=draft['id'],revision=draft['revision'],title='Imported graph',workflow=w))
        req=dict(id=saved['id'],revision=saved['revision'],values={},request_id=str(uuid.uuid4()))
        p=runs.preview(req);receipt=runs.start(dict(**req,fingerprint=p['fingerprint'],allow_paid=False))
        self.complete(receipt,['adjust'])
        self.run=receipt['run']
        record=runs.read_canvas({'run':self.run});source=record['workflow']['tasks'][0]
        self.assertEqual(source['objective'],'Second')
        self.assertEqual(record['workflow']['tasks'][1]['inputs']['result'],dict(task=source['id'],output='text'))
        cmd,p=self.canvas_command(source['id'],'New source',source['id'])
        self.assertEqual([t['id'] for t in p['plan']['tasks']],[source['id']])
        r=runs.start(cmd);self.complete(r,[source['id']])
        view=workspace.detail(self.run,self.paths)
        self.assertFalse(any(t.get('reused_source') for t in view['tasks']))
        self.assertEqual(len(view['tasks']),2)
        cmd,p=self.canvas_command('all')
        self.assertEqual([t['id'] for t in p['plan']['tasks']],[source['id'],'adjust'])
        r=runs.start(cmd);self.complete(r,[source['id'],'adjust'])
        self.assertEqual(len(runs.node_versions(self.state.db,self.run,source['id'])),2)
