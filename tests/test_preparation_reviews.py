import copy
import unittest
from task_relay import preparation_reviews


class Tests(unittest.TestCase):
    def test_pure_registered_json_preparation_gets_review_but_effectful_native_work_does_not(self):
        proposal,scope,options=self.fixture();producer=proposal['plan']['tasks'][0];producer.pop('worker');producer['execution']={'capability':'fixture.project'}
        scope['graph_operations'].append(dict(id='fixture.project',kind='procedure',external_requests=0,output_type='application/json'))
        before=copy.deepcopy(proposal);self.assertTrue(preparation_reviews.bind(proposal,scope,options))
        review=proposal['plan']['tasks'][-1];self.assertEqual(review['review_of'],'prepare');self.assertNotIn('execution',review);self.assertIn(review['id'],proposal['plan']['tasks'][1]['dependencies'])
        scope['graph_operations'][-1]['external_requests']=1
        self.assertEqual(preparation_reviews.bind(before,scope,options),[])

    def fixture(self):
        producer=dict(id='prepare',criteria=['References come from declared evidence'],
            outputs=[dict(path='manifest.json',media_type='application/json',purpose='Observed references')],
            worker=dict(executor='code',requires=['files.text','code.execute']))
        consumer=dict(id='fetch',execution={'capability':'fixture.fetch'},
                      inputs=[dict(from_task='prepare',output='manifest.json')],dependencies=['prepare'])
        proposal=dict(plan=dict(tasks=[producer,consumer]),deliverable_map={'photos':{'task':'fetch','output':'photos.zip'}})
        scope=dict(connector_companions_version=1,delivery_completion_policy_version=1,
                   graph_operations=[dict(id='fixture.fetch',kind='procedure')])
        options=dict(max_tasks=3,max_attempts=2,limits=dict(seconds=600,tool_calls=15,output_bytes=512000))
        return proposal,scope,options

    def test_missing_preparation_review_gates_dispatch_and_keeps_exact_criteria(self):
        proposal,scope,options=self.fixture();before=copy.deepcopy(proposal)
        receipts=preparation_reviews.bind(proposal,scope,options)
        review=proposal['plan']['tasks'][-1]
        self.assertEqual(review['review_of'],'prepare');self.assertEqual(review['criteria'],before['plan']['tasks'][0]['criteria'])
        self.assertEqual(review['inputs'][0]['output'],'manifest.json')
        self.assertIn(review['id'],proposal['plan']['tasks'][1]['dependencies'])
        self.assertEqual(proposal['deliverable_map'],before['deliverable_map']);self.assertTrue(receipts)
        self.assertEqual(preparation_reviews.bind(proposal,scope,options),[])

    def test_legacy_host_api_deliverable_and_user_gate_are_not_expanded(self):
        for variation in ('legacy','host','api','deliverable','gate'):
            proposal,scope,options=self.fixture()
            if variation=='legacy':scope={}
            elif variation in ('host','api'):scope['graph_operations'][0]['kind']=variation
            elif variation=='deliverable':proposal['deliverable_map']['manifest']={'task':'prepare','output':'manifest.json'}
            else:proposal['plan']['tasks'][0]['user_gate']='Choose exact inputs'
            before=copy.deepcopy(proposal)
            self.assertEqual(preparation_reviews.bind(proposal,scope,options),[]);self.assertEqual(proposal,before)

    def test_existing_review_and_task_ceiling_are_preserved(self):
        proposal,scope,options=self.fixture();options['max_tasks']=2
        with self.assertRaisesRegex(ValueError,'frozen task ceiling'):preparation_reviews.bind(proposal,scope,options)
        self.assertEqual(len(proposal['plan']['tasks']),2)
        proposal['plan']['tasks'].append(dict(id='review',review_of='prepare'))
        self.assertEqual(preparation_reviews.bind(proposal,scope,options),[])


if __name__=='__main__':unittest.main()
