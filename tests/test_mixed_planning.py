import json
import copy
import unittest
from unittest.mock import patch

import gemini
import production_planning as planning
import capabilities
from tests import test_production_planning as fixtures
from tests.test_mixed_execution import operation,upstream


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    click=fixtures.Tests.click
    start=fixtures.Tests.start

    def mixed_response(self):
        response=self.response();tasks=response['plan']['tasks']
        tasks[0].pop('user_gate');tasks[0]['outputs'][0]['media_type']='text/plain'
        tasks.append(operation('bundle','text.bundle',[upstream('produce','output.txt')],['produce','review']))
        tasks.append(operation('api','gemini.text',[upstream('bundle','bundle.txt')],['bundle'],user_gate='Select the summary'))
        for task in tasks[2:]:
            from orchestrator.contracts import assignment
            normalized=assignment(task);task.update(normalized)
        return response

    def test_mixed_scope_requires_capability_choice_and_card_exposes_external_transfer(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'test-model'}}):
            row=self.queue(action=self.action(step_capabilities=['text.bundle','gemini.text']))
            planning.Worker(self.state,lambda *_:(json.dumps(self.mixed_response()),{})).tick()
            row=self.row();self.assertEqual(row['status'],'ready',row['error'])
            preview=planning.preview(row)
            self.assertIn('External transfer',preview);self.assertIn('test-model',preview)
            plan=json.loads(row['plan']);self.assertEqual(len(plan['tasks']),4)
            self.assertTrue(all(any(i['path']=='request/USER-REQUEST.txt' for i in t['inputs']) for t in plan['tasks']))
            self.start(row);self.click(row['token'])
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
            self.assertEqual(self.row()['status'],'started')

    def test_unrequested_or_unavailable_operation_cannot_be_approved(self):
        row=self.queue()
        with self.assertRaises(ValueError):planning.validate_result(json.dumps(self.mixed_response()),row)
        with patch.object(gemini,'read_config',return_value=None):
            snap={'capabilities':capabilities.catalog(self.state,{})}
            with self.assertRaisesRegex(ValueError,'unavailable'):
                planning.validate_action(self.action(step_capabilities=['gemini.text']),snap)

    def test_disconnection_between_plan_and_start_keeps_registration_atomic(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'test-model'}}):
            self.queue(action=self.action(step_capabilities=['text.bundle','gemini.text']))
            planning.Worker(self.state,lambda *_:(json.dumps(self.mixed_response()),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        with patch.object(gemini,'read_config',return_value=None):self.start(row)
        self.assertEqual(self.row()['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_planner_cannot_switch_the_frozen_api_model(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'chosen-model'}}):
            row=self.queue(action=self.action(step_capabilities=['text.bundle','gemini.text']))
        with self.assertRaisesRegex(ValueError,'frozen configured'):
            planning.validate_result(json.dumps(self.mixed_response()),row)

    def image_response(self):
        from orchestrator import execution,contracts
        response=self.response()
        photo=dict(id='image',role='api',objective='Create the requested image',instruction='Create one architectural image.',
            inputs=[],outputs=[{'path':'tower-photo.png','purpose':'Candidate visualization','media_type':'image/png'}],
            criteria=copy.deepcopy(execution.REGISTRY['gemini.image']['criteria']),
            execution={'capability':'gemini.image','version':1,'parameters':{'model':'chosen-image','max_output_tokens':128,'aspect_ratio':'1:1'}},
            user_gate='Select the image')
        # Normalize against a fixture text input; planner installs its exact request.
        photo['inputs']=[{'artifact':'fixture','path':'request.txt','purpose':'Request','authority':'User','media_type':'text/plain'}]
        photo=contracts.assignment(photo);photo['inputs']=[]
        reviewer=response['plan']['tasks'][1]
        reviewer.update(review_of='image',dependencies=['image'],criteria=photo['criteria'].copy(),
            inputs=[{'from_task':'image','output':'tower-photo.png','path':'candidate.png','purpose':'Review image','authority':'Unselected candidate','media_type':'image/png'}])
        response['plan']['tasks']=[photo,reviewer]
        return response

    def test_media_only_plan_freezes_model_and_requires_review(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'image':'chosen-image'}}):
            row=self.queue(action=self.action(step_capabilities=['gemini.image']),text='Create an architectural image')
            planning.Worker(self.state,lambda *_:(json.dumps(self.image_response()),{})).tick()
        self.assertEqual(self.row()['status'],'ready',self.row()['error'])
        self.assertIn('chosen-image',planning.preview(self.row()))
        value=self.image_response();value['plan']['tasks'][1].pop('review_of')
        with self.assertRaisesRegex(ValueError,'independent review'):
            planning.validate_result(json.dumps(value),row)

    def test_selected_image_outcome_cannot_disappear_from_plan(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'image':'chosen-image'}}):
            row=self.queue(action=self.action(step_capabilities=['gemini.image']),text='Create the model and a photograph')
        with self.assertRaisesRegex(ValueError,'omitted selected operations'):
            planning.validate_result(json.dumps(self.response()),row)

    def test_declared_document_deliverables_must_bind_real_reviewed_outputs(self):
        row=self.queue(action=self.action(deliverables={'report':'A research report','slides':'An editable presentation'}))
        result=self.response();result['deliverable_map']={'report':{'task':'produce','output':'output.txt'}}
        with self.assertRaisesRegex(ValueError,'every requested deliverable'):
            planning.validate_result(json.dumps(result),row)
        result['deliverable_map']['slides']={'task':'produce','output':'missing.pptx'}
        with self.assertRaisesRegex(ValueError,'actual declared producer output'):
            planning.validate_result(json.dumps(result),row)
        result['plan']['tasks'][0]['outputs'].append({'path':'slides.pptx','purpose':'Editable presentation'})
        result['deliverable_map']['slides']['output']='slides.pptx'
        with self.assertRaisesRegex(ValueError,'independent review'):
            planning.validate_result(json.dumps(result),row)
        result['plan']['tasks'][1]['inputs'].append({'from_task':'produce','output':'slides.pptx','path':'candidate/slides.pptx','purpose':'Review presentation','authority':'Candidate'})
        checked,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(checked['deliverable_map'],result['deliverable_map'])

    def test_nonimage_operation_cannot_silently_disappear(self):
        row=self.queue(action=self.action(step_capabilities=['text.bundle']))
        with self.assertRaisesRegex(ValueError,'omitted selected operations: text.bundle'):
            planning.validate_result(json.dumps(self.response()),row)

    def test_unrelated_deferral_cannot_excuse_missing_image(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'image':'chosen-image'}}):
            row=self.queue(action=self.action(step_capabilities=['gemini.image']))
        result=self.response();result['deferred_operations']={'gemini.image':'Later'}
        with self.assertRaisesRegex(ValueError,'Only exact-input host'):
            planning.validate_result(json.dumps(result),row)

    def test_openrouter_plan_freezes_model_and_requires_review(self):
        with patch('task_relay.api_providers.read_config',return_value={'api_key':'fixture','models':{'image':'vendor/image-model'}}):
            row=self.queue(action=self.action(step_capabilities=['openrouter.image']))
        result=self.image_response();producer=result['plan']['tasks'][0]
        producer['execution']={'capability':'openrouter.image','version':1,'parameters':{'model':'vendor/image-model','aspect_ratio':'1:1'}}
        checked,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(plan['tasks'][0]['execution']['capability'],'openrouter.image')
        producer['execution']['parameters']['model']='other/image'
        with self.assertRaisesRegex(ValueError,'frozen configured'):
            planning.validate_result(json.dumps(result),row)

    def test_image_reviewer_receives_the_exact_upstream_reference_as_well_as_result(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'image':'chosen-image'}}):
            row=self.queue(action=self.action(step_capabilities=['gemini.image']),text='Make a preview and then an architectural photograph')
        value=self.response();producer,review=value['plan']['tasks']
        producer.pop('user_gate')
        producer['outputs'][0].update(path='preview.png',media_type='image/png')
        review['inputs'][0].update(output='preview.png',path='candidate-preview.png',media_type='image/png')
        photo,photo_review=self.image_response()['plan']['tasks']
        photo['inputs']=[{'from_task':'produce','output':'preview.png','path':'model-preview.png','purpose':'Exact model view','authority':'Candidate','media_type':'image/png'}]
        photo['dependencies']=['produce','review'];photo_review['id']='photo-review'
        value['plan']['tasks'].extend([photo,photo_review])
        checked=planning.validate_result(json.dumps(value),row)
        # validate_result returns the normalized plan alongside its message.
        encoded=json.dumps(checked)
        self.assertIn('source-inputs/image/model-preview.png',encoded)


if __name__=='__main__':unittest.main()
