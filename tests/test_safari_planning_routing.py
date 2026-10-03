"""Capability routing must not accidentally lock the text reviewer to Safari."""
import copy
import json
import unittest
from unittest.mock import patch
from orchestrator import executors,worker_capabilities as workers
from task_relay import production_planning as planning,computer_target
from tests import test_production_planning as fixtures
from tests.test_computer_launch import runtime

CAPTURE=workers.capture
COMPUTER={'type':'gemini-computer','model':'fixture-model'}
TEXT={'type':'gemini-agent','model':'fixture-model'}
CATALOG=[dict(workers.entry(b),available=True) for b in (COMPUTER,TEXT)]
REQUEST='Use Safari Computer Use to open https://example.com/profile, read the profile, scroll once, and save a short evidence-based summary.'

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response

    def queue_safari(self,ident=1,action=None,text=REQUEST):
        with patch.object(executors,'catalog',return_value=copy.deepcopy(CATALOG)),patch.object(executors,'available'),patch.object(workers,'capture',wraps=CAPTURE),patch.object(computer_target,'runtime',return_value=runtime()):
            return self.queue(ident=ident,action=action or self.action(executor='gemini-computer'),text=text)

    def proposal(self):
        response=self.response()
        for task in response['plan']['tasks']:
            task.pop('tools');task['worker']={'requires':['files.text']};task['limits']=executors.GEMINI_LIMITS.copy()
        task=response['plan']['tasks'][0]
        task['worker']['requires'].append('computer.use')
        task['computer']={'selection':runtime()['selection'],'url':'https://example.com/profile','allowed_urls':['https://example.com/profile'],'max_seconds':300}
        return response

    def test_inferred_computer_profile_keeps_text_reviewer_available(self):
        row=self.queue_safari();options=json.loads(row['options'])
        self.assertFalse(options['executor_locked']);self.assertNotIn('executor',options)
        self.assertEqual(options['backend'],COMPUTER)
        self.assertEqual({v['id'] for v in options['worker_catalog']},{'gemini-computer','gemini-agent'})
        self.assertEqual(row['request'],REQUEST)
        planning.Worker(self.state,lambda *_:(json.dumps(self.proposal()),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        plan=json.loads(row['plan'])
        self.assertEqual(plan['tasks'][0]['worker']['backend'],COMPUTER)
        self.assertEqual(plan['tasks'][1]['worker']['backend'],TEXT)
        self.assertEqual(plan['tasks'][1]['tools'],['files'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_profile_plan_freezes_post_cap_and_extra_audit_before_dispatch(self):
        self.queue_safari(text=REQUEST+' Inspect up to five visible posts.')
        response=self.proposal();producer,reviewer=response['plan']['tasks']
        producer['research']={'mode':'profile'}
        reviewer['limits']['provider_requests']=16
        producer['outputs']=[{'path':'delivery/summary.md','purpose':'Profile summary'},
                             {'path':'delivery/evidence.json','purpose':'Post evidence'}]
        reviewer['inputs']=[{'from_task':producer['id'],'output':o['path'],'path':'candidate/'+o['path'],
                            'purpose':o['purpose'],'authority':'Unaccepted candidate'} for o in producer['outputs']]
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        saved=json.loads(row['plan']);producer,reviewer=saved['tasks']
        self.assertEqual(producer['research_delivery']['max_posts'],5)
        self.assertEqual(reviewer['research_audit']['producer'],producer['id'])
        self.assertEqual(reviewer['research_audit']['version'],2)
        self.assertEqual(reviewer['operation_contract']['id'],'research.audit')
        self.assertEqual(reviewer['criteria'][:-1],producer['criteria'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_undersized_multi_page_plan_is_corrected_before_dispatch(self):
        self.queue_safari()
        response=self.proposal();task=response['plan']['tasks'][0]
        task['computer']['allowed_urls'].append('https://example.com/second')
        calls=[]
        def model(_job,payload):
            calls.append(payload)
            if len(calls)==2:
                task['limits'].update(provider_requests=12,response_tokens=8192)
            return json.dumps(response),{}
        worker=planning.Worker(self.state,model)
        worker.tick()
        self.assertEqual(self.row()['status'],'queued')
        self.assertIn('Safari batch budget is too small',self.row()['error'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        worker.tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        saved=json.loads(row['plan'])['tasks'][0]
        self.assertEqual(len(saved['computer']['spec']['allowed_urls']),2)
        self.assertEqual(saved['limits']['provider_requests'],12)
        self.assertEqual(saved['limits']['response_tokens'],8192)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plan_calls').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_explicit_small_response_budget_is_not_silently_enlarged(self):
        self.queue_safari()
        response=self.proposal();task=response['plan']['tasks'][0]
        task['computer']['allowed_urls'].append('https://example.com/second')
        task['limits'].update(provider_requests=12,response_tokens=4096)
        original=copy.deepcopy(response)
        with self.assertRaisesRegex(ValueError,'response_tokens'):
            planning.validate_result(json.dumps(response),self.row())
        self.assertEqual(response,original)
        task['computer']['allowed_urls'].pop()
        _,plan=planning.validate_result(json.dumps(response),self.row())
        self.assertEqual(plan['tasks'][0]['limits']['response_tokens'],4096)

    def test_explicit_provider_or_executor_remains_locked(self):
        for n,name in enumerate(('Gemini','gemini-computer','OpenAI','Codex'),1):
            row=self.queue_safari(ident=n,text=REQUEST+' Use '+name+' only.')
            options=json.loads(row['options'])
            self.assertTrue(options['executor_locked'])
            self.assertEqual(options['worker_catalog'],[workers.entry(COMPUTER)])

    def test_fresh_child_of_old_inferred_lock_preserves_failed_record(self):
        row=self.queue_safari()
        # Represent the old route exactly: a locked catalog, no executable plan/run.
        options=json.loads(row['options']);options.update(executor='gemini-computer',executor_locked=True,worker_catalog=[workers.entry(COMPUTER)])
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='blocked',options=?,error='No eligible worker for files.text' WHERE id=?",(json.dumps(options),row['id']))
        before=dict(self.row())
        child=self.queue_safari(ident=2,action=self.action(parent_id=row['id']),text='Please try this request again.')
        self.assertFalse(json.loads(child['options'])['executor_locked'])
        self.assertEqual(len(json.loads(child['options'])['worker_catalog']),2)
        self.assertIn(REQUEST,child['request'])
        for key in ('request','options','context','context_hash','result','plan','error','run'):
            self.assertEqual(self.row()[key],before[key],key)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_child_of_explicit_lock_cannot_expand_catalog(self):
        row=self.queue_safari(text=REQUEST+' Use gemini-computer only.')
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='blocked' WHERE id=?",(row['id'],))
        child=self.queue_safari(ident=2,action=self.action(parent_id=row['id']),text='Try again.')
        options=json.loads(child['options'])
        self.assertTrue(options['executor_locked']);self.assertEqual(len(options['worker_catalog']),1)

    def test_saved_executable_scope_is_not_rebound(self):
        row=self.queue_safari()
        options=json.loads(row['options']);options.update(executor='gemini-computer',executor_locked=True,worker_catalog=[workers.entry(COMPUTER)])
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='blocked',options=?,run='saved-run' WHERE id=?",(json.dumps(options),row['id']))
        child=self.queue_safari(ident=2,action=self.action(parent_id=row['id']),text='Try again.')
        self.assertTrue(json.loads(child['options'])['executor_locked'])
