"""Proposal correction uses registered content ports; no provider/native calls."""
import copy
import unittest
import uuid
from unittest.mock import patch
from orchestrator.workflow_proposal import record
from orchestrator.operation_definition import catalog
from tests import test_chat_work_node as fixture
from tests.test_canvas_schema_handoff import workflow


def reply(media='text/markdown'):
    w=workflow('pptx.create')
    w['tasks'][0]['outputs'][0]['media_type']=media
    return dict(kind='work',message='Prepare and export slides.',workflow=w)


class Handoff(unittest.TestCase):
    def test_preparation_baseline_identity_checked_before_commit(self):
        from tests.test_animation_handoff import graph
        w=graph();value=dict(kind='work',message='Animate saved scene',workflow=w)
        ctx=dict(reply_contract_version=5,model=dict(provider='codex',id='gpt-6.1-sol'))
        self.assertEqual(record(value,{},ctx),'reply')
        source=w['tasks'][2];original=copy.deepcopy(source)
        source['inputs'].clear();source['input_definitions'].clear()
        with self.assertRaisesRegex(ValueError,'prepare.*same exact baseline'):
            record(value,{},ctx)
        self.assertEqual(record(value,{},dict(ctx,reply_contract_version=4)),'reply')
        w['tasks'][2]=original
        self.assertEqual(record(value,{},ctx),'reply')

    def test_unreadable_movie_rejects_before_commit_but_image_is_supported(self):
        node=dict(schema_version=3,id='explain',operation='model',objective='Explain supplied evidence',inputs={'evidence':{'artifact':'saved'}},
                  input_definitions={'evidence':dict(type='artifact',media_type='*/*',label='Evidence',required=True)},
                  outputs=[dict(name='notes',media_type='text/markdown',purpose='Notes')])
        value=dict(kind='work',message='Explain evidence',workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[node]))
        context=dict(reply_contract_version=4,model=dict(provider='codex',id='gpt-6.1-sol'),artifacts={'saved':dict(media_type='video/mp4')})
        with self.assertRaisesRegex(ValueError,'explain.*No eligible worker'):record(value,{},context)
        self.assertEqual(record(value,{},dict(context,reply_contract_version=3)),'reply')
        context['artifacts']['saved']['media_type']='image/png'
        self.assertEqual(record(value,{},context),'reply')

    def test_future_script_media_is_checked_without_retyping_source(self):
        from tests.test_script_runtime_handoff import Handoff as ScriptFixture
        w=ScriptFixture().graph();ident=w['tasks'][0]['id']
        w['tasks'][0]['outputs'][0]['media_type']='text/plain'
        for node in w['tasks']:
            for name,binding in node['inputs'].items():
                if binding.get('task')==ident and binding.get('output')=='script' and name in node.get('input_definitions',{}):
                    node['input_definitions'][name]['media_type']='text/plain'
        before=copy.deepcopy(w)
        with self.assertRaisesRegex(ValueError,'must declare text/x-python'):
            record(dict(kind='work',message='Script graph',workflow=w),{}, dict(reply_contract_version=3))
        self.assertEqual(w,before)

    def test_prose_rejected_at_proposal_with_specific_consumer(self):
        value=reply();before=copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,r'build \(pptx.create\).*application/json.*document.layout'):
            record(value,{},dict(reply_contract_version=3))
        self.assertEqual(value,before)
        self.assertEqual(record(value,{},dict(reply_contract_version=2)),'reply')

    def test_registered_contracts_exposed_and_compatible_proposals_accepted(self):
        row=next(r for r in catalog() if r['id']=='pptx.create')
        self.assertEqual(row['handoffs'][0]['families'],['document.layout'])
        for cap in ('pptx.create','blender.scene','rhino3dm.create'):
            value=reply('application/json');value['workflow']['tasks'][1]['operation']=cap
            self.assertEqual(record(value,{},dict(reply_contract_version=3)),'reply')

    def test_ambiguous_json_and_multioutput_preparation_reject(self):
        value=reply('application/json');w=value['workflow']
        w['tasks'][0]['outputs'].append(dict(name='extra',media_type='application/json',purpose='Extra'))
        w['tasks'][1]['inputs']['files']['value'].append(dict(task='geometry',output='extra'))
        with self.assertRaisesRegex(ValueError,'exactly one'):record(value,{}, dict(reply_contract_version=3))
        w['tasks'][1]['inputs']['files']['value'].pop();w['tasks'][1]['operation']='blender.scene'
        with self.assertRaisesRegex(ValueError,'split structured preparation'):record(value,{}, dict(reply_contract_version=3))

    def test_ask_when_run_file_remains_unresolved_not_fabricated(self):
        value=reply();w=value['workflow'];w['tasks']=w['tasks'][1:]
        w['inputs']={'layout':dict(type='artifact',media_type='application/json',label='Layout',required=True)}
        w['tasks'][0]['inputs']['files']={'workflow':'layout'}
        # An artifact cannot replace an array-valued files input. Existing schema
        # validation remains authoritative even when handoff validation is deferred.
        with self.assertRaises(ValueError):record(value,{}, dict(reply_contract_version=3))

    def test_actual_store_rejection_then_correction_before_dispatch(self):
        from task_relay import desktop_node_runs as runs
        from orchestrator.operation_records import Store
        from orchestrator.gemini_worker import Files
        f=fixture.ChatWorkNode();f.setUp();self.addCleanup(f.doCleanups)
        host=f.f
        command=dict(request_id=str(uuid.uuid4()),question='Create a brief presentation',title='Slides',
            workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]),model=dict(provider='codex',id='gpt-6.1-sol'))
        run=runs.compose_workflow(command)['run'];host.rt.tick(run)
        aid=host.rt.task(run,'compose')['latest'];frozen=host.factory.sessions[aid]['frozen']
        limits=copy.deepcopy(frozen['limits']);store=Store(frozen,host.rt.db)
        with self.assertRaisesRegex(ValueError,'document.layout'):
            store.submit(dict(request_key='wrong',revision=0,records=[reply()]),{})
        self.assertNotIn('workflow',runs.composition_result(dict(request_id=command['request_id'])))
        store.submit(dict(request_key='correct',revision=0,records=[reply('application/json')]),{})
        host.factory.finish(aid);store.export(Files(frozen),complete=True);host.rt.tick(run)
        result=runs.composition_result(dict(request_id=command['request_id']))
        self.assertEqual(result['status'],'completed')
        with patch('orchestrator.execution.available'),patch('orchestrator.executors.available'):
            plan=runs.compile_plan(host.rt,result['workflow'],{},'prepared','Slides')['plan']
        self.assertEqual(plan['tasks'][0]['operation_contract']['id'],'document.layout')
        self.assertEqual(plan['tasks'][1]['execution']['capability'],'pptx.create')
        self.assertEqual(frozen['limits'],limits)
        self.assertEqual([r['id'] for r in host.rt.db.execute('SELECT id FROM production_tasks WHERE run=?',(run,))],['compose'])
