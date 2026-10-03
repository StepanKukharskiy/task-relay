"""Selected outcomes, durable lineage and bounded research; small fake providers."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from task_relay import conversation_flow as flow, desktop_plans, desktop_workspace, orchestrator_chat as chat
from tests import test_shared_orchestrator as fixture


class FlowTests(unittest.TestCase):
    setUp=fixture.SharedTests.setUp
    create_conversation=fixture.SharedTests.create_conversation

    def root(self,files=None):
        self.create_conversation(files=files or [])
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        with patch.object(chat,'snapshot',return_value={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}),patch.object(chat.gemini,'DATA',self.paths.data):
            chat.Worker(self.state,generator=lambda *_:json.dumps(fixture.REPLY)).tick()
        self.ident=str(self.state.db.execute('SELECT id FROM orchestrator_chats').fetchone()[0])
        return desktop_workspace.chat_detail(self.ident,self.paths)

    def choose(self,view,index=0,identity=None):
        return flow.choose(view['id'],index,view['option_digests'][index],identity or str(uuid.uuid4()),self.paths)

    def test_public_read_choice_queues_once_in_root_without_plan_or_execution(self):
        original=self.paths.data/'input.txt';original.write_text('Original frozen bytes.')
        view=self.root([str(original)]);original.write_text('Later original bytes.')
        key=str(uuid.uuid4());receipt=self.choose(view,identity=key)
        self.assertEqual(receipt['mode'],'research');self.assertEqual(receipt['root_id'],self.ident)
        known=self.choose(view,identity=str(uuid.uuid4()));self.assertEqual(known['request_id'],key)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        jobs=desktop_workspace.jobs(paths=self.paths)
        self.assertEqual(jobs['total'],1);self.assertEqual(jobs['items'][0]['status'],'queued')
        self.assertTrue(jobs['items'][0]['conversation_flow'])
        child=self.state.db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?',(key,)).fetchone()
        self.assertTrue(child['prompt'].startswith(fixture.OPTIONS[0]['request']))
        inputs=json.loads(self.state.db.execute('SELECT manifest FROM desktop_plan_inputs WHERE request_id=?',(key,)).fetchone()[0])
        self.assertEqual(Path(inputs[0]['path']).read_text(),'Original frozen bytes.')
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        child=self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(child['job_id'],)).fetchone()
        from task_relay.relay_channels import ScopedState
        context=chat.conversation_context(ScopedState(self.state,'desktop'),child,{'capabilities':fixture.CATALOG})
        self.assertEqual(context['entry_context']['research_mode'],'sources')
        self.assertEqual(context['entry_context']['followup']['mode'],'research')

    def test_stale_choice_and_database_failure_preserve_root_and_queue_nothing(self):
        view=self.root();before=dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone())
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError,'changed'):
            flow.choose(self.ident,0,'0'*64,str(uuid.uuid4()),self.paths)
        with self.state.db:
            self.state.db.execute("CREATE TRIGGER reject_link BEFORE INSERT ON conversation_followups BEGIN SELECT RAISE(ABORT,'Controlled lineage failure'); END")
        with self.assertRaises(Exception):self.choose(view)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM conversation_followups').fetchone()[0],0)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()),before)

    def test_research_cannot_dispatch_a_model_action_or_retry_a_provider(self):
        view=self.root();receipt=self.choose(view)
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        value=copy.deepcopy(fixture.REPLY);value['next_options']=[];value['action']={'kind':'plan_production','template':'custom'}
        generator=unittest.mock.Mock(return_value=json.dumps(value))
        with patch.object(chat,'snapshot',return_value={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}),patch.object(chat.gemini,'DATA',self.paths.data):
            chat.Worker(self.state,generator=generator).tick()
        generator.assert_called_once()
        child=self.state.db.execute('SELECT c.* FROM orchestrator_chats c JOIN desktop_plan_requests d ON d.job_id=c.id WHERE d.request_id=?',(receipt['request_id'],)).fetchone()
        self.assertEqual(child['status'],'failed');self.assertEqual(child['response'],json.dumps(value))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_research_result_read_steps_and_more_choices_keep_original_root(self):
        view=self.root();receipt=self.choose(view)
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        with patch.object(chat,'snapshot',return_value={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}),patch.object(chat.gemini,'DATA',self.paths.data):
            chat.Worker(self.state,generator=lambda *_:json.dumps(fixture.REPLY)).tick()
        child=self.state.db.execute('SELECT job_id FROM desktop_plan_requests WHERE request_id=?',(receipt['request_id'],)).fetchone()[0]
        result={'ok':True,'url':'https://docs.example/read','text':'Source text.'}
        path=self.paths.data/'orchestrator-reads'/(hashlib.sha256(str(child).encode()).hexdigest()+'.json');path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps([{'reads':[{'call':{'name':'web_fetch','arguments':json.dumps({'url':'https://docs.example/read'})},'result':result,'read_at':1,'result_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()}]}]))
        projected=desktop_workspace.chat_detail(self.ident,self.paths)
        self.assertEqual(len(projected['flow']['tasks']),3)
        self.assertEqual(projected['flow']['tasks'][1]['status'],'completed')
        self.assertEqual(projected['flow']['stages'][0]['conversation']['answer'],self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=?',(child,)).fetchone()[0])
        child_view=projected['flow']['stages'][0]['conversation'];another=self.choose(child_view)
        self.assertEqual(another['root_id'],self.ident)
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['total'],1)
        self.assertEqual(len(desktop_workspace.chat_detail(self.ident,self.paths)['flow']['stages']),2)
        result['text']='Changed result.';record=json.loads(path.read_text());record[0]['reads'][0]['result']=result;path.write_text(json.dumps(record))
        self.assertEqual(flow.read_steps(self.paths,child),[])

    def test_non_read_recommendation_queues_attached_plan_not_executing_worker(self):
        view=self.root();result=self.choose(view,1)
        self.assertEqual(result['mode'],'plan')
        mode=self.state.db.execute('SELECT entry_mode FROM desktop_request_modes WHERE request_id=?',(result['request_id'],)).fetchone()[0]
        self.assertEqual(mode,'plan');self.assertEqual(desktop_workspace.jobs(paths=self.paths)['total'],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_native_research_reads_and_final_answer_keep_the_nonexecuting_contract(self):
        view=self.root();receipt=self.choose(view)
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        from task_relay import orchestrator_web as web
        from tests.test_response_data import response,DATA
        data=copy.deepcopy(DATA);data['research_advice']['recommended_mode']='sources';data['research_advice']['requirement']='required';data['answer']='A documented interface is described in [the primary page](https://docs.example/read).'
        first={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':'web_fetch','args':{'url':'https://docs.example/read','offset':0,'limit':1000}}}]}}]}
        with patch.object(chat,'snapshot',return_value={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}),patch.object(chat.gemini,'DATA',self.paths.data),patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}),patch.object(chat.gemini,'Client') as client,patch.object(web,'download',return_value=('https://docs.example/read',b'<title>Interface</title><p>Primary interface documentation.</p>','text/html','utf-8')):
            client.return_value.request.side_effect=[first,response('gemini',data)]
            chat.Worker(self.state).tick()
            self.assertEqual(client.return_value.request.call_count,2)
            definition=client.return_value.request.call_args_list[0].args[1]['tools'][0]['functionDeclarations'][-1]
            self.assertEqual(definition['parametersJsonSchema']['properties']['action_json']['type'],'null')
        projected=desktop_workspace.chat_detail(self.ident,self.paths)
        stage=projected['flow']['stages'][0]
        self.assertEqual(stage['conversation']['status'],'answered',[dict(r) for r in self.state.db.execute('SELECT * FROM orchestrator_chat_errors')])
        self.assertEqual(stage['conversation']['source_summary']['pages'],1)
        self.assertEqual(len(projected['flow']['tasks']),3)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)

    def test_explicit_historical_attachment_preserves_failure_and_new_choice_starts_research(self):
        view=self.root();request_id=str(uuid.uuid4())
        desktop_plans.create(fixture.OPTIONS[0]['request'],'Original request:\n'+view['prompt'],None,None,request_id,self.paths)
        child=self.state.db.execute('SELECT job_id FROM desktop_plan_requests WHERE request_id=?',(request_id,)).fetchone()[0]
        values={'id':'plan-'+str(child),'request_id':child,'parent_id':None,'channel':'desktop','request':fixture.OPTIONS[0]['request'],
                'options':json.dumps({'planning_only':True}),'context':json.dumps({'research_mode':'sources'}),'context_hash':'fixture',
                'provider':'gemini','model':'fixture','status':'blocked','calls':2,'result':None,'plan':None,'plan_hash':None,
                'token':'fixture','event_id':None,'expires':9999999999,'run':None,'error':'Invalid registered-operation parameters.','created':1}
        with self.state.db:
            self.state.db.execute("UPDATE desktop_plan_requests SET status='accepted' WHERE request_id=?",(request_id,))
            self.state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
        before=dict(self.state.db.execute('SELECT * FROM production_plans').fetchone())
        link=flow.attach_saved(view['id'],0,view['option_digests'][0],request_id,self.paths)
        self.assertEqual(link['scope'],'display lineage only; no acceptance or execution')
        self.assertEqual(flow.attach_saved(view['id'],0,view['option_digests'][0],request_id,self.paths),link)
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['total'],1)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans').fetchone()),before)
        receipt=self.choose(view);self.assertNotEqual(receipt['request_id'],request_id)
        self.assertEqual(receipt['mode'],'research')
        self.assertEqual(desktop_workspace.jobs(paths=self.paths)['items'][0]['status'],'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_changed_frozen_attachment_during_capture_rolls_back_the_followup(self):
        attachment=self.paths.data/'input.txt';attachment.write_text('Frozen fixture.')
        view=self.root([str(attachment)])
        from task_relay import routing_inputs
        capture=routing_inputs.capture
        def changed(*args,**kwargs):
            Path(view['files'][0]).chmod(0o600);Path(view['files'][0]).write_text('Changed during capture.')
            return capture(*args,**kwargs)
        with patch.object(routing_inputs,'capture',side_effect=changed),self.assertRaisesRegex(desktop_plans.DesktopPlanError,'during capture'):
            self.choose(view)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM conversation_followups').fetchone()[0],0)

    def test_malformed_rejected_proposal_cannot_break_saved_job_inspection(self):
        self.assertEqual(flow.proposed_tasks({'plan':['invalid']}),[])
        tasks=flow.proposed_tasks({'plan':{'tasks':[{'id':'step','instruction':None,'dependencies':None,'after':'step','input_bindings':None}]}})
        self.assertEqual(tasks[0]['dependencies'],[])
        self.assertIn('no assignment was executed',tasks[0]['instruction'])

    def test_truncated_historical_catalog_keeps_only_proven_offered_tools(self):
        view=self.root()
        with self.state.db:
            saved=json.loads(self.state.db.execute('SELECT snapshot FROM orchestrator_chats WHERE id=?',(int(self.ident),)).fetchone()[0])
            self.assertIn('operations:web_fetch',saved.pop('option_tool_ids'))
            saved['capabilities']['operations']=[]
            saved['current_execution_availability']={'executors':[{'id':'codex-cli','available':True}]}
            saved['capabilities']['web']={'web_search':'Gemini/Google Search; configured'}
            response=copy.deepcopy(fixture.REPLY);response['next_options'][0]['tools']=['operations:web_search']
            self.state.db.execute('UPDATE orchestrator_chats SET snapshot=?,response=? WHERE id=?',
                (json.dumps(saved),json.dumps(response),int(self.ident)))
        historical=desktop_workspace.chat_detail(self.ident,self.paths)
        self.assertEqual(len(historical['option_digests']),2)
        self.assertEqual(self.choose(historical)['mode'],'research')
        with self.state.db:
            response['next_options'][0]['tools']=['operations:unknown']
            self.state.db.execute('UPDATE orchestrator_chats SET response=? WHERE id=?',(json.dumps(response),int(self.ident)))
        self.assertEqual(desktop_workspace.chat_detail(self.ident,self.paths)['option_digests'],[])
