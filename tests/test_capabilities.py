import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from task_relay.bridge import State, Bridge
from tests.test_bridge import TelegramFake
from task_relay import capabilities as caps
from task_relay import orchestrator_chat as chat
from task_relay import backends


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.state=State(self.root/'state.sqlite')
        self.patches=[patch.object(backends,'CLAUDE_PYTHON',Path(__file__)),
                      patch.object(backends,'claude_config',return_value={'auth':'account'}),
                      patch('task_relay.api_providers.read_config',return_value={'api_key':'DO-NOT-EXPOSE'}),
                      patch('task_relay.gemini.read_config',return_value=None),
                      patch('task_relay.bridge.local_tasks',return_value=[])]
        for p in self.patches:p.start()
        with self.state.db:
            self.state.put('orchestrator_routing_enabled',True)
            self.state.put('chat_id',7);self.state.put('user_id',7)
            for provider in ('claude','openai','gemini'):
                tid=provider+':research'
                self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',(tid,'',0,provider+' research','idle',1))
                self.state.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,0)',(tid,provider,'session',str(self.root),'test-model'))
        self.job={'id':71,'prompt':'Use Claude to research agents online. Cite sources.\nDo not edit the script.','focus':None}
        self.action={'kind':'delegate_task','task_id':'claude:research','provider':'claude','required_capabilities':['web_search','web_fetch']}

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.state.db.close();self.temp.cleanup()

    def snapshot(self):
        return chat.snapshot(self.state,None)

    def dispatch(self,action=None,snap=None):
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            return caps.dispatch(self.state,self.job,action or self.action,snap or self.snapshot())

    def test_catalog_reports_real_provider_differences_without_credentials(self):
        data=self.snapshot()['capabilities'];targets={t['provider']:t for t in data['targets']}
        self.assertIn('web_search',targets['claude']['capabilities'])
        self.assertNotIn('shell',targets['openai']['capabilities'])
        self.assertFalse(targets['gemini']['available'])
        self.assertIn('web_search',data['direct_unavailable'])
        self.assertNotIn('DO-NOT-EXPOSE',json.dumps(data))
        with self.state.db:self.state.put('orchestrator_routing_enabled',False)
        self.assertEqual(self.snapshot()['capabilities']['targets'],[])

    def test_claude_dispatch_is_exact_atomic_idempotent_and_reports_native_status(self):
        snap=self.snapshot();text,tid=self.dispatch(snap=snap)
        self.assertEqual(tid,'claude:research');self.assertIn('Queued',text)
        job=self.state.db.execute('SELECT * FROM backend_jobs').fetchone()
        self.assertEqual(job['prompt'],self.job['prompt']);self.assertEqual(job['status'],'queued')
        self.assertEqual(self.dispatch(snap=snap),(text,tid))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],1)
        with self.state.db:
            self.state.db.execute("UPDATE backend_jobs SET status='uncertain'")
            self.state.db.execute("UPDATE watched SET status='uncertain' WHERE id=?",(tid,))
        self.assertEqual(self.snapshot()['capabilities']['dispatches'][0]['status'],'uncertain')
        self.assertEqual(self.dispatch(snap=snap),(text,tid))
        with self.assertRaisesRegex(ValueError,'different action'):
            self.dispatch({**self.action,'required_capabilities':['shell']},snap)

    def test_incompatible_provider_and_unavailable_tools_do_not_queue(self):
        snap=self.snapshot()
        for action in ({**self.action,'provider':'codex'},
                       {**self.action,'task_id':'openai:research','provider':'openai'},
                       {**self.action,'required_capabilities':['invented_tool']},
                       {**self.action,'prompt':'rewritten user request'}):
            with self.assertRaises(ValueError):self.dispatch(action,snap)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)

    def test_api_dispatch_retains_native_read_only_tool_schema(self):
        self.job['prompt']='Use OpenAI to read README.md and summarize it.'
        action={**self.action,'task_id':'openai:research','provider':'openai','required_capabilities':['file_read']}
        self.dispatch(action)
        run=self.state.db.execute('SELECT * FROM api_runs').fetchone()
        request=json.loads(run['request_json'])
        self.assertEqual({t['name'] for t in request['tools']},set(caps.READ))
        self.assertEqual(request['input'][-1]['content'],self.job['prompt'])
        self.assertEqual(run['workspace'],str(self.root))

    def test_approved_guides_reach_native_claude_and_api_prompts(self):
        from task_relay import routing_inputs
        source=self.root/'card-guide.md';source.write_text('Use a concrete claim on every card.')
        for number,provider in enumerate(('claude','openai'),71):
            self.job={**self.job,'id':number,'prompt':'Draft the card text.'}
            records=routing_inputs.capture(self.state,self.job,[(source,source.name,'project guide',str(self.root),None)],section='conversation-guides')
            with self.state.db:self.state.db.execute('INSERT INTO orchestrator_guide_choices VALUES (?,?,?,?,?,?,?)',(number,str(number),'selected',json.dumps(records),'[]','[0]',9999999999))
            action={**self.action,'provider':provider,'task_id':provider+':research','required_capabilities':['file_read']}
            self.dispatch(action)
            prompt=self.state.db.execute('SELECT prompt FROM backend_jobs WHERE thread_id=?',(provider+':research',)).fetchone()[0]
            self.assertTrue(prompt.startswith(self.job['prompt']))
            self.assertIn('Use a concrete claim on every card.',prompt)
            self.assertIn(records[0]['sha256'],prompt)

    def test_changed_model_disconnection_busy_and_uncertain_block_before_enqueue(self):
        snap=self.snapshot()
        with patch.object(backends,'claude_config',return_value=None):
            with self.assertRaisesRegex(ValueError,'unavailable'):self.dispatch(snap=snap)
        with self.state.db:self.state.db.execute("UPDATE backend_tasks SET model='changed' WHERE backend='claude'")
        with self.assertRaisesRegex(ValueError,'changed'):self.dispatch(snap=snap)
        for status in ('running','uncertain'):
            with self.state.db:self.state.db.execute("UPDATE watched SET status=? WHERE id='claude:research'",(status,))
            with self.assertRaises(ValueError):self.dispatch(snap=snap)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)

    def test_queue_failure_rolls_back_receipt_and_incoming(self):
        real=backends.enqueue
        def fail(*args,**kwargs):
            real(*args,**kwargs)
            raise ValueError('fixture failed after queue insertion')
        with patch.object(backends,'enqueue',side_effect=fail):
            with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM backend_jobs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM incoming').fetchone()[0],0)

    def test_chat_dispatch_delivers_replyable_ack_and_preserves_original(self):
        with self.state.db:
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,provider,model,created) VALUES (?,?,?,?,?)',
                (71,self.job['prompt'],'gemini','fixture',time.time()))
        captured=[]
        def generate(job,payload):
            captured.append(payload)
            return json.dumps({'answer':'I already completed the research.','action':self.action})
        worker=chat.Worker(self.state,generate);worker.tick();worker.tick()
        self.assertEqual(len(captured),1)
        self.assertIn('capabilities',captured[0]['snapshot'])
        answer=self.state.db.execute('SELECT answer,status FROM orchestrator_chats').fetchone()
        self.assertEqual(answer['status'],'answered');self.assertIn('Queued',answer['answer'])
        self.assertNotIn('completed',answer['answer'])
        telegram=TelegramFake();bridge=Bridge(self.state,telegram,{},None);bridge.flush(False)
        self.assertTrue(self.state.db.execute("SELECT 1 FROM messages WHERE thread_id='claude:research'").fetchone())

    def test_cards_stay_gated_and_production_context_does_not_route_feedback(self):
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            self.assertIsNone(caps.dispatch(self.state,self.job,{'kind':'run'},{}))
        system,payload=chat.model_context({'snapshot':{'focus':'video','production_runs':[{'name':'video'}],
            'capabilities':self.snapshot()['capabilities']}})
        self.assertIn('targets',payload['snapshot'].get('capabilities',{}))
        self.assertIn('delegate_task',system)
        self.assertIn('Do not route ordinary editorial',system)


if __name__=='__main__':unittest.main()
