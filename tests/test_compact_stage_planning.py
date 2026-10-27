"""Planning manifests stay small; execution still binds exact original evidence."""
import copy
import json
import unittest
from unittest.mock import Mock,patch

from orchestrator import contracts as c
from task_relay import planner_view,production_planning as planning,planning_contract


class Tests(unittest.TestCase):
    def test_native_graph_context_reaches_unique_semantic_owner_without_changing_wire_inputs(self):
        from task_relay import artifact_bindings
        source=dict(artifact='notes',path='notes.md',purpose='Required notes',authority='Source context',sha256='a'*64,bytes=4,media_type='text/markdown')
        payload=dict(handoff_binding_version=1,sources=[source],input_ports={'prior.notes':source},pipeline_step=dict(handoff=dict(inputs=[dict(stage='prior',deliverable='notes',consumer='context')])))
        producer=dict(id='make',execution={'capability':'fixture.native','parameters':{}},input_bindings=[],outputs=[dict(path='out.json',purpose='Candidate')])
        review=dict(id='review',review_of='make',input_bindings=[],outputs=[])
        raw=dict(plan=dict(tasks=[producer,review]));before=copy.deepcopy(raw)
        value,receipts=artifact_bindings.build(raw,payload)
        self.assertEqual(value['plan']['tasks'][0]['inputs'],[])
        self.assertEqual(value['plan']['tasks'][1]['inputs'][0]['artifact'],'notes')
        self.assertEqual(receipts[1]['compiled_context_ports'],['prior.notes']);self.assertEqual(raw,before)
        raw['plan']['tasks'].append(dict(review,id='other'))
        value,_=artifact_bindings.build(raw,payload)
        self.assertFalse(any(i.get('artifact')=='notes' for t in value['plan']['tasks'] for i in t['inputs']))

    def test_provider_receives_manifest_without_copying_evidence_or_changing_ledger(self):
        payload=dict(planner_view_version=1,planner_request='Make the requested reviewed file.',
                     planner_instructions='Compose compatible connectors within this scope.',
                     original_request='Stage instruction plus full retained audit.'*1000,
                     pipeline_step={'id':'arbitrary','capabilities':['text.bundle']},
                     sources=[dict(artifact='saved',sha256='a'*64,path='exact.json',bytes=90000)],
                     source_texts=[dict(artifact='saved',text='Full immutable evidence.'*4000)],
                     structural_correction=dict(error='Bad binding',previous_response={'plan':None}),
                     options=dict(limits={'seconds':123},step_capabilities=['text.bundle']))
        before=copy.deepcopy(payload);client=Mock()
        client.request.return_value={'candidates':[{'content':{'parts':[{'text':'{}'}]}}]}
        with patch.object(planning.gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(planning.gemini,'Client',return_value=client):
            planning.generate({'provider':'gemini','model':'gemini-3.7-flash'},payload)
        sent=client.request.call_args.args[1];wire=json.loads(sent['contents'][0]['parts'][0]['text'])
        self.assertEqual(wire['original_request'],payload['planner_request'])
        self.assertEqual(wire['sources'],before['sources'])
        self.assertEqual(wire['options'],before['options'])
        self.assertEqual(wire['structural_correction'],before['structural_correction'])
        self.assertLess(len(json.dumps(wire)),2000)
        self.assertEqual(payload,before)
        self.assertEqual(planner_view.request_receipt(payload)['provider_input'],wire)

    def test_structured_planner_constrains_reasoning_without_expanding_output_allowance(self):
        payload=dict(planner_instructions='Compose the graph',options={},sources=[])
        client=Mock();client.request.return_value={'candidates':[{'content':{'parts':[{'text':'{}'}]}}]}
        with patch.object(planning.gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(planning.gemini,'Client',return_value=client):
            for model in ('gemini-3.7-flash','gemini-3.1-pro-preview','gemini-2.5-flash','unrecognized-model'):
                with self.subTest(model=model):
                    self.assertEqual(planning.generate({'provider':'gemini','model':model},payload)[0],'{}')
                    config=client.request.call_args.args[1]['generationConfig']
                    self.assertEqual(config['maxOutputTokens'],10000)
                    self.assertEqual(config.get('thinkingConfig'),{'thinkingLevel':'low'} if model.startswith('gemini-3.') else None)

    def test_scoped_instructions_do_not_include_unselected_host_or_media_recipes(self):
        payload=dict(planner_view_version=1,graph_operations=[{'id':'text.bundle'}])
        compact=planner_view.system(payload,'Huge unrelated host/media recipes')
        self.assertLess(len(compact),6000)
        self.assertIn('response_contract.schema',compact)
        self.assertIn('Unknown values remain',compact)
        self.assertNotIn('unrelated host/media',compact)
        for policy in ({'operation_builder':{'version':1}},{'design_intent_policy':1},
                       {'research_campaign':{'version':1}},
                       {'graph_operations':[{'id':'any.host','requires_registered_inputs':True}]}):
            self.assertEqual(planner_view.system({**payload,**policy},'Retained exact-code guide'),'Retained exact-code guide')

    def test_routing_omits_large_prior_results_but_full_inputs_remain_available(self):
        inputs=dict(sources=[{'artifact':'saved'}],prior_results=[dict(id='earlier',result='Full audit.'*10000)],
                    handoffs=[{'kind':'context','result':'An exact upstream instruction'}],request_contract={'outcomes':['Requested file']})
        before=copy.deepcopy(inputs)
        view=planner_view.stage_prompt({'route':'production','id':'next'},'Exact request',inputs)
        self.assertLess(len(json.dumps(view)),1500)
        self.assertEqual(view['handoffs'],inputs['handoffs'])
        self.assertEqual(view['prior_results'][0]['result_sha256'],c.digest(inputs['prior_results'][0]['result']))
        self.assertEqual(inputs,before)
        self.assertEqual(planner_view.stage_prompt({'route':'conversation'},'Exact request',inputs)['prior_results'],inputs['prior_results'])

    def test_port_compiles_through_normal_planner_with_exact_versions_and_review_edges(self):
        from tests.test_contract_builders import BindingTests
        f=BindingTests();f.setUp();self.addCleanup(f.tearDown)
        row=dict(f.queue());payload=json.loads(row['context']);source=payload['sources'][0]
        handoff=dict(kind='artifact',stage='arbitrary_stage',deliverable='evidence',media_type='application/json',source=source)
        payload['input_ports']=planner_view.ports(payload['sources'],[handoff])
        payload['handoff_binding_version']=payload['options']['handoff_binding_version']=1
        payload['response_contract']=planning_contract.contract(payload['options'],bindings=True)
        row['context']=c.encoded(payload)
        value=f.compact();value['plan']['tasks'][0]['input_bindings']=[dict(port='arbitrary_stage.evidence')]
        original=copy.deepcopy(value);_,plan=planning.validate_result(c.encoded(value),row)
        bound=next(i for i in plan['tasks'][0]['inputs'] if i.get('artifact')==source['artifact'])
        self.assertEqual(bound['path'],source['path']);self.assertEqual(bound['authority'],source['authority'])
        receipt=plan['origin']['artifact_bindings']['tasks'][0]
        self.assertEqual(receipt['input_versions'],[dict(artifact=source['artifact'],sha256=source['sha256'])])
        self.assertEqual(receipt['selections'],[dict(port='arbitrary_stage.evidence')])
        self.assertEqual(plan['tasks'][1]['dependencies'],['produce'])
        self.assertEqual(value,original);self.assertEqual(f.factory.calls,[])
        for change in ('unknown','version','legacy','duplicate'):
            bad=copy.deepcopy(payload);candidate=copy.deepcopy(value)
            if change=='unknown':candidate['plan']['tasks'][0]['input_bindings'][0]['port']='unbound.output'
            elif change=='version':bad['input_ports']['arbitrary_stage.evidence']['sha256']='b'*64
            elif change=='legacy':bad.pop('handoff_binding_version')
            else:candidate['plan']['tasks'][0]['input_bindings'].append(dict(source=source['artifact']))
            with self.subTest(change=change),self.assertRaises(ValueError):
                planning.validate_result(c.encoded(candidate),{**row,'context':c.encoded(bad)})

    def test_alias_selection_rejects_changed_or_ambiguous_handoffs(self):
        source=dict(artifact='alias',path='saved.txt',bytes=4,sha256='a'*64,purpose='Source',authority='Candidate')
        origin={**source,'artifact':'original'}
        edge=dict(kind='artifact',stage='any',deliverable='text',media_type='text/plain',source=origin)
        self.assertEqual(planner_view.ports([source],[edge])['any.text']['artifact'],'alias')
        for sources in ([{**source,'sha256':'b'*64}],[source,{**source,'artifact':'second'}]):
            with self.assertRaisesRegex(ValueError,'ambiguous'):planner_view.ports(sources,[edge])
        # A frozen identity is preferred over a byte-identical unrelated alias.
        self.assertEqual(planner_view.ports([origin,source],[edge])['any.text']['artifact'],'original')

    def test_real_stage_dispatch_retains_full_context_and_records_exact_provider_view(self):
        from tests import test_delivery_completion as fixtures
        from task_relay import pipelines
        f=fixtures.Tests();f.setUp();self.addCleanup(f.tearDown)
        action=f.action()
        action['stages'][1]['handoff']['inputs']=[dict(stage='outline',deliverable='outline',consumer='context',media_type='text/plain')]
        p=f.create(action=action);f.complete_stage(p,'outline');pipelines.tick(f.state)
        action=dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,
                    research_ids=[],artifact_ids=[],reference_ids=[],planning_only=False,
                    research_mode='none',step_capabilities=[],deliverables={'finish':'Exact finish output'})
        f.answer(action);stage=f.step(p,'finish')
        row=f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        payload=json.loads(row['context'])
        port=payload['input_ports']['outline.outline']
        source=next(s for s in payload['sources'] if s['artifact']==port['artifact'])
        self.assertEqual(port['sha256'],source['sha256']);planning.verify_artifact(f.rt,source)
        archive=pipelines.request_context(f.state,stage['request_id'])['inputs']
        self.assertIn('result',archive['prior_results'][0])
        self.assertEqual(payload['planner_request'],p['request'])
        seen=[]
        def no_provider(_,context):seen.append(copy.deepcopy(context));return c.encoded(dict(decision='needs_input',message='Controlled fixture only',plan=None)),{}
        planning.Worker(f.state,no_provider).tick()
        receipt=f.state.db.execute('SELECT request FROM production_plan_calls WHERE plan_id=?',(row['id'],)).fetchone()
        request=json.loads(receipt[0]);self.assertEqual(request['provider_input'],planner_view.provider_payload(seen[0]))
        self.assertTrue(request['source_texts']);self.assertEqual(request['provider_input']['source_texts'],[])
        self.assertEqual(payload,json.loads(f.state.db.execute('SELECT context FROM production_plans WHERE id=?',(row['id'],)).fetchone()[0]))


if __name__=='__main__':unittest.main()
