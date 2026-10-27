"""Shared lifecycle qualification with small text and scripted local peers."""
import json,unittest
from unittest.mock import patch
from pathlib import Path
from orchestrator import owner_intents,contracts as c
from orchestrator.runtime import Runtime
from orchestrator.owner_compilation import label
from tests import test_owner_compilation as fixture
from tests import test_owner_intents as intents_fixture
from tests import test_owner_parallel_progress as parallel
from tests import test_review_followup as followup


class Reviews(unittest.TestCase):
    create=fixture.Tests.create
    source=fixture.Tests.source
    session=fixture.Tests.session
    invoke=fixture.Tests.invoke
    run_worker=fixture.Tests.run_worker
    finish=followup.Tests.finish
    def setUp(self):
        fixture.Tests.setUp(self)
        self.grant.update(review_snapshot_version=1,max_tasks=20,owner_turns=10)

    def candidate(self):
        self.create();self.rt.tick('job')
        self.invoke([('job_delegate',dict(request_id='first',tasks=[intents_fixture.worker('write')]))])
        self.run_worker('write',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Saved exact candidate.'))])
        self.run_worker(label('write','review'),lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Inspected.'))],decision='accept')
        return self.rt.output('job','write','outputs/result.txt')

    def proposal(self):
        return dict(request_id='final',tasks=[dict(id='final',objective='Independent final assessment of exact files',review_of='write')])

    def test_completed_review_admission_restart_idempotency_and_exact_final_delivery(self):
        artifact=self.candidate();session=self.session();args=self.proposal()
        receipt=session.delegate(args);self.assertEqual(receipt,session.delegate(args))
        self.assertEqual(receipt['queued'],['final'])
        target=dict(self.rt.task('job','write'));self.rt.close();self.rt=Runtime(self.root,self.factory)
        f,_=self.run_worker('final',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=1000)) for i in f['inputs']]+[('file_write',dict(path=f['outputs'][0]['path'],text='Exact candidate accepted.'))],decision='accept')
        self.assertEqual(dict(self.rt.task('job','write')),target)
        self.assertEqual(self.rt.reviewer('job','write')['id'],label('write','review'))
        self.assertEqual(f['review_snapshot']['attempts']['write'],artifact['attempt'])
        owner=self.session();result=owner.complete(dict(deliverables_json=json.dumps(dict(report=artifact['id'])),summary='Exact reviewed file'))
        self.assertIn(self.rt.task('job','final')['latest'],result['deliverables']['report']['reviews'])
        self.assertEqual(len(self.factory.calls),len(set(self.factory.calls)))

    def test_snapshot_rejection_preserves_original_and_prevents_old_acceptance_reuse(self):
        artifact=self.candidate();self.session().delegate(self.proposal());target=dict(self.rt.task('job','write'))
        self.finish('final','Required correction remains.',decision='revise',defect='Missing required field')
        self.assertEqual(dict(self.rt.task('job','write')),target)
        self.assertEqual(Path(artifact['blob']).read_text(),'Saved exact candidate.')
        with self.assertRaisesRegex(ValueError,'independent review|outstanding finding'):
            self.session().complete(dict(deliverables_json=json.dumps(dict(report=artifact['id'])),summary='Cannot reuse earlier approval'))

    def test_stale_snapshot_blocks_before_dispatch_without_replay(self):
        self.candidate();self.session().delegate(self.proposal());calls=list(self.factory.calls)
        with self.rt.transaction():self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='job' AND id='write'")
        self.rt.tick('job');self.assertEqual(self.rt.task('job','final')['status'],'blocked')
        self.assertEqual(self.factory.calls,calls)

    def test_correction_restart_combined_snapshot_retains_exact_earlier_evidence(self):
        old=self.candidate();self.session().delegate(self.proposal())
        self.finish('final','Missing field.',decision='revise',defect='Missing required field')
        self.invoke([('job_delegate',dict(request_id='repair',tasks=[
            intents_fixture.worker('fixed',[dict(artifact=old['id'])])]))])
        self.finish('fixed','Saved exact candidate with required field.')
        self.finish(label('fixed','review'),'Repair independently verified.',decision='accept')
        fixed=self.rt.output('job','fixed','outputs/result.txt')
        args=dict(request_id='combined',tasks=[dict(id='combined',objective='Inspect new candidate and exact earlier evidence',review_of='fixed',inputs=[dict(artifact=old['id'])])])
        self.session().delegate(args)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        f,_=self.finish('combined','Combined independent final review.',decision='accept')
        self.assertIn(old['id'],[i['artifact'] for i in f['inputs']])
        self.assertIn(fixed['id'],[i['artifact'] for i in f['inputs']])
        self.assertEqual(Path(old['blob']).read_text(),'Saved exact candidate.')
        self.invoke([('job_complete',dict(deliverables_json=json.dumps(dict(report=fixed['id'])),summary='Corrected exact candidate reviewed'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed')

    def test_one_snapshot_independently_covers_two_exact_completed_deliverables(self):
        self.grant['deliverables']=dict(first='text/plain',second='text/plain')
        first=self.candidate()
        self.invoke([('job_delegate',dict(request_id='second',tasks=[intents_fixture.worker('second')]))])
        self.finish('second','Independent second deliverable.')
        self.finish(label('second','review'),'Second checked.',decision='accept')
        second=self.rt.output('job','second','outputs/result.txt')
        args=self.proposal();args['tasks'][0]['inputs']=[dict(artifact=second['id'])]
        self.session().delegate(args)
        self.finish('final','Both exact files assessed together.',decision='accept')
        result=self.session().complete(dict(deliverables_json=json.dumps(dict(first=first['id'],second=second['id'])),summary='Both exact deliverables'))
        common=set(result['deliverables']['first']['reviews']) & set(result['deliverables']['second']['reviews'])
        self.assertEqual(common,{self.rt.task('job','final')['latest']})

    def test_snapshot_uncertainty_is_retained_once_without_recollection(self):
        self.candidate();self.session().delegate(self.proposal());self.rt.tick('job')
        aid=self.rt.task('job','final')['latest'];self.factory.finish(aid,decision='accept')
        path=Path(self.factory.sessions[aid]['frozen']['workspace'])/'.relay/result.json'
        report=json.loads(path.read_text());report['findings']=[dict(category='uncertainty',code='unconfirmed',message='Evidence outcome unknown',evidence='Missing correlated receipt')]
        path.write_text(json.dumps(report));self.rt.tick('job')
        self.assertEqual(self.rt.task('job','final')['status'],'uncertain')
        count=self.rt.db.execute("SELECT count(*) FROM production_events WHERE attempt=? AND kind='checks_recorded'",(aid,)).fetchone()[0]
        calls=list(self.factory.calls)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.rt.tick('job');self.rt.tick('job')
        self.assertEqual(count,self.rt.db.execute("SELECT count(*) FROM production_events WHERE attempt=? AND kind='checks_recorded'",(aid,)).fetchone()[0])
        self.assertEqual(calls,self.factory.calls)
        self.assertEqual(self.rt.task('job','write')['status'],'completed')

    def test_running_target_rejection_and_invalid_outputs_are_actionable_atomic(self):
        self.create();self.rt.tick('job');self.session().delegate(dict(request_id='first',tasks=[intents_fixture.worker('write')]))
        before=len(self.rt.status('job')['tasks'])
        with self.assertRaisesRegex(ValueError,'Wait for its existing review'):
            owner_intents.compile(self.session(),self.proposal())
        self.assertEqual(len(self.rt.status('job')['tasks']),before)
        for outputs in ({'assessment':'text/markdown'},[dict(name='assessment',format='text/markdown')]):
            with self.assertRaisesRegex(ValueError,'name,media_type,purpose'):
                owner_intents.validate_delegation(dict(request_id='bad',tasks=[dict(id='assessment',objective='Assess',outputs=outputs)]),4)


class Settlement(unittest.TestCase):
    create=parallel.Tests.create
    start=parallel.Tests.start
    invoke=parallel.Tests.invoke
    delegate=parallel.Tests.delegate
    batch=parallel.Tests.batch
    def setUp(self):parallel.Tests.setUp(self)

    def test_owner_stop_drains_late_results_across_restart_without_dispatch(self):
        self.start();calls=list(self.factory.calls)
        with self.rt.transaction():self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='job' AND id='owner'")
        status=self.rt.status('job');self.assertEqual(status['status'],'active')
        self.assertEqual(status['settlement']['terminal_outcome'],'blocked')
        self.assertFalse(status['settlement']['dispatch_allowed'])
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        for name in ('fast','slow'):
            self.factory.finish(self.rt.task('job',name)['latest']);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'blocked')
        self.assertEqual(self.factory.calls,calls)
        for name in ('fast','slow'):
            self.assertIsNotNone(self.rt.output('job',name,'report.txt'))
            self.assertIsNone(self.rt.task('job',name+'_review')['latest'])
        count=self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='checks_recorded'").fetchone()[0]
        self.rt.tick('job');self.assertEqual(count,self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='checks_recorded'").fetchone()[0])

    def test_unknown_terminal_is_preserved_without_duplicate_dispatch(self):
        self.start();calls=list(self.factory.calls)
        with self.rt.transaction():self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='job' AND id='owner'")
        aid=self.rt.task('job','slow')['latest'];self.factory.sessions[aid]['status']=dict(status='uncertain',reason='No correlated terminal receipt')
        self.rt.tick('job');self.assertEqual(self.rt.status('job')['status'],'active')
        self.assertEqual(self.rt.task('job','slow')['status'],'uncertain')
        self.factory.finish(self.rt.task('job','fast')['latest'])
        self.rt.tick('job');self.assertEqual(self.rt.status('job')['status'],'uncertain')
        self.assertEqual(self.factory.calls,calls)
        self.assertIsNotNone(self.rt.output('job','fast','report.txt'))

    def test_already_dispatched_review_is_collected_after_owner_failure(self):
        self.start();self.factory.finish(self.rt.task('job','fast')['latest']);self.rt.tick('job')
        review=self.rt.task('job','fast_review')['latest'];self.assertIsNotNone(review)
        calls=list(self.factory.calls)
        with self.rt.transaction():self.rt.db.execute("UPDATE production_tasks SET status='blocked' WHERE run='job' AND id='owner'")
        self.factory.finish(review,decision='accept');self.rt.tick('job')
        self.assertEqual(self.rt.task('job','fast')['status'],'completed')
        self.assertEqual(self.rt.task('job','fast_review')['status'],'completed')
        self.assertEqual(self.rt.status('job')['status'],'active')
        self.factory.finish(self.rt.task('job','slow')['latest']);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'blocked')
        self.assertEqual(calls,self.factory.calls)

