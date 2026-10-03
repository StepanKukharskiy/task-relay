"""Small controlled requests through both entry points and saved reply inspection."""
import copy
import hashlib
import json
import uuid
import unittest
from tests import intake_fixtures as intake
from unittest.mock import patch

from tests import test_desktop_plans as desktop_fixture
from tests.test_bridge import TelegramFake
from task_relay.bridge import Bridge
from task_relay import desktop_plans, desktop_workspace, orchestrator_chat as chat, orchestrator_advice, relay_channels

REQUEST = 'What useful projects could I make with an old controller?'
CATALOG = {'operations':[{'id':'web_fetch','executor':'relay.web','available':True}],
           'graph_executors':[{'id':'codex-cli','available':True,'tools':['files','shell']},
                              {'id':'disconnected-worker','available':False}],
           'graph_operations':[{'id':'unavailable.image','available':False}]}
OPTIONS = [dict(title='Check compatible projects',outcome='A short comparison of existing designs with documentation and gaps.',
                tools=['operations:web_fetch'],request='Check existing controller interface projects against their primary documentation.'),
           dict(title='Prepare a software prototype',outcome='An interactive desktop UI to explore input and text display before hardware work.',
                tools=['graph_executors:codex-cli'],request='Prepare a plan for a local text UI prototype; no hardware modification or external deployment.')]
REPLY = dict(answer='A small controller could provide a fun interface for an external assistant. The hardware bridge needs checking.',action=None,
             research_advice=dict(recommended_mode='none',requirement='optional',reason='Explore the UI first or check supported interface projects.',
                                  questions=['Which documented projects support this interface?']),next_options=OPTIONS)


