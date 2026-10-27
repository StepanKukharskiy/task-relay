"""Real model loop and durable controller, scripted transport; no live calls."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import contracts as c,executors
from orchestrator.gemini_worker import execute
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from orchestrator.workers import atomic
from task_relay import completion_recovery as recovery,local_review
from tests import test_review_budget_recovery as fixture
from tests.test_orchestrator import pair

CONFIG={'api_key':'fixture-only','models':{'text':'fixture'}}


class Script:
    def __init__(self,steps):self.steps=iter(steps);self.requests=[]
    def request(self,_endpoint,payload,**_):
        self.requests.append(copy.deepcopy(payload));step=next(self.steps)
        if isinstance(step,dict):return step
        name,args=step
        return dict(candidates=[dict(finishReason='STOP',content=dict(role='model',parts=[dict(functionCall=dict(name=name,args=args))]))])


def final(evidence='Candidate has the requested exact text',**changes):
    return ('finish',dict(report_json=c.encoded(dict(summary='Inspected candidate',decision='accept',instruction='',findings=[],checks={'c1':dict(passed=True,evidence=evidence)},**changes))))


class Tests(unittest.TestCase):
    def fixture(self,max_attempts=2):
        f=fixture.Tests();f.setUp();self.addCleanup(f.tearDown)
        p,s=f.prepare();graph=pair(max_attempts=max_attempts);graph['id']='parent';graph['backend']=dict(type='gemini-agent',model='fixture')
        for t in graph['tasks']:t.update(tools=['files'],limits=dict(seconds=600,tool_calls=3,provider_requests=3,output_bytes=200000))
        f.rt.create(graph);f.rt.tick('parent');producer=f.rt.task('parent','produce')['latest']
        # Producer also uses the actual worker protocol.
        self.run_worker(f,producer,Script([('file_write',dict(path='output.txt',text='Exact candidate text.')),('finish',dict(report_json=c.encoded(dict(summary='Wrote candidate',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='output.txt contains exact requested text')}))))]))
        f.rt.tick('parent');aid=f.rt.task('parent','review')['latest']
        with transaction(f.state.db):f.state.db.execute('UPDATE completion_recovery_grants SET policy=? WHERE pipeline=?',(c.encoded(recovery.DELIVERY_POLICY),p['id']))
        return f,p,s,producer,aid

    def run_worker(self,f,aid,client):
        session=f.factory.sessions[aid];frozen=session['frozen'];control=f.rt.root/'workers'/aid
        control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,frozen['backend'])))
        try:
            with patch('orchestrator.gemini_worker.emit'):result=execute(frozen,control,client,lambda:(CONFIG,frozen['backend']))
            code=0;reason=None
        except ValueError as exc:result=None;code=1;reason=str(exc)
        session['status']=dict(status='finished',token=aid,exit_code=code,reason=reason,external_outcome='no_pending_response',pending_requests=[],api_requests=len(list(control.glob('api-*.request.json'))),tool_calls=len(list(control.glob('tool-*.json'))))
        return result,control

    def stopped(self,max_attempts=2):
        f,p,s,producer,aid=self.fixture(max_attempts)
        script=Script([('report_check',dict(check='c1',value_json=c.encoded(dict(passed=True,evidence='Provisional exact text')))),('finish',dict(report_json='{"decision":')),('finish',dict(report_json='{}'))])
        result,control=self.run_worker(f,aid,script);self.assertIsNone(result)
        self.assertFalse((f.factory.sessions[aid]['workspace']/'.relay/result.json').exists())
        self.assertFalse((f.factory.sessions[aid]['workspace']/'review.md').exists())
        f.rt.tick('parent');return f,p,s,producer,aid,control

    def test_yield_restart_amended_finalization_retains_candidate_without_replanning(self):
        f,p,s,producer,aid,control=self.stopped()
        prior=dict(f.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone())
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        calls=list(f.factory.calls)
        f.rt=Runtime(f.rt.root,f.factory,connection=f.state.db)
        self.assertEqual(f.factory.calls,calls) # dispatch happens after commit
        f.rt.tick('parent');new=f.rt.task('parent','review')['latest'];self.assertNotEqual(new,aid)
        script=Script([final('Refined final evidence: the exact candidate text is present.')])
        result,_=self.run_worker(f,new,script);self.assertEqual(result['decision'],'accept')
        initial=json.loads(script.requests[0]['contents'][0]['parts'][0]['text'])
        self.assertEqual(initial['review_session']['remaining'],[])
        self.assertIn('Provisional',initial['review_session']['provisional_checks']['c1']['evidence'])
        f.rt.tick('parent');self.assertEqual(f.rt.status('parent')['status'],'completed')
        self.assertEqual(prior,dict(f.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()))
        self.assertEqual(f.rt.task('parent','produce')['latest'],producer)
        self.assertEqual(f.rt.task('parent','produce')['attempts'],1)
        self.assertEqual(f.rt.task('parent','review')['attempts'],2)
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)

    def test_changed_checkpoint_after_commit_holds_without_dispatch(self):
        f,p,s,producer,aid,control=self.stopped()
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        checkpoint=json.loads((control/'review-session.json').read_text());checkpoint['checks']['c1']['evidence']='Altered after commit'
        atomic(control/'review-session.json',checkpoint);calls=list(f.factory.calls)
        f.rt.tick('parent');self.assertEqual(f.factory.calls,calls);self.assertEqual(f.rt.task('parent','review')['status'],'blocked')

    def test_unknown_response_and_exhausted_attempts_are_not_retry_permission(self):
        f,p,s,producer,aid,control=self.stopped();task=f.rt.task('parent','review');attempt=f.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()
        self.assertIsNotNone(local_review.proof(f.rt,task,attempt))
        self.assertTrue(local_review.proof(f.rt,dict(task,attempts=2),attempt)['requires_cycle_attempt'])
        with self.assertRaisesRegex(ValueError,'grant'):local_review.allocation(f.rt,task,{},dict(version=0))
        (control/'api-03.response.json').unlink()
        self.assertIsNone(local_review.proof(f.rt,task,attempt))

    def test_invalid_received_envelope_repairs_locally_before_final_report(self):
        f,p,s,producer,aid=self.fixture()
        script=Script([dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text='Non-executable answer')]))]),final()])
        result,control=self.run_worker(f,aid,script);self.assertEqual(result['decision'],'accept')
        self.assertEqual(len(list(control.glob('tool-*.json'))),1)
        self.assertEqual(json.loads((control/'api-01.validation.json').read_text())['code'],'invalid_received_envelope')

    def test_invalid_final_replacement_cannot_publish_partial_acceptance(self):
        f,p,s,producer,aid=self.fixture()
        script=Script([('report_check',dict(check='c1',value_json=c.encoded(dict(passed=True,evidence='Provisional')))),('finish',dict(report_json=c.encoded(dict(summary='Invalid',decision='accept',instruction='',findings=[],checks={'c1':dict(passed='yes',evidence='Invalid type')})))),final('Correct final evidence')])
        result,control=self.run_worker(f,aid,script);self.assertEqual(result['decision'],'accept')
        self.assertIn('error',json.loads((control/'tool-02-00.json').read_text())['result'])
        self.assertEqual(json.loads((control/'report-checks.json').read_text())['checks']['c1']['evidence'],'Provisional')

    def test_failed_replan_can_spend_its_unused_worker_allocation_once(self):
        f,p,s,producer,aid,control=self.stopped(max_attempts=1)
        baseline=recovery.snapshot(f.state,'parent',photo_recovery=True)
        self.assertTrue(baseline['gaps'][0]['requires_cycle_attempt'])
        baseline['gaps']=[dict(kind='split_budget',task='review',attempt=aid,instruction='Historical generic budget stop')]
        from tests import test_production_planning as planning_fixture
        row=planning_fixture.Tests.queue(f,99);context=json.loads(row['context'])
        context['completion_recovery']=recovery.planner_context(dict(parent='parent',cycle=1,policy=recovery.DELIVERY_POLICY,authorization='complete delivery',baseline=baseline))
        with transaction(f.state.db):
            f.state.db.execute("UPDATE production_plans SET context=?,context_hash=?,status='blocked',calls=2,error='Incomplete JSON' WHERE id=?",(c.encoded(context),c.digest(context),row['id']))
            for number in (1,2):f.state.db.execute('INSERT INTO production_plan_calls(plan_id,number,request,response,usage,error,created) VALUES(?,?,?,?,?,?,?)',(row['id'],number,'{}','{"plan":','{"totalTokens":20}','Incomplete JSON',number))
            f.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',(p['id'],s['id'],'parent',1,row['request_id'],c.encoded(baseline)))
            f.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            f.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind='plan_production',target=? WHERE pipeline=? AND id=?",(row['id'],p['id'],s['id']))
        prior=dict(f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(row['id'],)).fetchone())
        recovery.reconcile_stranded_local_revision(f.state);recovery.reconcile_stranded_local_revision(f.state)
        self.assertEqual(f.rt.task('parent','review')['status'],'queued')
        self.assertEqual(f.rt.spec(f.rt.task('parent','review'))['max_attempts'],2)
        self.assertEqual(prior,dict(f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(row['id'],)).fetchone()))
        f.rt.tick('parent');new=f.rt.task('parent','review')['latest']
        result,_=self.run_worker(f,new,Script([final()]));self.assertEqual(result['decision'],'accept')
        f.rt.tick('parent');self.assertEqual(f.rt.status('parent')['status'],'completed')
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
        self.assertEqual(f.rt.task('parent','produce')['latest'],producer)
