"""Focused draft scope, workflow proposal, and model-choice boundaries. No providers."""
import copy,json,uuid,unittest
from unittest.mock import patch
from tests.test_same_canvas_rerun import SameCanvas
from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts,desktop_node_setup as setup,desktop_workspace as workspace

class Controls(unittest.TestCase):
    def setUp(self):SameCanvas.setUp(self)

    def test_draft_node_scope_preserves_whole_canvas_and_continues_second(self):
        req=dict(id=self.saved['id'],revision=self.saved['revision'],scope='first',values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req)
        self.assertEqual([t['id'] for t in checked['plan']['tasks']],['first'])
        result=runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=False));run=result['run']
        self.rt.tick(run);self.factory.finish(self.rt.task(run,'first')['latest']);self.rt.tick(run)
        record=runs.read_canvas({'run':run})
        self.assertEqual([n['id'] for n in record['workflow']['tasks']],['first','second'])
        self.assertEqual(set(record['baselines']),{'first'})
        view=workspace.detail(run,self.paths)
        self.assertEqual([(t['id'],t['status']) for t in view['tasks']],[('first','completed'),('second','draft')])
        req=dict(canvas=run,revision=record['revision'],scope='second',values={},request_id=str(uuid.uuid4()))
        checked=runs.preview(req);self.assertEqual([t['id'] for t in checked['plan']['tasks']],['second'])
        result=runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=False))
        self.assertEqual(result['canvas_run'],run)
        self.assertTrue(runs.start(dict(**req,fingerprint=checked['fingerprint'],allow_paid=False))['reused'])
        self.assertEqual(len(self.factory.calls),3,'admission does not dispatch the second node')

    def test_draft_scope_missing_source_never_schedules_upstream(self):
        before=self.state.db.execute('select count(*) from production_runs').fetchone()[0]
        req=dict(id=self.saved['id'],revision=self.saved['revision'],scope='second',values={},request_id=str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError,'connected input node first'):runs.preview(req)
        self.assertEqual(before,self.state.db.execute('select count(*) from production_runs').fetchone()[0])

    def test_compose_validates_exact_result_without_executing_proposal(self):
        command=dict(request_id=str(uuid.uuid4()),question='Read a page and summarise it',title='New graph',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]))
        receipt=runs.compose_workflow(command);run=receipt['run']
        self.assertTrue(runs.compose_workflow(command)['reused'])
        with self.assertRaisesRegex(ValueError,'identity changed'):runs.compose_workflow(dict(command,question='Different'))
        self.assertEqual(runs.composition_result({'request_id':command['request_id']})['status'],'active')
        self.rt.tick(run);aid=self.rt.task(run,'compose')['latest']
        proposal=copy.deepcopy(self.saved['workflow'])
        from orchestrator.operation_records import Store
        from orchestrator.gemini_worker import Files
        store=Store(self.factory.sessions[aid]['frozen'],self.rt.db)
        store.submit(dict(request_key='valid',revision=0,records=[dict(kind='work',message='Here is your graph.',workflow=proposal)]),{})
        self.factory.finish(aid);store.export(Files(self.factory.sessions[aid]['frozen']),complete=True)
        self.rt.tick(run)
        before=[tuple(r) for r in self.state.db.execute('select * from production_attempts')]
        result=runs.composition_result({'request_id':command['request_id']})
        self.assertEqual(result['workflow'],proposal)
        self.assertEqual(before,[tuple(r) for r in self.state.db.execute('select * from production_attempts')])
        self.assertEqual([t['id'] for t in json.loads(self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])['tasks']],['compose'])

    def test_active_graph_revisions_are_read_only_and_invalid_amendment_keeps_preview(self):
        from orchestrator.operation_records import Store
        from orchestrator.operation_contracts import digest
        from orchestrator.gemini_worker import Files
        command=dict(request_id=str(uuid.uuid4()),question='Build in steps',title='Progressive',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]))
        run=runs.compose_workflow(command)['run'];self.rt.tick(run);aid=self.rt.task(run,'compose')['latest']
        frozen=self.factory.sessions[aid]['frozen'];store=Store(frozen,self.rt.db)
        graph=copy.deepcopy(self.saved['workflow']);one=copy.deepcopy(graph);one['tasks']=one['tasks'][:1]
        first=dict(kind='work',message='First node ready',workflow=one)
        saved=store.submit(dict(request_key='first',revision=0,records=[first]),{})
        before=list(self.state.db.iterdump())
        preview=runs.composition_result(dict(request_id=command['request_id']))
        self.assertEqual(preview['workflow'],one);self.assertEqual(preview['status'],'active')
        self.assertEqual(preview['preview'],dict(attempt=aid,revision=1,sha256=digest(first)))
        self.assertEqual(before,list(self.state.db.iterdump()),'status projection must not write or collect')
        broken=copy.deepcopy(graph);broken['tasks'][1]['inputs']={'page':dict(task='missing',output='page')}
        with self.assertRaises(ValueError):store.amend(dict(request_key='bad',revision=1,expected_record_sha256=digest(first),record=dict(kind='work',message='Bad wire',workflow=broken)),{})
        self.assertEqual(runs.composition_result(dict(request_id=command['request_id']))['preview'],preview['preview'])
        final=dict(kind='work',message='Both nodes ready',workflow=graph)
        store.amend(dict(request_key='second',revision=1,expected_record_sha256=digest(first),record=final),{})
        preview=runs.composition_result(dict(request_id=command['request_id']))
        self.assertEqual(preview['workflow'],graph);self.assertEqual(preview['preview']['revision'],2)
        self.assertEqual(len(self.state.db.execute('SELECT * FROM operation_record_versions WHERE attempt=?',(aid,)).fetchall()),1)
        self.factory.finish(aid);store.export(Files(frozen),complete=True);self.rt.tick(run)
        completed=runs.composition_result(dict(request_id=command['request_id']))
        self.assertEqual(completed['workflow'],graph);self.assertEqual(completed['status'],'completed');self.assertNotIn('preview',completed)
        self.assertEqual([t['id'] for t in json.loads(self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])['tasks']],['compose'])
        self.assertEqual(frozen,self.factory.sessions[aid]['frozen'],'grants stay unchanged')

    def test_proposed_ai_nodes_inherit_chat_model_without_overwriting_saved_choices(self):
        original=copy.deepcopy(self.saved['workflow'])
        original['tasks']=original['tasks'][:1]
        original['tasks'][0]['model']=dict(provider='codex',id='gpt-6-sol',reasoning='high')
        choice=dict(provider='codex',id='gpt-6.1-sol',reasoning='high')
        command=dict(request_id=str(uuid.uuid4()),question='Add an AI step',title='Models',workflow=original,model=choice)
        receipt=runs.compose_workflow(command);run=receipt['run'];self.rt.tick(run);aid=self.rt.task(run,'compose')['latest']
        proposal=copy.deepcopy(self.saved['workflow'])
        for n in proposal['tasks']:n.pop('model',None)
        explicit=copy.deepcopy(proposal['tasks'][0]);explicit['id']='explicit';explicit['model']=dict(provider='codex',id='gpt-6-sol',reasoning='low');proposal['tasks'].append(explicit)
        from orchestrator.operation_records import Store
        from orchestrator.gemini_worker import Files
        store=Store(self.factory.sessions[aid]['frozen'],self.rt.db)
        store.submit(dict(request_key='valid',revision=0,records=[dict(kind='work',message='Updated graph',workflow=proposal)]),{})
        self.factory.finish(aid);store.export(Files(self.factory.sessions[aid]['frozen']),complete=True);self.rt.tick(run)
        result=runs.composition_result({'request_id':command['request_id']})
        self.assertEqual(result['workflow']['tasks'][0]['model'],original['tasks'][0]['model'])
        self.assertEqual(result['workflow']['tasks'][1]['model'],choice)
        self.assertEqual(result['workflow']['tasks'][2]['model'],explicit['model'])
        self.assertNotIn('model',proposal['tasks'][0],'original returned proposal stays untouched')

    def test_invalid_proposal_stays_evidence_and_never_applies_or_retries(self):
        command=dict(request_id=str(uuid.uuid4()),question='Propose a graph',title='Invalid fixture',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]))
        receipt=runs.compose_workflow(command);run=receipt['run']
        self.rt.tick(run);aid=self.rt.task(run,'compose')['latest'];self.factory.finish(aid)
        proposal=copy.deepcopy(self.saved['workflow']);proposal['tasks'][0]['operation']='invented.tool'
        (self.factory.sessions[aid]['workspace']/'outputs/result.json').write_text(json.dumps(dict(kind='work',message='Invalid',workflow=proposal)));self.rt.tick(run)
        calls=len(self.factory.calls)
        result=runs.composition_result({'request_id':command['request_id']})
        self.assertEqual(result['status'],'blocked');self.assertNotIn('workflow',result)
        self.assertEqual(len(self.factory.calls),calls)
        self.assertTrue(runs.compose_workflow(command)['reused'])

    def test_codex_choices_are_local_and_valid_backend_settings(self):
        with patch.object(setup.capability_defaults,'snapshot',return_value={'capabilities':[{'capability':'text','options':[]}]}):
            models=setup.snapshot()['text'][0]['models']
        self.assertIn('gpt-6.1-sol',models);self.assertIn('gpt-6-sol',models)
        for model in models:self.assertEqual(setup.backend({'provider':'codex','id':model})['model'],model)

    def test_selected_chat_model_preview_paid_consent_and_exact_reuse(self):
        command=dict(request_id=str(uuid.uuid4()),question='Propose a summary graph',title='Gemini chat',
            workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]),model=dict(provider='gemini',id='gemini-2.5-flash'))
        before=self.state.db.execute('select count(*) from production_runs').fetchone()[0]
        checked=runs.compose_workflow(command,preview_only=True)
        self.assertEqual(checked['paid_nodes'],['compose'])
        self.assertEqual(checked['plan']['backend']['type'],'gemini-agent')
        self.assertEqual(checked['plan']['backend']['model'],'gemini-2.5-flash')
        self.assertEqual(before,self.state.db.execute('select count(*) from production_runs').fetchone()[0])
        submission=dict(**checked['command'],fingerprint=checked['fingerprint'],allow_paid=False)
        with self.assertRaisesRegex(ValueError,'Paid API'):runs.start(submission)
        with self.assertRaisesRegex(ValueError,'identity changed'):
            runs.compose_workflow(dict(command,model=dict(provider='codex',id='gpt-6-sol')),preview_only=True)
        submission['allow_paid']=True
        receipt=runs.start(submission)
        self.assertTrue(runs.start(submission)['reused'])
        self.assertEqual(runs.composition_result(dict(request_id=command['request_id']))['status'],'active')
        self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],before+1)

    def test_chat_preview_requires_choice_and_checks_availability(self):
        command=dict(request_id=str(uuid.uuid4()),question='Propose a graph',title='Chat',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]))
        with self.assertRaisesRegex(ValueError,'Choose a chat'):runs.compose_workflow(command,preview_only=True)
        command['model']=dict(provider='invalid',id='invalid')
        with self.assertRaises(ValueError):runs.compose_workflow(command,preview_only=True)
        command['model']=dict(provider='codex',id='gpt-6-sol')
        with patch.object(runs.executors,'available',side_effect=ValueError('Missing connection')):
            checked=runs.compose_workflow(command,preview_only=True)
        self.assertEqual(checked['paid_nodes'],[])
        self.assertIn('Missing connection',checked['blockers'][0]['message'])
        self.assertEqual(checked['plan']['backend']['model'],'gpt-6-sol')

    def test_failed_proposal_corrected_inside_same_worker_and_limits(self):
        from tests.test_operation_session import Script,Tests as Loop
        from orchestrator import contracts
        command=dict(request_id=str(uuid.uuid4()),question='How do I summarise a web page?',title='Conversation',
            workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]),model=dict(provider='gemini',id='fixture'),
            messages=[dict(role='user',text='Hello'),dict(role='assistant',text='What would you like to do?')])
        checked=runs.compose_workflow(command,preview_only=True)
        receipt=runs.start(dict(**checked['command'],fingerprint=checked['fingerprint'],allow_paid=True));run=receipt['run']
        self.rt.tick(run);aid=self.rt.task(run,'compose')['latest'];frozen=self.factory.sessions[aid]['frozen']
        proposal=copy.deepcopy(self.saved['workflow'])
        fetch=dict(schema_version=3,id='page',operation='web.fetch',objective='Read a page',inputs={'url':{'value':'https://example.com'}})
        proposal['tasks'].insert(0,fetch)
        wrong=copy.deepcopy(proposal);wrong['tasks'][0]['outputs']=[dict(name='page',media_type='application/json',purpose='Page')]
        invalid_wire=copy.deepcopy(proposal);invalid_wire['tasks'][1]['inputs']={'page':{'task':'missing','output':'page'}}
        invalid_wire['tasks'][1]['input_definitions']={'page':dict(type='artifact',label='Page',media_type='application/json',required=True)}
        reply=lambda w:dict(kind='work',message='Read the page, then summarise its text.',workflow=w)
        from orchestrator.operation_contracts import digest
        initial=copy.deepcopy(proposal);initial['tasks']=initial['tasks'][:1]
        script=Script([('operation_submit',dict(request_key='bad',revision=0,records=[reply(wrong)])),
            ('operation_submit',dict(request_key='bad-wire',revision=0,records=[reply(invalid_wire)])),
            ('operation_submit',dict(request_key='first-node',revision=0,records=[reply(initial)])),
            ('operation_amend',dict(request_key='invalid-extension',revision=1,expected_record_sha256=digest(reply(initial)),record=reply(invalid_wire))),
            ('operation_amend',dict(request_key='complete-graph',revision=1,expected_record_sha256=digest(reply(initial)),record=reply(proposal))),
            ('finish',dict(report_json=contracts.encoded(dict(summary='Saved valid proposal',decision='delivered',instruction='',findings=[],checks={f'c{i}':dict(passed=True,evidence='Typed proposal saved') for i in range(1,len(frozen['criteria'])+1)}))))])
        result,control=Loop.run_worker(self,self,aid,script)
        self.assertIsNotNone(result)
        self.assertIn('outputs',json.dumps(script.requests[1]))
        self.assertIn('Unknown task',json.dumps(script.requests[2]))
        self.assertIn(digest(reply(initial)),json.dumps(script.requests[3]),'code supplies the exact current record hash to the next model request')
        self.rt.tick(run)
        final=runs.composition_result(dict(request_id=command['request_id']))
        self.assertEqual(final['workflow'],proposal);self.assertIn('Read the page',final['message'])
        self.assertEqual(self.rt.task(run,'compose')['latest'],aid)
        self.assertEqual(len(script.requests),6);self.assertEqual(frozen['limits']['provider_requests'],24)
        self.assertEqual(self.rt.db.execute('select count(*) from operation_submissions where attempt=?',(aid,)).fetchone()[0],2)

    def test_conversational_reply_without_graph_and_schema_rejects_ports(self):
        from orchestrator.workflow_proposal import record,authoring_schema
        from orchestrator.parameter_contracts import validate
        record(dict(kind='clarification',message='Please share the page URL.',workflow=None),{})
        w=copy.deepcopy(self.saved['workflow'])
        w['tasks'][0]=dict(schema_version=3,id='fetch',operation='web.fetch',objective='Read page',inputs={},outputs=[])
        with self.assertRaises(ValueError):validate(w,authoring_schema())
        with self.assertRaisesRegex(ValueError,'already defines its ports'):record(dict(kind='work',message='Graph',workflow=w),{})

    def test_proposal_cannot_add_files_and_registered_context_is_preserved(self):
        from orchestrator.workflow_proposal import record
        w=copy.deepcopy(self.saved['workflow'])
        w['tasks'][0]['inputs']={'source':{'artifact':'selected-file'}}
        w['tasks'][0]['input_definitions']={'source':dict(type='artifact',label='Source',media_type='text/plain',required=True)}
        reply=dict(kind='work',message='Use the selected file.',workflow=w)
        with self.assertRaisesRegex(ValueError,'unselected file'):record(reply,{},dict(artifacts={}))
        self.assertEqual(record(reply,{},dict(artifacts={'selected-file':dict(media_type='text/plain')})),'reply')
        self.assertEqual(record(reply,{}),'reply','record identity reads do not invent a file lookup')
