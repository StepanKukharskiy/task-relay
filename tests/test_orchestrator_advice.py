"""Direct Telegram advice, actual source disclosure and no-dispatch failures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay import orchestrator_advice as advice, orchestrator_chat as chat
from tests import intake_fixtures as intake
from tests import test_orchestrator_chat as fixture
from tests import test_production_planning as stage_fixture

REQUEST = 'What can I do with an old handheld console? Can I turn it into an assistant?'
ADVICE = {'recommended_mode':'none','requirement':'optional',
          'reason':'Start with reuse ideas; documentation can check which interface projects actually work.',
          'questions':['Which existing projects support the console link protocol?', 'What power and interface limits are documented?']}


class DirectTests(unittest.TestCase):
    setUp = fixture.Tests.setUp
    tearDown = fixture.Tests.tearDown
    message = fixture.Tests.message

    def value(self, recommendation=ADVICE):
        return {'answer':'The console could serve as a retro screen and controller for an external assistant. Start with a simple text UI; the bridge needs a documented compatible design.',
                'action':None,'research_advice':copy.deepcopy(recommendation),'next_options':[]}

    def test_actual_generator_saves_advice_and_no_lookup_without_starting_a_plan(self):
        value=self.value();self.message(REQUEST)
        provider_reply={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}]}
        with patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),provider_reply]
            chat.Worker(self.state).tick()
            self.assertEqual(client.return_value.request.call_count,2)
            sent=client.return_value.request.call_args.args[1]
            self.assertIn('research_advice',sent['systemInstruction']['parts'][0]['text'])
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['prompt'],REQUEST)
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(json.loads(row['response'])['research_advice'],ADVICE)
        self.assertNotIn(ADVICE['reason'],row['answer'])
        self.assertNotIn(ADVICE['questions'][0],row['answer'])
        self.assertIn('Sources: not checked yet',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT text FROM outbox').fetchone()[0],'Orchestrator\n'+row['answer'])
        self.assertEqual(self.telegram.sent,[])

    def test_advice_contract_also_applies_to_api_transports(self):
        value=self.value();raw=json.dumps(value)
        for name in ('openai','qwen'):
            response=({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':raw}]}]} if name=='openai'
                      else {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':raw}}]})
            with self.subTest(provider=name), patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value=None), patch.object(chat.api,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.api,'Client') as client:
                client.return_value.request.side_effect=[intake.response(name),response]
                result=chat.generate({'id':'api-'+name,'provider':name,'model':'fixture-model'},{'user_message':REQUEST,'snapshot':{}})
                self.assertEqual(json.loads(result)['research_advice'],ADVICE)
                self.assertEqual(client.return_value.request.call_count,2)

    def test_actual_tool_loop_projects_a_recorded_page_into_the_saved_reply(self):
        self.message('Check the documented controller interface.')
        recommendation={**ADVICE,'recommended_mode':'sources','requirement':'required'}
        value=self.value(recommendation)
        responses=[{'candidates':[{'content':{'parts':[{'functionCall':{'name':'web_fetch','args':{'url':'https://docs.example/spec','offset':0,'limit':1000}}}]}}]},
                   {'candidates':[{'content':{'parts':[{'text':json.dumps(value)}]}}]}]
        with patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client, patch('task_relay.orchestrator_web.download',return_value=('https://docs.example/spec',b'Documented controller interface.','text/plain','utf-8')) as download:
            client.return_value.request.side_effect=[intake.response('gemini')]+responses
            chat.Worker(self.state).tick()
            self.assertEqual(client.return_value.request.call_count,3)
            download.assert_called_once()
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertIn('Sources: 1 page read\nhttps://docs.example/spec',row['answer'])
        self.assertNotIn('No successful web lookup',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)

    def test_missing_advisory_data_preserves_a_direct_answer_without_replay(self):
        self.message(REQUEST);value=self.value();value.pop('research_advice');raw=json.dumps(value)
        with patch.object(chat.gemini,'DATA',Path(self.temp.name)), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),{'candidates':[{'content':{'parts':[{'text':raw}]}}]}]
            worker=chat.Worker(self.state);worker.tick();worker.tick()
            self.assertEqual(client.return_value.request.call_count,2)
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(json.loads(row['response']),{**json.loads(raw),'request_contract':intake.ANSWER})
        self.assertEqual(row['answer'],value['answer'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)

    def test_plain_creative_answers_need_no_research_push_and_legacy_answers_still_parse(self):
        recommendation={'recommended_mode':'none','requirement':'unnecessary','reason':'This poem needs imagination.','questions':[]}
        raw=json.dumps(self.value(recommendation))
        advice.validate(raw,'Write a short poem about an old console.')
        self.assertEqual(advice.render(recommendation,{'sources':[],'partial':False}),'')
        self.assertIsNone(chat.interpret(json.dumps({'answer':'A historical answer.','action':None}),{})['action'])
        invalid=self.value();invalid['action']={'kind':'plan_production'};invalid['research_advice']['requirement']='required'
        with self.assertRaisesRegex(advice.AdviceError,'must agree'):
            advice.validate(json.dumps(invalid),REQUEST)

    def test_exploration_cannot_silently_become_a_full_build_reply(self):
        value=self.value();value['answer']='Follow this step-by-step firmware implementation guide.'
        with self.assertRaisesRegex(advice.AdviceError,'exploratory'):
            advice.validate(json.dumps(value),REQUEST)
        value['answer']='A'*2201
        # Concision is constrained in the runtime-owned response schema; a longer
        # non-executing compatible reply is preserved, rather than replayed.
        advice.validate(json.dumps(value),REQUEST)
        self.assertEqual(advice.response_definition(REQUEST,[])['parameters']['properties']['answer']['maxLength'],2200)
        # An explicit implementation request retains its own scope.
        advice.validate(json.dumps(value),'Write a full implementation guide.')


class SourceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.receipt=self.root/'orchestrator-reads'/(hashlib.sha256(b'1').hexdigest()+'.json')
        self.receipt.parent.mkdir()

    def read(self,name,result):
        return {'call':{'name':name},'result':result,'result_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()}

    def test_disclosure_uses_actual_reads_not_candidate_links_or_failed_calls(self):
        reads=[self.read('web_fetch',{'ok':True,'url':'https://docs.example/spec','text':'Observed spec.'}),
               self.read('web_search',{'ok':True,'sources':[{'url':'https://docs.example/search-only'},{'url':'https://docs.example/spec'}]}),
               self.read('web_fetch',{'ok':False,'url':'https://docs.example/failed'}),
               self.read('context_read',{'ok':True,'url':'https://docs.example/not-a-web-read'})]
        self.receipt.write_text(json.dumps([{'reads':reads,'response':{'answer':'https://docs.example/invented'}}]))
        evidence=advice.disclosure(self.root,1);rendered=advice.render(ADVICE,evidence)
        self.assertEqual(evidence['sources'],[{'url':'https://docs.example/spec','kind':'page'},{'url':'https://docs.example/search-only','kind':'search_result'}])
        self.assertIn('Sources: 1 page read',rendered);self.assertIn('https://docs.example/search-only',rendered)
        self.assertNotIn('invented',rendered);self.assertNotIn('failed',rendered)
        self.assertEqual(advice.disclosure(self.root,2)['sources'],[])
        reads[0]['result']['url']='https://docs.example/changed'
        self.receipt.write_text(json.dumps([{'reads':reads}]))
        self.assertTrue(advice.disclosure(self.root,1)['partial'])
        self.assertNotIn('https://docs.example/changed',advice.render(ADVICE,advice.disclosure(self.root,1)))

    def test_malformed_receipts_and_long_links_are_disclosed_without_breaking_answer(self):
        self.receipt.write_text('bad json')
        self.assertTrue(advice.disclosure(self.root,1)['partial'])
        urls=[{'url':'https://docs.example/'+str(n)+'x'*3000,'kind':'page'} for n in range(15)]
        rendered=advice.render(ADVICE,{'sources':urls,'partial':False})
        self.assertLess(len(rendered),5000)
        self.assertIn('More source details',rendered)


class StageTests(unittest.TestCase):
    setUp = stage_fixture.Tests.setUp
    tearDown = stage_fixture.Tests.tearDown
    request = stage_fixture.Tests.request
    action = stage_fixture.Tests.action
    queue = stage_fixture.Tests.queue
    row = stage_fixture.Tests.row

    def test_telegram_choices_reach_the_same_frozen_stage_contract(self):
        for n,mode in enumerate(('suggest','none','sources'),1):
            row=self.queue(n,self.action(research_mode=mode),REQUEST)
            context=json.loads(row['context'])
            self.assertEqual(row['channel'],'telegram')
            self.assertEqual(context['research_mode'],mode)
            self.assertEqual(context['options']['research_mode'],mode)
            self.assertEqual(context.get('research_advice_version')==1,mode=='suggest')
            self.assertEqual(row['request'],REQUEST)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
