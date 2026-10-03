"""Universal outcome coverage, general task graphs and incomplete-delivery recovery."""
import copy
import json
import unittest
from unittest.mock import Mock

from task_relay import request_contract as contracts, orchestrator_chat as chat
from task_relay import production_planning as planning, production_control as control
from orchestrator import deliverable_outputs as outputs
from tests.intake_fixtures import outcome, work
from tests import test_production_planning as fixture


REQUEST='Please create drafts in md for all 5 articles with examples and code snippets necessary to use these algorithms'
CONTRACT=work([outcome('articles',5,checks=['nonempty','utf8','fenced_code'])])


class Tests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        # The routing fixture's Desktop failure flag shadows unittest.fail.
        # This suite exercises production workers, never that Desktop adapter.
        del self.fail
    tearDown=fixture.Tests.tearDown
    def queue(self,ident=1,action=None,text=REQUEST,contract=CONTRACT):
        self.bridge.process({'update_id':ident,'message':{'text':'/orchestrator '+text,'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Prepare the requested work.','action':action or self.action(),'request_contract':contract})).tick()
        row=self.row(ident)
        self.assertIsNotNone(row,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()[0])
        return row
    row=fixture.Tests.row
    request=fixture.Tests.request
    action=fixture.Tests.action
    start=fixture.Tests.start
    click=fixture.Tests.click

    def response(self):
        result=fixture.Tests.response(self);produce,review=result['plan']['tasks']
        tasks=[];coverage={}
        for i in range(1,6):
            author=copy.deepcopy(produce);author['id']=f'author-{i}'
            author.pop('user_gate',None)
            author['outputs']=[{'path':f'article-{i}.md','purpose':f'Article {i}'}]
            inspector=copy.deepcopy(review);inspector['id']=f'review-{i}'
            inspector['review_of']=author['id'];inspector['dependencies']=[author['id']]
            inspector['inputs']=[{'from_task':author['id'],'output':f'article-{i}.md',
                                  'path':'candidate.md','purpose':'Review exact article','authority':'Unaccepted draft'}]
            tasks.extend([author,inspector])
            coverage[f'articles-{i}']={'task':author['id'],'output':f'article-{i}.md'}
        result['plan']['tasks']=tasks;result['deliverable_map']=coverage
        return result

    def test_frozen_intake_preserves_all_outcomes_context_and_does_not_start_workers(self):
        self.request(None,'Article topics: differential growth, reaction-diffusion, swarms, L-systems, topology optimization.')
        row=self.queue(2)
        options=json.loads(row['options']);payload=json.loads(row['context'])
        self.assertEqual(options['request_contract'],CONTRACT)
        self.assertEqual(len(options['deliverables']),5)
        self.assertEqual(row['request'],REQUEST)
        self.assertTrue(any('differential growth' in s['text'] for s in payload['source_texts']))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_plan_requires_every_distinct_output_and_its_review(self):
        row=self.queue(text=REQUEST)
        for kind in ('missing','wrong_extension','missing_review','duplicate_output'):
            result=self.response()
            if kind=='missing':result['deliverable_map'].pop('articles-5')
            elif kind=='duplicate_output':result['deliverable_map']['articles-5']=copy.deepcopy(result['deliverable_map']['articles-4'])
            elif kind=='wrong_extension':
                result['plan']['tasks'][0]['outputs'][0]['path']='article-1.txt'
                result['plan']['tasks'][1]['inputs'][0]['output']='article-1.txt'
                result['deliverable_map']['articles-1']['output']='article-1.txt'
            else:result['plan']['tasks'][1]['inputs']=[]
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                planning.validate_result(json.dumps(result),row)
        result,plan=planning.validate_result(json.dumps(self.response()),row)
        self.assertEqual(len(plan['deliverables']),5)
        self.assertEqual(sum('output_contracts' in t for t in plan['tasks']),5)
        self.assertEqual(self.factory.calls,[])

    def run_batch(self,missing=False):
        row=self.queue(text=REQUEST)
        planning.Worker(self.state,lambda *_:(json.dumps(self.response()),{})).tick()
        self.assertEqual(self.row()['status'],'ready',self.row()['error'])
        self.start(self.row())
        worker=control.Worker(self.state,lambda _:self.rt)
        for _ in range(20):
            worker.tick()
            running=[s for s in self.factory.sessions.values() if s['status']['status']=='running']
            if not running:break
            for session in running:
                frozen=session['frozen'];author=not frozen.get('review_of')
                absent=frozen['outputs'][0]['path'] if missing and frozen['id']=='author-5' else None
                self.factory.finish(frozen['assignment_id'],decision='delivered' if author else 'accept',missing=absent)
                if author and not absent:
                    (session['workspace']/frozen['outputs'][0]['path']).write_text('# Article\nExample:\n```python\nprint("example")\n```\n')
        worker.tick()
        return self.rt.status('production-1')

    def test_five_files_complete_only_after_their_independent_reviews(self):
        status=self.run_batch()
        self.assertEqual(status['status'],'completed',status)
        self.assertEqual(len(self.factory.calls),10)
        self.assertEqual(sum(t['status']=='completed' for t in status['tasks']),10)

    def test_missing_fifth_file_blocks_completion_and_preserves_other_articles(self):
        status=self.run_batch(missing=True)
        self.assertEqual(status['status'],'blocked',status)
        self.assertEqual(self.rt.task('production-1','author-5')['status'],'blocked')
        self.assertNotEqual(self.rt.task('production-1','review-5')['status'],'completed')
        self.assertEqual(sum(self.rt.task('production-1',f'author-{i}')['status']=='completed' for i in range(1,5)),4)

    def test_multiple_small_outputs_may_share_an_author_and_review(self):
        row=self.queue();result=self.response();author,review=result['plan']['tasks'][:2]
        author['outputs']=[];review['inputs']=[]
        for i in range(1,6):
            author['outputs'].append({'path':f'article-{i}.md','purpose':'Draft'})
            review['inputs'].append({'from_task':author['id'],'output':f'article-{i}.md','path':f'candidate-{i}.md','purpose':'Review','authority':'Unaccepted draft'})
            result['deliverable_map'][f'articles-{i}']['task']=author['id']
        result['plan']['tasks']=[author,review]
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(len(plan['tasks']),2)
        self.assertEqual(len(plan['tasks'][0]['output_contracts']),5)

    def test_unrelated_csv_json_and_python_outcomes_use_the_same_contract(self):
        contract=work([outcome('dataset',format='.csv'),outcome('config',format='.json',checks=['nonempty','json']),outcome('script',format='.py')])
        row=self.queue(text='Export a dataset, config and analysis script.',contract=contract)
        result=self.response();result['plan']['tasks']=result['plan']['tasks'][:6];result['deliverable_map']={}
        for i,(ident,item) in enumerate(contracts.slots(contract).items()):
            author,review=result['plan']['tasks'][i*2:i*2+2];path=ident+item['format']
            author['outputs'][0]['path']=path;review['inputs'][0]['output']=path
            result['deliverable_map'][ident]={'task':author['id'],'output':path}
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(len(plan['tasks']),6)
        self.assertEqual(set(plan['deliverables']),{'dataset','config','script'})

    def test_general_parallel_graph_does_not_require_a_domain_flag(self):
        row=fixture.Tests.queue(self,text='Prepare the requested outcomes.')
        result=self.response();result['deliverable_map']={}
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertEqual(len(plan['tasks']),10)
        modified=json.loads(row['options']);modified['max_tasks']=6
        row=dict(row);row['options']=json.dumps(modified)
        with self.assertRaisesRegex(ValueError,'frozen stage budget'):
            planning.validate_result(json.dumps(result),row)


