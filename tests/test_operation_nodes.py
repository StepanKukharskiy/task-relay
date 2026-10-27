"""Same operation through inline tools and Runtime nodes; synthetic transports only."""
import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from orchestrator import node_spec, operation_definition as interface, execution, job_owner
from orchestrator import public_read_operation as reader
from task_relay import orchestrator_web as web,source_browser
from tests import test_read_recovery as read_fixture


class Ports(unittest.TestCase):
    def test_named_file_and_tool_inputs_have_one_schema_and_unknowns_fail(self):
        node=json.loads(Path('examples/read-page.node.json').read_text())
        lowered=node_spec.legacy_tasks({'tasks':[node]},2)['tasks'][0]
        self.assertEqual(lowered['parameters'],dict(url=node['inputs']['url']['value'],**reader.DEFAULTS))
        self.assertEqual(interface.tool('web.fetch')['parameters'],interface.definition('web.fetch')['inputs'])
        self.assertEqual(interface.definition('web.fetch')['outputs']['page']['media_type'],'application/json')
        node['inputs']['cookies']={'value':'secret'}
        with self.assertRaisesRegex(ValueError,'unsupported field'):node_spec.validate(node)

    def test_named_model_inputs_preserve_literals_and_exact_connections(self):
        node=json.loads(Path('examples/summary-named.node.json').read_text())
        node['inputs']['article']={'task':'read','output':'page'}
        lower=node_spec.legacy_tasks({'tasks':[node]},2)['tasks'][0]
        self.assertEqual(lower['inputs'],[{'task':'read','output':'page'}])
        self.assertIn('Three short paragraphs',lower['instruction'])
        self.assertIn('article',lower['instruction'])
        cap=node_spec.capture(node);self.assertEqual(node_spec.presentation(cap)['document'],node)
        cap['operation_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'Changed operation'):node_spec.check_capture(cap)

    def test_all_registered_native_ports_are_derived_without_new_handlers(self):
        for cap in execution.REGISTRY:
            with self.subTest(cap=cap):
                d=interface.definition(cap)
                self.assertEqual(set(d['outputs']),set(__import__('orchestrator.owner_intents',fromlist=['ports']).ports(dict(outputs=__import__('orchestrator.owner_intents',fromlist=['native_outputs']).native_outputs(cap)))))
                self.assertIsNotNone(execution.adapter(cap).handler)

    def test_version_one_capture_is_unchanged_and_never_promoted(self):
        node=json.loads(Path('examples/summary.node.json').read_text())
        cap=node_spec.capture(node)
        self.assertEqual(cap['version'],1);self.assertEqual(node_spec.check_capture(cap),node)
        self.assertNotIn('operation_sha256',cap)

    def test_content_definition_exposes_both_actual_compiler_outputs(self):
        from orchestrator.owner_intents import content_outputs,ports
        declared=interface.definition('collection.subjects')
        self.assertEqual(declared['outputs'],ports(dict(outputs=content_outputs('collection.subjects'))))
        self.assertEqual(set(declared['outputs']),{'result','result_summary'})


class Catalog(unittest.TestCase):
    def test_categories_are_complete_presentation_only_and_task_oriented(self):
        rows=interface.catalog()
        self.assertEqual({r['category'] for r in rows},set(interface.CATEGORIES))
        for r in rows:
            self.assertEqual(r['category_order'],interface.CATEGORIES.index(r['category']))
            self.assertNotIn('category',r['definition'])
            self.assertEqual(r['definition'],interface.definition(r['id']))
        categories={r['id']:r['category'] for r in rows}
        for op,category in {
            'model':'AI & text','gemini.text':'AI & text','web.fetch':'Web & research',
            'gemini.image':'Images','higgsfield.image':'Images','higgsfield.video':'Video & audio',
            'blender.animate':'3D & CAD','rhino.render':'3D & CAD',
            'images.pptx':'Documents & presentations','collection.slides':'Documents & presentations',
            'collection.subjects':'Data','records.merge':'Data',
        }.items():self.assertEqual(categories[op],category)

    def content_node(self,operation):
        settings=(dict(max_records=3,fields=[]) if operation=='collection.subjects' else
                  dict(renderer='pptx.create',title='Example',style='clean_minimal_v1',max_records=3))
        inputs={'parameters':{'value':settings}}
        if operation=='collection.subjects':inputs['source_path']={'artifact':'source'}
        return dict(schema_version=3,id='content',objective='Create content',operation=operation,inputs=inputs)

    def test_default_catalog_hides_only_registered_legacy_choices(self):
        normal={r['id'] for r in interface.catalog()}
        complete={r['id'] for r in interface.catalog(include_legacy=True)}
        self.assertEqual(complete-normal,{'sourcing.merge','sourcing.slides'})
        self.assertTrue({'web.sources','web.sources.codex','web.sources.native','web.sources.rendered','images.products','images.catalog'}<=normal)
        self.assertNotIn('research.batch',complete)
        for old,new in [('sourcing.merge','records.merge'),('sourcing.slides','collection.slides')]:
            self.assertEqual(interface.definition(old)['id'],old)
            self.assertEqual(interface.presentation(old)['replaced_by'],new)

    def test_labels_preserve_wire_schema_and_saved_connector_pins(self):
        from orchestrator import connector_protocol,contracts
        for operation,spec in execution.REGISTRY.items():
            with self.subTest(operation=operation):
                declared=interface.definition(operation);shown=interface.presentation(operation)
                self.assertEqual(set(shown['inputs']),set(declared['inputs']['properties']))
                self.assertEqual(set(shown['outputs']),set(declared['outputs']))
                for name,field in shown['inputs'].items():
                    self.assertEqual(field['schema'],declared['inputs']['properties'][name])
                    self.assertNotIn(field['label'],('Files','Result'))
                for field in shown['outputs'].values():self.assertNotEqual(field['label'],'Result')
                before=connector_protocol.capture(operation)
                historical={k:v for k,v in spec.items() if k!='node_ui'}
                self.assertEqual(before['definition_sha256'],connector_protocol.interface(operation,historical)['definition_sha256'])
                with patch.dict(spec,node_ui={'title':'A different UI name'}):
                    self.assertEqual(connector_protocol.capture(operation),before)
                    self.assertEqual(contracts.digest(interface.definition(operation)),contracts.digest(declared))
                changed=copy.deepcopy(historical);changed['seconds']+=1
                self.assertNotEqual(before['definition_sha256'],connector_protocol.interface(operation,changed)['definition_sha256'])

    def test_baseline_is_advertised_only_when_supported_and_granted(self):
        from orchestrator import operation_contracts
        for grant,wanted in [(None,True),({},False),({'coordination_version':1,'delegation_version':3},False),({'coordination_version':1,'delegation_version':4},True)]:
            for operation in ('collection.subjects','document.layout','collection.options'):
                expected=wanted and operation=='collection.options'
                self.assertEqual('baseline' in interface.definition(operation,grant)['inputs']['properties'],expected)
                self.assertEqual(operation_contracts.baseline_supported(operation,grant),expected)
        for operation in ('collection.subjects','document.layout'):
            node=self.content_node(operation);node['inputs']['baseline']={'artifact':'old'}
            with self.assertRaisesRegex(ValueError,'unsupported field'):node_spec.validate(node)
            with self.assertRaisesRegex(ValueError,'Unknown input'):node_spec.inspect_graph([node],artifact=lambda _:dict(media_type='application/json'))

    def test_exact_historical_content_captures_reload_without_unsupported_baseline(self):
        hashes={'collection.subjects':'1ab0e81726d7291714563b2177f60b1658e936a99f67284c2811bae250b78884',
                'document.layout':'984d99ca5d93dd6fc76bb05330ac5f41391df9f7a232b8daac05b12179539e6b'}
        for operation,old_hash in hashes.items():
            node=self.content_node(operation);cap=node_spec.capture(node);cap['operation_sha256']=old_hash
            saved=json.dumps(cap,sort_keys=True)
            self.assertEqual(node_spec.check_capture(json.loads(saved)),node)
            self.assertNotIn('baseline',node_spec.presentation(cap)['operation']['inputs']['properties'])
            self.assertEqual(json.dumps(cap,sort_keys=True),saved)
            bad=copy.deepcopy(cap);bad['document']['inputs']['baseline']={'artifact':'old'}
            with self.assertRaisesRegex(ValueError,'Changed operation'):node_spec.check_capture(bad)
            bad=copy.deepcopy(cap);bad['operation_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'Changed operation'):node_spec.check_capture(bad)

    def test_supported_correction_subset_uses_same_graph_and_lowering_schema(self):
        node=dict(schema_version=3,id='repair',objective='Correct catalog',operation='collection.options',inputs={
            'inventory_path':{'artifact':'inventory'},'source_pack_path':{'artifact':'sources'},
            'baseline':{'artifact':'baseline'},'parameters':{'value':{'options_per_item':3}}})
        grant=dict(coordination_version=1,delegation_version=4)
        checked=node_spec.inspect_graph([node],grant=grant,artifact=lambda _:dict(media_type='application/json'))
        self.assertTrue(checked['ready'])
        self.assertEqual(interface.lower(node,grant)['content']['parameters'],{'options_per_item':3})
        with self.assertRaises(ValueError):node_spec.inspect_graph([node],grant={},artifact=lambda _:dict(media_type='application/json'))
        node['inputs']['parameters']['value']['invented']=True
        with self.assertRaisesRegex(ValueError,'unsupported field'):node_spec.validate(node,grant)

    def test_display_names_are_not_new_aliases_or_graph_outputs(self):
        node=dict(schema_version=3,id='crop',objective='Crop image',operation='images.crop',inputs={
            'files':{'value':[{'artifact':'image'}]},'region':{'value':[0,0,10,10]}})
        cap=node_spec.capture(node)
        self.assertEqual(node_spec.presentation(cap)['presentation']['inputs']['files']['label'],'Source image')
        self.assertEqual(node_spec.presentation(cap)['presentation']['outputs']['result']['label'],'Cropped image')
        self.assertEqual(node_spec.check_capture(json.loads(json.dumps(cap))),node)
        self.assertTrue(node_spec.inspect_graph([node],artifact=lambda _:dict(media_type='image/png'))['ready'])
        bad=copy.deepcopy(node);bad['inputs']['source_image']=bad['inputs'].pop('files')
        with self.assertRaises(ValueError):node_spec.validate(bad)

    def test_desktop_catalog_is_read_only_and_uses_registered_projection(self):
        from task_relay.desktop_bridge import dispatch
        value=dispatch('node-catalog',{})
        self.assertFalse(value['execution_authorized']);self.assertEqual(value['operations'],interface.catalog())
        self.assertEqual(dispatch('node-catalog',{'include_legacy':True})['operations'],interface.catalog(include_legacy=True))
        for args in ({'include_legacy':'yes'},{'run':'existing'},None):
            with self.assertRaises(ValueError):dispatch('node-catalog',args)


class SharedReads(unittest.TestCase):
    def setUp(self):
        self.f=read_fixture.Recovery();self.f.setUp();self.addCleanup(self.f.doCleanups)
        root=Path(self.f.tmp.name)
        self.ctx=SimpleNamespace(frozen=dict(workspace=str(root/'runtime/workspaces/read'),run='job',execution={'parameters':dict(url=self.f.url,**reader.DEFAULTS)}))
        self.f.receipt=root/'runtime/owner-context/job/public-reads.json'

    def test_inline_then_node_restart_reuses_exact_outcome_and_single_allowance(self):
        with patch.object(source_browser,'read_http',side_effect=ValueError('403')) as h,patch.object(source_browser,'render',side_effect=self.f.render) as r:
            first=self.f.session().execute(dict(name='web_fetch',arguments=json.dumps(dict(url=self.f.url))))
            second=json.loads(reader.execute(self.ctx).data)
            self.assertEqual(first,second);self.assertEqual((h.call_count,r.call_count),(1,1))
            self.assertEqual(second['recovery']['methods_used'],2)
            for n in range(2):
                self.ctx.frozen['execution']['parameters']['url']='https://example.com/'+str(n)
                reader.execute(self.ctx)
            exhausted=self.f.call('https://example.com/last')
            self.assertEqual(exhausted['outcome'],'exhausted');self.assertEqual((h.call_count,r.call_count),(3,3))

    def test_uncertain_inline_read_cannot_be_replayed_as_node(self):
        from orchestrator.runtime_outcomes import UncertainOperation
        with patch.object(source_browser,'read_http',side_effect=UncertainOperation('missing receipt')) as h:
            self.assertEqual(self.f.call()['outcome'],'uncertain')
            with self.assertRaises(UncertainOperation):reader.execute(self.ctx)
            self.assertEqual(h.call_count,1)

    def test_concurrent_entry_is_no_effect_and_does_not_spend_allowance(self):
        from task_relay.host import HOST
        root=self.f.receipt.with_suffix('');root.mkdir(parents=True)
        with (root/'reader.lock').open('a+b') as lock,patch.object(source_browser,'read_http') as h:
            HOST.lock(lock)
            result=self.f.call()
            self.assertFalse(result['action_taken']);self.assertIn('Another public read',result['error']);h.assert_not_called()
            scheduled=json.loads(reader.execute(self.ctx).data)
            self.assertFalse(scheduled['action_taken']);self.assertIn('Another public read',scheduled['error']);h.assert_not_called()
        self.assertEqual(list(root.glob('*/*-claim.json')),[])


class Composed(unittest.TestCase):
    def test_real_runtime_read_node_to_model_binding_and_saved_result(self):
        from tests.test_job_owner_loop import Tests as Fixture
        from tests.test_mixed_execution import LocalRegistered,Client
        from orchestrator.adapters import ExecutionFactory
        f=Fixture();f.setUp();self.addCleanup(f.doCleanups)
        node=dict(schema_version=2,id='request',objective='Write a sourced text report.',operation='model',inputs={},outputs=[dict(name='report',media_type='text/plain',purpose='Summary')])
        f.grant.update(delegation_version=4,operations=['web.fetch'],execution_policy=dict(version=2,review='owner',public_read=True),execution_review_version=1,node_contract=node_spec.capture(node))
        class OfflineFactory(ExecutionFactory):
            def available(self,backend):return None
            def create(self,control,workspace,frozen,backend):
                return (self.registered if frozen.get('execution') else self.agents).create(control,workspace,frozen,backend)
        ops=LocalRegistered(Client());f.rt.factory=OfflineFactory(f.factory,ops)
        f.create();f.rt.tick('job')
        s=f.factory.sessions[f.rt.task('job','owner')['latest']];control=Path(s['session']['control']);control.mkdir(parents=True,exist_ok=True)
        owner=job_owner.Session(s['frozen'],control,job_owner.files(s['frozen'],control));self.addCleanup(owner.rt.close)
        read=dict(schema_version=2,id='article',objective='Read article',operation='web.fetch',inputs={'url':{'value':'https://example.com/article'}})
        write=dict(schema_version=2,id='summary',objective='Summarise the exact page',operation='model',inputs={'article':{'task':'article','output':'page'}},outputs=[dict(name='text',media_type='text/plain',purpose='Summary')])
        denied=copy.deepcopy(read);denied['operation']='text.bundle';denied['inputs']={}
        rejected=owner.call('node_run',dict(tasks=[denied]))
        self.assertIn('error',rejected)
        self.assertEqual(rejected['correction']['proposal'],dict(tasks=[denied]))
        self.assertEqual(len(f.rt.status('job')['tasks']),1)
        result=owner.call('node_run',dict(tasks=[read,write]));self.assertNotIn('error',result,str(result))
        with patch.object(web,'download',return_value=('https://example.com/article',b'<h1>Article</h1><p>Retain exact evidence.</p>','text/html','utf-8')):
            f.rt.tick('job');f.rt.tick('job')
        self.assertEqual(f.rt.task('job','article')['status'],'completed')
        aid=f.rt.task('job','summary')['latest'];self.assertIsNotNone(aid)
        frozen=f.factory.sessions[aid]['frozen'];self.assertIn('Retain exact evidence',(Path(frozen['workspace'])/frozen['inputs'][0]['path']).read_text())
        f.factory.finish(aid);f.rt.tick('job')
        owner.call('node_read',dict(reference={'task':'summary','output':'text'}))
        result=owner.call('node_result',dict(outputs={'report':{'task':'summary','output':'text'}},summary='Done'))
        self.assertFalse(result['user_acceptance']);self.assertEqual(len(ops.calls),1)
