"""One node document through desktop admission, runtime, tools and UI; offline only."""
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch

from orchestrator import node_spec, job_owner, executors, contracts
from orchestrator.runtime import Runtime
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from task_relay import persistent_jobs, desktop_plans, desktop_workspace, production_control
from tests import test_desktop_plans as desktop_fixture
from tests.test_orchestrator import FakeFactory
from tests.test_operation_session import Script, CONFIG

ROOT=Path(__file__).resolve().parents[1]
BACKEND=dict(type='codex-agent',model='gpt-6.1-sol',reasoning='high',budget_semantics='cli-exchanges-v1')

class Specification(unittest.TestCase):
    def setUp(self):
        self.node=json.loads((ROOT/'examples/summary.node.json').read_text())

    def test_file_is_the_runtime_declaration_and_ui_projection(self):
        p=persistent_jobs.node_proposal('example',self.node,BACKEND,[],public_read=True)
        cap=p['grant']['node_contract']
        declarations=job_owner.definitions({**p['grant'],'delegation_version':4})
        run=next(d for d in declarations if d['name']=='node_run')
        self.assertEqual(run['parametersJsonSchema']['properties']['tasks']['items'],node_spec.schema())
        view=node_spec.presentation(cap)
        self.assertEqual(view['document'],self.node)
        self.assertEqual(view['schema'],run['parametersJsonSchema']['properties']['tasks']['items'])
        self.assertEqual(p['grant']['deliverables'],{'summary':'text/markdown'})

    def test_node_ports_do_not_pass_through_a_second_request_contract(self):
        self.node['outputs'][0]['name'] = 'a' * 41
        p=persistent_jobs.node_proposal('example',self.node,BACKEND,[])
        self.assertNotIn('request_contract',p['grant']['execution_policy'])
        self.assertEqual(list(p['grant']['deliverables']),['a'*41])

    def test_model_node_cannot_masquerade_as_native_operation_without_outputs(self):
        del self.node['outputs']
        with self.assertRaises(ValueError):node_spec.validate(self.node)

    def test_duplicate_ports_unknown_fields_and_forged_authority_fail(self):
        for patch_value in ({'limits':{'seconds':9999}},{'outputs':self.node['outputs']*2},{'provider':'paid'}, {'schema_version':2}):
            with self.subTest(value=patch_value),self.assertRaises(ValueError):node_spec.validate({**self.node,**patch_value})
        with self.assertRaisesRegex(ValueError,'no paid fallback'):
            persistent_jobs.node_proposal('example',self.node,dict(type='openai-agent'),[])
        with self.assertRaisesRegex(ValueError,'inputs differ'):
            persistent_jobs.node_proposal('example',{**self.node,'inputs':[{'artifact':'foreign'}]},BACKEND,[])

    def test_schema_and_document_tamper_cannot_enter_runtime(self):
        cap=node_spec.capture(self.node);cap['schema_sha256']='changed'
        with self.assertRaises(ValueError):node_spec.presentation(cap)
        cap=node_spec.capture(self.node);cap['document']['operation']='unknown'
        with self.assertRaises(ValueError):node_spec.presentation(cap)

    def test_same_schema_compiles_model_content_operation_review_without_authority(self):
        nodes=[self.node,dict(id='read',objective='Read',operation='web.sources.rendered',parameters={}),
            dict(id='subjects',objective='Inventory',content=dict(family='collection.subjects',sources={})),
            dict(id='review',objective='Assess',review_of='summary')]
        converted=node_spec.legacy_tasks({'tasks':nodes})
        self.assertNotIn('operation',converted['tasks'][0])
        self.assertEqual(converted['tasks'][1],nodes[1])
        # Schema acceptance grants nothing; the existing compiler still owns operation admission.
        from orchestrator.owner_intents import validate_delegation
        validate_delegation({'request_id':'code-owned',**converted},4)

