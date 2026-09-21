"""Confirmed native verification failures produce proposals, never blind replay."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from orchestrator.step_runner import execute
from orchestrator.storage import transaction
from task_relay import production_control as pc, production_planning as planning
from task_relay import production_continuations as continuations, production_review_corrections as correction
from tests import test_rhino_launch_recovery as fixture


class Tests(unittest.TestCase):
    for name in ('setUp','tearDown','request','action','queue','row','response','setup_plan','delivered'):
        locals()[name]=getattr(fixture.Tests,name)

    def failed(self, uncertain=False):
        row=self.setup_plan()
        with transaction(self.state.db):
            self.delivered(row);planning.apply(self.state,row['token'],'start')
        run=self.row()['run'];worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        session=self.factory.sessions[self.rt.task(run,'app')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        def native(*args):
            request=json.loads(Path(args[2]).read_text());out=Path(request['out'])
            if request['mode']=='before':Path(request['baseline']).write_text('{"objects":{}}')
            if request['mode']=='model':(out/'candidate.3dm').write_bytes(b'native draft fixture')
            if request['mode']=='verify':
                (out/'checks.json').write_text(json.dumps({'passed':False,'errors':['Unexpected dimensions: Surface'],
                    'before':{'objects':{}},'after':{'objects':{'mesh':{'dimensions':[7,6,1]}}}}))
                return dict(passed=False,returncode=0,timeout=uncertain,worker=dict(passed=False,error='ValueError: Unexpected dimensions: Surface'))
            return dict(passed=True,returncode=0,worker=dict(passed=True,details={}))
        with patch('task_relay.rhino_host.run',side_effect=native):result=execute(session['frozen'],control)
        session['status']={'status':'finished','exit_code':0,'reason':None,'usage':[],'operation':result}
        worker.tick()
        self.assertEqual(self.rt.status(run)['status'],'blocked')
        return run

    def test_continue_proposes_correction_with_measured_report_and_original_checks(self):
        run=self.failed();before=self.rt.status(run);calls=len(self.factory.calls)
        original=self.rt.spec(self.rt.task(run,'app'))
        self.assertEqual(correction.details(self.state,run)['kind'],'execution_failure')
        self.assertIn('Plan correction',correction.text(self.state,run))
        with transaction(self.state.db):
            reply=continuations.enqueue(self.state,{'id':99,'prompt':'Continue the model'},run)
        self.assertIn('Native correction preparation ready',reply)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(self.row()['id'],)).fetchone()
        plan=json.loads(row['plan']);payload=json.loads(row['context'])
        self.assertEqual(self.rt.status(run),before);self.assertEqual(len(self.factory.calls),calls)
        self.assertEqual(row['calls'],0);self.assertIsNone(row['run'])
        self.assertTrue(all(not t.get('execution') for t in plan['tasks']))
        supplied={s['artifact'] for s in payload['sources']}
        self.assertTrue({i['artifact'] for i in original['inputs']}<=supplied)
        for name in ('candidate.3dm','checks.json','execution.json'):
            self.assertIn(self.rt.output(run,'app','delivery/'+name)['id'],supplied)
        self.assertIn('independently derived expected values',plan['tasks'][0]['instruction'])
        self.assertEqual(plan['origin']['geometry_basis'],json.loads(self.row()['plan'])['origin']['geometry_basis'])
        with transaction(self.state.db):self.assertEqual(correction.propose(self.state,run),row['id'])
        with self.assertRaisesRegex(ValueError,'complete plan card'),transaction(self.state.db):
            planning.apply(self.state,row['token'],'start')
        with transaction(self.state.db):
            self.delivered(row);planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.rt.task(run,'app')['attempts'],1)
        self.assertEqual(len(self.factory.calls),calls)

    def test_timeout_does_not_become_correction_or_replay(self):
        run=self.failed(uncertain=True)
        self.assertIsNone(correction.details(self.state,run))
        with self.assertRaises(ValueError),transaction(self.state.db):correction.propose(self.state,run)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)

    def test_changed_failure_evidence_invalidates_proposal_start(self):
        run=self.failed()
        with transaction(self.state.db):ident=correction.propose(self.state,run)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        blob=Path(self.rt.output(run,'app','delivery/checks.json')['blob'])
        blob.chmod(0o600);blob.write_text('{"passed":true}')
        with self.assertRaises(ValueError),transaction(self.state.db):
            self.delivered(row);planning.apply(self.state,row['token'],'start')
        self.assertIsNone(self.state.db.execute('SELECT run FROM production_plans WHERE id=?',(ident,)).fetchone()[0])


class BlenderTests(unittest.TestCase):
    from tests.test_native_recovery import BlenderContinuationTests as _Fixture
    for name in ('setUp','tearDown','request','action','queue','row','response','setup_plan'):
        locals()[name]=getattr(_Fixture,name)

    def test_blender_failure_retains_original_scene_as_source_and_draft_as_evidence(self):
        from types import SimpleNamespace
        row=self.setup_plan()
        with transaction(self.state.db):
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
            planning.apply(self.state,row['token'],'start')
        run=self.row()['run'];worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        session=self.factory.sessions[self.rt.task(run,'app')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        def native(command,**kwargs):
            mode=command[command.index('--')+1];out=Path(command[-1])
            if mode=='before':
                (out/'checks.json').write_text('{"before":{}}')
                return SimpleNamespace(returncode=0,stdout=b'RELAY_EDIT_BEFORE_OK',stderr=b'')
            (out/'candidate.blend').write_bytes(b'unaccepted fixture')
            return SimpleNamespace(returncode=1,stdout=b'',stderr=b'Traceback (most recent call last):\nValueError: Unsupported geometry operation')
        with patch('orchestrator.blender_edit.subprocess.run',side_effect=native):result=execute(session['frozen'],control)
        session['status']={'status':'finished','exit_code':0,'reason':None,'usage':[],'operation':result};worker.tick()
        with transaction(self.state.db):ident=correction.propose(self.state,run)
        fresh=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        proposed=json.loads(fresh['plan']);context=json.loads(fresh['context'])
        self.assertEqual(proposed['origin']['geometry_basis'],json.loads(row['plan'])['origin']['geometry_basis'])
        draft=self.rt.output(run,'app','delivery/candidate.blend')['id']
        self.assertTrue(next(s for s in context['sources'] if s['artifact']==draft)['diagnostic_evidence'])
        self.assertNotIn(draft,proposed['origin']['geometry_basis']['artifacts'])
        self.assertTrue(all(not t.get('execution') for t in proposed['tasks']))
        self.assertEqual(len(self.factory.calls),1)


if __name__=='__main__':unittest.main()
