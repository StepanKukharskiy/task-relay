"""Synthetic annotations remain data; authority comes from captured contracts."""
import copy
import unittest

from orchestrator import execution
from task_relay import external_evidence,planning_contract,production_planning,sourcing_planning


class Tests(unittest.TestCase):
    def test_registered_record_pair_cannot_invent_an_alternative_wire_format(self):
        from orchestrator.sourcing_inventory import PLANNING_CRITERIA
        schema={'type':'object','additionalProperties':True}
        payload=dict(response_contract={'version':1,'schema':schema},connector_companions_version=1)
        for selector in (dict(sourcing=dict(version=2,kind='inventory')),dict(records=dict(family=dict(id='sourcing.inventory',version=1)))):
            value=dict(plan=dict(tasks=[dict(id='observe',instruction='Inventory all requested lighting and textiles',
                criteria=['Use ymin,xmin,ymax,xmax in 0–1000 integers'],**selector),
                dict(id='review',review_of='observe',criteria=['Reject normalized 0–1 coordinates'])]))
            original=copy.deepcopy(value)
            result,receipts=planning_contract.prepare(value,payload,{})
            self.assertEqual(value,original)
            self.assertEqual(result['plan']['tasks'][0]['instruction'],original['plan']['tasks'][0]['instruction'])
            self.assertEqual([t['criteria'] for t in result['plan']['tasks']],[PLANNING_CRITERIA]*2)
            self.assertEqual([r['before'] for r in receipts],[t['criteria'] for t in original['plan']['tasks']])
            repeated,again=planning_contract.prepare(result,payload,{})
            self.assertEqual(repeated,result);self.assertEqual(again,[])
        legacy,_=planning_contract.prepare(value,dict(payload,connector_companions_version=0),{})
        self.assertEqual(legacy,value)

    def test_optional_helper_requires_frozen_executed_owner_and_completion_scope(self):
        spec=dict(id='fixture.fetch',completion_companions={'fixture.merge':'fill-gaps'})
        scope=dict(connector_companions_version=1,delivery_completion_policy_version=1,graph_operations=[spec])
        selected={'fixture.fetch','fixture.merge','gemini.image'}
        before=copy.deepcopy(scope)
        self.assertEqual(planning_contract.unused_completion_companions(selected,{'fixture.fetch'},scope),
                         {'fixture.merge':{'owner':'fixture.fetch','reason':'fill-gaps'}})
        self.assertEqual(scope,before)
        for altered in ({},dict(scope,delivery_completion_policy_version=0),dict(scope,graph_operations=[])):
            self.assertEqual(planning_contract.unused_completion_companions(selected,{'fixture.fetch'},altered),{})
        self.assertEqual(planning_contract.unused_completion_companions(selected,set(),scope),{})
        self.assertEqual(planning_contract.unused_completion_companions(selected,{'fixture.fetch','fixture.merge'},scope),{})

    def test_unique_unlocked_profile_repair_does_not_override_locks_or_ambiguity(self):
        task=dict(id='prepare',inputs=[dict(path='operation-support/example/validate.py')],
                  outputs=[dict(path='data.json')],worker=dict(executor='api',requires=['files.text']))
        catalog=[dict(id='api',backend={'type':'gemini-agent','model':'fixture'}),
                 dict(id='code',backend={'type':'codex-cli','model':'fixture','reasoning':'high'})]
        scope={'connector_companions_version':1};options=dict(executor_locked=False,worker_catalog=catalog)
        candidate=copy.deepcopy(task);receipt=production_planning.bind_compatible_worker(candidate,options,scope)
        self.assertEqual(candidate['worker']['executor'],'code');self.assertEqual(receipt['before'],'api')
        for variation in ('locked','ambiguous','unknown','legacy'):
            candidate=copy.deepcopy(task);opts=copy.deepcopy(options);payload=copy.deepcopy(scope)
            if variation=='locked':opts['executor_locked']=True
            elif variation=='ambiguous':opts['worker_catalog'].append(dict(id='other',backend=catalog[1]['backend']))
            elif variation=='unknown':candidate['worker']['executor']='uncaptured'
            else:payload={}
            before=copy.deepcopy(candidate)
            self.assertIsNone(production_planning.bind_compatible_worker(candidate,opts,payload))
            self.assertEqual(candidate,before)

    def test_native_checks_and_scheduler_limits_do_not_change_internal_http_grant(self):
        spec=copy.deepcopy(execution.REGISTRY['web.sources.prepared']);spec['id']='web.sources.prepared'
        schema={'type':'object','additionalProperties':True}
        payload=dict(response_contract={'version':1,'schema':schema},connector_companions_version=1,graph_operations=[spec])
        value=dict(plan=dict(tasks=[dict(id='read',execution=dict(capability=spec['id'],version=spec['version']),
            criteria=['Records raw HTML bodies and three products per target'],limits=dict(seconds=9999,tool_calls=80,output_bytes=999999999)),
            dict(id='review',review_of='read',criteria=['Check exact evidence'])]))
        before=copy.deepcopy(value)
        result,receipts=planning_contract.prepare(value,payload,{'limits':{'seconds':1800}})
        self.assertEqual(value,before);self.assertEqual(result['plan']['tasks'][0]['criteria'],spec['criteria'])
        self.assertEqual(result['plan']['tasks'][1]['criteria'],['Check exact evidence'])
        binding=next(r for r in receipts if r['path'].endswith('.criteria'))
        self.assertEqual(binding['before'],before['plan']['tasks'][0]['criteria'])
        self.assertEqual(binding['proposal_criteria_authority'],'audit_only')
        self.assertEqual(result['plan']['tasks'][0]['limits']['tool_calls'],1)
        self.assertEqual(payload['graph_operations'][0]['external_requests'],80);self.assertTrue(receipts)
        value['plan']['tasks'].pop()
        intermediate,receipts=planning_contract.prepare(value,payload,{'limits':{'seconds':1800}})
        self.assertEqual(intermediate['plan']['tasks'][0]['criteria'],spec['criteria'])
        self.assertIsNone(next(r for r in receipts if r['path'].endswith('.criteria'))['semantic_review_task'])

    def test_record_budget_uses_existing_scope_ceiling_and_preserves_user_limit(self):
        plan=dict(backend={'type':'gemini-agent','model':'fixture'},tasks=[
            dict(id='author',sourcing=dict(version=1,inventory={'source':'inventory'},source_pack={'source':'sources'},
                options_per_item=3,count_policy='target',max_records=10),limits={'tool_calls':14,'provider_requests':14,'response_tokens':8000}),
            dict(id='review',review_of='author',limits={'tool_calls':6,'provider_requests':6,'response_tokens':4000})])
        receipts=sourcing_planning.budgets(plan,2,{'author':24,'review':24},4096)
        # Keep the original authorized room for inspection and corrections;
        # workload minima are not a smaller replacement grant.
        self.assertEqual(plan['tasks'][1]['limits'],dict(tool_calls=24,provider_requests=24,response_tokens=4096))
        self.assertTrue(receipts)
        plan['tasks'][1]['limits'].update(tool_calls=6,provider_requests=6,response_tokens=4000)
        with self.assertRaisesRegex(ValueError,'frozen allowance'):sourcing_planning.budgets(plan,2,{'review':6},4000)
        self.assertEqual(plan['tasks'][1]['limits'],dict(tool_calls=6,provider_requests=6,response_tokens=4000))

    def test_research_review_closure_is_exact_idempotent_and_keeps_native_wire_inputs(self):
        plan={'tasks':[dict(id='pages',execution={'capability':'web.sources.prepared'}),
            dict(id='review',review_of='pages',outputs=[dict(path='review.md',media_type='text/markdown')]),
            dict(id='author',inputs=[dict(from_task='pages',output='source-pack.json',path='sources.json')],dependencies=['pages']),
            dict(id='native',execution={'capability':'text.bundle'},inputs=[dict(from_task='pages',output='source-pack.json',path='sources.json')])]}
        original_native=copy.deepcopy(plan['tasks'][-1])
        receipts=external_evidence.bind_review_closure(plan);self.assertEqual(len(receipts),1)
        self.assertEqual(plan['tasks'][2]['inputs'][-1]['from_task'],'review')
        self.assertEqual(plan['tasks'][2]['inputs'][-1]['output'],'review.md')
        self.assertIn('review',plan['tasks'][2]['dependencies']);self.assertEqual(plan['tasks'][-1],original_native)
        self.assertEqual(external_evidence.bind_review_closure(plan),[])


if __name__=='__main__':unittest.main()
