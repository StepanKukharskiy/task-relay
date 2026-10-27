import copy,unittest
from orchestrator.product_evidence import capture,verify,source_pack_journal

class Tests(unittest.TestCase):
    def setUp(self):
        self.text='Previous price $149.99\nPrice $ 99.99\nDiameter\n31 1/2 "\nCheck delivery and in-stock availability\nAdd to bag'
        self.journal={'actions':[{'id':'call-7','result':{'observation':'obs','url':'https://example.test/product','text':self.text}}]}
    def select(self,field,quote):
        start=self.text.index(quote)
        return dict(field=field,observation='obs',start=start,end=start+len(quote))
    def test_price_is_derived_and_contradicted_value_cannot_pass(self):
        value=capture(self.journal,self.select('price','Price $ 99.99'))
        self.assertEqual(value['amount'],'99.99');self.assertEqual(value['action_id'],'call-7')
        value['amount']='159.99'
        with self.assertRaises(ValueError):verify(self.journal,value)
    def test_whitespace_and_identity_are_not_reconstructed(self):
        value=capture(self.journal,self.select('dimensions','Diameter\n31 1/2 "'))
        self.assertEqual(value['value'],'Diameter\n31 1/2 "')
        value['action_id']='browser_read'
        with self.assertRaises(ValueError):verify(self.journal,value)
    def test_authored_values_and_ambiguous_prices_are_rejected(self):
        selected=self.select('price','Price $ 99.99');selected['amount']='159.99'
        with self.assertRaises(ValueError):capture(self.journal,selected)
        with self.assertRaises(ValueError):capture(self.journal,dict(field='price',observation='obs',start=0,end=35))
    def test_duplicate_observations_and_changed_pages_are_rejected(self):
        value=capture(self.journal,self.select('price','Price $ 99.99'))
        changed=copy.deepcopy(self.journal);changed['actions'][0]['result']['text']=self.text.replace('99.99','89.99')
        with self.assertRaises(ValueError):verify(changed,value)
        self.journal['actions'].append(copy.deepcopy(self.journal['actions'][0]))
        with self.assertRaises(ValueError):capture(self.journal,self.select('price','Price $ 99.99'))

    def test_search_summary_is_not_a_fetched_price_source(self):
        pack={'entries':[{'grounding':[{'text':'Invented $159.99'}],'pages':[]}]}
        self.assertEqual(source_pack_journal(pack)['actions'],[])
        pack['entries'][0]['pages']=[{'url':'https://example.test/product','text':'Price $349.99'}]
        j=source_pack_journal(pack)
        value=capture(j,dict(field='price',observation='page-0-0',start=0,end=13))
        self.assertEqual(value['amount'],'349.99')

    def test_jsonld_offer_retains_explicit_currency_and_source_spans(self):
        text='Observed product JSON-LD: {"name":"Chair", "offers":[{"price":"129.95", "priceCurrency":"USD", "availability":"InStock"}]} '
        self.text=text;self.journal['actions'][0]['result']['text']=text
        quote='{"price":"129.95", "priceCurrency":"USD", "availability":"InStock"}'
        result=capture(self.journal,self.select('price',quote))
        self.assertEqual(result['currency'],'USD');self.assertEqual(result['amount'],'129.95')
        verify(self.journal,result)
        from orchestrator.sourcing_contract import source_read
        page=self.journal['actions'][0]['result']
        spans=source_read({'observations':{'obs':page}},dict(observation='obs',offset=0,limit=12000))['price_spans']
        self.assertEqual(spans[0]['text'],quote);self.assertEqual(spans[0]['currency'],'USD')
        with self.assertRaises(ValueError):capture(self.journal,self.select('price','129.95'))

    def test_split_punctuation_uses_one_literal_parser_for_selection_and_capture(self):
        from orchestrator.sourcing_contract import source_read
        for literal,amount in [('$\n69\n.\n99\n','69.99'),('$ 1 , 234 . 50','1234.50'),('$69.9','69.9'),('$349','349')]:
            with self.subTest(literal=literal):
                self.text='Observed price '+literal+'\nAvailability unknown'
                page=self.journal['actions'][0]['result'];page['text']=self.text
                value=capture(self.journal,self.select('price',literal))
                self.assertEqual(value['amount'],amount);self.assertEqual(value['excerpt'],literal)
                spans=source_read({'observations':{'obs':page}},dict(observation='obs',offset=0,limit=12000))['price_spans']
                self.assertEqual(len(spans),1)
                selection=dict(field='price',observation='obs',**{k:spans[0][k] for k in ('start','end')})
                self.assertEqual(capture(self.journal,selection)['amount'],amount)
                self.assertEqual(self.text[spans[0]['start']:spans[0]['end']],spans[0]['text'])
                short=source_read({'observations':{'obs':page}},dict(observation='obs',offset=0,limit=spans[0]['end']-1))
                self.assertEqual(short['price_spans'],[])

    def test_prefixes_ambiguous_digits_ranges_and_locales_cannot_become_prices(self):
        from orchestrator.product_evidence import displayed_prices
        for literal in ('$69.999','$69,99','$1.234,56','$1234,567','$69–99','$69\n99','$69.9 9','$1e3'):
            with self.subTest(literal=literal):
                self.text='Price '+literal+'\nUnknown';self.journal['actions'][0]['result']['text']=self.text
                self.assertEqual(displayed_prices(self.text),[])
                with self.assertRaises(ValueError):capture(self.journal,self.select('price',literal))
        for literal,prefix in [('$69.99','$69'),('$\n69\n.\n99','$\n69'),('$1,299','$1'),('$120','$12')]:
            self.text=literal;self.journal['actions'][0]['result']['text']=literal
            with self.assertRaises(ValueError):capture(self.journal,self.select('price',prefix))

    def test_structured_and_displayed_numbers_must_agree(self):
        for display,passes in [('$69.99',True),('$69',False)]:
            self.text='{"name":"Price '+display+'", "price":"69.99", "priceCurrency":"USD"}'
            self.journal['actions'][0]['result']['text']=self.text
            if passes:
                value=capture(self.journal,self.select('price',self.text));self.assertEqual(value['amount'],'69.99');self.assertEqual(value['currency'],'USD')
            else:
                with self.assertRaisesRegex(ValueError,'disagree'):capture(self.journal,self.select('price',self.text))
