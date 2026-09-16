"""Approved request limits, output checkpoints and same-workflow recovery."""
import copy,json
from pathlib import Path
from unittest.mock import patch
import unittest
from orchestrator import executors,contracts as c
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from orchestrator.storage import transaction
from task_relay import code_runtime,native_code_host,production_visual_review as recovery
from tests import test_shared_code_workers as workers,test_production_planning as fixtures
from tests.test_gemini_executor import report
from tests.test_orchestrator import pair


class LoopTests(unittest.TestCase):
    setUp=workers.Tests.setUp;backend=workers.Tests.backend;host_result=workers.Tests.host_result
    def test_code_can_write_after_eight_requests_with_explicit_budget(self):
        backend=self.backend('gemini',True);self.frozen.update(backend=backend,tools=['files','python'])
        self.frozen['limits']['provider_requests']=12
        config={'api_key':'fixture-only'};atomic(self.control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
        frozen=self.frozen;seen=[]
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                name,args=('python_run',{'code':'fixture write','seconds':5}) if n==3 else ('file_list',{}) if n<11 else ('finish',report(frozen))
                return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        with patch.object(code_runtime,'available',return_value=workers.RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result):
            result=execute(frozen,self.control,Client(),lambda:(config,backend))
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(seen),11)
        self.assertTrue((self.ws/'output.txt').is_file())
        self.assertIn('Declared outputs still missing: ["output.txt"]',seen[1]['systemInstruction']['parts'][0]['text'])
        self.assertIn('Declared outputs still missing: []',seen[10]['systemInstruction']['parts'][0]['text'])

    def test_request_limit_rejects_unbounded_or_noninteger_values(self):
        for value in (True,0,25,'20'):
            self.frozen['limits']['provider_requests']=value
            with self.assertRaisesRegex(ValueError,'provider request limit'):c.assignment(self.frozen)
        self.frozen['limits'].pop('provider_requests')
        self.assertEqual(executors.request_limit(self.frozen),8)

    def test_response_limit_is_validated_and_frozen(self):
        for value in (True,0,1023,16385,'16384'):
            self.frozen['limits']['response_tokens']=value
            with self.assertRaisesRegex(ValueError,'response token limit'):c.assignment(self.frozen)
        self.frozen['limits']['response_tokens']=16384
        self.assertEqual(c.assignment(self.frozen)['limits']['response_tokens'],16384)

    def test_read_only_loop_requires_real_checkpoint_then_restores_validation(self):
        backend=self.backend('gemini',True);self.frozen.update(backend=backend,tools=['files','python'])
        self.frozen['limits']['provider_requests']=12
        config={'api_key':'fixture-only'};atomic(self.control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
        frozen=self.frozen;seen=[]
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                offered={t['name'] for t in payload['tools'][0]['functionDeclarations']}
                if n<5:name,args='python_run',{'code':'read-only fixture','seconds':5}
                elif n==5:
                    assert offered=={'file_write','python_checkpoint','finish'}
                    # An attempted out-of-policy inspection is rejected locally.
                    name,args='python_run',{'code':'forbidden read','seconds':5}
                elif n==6:name,args='file_write',{'path':'output.txt','text':'Unreviewed draft'}
                elif n==7:
                    assert 'python_run' in offered
                    name,args='python_run',{'code':'validate saved draft','seconds':5}
                else:name,args='finish',report(frozen)
                return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        def inspect(runtime,folder,code,*args):
            self.assertNotEqual(code,'forbidden read')
            if code=='validate saved draft':self.assertEqual((folder/'inputs/output.txt').read_text(),'Unreviewed draft')
            out=folder/'outputs';out.mkdir()
            return {'returncode':0,'log':'inspection complete','outputs':str(out)}
        with patch.object(code_runtime,'available',return_value=workers.RECEIPT),patch.object(native_code_host,'run',side_effect=inspect) as host:
            self.assertEqual(execute(frozen,self.control,Client(),lambda:(config,backend))['decision'],'delivered')
        self.assertEqual(host.call_count,5);self.assertEqual(len(seen),8)
        self.assertEqual((self.ws/'output.txt').read_text(),'Unreviewed draft')

    def test_python_checkpoint_requires_files_and_keeps_compact_code_editing(self):
        backend=self.backend('gemini',True);self.frozen.update(backend=backend,tools=['files','python'])
        self.frozen['limits']['provider_requests']=12
        config={'api_key':'fixture-only'};atomic(self.control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
        frozen=self.frozen;seen=[]
        class Client:
            def request(self,endpoint,payload,**kwargs):
                seen.append(copy.deepcopy(payload));n=len(seen)
                if n<5:name,args='file_list',{}
                elif n in (5,6):name,args='python_checkpoint',{'code':'inspect' if n==5 else 'transform existing document','seconds':5}
                else:name,args='finish',report(frozen)
                return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}
        def run(runtime,folder,code,*args):
            out=folder/'outputs';out.mkdir()
            if code!='inspect':(out/'output.txt').write_text('large preserved document '*3000)
            return {'returncode':0,'log':'done','outputs':str(out)}
        with patch.object(code_runtime,'available',return_value=workers.RECEIPT),patch.object(native_code_host,'run',side_effect=run):
            self.assertEqual(execute(frozen,self.control,Client(),lambda:(config,backend))['decision'],'delivered')
        receipt=json.loads((self.control/'tool-05-00.json').read_text())
        self.assertEqual(receipt['result']['missing_outputs'],['output.txt'])
        self.assertGreater((self.ws/'output.txt').stat().st_size,50000)


class RecoveryTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    def stopped(self):
        p=pair(max_attempts=2);p['backend']={'type':'gemini-code','model':'fixture-model','runtime':workers.RECEIPT['id']}
        for t in p['tasks']:t.update(tools=['files','python'],limits={'seconds':600,'tool_calls':20,'output_bytes':1000000})
        self.rt.create(p);self.rt.tick('demo');aid=self.rt.task('demo','produce')['latest']
        self.factory.sessions[aid]['status']={'status':'finished','exit_code':1,'external_outcome':'no_pending_response','pending_requests':[],
            'reason':'ValueError: Provider request budget exhausted; no automatic continuation.','api_requests':8}
        self.rt.tick('demo');return aid

    def test_delivered_start_uses_remaining_attempt_and_preserves_graph(self):
        old=self.stopped();before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone())
        with transaction(self.state.db):
            from task_relay.production_continuations import enqueue
            text=enqueue(self.state,{'id':99,'prompt':'Continue the saved work.'},'demo')
        self.assertIn('20 provider requests',text)
        row=self.state.db.execute('SELECT * FROM production_visual_review_cards').fetchone()
        self.assertEqual(recovery.controls(self.state,row['event_id'])['inline_keyboard'][0][0]['text'],'Start preparation')
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO outbox(id,text,sent) VALUES (?,?,1)',(row['event_id'],'Fixture Start card'))
            recovery.remember(self.state,row['event_id'],7,9)
            recovery.apply(self.state,row['token'],7,9)
            recovery.apply(self.state,row['token'],7,9)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone()),before)
        self.rt.tick('demo');new=self.rt.task('demo','produce')['latest']
        self.assertNotEqual(new,old);self.assertEqual(self.rt.task('demo','produce')['attempts'],2)
        frozen=self.factory.sessions[new]['frozen'];self.assertEqual(frozen['limits']['provider_requests'],20)
        self.assertEqual(self.rt.spec(self.rt.task('demo','produce'))['max_attempts'],2)
        self.assertEqual(self.rt.spec(self.rt.task('demo','review'))['limits']['provider_requests'],20)
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.factory.finish(new);self.rt.tick('demo');review=self.rt.task('demo','review')['latest']
        self.factory.finish(review,decision='accept');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['status'],'completed')

    def test_pending_provider_response_cannot_be_replayed(self):
        old=self.stopped()
        with self.state.db:
            self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(old,))
        with self.assertRaisesRegex(ValueError,'uncertain'):recovery.snapshot(self.state,'demo')


class SuccessorTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request;action=fixtures.Tests.action;queue=fixtures.Tests.queue
    row=fixtures.Tests.row;response=fixtures.Tests.response;click=fixtures.Tests.click;start=fixtures.Tests.start

    def test_exhausted_preparation_creates_new_start_not_reset_or_dispatch(self):
        self.check_successor('budget')

    def test_received_truncation_creates_new_start_with_unchanged_limits(self):
        self.check_successor('generation_limit')

    def test_received_malformed_call_creates_new_start_with_unchanged_limits(self):
        self.check_successor('malformed')

    def check_successor(self,failure):
        from task_relay import production_planning as planning,production_control as pc,production_stages
        from task_relay.production_continuations import enqueue
        backend={'type':'gemini-code','model':'fixture-model','runtime':workers.RECEIPT['id']}
        with self.state.db:self.state.put('production-planner-policy',{'backend':backend})
        with patch.object(executors,'available'):
            self.queue()
            legacy=self.row();options=json.loads(legacy['options']);options.pop('response_budgets',None)
            with self.state.db:self.state.db.execute('UPDATE production_plans SET options=? WHERE id=?',(c.encoded(options),legacy['id']))
            response=self.response()
            for t in response['plan']['tasks']:
                t['tools']=['files','python'];t['limits']={'seconds':600,'tool_calls':20,'provider_requests':20,'output_bytes':1000000}
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
            old=self.row();self.assertEqual(old['status'],'ready',old['error'])
            self.start(old)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        aid=self.rt.task('production-1','produce')['latest']
        self.factory.sessions[aid]['status']={'status':'finished','exit_code':1,'external_outcome':'no_pending_response','pending_requests':[],
            'reason':('ValueError: Provider request budget exhausted (20 requests); missing outputs: output.txt; no automatic continuation.'
                      if failure=='budget' else 'ValueError: Incomplete provider response; retained without retry.')}
        worker.tick()
        if failure!='budget':
            control=self.rt.root/'received-generation';control.mkdir()
            atomic(control/'api-16.request.json',{})
            atomic(control/'api-16.response.json',{'candidates':[{'finishReason':'MAX_TOKENS' if failure=='generation_limit' else 'MALFORMED_FUNCTION_CALL'}]})
            with self.state.db:
                self.state.db.execute('UPDATE production_attempts SET session=? WHERE id=?',
                    (json.dumps({'control':str(control),'backend':backend}),aid))
        retained_file=self.rt.root/'completed.txt';retained_file.write_text('Earlier completed artifact')
        retained_id=self.rt.register(retained_file,'Earlier deliverable',path='delivery/completed.txt')
        context=json.loads(old['context'])
        # An older recovery already supplied a draft under the former shared
        # path. The latest stopped attempt produced another version of it.
        prior_file=self.rt.root/'prior-draft.txt';prior_file.write_text('old unreviewed draft')
        prior_id=self.rt.register(prior_file,'Older unreviewed draft',path='output.txt')
        context['sources'].append(planning.source_entry(self.rt,prior_id,'recovery/previous/produce/output.txt',
            'Older draft','Unreviewed historical evidence'))
        context['required_artifacts'].append(prior_id)
        latest_file=self.rt.root/'latest-draft.txt';latest_file.write_text('new unreviewed draft')
        latest_id=self.rt.register(latest_file,'Latest unreviewed draft',run='production-1',task='produce',attempt=aid,path='output.txt')
        context['execution_recovery']={'completed_deliverables':{'prior':{'artifact':retained_id,
            'sha256':self.rt.artifact(retained_id)['sha256'],'description':'Earlier deliverable',
            'run':'earlier','task':'earlier','output':'delivery/completed.txt'}}}
        with self.state.db:self.state.db.execute('INSERT INTO production_user_notes VALUES (?,?,?,?,?)',
            ('fixture-note','production-1','Skip photos marked missing; retain subject text.','user',1))
        with self.state.db:self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',
            (c.encoded(context),c.digest(context),old['id']))
        before=[dict(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        calls=len(self.factory.calls)
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            text=enqueue(self.state,{'id':99,'prompt':'Continue with the saved files.'},'production-1')
        self.assertIn('Preparation recovery planned',text)
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(old['id'],)).fetchone()
        self.assertEqual(successor['status'],'ready')
        self.assertEqual([dict(r) for r in self.state.db.execute('SELECT * FROM production_attempts')],before)
        self.assertEqual(len(self.factory.calls),calls)
        plan=json.loads(successor['plan'])
        inputs=plan['tasks'][0]['inputs']
        self.assertEqual(len({i['path'] for i in inputs}),len(inputs))
        self.assertTrue(any(i.get('artifact')==prior_id for i in inputs))
        self.assertTrue(any(i.get('artifact')==latest_id and aid in i['path'] for i in inputs))
        self.assertEqual(plan['tasks'][0]['limits']['provider_requests'],20)
        self.assertEqual(plan['tasks'][0]['limits']['response_tokens'],16384)
        self.assertEqual(plan['tasks'][1]['limits']['response_tokens'],4096)
        self.assertNotIn('response_tokens',json.loads(before[0]['frozen'])['limits'])
        self.assertIn('16,384 output tokens per provider response',planning.preview(successor))
        self.assertEqual(plan['tasks'][0]['max_attempts'],2)
        feedback=next(i for i in plan['tasks'][0]['inputs'] if i['path'].endswith('/USER_FEEDBACK.json'))
        exact=json.loads(Path(self.rt.artifact(feedback['artifact'])['blob']).read_text())
        self.assertEqual(exact['current_request'],'Continue with the saved files.')
        self.assertEqual(exact['history']['user_notes'][0]['text'],'Skip photos marked missing; retain subject text.')
        self.assertTrue(all(any(i.get('artifact')==feedback['artifact'] for i in t['inputs']) for t in plan['tasks']))
        context=json.loads(successor['context'])
        self.assertEqual(context['execution_recovery']['completed_deliverables']['prior']['artifact'],retained_id)
        production_stages.verify(self.state,self.rt,context,successor['id'],'telegram')
        # A changed failure receipt makes the saved Start stale.
        with self.state.db:self.state.db.execute("UPDATE production_attempts SET receipt='{}' WHERE id=?",(aid,))
        with self.assertRaises(ValueError):production_stages.verify(self.state,self.rt,context,successor['id'],'telegram')
        with self.state.db:self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(before[0]['receipt'],aid))
        with patch.object(executors,'available'):self.start(successor)
        started=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(successor['id'],)).fetchone()
        self.assertEqual(started['status'],'started',started['error'])
        self.assertEqual(len(self.factory.calls),calls)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()),before[0])
