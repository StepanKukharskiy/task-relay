"""Installed intake callers retain bounded context and correction APIs."""
import copy
import json
import unittest

from task_relay import request_contract as contracts
from tests.intake_fixtures import outcome, work


class Tests(unittest.TestCase):
    def test_operation_semantics_and_frozen_file_checks_bind_once(self):
        from orchestrator.deliverable_outputs import bind_review_criteria,validate_assignment
        producer=dict(id='merge',execution=dict(capability='images.merge'),criteria=['Native merge check'],
                      outputs=[dict(path='photos.zip')])
        review=dict(id='review',review_of='merge',criteria=['Native merge check','Check exact product identity'])
        plan=dict(tasks=[producer,review]);bind_review_criteria(plan['tasks'])
        contract=work([outcome('photos',format='.zip',checks=['nonempty'],validation=['Disclose missing photos'])])
        coverage=dict(photos=dict(task='merge',output='photos.zip'))
        for _ in range(2):contracts.bind(plan,coverage,contract,separate_operation_review=True)
        self.assertEqual(len(producer['output_contracts']),1)
        value=producer['output_contracts'][0]
        self.assertEqual(value['checks'],['nonempty'])
        self.assertEqual(value['format'],'.zip')
        self.assertEqual(value['validation'],['Check exact product identity','Disclose missing photos'])
        validate_assignment(producer)

    def test_current_stage_survives_catalog_omission_without_mutation(self):
        payload={'user_message':'Exact continuation', 'entry_context':{'image':'bound.png'},
                 'snapshot':{'focus':'room', 'pipeline_step':{'stage':{'id':'photos'}},
                             'current_attachment_ids':[3], 'capabilities':'x'*100000},
                 'history':['x'*100000]}
        original=copy.deepcopy(payload)
        context=contracts.context(payload)
        self.assertEqual(context['user_message'],payload['user_message'])
        self.assertEqual(context['pipeline_step'],payload['snapshot']['pipeline_step'])
        self.assertEqual(context['entry_context'],payload['entry_context'])
        self.assertEqual(context['current_attachment_ids'],[3])
        self.assertEqual(context['intake_context']['omitted'],['history'])
        self.assertNotIn('capabilities',context)
        self.assertEqual(payload,original)

    def test_wrapper_and_legacy_scope_reach_same_frozen_contract(self):
        contract=work([outcome('deck',format='.pptx')])
        self.assertEqual(contracts.load(json.dumps(contract)),contract)
        self.assertEqual(contracts.load(json.dumps({'scope':contract}),recover_answer=True),contract)
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            contracts.load('{"scope":{},"scope":{}}',recover_answer=True)

    def test_answer_metadata_repair_cannot_turn_files_into_answers(self):
        result={'mode':'answer','reason':'Inline status', 'outcomes':[
            {'id':'status','description':'Inline status','kind':'result','count':1,
             'format':'','checks':[],'validation':[]}]}
        self.assertEqual(contracts.load(json.dumps({'scope':result}),recover_answer=True)['outcomes'],[])
        result['outcomes'][0].update(kind='file',format='.pptx',checks=['nonempty'])
        with self.assertRaises(ValueError):contracts.load(json.dumps(result),recover_answer=True)

    def test_format_correction_cannot_change_work_scope(self):
        original=work([outcome('deck',format='.pptx')])
        for field,value in [('format','.md'),('description','Different work'),('validation',[])]:
            corrected=copy.deepcopy(original);corrected['outcomes'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                contracts.check_correction(json.dumps({'scope':original}),corrected)
        contracts.check_correction(json.dumps({'scope':original}),original)


if __name__=='__main__':unittest.main()
