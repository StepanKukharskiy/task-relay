"""Proposed validation is not a completed source finding."""
import json
import unittest
from task_relay import orchestrator_advice as advice,orchestrator_chat as chat

class Tests(unittest.TestCase):
    def reply(self,basis='proposed_work'):
        return {'answer':'This workflow will produce three verified purchasable options per item. No product pages have been checked yet.',
                'action':None,'answer_basis':basis,'claim_sources':[], 'next_options':[],
                'research_advice':{'recommended_mode':'sources','requirement':'required',
                                   'reason':'Future pricing and availability need page reads.','questions':[]}}
    def test_future_verification_proposal_does_not_need_already_read_pages(self):
        value=self.reply()
        raw=json.dumps(value)
        self.assertEqual(advice.validate(raw,'How would you plan sourcing?',[],{'sources':[]}),raw)
        self.assertEqual(chat.interpret(raw,{})['answer_basis'],'proposed_work')
    def test_negated_verification_in_gap_is_not_a_verified_guide(self):
        value=self.reply('supplied_context');value['answer']='Nothing is verified yet; current prices require page reads.'
        advice.validate(json.dumps(value),'Explain the missing source evidence.',[],{'sources':[]})
    def test_factual_findings_need_pages_even_without_verification_words(self):
        value=self.reply('source_findings');value['answer']='The lamp costs USD 100.'
        for sources in ([],[{'kind':'search_result','url':'https://retailer.example/lamp'}]):
            with self.subTest(sources=sources),self.assertRaisesRegex(advice.AdviceError,'recorded page reads'):
                advice.validate(json.dumps(value),'Check product prices.',[],{'sources':sources})
    def test_retrieval_alone_does_not_ground_a_claim(self):
        value=self.reply('source_findings');value['answer']='The lamp costs USD 100.'
        evidence={'sources':[{'kind':'page','url':'https://retailer.example/lamp'}]}
        with self.assertRaisesRegex(advice.AdviceError,'exact answer claims'):
            advice.validate(json.dumps(value),'Check product prices.',[],evidence)
        value['claim_sources']=[{'statement':value['answer'],'source_urls':['https://retailer.example/lamp']}]
        advice.validate(json.dumps(value),'Check product prices.',[],evidence)
        value['claim_sources'][0]['source_urls']=['https://invented.example/lamp']
        with self.assertRaisesRegex(advice.AdviceError,'recorded page reads'):
            advice.validate(json.dumps(value),'Check product prices.',[],evidence)
    def test_proposal_cannot_carry_unrecorded_factual_source_claim(self):
        value=self.reply();value['claim_sources']=[{'statement':value['answer'],'source_urls':['https://invented.example/lamp']}]
        with self.assertRaisesRegex(advice.AdviceError,'recorded page reads'):
            advice.validate(json.dumps(value),'Plan sourcing.',[],{'sources':[]})
    def test_historical_untyped_actual_guide_remains_rejected(self):
        value=self.reply();value.pop('answer_basis');value['answer']='Here are the verified hardware pinouts.'
        with self.assertRaisesRegex(advice.AdviceError,'recorded page reads'):
            advice.validate(json.dumps(value),'Check hardware pinouts.',[],{'sources':[]})
    def test_typed_tool_envelope_preserves_scope_without_dispatch(self):
        value=self.reply();value['action_json']=None;value.pop('action')
        parsed=chat.response_json(json.dumps(value));self.assertEqual(parsed['answer_basis'],'proposed_work')
        self.assertIsNone(parsed['action'])
        schema=advice.response_definition('Plan sourcing.',[])['parameters']
        self.assertIn('answer_basis',schema['required'])
    def test_result_without_file_format_requires_a_scoped_route(self):
        from task_relay import request_contract as contracts
        contract={'mode':'new_work','reason':'Inspect the supplied photo and source actual products.',
                  'outcomes':[{'id':'sourcing','description':'Every visible furniture and lighting item; three US purchasable options each, unlimited budget, checked pages/prices/dimensions/availability and uncertainty.',
                               'kind':'result','count':1,'format':'','checks':[],
                               'validation':['Check actual product pages and flag uncertain identifications.']}]}
        value=self.reply();value['request_contract']=contract
        with self.assertRaisesRegex(ValueError,'scoped work route'):
            contracts.route(value)
        value['action']={'kind':'plan_production'};value['next_options']=[]
        result=contracts.route(value)
        self.assertEqual(result['action']['deliverables'],contracts.descriptions(contract))
        value['action']['deliverables']={'deck':'An editable presentation'}
        with self.assertRaisesRegex(ValueError,'changed or omitted'):
            contracts.route(value)

    def test_invalid_scope_is_not_inferred_or_accepted(self):
        value=self.reply('verified')
        with self.assertRaisesRegex(advice.AdviceError,'answer basis'):
            advice.validate(json.dumps(value),'Check sources.',[],{'sources':[]})

if __name__=='__main__':unittest.main()