class Desktop(unittest.TestCase):
    def setUp(self):
        self.f=desktop_fixture.DesktopPlansTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.state=self.f.state;self.paths=self.f.paths
        with self.state.db:self.state.put('health:desktop-plans',dict(interface_version=1,orchestrator_entry_version=1,node_entry_version=1,last_success=time.time()))
        self.catalog=patch.object(executors,'catalog',return_value=[dict(id='codex-agent',available=True,backend=BACKEND)])
        self.catalog.start();self.addCleanup(self.catalog.stop)

    def submit(self,ident=None,files=None):
        ident=ident or str(uuid.uuid4())
        desktop_plans.create('Summarise the supplied text.', '', None, None, ident,self.paths,files=files,entry_mode='node',research_mode='none')
        with patch('task_relay.orchestrator_chat.provider',side_effect=AssertionError('Legacy intake must not run')):
            desktop_plans.process_requests(self.state)
        return ident

    def test_node_read_receipts_are_visible_without_reading_again(self):
        from task_relay import desktop_sources
        ident=self.submit()
        run=self.state.db.execute('SELECT result FROM desktop_plan_requests WHERE request_id=?',(ident,)).fetchone()[0]
        factory=FakeFactory();rt=Runtime(production_control.root(self.state),factory,connection=self.state.db)
        rt.tick(run);session=factory.sessions[rt.task(run,'owner')['latest']]
        frozen=session['frozen']
        # The ordinary no-research fixture grant is extended only in this saved
        # observation fixture; no worker dispatch or new authority is performed.
        frozen=copy.deepcopy(frozen);frozen['owner_grant']['execution_policy']['public_read']=True
        with self.state.db:self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),rt.task(run,'owner')['latest']))
        root=Path(frozen['workspace']).parent.parent/'owner-context'/run/'public-reads'/'captured'
        evidence=root/'rendered'/'text.txt';evidence.parent.mkdir(parents=True);evidence.write_text('Accessible introduction.')
        identity=dict(url='https://example.com/article',method='rendered',domains=[])
        atomic(root/'rendered-claim.json',identity)
        atomic(root/'rendered-result.json',dict(identity=identity,status='captured',page=dict(url=identity['url'],text=evidence.read_text(),title='Article'),evidence=str(evidence),evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest()))
        plan=job_owner.original(rt,run)
        result=desktop_sources.inspect(self.state.db,run,plan)
        self.assertEqual([p['url'] for p in result['pages']],[identity['url']])
        evidence.write_text('Changed')
        result=desktop_sources.inspect(self.state.db,run,plan)
        self.assertEqual(result['pages'],[]);self.assertTrue(result['partial'])

    def test_desktop_admits_once_and_actual_tool_loop_delivers_to_same_ui_node(self):
        ident=self.submit();self.submit(ident)
        row=self.state.db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?',(ident,)).fetchone()
        self.assertEqual(row['status'],'accepted',row['result']);run=row['result']
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        factory=FakeFactory();rt=Runtime(production_control.root(self.state),factory,connection=self.state.db)
        rt.tick(run);session=factory.sessions[rt.task(run,'owner')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        class Decisions(Script):
            def request(inner, endpoint, payload, **kw):
                inner.requests.append(copy.deepcopy(payload))
                return dict(choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content=None,tool_calls=[dict(id='call-1',type='function',function=dict(name='node_result',arguments=json.dumps(dict(outputs={'result':{'text':'The requested summary.'}},summary='Done.'))))]))])
        script=Decisions([])
        result=execute(session['frozen'],control,script,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered')
        session['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        rt.tick(run)
        view=desktop_workspace.request_detail(ident,self.paths)['node_view']
        self.assertEqual(view['status'],'completed')
        self.assertEqual(view['node']['document'],job_owner.original(rt,run)['job_owner']['node_contract']['document'])
        self.assertEqual(view['node']['document']['outputs'][0]['name'],'result')
        delivered=view['delivered_outputs'][0]
        self.assertEqual(delivered['review_status'],'unreviewed')
        output=next(a for a in view['latest_outputs'] if a['id']==delivered['artifact'])
        self.assertEqual(output['path'],'deliverables/result.md')
        self.assertEqual(next(a['text'] for a in view['output_texts'] if a['path']==output['path']),'The requested summary.')
        # A changed binding cannot relabel another artifact as the delivered port.
        with self.state.db:
            receipt=self.state.db.execute("SELECT id,data FROM production_events WHERE run=? AND kind='owner_delivery_verified'",(run,)).fetchone()
            bad=json.loads(receipt['data']);bad['deliverables']['result']['sha256']='0'*64
            self.state.db.execute('UPDATE production_events SET data=? WHERE id=?',(json.dumps(bad),receipt['id']))
        self.assertEqual(desktop_workspace.request_detail(ident,self.paths)['node_view']['delivered_outputs'],[])
        with self.state.db:self.state.db.execute('UPDATE production_events SET data=? WHERE id=?',(receipt['data'],receipt['id']))
        items=desktop_workspace.jobs(paths=self.paths)['items']
        self.assertEqual(len([i for i in items if i.get('run')==run or i['id']==ident]),1)
        # New revision is compiled from the exact baseline; the original stays byte-identical.
        original=self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0]
        revision_id=str(uuid.uuid4())
        desktop_plans.create('Make it shorter.','',None,None,revision_id,self.paths,entry_mode='node',previous_run=run)
        with patch('task_relay.orchestrator_chat.provider',side_effect=AssertionError('Continuation must not plan')):
            desktop_plans.process_requests(self.state)
        revision=self.state.db.execute('SELECT status,result FROM desktop_plan_requests WHERE request_id=?',(revision_id,)).fetchone()
        self.assertEqual(revision['status'],'accepted',revision['result'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0],original)
        self.assertIn('Make it shorter.',job_owner.original(rt,revision['result'])['job_owner']['node_contract']['document']['objective'])

    def test_frozen_attachments_survive_original_change_and_are_not_model_reconstructed(self):
        source=self.paths.data/'input.txt';source.write_text('Original evidence')
        ident=str(uuid.uuid4())
        desktop_plans.create('Summarise attached text.','',None,None,ident,self.paths,files=[str(source)],entry_mode='node')
        source.write_text('Changed original')
        desktop_plans.process_requests(self.state)
        row=self.state.db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?',(ident,)).fetchone()
        self.assertEqual(row['status'],'accepted',row['result'])
        rt=Runtime(production_control.root(self.state),connection=self.state.db)
        plan=job_owner.original(rt,row['result']);ref=node_spec.artifact_inputs(plan['job_owner']['node_contract']['document'])[0]
        self.assertEqual(Path(rt.artifact(ref['artifact'])['blob']).read_text(),'Original evidence')

    def test_unavailable_codex_fails_without_legacy_or_paid_fallback(self):
        with patch.object(executors,'catalog',return_value=[]):ident=self.submit()
        row=self.state.db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?',(ident,)).fetchone()
        self.assertEqual(row['status'],'rejected')
        self.assertIn('no paid fallback',row['result'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_changed_capture_rejects_atomically_before_dispatch(self):
        source=self.paths.data/'input.txt';source.write_text('Evidence')
        ident=str(uuid.uuid4());desktop_plans.create('Summarise.','',None,None,ident,self.paths,files=[str(source)],entry_mode='node')
        manifest=json.loads(self.state.db.execute('SELECT manifest FROM desktop_plan_inputs').fetchone()[0]);Path(manifest[0]['path']).chmod(0o600);Path(manifest[0]['path']).write_text('tampered')
        desktop_plans.process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM desktop_plan_requests').fetchone()[0],'rejected')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],0)

class PersistedInputs(unittest.TestCase):
    def setUp(self):
        from tests import test_job_owner_loop as fixture
        self.f=fixture.Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.inputs=[]
        for name in ('room','workflow','inventory'):
            path=self.f.root.parent/(name+'.txt');path.write_text(name)
            ident=self.f.rt.register(path,name)
            self.inputs.append(dict(artifact=ident,path=name+'.txt',purpose=name,
                                    authority='Synthetic fixture',media_type='text/plain'))
        self.node=dict(schema_version=3,id='request',operation='model',objective='Use the supplied inputs',
            inputs={name:{'artifact':item['artifact']} for name,item in zip(('room','workflow','inventory'),self.inputs)},
            input_definitions={name:dict(type='artifact',label=name,required=True,media_type='text/plain') for name in ('room','workflow','inventory')},
            outputs=[dict(name='report',media_type='text/plain',purpose='Report')])

    def test_saved_named_inputs_reload_and_dispatch_without_order_dependency(self):
        grant={**self.f.grant,'node_contract':node_spec.capture(self.node)}
        job_owner.create(self.f.rt,'job',self.node['objective'],dict(type='gemini-agent',model='fixture'),self.inputs,grant)
        self.f.rt.close();self.f.rt=Runtime(self.f.root,self.f.factory)
        saved=job_owner.original(self.f.rt,'job')
        self.assertEqual(list(saved['job_owner']['node_contract']['document']['inputs']),['inventory','room','workflow'])
        self.assertEqual(saved['job_owner']['inputs'],[i['artifact'] for i in self.inputs])
        contracts.plan(saved)
        self.f.rt.tick('job')
        self.assertEqual(self.f.rt.task('job','owner')['status'],'launching')
        frozen=self.f.factory.sessions[self.f.rt.task('job','owner')['latest']]['frozen']
        self.assertEqual({i['artifact'] for i in frozen['inputs']},{i['artifact'] for i in self.inputs})
        # Sorting must not mask missing, substituted or duplicate input identities.
        for changed in (saved['job_owner']['inputs'][:-1],saved['job_owner']['inputs']+saved['job_owner']['inputs'][:1],['foreign']+saved['job_owner']['inputs'][1:]):
            bad=copy.deepcopy(saved);bad['job_owner']['inputs']=changed
            with self.subTest(inputs=changed),self.assertRaisesRegex(ValueError,'Node document differs'):
                contracts.plan(bad)

    def test_desktop_admission_accepts_reordered_exact_inputs_but_not_multiplicity_changes(self):
        document=json.loads(contracts.encoded(self.node))
        proposal=persistent_jobs.node_proposal('root',document,BACKEND,self.inputs)
        self.assertEqual(proposal['inputs'],self.inputs)
        for changed in (self.inputs[:-1],self.inputs+self.inputs[:1]):
            with self.assertRaisesRegex(ValueError,'inputs differ'):
                persistent_jobs.node_proposal('root',document,BACKEND,changed)

class Continuation(unittest.TestCase):
    def setUp(self):
        from tests import test_job_owner_loop as fixture
        self.f=fixture.Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        doc=dict(schema_version=1,id='job',operation='model',objective='Write a report',inputs=[],outputs=[dict(name='report',media_type='text/plain',purpose='Report')])
        if self._testMethodName.startswith('test_failed_completion'):
            doc['outputs'].append(dict(name='appendix',media_type='text/plain',purpose='Appendix'))
            self.f.grant['deliverables']['appendix']='text/plain'
        self.f.grant.update(delegation_version=4,execution_policy=dict(version=2,review='owner',public_read=False),execution_review_version=1,node_contract=node_spec.capture(doc))
        self.f.create(request=doc['objective']);self.f.rt.tick('job')
        session=self.f.factory.sessions[self.f.rt.task('job','owner')['latest']]
        self.frozen=session['frozen'];self.control=Path(session['session']['control']);self.control.mkdir(parents=True,exist_ok=True)
        self.files=job_owner.files(self.frozen,self.control)
        self.owner=job_owner.Session(self.frozen,self.control,self.files);self.addCleanup(self.owner.rt.close)

    def test_failed_node_proposal_corrects_through_existing_compiler(self):
        denied=self.owner.call('node_run',dict(tasks=[dict(id='forbidden',operation='not.granted',objective='Forbidden')]))
        self.assertIn('correction',denied)
        self.assertEqual(len(self.f.rt.status('job')['tasks']),1)
        fixed=self.owner.call('node_run',dict(tasks=[dict(id='draft',operation='model',objective='Draft',outputs=[dict(name='text',media_type='text/plain',purpose='Draft')])]))
        self.assertEqual({t['id'] for t in self.f.rt.status('job')['tasks']},{'owner','draft'})
        self.assertEqual(self.owner.call('node_run',dict(tasks=[dict(id='draft',operation='model',objective='Draft',outputs=[dict(name='text',media_type='text/plain',purpose='Draft')])])),fixed)

    def test_failed_completion_retains_ports_across_restart(self):
        self.owner.call('node_result',dict(outputs={'report':{'text':'Saved exact draft'}},summary='Saved',complete=False))
        with self.assertRaisesRegex(ValueError,'Every requested deliverable'):
            self.owner.call('node_result',dict(outputs={},summary='Finish'))
        # Restart retains the first exact port; only the missing port is supplied.
        self.owner.rt.close();self.owner=job_owner.Session(self.frozen,self.control,self.files);self.addCleanup(self.owner.rt.close)
        result=self.owner.call('node_result',dict(outputs={'appendix':{'text':'Additional result'}},summary='Finish'))
        self.assertEqual(result['deliverables']['report']['review_status'],'unreviewed')
        self.assertEqual(len(self.f.rt.db.execute("SELECT id FROM production_events WHERE kind='owner_result_saved'").fetchall()),2)
        self.assertFalse(result['user_acceptance'])

class ExecutorDiscovery(unittest.TestCase):
    def test_gated_catalog_uses_dispatch_check_not_unrelated_shell_discovery(self):
        from task_relay.host import HOST, UnsupportedHost
        class State:
            def get(self, key, default=None):return {'backend':{**BACKEND,'type':'codex-cli'}} if key=='production-planner-policy' else default
        from orchestrator import codex_transport
        with patch.object(HOST,'codex',side_effect=UnsupportedHost('No general shell CLI')), patch.object(codex_transport,'configuration',return_value=({},BACKEND)) as check:
            rows=executors.catalog(State())
            self.assertTrue(next(v for v in rows if v['id']=='codex-agent')['available'])
            self.assertFalse(next(v for v in rows if v['id']=='codex-cli')['available'])
            check.assert_called_once_with(BACKEND)
        with patch.object(HOST,'codex',return_value='/fixture/unrestricted-cli'), patch.object(codex_transport,'configuration',side_effect=ValueError('Missing qualified gate')):
            row=next(v for v in executors.catalog(State()) if v['id']=='codex-agent')
            self.assertFalse(row['available']);self.assertEqual(row['blocker'],'Missing qualified gate')
