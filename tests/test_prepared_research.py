"""Data-dependent research keeps literal queries and item coverage across review."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import web_sources,execution,outcomes
from task_relay import orchestrator_web,production_planning as planning,planning_contract
from tests.test_web_sources import FakeSession,CONFIG,assignment,SourceFactory
from tests.test_orchestrator import FakeFactory,plan
from orchestrator.adapters import ExecutionFactory
from orchestrator.runtime import Runtime

DATA={'version':1,'targets':[{'id':'item-1','queries':['yellow sectional US buy dimensions price'],'required_options':3}]}
class Session(FakeSession):
    def search(self,query):
        result=super().search(query)
        result['sources']=[{'url':f'https://retailer.example/product-{i}','title':f'Product {i}'} for i in range(3)]
        return result

class Tests(unittest.TestCase):
    def test_reviewed_item_queries_map_to_three_fetched_candidates(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(orchestrator_web,'Session',Session),patch.object(orchestrator_web,'public_url',side_effect=lambda u:u):
            raw,_=web_sources.collect(DATA['targets'][0]['queries'],[],CONFIG['models']['text'],temp,CONFIG,
                    prepared_spec={'path':'queries.json','sha256':'a'*64,'data':DATA})
        pack=json.loads(raw);self.assertEqual(pack['query_specification']['data'],DATA)
        self.assertEqual(pack['entries'][0]['target_ids'],['item-1']);self.assertEqual(len(pack['entries'][0]['pages']),3)
        self.assertIn('not verified facts',pack['interpretation'])
    def test_bad_or_scope_changing_spec_never_searches(self):
        for key,value in [('model','another-provider'),('domains',['private.example']),('version',2)]:
            data=copy.deepcopy(DATA);data[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):web_sources.validate_prepared(data)
        data=copy.deepcopy(DATA);data['targets']*=2
        with self.assertRaisesRegex(ValueError,'distinct'):web_sources.validate_prepared(data)
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            web_sources.prepared_document([{'path':'q.json','sha256':'a'*64,'text':'{"version":1,"version":2,"targets":[]}'}])
    def test_total_query_budget_is_bounded_before_transport(self):
        data=copy.deepcopy(DATA);data['targets'][0]['queries']=[f'item query {i}' for i in range(20)]
        data['targets'].append({'id':'item-2','queries':['extra query'],'required_options':3})
        with self.assertRaisesRegex(ValueError,'1–20'):web_sources.validate_prepared(data)
    def graph(self):
        author={'id':'queries','outputs':[{'path':'queries.json'}]}
        review={'id':'review_queries','review_of':'queries','inputs':[{'from_task':'queries','output':'queries.json'}],'criteria':['Match exact observed items']}
        source={'id':'search','execution':{'capability':'web.sources.prepared'},'inputs':[{'from_task':'queries','output':'queries.json'}],'dependencies':['queries','review_queries']}
        source_review={'id':'review_search','review_of':'search','inputs':[{'from_task':'queries','output':'queries.json'}],'criteria':copy.deepcopy(execution.REGISTRY['web.sources.prepared']['criteria'])}
        return {'tasks':[author,review,source,source_review]}
    def test_exact_query_review_and_source_review_edges_are_required(self):
        for kind in ('missing_review_dependency','missing_exact_spec','unbound_queries'):
            graph=self.graph();source=graph['tasks'][2]
            if kind=='missing_review_dependency':source['dependencies'].remove('review_queries')
            elif kind=='missing_exact_spec':graph['tasks'][3]['inputs']=[]
            else:source['inputs']=[{'artifact':'unreviewed','path':'queries.json'}]
            with self.subTest(kind=kind),self.assertRaises(ValueError):planning.validate_prepared_research(graph)
        graph=self.graph();planning.validate_prepared_research(graph)
        self.assertEqual(graph['tasks'][2]['output_contracts'][0]['version'],2)
        self.assertEqual(graph['tasks'][3]['criteria'][-1],graph['tasks'][2]['output_contracts'][0]['validation'][0])
    def test_prepared_operation_has_typed_parameters_and_legacy_stays_fixed(self):
        options={'step_capabilities':['web.sources'],'prepared_research_policy_version':1}
        schema=planning_contract.contract(options)['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']['execution']
        planning_contract.validate({'capability':'web.sources.prepared','version':1,'parameters':{'domains':[]}},schema)
        with self.assertRaises(ValueError):planning_contract.validate({'capability':'web.sources.prepared','version':1,'parameters':{'domains':[],'queries':['invented']}},schema)
        self.assertEqual(execution.REGISTRY['web.sources']['max_inputs'],0)
        self.assertEqual(execution.REGISTRY['web.sources']['external_requests'],60)

    def test_count_policy_replaces_only_superseded_owned_criteria_on_fresh_plan(self):
        graph=self.graph();planning.validate_prepared_research(graph)
        source=graph['tasks'][2];review=graph['tasks'][3]
        review['criteria'].append('Selected variant facts must be supported.')
        source['output_contracts'][0]['validation'].append('Keep exact evidence.')
        historical=copy.deepcopy(graph);original_index=review['criteria'].index(planning.REQUIRED_SOURCE_COVERAGE)
        planning.validate_prepared_research(graph,count_policy='target')
        self.assertNotIn(planning.REQUIRED_SOURCE_COVERAGE,review['criteria'])
        self.assertNotIn(planning.REQUIRED_SOURCE_COVERAGE,source['output_contracts'][0]['validation'])
        self.assertEqual(review['criteria'][original_index],planning.TARGET_SOURCE_COVERAGE)
        self.assertIn('Selected variant facts must be supported.',review['criteria'])
        self.assertIn('Keep exact evidence.',source['output_contracts'][0]['validation'])
        self.assertIn(planning.REQUIRED_SOURCE_COVERAGE,historical['tasks'][3]['criteria'])
        saved=copy.deepcopy(graph);planning.validate_prepared_research(graph,count_policy='target')
        self.assertEqual(graph,saved)
        planning.validate_prepared_research(graph,count_policy='required')
        self.assertNotIn(planning.TARGET_SOURCE_COVERAGE,review['criteria'])
        self.assertIn(planning.REQUIRED_SOURCE_COVERAGE,review['criteria'])
    def test_missing_mandatory_evidence_is_a_blocking_requirement(self):
        finding={'category':'requirements','code':'coverage','message':'Three required options are missing','evidence':'All target option slots empty'}
        self.assertEqual(outcomes.disposition([finding]),'block')
        self.assertEqual(outcomes.disposition([outcomes.quality('style','Subjective finish preference','Preview')]),'user_review')
    def test_frozen_output_bound_is_recorded_without_changing_raw_plan_or_operations(self):
        value={'decision':'ready','message':'Prepare result','plan':{'brief':'Observed-item research','tasks':[
            {'limits':{'output_bytes':1000000}},
            {'execution':{'capability':'web.sources.prepared'},'limits':{'output_bytes':2000000}}]}}
        options={'limits':{'output_bytes':200000}};payload={'planner_budget_binding_version':1,'response_contract':{'version':1,'schema':{}}}
        result,bindings=planning_contract.prepare(value,payload,options)
        self.assertEqual(result['plan']['tasks'][0]['limits']['output_bytes'],200000)
        self.assertEqual(value['plan']['tasks'][0]['limits']['output_bytes'],1000000)
        self.assertEqual(result['plan']['tasks'][1]['limits']['output_bytes'],2000000)
        self.assertEqual(bindings[0]['source'],'options.limits.output_bytes')
        legacy,_=planning_contract.prepare(value,{'response_contract':{'version':1,'schema':{}}},options)
        self.assertEqual(legacy,value)

    def test_registered_child_consumes_exact_frozen_spec_without_generic_queries(self):
        with tempfile.TemporaryDirectory() as temp,patch('task_relay.gemini.read_config',return_value=CONFIG):
            factory=SourceFactory();rt=Runtime(Path(temp)/'runtime',ExecutionFactory(FakeFactory(),factory))
            try:
                source=Path(temp).resolve()/'queries.json';source.write_text(json.dumps(DATA));aid=rt.register(source,'Reviewed query fixture')
                task=assignment();task['execution']={'capability':'web.sources.prepared','version':1,'parameters':{'domains':[],'model':'fixture-text'}}
                task['criteria']=copy.deepcopy(execution.REGISTRY['web.sources.prepared']['criteria']);task['inputs']=[{'artifact':aid,'path':'queries.json','purpose':'Exact query fixture','authority':'Controlled input','media_type':'application/json'}]
                rt.create(plan([task]));rt.tick('demo');status=rt.tick('demo')
                self.assertEqual(status['status'],'completed',status)
                pack=json.loads(Path(rt.output('demo','sources','delivery/source-pack.json')['blob']).read_text())
                self.assertEqual(pack['entries'][0]['query'],DATA['targets'][0]['queries'][0]);self.assertEqual(pack['entries'][0]['target_ids'],['item-1'])
                self.assertEqual(factory.calls,1)
            finally:rt.close()
class RequirementRuntimeTests(unittest.TestCase):
    from tests.test_outcome_policy import Tests as PolicyTests
    setUp=PolicyTests.setUp
    tearDown=PolicyTests.tearDown
    graph=PolicyTests.graph
    finish=PolicyTests.finish
    def test_missing_required_evidence_holds_downstream_without_as_is_choice(self):
        self.graph();self.finish('produce')
        finding={'category':'requirements','code':'missing_options','message':'No required product options were supplied','evidence':'Every requested option slot is missing'}
        self.finish('review',[finding],decision='revise')
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','next')['attempts'],0)
        self.assertIsNone(self.rt.quality_review(self.rt.task('demo','produce')))
        self.assertEqual(len(self.factory.calls),2)

if __name__=='__main__':unittest.main()
