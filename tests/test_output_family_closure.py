"""Exact output-family handoffs; small text identities, no native application calls."""
import copy,unittest
from unittest.mock import patch
from orchestrator import handoff_closure as h,execution

class Tests(unittest.TestCase):
    def setUp(self):
        self.cap='fixture.native'
        self.ports={'out/model.dat':'application/x-fixture','out/view.png':'image/png','out/checks.json':'application/json'}
        self.scope=patch.dict(execution.REGISTRY,{self.cap:dict(outputs=self.ports)})
        self.scope.start();self.addCleanup(self.scope.stop)
        self.policy=h.capture_outputs([self.cap])
        self.producer=dict(id='corrected',execution=dict(capability=self.cap),inputs=[dict(artifact='old',path='old.dat',purpose='Prior rejected version',media_type='application/x-fixture',authority='Historical')],outputs=[dict(path=p,media_type=m,purpose='Fixed output') for p,m in self.ports.items()])

    def ref(self,task,path,mime):return dict(from_task=task,output=path,path=path,media_type=mime,purpose='Selected',authority='Unaccepted')

    def test_composed_graph_keeps_native_peer_out_of_renderer_but_in_final_review(self):
        section=dict(id='section',inputs=[self.ref('corrected','out/view.png','image/png')],outputs=[dict(path='section.json',media_type='application/json')])
        build=dict(id='build',execution={},inputs=[self.ref('section','section.json','application/json')],outputs=[dict(path='deck.pptx')])
        review=dict(id='review',inputs=[self.ref('build','deck.pptx','application/x-fixture')],outputs=[])
        tasks=[self.producer,section,build,review]
        h.bind(tasks,lambda _:None,lambda _:None,inherit=lambda task,item:not task.get('id')=='build' or item['media_type']=='image/png',output_policy=self.policy)
        self.assertNotIn('out/model.dat',[i.get('output') for i in build['inputs']])
        self.assertTrue({'out/model.dat','out/view.png','out/checks.json'}<={i.get('output') for i in review['inputs']})
        self.assertIn('old',[i.get('artifact') for i in review['inputs']])
        before=copy.deepcopy(tasks);h.bind(tasks,lambda _:None,lambda _:None,inherit=lambda task,item:task['id']!='build' or item['media_type']=='image/png',output_policy=self.policy)
        self.assertEqual(tasks,before)

    def test_in_worker_mapping_is_step_specific_not_all_worker_outputs(self):
        mapped={p:dict(path='worker/'+p,media_type=m,purpose='Mapped output') for p,m in self.ports.items()}
        task=dict(work_tools=dict(steps=dict(build=dict(operation=self.cap,outputs=mapped),inspect=dict(operation='other',outputs={'unrelated':dict(path='unrelated')}))))
        peers=h.output_peers(task,'worker/out/view.png',self.policy)
        self.assertEqual({p['path'] for p in peers},{'worker/out/model.dat','worker/out/checks.json'})
        mapped.pop('out/model.dat')
        with self.assertRaisesRegex(ValueError,'differs'):h.output_peers(task,'worker/out/view.png',self.policy)

    def test_legacy_policy_does_not_import_siblings_or_mutate_grant(self):
        policy={};h.validate_outputs(policy,[self.cap]);self.assertEqual(h.output_peers(self.producer,'out/view.png',policy),[]);self.assertEqual(policy,{})
        with self.assertRaisesRegex(ValueError,'differs'):h.validate_outputs({self.cap:{'out/secret':'text/plain'}},[self.cap])

    def test_registered_same_attempt_peers_remain_distinct_from_historical_inputs(self):
        old=dict(artifact='old-model',path='candidate.dat',purpose='Historical',authority='Old',media_type='application/x-fixture')
        new=dict(artifact='new-model',path='candidate.dat',purpose='Exact corrected peer',authority='Same attempt as selected preview',media_type='application/x-fixture')
        task=dict(id='review',inputs=[dict(artifact='preview-new',path='preview.png',purpose='New preview')],outputs=[])
        receipt=h.bind([task],lambda _:None,lambda aid:dict(id='producer',inputs=[old],companions=[new]) if aid=='preview-new' else None)
        self.assertEqual({i['artifact'] for i in task['inputs']},{'old-model','new-model','preview-new'})
        self.assertEqual(len({i['path'] for i in task['inputs']}),3)
        self.assertEqual(receipt[0]['inherited'][0]['via'],('artifact','preview-new'))
