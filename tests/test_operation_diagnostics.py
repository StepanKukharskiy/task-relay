"""Synthetic failed operations through real worker, collection and handoff boundaries."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import worker_tools, operation_diagnostics as diagnostics, contracts as c
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from tests.test_operation_session import Script, CONFIG
from tests import test_worker_tools as work_fixture


class Tests(unittest.TestCase):
    def setUp(self):
        work_fixture.Tests.setUp(self)
        self.grant['work_diagnostics_version']=1
    create=work_fixture.Tests.create
    source=work_fixture.Tests.source
    session=work_fixture.Tests.session
    invoke=work_fixture.Tests.invoke
    admit=work_fixture.Tests.admit
    text_work=work_fixture.Tests.text_work
    report=work_fixture.Tests.report

    def fail(self,sub,folder,*args):
        path=Path(sub['workspace'])/sub['outputs'][0]['path']
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('partial fixture; not a delivered document')
        receipt=dict(outcome='failed',effect='confirmed',summary='Validation mismatch at item 7',
                     execution=sub['execution'])
        atomic(folder/'operation.json',receipt)
        (folder/'runtime.log').write_text('Exact fixture diagnostic: expected seven points; received six.')
        return receipt

    def test_failed_worker_can_read_receipt_then_retry_without_accepting_partial(self):
        f,control,_=self.text_work();original=worker_tools.execute_local;calls=[]
        def run(sub,folder,*args):
            calls.append(folder)
            return self.fail(sub,folder,*args) if len(calls)==1 else original(sub,folder,*args)
        steps=[('work_run',dict(step='build',request_key='first')),
               ('file_read',dict(path=diagnostics.OUTPUT['path'],offset=0,limit=24000)),
               ('artifact_inspect',dict(path='outputs/work-build/result.txt')),
               ('work_run',dict(step='build',request_key='corrected')),self.report(f)]
        with patch.object(worker_tools,'execute_local',side_effect=run):
            execute(f,control,Script(steps),lambda:(CONFIG,f['backend']))
        first=json.loads((control/'tool-01-00.json').read_text())['result']
        self.assertIn('item 7',first['error']);self.assertEqual(first['diagnostics'],diagnostics.OUTPUT['path'])
        read=json.loads((control/'tool-02-00.json').read_text())['result']
        self.assertIn('expected seven points',read['text'])
        self.assertIn('error',json.loads((control/'tool-03-00.json').read_text())['result'])
        self.assertEqual(len(calls),2)
        proof=worker_tools.verify_delivery(f,control)
        self.assertEqual(proof['steps']['build']['version'],'0002')
        self.assertEqual(len(json.loads((Path(f['workspace'])/diagnostics.OUTPUT['path']).read_text())['failures']),1)

    def test_failure_commit_restart_and_recovery_handoff(self):
        f,control,state=self.text_work();publish=worker_tools.Session.publish_diagnostics
        def stop(session):
            if session.receipts:raise KeyboardInterrupt('after failed receipt commit')
            publish(session)
        with patch.object(worker_tools,'execute_local',side_effect=self.fail),patch.object(worker_tools.Session,'publish_diagnostics',stop):
            with self.assertRaises(KeyboardInterrupt):
                execute(f,control,Script([('work_run',dict(step='build',request_key='failed'))]),lambda:(CONFIG,f['backend']))
        before=(control/'work-operations/0001/outcome.json').read_bytes()
        name,args=self.report(f);report=json.loads(args['report_json']);report['decision']='blocked'
        for check in report['checks'].values():check['passed']=False
        with patch.object(worker_tools,'execute_local',side_effect=AssertionError('Failure cannot replay')):
            execute(f,control,Script([('file_read',dict(path=diagnostics.OUTPUT['path'],offset=0,limit=24000)),
                                    ('finish',dict(report_json=c.encoded(report)))]),lambda:(CONFIG,f['backend']))
        self.assertEqual(before,(control/'work-operations/0001/outcome.json').read_bytes())
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');self.assertEqual(self.rt.task('job','make')['status'],'blocked')
        artifact=self.rt.output('job','make',diagnostics.OUTPUT['path'])
        # The ordinary owner delegation can bind the diagnostic from a failed producer.
        owner=self.session()
        result=owner.delegate(dict(request_id='diagnose',tasks=[dict(id='diagnose',objective='Inspect exact failure, do not execute native work',
            inputs=[dict(artifact=artifact['id'])],outputs=[dict(name='report',media_type='text/plain',purpose='Failure explanation')])]))
        self.assertIn('diagnose',result['queued'])
        task=self.rt.spec(self.rt.task('job','diagnose'))
        self.assertIn(artifact['id'],[i['artifact'] for i in task['inputs']])
        self.assertFalse((Path(f['workspace'])/'outputs/work-build/result.txt').exists())
        self.rt.tick('job')
        worker=self.factory.sessions[self.rt.task('job','diagnose')['latest']]
        frozen=worker['frozen'];destination=Path(worker['session']['control']);destination.mkdir(parents=True,exist_ok=True)
        from orchestrator import executors
        atomic(destination/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,frozen['backend'])))
        evidence=next(i for i in frozen['inputs'] if i['artifact']==artifact['id'])
        execute(frozen,destination,Script([
            ('file_read',dict(path=evidence['path'],offset=0,limit=24000)),
            ('file_write',dict(path=frozen['outputs'][0]['path'],text='The retained fixture receipt reports a seven-versus-six point mismatch. No operation was retried.')),
            self.report(frozen)]),lambda:(CONFIG,frozen['backend']))
        read=json.loads((destination/'tool-01-00.json').read_text())['result']
        self.assertIn('expected seven points',read['text'])

    def test_diagnostics_are_immutable_and_do_not_grant_undeclared_files(self):
        f,control,_=self.text_work();files=worker_tools.files(f,control);session=worker_tools.Session(files,control)
        with patch.object(worker_tools,'execute_local',side_effect=self.fail):session.run(dict(step='build',request_key='fail'))
        with self.assertRaisesRegex(ValueError,'code owned'):files.call('file_write',dict(path=diagnostics.OUTPUT['path'],text='forged'))
        path=Path(f['workspace'])/diagnostics.OUTPUT['path'];path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'projection differs'):diagnostics.verify_projection(f,control)
        session.publish_diagnostics()
        (control/'work-operations/0001/runtime.log').write_text('altered')
        with self.assertRaisesRegex(ValueError,'evidence changed'):worker_tools.Session(worker_tools.files(f,control),control)

    def test_unknown_effect_still_holds_without_diagnostic_acceptance_or_replay(self):
        from orchestrator.runtime_outcomes import UncertainOperation
        f,control,_=self.text_work();session=worker_tools.Session(worker_tools.files(f,control),control)
        with patch.object(worker_tools,'execute_local',side_effect=UncertainOperation('no terminal receipt')):
            with self.assertRaises(UncertainOperation):session.run(dict(step='build',request_key='unknown'))
        self.assertFalse((control/'work-operations/0001/outcome.json').exists())
        self.assertEqual(json.loads((Path(f['workspace'])/diagnostics.OUTPUT['path']).read_text())['failures'],[])
        with patch.object(worker_tools,'execute_local',side_effect=AssertionError('no duplicate dispatch')):
            with self.assertRaises(UncertainOperation):worker_tools.Session(worker_tools.files(f,control),control)

    def test_capture_excludes_links_and_marks_binary_and_truncation(self):
        f,control,_=self.text_work();session=worker_tools.Session(worker_tools.files(f,control),control)
        with patch.object(worker_tools,'execute_local',side_effect=self.fail):session.run(dict(step='build',request_key='failed'))
        folder=control/'work-operations/0001';sub=json.loads((folder/'workspace/.relay/ASSIGNMENT.json').read_text())
        log=folder/'runtime.log';log.unlink();log.symlink_to(folder/'intent.json')
        path=folder/'workspace'/sub['outputs'][0]['path'];path.write_bytes(b'\x00\xffbinary')
        result=diagnostics.capture(folder,sub,{},'failure',10000)
        self.assertFalse(next(i for i in result['files'] if i['path']=='runtime.log')['available'])
        self.assertIn('identity-only',next(i for i in result['files'] if i['origin']=='workspace')['representation'])
        limited=diagnostics.capture(folder,sub,{},'failure',200)
        self.assertTrue(next(i for i in limited['files'] if i['path']=='operation.json')['truncated'])

    def test_historical_scope_does_not_gain_diagnostic_outputs(self):
        f,control,_=self.text_work();old=copy.deepcopy(f)
        old['work_tools'].pop('diagnostics');old['outputs'].remove(diagnostics.OUTPUT)
        old['artifact_roles']['results'].pop(diagnostics.OUTPUT['path'])
        worker_tools.validate_assignment(old)
        self.assertNotIn(diagnostics.OUTPUT['path'],worker_tools.owned(old))


if __name__=='__main__':unittest.main()