class ContractTests(unittest.TestCase):
    def test_inline_work_cannot_satisfy_a_frozen_file_request(self):
        for contract in (CONTRACT,work([outcome('photos',3,format='.png',checks=['nonempty'])])):
            with self.subTest(contract=contract),self.assertRaisesRegex(ValueError,'inline text'):
                contracts.route({'answer':'All done.','action':None,'request_contract':contract})

    def test_route_cannot_reduce_requested_count_or_change_frozen_scope(self):
        action={'kind':'plan_production','deliverables':{'articles-1':'Only one'}}
        with self.assertRaisesRegex(ValueError,'omitted'):
            contracts.route({'action':action,'request_contract':CONTRACT})
        for mode in ('answer','clarify'):
            with self.assertRaisesRegex(ValueError,'cannot dispatch'):
                contracts.route({'action':action,'request_contract':{'mode':mode,'reason':'A question or ambiguity.','outcomes':[]}})
        with self.assertRaisesRegex(ValueError,'multiple bounded stages'):
            options={'deliverables':{}}
            contracts.freeze(options,work([outcome(count=20)]))
        with self.assertRaisesRegex(ValueError,'change the frozen'):
            contracts.seal(json.dumps({'answer':'Done','action':None,'request_contract':{'mode':'answer','reason':'changed','outcomes':[]}}),CONTRACT)

    def test_structural_output_checks_apply_across_formats(self):
        assignment={'outputs':[{'path':'result.json'}],'output_contracts':[{'path':'result.json','format':'.json','checks':['nonempty','json']}]}
        for raw in (b'',b'  ',b'not json',b'\xff'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):outputs.check_delivery(assignment,lambda _:raw)
        outputs.check_delivery(assignment,lambda _:b'{"result":1}')
        assignment={'outputs':[{'path':'article.md'}],'output_contracts':[{'path':'article.md','format':'.md','checks':['nonempty','utf8','fenced_code']}]}
        for data in (b'',b'  \n',b'\xff',b'# Article\nNo code.',b'```python\nprint(1)',b'```python\n \n```'):
            with self.subTest(data=data),self.assertRaises(ValueError):outputs.check_delivery(assignment,lambda _:data)
        outputs.check_delivery(assignment,lambda _:b'# Article\n```python\nprint(1)\n```\n')
        assignment={'outputs':[{'path':'image.png'}],'output_contracts':[{'path':'image.png','format':'.png','checks':['nonempty']}]}
        outputs.check_delivery(assignment,lambda _:b'\x89PNG binary bytes')

    def test_pipeline_covers_all_outcomes_without_truncating_them(self):
        contract=work([outcome('reports',10)])
        declared=contracts.descriptions(contract)
        action={'kind':'plan_pipeline','stage_details':[{'outputs':{k:{'description':v,'format':'markdown'} for k,v in declared.items()}}]}
        contracts.route({'action':action,'request_contract':contract})
        action['stage_details'][0]['outputs'].pop('reports-10')
        with self.assertRaisesRegex(ValueError,'workflow stages'):
            contracts.route({'action':action,'request_contract':contract})

    def test_stage_scope_preserves_requested_format_checks_and_only_its_outputs(self):
        contract=work([outcome('reports',10,format='.json',checks=['nonempty','json'])])
        original=contracts.descriptions(contract)
        stage={'deliverables':{'reports-7':original['reports-7'],'intermediate':'Preparation for this stage'}}
        narrowed=contracts.for_stage(contract,stage)
        self.assertEqual(set(contracts.descriptions(narrowed)),{'reports-7','intermediate'})
        self.assertEqual(contracts.slots(narrowed)['reports-7']['format'],'.json')
        self.assertIn('json',contracts.slots(narrowed)['reports-7']['checks'])
        stage['deliverables']['reports-7']='A different output'
        with self.assertRaisesRegex(ValueError,'changed a frozen'):
            contracts.for_stage(contract,stage)

    def test_unresolved_work_retains_scope_but_cannot_execute_a_route(self):
        for status in ('needs_input','blocked'):
            value={'answer':'The source version or required capability is missing.','action':None,'work_status':status,'request_contract':CONTRACT}
            self.assertEqual(contracts.route(value),value)
            value['action']={'kind':'plan_production'}
            with self.assertRaisesRegex(ValueError,'unresolved scope'):
                contracts.route(value)
