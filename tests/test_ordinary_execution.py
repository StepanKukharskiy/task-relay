"""Ordinary owner uses the existing queue and tools; fixtures never call a provider."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import job_owner,executors,contracts as c
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from tests import test_job_owner_loop as fixture
BACKEND=fixture.BACKEND
from tests.test_operation_session import CONFIG,Script
from task_relay import orchestrator_web as web,source_browser,persistent_jobs


class Ordinary(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.grant.update(delegation_version=4,execution_policy=dict(version=1,review='owner',public_read=True),execution_review_version=1)
        self.f.create();self.f.rt.tick('job')
        self.aid=self.f.rt.task('job','owner')['latest'];self.s=self.f.factory.sessions[self.aid]
        self.frozen=self.s['frozen'];self.control=Path(self.s['session']['control']);self.control.mkdir(parents=True,exist_ok=True)
        self.files=job_owner.files(self.frozen,self.control)
        self.owner=job_owner.Session(self.frozen,self.control,self.files);self.addCleanup(self.owner.rt.close)

    def save(self,text='A concise result.'):
        return self.owner.call('job_write',dict(deliverable='report',text=text))

    def inspect(self,v):return self.owner.call('job_read',dict(artifact=v['artifact']))

    def complete(self,v):return self.owner.complete(dict(deliverables_json=json.dumps({'report':v['artifact']}),summary='Completed the requested text.'))

    def test_saved_result_requires_exact_current_inspection_and_survives_restart(self):
        a=self.save()
        with self.assertRaisesRegex(ValueError,'Inspect'):self.complete(a)
        self.inspect(a);b=self.save('Corrected result.')
        with self.assertRaisesRegex(ValueError,'current saved'):self.complete(a)
        self.inspect(b);self.owner.rt.close()
        self.owner=job_owner.Session(self.frozen,self.control,self.files);self.addCleanup(self.owner.rt.close)
        result=self.complete(b)
        self.assertEqual(result['deliverables']['report']['review_status'],'owner_inspected')
        self.assertFalse(result['user_acceptance']);self.assertEqual(self.f.rt.status('job')['tasks'][0]['id'],'owner')
        self.assertEqual(len(self.f.rt.status('job')['tasks']),1)

    def test_explicit_review_remains_required(self):
        self.owner.grant['execution_policy']['review']='independent'
        a=self.save();self.inspect(a)
        with self.assertRaisesRegex(ValueError,'independent review'):self.complete(a)

    def test_actual_common_model_loop_writes_inspects_and_delivers_without_review_task(self):
        atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        rt=self.f.rt
        class Decisions(Script):
            def request(inner,endpoint,payload,**kw):
                n=len(inner.requests)
                if n==0:step=('job_write',dict(deliverable='report',text='Exact requested answer.'))
                else:
                    row=rt.db.execute("SELECT data FROM production_events WHERE run='job' AND kind='owner_result_saved' ORDER BY id DESC LIMIT 1").fetchone();a=json.loads(row[0])['artifact']
                    step=('job_read',dict(artifact=a)) if n==1 else ('job_complete',dict(deliverables_json=json.dumps({'report':a}),summary='Exact requested answer.'))
                inner.steps=iter([step]);return super().request(endpoint,payload,**kw)
        client=Decisions([]);result=execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.requests),3)
        self.s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.f.rt.tick('job');self.assertEqual(self.f.rt.status('job')['status'],'completed')
        self.assertEqual(len(self.f.factory.calls),1)
        self.assertNotIn('independent review receipts',result['checks'][0]['evidence'])

    def test_identical_save_reuses_artifact_and_versioned_path(self):
        a=self.save();b=self.save()
        self.assertEqual(a,b)
        self.assertEqual(self.owner.rt.artifact(a['artifact'])['path'],'deliverables/report.txt')
        self.assertEqual(self.owner.rt.db.execute("SELECT count(*) FROM production_events WHERE run='job' AND kind='owner_result_saved'").fetchone()[0],1)

    def test_saved_result_remains_partial_when_owner_stops(self):
        a=self.save('Useful partial answer.')
        self.s['status']=dict(status='finished',exit_code=1,reason='Source unavailable',external_outcome='no_pending_response',pending_requests=[])
        self.f.rt.tick('job');status=self.f.rt.status('job')
        self.assertEqual(status['status'],'blocked')
        self.assertEqual(status['delivery']['candidates'][0]['artifact'],a['artifact'])
        self.assertEqual(status['delivery']['candidates'][0]['review_status'],'unreviewed')
        self.assertFalse(status['delivery']['user_acceptance'])

    def test_pending_read_prevents_delivery_even_after_saved_result_inspection(self):
        a=self.save();self.inspect(a)
        pending=self.owner.web.root/'pending';pending.mkdir(parents=True)
        (pending/'http-claim.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unresolved public read'):self.complete(a)

    def test_actual_loop_reads_fallback_source_and_returns_text_without_delegation(self):
        atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        rt=self.f.rt
        class Decisions(Script):
            def request(inner,endpoint,payload,**kw):
                n=len(inner.requests)
                if n==0:step=('web_fetch',dict(url='https://example.com/article',offset=0,limit=1000))
                elif n==1:step=('job_write',dict(deliverable='report',text='The article describes three approaches.'))
                else:
                    row=rt.db.execute("SELECT data FROM production_events WHERE run='job' AND kind='owner_result_saved' ORDER BY id DESC LIMIT 1").fetchone();a=json.loads(row[0])['artifact']
                    step=('job_read',dict(artifact=a)) if n==2 else ('job_complete',dict(deliverables_json=json.dumps({'report':a}),summary='Article summarized.'))
                inner.steps=iter([step]);return super().request(endpoint,payload,**kw)
        def render(url,domains,control,**kw):
            control.mkdir(parents=True,exist_ok=True);text='This article describes three approaches.'
            (control/'rendered-text.txt').write_text(text)
            return dict(url=url,title='Article',text=text,sha256='fixture',retrieval_status='captured')
        client=Decisions([])
        with patch.object(source_browser,'read_http',side_effect=ValueError('403')),patch.object(source_browser,'render',side_effect=render):
            result=execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(client.requests),4)
        self.assertIn('three approaches',json.dumps(client.requests[1]))
        self.assertEqual(len(self.f.factory.calls),1)

    def test_frozen_procedural_checks_are_enforced_by_existing_output_checker(self):
        self.owner.grant['execution_policy']['request_contract']=dict(mode='new_work',reason='Requested code example',outcomes=[dict(id='report',kind='file',description='Code example',count=1,format='.txt',checks=['fenced_code'],validation=[])])
        a=self.save('No code');self.inspect(a)
        with self.assertRaisesRegex(ValueError,'code example'):self.complete(a)
        b=self.save('```python\nprint(1)\n```');self.inspect(b);self.complete(b)

    def test_historical_grant_has_no_new_tools(self):
        old=copy.deepcopy(self.owner.grant);old.pop('execution_policy')
        self.assertNotIn('job_write',[t['name'] for t in job_owner.definitions(old)])
        self.assertNotIn('web_fetch',[t['name'] for t in job_owner.definitions(old)])
        self.assertTrue(job_owner.independent(old))


class Reads(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.receipt=self.root/'reads.json';self.url='https://example.com/article'
    def session(self):return web.Session(self.receipt,durable=True,rendered=True)
    def fetch(self,s=None):return (s or self.session()).execute(dict(name='web_fetch',arguments=json.dumps(dict(url=self.url,offset=0,limit=100))))
    def render(self,url,domains,control,**kw):
        control.mkdir(parents=True,exist_ok=True);(control/'rendered-text.txt').write_text('Actual article. '*20)
        return dict(url=url,title='An article',text='Actual article. '*20,sha256='fixture',retrieval_status='captured')
    def test_direct_first_rendered_fallback_restart_reuses_success_and_failed_method(self):
        with patch.object(source_browser,'read_http',side_effect=ValueError('HTTP 403')) as h,patch.object(source_browser,'render',side_effect=self.render) as r:
            a=self.fetch();b=self.fetch()
            self.assertTrue(a['ok']);self.assertEqual(a,b);self.assertEqual(h.call_count,1);self.assertEqual(r.call_count,1)
            self.assertEqual(a['failed_methods'][0]['method'],'http')
    def test_pending_read_never_replayed_or_fallback(self):
        from orchestrator.runtime_outcomes import UncertainOperation
        with patch.object(source_browser,'read_http',side_effect=UncertainOperation('missing terminal')) as h,patch.object(source_browser,'render') as r:
            a=self.fetch();b=self.fetch()
            self.assertEqual(a['outcome'],'uncertain');self.assertEqual(b['outcome'],'uncertain');self.assertEqual(h.call_count,1);r.assert_not_called()
    def test_failed_acquisition_returns_to_owner_and_original_cap_survives_restart(self):
        with patch.object(source_browser,'read_http',side_effect=ValueError('403')) as h,patch.object(source_browser,'render',side_effect=ValueError('blocked')) as r:
            for n in range(4):
                self.url='https://example.com/'+str(n);value=self.fetch()
            self.assertEqual(value['outcome'],'exhausted');self.assertEqual(h.call_count+r.call_count,6)
    def test_changed_saved_content_never_refetched(self):
        with patch.object(source_browser,'read_http',side_effect=ValueError('403')),patch.object(source_browser,'render',side_effect=self.render) as r:
            self.assertTrue(self.fetch()['ok'])
            next(self.root.rglob('rendered-text.txt')).write_text('changed')
            self.assertFalse(self.fetch()['ok']);self.assertEqual(r.call_count,1)


class Admission(unittest.TestCase):
    def test_request_outcomes_bound_without_planner_and_no_paid_fallback(self):
        contract=dict(mode='new_work',reason='Requested text result',outcomes=[dict(id='answer',kind='result',description='Summary',count=1,format='',checks=[],validation=[])])
        backend=dict(type='codex-agent',model='gpt-6.1-sol',reasoning='high',budget_semantics='cli-exchanges-v1')
        p=persistent_jobs.ordinary_proposal('test','Exact request',contract,backend,[])
        self.assertEqual(p['request'],'Exact request');self.assertEqual(p['grant']['deliverables'],{'answer':'text/markdown'})
        self.assertEqual(p['grant']['operations'],[])
        with self.assertRaisesRegex(ValueError,'no paid fallback'):persistent_jobs.ordinary_proposal('test','Exact',contract,dict(type='openai-agent'),[])
        contract['outcomes'][0].update(kind='file',format='.pptx')
        with self.assertRaisesRegex(ValueError,'format tool'):persistent_jobs.ordinary_proposal('test','Exact',contract,backend,[])

class ServiceAdmission(unittest.TestCase):
    def test_existing_dispatch_admits_once_without_plan_or_start_card(self):
        from task_relay import capabilities as caps
        from tests import test_capabilities as f
        helper=f.Tests();helper.setUp();self.addCleanup(helper.tearDown)
        helper.job['prompt']='Summarize this public article.'
        backend=dict(type='codex-agent',model='gpt-6.1-sol',reasoning='high',budget_semantics='cli-exchanges-v1')
        contract=dict(mode='new_work',reason='Requested summary',outcomes=[dict(id='answer',kind='result',description='Article summary',count=1,format='',checks=[],validation=[])])
        snap=helper.snapshot();snap['capabilities']['ordinary_execution']=dict(available=True,backend=backend);snap['request_contract']=contract
        action=dict(kind='execute_work',public_read=True,review='owner',artifact_ids=[])
        with patch.object(executors,'catalog',return_value=[dict(id='codex-agent',available=True,backend=backend)]):
            a=helper.dispatch(action,snap);b=helper.dispatch(action,snap)
        self.assertEqual(a,b)
        db=helper.state.db
        self.assertEqual(db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        plan=json.loads(db.execute('SELECT plan FROM production_runs').fetchone()[0])
        self.assertEqual(plan['brief'],helper.job['prompt'])
        self.assertEqual(len(plan['tasks']),1)
        self.assertEqual(plan['job_owner']['execution_policy']['review'],'owner')
        snap['pipeline_step']={'id':'existing'}
        with self.assertRaisesRegex(ValueError,'frozen'):persistent_jobs.validate_action(action,snap)

    def test_completed_owner_delivers_actual_text_through_existing_export(self):
        from tests import test_capabilities as f
        from task_relay import production_control as pc,result_handoff
        from tests.test_orchestrator import FakeFactory
        from orchestrator.runtime import Runtime
        helper=f.Tests();helper.setUp();self.addCleanup(helper.tearDown)
        backend=dict(type='codex-agent',model='gpt-6.1-sol',reasoning='high',budget_semantics='cli-exchanges-v1')
        contract=dict(mode='new_work',reason='Requested summary',outcomes=[dict(id='answer',kind='result',description='Summary',count=1,format='',checks=[],validation=[])])
        proposal=persistent_jobs.ordinary_proposal('ordinary-export','Summarize the supplied text',contract,backend,[])
        persistent_jobs.start(helper.state,proposal,channel='telegram')
        factory=FakeFactory();rt=Runtime(pc.root(helper.state),factory,connection=helper.state.db);rt.tick('ordinary-export')
        aid=rt.task('ordinary-export','owner')['latest'];session=factory.sessions[aid];control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
        frozen=session['frozen'];atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,backend)))
        class Decisions(Script):
            def request(inner,endpoint,payload,**kw):
                n=len(inner.requests);step=('node_result',dict(outputs={'answer':{'text':'Exact ordinary summary.'}},summary='Done.'))
                inner.requests.append(copy.deepcopy(payload));return dict(choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content=None,tool_calls=[dict(id='call-'+str(n),type='function',function=dict(name=step[0],arguments=json.dumps(step[1])))]))])
        execute(frozen,control,Decisions([]),lambda:(CONFIG,backend))
        session['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        rt.tick('ordinary-export');self.assertEqual(rt.status('ordinary-export')['status'],'completed')
        result_handoff.sync(helper.state,'ordinary-export')
        text=result_handoff.saved_text(helper.state,'ordinary-export')
        self.assertIn('Exact ordinary summary.',text);self.assertIn('unreviewed',text)
        self.assertNotIn('job-result.json',text)
