"""Registered wire inputs remain narrow while independent review gates dispatch."""
import copy,unittest
from task_relay import external_evidence

class Tests(unittest.TestCase):
    def graph(self):
        research={'id':'research','browser':{},'worker':{'requires':['browser.use']},'inputs':[]}
        research['browser']={'profile':'fixture'}
        review={'id':'review_sources','review_of':'research','inputs':[{'from_task':'research','output':'manifest.json'}]}
        operation={'id':'download','execution':{'capability':'images.fetch','version':1,'parameters':{}},'inputs':[{'from_task':'research','output':'manifest.json'}],'dependencies':['research','review_sources']}
        return {'tasks':[research,review,operation]}

    def payload(self,version=2):
        return {'original_request':'Verify public source catalog evidence.','options':{},'sources':[],'external_evidence_policy_version':version}

    def test_manifest_only_operation_waits_for_review_without_extra_input(self):
        plan=self.graph();before=copy.deepcopy(plan)
        external_evidence.validate_plan(plan,self.payload())
        self.assertEqual(plan,before)
        self.assertEqual(len(plan['tasks'][-1]['inputs']),1)

    def test_missing_review_dependency_cannot_be_replaced_by_prose_or_input(self):
        plan=self.graph();task=plan['tasks'][-1];task['dependencies']=['research']
        task['instruction']='Run after review_sources.'
        task['inputs'].append({'from_task':'review_sources','output':'review.md'})
        with self.assertRaisesRegex(ValueError,'must wait for independent review'):
            external_evidence.validate_plan(plan,self.payload())

    def test_agent_author_still_requires_actual_review_file(self):
        plan=self.graph();task=plan['tasks'][-1];task.pop('execution')
        with self.assertRaisesRegex(ValueError,'consume the independent research review'):
            external_evidence.validate_plan(plan,self.payload())
        task['inputs'].append({'from_task':'review_sources','output':'review.md'})
        external_evidence.validate_plan(plan,self.payload())

    def test_historical_policy_retains_original_rule(self):
        with self.assertRaisesRegex(ValueError,'consume the independent research review'):
            external_evidence.validate_plan(self.graph(),self.payload(1))
