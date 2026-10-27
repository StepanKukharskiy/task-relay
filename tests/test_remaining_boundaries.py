"""Literal evidence, bounded archive continuation and coverage-first ordering."""
import copy,json,tempfile,unittest
from pathlib import Path
from orchestrator import working_context as ctx,product_evidence as prices,web_sources,collection_core
from tests import test_owner_context_retention as shapes

class Prices(unittest.TestCase):
    def test_literal_currency_offsets_round_trip_without_conversion(self):
        from orchestrator.sourcing_contract import source_read
        for literal,amount,currency in [('€394,95','394.95','EUR'),('€1.234,56','1234.56','EUR'),('€1,234.56','1234.56','EUR'),('£1,234.50','1234.50','GBP')]:
            with self.subTest(literal=literal):
                text='Small variant\n'+literal+'\nDelivery unknown'
                page=dict(observation='obs',url='https://example.test/item',text=text)
                journal=dict(actions=[dict(id='saved',result=page)])
                span=source_read(dict(observations={'obs':page}),dict(observation='obs',offset=0,limit=12000))['price_spans'][0]
                record=prices.capture(journal,dict(field='price',observation='obs',start=span['start'],end=span['end']))
                self.assertEqual((record['amount'],record['currency'],record['excerpt']),(amount,currency,literal))
                self.assertEqual(prices.verify(journal,record),record)
                with self.assertRaises(ValueError):prices.capture(journal,dict(field='price',observation='obs',start=span['start'],end=span['end']-1))
    def test_malformed_ranges_ambiguity_and_foreign_currency_fail_closed(self):
        for literal in ('€1234,567','€1.2345','€394,95,99','£69,99','€69–99','€69 99','€1e3'):
            with self.subTest(literal=literal):self.assertEqual(prices.displayed_prices(literal),[])
        for literal in ('€99 £99','{"name":"€99", "price":"99", "priceCurrency":"USD"}'):
            journal=dict(actions=[dict(id='saved',result=dict(observation='obs',url='https://example.test',text=literal))])
            with self.assertRaises(ValueError):prices.capture(journal,dict(field='price',observation='obs',start=0,end=len(literal)))

