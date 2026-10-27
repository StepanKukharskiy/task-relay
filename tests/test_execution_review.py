"""Shared execution review on both routes; real compiler/runner, scripted decisions."""
import json,unittest
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
from orchestrator import contracts as c,job_owner,step_runner
from orchestrator.runtime import Runtime
from orchestrator.owner_compilation import label
from tests import test_browser_fallback_lifecycle as fixture
retain_evidence=fixture.retain_evidence
from tests import test_owner_intents as owner
from tests.test_native_source_browser import Helper
from task_relay import source_native_browser as host

class Tests(unittest.TestCase):
    create=fixture.Tests.create;source=fixture.Tests.source;invoke=fixture.Tests.invoke
    session=fixture.Tests.session;run_worker=fixture.Tests.run_worker;begin=fixture.Tests.begin
    execute_operation=fixture.Tests.execute_operation;native_intent=fixture.Tests.native_intent
    tearDown=retain_evidence

    def setUp(self):
        fixture.Tests.setUp(self)
        self.grant.update(execution_review_version=1,worker_tools_version=3,review_snapshot_version=1)
        self.grant['task_limits'].update(provider_requests=20,tool_calls=24,output_bytes=1000000)

    def run_path(self,inline,both_deliverables=False):
        if both_deliverables:self.grant['deliverables']['sources']='application/json'
        artifact,prior=self.begin()
        if self.rt.task('job','isolated')['status']=='awaiting_review':
            self.run_worker(label('isolated','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        native=self.native_intent(artifact)
        if inline:
            native=dict(id='native',objective='Read only the missing source',work=dict(mode='execute',operation='web.sources.native',
                data=dict(artifact=artifact['id']),parameters=native['parameters']))
        self.invoke([('job_delegate',dict(request_id='fallback',tasks=[native,owner.worker('report',[dict(task='native',output='source-pack')])]))])
        real=host.render
        calls=[]
        def render(url,domains,root,**kwargs):
            calls.append(url)
            return real(url,domains,root,**kwargs,helper=Helper(root),lease_context=nullcontext,wait=lambda _:None)
        if inline:
            def local(sub,folder,*a,**kw):return step_runner.execute(sub,folder)
            with patch('orchestrator.worker_tools.execute_local',side_effect=local),patch.object(host,'render',side_effect=render):
                f,_=self.run_worker('native',lambda f:[('work_run',dict(step='build',request_key='read')),
                    ('work_evidence',dict(step='build')),
                    ('file_read',dict(path='outputs/work-build/source-pack.json',offset=0,limit=24000))])
            path='outputs/work-build/source-pack.json'
            self.assertNotIn('Inspect pixels\nin a subsequent response',f['instruction'])
        else:
            _,control=self.execute_operation('native',render,native=True)
            path='delivery/source-pack.json'
        if self.rt.task('job','native')['status']=='awaiting_review':
            self.run_worker(label('native','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        source=self.rt.output('job','native',path)
        doc=json.loads(Path(source['blob']).read_text())
        self.assertEqual(doc['entries'][:len(prior['entries'])],prior['entries'])
        self.assertEqual(doc['rendered_fallback']['reads'][:len(prior['rendered_fallback']['reads'])],prior['rendered_fallback']['reads'])
        self.assertEqual(len(calls),1)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        f,_=self.run_worker('report',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]+
            [('file_write',dict(path=f['outputs'][0]['path'],text='Exact product dimensions from native observations; retained earlier evidence.'))])
        evidence=[i for i in f['inputs'] if i['path'].startswith('execution-evidence/')]
        self.assertGreaterEqual(len(evidence),1)
        evidence.sort(key=lambda i:i['path'].endswith(self.rt.task('job','native')['latest']+'.json'),reverse=True)
        raw=(Path(f['workspace'])/evidence[0]['path']).read_bytes();capsule=json.loads(raw)
        self.assertEqual(capsule['admission'][0]['tasks'][0]['id'],'native')
        self.assertEqual(capsule['operations'][0]['execution']['capability'],'web.sources.native')
        self.assertTrue(capsule['operations'][0]['adapter_evidence'])
        judge,_=self.run_worker(label('report','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]+
            [('file_write',dict(path=f['outputs'][0]['path'],text='Exact report and native provenance independently checked.'))],decision='accept')
        self.assertTrue(any(i['path'].startswith('execution-evidence/') for i in judge['inputs']))
        report=self.rt.output('job','report','outputs/result.txt')
        deliverables=dict(report=report['id'])
        if both_deliverables:deliverables['sources']=source['id']
        self.invoke([('job_complete',dict(deliverables_json=c.encoded(deliverables),summary='Exact reviewed result'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed')
        self.assertEqual(len(calls),1)
        return f,evidence[0]

    def test_standalone_execution_review_restart_and_final_delivery(self):self.run_path(False)
    def test_inline_execution_review_restart_and_final_delivery(self):self.run_path(True)

    def test_tampered_original_operation_receipt_cannot_bind_review(self):
        f,_=self.run_path(False)
        state=self.factory.sessions[self.rt.task('job','native')['latest']]
        control=Path(state['session']['control']);p=control/'operation.json'
        value=json.loads(p.read_text());value['validation']['fetched']=999;p.write_text(json.dumps(value))
        from orchestrator.execution_evidence import capsule
        with self.assertRaisesRegex(ValueError,'materialization receipt'):capsule(state['frozen'],control)

    def test_owner_stop_terminates_without_another_provider_exchange(self):
        self.create();self.rt.tick('job')
        with self.assertRaisesRegex(ValueError,'Missing permission cannot be corrected'):
            self.invoke([('job_stop',dict(reason='Missing permission cannot be corrected inside this grant'))])
        events=self.rt.db.execute("SELECT data FROM production_events WHERE kind='owner_stop_requested'").fetchall()
        self.assertEqual(len(events),1)
        control=Path(self.factory.sessions[self.rt.task('job','owner')['latest']]['session']['control'])
        self.assertEqual(len(list(control.glob('api-*.request.json'))),1)
        self.assertEqual(json.loads((control/'execution-outcome.json').read_text())['code'],'owner_reported_blocker')

    def test_unchanged_failed_review_stops_but_new_evidence_is_allowed(self):
        ref=self.source();self.create(inputs=[ref]);self.rt.tick('job')
        self.invoke([('job_delegate',dict(request_id='report',tasks=[owner.worker('report',[dict(artifact=ref['artifact'])])]))])
        f,_=self.run_worker('report',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Exact substantive candidate needing review.'))])
        judge,_=self.run_worker(label('report','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='blocked')
        from orchestrator.review_recovery import check
        snapshot=dict(judge,review_snapshot=dict(version=1,attempts={}))
        with self.assertRaisesRegex(ValueError,'already received'):check(self.rt,'job',[snapshot])
        extra=self.source('New evidence resolves the blocked fact','new.txt')
        snapshot['inputs']=snapshot['inputs']+[extra]
        check(self.rt,'job',[snapshot])

    def test_repeated_completion_rejection_survives_owner_session_restart(self):
        self.create();self.rt.tick('job')
        for n in range(3):
            session=self.session()
            session.observe_outcome(dict(name='job_complete',arguments=dict(deliverables_json='{}',summary='Changed wording '+str(n)),result=dict(error='Missing required reviewed candidate')))
            if n<2:session.check_progress(1,1)
            else:
                with self.assertRaisesRegex(ValueError,'unchanged'):session.check_progress(1,1)
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='owner_completion_rejected'").fetchone()[0],3)

    def test_tampered_adapter_evidence_is_rejected_against_completion_binding(self):
        self.run_path(False)
        state=self.factory.sessions[self.rt.task('job','native')['latest']]
        control=Path(state['session']['control'])
        p=control/'render-1/fallback-read-intent.json';value=json.loads(p.read_text());value['reason']='altered after completion';p.write_text(json.dumps(value))
        from orchestrator.execution_evidence import capsule
        with self.assertRaisesRegex(ValueError,'materialization receipt'):capsule(state['frozen'],control)

    def test_standalone_two_deliverables_and_producer_gate(self):self.run_path(False,True)
    def test_inline_two_deliverables_and_producer_gate(self):self.run_path(True,True)

    def repeated_handoff(self,inline):
        import copy
        f,evidence=self.run_path(inline,True)
        spec=copy.deepcopy(f)
        # Another consumer inherits both the source and its already-bound receipt.
        for _ in range(2):
            resolved=self.rt.checked_inputs('job',spec,f['backend'])
            capsules=[i for i in resolved if i['path'].startswith('execution-evidence/')]
            self.assertEqual(len(capsules),len([i for i in f['inputs'] if i['path'].startswith('execution-evidence/')]))
            self.assertEqual(next(i['sha256'] for i in capsules if i['path']==evidence['path']),evidence['sha256'])
            spec['inputs']=[{k:v for k,v in i.items() if k not in ('blob','bytes')} for i in resolved]
        # Aliases identify the same immutable evidence, not another operation input.
        original=next(i for i in spec['inputs'] if i['path']==evidence['path'])
        original['path']='prior/retained-execution.json'
        resolved=self.rt.checked_inputs('job',spec,f['backend'])
        self.assertEqual(sum(i['sha256']==evidence['sha256'] for i in resolved),1)
        # A colliding name with different bytes is a terminal binding fault.
        forged=self.source('changed provenance','changed.json','application/json');forged['path']=evidence['path']
        spec['inputs']=[i for i in spec['inputs'] if i['path']!='prior/retained-execution.json']+[forged]
        from orchestrator.runtime_outcomes import Hold
        with self.assertRaises(Hold) as error:self.rt.checked_inputs('job',spec,f['backend'])
        self.assertEqual(error.exception.outcome['code'],'execution_evidence_conflict')

    def test_standalone_repeated_handoff_reuses_identity_and_rejects_conflicts(self):self.repeated_handoff(False)
    def test_inline_repeated_handoff_reuses_identity_and_rejects_conflicts(self):self.repeated_handoff(True)
