"""Reusable drafts, run binding and exact saved graph execution; offline only."""
import copy,hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import node_spec,job_owner,contracts


def workflow():return json.loads(Path('examples/reusable-summary.workflow.json').read_text())


class Contracts(unittest.TestCase):
    def test_draft_is_reusable_values_are_validated_and_defaults_do_not_mutate_it(self):
        w=workflow();original=copy.deepcopy(w)
        view=node_spec.resolve_workflow(w)
        self.assertFalse(view['ready']);self.assertIn('workflow.article_url',view['missing_inputs'])
        for url in ('https://example.com/a','https://example.com/b'):
            bound=node_spec.resolve_workflow(w,{'article_url':url})
            self.assertTrue(bound['ready']);self.assertEqual(bound['tasks'][0]['inputs']['url'],{'value':url})
            self.assertEqual(bound['values']['length'],'Three short paragraphs')
            self.assertEqual(bound['template_sha256'],contracts.digest(w))
        self.assertEqual(w,original)
        for values in ({},{'article_url':False},{'article_url':'https://example.com','paid':True}):
            with self.subTest(values=values),self.assertRaises(ValueError):node_spec.resolve_workflow(w,values)

    def test_custom_types_defaults_optional_and_required(self):
        n=workflow()['tasks'][1];n['inputs'].pop('length')
        n['input_definitions']['length']['default']='Two paragraphs'
        self.assertEqual(node_spec.validate(n)['inputs']['length'],{'value':'Two paragraphs'})
        n['input_definitions']['length']['default']=False
        with self.assertRaisesRegex(ValueError,'expected string'):node_spec.validate(n)
        n['input_definitions']['length'].pop('default');n['input_definitions']['length']['required']=False
        self.assertNotIn('length',node_spec.validate(n)['inputs'])
        n['inputs']['hidden']={'value':1}
        with self.assertRaisesRegex(ValueError,'Undeclared'):node_spec.validate(n)

    def test_invalid_output_media_cycle_duplicate_and_scalar_connection_fail(self):
        def bad_port(w):w['tasks'][1]['inputs']['article']['output']='imaginary'
        def bad_media(w):w['tasks'][1]['input_definitions']['article']['media_type']='image/png'
        def cycle(w):w['tasks'][0]['dependencies']=['summary']
        def duplicate(w):w['tasks'].append(copy.deepcopy(w['tasks'][0]))
        def scalar(w):w['tasks'][0]['inputs']['url']={'task':'summary','output':'summary'}
        def unknown(w):w['tasks'][0]['inputs']['url']={'workflow':'missing'}
        for change in (bad_port,bad_media,cycle,duplicate,scalar,unknown):
            w=workflow();change(w)
            with self.subTest(change=change.__name__),self.assertRaises(ValueError):node_spec.resolve_workflow(w,{'article_url':'https://example.com'})

    def test_registered_schema_cannot_be_overridden_and_unresolved_cannot_run(self):
        w=workflow();w['tasks'][0]['input_definitions']={}
        with self.assertRaisesRegex(ValueError,'Registered operation owns'):node_spec.resolve_workflow(w)
        with self.assertRaises(ValueError):node_spec.legacy_tasks({'tasks':workflow()['tasks']},3)
        w=workflow();w['tasks'][0]['inputs']['offset']={'value':-1}
        with self.assertRaisesRegex(ValueError,'below minimum'):node_spec.resolve_workflow(w)

    def test_artifact_connection_requires_actual_metadata(self):
        n=workflow()['tasks'][1];n['inputs']={'article':{'artifact':'exact'},'length':{'value':'short'}}
        with self.assertRaisesRegex(ValueError,'lookup required'):node_spec.inspect_graph([n])
        with self.assertRaisesRegex(ValueError,'media type'):node_spec.inspect_graph([n],artifact=lambda _:dict(media_type='image/png'))
        self.assertTrue(node_spec.inspect_graph([n],artifact=lambda _:dict(media_type='application/json'))['ready'])

    def test_ui_bridge_uses_same_validator_and_grants_no_execution(self):
        from task_relay.desktop_bridge import dispatch
        view=dispatch('node-validate',{'workflow':workflow()})
        self.assertFalse(view['execution_authorized']);self.assertFalse(view['validation']['ready'])
        view=dispatch('node-validate',{'workflow':workflow(),'values':{'article_url':'https://example.com'}})
        self.assertEqual(view['validation']['connections'][0]['source'],dict(task='article',output='page'))
        with self.assertRaises(ValueError):dispatch('node-validate',{'workflow':workflow(),'values':{}})

    def test_v1_v2_capture_hashes_and_documents_stay_exact(self):
        for version,path in [(1,'examples/summary.node.json'),(2,'examples/read-page.node.json')]:
            n=json.loads(Path(path).read_text());cap=node_spec.capture(n)
            self.assertEqual(node_spec.check_capture(cap),n)
            raw=json.loads(Path('orchestrator/node.v'+str(version)+'.schema.json').read_text())
            expected={k:v for k,v in raw.items() if not k.startswith('$') and k!='title'}
            self.assertEqual(cap['schema_sha256'],contracts.digest(expected))