class Pages(unittest.TestCase):
    group=shapes.ContextTests.group
    def test_escaped_history_fits_all_transports_exact_continuation_and_restart(self):
        for provider in ('gemini','openai','openrouter','codex'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as root:
                view=ctx.WorkingView(Path(root),semantic=True);value={'evidence':'"\\ Ω '*6000};ident=view.save(value)
                initial=dict(role='user',**({'parts':[dict(text='scope '*19300)]} if provider=='gemini' else {'content':'scope '*19300}))
                raw=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'));offset=0;read=[]
                while offset is not None:
                    page=view.read(dict(context=ident,offset=offset));chunk=self.group(provider,'job_history',dict(context=ident,offset=offset),page,1);before=copy.deepcopy(chunk)
                    projected=view.project([initial]+chunk,provider,version=2)
                    result=ctx.exchanges(projected[1:])[1][0];result=json.loads(result) if isinstance(result,str) else result
                    self.assertLessEqual(ctx.size(projected),128000);self.assertEqual(chunk,before)
                    self.assertEqual(result['text'],raw[offset:offset+len(result['text'])]);self.assertTrue(result['text'])
                    self.assertLess(len(result['text']),8000)
                    read.append(result['text']);offset=result['next_offset'];view=ctx.WorkingView(Path(root),semantic=True)
                self.assertEqual(''.join(read),raw)
    def test_history_forgery_effects_pending_read_and_required_state_still_stop(self):
        with tempfile.TemporaryDirectory() as root:
            view=ctx.WorkingView(Path(root));ident=view.save('"\\'*9000);args=dict(context=ident,offset=0);page=view.read(args)
            initial=dict(role='user',content='x'*117000)
            bad={**page,'text':'bad'*9000}
            for name,value,available in [('job_history',bad,True),('job_delegate',page,True),('job_history',page,False)]:
                with self.subTest(name=name,available=available),self.assertRaisesRegex(ValueError,'capacity'):
                    view.project([initial]+self.group('codex',name,args,value,1),'codex',version=2,history_available=available)
            chunk=self.group('codex','job_history',args,page,1)
            with self.assertRaisesRegex(ValueError,'capacity'):view.project([dict(role='user',content='x'*128000)]+chunk,'codex',version=2)
            (view.folder/(ident+'.json')).write_text('{}')
            with self.assertRaisesRegex(ValueError,'capacity'):view.project([initial]+chunk,'codex',version=2)

class Coverage(unittest.TestCase):
    def test_initial_round_robin_and_zero_coverage_before_deepening(self):
        subjects=[dict(id=k,queries=[k+' US exact variant '+str(n) for n in range(3)],required_options=3) for k in ('A','B','C')]
        before=copy.deepcopy(subjects)
        self.assertEqual(web_sources.validate_prepared(dict(version=1,targets=subjects)),[s['queries'][n] for n in range(3) for s in subjects])
        states=[dict(item=k,supported_options=n,shortfall=3-n) for k,n in [('A',2),('B',0),('C',1)]]
        selected=collection_core.fallback_queries(subjects,states,[],suffix=' dimensions',maximum=2)
        self.assertEqual([s['id'] for s in selected],['B','C']);self.assertEqual(subjects,before)
        self.assertTrue(all('US exact variant' in s['queries'][0] for s in selected))
        self.assertEqual([s['required_options'] for s in selected],[3,3])
    def test_duplicate_queries_preserve_mapping_and_capacity_is_not_expanded(self):
        targets=[dict(id=k,queries=['Shared US query',k+' exact'],required_options=3) for k in ('A','B')]
        self.assertEqual(web_sources.validate_prepared(dict(version=1,targets=targets)),['Shared US query','A exact','B exact'])
        targets[0]['queries']=['A '+str(n) for n in range(20)]
        with self.assertRaisesRegex(ValueError,'1–20'):web_sources.validate_prepared(dict(version=1,targets=targets))

from tests import lifecycle_fixture as life
from tests import test_operation_session as model_fixture
from tests.test_owner_intents import worker
from unittest.mock import patch
from orchestrator import job_owner

class OwnerContinuation(life.Lifecycle,unittest.TestCase):
    def test_tight_history_page_then_actual_delegation_correction_restart_and_partial(self):
        original=job_owner.Session._call;request=model_fixture.Script.request;brief=ctx.owner_brief;seen=[];pages=[]
        def large(session,name,args):
            result=original(session,name,args)
            if name=='job_catalog':result={**result,'large_saved_catalog':'"\\ Ω '*30000};seen.append(result)
            return result
        def padded(frozen):return {**brief(frozen),'offline_fixture_required_state':'x'*108000}
        def scripted(script,endpoint,payload,**kwargs):
            response=payload['contents'][-1].get('parts',[{}])[0].get('functionResponse',{})
            value=response.get('response',{})
            if value.get('representation')=='relay.tool-result-pages.v1':
                script.requests.append(copy.deepcopy(payload));field=next(f for f in value['fields'] if f['field']=='large_saved_catalog')
                return dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(functionCall=dict(name='job_history',args=dict(context=value['context'],offset=field['offset'])))]))])
            if response.get('name')=='job_history':pages.append(value)
            return request(script,endpoint,payload,**kwargs)
        with patch.object(job_owner.Session,'_call',large),patch.object(model_fixture.Script,'request',scripted),patch.object(ctx,'owner_brief',padded):
            result,script=self.invoke([('job_catalog',{}),('job_delegate',dict(request_id='initial',tasks=self.pair('v1',[{'artifact':self.evidence['artifact']},{'artifact':self.other['artifact']}])) )])
        self.assertEqual(result['outcome'],'yielded');self.assertEqual(len(seen),1);self.assertEqual(len(pages),1)
        self.assertGreater(len(pages[0]['text']),0);self.assertLess(len(pages[0]['text']),8000)
        self.assertEqual(pages[0]['next_offset'],pages[0]['offset']+len(pages[0]['text']))
        self.rt.tick('job');self.work('v1','Price: 99. No gap disclosed.',collect=False)
        final=self.corrected(resume=True)
        self.delegate('uncertain',[worker('unknown')]);aid=self.rt.task('job','unknown')['latest']
        self.factory.sessions[aid]['status']=dict(status='uncertain',reason='Controlled absent receipt');self.rt.tick('job')
        self.export_partial(final);self.invariants()