class SharedTests(unittest.TestCase):
    # Reuse fixture setup without inheriting the unrelated stage cases.
    def setUp(self):
        desktop_fixture.DesktopPlansTests.setUp(self)
        with self.state.db:
            health=self.state.get('health:desktop-plans');health['orchestrator_entry_version']=1
            self.state.put('health:desktop-plans',health)

    def test_old_service_readiness_cannot_route_a_new_conversation_as_a_plan(self):
        with self.state.db:
            health=self.state.get('health:desktop-plans');health.pop('orchestrator_entry_version')
            self.state.put('health:desktop-plans',health)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'Restart Relay'):
            self.create_conversation()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],0)
    def create_conversation(self, ident=None, **kwargs):
        return desktop_plans.create(REQUEST,'',None,None,ident or str(uuid.uuid4()),self.paths,
                                    entry_mode='conversation',**kwargs)

    def test_admission_retry_frozen_files_and_entry_scope_are_atomic(self):
        attachment=self.paths.data/'input.txt';attachment.write_text('Exact initial attachment.')
        ident=str(uuid.uuid4());self.create_conversation(ident,files=[str(attachment)])
        initial=self.state.db.execute('SELECT manifest FROM desktop_plan_inputs').fetchone()[0]
        attachment.write_text('Later changed original.')
        self.create_conversation(ident,files=[str(attachment)])
        self.assertEqual(self.state.db.execute('SELECT manifest FROM desktop_plan_inputs').fetchone()[0],initial)
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'entry mode'):
            desktop_plans.create(REQUEST,'',None,None,ident,self.paths,files=[str(attachment)])
        with patch.object(chat,'provider',return_value=('gemini','fixture')):
            desktop_plans.process_requests(self.state);desktop_plans.process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        job=dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone())
        payload=chat.conversation_context(relay_channels.ScopedState(self.state,'desktop'),job,{'capabilities':CATALOG})
        self.assertEqual(payload['user_message'],REQUEST)
        self.assertEqual(json.dumps(payload['entry_context']['attachments']),initial)
        self.assertEqual(relay_channels.request_channel(self.state,job['id']),'desktop')

    def test_both_entries_use_one_generator_and_desktop_shows_exact_telegram_answer(self):
        desktop=self.create_conversation();telegram=TelegramFake()
        with self.state.db:
            self.state.put('user_id',7);self.state.put('chat_id',7)
        bridge=Bridge(self.state,telegram,{})
        snapshot=lambda *_:dict(capabilities=copy.deepcopy(CATALOG),production_runs=[],codex_tasks=[],uploaded_files=[])
        with patch.object(chat,'provider',return_value=('gemini','fixture')):
            desktop_plans.process_requests(self.state)
            bridge.process({'update_id':1,'message':{'text':REQUEST,'chat':{'id':7,'type':'private'},'from':{'id':7}}})
        raw=json.dumps(REPLY)
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':raw}]}}]}
        with patch.object(chat,'snapshot',side_effect=snapshot), patch.object(chat.gemini,'DATA',self.paths.data), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response("gemini"),response,intake.response("gemini"),response]
            worker=chat.Worker(self.state);worker.tick();worker.tick()
            self.assertEqual(client.return_value.request.call_count,4)
            for call in client.return_value.request.call_args_list:
                sent=call.args[1];payload=json.loads(sent['contents'][0]['parts'][0]['text'])
                self.assertEqual(payload['user_message'],REQUEST)
                self.assertEqual(payload['option_tools'],orchestrator_advice.option_tools({'snapshot':{'capabilities':CATALOG}}))
        rows=self.state.db.execute('SELECT * FROM orchestrator_chats ORDER BY created').fetchall()
        self.assertEqual([r['status'] for r in rows],['answered','answered'],[r['answer'] for r in rows])
        self.assertEqual(rows[0]['response'],rows[1]['response'])
        self.assertEqual(rows[0]['answer'],rows[1]['answer'])
        view=desktop_workspace.request_detail(desktop['request_id'],self.paths)['conversation']
        self.assertEqual(view['answer'],rows[0]['answer']);self.assertEqual(view['next_options'],OPTIONS)
        self.assertEqual(view['id'],str(rows[0]['id']))
        remote=desktop_workspace.chat_detail('1',self.paths)
        self.assertEqual(remote['answer'],rows[1]['answer']);self.assertFalse(remote['can_continue'])
        channels={r['id']:relay_channels.event_channel(self.state,r['id']) for r in self.state.db.execute('SELECT * FROM outbox')}
        self.assertEqual(channels['orchestrator:'+str(rows[0]['id'])],'desktop')
        self.assertEqual(channels['orchestrator:1'],'telegram')
        self.assertEqual([r['id'] for r in relay_channels.pending(self.state,'telegram')],['orchestrator:1'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)
        self.assertEqual(telegram.sent,[])
        jobs=desktop_workspace.jobs(paths=self.paths)['items']
        self.assertEqual({r['kind'] for r in jobs},{'request','chat'})

    def test_search_only_verification_preserves_reply_without_retry_or_dispatch(self):
        self.create_conversation()
        with patch.object(chat,'provider',return_value=('gemini','fixture')):
            desktop_plans.process_requests(self.state)
        value=copy.deepcopy(REPLY);value['answer']='Here are the verified hardware pinouts.'
        value['research_advice'].update(recommended_mode='sources',requirement='required')
        raw=json.dumps(value)
        searched={'ok':True,'sources':[{'url':'https://docs.example/search-only','title':'Interface project'}],'summary':'Search synthesis.'}
        responses=[{'candidates':[{'content':{'parts':[{'functionCall':{'name':'web_search','args':{'query':'controller documentation'}}}]}}]},
                   {'candidates':[{'content':{'parts':[{'text':raw}]}}]}]
        with patch.object(chat,'snapshot',return_value={'capabilities':CATALOG}), patch.object(chat.gemini,'DATA',self.paths.data), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client, patch('task_relay.orchestrator_web.Session.execute',return_value=searched):
            client.return_value.request.side_effect=[intake.response("gemini"),*responses]
            worker=chat.Worker(self.state);worker.tick();worker.tick()
            self.assertEqual(client.return_value.request.call_count,3,'No provider replay after the search and rejected answer.')
        row=self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['status'],'failed');self.assertEqual(json.loads(row['response']),{**value,'request_contract':intake.ANSWER})
        self.assertIn('without recorded page reads',row['answer'])
        self.assertIn('no automatic retry',row['answer'])
        self.assertEqual(orchestrator_advice.disclosure(self.paths.data,row['id'])['sources'][0]['kind'],'search_result')
        self.assertEqual(desktop_workspace.request_detail(self.state.db.execute('SELECT request_id FROM desktop_plan_requests').fetchone()[0],self.paths)['conversation']['next_options'],[])

    def test_options_reject_unavailable_routes_and_manual_none_removes_web_tools(self):
        offered=orchestrator_advice.option_tools({'snapshot':{'capabilities':CATALOG}})
        with self.assertRaisesRegex(orchestrator_advice.AdviceError,'explicit source-backed'):
            orchestrator_advice.validate(json.dumps(REPLY),REQUEST,offered,{'sources':[]},research_mode='sources')
        self.assertEqual(orchestrator_advice.options(OPTIONS,offered),OPTIONS)
        bad=copy.deepcopy(OPTIONS);bad[0]['tools']=['graph_executors:disconnected-worker']
        with self.assertRaisesRegex(ValueError,'unavailable'):
            orchestrator_advice.options(bad,offered)
        payload={'user_message':REQUEST,'snapshot':{'capabilities':CATALOG},'entry_context':{'research_mode':'none'}}
        value=copy.deepcopy(REPLY);value['next_options']=[OPTIONS[1]]
        with patch.object(chat.gemini,'DATA',self.paths.data), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.side_effect=[intake.response('gemini'),{'candidates':[{'content':{'parts':[{'text':json.dumps(value)}]}}]}]
            chat.generate({'id':'no-web','provider':'gemini','model':'fixture'},payload)
            definitions=client.return_value.request.call_args.args[1]['tools'][0]['functionDeclarations']
            self.assertFalse(any(d['name'].startswith('web_') for d in definitions))

    def test_desktop_source_open_rechecks_the_exact_request_read_receipt(self):
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,created,status,response,answer) VALUES (1,?,'gemini','fixture',1,'answered',?,?)",(REQUEST,json.dumps(REPLY),'Exact saved answer.'))
        stem=hashlib.sha256(b'1').hexdigest();receipt=self.paths.data/'orchestrator-reads'/(stem+'.json');receipt.parent.mkdir()
        result={'ok':True,'url':'https://docs.example/spec','text':'Documented interface.'}
        read={'call':{'name':'web_fetch'},'result':result,'result_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()}
        receipt.write_text(json.dumps([{'reads':[read]}]))
        self.assertEqual(desktop_workspace.chat_source('1',result['url'],self.paths),{'url':result['url']})
        read['result']['text']='Changed receipt';receipt.write_text(json.dumps([{'reads':[read]}]))
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'receipt'):
            desktop_workspace.chat_source('1',result['url'],self.paths)
        view=desktop_workspace.chat_detail('1',self.paths)
        self.assertEqual(view['answer'],'Exact saved answer.');self.assertTrue(view['evidence']['partial'])
