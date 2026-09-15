import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay.bridge import Bridge, State
from tests.test_bridge import TelegramFake
from task_relay import workflows as wf
from task_relay import workflow_protocol as protocol

PLAN = {'step_id': 'one', 'objective': 'Bounded fix', 'scope': ['one file'],
        'exclusions': ['no solver'], 'deliverables': ['test evidence'], 'criteria': ['test passes'],
        'bounds': '10 seconds', 'instruction': 'Fix and test only this item.'}


def report(marker, decision, **extra):
    return 'Summary\n```relay-result\n' + json.dumps(dict(marker=marker, decision=decision, **extra)) + '\n```'


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.state = State(self.root / 'state.sqlite')
        self.tasks = []
        for tid in ('strategy', 'executor'):
            p = self.root / (tid + '.jsonl')
            p.write_text(json.dumps({'type':'event_msg','payload':{'type':'task_complete','turn_id':'old','last_agent_message':'Old'}})+'\n')
            self.tasks.append({'id':tid,'name':tid,'title':tid,'cwd':str(self.root),'rollout_path':str(p)})
        self.data = {'name':'demo','cwd':str(self.root),'strategy_id':'strategy','executor_id':'executor',
            'strategy_title':'Strategy','executor_title':'Executor','status':'active','phase':'plan_ready',
            'accepted':0,'attempts':0,'step_limit':1,'run_id':'run','planning_only':False}
        with self.state.db:
            self.state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)',('demo',json.dumps(self.data)))
            self.state.put('workflow_service_enabled',True)
            self.state.put('user_id',7); self.state.put('chat_id',7)
        self.calls = []; self.fail = False; self.on_start = None
        test = self
        class Desktop:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ready_owner(self,tid):return 'owner'
            def start(self,tid,prompt,owner):
                test.calls.append((tid,prompt))
                if test.on_start:test.on_start()
                turn='turn'+str(len(test.calls))
                test.append(tid,{'type':'event_msg','payload':{'type':'task_started','turn_id':turn}})
                test.append(tid,{'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':prompt}]}})
                if test.fail:raise TimeoutError()
                return {'result': {'turn':{'id':turn}}}
        self.worker = wf.Worker(self.state,Desktop,lambda:self.tasks)
        self.bridge = Bridge(self.state,TelegramFake(),{},Desktop)

    def tearDown(self):
        self.state.db.close();self.temp.cleanup()

    def append(self,tid,e):
        with open(next(t['rollout_path'] for t in self.tasks if t['id']==tid),'a') as f:f.write(json.dumps(e)+'\n')

    def read(self):return wf.read(self.state,'demo')[0]

    def mutate(self,**values):
        d,r=wf.read(self.state,'demo');d.update(values)
        with self.state.db:wf.save(self.state,d,r,'test')

    def finish(self,decision,**extra):
        d=self.read();op=d['operation'];text=report(op['marker'],decision,**extra)
        self.append(op['thread_id'],{'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn'+str(len(self.calls)),'last_agent_message':text}})
        self.worker.tick()

    def ready_execution(self):
        self.worker.tick();self.finish('READY',plan=PLAN);self.worker.tick()

    def review(self,decision='ACCEPTED'):
        self.finish('RESULT',step_id='one',evidence=['/project/evidence.json'])
        self.worker.tick()
        self.finish(decision,step_id='one',checks=[{'criterion':1,'passed':decision=='ACCEPTED','evidence':['inspected evidence']}],
                    human_gate_remaining=False,scope_unchanged=True,instruction='Fix the same criterion')

    def test_complete_loop_stops_at_one_accepted_item(self):
        self.ready_execution();self.review();self.worker.tick()
        self.assertEqual((self.read()['status'],self.read()['accepted']),('completed',1))
        self.assertEqual([t for t,_ in self.calls],['strategy','executor','strategy'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM workflow_dispatches').fetchone()[0],3)

    def test_verbatim_source_reaches_actual_planner_dispatch(self):
        source = {'message_id':12, 'text':'Why strips?\nRoom-first is my hypothesis; investigate it.', 'created':123}
        self.mutate(source_request=source, direction='Summarized investigation', planning_only=True)
        self.worker.tick()
        self.assertIn(source['text'], self.calls[0][1])
        self.assertIn('READ-ONLY PLANNING', self.calls[0][1])
        self.assertEqual(self.read()['attempts'], 0)

    def test_revision_budget_is_three_executor_attempts(self):
        self.ready_execution()
        for i in range(3):
            self.review('REVISE')
            if i<2:self.worker.tick()
        self.worker.tick()
        self.assertEqual(self.read()['status'],'paused')
        self.assertEqual(self.read()['attempts'],3)
        self.assertEqual(len(self.calls),7)
        self.assertEqual(self.read()['accepted'],0)

    def test_stricter_authorized_attempt_limit_prevents_any_retry(self):
        self.mutate(attempt_limit=1)
        self.ready_execution();self.review('REVISE');self.worker.tick()
        self.assertEqual(self.read()['status'],'paused')
        self.assertEqual(self.read()['attempts'],1)
        self.assertEqual(len(self.calls),3)

    def test_planning_only_never_dispatches_executor(self):
        self.mutate(planning_only=True);self.worker.tick();self.finish('READY',plan=PLAN);self.worker.tick()
        self.assertEqual(self.read()['status'],'paused');self.assertEqual(len(self.calls),1)

    def test_restart_during_dispatch_never_replays(self):
        self.mutate(phase='dispatching');self.worker.tick();self.worker.tick()
        self.assertEqual(self.read()['status'],'paused');self.assertFalse(self.calls)

    def test_uncertain_ipc_preserves_attempt_and_pauses(self):
        self.worker.tick();self.finish('READY',plan=PLAN);self.fail=True;self.worker.tick();self.worker.tick()
        self.assertEqual(self.read()['status'],'paused');self.assertEqual(self.read()['attempts'],1)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM workflow_dispatches WHERE status='uncertain'").fetchone()[0],1)

    def test_busy_project_and_other_workflow_prevent_dispatch(self):
        self.append('executor',{'type':'event_msg','payload':{'type':'task_started','turn_id':'outside'}})
        self.worker.tick();self.assertFalse(self.calls)
        self.append('executor',{'type':'event_msg','payload':{'type':'task_complete','turn_id':'outside','last_agent_message':'done'}})
        other=copy.deepcopy(self.data);other.update(name='other',phase='executing',operation={'thread_id':'executor'})
        with self.state.db:self.state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)',('other',json.dumps(other)))
        self.worker.advance(*wf.read(self.state,'demo'));self.assertFalse(self.calls)

    def test_unknown_history_malformed_response_and_wrong_marker_pause(self):
        self.worker.tick();self.finish('READY',plan={})
        self.assertEqual(self.read()['status'],'paused');self.assertEqual(len(self.calls),1)
        with self.assertRaises(ValueError):protocol.response(report('wrong','READY',plan=PLAN),'right','planning')
        with self.assertRaises(ValueError):protocol.response('ACCEPTED','right','reviewing',PLAN)

    def test_reviewer_must_check_every_criterion_and_human_gate(self):
        for checks,gate in [([],False),([{'criterion':1,'passed':False,'evidence':['test failed']}],False),([{'criterion':1,'passed':True,'evidence':['tested']}],True)]:
            with self.assertRaises(ValueError):protocol.response(report('m','ACCEPTED',step_id='one',checks=checks,human_gate_remaining=gate),'m','reviewing',PLAN)

    def test_user_turn_after_workflow_is_not_its_result(self):
        self.worker.tick()
        self.append('strategy',{'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn1','last_agent_message':report(self.read()['operation']['marker'],'READY',plan=PLAN)}})
        self.append('strategy',{'type':'event_msg','payload':{'type':'task_started','turn_id':'outside'}})
        self.append('strategy',{'type':'event_msg','payload':{'type':'task_complete','turn_id':'outside','last_agent_message':'different'}})
        self.worker.tick();self.assertEqual(self.read()['status'],'paused');self.assertEqual(len(self.calls),1)

    def test_pause_race_during_ipc_keeps_user_pause(self):
        self.on_start=lambda:wf.command(self.bridge,'pause demo',100)
        self.worker.tick();self.worker.tick()
        self.assertEqual(self.read()['status'],'paused');self.assertEqual(len(self.calls),1)
        self.assertEqual(self.read()['phase'],'planning')

    def test_controls_auth_dedup_and_budgets(self):
        update={'update_id':81,'message':{'from':{'id':99},'chat':{'id':7,'type':'private'},'text':'/workflow stop demo'}}
        self.bridge.process(update);self.assertEqual(self.read()['status'],'active')
        update['message']['from']['id']=7;self.bridge.process(update);self.bridge.process(update)
        self.assertEqual(self.read()['status'],'stopped')
        wf.command(self.bridge,'run demo 2 Keep current gates',82)
        self.assertEqual(self.read()['step_limit'],2)
        self.assertEqual(self.read()['direction'],'Keep current gates')
        with self.assertRaises(ValueError):wf.command(self.bridge,'run demo 99',83)

    def test_direct_user_instruction_pauses_and_claim_blocks_race(self):
        self.assertFalse(wf.user_intervention(self.state,'executor'))
        self.assertEqual(self.read()['status'],'paused')
        self.mutate(status='active',phase='dispatching')
        self.assertTrue(wf.user_intervention(self.state,'strategy'))

    def test_service_disabled_does_nothing(self):
        self.state.put('workflow_service_enabled',False);self.state.db.commit()
        self.worker.tick();self.assertFalse(self.calls)

    def test_recovery_import_completion_does_not_authorize_execution(self):
        self.mutate(phase='recovery_planning',planning_only=True,operation={
            'thread_id':'strategy','path':self.tasks[0]['rollout_path'],'turn_id':'old','offset':0})
        self.worker.tick();self.assertEqual(self.read()['status'],'paused');self.assertFalse(self.calls)

    def test_paused_restart_and_blocked_run_are_not_auto_resumed(self):
        self.worker.tick();self.finish('BLOCKED',reason='missing bytes');self.worker.tick()
        with self.assertRaises(ValueError):wf.command(self.bridge,'resume demo',100)
        wf.command(self.bridge,'plan demo Find retained inputs only',101)
        self.assertTrue(self.read()['planning_only']);self.assertEqual(self.read()['attempts'],0)

    def test_snapshot_revision_prevents_stale_dispatch_claim(self):
        d,r=wf.read(self.state,'demo');wf.command(self.bridge,'pause demo',100)
        with self.assertRaises(ValueError):self.worker.dispatch(d,r,{t['id']:t for t in self.tasks})
        self.assertFalse(self.calls)



    def test_routine_turns_owned_and_machine_handoffs_not_in_notices(self):
        self.worker.tick();op=self.read()['operation']
        self.assertTrue(wf.owns_turn(self.state,'strategy','turn1'))
        self.assertFalse(wf.owns_turn(self.state,'executor','turn1'))
        self.finish('READY',plan=PLAN);self.worker.tick();self.review()
        self.assertTrue(wf.owns_turn(self.state,'strategy','turn1'))
        text='\n'.join(r[0] for r in self.state.db.execute('SELECT text FROM outbox'))
        self.assertNotIn('relay-result',text);self.assertNotIn('"checks"',text)

    def test_bound_review_does_not_accept_duplicate_or_missing_json_keys(self):
        with self.assertRaises(ValueError):protocol.response('```relay-result\n{"marker":"m","marker":"m","decision":"READY"}\n```','m','planning')
        self.ready_execution();self.review();self.mutate(status='active',phase='plan_ready',step_limit=2)
        self.worker.tick();self.finish('READY',plan=PLAN)
        self.assertEqual(self.read()['status'],'paused')
        self.assertEqual(self.read()['accepted'],1)
