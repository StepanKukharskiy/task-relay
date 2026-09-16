"""Stopped browser setup failure recovery; no live browser or provider calls."""
import copy
import json
import unittest
from unittest.mock import patch
from orchestrator import executors
from tests.test_browser_screenshots import capture_graph
from tests.test_gemini_executor import CONFIG
from tests import test_production_planning as fixtures
from task_relay import production_planning as planning,production_control as pc,production_stages as stages
from task_relay.production_browser_recovery import prepare


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request;action=fixtures.Tests.action;queue=fixtures.Tests.queue
    row=fixtures.Tests.row;response=fixtures.Tests.response;click=fixtures.Tests.click;start=fixtures.Tests.start

    def stopped(self,completed_sources=False):
        backend={'type':'gemini-agent','model':'fixture-model'}
        with patch.object(executors,'configured',return_value=(CONFIG,backend)),patch.object(executors,'available'):
            self.queue(action=self.action(executor='gemini-browser'),text='Capture the requested map viewport. I will review it.')
            response=self.response();response['plan']['tasks']=capture_graph()['tasks']
            if completed_sources:
                from tests.test_general_browser import browser_graph
                sources=browser_graph()['tasks']
                for t in sources:
                    t.pop('user_gate',None)
                    t['id']='source_'+t['id']
                    t['dependencies']=['source_'+d for d in t.get('dependencies',[])]
                    if t.get('review_of'):t['review_of']='source_'+t['review_of']
                    for i in t.get('inputs',[]):
                        if i.get('from_task'):i['from_task']='source_'+i['from_task']
                producer=response['plan']['tasks'][0]
                producer['dependencies']=['source_produce','source_review']
                output=sources[0]['outputs'][0]['path']
                producer['inputs']=[dict(from_task='source_produce',output=output,path='sources/completed.txt',purpose='Use exact completed source',authority='Previously reviewed source')]
                response['plan']['tasks']=sources+response['plan']['tasks']
            saved_tasks=copy.deepcopy(response['plan']['tasks'])
            if completed_sources:response['plan']['tasks']=capture_graph()['tasks']
            planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
            old=self.row()
            if old['status']!='ready':raise ValueError(old['error'])
            if completed_sources:
                from orchestrator import contracts as c
                plan=json.loads(old['plan']);plan['tasks']=saved_tasks
                self.rt.create(plan)
                response['plan']['tasks']=saved_tasks
                response['deliverable_map']={'source':{'task':'source_produce','output':'output.txt'}}
                options=json.loads(old['options']);options['deliverables']={'source':'Completed source delivery'}
                context=json.loads(old['context']);context['options']=options
                with self.state.db:
                    self.state.db.execute('UPDATE production_plans SET run=?,status=?,result=?,plan=?,plan_hash=?,options=?,context=?,context_hash=? WHERE id=?',
                        ('production-1','started',c.encoded(response),c.encoded(plan),c.digest(plan),c.encoded(options),c.encoded(context),c.digest(context),old['id']))
                old=self.row()
            else:self.start(old)
            worker=pc.Worker(self.state,lambda _:self.rt)
            if completed_sources:
                from types import SimpleNamespace
                worker=SimpleNamespace(tick=lambda:self.rt.tick('production-1'))
            worker.tick()
            if completed_sources:
                for tid,decision in [('source_produce','delivered'),('source_review','accept')]:
                    source=self.rt.task('production-1',tid)['latest'];self.factory.finish(source,decision=decision)
                    self.factory.sessions[source]['status']['browser']={'actions':[]}
                    worker.tick()
            task=self.rt.task('production-1','produce');aid=task['latest']
            self.factory.sessions[aid]['status']={'status':'finished','exit_code':1,
                'browser':{'actions':[{'id':'open','status':'observed'}]},'reason':'Consent redirect outside declared origins'}
            worker.tick()
        return old,aid

    def test_prelaunch_failure_reuses_completed_sources_and_review(self):
        old,aid=self.stopped(completed_sources=True)
        with self.state.db:
            receipt=json.loads(self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(aid,)).fetchone()[0])
            receipt.update(api_requests=0,tool_calls=0,browser={'actions':[],'uncertain_actions':[]},
                reason='ValueError: Chrome did not finish opening. Close the Relay browser window and use Open browser to retry.')
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),aid))
        before=[dict(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        policies={t['id']:t['browser'] for t in json.loads(old['result'])['plan']['tasks'] if not t['id'].startswith('source_')}
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            from task_relay.production_continuations import enqueue
            enqueue(self.state,{'id':99,'prompt':'Recover browser startup; retain completed sources.'},'production-1')
            ident=self.state.db.execute('SELECT plan_id FROM production_stage_links WHERE parent=?',('production-1',)).fetchone()[0]
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        plan=json.loads(row['plan']);context=json.loads(row['context'])
        self.assertEqual({t['id'] for t in plan['tasks']},{'produce','review'})
        self.assertEqual(context['execution_recovery']['reused_completed_tasks'],['source_produce','source_review'])
        artifact=self.rt.output('production-1','source_produce','output.txt')
        selected=next(i for i in plan['tasks'][0]['inputs'] if i['path']=='sources/completed.txt')
        self.assertEqual(selected['artifact'],artifact['id'])
        retained=context['execution_recovery']['completed_deliverables']['source']
        self.assertEqual(retained['artifact'],artifact['id']);self.assertEqual(retained['sha256'],artifact['sha256'])
        self.assertNotIn('source_review',plan['tasks'][0]['dependencies'])
        self.assertEqual([dict(r) for r in self.state.db.execute('SELECT * FROM production_attempts')],before)
        stages.verify(self.state,self.rt,context,ident,'telegram')

    def test_repair_requires_new_start_preserves_old_attempt_and_policies(self):
        old,aid=self.stopped()
        policies={t['id']:copy.deepcopy(t['browser']) for t in json.loads(old['result'])['plan']['tasks']}
        for p in policies.values():p['profile']='managed';p['session_source']='settings';p['origins'].append('https://consent.example.test')
        before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone())
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            ident=prepare(self.state,'production-1','Propose saved browser setup and consent origin recovery.',policies)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        self.assertEqual(row['status'],'ready');self.assertIsNone(row['run'])
        proposal=json.loads(row['plan'])
        self.assertTrue(all(t['browser']==policies[t['id']] for t in proposal['tasks']))
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()),before)
        self.assertEqual(len(self.factory.calls),1)
        with self.state.db,self.assertRaisesRegex(ValueError,'already exists'):
            self.state.db.execute('BEGIN IMMEDIATE')
            prepare(self.state,'production-1','Repeat repair',policies)
        with self.state.db:
            receipt=json.loads(before['receipt']);receipt['browser']['actions'][0]['status']='uncertain'
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),aid))
        with self.assertRaisesRegex(ValueError,'read-only observed'):
            stages.verify(self.state,self.rt,json.loads(row['context']),ident,'telegram')

    def test_repair_cannot_expand_actions_or_capture_grants(self):
        old,aid=self.stopped()
        policies={t['id']:copy.deepcopy(t['browser']) for t in json.loads(old['result'])['plan']['tasks']}
        policies['produce']['interaction_scope']='Submit a form'
        with self.state.db,self.assertRaisesRegex(ValueError,'only profile, session source and exact origins'):
            self.state.db.execute('BEGIN IMMEDIATE')
            prepare(self.state,'production-1','Setup repair',policies)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_stage_links').fetchone()[0],0)
