"""Canvas compilation uses the existing preparation writer, without dispatch."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import prepared_contract, producer_binding
from orchestrator.runtime import Runtime
from task_relay import desktop_node_runs as runs


def workflow(target='blender.mesh_scene'):
    return dict(schema_version=1,kind='workflow',inputs={},tasks=[
        dict(schema_version=3,id='geometry',operation='model',objective='Model the supplied object',
             inputs={},input_definitions={},outputs=[dict(name='geometry',media_type='application/json',purpose='Geometry')],
             model=dict(provider='codex',id='gpt-6.1-sol')),
        dict(schema_version=3,id='build',operation=target,objective='Build prepared geometry',
             inputs={'files':{'value':[{'task':'geometry','output':'geometry'}]}})])


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.rt=Runtime(self.tmp.name);self.addCleanup(self.rt.close)
        for p in (patch('orchestrator.executors.available'),patch('orchestrator.execution.available')):
            p.start();self.addCleanup(p.stop)

    def compile(self,w,**kw):
        return runs.compile_plan(self.rt,w,{},'fixture','Geometry',**kw)['plan']

    def test_registered_consumers_bind_schema_without_extra_nodes_or_limits(self):
        for target in ('blender.mesh_scene','blender.scene','rhino3dm.create'):
            with self.subTest(target=target):
                w=workflow(target);original=copy.deepcopy(w);p=self.compile(w)
                self.assertEqual(w,original)
                self.assertEqual([t['id'] for t in p['tasks']],['geometry','build'])
                model,native=p['tasks']
                self.assertEqual(model['operation_contract']['parameters']['target'],target)
                self.assertEqual(model['operation_contract']['id'],'operation.preparation')
                self.assertEqual(model['limits']['tool_calls'],24)
                self.assertEqual(model['limits']['provider_requests'],24)
                self.assertEqual(native['dependencies'],['geometry'])
                self.assertTrue(prepared_contract.schema(model['operation_contract']['parameters'])['anyOf'])

    def test_incompatible_consumers_reject_before_admission(self):
        w=workflow();other=copy.deepcopy(w['tasks'][1]);other.update(id='other',operation='rhino3dm.create')
        w['tasks'].append(other)
        with self.assertRaisesRegex(ValueError,'incompatible producer schemas'):self.compile(w)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_selected_model_inherits_downstream_contract_without_scheduling_consumer(self):
        context=workflow()
        selected=copy.deepcopy(context);selected['tasks']=selected['tasks'][:1]
        p=self.compile(selected,schema_workflow=context)
        self.assertEqual([t['id'] for t in p['tasks']],['geometry'])
        self.assertEqual(p['tasks'][0]['operation_contract'],self.compile(context)['tasks'][0]['operation_contract'])

    def test_native_validator_rejects_malformed_geometry_before_host(self):
        p=self.compile(workflow())
        with self.assertRaises(ValueError):
            producer_binding.validate_content(p['tasks'][1],lambda path:b'{"version":2,"objects":[]}')

    def test_unconnected_model_keeps_declared_output_and_normal_writer(self):
        w=workflow();w['tasks']=w['tasks'][:1]
        p=self.compile(w)
        self.assertNotIn('operation_contract',p['tasks'][0])
        self.assertNotIn('content_contract',p['tasks'][0]['outputs'][0])

    def test_model_consumer_capabilities_do_not_block_selected_text_producer(self):
        w=workflow()
        w['tasks'][1]=dict(schema_version=3,id='later',operation='model',objective='Later media task',
            inputs={'notes':{'task':'geometry','output':'geometry'}},
            input_definitions={'notes':dict(type='artifact',label='Notes',media_type='application/json',required=True)},
            outputs=[dict(name='image',media_type='image/png',purpose='Image')],
            model=dict(provider='codex',id='gpt-6.1-sol'))
        selected=runs.scope_execution(self.rt,dict(workflow=w,title='Fixture'),
            dict(scope='geometry',values={}),lambda ident:None)
        self.assertIsNone(selected['schema_workflow'])
        p=self.compile(selected['workflow'],schema_workflow=selected['schema_workflow'])
        self.assertEqual([t['id'] for t in p['tasks']],['geometry'])
        self.assertNotIn('operation_contract',p['tasks'][0])
        with self.assertRaisesRegex(ValueError,'No eligible worker'):self.compile(w)

    def test_selected_registered_consumer_still_supplies_contract(self):
        w=workflow()
        selected=runs.scope_execution(self.rt,dict(workflow=w,title='Fixture'),
            dict(scope='geometry',values={}),lambda ident:None)
        self.assertIsNotNone(selected['schema_workflow'])
        p=self.compile(selected['workflow'],schema_workflow=selected['schema_workflow'])
        self.assertEqual([t['id'] for t in p['tasks']],['geometry'])
        self.assertEqual(p['tasks'][0]['operation_contract']['parameters']['target'],'blender.mesh_scene')
