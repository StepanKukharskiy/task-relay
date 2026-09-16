"""Small recorded receipts exercise truthful, read-only activity display."""
import json
from pathlib import Path
import tempfile
import unittest
from task_relay import production_activity as activity


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.control=self.root/'workers'/'attempt';self.control.mkdir(parents=True)
        self.spec={'objective':'Prepare the selected model','limits':{'seconds':900}}
        self.backend={'type':'codex-cli','model':'frozen-model','reasoning':'high'}
        self.frozen={**self.spec,'backend':self.backend}
        self.attempt={'id':'attempt','state':'running','frozen':json.dumps(self.frozen),'receipt':None}
    def tearDown(self):self.temp.cleanup()
    def write(self,name,**values):
        (self.control/name).write_text(json.dumps({'token':'attempt',**values}))
    def task(self,value,status='running'):
        return {'status':status,'latest_attempt':'attempt','activity':value}

    def test_running_uses_frozen_model_elapsed_and_reported_usage_without_mutation(self):
        self.write('started.json',started=100)
        self.write('progress.json',heartbeat_at=249,last_event_at=240,activity='using_tool',tool_calls=4,
                   usage=[{'input_tokens':100,'cached_input_tokens':80,'output_tokens':20},
                          {'input_tokens':50,'cached_input_tokens':30,'output_tokens':10}])
        before={p.name:p.read_bytes() for p in self.control.iterdir()}
        s=activity.snapshot(self.root,self.attempt,self.spec,{'model':'new-config'},now=250)
        self.assertEqual(s['model'],'frozen-model')
        self.assertEqual(s['elapsed_seconds'],150)
        self.assertEqual(s['usage']['tokens'],{'input':150,'output':30,'cached':110})
        text='\n'.join(activity.lines(self.task(s),now=250))
        self.assertIn('Relay is working on: Prepare the selected model',text)
        self.assertIn('Elapsed: 2m 30s',text)
        self.assertIn('Tokens reported so far',text)
        self.assertIn('10s ago',text)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.control.iterdir()})

    def test_final_receipt_overrides_stale_progress_and_stops_elapsed_clock(self):
        self.write('started.json',started=100)
        self.write('progress.json',usage=[{'input_tokens':999}])
        self.attempt.update(state='completed',receipt=json.dumps({'status':'finished','elapsed_seconds':90,
            'usage':[{'promptTokenCount':50,'candidatesTokenCount':20,'thoughtsTokenCount':7,'cachedContentTokenCount':10}]}))
        s=activity.snapshot(self.root,self.attempt,self.spec,self.backend,now=1000)
        self.assertEqual(s['elapsed_seconds'],90)
        self.assertEqual(s['usage']['tokens'],{'input':50,'output':20,'reasoning':7,'cached':10})
        self.assertIn('Tokens reported (final)','\n'.join(activity.lines(self.task(s,'completed'))))

    def test_unknown_usage_is_not_zero_and_malformed_identity_or_symlink_is_ignored(self):
        self.write('started.json',started=100)
        self.write('progress.json',token='another-attempt',usage=[{'input_tokens':123}])
        s=activity.snapshot(self.root,self.attempt,self.spec,self.backend,now=200)
        self.assertEqual(s['usage']['tokens'],{})
        self.assertIn('Tokens: not reported yet','\n'.join(activity.lines(self.task(s))))
        (self.control/'progress.json').unlink()
        secret=self.root/'private.json';secret.write_text(json.dumps({'token':'attempt','usage':[{'input_tokens':123}]}))
        (self.control/'progress.json').symlink_to(secret)
        self.assertEqual(activity.snapshot(self.root,self.attempt,self.spec,self.backend)['usage']['tokens'],{})
        self.assertNotIn('123','\n'.join(activity.lines(self.task(s))))

    def test_local_operation_does_not_claim_to_use_planner_model(self):
        self.write('progress.json',tool_calls=0)
        self.frozen['execution']={'capability':'rhino.run_python','parameters':{}}
        self.attempt['frozen']=json.dumps(self.frozen)
        s=activity.snapshot(self.root,self.attempt,self.spec,self.backend)
        self.assertFalse(s['ai']);self.assertIsNone(s['model'])
        text='\n'.join(activity.lines(self.task(s)))
        self.assertIn('Executor: rhino.run_python',text)
        self.assertNotIn('AI:',text);self.assertNotIn('Tokens:',text);self.assertNotIn('Tools used:',text)
        self.frozen['execution']={'capability':'gemini.text','parameters':{'model':'api-model'}}
        self.attempt['frozen']=json.dumps(self.frozen)
        self.assertEqual(activity.snapshot(self.root,self.attempt,self.spec,self.backend)['model'],'api-model')

    def test_response_allowance_uses_saved_attempt_not_changed_plan(self):
        self.frozen['backend']={'type':'gemini-code','model':'fixture','runtime':'fixture'}
        self.frozen['limits']={'seconds':600,'response_tokens':16384}
        self.attempt['frozen']=json.dumps(self.frozen)
        self.spec['limits']['response_tokens']=4096
        s=activity.snapshot(self.root,self.attempt,self.spec,self.backend)
        self.assertIn('Response limit: 16,384 output tokens per request','\n'.join(activity.lines(self.task(s))))

    def test_nested_usage_details_and_missing_fields_are_not_invented(self):
        result=activity.usage_totals([{'prompt_tokens':100,'completion_tokens':20,
            'prompt_tokens_details':{'cached_tokens':80},'completion_tokens_details':{'reasoning_tokens':10}},
            {'input_tokens':False,'output_tokens':-2},{}])
        self.assertEqual(result,{'reported_responses':1,'tokens':{'input':100,'output':20,'cached':80,'reasoning':10}})
        self.assertEqual(activity.usage_totals([{'input_tokens':0}])['tokens'],{'input':0})

    def test_missing_final_time_and_stale_heartbeat_do_not_claim_fresh_execution(self):
        self.write('started.json',started=100)
        self.write('progress.json',heartbeat_at=110,last_event_at=105)
        s=activity.snapshot(self.root,self.attempt,self.spec,self.backend,now=200)
        self.assertIn('heartbeat is stale','\n'.join(activity.lines(self.task(s),now=200)))
        self.attempt['state']='uncertain'
        self.assertIsNone(activity.snapshot(self.root,self.attempt,self.spec,self.backend,now=200)['elapsed_seconds'])
