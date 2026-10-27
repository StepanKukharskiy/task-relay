"""Recover missing operation defaults without widening execution grants."""
import copy
import unittest
from task_relay import planning_contract

class BindingRecovery(unittest.TestCase):
    def proposal(self):
        return {'plan':{'tasks':[
            {'limits':{'seconds':2400,'tool_calls':30,'output_bytes':300000}},
            {'execution':{'capability':'web.sources.prepared','parameters':{'domains':[]}},'limits':{'seconds':1800,'tool_calls':0,'output_bytes':2000000}}]}}
    def context(self):
        return {'planner_budget_binding_version':2,'response_contract':{'version':1,'schema':{}},'graph_operations':[{'id':'web.sources.prepared','configured_model':'configured-model','available':True}]}
    def test_missing_model_and_excess_budgets_recover_without_rewriting_reply_or_operation_budget(self):
        raw=self.proposal();before=copy.deepcopy(raw)
        bound,receipts=planning_contract.prepare(raw,self.context(),{'limits':{'seconds':1800,'tool_calls':24,'output_bytes':200000}})
        self.assertEqual(raw,before)
        self.assertEqual(bound['plan']['tasks'][0]['limits'],{'seconds':1800,'tool_calls':24,'output_bytes':200000})
        self.assertEqual(bound['plan']['tasks'][1]['limits'],raw['plan']['tasks'][1]['limits'])
        self.assertEqual(bound['plan']['tasks'][1]['execution']['parameters']['model'],'configured-model')
        self.assertEqual(len(receipts),4)
        self.assertEqual(receipts[-1]['source'],'graph_operations.web.sources.prepared.configured_model')
    def test_explicit_model_is_not_silently_replaced_and_missing_configuration_blocks(self):
        raw=self.proposal();raw['plan']['tasks'][1]['execution']['parameters']['model']='explicit-model'
        bound,_=planning_contract.prepare(raw,self.context(),{})
        self.assertEqual(bound['plan']['tasks'][1]['execution']['parameters']['model'],'explicit-model')
        ctx=self.context();ctx['graph_operations'][0]['available']=False
        with self.assertRaisesRegex(ValueError,'unavailable'):
            planning_contract.prepare(self.proposal(),ctx,{})
    def test_older_policy_keeps_time_and_tool_limits(self):
        ctx=self.context();ctx['planner_budget_binding_version']=1
        bound,_=planning_contract.prepare(self.proposal(),ctx,{'limits':{'seconds':1800,'tool_calls':24,'output_bytes':200000}})
        self.assertEqual(bound['plan']['tasks'][0]['limits']['tool_calls'],30)
        self.assertEqual(bound['plan']['tasks'][0]['limits']['seconds'],2400)

class ReviewBindingRecovery(unittest.TestCase):
    def test_inherit_producer_checks_and_keep_additional_review_requirements(self):
        from orchestrator.deliverable_outputs import bind_review_criteria
        tasks=[{'id':'author','criteria':['Three distinct options for each item'],'outputs':[{'path':'catalog.json'}]},
               {'id':'review','review_of':'author','criteria':['Check that variants match the photos']}]
        receipts=bind_review_criteria(tasks)
        self.assertEqual(tasks[1]['criteria'],['Three distinct options for each item','Check that variants match the photos'])
        self.assertEqual(tasks[0]['criteria'],tasks[1]['criteria'])
        self.assertEqual(receipts[0]['before'],['Check that variants match the photos'])
    def test_registered_criteria_stay_exact_and_semantic_coverage_merges_by_output(self):
        from orchestrator.deliverable_outputs import bind_review_criteria,review_criteria,validate_assignment
        from task_relay.production_planning import validate_prepared_research
        # Reuse the small upstream-query fixture, without providers or media.
        tasks=[{'id':'author','criteria':['Prepare queries'],'outputs':[{'path':'queries.json'}]},
            {'id':'review_author','review_of':'author','criteria':['Prepare queries'],'inputs':[{'from_task':'author','output':'queries.json'}]},
            {'id':'search','execution':{'capability':'web.sources.prepared'},'criteria':['Fixed procedural receipt'], 'outputs':[{'path':'delivery/source-pack.json'}],
             'inputs':[{'from_task':'author','output':'queries.json'}],'dependencies':['author','review_author']},
            {'id':'review_search','review_of':'search','criteria':['Require real product pages'],'inputs':[{'from_task':'author','output':'queries.json'}]}]
        bind_review_criteria(tasks);validate_prepared_research({'tasks':tasks})
        self.assertEqual(tasks[2]['criteria'],['Fixed procedural receipt'])
        self.assertEqual(len(tasks[2]['output_contracts']),1)
        validate_assignment(tasks[2])
        self.assertEqual(tasks[3]['criteria'],review_criteria(tasks[2]))