class SavedGraph(unittest.TestCase):
    def setUp(self):
        from tests.test_job_owner_loop import Tests
        from tests.test_mixed_execution import LocalRegistered,Client
        from orchestrator.adapters import ExecutionFactory
        self.f=Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        class OfflineFactory(ExecutionFactory):
            def available(self,backend):return None
            def create(self,control,workspace,frozen,backend):
                return (self.registered if frozen.get('execution') else self.agents).create(control,workspace,frozen,backend)
        self.ops=LocalRegistered(Client());self.f.rt.factory=OfflineFactory(self.f.factory,self.ops)
        path=Path(self.f.tmp.name).resolve()/'summary.workflow.json';path.write_text(json.dumps(workflow()))
        self.aid=self.f.rt.register(path,'User selected reusable workflow')
        root=dict(schema_version=3,id='request',operation='model',objective='Write a sourced text report.',inputs={'workflow':{'artifact':self.aid}},input_definitions={'workflow':dict(type='artifact',label='Workflow',required=True,media_type='*/*')},outputs=[dict(name='report',media_type='text/markdown',purpose='Summary')])
        self.f.grant.update(deliverables={'report':'text/markdown'},delegation_version=4,operations=['web.fetch'],execution_policy=dict(version=2,review='owner',public_read=True),execution_review_version=1,node_contract=node_spec.capture(root))
        self.f.create(inputs=[dict(artifact=self.aid,path='input/workflow.json',purpose='Workflow',authority='User selected workflow',media_type='application/json')]);self.f.rt.tick('job')
        session=self.f.factory.sessions[self.f.rt.task('job','owner')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
        self.owner=job_owner.Session(session['frozen'],control,job_owner.files(session['frozen'],control));self.addCleanup(self.owner.rt.close)
        self.request=dict(workflow={'artifact':self.aid},values={'article_url':'https://example.com/article'})

    def test_missing_run_value_then_exact_file_compilation_restart_and_delivery(self):
        from task_relay import orchestrator_web
        before=self.f.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0]
        rejected=self.owner.call('node_run',dict(workflow={'artifact':self.aid},values={}))
        self.assertIn('Missing workflow input',rejected['error'])
        self.assertEqual(self.f.rt.db.execute('SELECT count(*) FROM production_tasks').fetchone()[0],before)
        result=self.owner.call('node_run',self.request);self.assertNotIn('error',result,str(result))
        receipt=json.loads(self.f.rt.db.execute("SELECT data FROM production_events WHERE kind='owner_intents_compiled'").fetchone()[0])
        self.assertEqual(receipt['node_request'],self.request)
        self.assertEqual(receipt['workflow_binding']['sha256'],self.f.rt.artifact(self.aid)['sha256'])
        # Identical saved submission returns its receipt rather than duplicate nodes.
        again=self.owner.call('node_run',self.request);self.assertEqual(result['receipt'],again['receipt'])
        with patch.object(orchestrator_web,'download',return_value=('https://example.com/article',b'<h1>Article</h1><p>Retain exact evidence.</p>','text/html','utf-8')):
            self.f.rt.tick('job');self.f.rt.tick('job')
        self.assertEqual(self.f.rt.task('job','article')['status'],'completed')
        aid=self.f.rt.task('job','summary')['latest'];frozen=self.f.factory.sessions[aid]['frozen']
        self.assertIn('Retain exact evidence',(Path(frozen['workspace'])/frozen['inputs'][0]['path']).read_text())
        self.assertIn('Three short paragraphs',frozen['instruction'])
        from orchestrator.runtime import Runtime
        reopened=Runtime(self.f.root,self.f.rt.factory);self.addCleanup(reopened.close)
        self.assertEqual(reopened.task('job','summary')['latest'],aid)
        self.f.factory.finish(aid);reopened.tick('job')
        self.owner.call('node_read',dict(reference={'task':'summary','output':'summary'}))
        result=self.owner.call('node_result',dict(outputs={'report':{'task':'summary','output':'summary'}},summary='Completed synthetic fixture'))
        self.assertFalse(result['user_acceptance']);self.assertEqual(len(self.ops.calls),1)
        from orchestrator.owner_intents import artifact_descriptor
        delivered=self.f.rt.output('job','summary','outputs/summary.md')
        self.assertEqual(artifact_descriptor(self.owner,delivered['id'])['media_type'],'text/markdown')

    def test_typed_exact_attachment_uses_frozen_input_not_untyped_blob_row(self):
        node=workflow()['tasks'][1]
        node['inputs']={'article':{'artifact':self.aid},'length':{'value':'short'}}
        wrong=copy.deepcopy(node);wrong['input_definitions']['article']['media_type']='image/png'
        result=self.owner.call('node_run',{'tasks':[wrong]})
        self.assertIn('Incompatible artifact media type',result['error'])
        result=self.owner.call('node_run',{'tasks':[node]})
        self.assertNotIn('error',result,str(result))

    def test_conflicting_attachment_types_fail_closed(self):
        from orchestrator.owner_intents import artifact_descriptor
        self.owner.frozen['inputs'].append({**self.owner.frozen['inputs'][0],'media_type':'image/png'})
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            artifact_descriptor(self.owner,self.aid)

    def test_tampered_template_never_admitted(self):
        p=Path(self.f.rt.artifact(self.aid)['blob']);p.chmod(0o600);p.write_text('{}')
        result=self.owner.call('node_run',self.request)
        self.assertIn('Saved artifact bytes changed',result['error'])
        self.assertEqual(len(self.f.rt.status('job')['tasks']),1)

    def test_foreign_workflow_cannot_enter_via_file_loader(self):
        path=Path(self.f.tmp.name).resolve()/'foreign.json';path.write_text(json.dumps(workflow()))
        foreign=self.f.rt.register(path,'Not selected by user')
        result=self.owner.call('node_run',dict(workflow={'artifact':foreign},values=self.request['values']))
        self.assertIn('outside this job grant',result['error'])
        self.assertEqual(len(self.f.rt.status('job')['tasks']),1)

class BundleConnections(unittest.TestCase):
    def test_registered_file_bundle_uses_same_output_and_cycle_checks(self):
        w=workflow();w['tasks'][1]['inputs']['length']={'value':'Short'}
        w['tasks'][0]['inputs']['url']={'value':'https://example.com'}
        w['tasks'].append(dict(schema_version=3,id='bundle',operation='text.bundle',objective='Bundle text',inputs={'files':{'value':[{'task':'summary','output':'summary'}]}}))
        from orchestrator.operation_definition import definition
        spec=definition('text.bundle')
        # Supply the registered adapter's own required literal settings.
        for name,rule in spec['inputs']['properties'].items():
            if name!='files':w['tasks'][-1]['inputs'][name]={'value':spec['defaults'].get(name,[] if rule.get('type')=='array' else 'bundle')}
        view=node_spec.inspect_graph(w['tasks'])
        self.assertEqual(view['connections'][-1]['source'],{'task':'summary','output':'summary'})
        w['tasks'][0]['dependencies']=['bundle']
        with self.assertRaisesRegex(ValueError,'cycle'):node_spec.inspect_graph(w['tasks'])
