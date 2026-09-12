from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import usage_tracker as usage
from usage_sources import collect_local


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.db=sqlite3.connect(self.root/'ledger.sqlite');self.db.row_factory=sqlite3.Row;usage.initialize(self.db)
        self.sessions=self.root/'sessions';self.sessions.mkdir();self.log=self.sessions/'session.jsonl'
        self.now=datetime(2026,9,12,tzinfo=timezone.utc).timestamp()

    def tearDown(self):self.db.close();self.tmp.cleanup()

    def write(self,events,mode='w'):
        with self.log.open(mode) as f:
            for e in events:f.write(json.dumps(e)+'\n')

    def token(self,i,o=10,t='2026-09-11T12:00:00Z'):
        return {'timestamp':t,'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{
            'input_tokens':i,'cached_input_tokens':i//2,'output_tokens':o,'reasoning_output_tokens':2,'total_tokens':i+o}}}}

    def scan(self,provider='codex',max_bytes=32000000):collect_local(self.db,[(provider,self.sessions)],max_bytes)
    def total(self):return usage.report(self.db,7,now=self.now)['groups'][0]['total_tokens']

    def test_provider_cache_and_reasoning_semantics(self):
        c=usage.normalize('codex',{'input_tokens':100,'cached_input_tokens':80,'output_tokens':20,'reasoning_output_tokens':10})
        self.assertEqual(c['total_tokens'],120)
        c=usage.normalize('claude',{'input_tokens':10,'cache_read_input_tokens':80,'cache_creation_input_tokens':10,'output_tokens':20})
        self.assertEqual((c['input_tokens'],c['total_tokens']),(100,120))
        g=usage.normalize('gemini',{'promptTokenCount':100,'cachedContentTokenCount':80,'candidatesTokenCount':12,'thoughtsTokenCount':8,'totalTokenCount':120})
        self.assertEqual((g['output_tokens'],g['total_tokens']),(20,120))
        self.assertTrue(all(v is None for v in usage.normalize('openai',{}).values()))

    def test_repeated_totals_restart_and_copied_log_count_once(self):
        self.write([{'type':'session_meta','payload':{'id':'s','cwd':'project'}},self.token(100),self.token(100),self.token(200,20,'2026-09-11T13:00:00Z')])
        self.scan();self.assertEqual(self.total(),220)
        self.scan();self.assertEqual(self.total(),220)
        (self.sessions/'copied.jsonl').write_bytes(self.log.read_bytes());self.scan();self.assertEqual(self.total(),220)

    def test_partial_append_and_counter_reset_never_recount_context(self):
        self.write([self.token(100)])
        line=json.dumps(self.token(200,20,'2026-09-11T13:00:00Z'))
        with self.log.open('a') as f:f.write(line[:60])
        self.scan();self.assertEqual(self.total(),110)
        with self.log.open('a') as f:f.write(line[60:]+'\n')
        self.scan();self.assertEqual(self.total(),220)
        self.write([self.token(20,1,'2026-09-11T14:00:00Z'),self.token(40,3,'2026-09-11T15:00:00Z')],'a')
        self.scan();self.assertEqual(self.total(),242)
        self.assertIn('counter_reset',usage.report(self.db,7,now=self.now)['sources'][0]['warnings'])

    def test_budget_continuation_keeps_small_usage_lines(self):
        self.write([self.token(i,10,'2026-09-11T12:'+str(i//100).zfill(2)+':00Z') for i in range(100,600,100)])
        for _ in range(10):self.scan(max_bytes=100)
        self.assertEqual(self.total(),510)

    def test_claude_fragments_share_message_identity(self):
        def e(o):return {'type':'assistant','timestamp':'2026-09-11T12:00:00Z','sessionId':'s','requestId':'r','cwd':'p',
                        'message':{'id':'m','model':'claude-fixture','usage':{'input_tokens':10,'output_tokens':o,'cache_read_input_tokens':50}}}
        self.write([e(1),e(20),e(20)]);self.scan('claude');self.assertEqual(self.total(),80)
        self.scan('claude');self.assertEqual(self.total(),80)

    def test_receipt_overlap_unknown_usage_and_utc_filter(self):
        with self.db:
            usage.record(self.db,'native','local_codex','codex','m','p','s',self.now-30,{'input_tokens':100,'output_tokens':20})
            usage.record(self.db,'managed','relay_worker','codex','m','p','s',self.now-20,{'input_tokens':100,'output_tokens':20})
            usage.record(self.db,'unknown','relay_api','openrouter','auto',None,None,self.now-10,{})
            usage.record(self.db,'old','relay_api','gemini','m',None,None,self.now-999999,{'promptTokenCount':999,'candidatesTokenCount':1})
        report=usage.report(self.db,7,now=self.now)
        self.assertEqual(report['groups'][0]['total_tokens'],120)
        self.assertEqual(report['deduplicated_local_records'],1);self.assertEqual(report['unmeasured_records'],1)
        self.assertIsNone(next(r for r in report['groups'] if r['name']=='openrouter')['total_tokens'])

    def test_incremental_receipt_gets_timestamp_when_it_finishes(self):
        with self.db:
            usage.record(self.db,'a','relay_worker','codex','m',None,None,None,{})
            usage.record(self.db,'a','relay_worker','codex','m',None,None,self.now-10,{'input_tokens':10,'output_tokens':2})
        self.assertEqual(self.total(),12)

    def test_claude_model_receipt_replaces_cost_only_placeholder(self):
        from types import SimpleNamespace
        job={'id':'job','created_at':self.now-10,'started_at':None}
        info={'cwd':'project','session_id':'session','model':'configured'}
        with self.db:
            usage.record(self.db,'claude-job:job','relay_api','claude','unknown','project','session',self.now-10,{},1,'sdk_usage_value')
            result=SimpleNamespace(model_usage={'actual-model':{'inputTokens':10,'cacheReadInputTokens':20,'outputTokens':5,'costUSD':1}})
            usage.record_claude(self.db,job,info,result)
            usage.record_claude(self.db,job,info,result)
        report=usage.report(self.db,7,now=self.now)
        self.assertEqual(report['records'],1)
        self.assertEqual(report['groups'][0]['total_tokens'],35)
        self.assertEqual(report['groups'][0]['sdk_usage_value_usd'],1)

    def test_disabled_worker_does_not_read_sources(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        state=SimpleNamespace(get=lambda k,d:False)
        with patch.object(usage,'refresh') as refresh:
            usage.Worker(state).tick()
            refresh.assert_not_called()

    def test_relay_steps_precede_aggregate_and_import_is_idempotent(self):
        from bridge import State
        source=self.root/'state.sqlite';s=State(source)
        with s.db:
            s.db.execute('INSERT INTO backend_tasks VALUES (?,?,?,?,?,?)',('t','openai','s','project','m',1))
            s.db.execute('INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES (?,?,?,?,?,?)',('j','t',1,'PRIVATE PROMPT','completed',self.now-10))
            s.db.execute('INSERT INTO api_steps VALUES (?,?,?)',('j',0,json.dumps({'input_tokens':10,'output_tokens':2})))
            s.db.execute('INSERT INTO api_steps VALUES (?,?,?)',('j',1,json.dumps({'input_tokens':20,'output_tokens':3})))
            s.db.execute('INSERT INTO api_runs(job_id,model,base_url,response_path,request_json,usage_json) VALUES (?,?,?,?,?,?)',('j','m','url','response','{}',json.dumps({'input_tokens':30,'output_tokens':5})))
        s.db.close()
        usage.collect_relay(self.db,source);usage.collect_relay(self.db,source)
        self.assertEqual(self.total(),35)
        self.assertNotIn('PRIVATE PROMPT',str([tuple(r) for r in self.db.execute('select * from usage_events')]))

    def test_command_auth_and_no_provider_invocation(self):
        from bridge import State,Bridge
        from tests.test_bridge import TelegramFake
        s=State(self.root/'state.sqlite');tg=TelegramFake();bridge=Bridge(s,tg,{})
        with s.db:s.put('user_id',7);s.put('chat_id',7)
        bridge.process({'update_id':1,'message':{'from':{'id':8},'chat':{'id':7,'type':'private'},'text':'/usage'}})
        self.assertEqual(tg.sent,[])
        bridge.process({'update_id':2,'message':{'from':{'id':7},'chat':{'id':7,'type':'private'},'text':'/usage 7 model'}})
        self.assertIn('No indexed usage',tg.sent[-1][1]);s.db.close()


if __name__=='__main__':unittest.main()
