"""A mixed query/catalog graph compiles service-owned fields without model repair."""
import copy,json,unittest
from unittest.mock import patch
from orchestrator import contracts as c,executors,execution,worker_capabilities
from task_relay import production_planning as planning,gemini
from tests import test_production_planning as fixtures

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request;queue=fixtures.Tests.queue;row=fixtures.Tests.row
    action=fixtures.Tests.action;response=fixtures.Tests.response

    configuration=None
    record_version=1
    fresh_scope=False
    record_count=1
    coverage_round=False

    def test_record_scope_extensions_preserve_connector_snapshots_and_limits(self):
        from task_relay.planning_contract import operation_capabilities
        from orchestrator.connector_protocol import capture
        baseline=capture('records.merge')
        for version in (1,2):
            capabilities=operation_capabilities({'records.merge','images.catalog','collection.slides'},dict(record_interfaces_version=version))
            self.assertTrue({'records.merge','images.catalog','collection.slides'}<=capabilities)
        for version in (None,99):
            self.assertFalse(operation_capabilities({'records.merge','images.catalog','collection.slides'},dict(record_interfaces_version=version)))
        self.assertEqual(capture('records.merge'),baseline)

    def test_large_coverage_graph_is_partitioned_by_code_and_survives_revalidation(self):
        self.fresh_scope=True;self.record_count=24;self.coverage_round=True
        self.test_prepared_helpers_review_edges_outputs_and_api_limits_compose()

    def test_registered_generic_partition_handoffs_across_configurations(self):
        from tests.test_universal_interfaces import CONFIGURATIONS
        self.fresh_scope=True;self.record_count=24;self.coverage_round=True
        for version in (1,2):
            for name,configuration in CONFIGURATIONS.items():
                with self.subTest(version=version,configuration=name):
                    self.configuration=configuration;self.record_version=version
                    self.test_prepared_helpers_review_edges_outputs_and_api_limits_compose()

    def test_fresh_workload_and_rendered_companions_compile(self):
        self.fresh_scope=True
        self.test_prepared_helpers_review_edges_outputs_and_api_limits_compose()

    def test_prepared_helpers_review_edges_outputs_and_api_limits_compose(self):
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'fixture'}}),patch.object(execution,'available'):
            row=dict(self.queue(action=self.action(step_capabilities=['web.sources']),text='Verify manufacturer catalog SKU sources online.'))
        payload=json.loads(row['context']);opts=json.loads(row['options']);opts['worker_catalog'].append(worker_capabilities.entry({'type':'gemini-agent','model':'fixture'}));payload['options']=opts
        asset=self.rt.root/'inventory.json';asset.write_text(json.dumps(dict(items=[dict(id='VIS-'+str(n+1).zfill(3),label='Desk') for n in range(self.record_count)])))
        aid=self.rt.register(asset,'Synthetic inventory');source=planning.source_entry(self.rt,aid,'inventory.json','Exact inventory','Fixture data');payload['sources'].append(source);payload['required_artifacts'].append(aid)
        if self.fresh_scope:
            payload['connector_companions_version']=opts['connector_companions_version']=1
            payload['assignment_input_policy_version']=1
            payload['delivery_completion_policy_version']=opts['delivery_completion_policy_version']=1
            opts['max_tasks']=30
            from orchestrator import execution as ex
            payload['graph_operations'].append(dict(id='web.sources.rendered',available=True,**ex.REGISTRY['web.sources.rendered']))
            payload['graph_operations'].append(dict(id='sourcing.merge',available=True,**ex.REGISTRY['sourcing.merge']))
            if self.coverage_round:
                payload['sourcing_count_policy']='target'
                payload['graph_operations'].append(dict(id='web.sources.coverage',available=True,**ex.REGISTRY['web.sources.coverage']))
            for op in payload['graph_operations']:
                if op['id'] in ('web.sources','web.sources.prepared'):op['companions']=copy.deepcopy(ex.REGISTRY[op['id']]['companions'])
        if self.configuration:
            payload['record_interfaces_version']=opts['record_interfaces_version']=self.record_version
            payload['graph_operations'].append(dict(id='records.merge',available=True,**execution.REGISTRY['records.merge']))
        row.update(context=c.encoded(payload),options=c.encoded(opts))
        value=self.response();base,base_review=value['plan']['tasks']
        def author(ident,output,inputs):
            t=copy.deepcopy(base);t.pop('user_gate',None);t.pop('tools',None);t.update(id=ident,inputs=inputs,outputs=[dict(path=output,purpose='Synthetic output')],dependencies=[],worker={'requires':['files.text']},limits=dict(seconds=600,tool_calls=30,output_bytes=200000));return t
        def edge(ident,path):return dict(from_task=ident,output=path,path='upstream/'+ident+'/'+path,purpose='Exact candidate',authority='Unaccepted fixture')
        def review(ident,producer,inputs):
            t=author(ident,'delivery/'+ident+'.md',inputs);t['review_of']=producer;t['dependencies']=[producer];return t
        inv={k:source[k] for k in ('artifact','path','purpose','authority')}
        query=author('queries','delivery/queries.json',[inv]);qr=review('query_review','queries',[edge('queries','delivery/queries.json')])
        search=author('search','delivery/source-pack.json',[edge('queries','delivery/queries.json')]);search.pop('worker');search['tools']=[];search['dependencies']=['queries'];search['execution']=dict(capability='web.sources.prepared',version=1,parameters={'domains':[],'model':'fixture'});search['criteria']=copy.deepcopy(execution.REGISTRY['web.sources.prepared']['criteria']);search['max_attempts']=1;search['limits']=dict(seconds=600,tool_calls=1,output_bytes=2000000);search['outputs'][0]['media_type']='application/json'
        sr=review('source_review','search',[edge('search','delivery/source-pack.json'),edge('queries','delivery/queries.json')]);sr['criteria']=copy.deepcopy(search['criteria'])
        catalog=author('catalog','delivery/catalog.json',[inv,edge('search','delivery/source-pack.json'),edge('source_review','delivery/source_review.md')]);catalog['outputs'].append(dict(path='delivery/catalog.md',purpose='Schedule'));catalog['limits']['provider_requests']=30;catalog['sourcing']=dict(version=1,inventory={'source':aid},source_pack={'producer':'search','output':'delivery/source-pack.json'},options_per_item=3,count_policy='target',max_records=self.record_count)
        if self.configuration:
            intent=catalog.pop('sourcing')
            catalog['records']=dict(family=dict(id='collection.options',version=1),inputs=dict(inventory_path=intent['inventory'],source_pack_path=intent['source_pack']),parameters=dict(**{k:intent[k] for k in ('options_per_item','count_policy','max_records')},field_definitions=self.configuration['fields'],identity_field=self.configuration['identity']))
        cr=review('catalog_review','catalog',[inv,edge('catalog','delivery/catalog.json'),edge('catalog','delivery/catalog.md'),edge('search','delivery/source-pack.json')]);cr['limits']['tool_calls']=20
        from orchestrator.sourcing_contract import SEMANTIC_CRITERION
        cr['criteria'].append(SEMANTIC_CRITERION)
        value['plan']['tasks']=[query,qr,search,sr,catalog,cr];before=copy.deepcopy(value)
        _,plan=planning.validate_result(c.encoded(value),row);tasks={t['id']:t for t in plan['tasks']}
        self.assertEqual(value,before)
        from orchestrator import handoff_contracts as handoff
        family='collection.options' if self.configuration else 'sourcing.options'
        bound_stage=dict(handoff=dict(inputs=[],outputs={'catalog':dict(media_type='application/json',content_contract=dict(id=family,version=1))}))
        bound_graph=copy.deepcopy(plan)
        bound_graph['deliverables']={'catalog':dict(task='catalog',output='delivery/catalog.json')}
        handoff.bind_stage(bound_stage,bound_graph)
        # Reject contradictory producer intents before fallback rewrites either.
        conflicting=copy.deepcopy(value)
        owner=next(t for t in conflicting['plan']['tasks'] if t['id']=='catalog')
        owner['records' if 'sourcing' in owner else 'sourcing']={}
        with self.assertRaisesRegex(ValueError,'one record intent'):
            planning.validate_result(c.encoded(conflicting),row)
        if self.coverage_round:
            merge='records.merge' if self.configuration else 'sourcing.merge'
            family='collection.options' if self.configuration else 'sourcing.options'
            self.assertEqual(tasks['catalog']['execution']['capability'],merge)
            self.assertEqual(tasks['catalog_seed']['execution']['capability'],merge)
            self.assertEqual(tasks['catalog_coverage']['execution']['capability'],'web.sources.coverage')
            self.assertIn('catalog_seed',tasks['catalog_coverage']['dependencies'])
            self.assertNotIn('catalog_review_seed',tasks)
            self.assertNotIn('catalog_review',tasks)
            for prefix in ('catalog','catalog_seed'):
                chunks=[t for t in tasks.values() if t.get('operation_contract',{}).get('id')==family and t['id'].startswith(prefix+'_batch_')]
                self.assertEqual(len(chunks),3)
                self.assertEqual([t['operation_contract']['parameters']['record_range'] for t in chunks],[[0,10],[10,20],[20,24]])
                self.assertTrue(all(t['limits']['provider_requests']<=24 for t in chunks))
            # Normal saved-plan revalidation must retain compiler-owned fields,
            # never produce another recovery round or repartition its graph.
            _,again=planning.validate_result(c.encoded(value),row)
            self.assertEqual(plan,again)
            return
        if self.fresh_scope:
            self.assertEqual(len(tasks),8)
            self.assertEqual(tasks['catalog']['operation_contract']['parameters']['source_pack_path'],'upstream/search/delivery/source-pack.json')
            self.assertEqual(next(i['from_task'] for i in tasks['catalog']['inputs'] if i['path']=='upstream/search/delivery/source-pack.json'),'search_rendered')
            self.assertIn('search_rendered_review',tasks['catalog']['dependencies'])
            self.assertEqual(tasks['search_rendered']['execution']['parameters']['domains'],[])
            self.assertEqual(tasks['search_rendered_review']['review_of'],'search_rendered')
        self.assertIn('query_review',tasks['search']['dependencies'])
        self.assertEqual(tasks['catalog']['worker']['executor'],'gemini-agent')
        self.assertEqual(tasks['catalog']['limits']['provider_requests'],24)
        self.assertEqual(tasks['catalog_review']['limits']['provider_requests'],24 if self.fresh_scope else 20)
        self.assertEqual(tasks['catalog_review']['operation_contract']['output'],'delivery/catalog_review.json')
        self.assertNotIn(SEMANTIC_CRITERION,tasks['catalog']['criteria'])
        self.assertEqual(tasks['catalog_review']['criteria'].count(SEMANTIC_CRITERION),1)
        helper='operation-support/web.sources.prepared/validate.py'
        self.assertFalse(any(i['path']==helper for i in tasks['queries']['inputs']))
        self.assertEqual(tasks['queries']['operation_contract']['parameters']['target'],'web.sources.prepared')
        for name in ('catalog','catalog_review'):self.assertFalse(any(i['path']==helper for i in tasks[name]['inputs']))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])
        from task_relay import pipelines
        spec={'stages':[{'capabilities':['web.sources'],'research_mode':'sources'}]}
        pipe={'id':'scope-fixture','spec':c.encoded(spec)};step={'position':0,'id':'catalog'}
        grant={'automatic_worker_backends':[x['backend'] for x in opts['worker_catalog']], 'automatic_task_seconds':1800,'automatic_task_attempts':2}
        with self.state.db:pipelines.event(self.state,'scope-fixture',None,'created',grant)
        payload['delivery_completion_policy_version']=1
        approved={**row,'plan':c.encoded(plan),'context':c.encoded(payload)}
        self.assertTrue(pipelines.check_plan(self.state,pipe,step,approved))
        legacy=copy.deepcopy(payload);legacy.pop('prepared_research_policy_version')
        with self.assertRaisesRegex(ValueError,'expanded workflow capabilities'):
            pipelines.check_plan(self.state,pipe,step,{**approved,'context':c.encoded(legacy)})
        narrow=copy.deepcopy(spec);narrow['stages'][0]['capabilities']=[]
        with self.assertRaisesRegex(ValueError,'expanded workflow capabilities'):
            pipelines.check_plan(self.state,{**pipe,'spec':c.encoded(narrow)},step,approved)
