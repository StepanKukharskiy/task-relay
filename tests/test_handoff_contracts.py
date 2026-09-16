"""Whole-job feasibility and exact-port checks; tiny fixtures, no live providers/apps."""
import json
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import zipfile

from orchestrator import handoff_contracts as h,execution
from tests.test_orchestrator import plan
from tests import test_production_planning as planning_fixture
from task_relay import pipelines,production_planning as planning


def stage(ident,route,outputs,caps=(),inputs=()):
    return dict(id=ident,instruction='Produce the declared outputs.',route=route,gate='none',
                capabilities=list(caps),deliverables={k:k for k in outputs},
                handoff=dict(inputs=list(inputs),outputs=outputs),
                **({'visual_intent':'synthetic'} if route=='image' else {}))


def edge(s,d,m,consumer='context'):
    return dict(stage=s,deliverable=d,media_type=m,consumer=consumer)


def architecture():
    return [stage('research','conversation',{'research':{'media_type':'text/markdown'}}),
        stage('model','production',{'model':{'media_type':'application/vnd.rhino','max_bytes':1000000},
            'preview':{'media_type':'image/png','max_bytes':1000000}},['rhino.run_python'],[edge('research','research','text/markdown')]),
        stage('visual','image',{'visual':{'media_type':'image/png','max_bytes':1000000}},inputs=[edge('model','preview','image/png','gemini.image')]),
        stage('deck','production',{'deck':{'media_type':h.PPTX_MIME,'slides':3,'max_bytes':4000000}},['pptx.create'],
              [edge('research','research','text/markdown'),edge('visual','visual','image/png','pptx.create')])]


