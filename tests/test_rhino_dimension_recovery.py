"""Old dimension-only failures may propose a fresh Start, never reset history."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from orchestrator.step_runner import execute
from orchestrator.storage import transaction
from task_relay import production_control as pc, production_planning as planning, production_continuations as continuations
from tests import test_rhino_launch_recovery as fixture


class Tests(unittest.TestCase):
    for name in ('setUp','tearDown','request','action','queue','row','response','setup_plan','delivered'):
        locals()[name]=getattr(fixture.Tests,name)

    def legacy(self, invalid=False):
        row=self.setup_plan()
        with transaction(self.state.db):self.delivered(row);planning.apply(self.state,row['token'],'start')
        run=self.row()['run'];worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        session=self.factory.sessions[self.rt.task(run,'app')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        def native(*args):
            request=json.loads(Path(args[2]).read_text());out=Path(request['out'])
            if request['mode']=='before':Path(request['baseline']).write_text('{"objects":{}}')
            if request['mode']=='model':(out/'candidate.3dm').write_bytes(b'native fixture')
            if request['mode']=='verify':
                checks=json.loads(Path(request['checks']).read_text());name,dims=next(iter(checks['expected_dimensions'].items()))
                after=dict(objects={'obj':dict(name=name,dimensions=[dims[0]+1,*dims[1:]],valid=not invalid)},
                    units=checks['units'],tolerance=.001,named_views={},dependencies=[])
                (out/'checks.json').write_text(json.dumps(dict(before={'objects':{}},after=after,passed=False,errors=['Unexpected dimensions: '+name])))
                return dict(passed=False,returncode=0,worker=dict(passed=False,error='ValueError: Unexpected dimensions: '+name))
            return dict(passed=True,returncode=0,worker=dict(passed=True,details={}))
        with patch('task_relay.rhino_host.run',side_effect=native):result=execute(session['frozen'],control)
        receipt=Path(session['frozen']['workspace'])/'delivery/execution.json'
        value=json.loads(receipt.read_text());value['runtime_sources']['rhino_contract.py']='0'*64;receipt.write_text(json.dumps(value))
        session['status']=dict(status='finished',exit_code=0,reason=None,usage=[],operation=result);worker.tick()
        return run

    def test_continue_retains_script_checks_and_old_failure_with_no_provider_or_replay(self):
        run=self.legacy();before=self.rt.status(run);old=self.rt.spec(self.rt.task(run,'app'))
        with transaction(self.state.db):reply=continuations.enqueue(self.state,{'id':99,'prompt':'Continue'},run)
        self.assertIn('Native execution recovery ready',reply)
        fresh=self.state.db.execute('SELECT * FROM production_plans WHERE parent_id=?',(self.row()['id'],)).fetchone()
        self.assertIsNone(fresh['run']);self.assertEqual(fresh['calls'],0)
        plan=json.loads(fresh['plan']);op=next(t for t in plan['tasks'] if t.get('execution'))
        self.assertEqual(op['execution'],old['execution']);self.assertEqual(op['limits'],old['limits'])
        self.assertEqual(before,self.rt.status(run));self.assertEqual(len(self.factory.calls),1)
        review=next(t for t in plan['tasks'] if t.get('review_of'))
        self.assertIn('require user review before dependent work',review['instruction'])

    def test_geometry_failure_is_not_downgraded_even_if_old_error_text_only_mentions_dimensions(self):
        run=self.legacy(invalid=True)
        with transaction(self.state.db):self.assertIsNone(planning.prepare_host_launch_recovery(self.state,run,'Continue'))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)


if __name__=='__main__':unittest.main()
