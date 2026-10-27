"""Admission extensions and failures, with small artifacts and no real providers."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from orchestrator import execution, connector_protocol, parameter_contracts
from orchestrator.operation_adapters import Adapter, object_schema
from orchestrator.runtime import Runtime, file_hash
from tests.test_orchestrator import FakeFactory, plan


def assignment(capability, parameters, inputs=(), ident='produce', dependencies=()):
    spec=execution.REGISTRY[capability]
    ports=spec.get('outputs') or {'output.txt':spec['output_type']}
    return dict(id=ident,role=spec['kind'],objective='Exercise registered admission',
        instruction='Use exact declared inputs',execution=dict(capability=capability,version=spec['version'],parameters=parameters),
        inputs=list(inputs),outputs=[dict(path=p,media_type=m,purpose='Result') for p,m in ports.items()],
        criteria=copy.deepcopy(spec['criteria']),dependencies=list(dependencies))


def declared_text(ident='source'):
    return dict(artifact=ident,path='input.txt',media_type='text/plain',purpose='Exact source',authority='Data only')


def needs_two_inputs(value, spec):
    if len(value['inputs'])!=2:raise ValueError('Fixture requires two bound inputs')


class ContractTests(unittest.TestCase):
    def test_every_advertised_operation_has_a_valid_executable_parameter_contract(self):
        # Advertising parameters without a validator previously returned None.
        for name,spec in execution.REGISTRY.items():
            with self.subTest(name=name):
                schema=execution.parameter_schema(name)
                parameter_contracts.check(schema)
                self.assertEqual(set(schema['required']),set(spec['parameters'])-set(spec.get('optional_parameters',[])))
                bad=dict(schema,notARealConstraint=True)
                with patch.dict(execution.ADAPTERS,{name:replace(execution.adapter(name),parameters=bad)}):
                    with self.assertRaisesRegex(ValueError,'vocabulary'):connector_protocol.capture(name)

    def test_nested_wire_errors_fail_before_domain_hooks(self):
        cases=[('web.sources',dict(queries=['desk'],domains='example.com',model='model')),
               ('web.sources',dict(queries=['desk','desk'],domains=[],model='model')),
               ('web.sources.rendered',dict(domains=[],max_pages=True)),
               ('gemini.text',dict(model='model',max_output_tokens=4097)),
               ('images.collect',dict(subjects=[dict(id='desk',label='Desk',query='desk',extra='unregistered')])),
               ('images.collect',dict(subjects=[dict(id='desk',label='Desk',query='desk',exclude_titles=[7])])),
               ('rhino.grasshopper',dict(scene_sha256='a'*64,script_sha256='b'*64,checks_sha256='c'*64,permissions='unrestricted_host')),
               ('runway.video',dict(model='gen4.5',prompt='A fixture',aspect_ratio='16:9',duration=2.5))]
        for name,params in cases:
            with self.subTest(name=name,params=params):
                adapter=execution.adapter(name)
                hook=Mock()
                with self.assertRaisesRegex(ValueError,'parameters'):
                    replace(adapter,validators=(hook,)).validate(assignment(name,params),execution.REGISTRY[name])
                hook.assert_not_called()

    def test_schema_does_not_replace_semantic_input_validation(self):
        params=dict(subjects=[dict(id='desk',label='Desk',query='desk'),dict(id='desk',label='Other',query='table')])
        value=assignment('images.collect',params)
        value['outputs'][0]['path']='photos.zip'
        parameter_contracts.validate(params,execution.parameter_schema('images.collect'))
        with self.assertRaisesRegex(ValueError,'unique safe slugs'):execution.validate(value)
        value=assignment('pptx.create',{},[declared_text()])
        value['outputs'][0]['path']='deck.pptx'
        with self.assertRaisesRegex(ValueError,'exactly one JSON'):execution.validate(value)

    def test_optional_subject_fields_and_nullable_hashes_remain_supported(self):
        value=assignment('images.collect',dict(subjects=[dict(id='desk',label='Desk',query='desk')]))
        value['outputs'][0]['path']='photos.zip'
        execution.validate(value)
        for name in ('rhino.run_python','rhino3dm.run_python','sketchup.run_ruby'):
            parameter_contracts.validate(dict(scene_sha256=None,script_sha256='b'*64,checks_sha256='c'*64,
                permissions='unrestricted_host'),execution.parameter_schema(name))
        with self.assertRaises(ValueError):
            parameter_contracts.validate(dict(scene_sha256=None,script_sha256='b'*64,checks_sha256='c'*64,
                permissions='unrestricted_host'),execution.parameter_schema('blender.run_python'))

    def test_schema_constraints_are_enforced_and_unsupported_keywords_fail_closed(self):
        schema=object_schema(dict(value=dict(anyOf=[dict(type='integer',minimum=2,maximum=3),dict(type='null')]),
            labels=dict(type='array',minItems=1,maxItems=2,uniqueItems=True,items=dict(type='string',minLength=2,maxLength=4,pattern='^[a-z]+$'))))
        parameter_contracts.check(schema)
        parameter_contracts.validate(dict(value=2,labels=['ab']),schema)
        parameter_contracts.validate(dict(value=None,labels=['ab','cd']),schema)
        for value in (True,1,4,float('nan'),float('inf'),'2'):
            with self.subTest(value=value),self.assertRaises(ValueError):parameter_contracts.validate(dict(value=value,labels=['ab']),schema)
        for labels in ([],['a'],['abcde'],['AB'],['ab','ab'],['ab','cd','ef']):
            with self.subTest(labels=labels),self.assertRaises(ValueError):parameter_contracts.validate(dict(value=2,labels=labels),schema)
        for bad in (dict(type='string',format='uri'),dict(type='array',items=dict(type='integer'),minItems=True),
                    dict(type='integer',minimum=5,maximum=2),dict(type='object',required=['absent']),
                    dict(type='string',minimum=1)):
            with self.subTest(schema=bad),self.assertRaises(ValueError):parameter_contracts.check(bad)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.factory=FakeFactory();self.rt=Runtime(self.root/'runtime',self.factory)
        source=self.root/'source.txt';source.write_text('Small text fixture')
        self.source=self.rt.register(source,'Fixture',path='input.txt')

    def tearDown(self):self.rt.close();self.temp.cleanup()

    def test_json_inventory_bundle_preserves_literal_bytes_and_identity(self):
        from orchestrator.step_runner import execute
        raw=b'{\n  "dimensions": [1, 2, 3], "label": "quoted \\"part\\""\n}\n'
        source=self.root/'inspection.json';source.write_bytes(raw)
        aid=self.rt.register(source,'Exact native inventory',path=source.name)
        item=dict(artifact=aid,path=source.name,media_type='application/json',purpose='Inspection handoff',authority='Unaccepted evidence')
        self.rt.create(plan([assignment('text.bundle',{},[item])]))
        self.rt.tick('demo');state=self.factory.sessions[self.rt.task('demo','produce')['latest']]
        control=Path(state['session']['control']);control.mkdir(parents=True)
        self.assertEqual(execute(state['frozen'],control)['outcome'],'completed')
        output=Path(state['frozen']['workspace'])/'output.txt'
        header,body=output.read_bytes().split(b'\n',1)
        self.assertEqual(body,raw)
        self.assertIn(aid,header.decode());self.assertIn(file_hash(source),header.decode())
        self.assertEqual(source.read_bytes(),raw)

    def test_invalid_parameters_leave_no_partial_graph_or_worker(self):
        name='records.merge';params=dict(inventory_path='input.json',source_pack_path='input.json',max_records='forty',
            options_per_item=3,count_policy='target',catalog_paths=['input.json'],review_paths=['input.json'],
            field_definitions={'name':'text'},identity_field='name')
        source=self.root/'source.json';source.write_text('{}')
        aid=self.rt.register(source,'JSON fixture',path='input.json')
        inputs=[dict(artifact=aid,path='input'+str(n)+'.json',media_type='application/json',purpose='Fixture',authority='Data') for n in range(4)]
        value=assignment(name,params,inputs)
        with self.assertRaisesRegex(ValueError,'parameters.max_records'):
            self.rt.create(plan([assignment('text.bundle',{},[declared_text(self.source)],ident='first'),value]))
        for table in ('production_runs','production_tasks','production_assignments','production_attempts'):
            self.assertEqual(self.rt.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_new_admission_adapter_composes_and_resumes_without_core_changes(self):
        # Transport is controlled; this establishes admission/identity extension,
        # not arbitrary new live execution support in step_runner.
        name='fixture.combine';spec=copy.deepcopy(execution.REGISTRY['text.bundle'])
        spec['parameters']={'copies':'Integer copies'}
        adapter=Adapter(object_schema(dict(copies=dict(type='integer',minimum=1,maximum=2))),validators=(needs_two_inputs,))
        with patch.dict(execution.REGISTRY,{name:spec}),patch.dict(execution.ADAPTERS,{name:adapter}):
            first=assignment('text.bundle',{},[declared_text(self.source)],ident='first')
            inputs=[declared_text(self.source),dict(from_task='first',output='output.txt',path='prior.txt',media_type='text/plain',purpose='Prior output',authority='Data')]
            second=assignment(name,dict(copies=2),inputs,ident='second',dependencies=['first'])
            with self.assertRaisesRegex(ValueError,'two bound inputs'):
                execution.validate(assignment(name,dict(copies=2),inputs[:1]))
            self.rt.create(plan([first,second]));self.rt.tick('demo')
            parent=self.rt.task('demo','first')['latest'];self.factory.finish(parent)
            self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory)
            self.rt.tick('demo');child=self.rt.task('demo','second')['latest']
            self.assertIsNotNone(child)
            bound=json.loads(self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(child,)).fetchone()[0])
            produced=self.rt.db.execute('SELECT id FROM production_artifacts WHERE attempt=?',(parent,)).fetchone()[0]
            self.assertEqual(bound['inputs'][1]['artifact'],produced)
            self.factory.finish(child);self.assertEqual(self.rt.tick('demo')['status'],'completed')
            self.rt.tick('demo');self.assertEqual(self.factory.calls,[parent,child])

    def test_adapter_policy_drift_after_restart_blocks_before_dispatch(self):
        self.rt.create(plan([assignment('text.bundle',{},[declared_text(self.source)])]))
        original=self.rt.spec(self.rt.task('demo','produce'))
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory)
        adapter=execution.adapter('text.bundle')
        for changed in (replace(adapter,version=2),replace(adapter,validators=(needs_two_inputs,)),replace(adapter,max_attempts=2)):
            with self.subTest(adapter=changed),patch.dict(execution.ADAPTERS,{'text.bundle':changed}):
                with self.assertRaisesRegex(ValueError,'changed since capture'):execution.validate(copy.deepcopy(original))
        with patch.dict(execution.ADAPTERS,{'text.bundle':replace(adapter,version=2)}):self.rt.tick('demo')
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.rt.spec(self.rt.task('demo','produce')),original)

    def test_missing_execution_handler_cannot_fall_back_to_text_or_a_provider(self):
        from orchestrator.step_runner import execute
        for kind in ('procedure','api'):
            name='fixture.'+kind;spec=copy.deepcopy(execution.REGISTRY['text.bundle']);spec['kind']=kind
            with self.subTest(kind=kind),patch.dict(execution.REGISTRY,{name:spec}),patch.dict(execution.ADAPTERS,{name:Adapter(object_schema({}))}):
                value=assignment(name,{},[declared_text(self.source)])
                # Admission alone is not transport registration. Exercise the
                # real child entrypoint with a small frozen local input.
                frozen=copy.deepcopy(value);execution.validate(frozen)
                frozen.update(workspace=str(self.root),runtime_sources={p.name:file_hash(p) for p in Path(execution.__file__).parent.glob('*.py')})
                (self.root/'input.txt').write_text('Small text fixture')
                frozen['inputs'][0]['sha256']=file_hash(self.root/'input.txt')
                transport=Mock();config=Mock()
                with patch('task_relay.host.verify_support'),self.assertRaisesRegex(ValueError,'No execution handler'):
                    execute(frozen,self.root,transport,config)
                transport.assert_not_called();config.assert_not_called()
                self.assertFalse((self.root/'output.txt').exists())
                self.assertFalse((self.root/'request.json').exists())

    def test_adapter_implementation_change_stops_child_before_output(self):
        from orchestrator.step_runner import execute
        value=assignment('text.bundle',{},[declared_text(self.source)])
        execution.validate(value)
        value.update(workspace=str(self.root),runtime_sources={p.name:file_hash(p) for p in Path(execution.__file__).parent.glob('*.py')})
        for module in ('operation_adapters.py','operation_validators.py','parameter_contracts.py'):
            with self.subTest(module=module):
                frozen=copy.deepcopy(value);frozen['runtime_sources'][module]='0'*64
                with patch('task_relay.host.verify_support'),self.assertRaisesRegex(ValueError,'implementation changed'):
                    execute(frozen,self.root)
                self.assertFalse((self.root/'output.txt').exists())


if __name__=='__main__':unittest.main()
