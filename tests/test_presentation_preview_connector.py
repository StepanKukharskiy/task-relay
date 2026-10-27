"""Native preview compilation, exact-version execution and bounded correction."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from orchestrator import contracts, execution, corrections, pptx_render
from task_relay import presentation_planning, planning_contract
from tests import test_corrections as fixture

class Tests(unittest.TestCase):
    def scope(self):return dict(connector_companions_version=1,graph_operations=[dict(id='pptx.render',available=True)])
    def test_compiler_adds_exact_preview_inputs_and_reserves_new_version_on_correction(self):
        plan=fixture.graph()
        receipt=presentation_planning.bind(plan,self.scope())
        corrections.compile(plan['tasks'])
        helper=plan['tasks'][-1];final=next(t for t in plan['tasks'] if t.get('review_of')=='deck')
        self.assertEqual(receipt[0]['preview'],helper['id'])
        self.assertEqual(helper['max_attempts'],2)
        self.assertEqual(helper['inputs'][0]['from_task'],'deck')
        self.assertIn(helper['id'],final['dependencies'])
        self.assertEqual(contracts.review_evidence_dependencies(plan['tasks'])[helper['id']],{'deck'})
        self.assertEqual(corrections.workflow_attempt_limits(plan['tasks'])[helper['id']],2)
        self.assertEqual(len(presentation_planning.bind(plan,self.scope())),0)
        from orchestrator import final_quality
        from tests.intake_fixtures import work,outcome
        deck=next(t for t in plan['tasks'] if t['id']=='deck')
        final_quality.bind(plan,{'result':dict(task='deck',output=deck['outputs'][0]['path'])},work([outcome('result',format='.pptx')]))
        required=next(iter(final['final_quality']['checks'].values()))['inspection_inputs']
        self.assertEqual(set(required),{i['path'] for i in final['inputs'] if i.get('from_task')==helper['id']})
        self.assertTrue(required)
        contracts.plan(plan)

    def test_unavailable_renderer_rejected_before_any_dispatch(self):
        with self.assertRaisesRegex(ValueError,'unavailable before Start'):
            presentation_planning.bind(fixture.graph(),dict(connector_companions_version=1,graph_operations=[]))

    def test_registered_parameter_schema_rejects_extra_model_fields(self):
        from task_relay.planning_contract import validate
        options=dict(step_capabilities=['images.products'],connector_companions_version=1)
        shape=planning_contract.contract(options)['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']['execution']
        data=dict(capability='images.products',version=1,parameters=dict(inventory_path='i.json',catalog_path='c.json',source_pack_path='s.json',count_policy='target'))
        validate(data,shape)
        data['parameters']['invented']='guess'
        with self.assertRaises(ValueError):validate(data,shape)

    def test_native_execution_binds_all_previews_to_exact_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'candidate.pptx'
            with zipfile.ZipFile(source,'w') as z:
                for i in range(1,3):z.writestr('ppt/slides/slide'+str(i)+'.xml','<test/>')
            (root/'.relay').mkdir();control=root/'control';control.mkdir()
            frozen=dict(workspace=str(root),assignment_id='synthetic-render',presentation_runtime=dict(tools={k:dict(path=k) for k in ('soffice','pdftoppm')}),
                inputs=[dict(path='candidate.pptx',artifact='exact-candidate',sha256=hashlib.sha256(source.read_bytes()).hexdigest())],
                limits=dict(seconds=30,output_bytes=2000000),execution=dict(capability='pptx.render',version=1,parameters={}))
            def invoke(command,timeout,*,cwd):
                preview=Path(cwd)/'preview'
                if command[0]=='soffice':(preview/'candidate.pdf').write_bytes(b'%PDF-synthetic')
                else:
                    for i in range(1,3):Image.new('RGB',(100,80),'white').save(preview/f'slide-{i}.png')
                return dict(command=command,exit_code=0)
            with patch('task_relay.presentation_host.verify'),patch('task_relay.presentation_host.invoke',side_effect=invoke):
                pptx_render.execute(frozen,control)
            report=json.loads((root/'delivery/render.json').read_text())
            self.assertEqual(report['candidate_sha256'],frozen['inputs'][0]['sha256']);self.assertEqual(report['slide_count'],2)
            self.assertFalse(report['visual_review'])
            with zipfile.ZipFile(root/'delivery/slide-previews.zip') as z:
                self.assertEqual(z.namelist(),['slide-001.png','slide-002.png'])
            source.write_bytes(b'changed')
            with patch('task_relay.presentation_host.verify'),self.assertRaisesRegex(ValueError,'changed before'):
                pptx_render.execute(frozen,control)