class ContractTests(unittest.TestCase):
    def test_architecture_and_other_stage_orders_compile_without_templates(self):
        result=h.compile_workflow(architecture(),required=True)
        self.assertEqual(len(result['edges']),4)
        self.assertEqual(result['version'],1)
        self.assertTrue(result['unknowns'])
        stages=[stage('facts','conversation',{'facts':{'media_type':'text/plain'}}),
                stage('report','production',{'report':{'media_type':'text/markdown'}},inputs=[edge('facts','facts','text/plain')])]
        self.assertEqual(len(h.compile_workflow(stages,required=True)['edges']),1)

    def test_600_slide_request_is_rejected_before_any_stage(self):
        stages=architecture();stages[-1]['handoff']['outputs']['deck']['slides']=600
        with self.assertRaises(h.ContractError) as caught:h.compile_workflow(stages,required=True)
        self.assertEqual(caught.exception.code,'unsupported_scale')
        self.assertEqual(caught.exception.detail,dict(requested=600,maximum=50))
        self.assertEqual(stages[-1]['handoff']['outputs']['deck']['slides'],600)

    def test_native_model_cannot_be_disguised_as_an_image_reference(self):
        for consumer in ('gemini.image','context'):
            stages=architecture();stages[2]['handoff']['inputs']=[edge('model','model','application/vnd.rhino',consumer)]
            with self.assertRaisesRegex(h.ContractError,'native|cannot consume'):h.compile_workflow(stages,required=True)
        stages=architecture();stages[2]['handoff']['inputs'][0]['media_type']='image/jpeg'
        with self.assertRaisesRegex(h.ContractError,'disagree'):h.compile_workflow(stages,required=True)

    def test_missing_companion_forward_reference_and_known_capacity_fail(self):
        stages=architecture();stages[1]['handoff']['outputs']['preview']['companions']=['model']
        with self.assertRaises(h.ContractError) as caught:h.compile_workflow(stages,required=True)
        self.assertEqual(caught.exception.code,'missing_companion')
        stages=architecture();stages[2]['handoff']['inputs'][0]['stage']='deck'
        with self.assertRaisesRegex(h.ContractError,'earlier-stage'):h.compile_workflow(stages,required=True)
        stages=architecture();stages[1]['handoff']['outputs']['preview']['max_bytes']=12000000
        with self.assertRaises(h.ContractError) as caught:h.compile_workflow(stages,required=True)
        self.assertEqual(caught.exception.code,'input_capacity')

    def test_frozen_operation_limits_and_availability(self):
        saved={'id':'pptx.create',**execution.REGISTRY['pptx.create'],'output_bytes':2000000}
        stages=architecture()
        with self.assertRaisesRegex(h.ContractError,'producer capacity'):h.compile_workflow(stages,[saved],True)
        saved['available']=False
        with self.assertRaisesRegex(h.ContractError,'unavailable'):h.compile_workflow(stages,[saved],True)
        saved['available']=True;saved['version']=999
        with self.assertRaisesRegex(h.ContractError,'version changed'):h.compile_workflow(stages,[saved],True)

    def test_bound_consumer_needs_exact_artifact_identity_not_equal_hash(self):
        s=architecture()[-1]
        graph={'tasks':[dict(id='build',execution={'capability':'pptx.create'},inputs=[dict(artifact='copy')],
                       outputs=[dict(path='deck.pptx',media_type=h.PPTX_MIME)])],
               'deliverables':{'deck':{'task':'build','output':'deck.pptx'}}}
        bindings=[dict(**s['handoff']['inputs'][0],kind='context',result='Exact research'),
                  dict(**s['handoff']['inputs'][1],kind='artifact',source={'artifact':'selected'})]
        sources=[dict(artifact='copy',workflow_artifact='other-version',sha256='samehash')]
        with self.assertRaises(h.ContractError):h.bind_stage(s,graph,bindings,sources)
        sources[0]['workflow_artifact']='selected';h.bind_stage(s,graph,bindings,sources)
        self.assertEqual(graph['tasks'][0]['outputs'][0]['handoff']['slides'],3)

    def test_actual_slide_count_and_byte_limits_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sample.pptx'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst><p:sldId id="256"/></p:sldIdLst></p:presentation>')
            h.check_file(path,{'media_type':h.PPTX_MIME,'slides':1})
            with self.assertRaisesRegex(h.ContractError,'delivered 1'):h.check_file(path,{'media_type':h.PPTX_MIME,'slides':3})
            with self.assertRaisesRegex(h.ContractError,'byte bound'):h.check_file(path,{'media_type':h.PPTX_MIME,'max_bytes':1})

    def test_managed_image_requires_one_output_and_exact_declared_references(self):
        stages=architecture();visual=stages[2]
        binding=dict(**visual['handoff']['inputs'][0],kind='artifact',source={'artifact':'selected-preview'})
        unrelated=dict(binding,deliverable='old-preview',source={'artifact':'older-version'})
        self.assertEqual(h.image_references(visual,[binding,unrelated]),{'selected-preview'})
        with self.assertRaisesRegex(h.ContractError,'exact frozen'):h.image_references(visual,[unrelated])
        visual['handoff']['outputs']['second']={'media_type':'image/png'};visual['deliverables']['second']='Second image'
        with self.assertRaisesRegex(h.ContractError,'one selected image'):h.compile_workflow(stages,required=True)

    def test_managed_image_capacity_matches_dispatch(self):
        stages=architecture();stages[2]['handoff']['outputs']['visual']['max_bytes']=50000001
        with self.assertRaisesRegex(h.ContractError,'producer capacity'):h.compile_workflow(stages,required=True)
        stages=architecture()
        for i in range(7):
            key='preview'+str(i)
            stages[1]['handoff']['outputs'][key]={'media_type':'image/png'}
            stages[1]['deliverables'][key]=key
        stages[2]['handoff']['inputs']=[edge('model','preview'+str(i),'image/png','gemini.image') for i in range(7)]
        with self.assertRaisesRegex(h.ContractError,'at most 6'):h.compile_workflow(stages,required=True)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        planning_fixture.Tests.setUp(self)
        del self.fail
    tearDown=planning_fixture.Tests.tearDown
    request=planning_fixture.Tests.request

    def test_oversized_workflow_keeps_request_but_queues_no_stage(self):
        stages=architecture();stages[-1]['handoff']['outputs']['deck']['slides']=600
        action=dict(kind='plan_pipeline',contract_version=1,title='Large architecture deck',planning_only=False,stages=stages)
        original='Research a house, model it, visualize it and deliver one 600-slide presentation.'
        self.request(action,original,1)
        row=self.state.db.execute('SELECT prompt,answer FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertIn(original,row['prompt']);self.assertIn('600',row['answer']);self.assertIn('50',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_new_workflow_requires_contract_but_explicit_legacy_snapshot_is_readable(self):
        action=dict(kind='plan_pipeline',title='Legacy',planning_only=True,
                    stages=[stage('a','conversation',{'a':{'media_type':'text/plain'}}),stage('b','conversation',{'b':{'media_type':'text/plain'}})])
        for s in action['stages']:s.pop('handoff')
        with self.assertRaisesRegex(pipelines.PipelineValidationError,'contract_version'):
            pipelines.validate(action,{'workflow_contract_version':1})
        pipelines.validate(action,{})

    def test_planning_clarification_preserves_the_saved_stage_contract(self):
        from task_relay import orchestrator_chat as chat
        stages=[stage('write','production',{'brief':{'media_type':'text/plain'}}),
                stage('summarize','conversation',{'summary':{'media_type':'text/plain'}},inputs=[edge('write','brief','text/plain')])]
        self.request(dict(kind='plan_pipeline',contract_version=1,title='Contract recovery',planning_only=False,stages=stages),'Write a brief then summarize it.',1)
        pipelines.tick(self.state)
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],artifact_ids=[],
                    planning_only=False,step_capabilities=[],deliverables={'brief':'brief'})
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Plan this stage','action':action})).tick()
        old=self.state.db.execute('SELECT * FROM production_plans').fetchone()
        self.assertIsNotNone(old)
        planning.Worker(self.state,lambda *_:(json.dumps(dict(decision='needs_input',message='Which audience?',plan=None)),{})).tick()
        self.request({**action,'parent_id':old['id']},'Technical audience.',2)
        successor=self.state.db.execute('SELECT context FROM production_plans WHERE parent_id=?',(old['id'],)).fetchone()
        self.assertIsNotNone(successor)
        self.assertEqual(json.loads(successor[0])['pipeline_step'],stages[0])
        self.assertEqual(json.loads(successor[0])['handoff_sources'],[])

    def test_exact_completed_output_bindings_survive_enqueue_and_import(self):
        from orchestrator.storage import transaction
        stages=[stage('source','production',{'research':{'media_type':'text/plain'}}),
                stage('report','production',{'report':{'media_type':'text/markdown'}},inputs=[edge('source','research','text/plain')])]
        action=dict(kind='plan_pipeline',contract_version=1,title='Exact handoff',planning_only=False,stages=stages)
        self.request(action,'Prepare research then report from that research.',1)
        p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        s=self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id='source'",(p['id'],)).fetchone()
        path=self.rt.root/'source.txt';path.write_text('Exact source statement')
        aid=self.rt.register(path,'Source')
        source=pipelines.artifact_source(self.state,aid)
        with transaction(self.state.db):
            pipelines.complete(self.state,p,s,[source],json.dumps({'deliverables':{'research':source}}))
            target=self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id='report'",(p['id'],)).fetchone()
            pipelines.enqueue_step(self.state,p,target)
        target=self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id='report'",(p['id'],)).fetchone()
        ctx=pipelines.request_context(self.state,target['request_id'])
        self.assertEqual(ctx['inputs']['handoffs'][0]['source']['artifact'],aid)
        job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(target['request_id'],)).fetchone()
        records=pipelines.frozen_sources(self.state,job)
        record=next(r for r in records if r.get('workflow_artifact')==aid)
        self.assertEqual(record['sha256'],source['sha256'])

    def test_four_stage_handoffs_preserve_model_preview_and_visual_versions(self):
        # Controlled data-flow fixture only: no Rhino execution or image generation.
        from orchestrator.storage import transaction
        from tests.test_gemini import PNG
        stages=architecture()
        action=dict(kind='plan_pipeline',contract_version=1,title='Architecture handoffs',planning_only=False,stages=stages)
        self.request(action,'Research, model, visualize the selected preview, then compose a deck.',1)
        p=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertIsNotNone(p)
        def row(ident):return self.state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',(p['id'],ident)).fetchone()
        def source(name,data):
            path=self.rt.root/name;path.write_bytes(data)
            return pipelines.artifact_source(self.state,self.rt.register(path,'Fixture only',path=name))
        model=source('candidate.3dm',b'Controlled native adapter placeholder; not a Rhino model.')
        preview=source('preview.png',PNG);old_preview=source('old-preview.png',PNG)
        visual=source('visual.png',PNG)
        with transaction(self.state.db):
            pipelines.complete(self.state,p,row('research'),[],'Exact research findings')
            pipelines.enqueue_step(self.state,p,row('model'))
            pipelines.complete(self.state,p,row('model'),[model,preview,old_preview],json.dumps({'deliverables':{'model':model,'preview':preview}}))
            pipelines.enqueue_step(self.state,p,row('visual'))
        job=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(row('visual')['request_id'],)).fetchone()
        pipelines.guard(self.state,job,dict(kind='generate_image',reference_ids=[],artifact_ids=[preview['artifact']]))
        with self.assertRaisesRegex(ValueError,'exact frozen'):
            pipelines.guard(self.state,job,dict(kind='generate_image',reference_ids=[],artifact_ids=[old_preview['artifact']]))
        with transaction(self.state.db):
            pipelines.complete(self.state,p,row('visual'),[visual],'Controlled image fixture')
            pipelines.enqueue_step(self.state,p,row('deck'))
        ctx=pipelines.request_context(self.state,row('deck')['request_id'])
        self.assertEqual(ctx['inputs']['handoffs'][0]['result'],'Exact research findings')
        self.assertEqual(ctx['inputs']['handoffs'][1]['source']['artifact'],visual['artifact'])
        self.assertNotEqual(ctx['inputs']['handoffs'][1]['source']['artifact'],preview['artifact'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)


class DeliveryTests(unittest.TestCase):
    from tests.test_mixed_execution import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown

    def test_deck_quantity_failure_stops_before_builder_and_does_not_replay(self):
        from orchestrator import pptx_document
        from tests.test_presentations import fixture,pptx_step
        source=self.root/'slides.json';source.write_text(json.dumps(fixture()))
        aid=self.rt.register(source,'Exact slides',path='slides.json')
        item=dict(artifact=aid,path='slides.json',purpose='Slides',authority='Selected source',media_type='application/json')
        deck=pptx_step([item]);deck['outputs'][0]['handoff']={'media_type':h.PPTX_MIME,'slides':4}
        self.rt.create(plan([deck]))
        with patch.object(pptx_document,'create',wraps=pptx_document.create) as build:
            self.rt.tick('demo');self.rt.tick('demo');self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'blocked')
        self.assertEqual(len(self.ops.calls),1);build.assert_not_called()
