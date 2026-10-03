import copy
import json
from pathlib import Path
import unittest

from orchestrator import contracts as c, design_review
from task_relay import design_intent as intent, production_planning as planning
from tests import test_production_planning as fixture


def addition(lid='n1', statement='Six narrow units', quote='Use six narrow units.', **changes):
    return dict(local_id=lid,statement=statement,kind='requirement',basis='user',quote=quote,
                supersedes=[],test='Count units and inspect their plan proportions.',**changes)


def proposal(additions=None, phase='prototype', advance_quote=''):
    return dict(phase=phase,representation='Derive a representative unit from its continuous terrain-following path.',
                advance_quote=advance_quote,additions=[addition()] if additions is None else additions)


def payload(previous=None, request='Use six narrow units.'):
    return dict(design_intent_policy=1,design_intent_request=request,design_intent_previous=previous,
                design_intent_checkpoint=[])


def evidence(frozen, status='supported'):
    p=frozen['design_review']
    return json.dumps(dict(intent_sha256=p['sha256'],phase=p['phase'],observations=[
        dict(id=e['id'],status=status,evidence='Checked the saved candidate section against the cited requirement.') for e in p['entries']]))


class IntentTests(unittest.TestCase):
    def compile(self, value=None, context=None, ident=1):
        return intent.compile_proposal({'design_intent':value or proposal()},context or payload(),ident)

    def test_change_retains_unaffected_entries_and_old_version(self):
        a=addition('n2','Keep the continuous trail.','Keep the continuous trail.')
        first=self.compile(proposal([addition(),a]),payload(request='Use six narrow units. Keep the continuous trail.'))
        original=copy.deepcopy(first)
        change=addition(statement='Three narrow units',quote='Make three units.')
        change['supersedes']=['1:n1']
        second=self.compile(proposal([change],phase='revision'),payload(first,'Make three units.'),2)
        self.assertEqual(first,original)
        self.assertEqual(second['superseded'],['1:n1'])
        self.assertEqual([e['id'] for e in second['entries'] if e['id'] not in second['superseded']],['1:n2','2:n1'])
        self.assertEqual(second['ancestors'],[first['sha256']])

    def test_agent_dimension_cannot_become_requirement(self):
        value=addition(statement='Length 17 metres',quote='17 metres')
        with self.assertRaisesRegex(ValueError,'authored quotation'):self.compile(proposal([value]))
        value.update(basis='interpretation',quote='')
        with self.assertRaisesRegex(ValueError,'proposals/questions'):self.compile(proposal([value]))
        value['kind']='proposal'
        self.assertEqual(self.compile(proposal([value]))['entries'][0]['kind'],'proposal')

    def test_quoted_example_is_not_direct_user_instruction(self):
        for request in ('> Use six narrow units.','```\nUse six narrow units.\n```'):
            with self.subTest(request=request),self.assertRaisesRegex(ValueError,'authored quotation'):
                self.compile(context=payload(request=request))

    def test_unapproved_interpretation_cannot_override(self):
        first=self.compile()
        value=addition();value.update(kind='proposal',basis='interpretation',quote='',supersedes=['1:n1'])
        with self.assertRaisesRegex(ValueError,'cited user change'):
            self.compile(proposal([value],phase='revision'),payload(first),2)

    def test_first_development_requires_checkpoint_or_explicit_bypass(self):
        with self.assertRaisesRegex(ValueError,'selected geometric prototype'):
            self.compile(proposal(phase='development'))
        request='Skip the prototype and develop the complete design. Use six narrow units.'
        record=self.compile(proposal(phase='development',advance_quote='Skip the prototype and develop the complete design.'),payload(request=request))
        self.assertEqual(record['phase'],'development')

    def test_revision_without_prior_lineage_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'established design lineage'):self.compile(proposal(phase='revision'))

    def test_feedback_is_verbatim_and_can_be_reconciled_next_plan(self):
        first=self.compile()
        revised=intent.feedback_record(first,'Make three units.','telegram:2')
        self.assertEqual(first['entries'],[e for e in revised['entries'] if e['id']=='1:n1'])
        self.assertEqual(intent.feedback_record(revised,'Make three units.','telegram:2'),revised)
        change=addition(statement='Three units',quote='Make three units.');change['supersedes']=['1:n1',revised['entries'][-1]['id']]
        record=self.compile(proposal([change],phase='revision'),payload(revised,'Continue the correction.'),3)
        self.assertEqual(len(record['superseded']),2)

    def test_generic_acceptance_wrong_phase_missing_entry_or_wrong_hash_fails(self):
        from tests.test_orchestrator import pair
        tasks=pair()['tasks'];intent.bind(tasks,self.compile());frozen=tasks[1]
        frozen['assignment_id']='review'
        result=dict(assignment_id='review',summary='Reviewed',decision='accept',instruction='',checks=[
            dict(criterion=i,passed=True,evidence='valid model') for i in range(1,len(frozen['criteria'])+1)])
        with self.assertRaisesRegex(ValueError,'structured per-entry'):c.report(result,frozen)
        good=json.loads(evidence(frozen))
        for key,value in [('intent_sha256','b'*64),('phase','output'),('observations',[])]:
            bad={**good,key:value};result['checks'][-1]['evidence']=json.dumps(bad)
            with self.subTest(key=key),self.assertRaises(ValueError):c.report(result,frozen)
        result['checks'][-1]['evidence']=json.dumps(good)
        c.report(result,frozen)
        for status in ('concern','unverified'):
            result['checks'][-1]['evidence']=evidence(frozen,status)
            self.assertTrue(c.report(result,frozen)['findings'])


class PlanningTests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        del self.fail
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    click=fixture.Tests.click
    start=fixture.Tests.start

    def ready(self):
        row=self.queue(action=self.action(design_intent=True),text='Use six narrow units.')
        response=self.response();response['design_intent']=proposal()
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        return row

    def test_missing_intent_is_not_silently_accepted(self):
        row=self.queue(action=self.action(design_intent=True),text='Use six narrow units.')
        with self.assertRaisesRegex(ValueError,'Design intent requires'):
            planning.validate_result(json.dumps(self.response()),row)
        self.assertEqual(self.factory.calls,[])

    def test_both_assignments_receive_intent_and_generic_review_blocks(self):
        row=self.ready();self.assertIn('Six narrow units',planning.preview(row))
        self.start(row);self.rt.tick('production-1')
        first=self.rt.task('production-1','produce')['latest'];self.factory.finish(first);self.rt.tick('production-1')
        second=self.rt.task('production-1','review')['latest']
        for aid in (first,second):
            frozen=self.factory.sessions[aid]['frozen']
            self.assertIn('1:n1',frozen['instruction'])
            self.assertEqual(frozen['design_intent_state']['entries'][0]['quote'],'Use six narrow units.')
        self.factory.finish(second,decision='accept');self.rt.tick('production-1')
        self.assertEqual(self.rt.task('production-1','review')['status'],'blocked')

    def finish_review(self, status='supported'):
        first=self.rt.task('production-1','produce')['latest'];self.factory.finish(first);self.rt.tick('production-1')
        second=self.rt.task('production-1','review')['latest'];self.factory.finish(second,decision='accept')
        frozen=self.factory.sessions[second]['frozen']
        path=Path(frozen['workspace'])/'.relay/result.json';report=json.loads(path.read_text())
        report['checks'][-1]['evidence']=evidence(frozen,status);path.write_text(json.dumps(report));self.rt.tick('production-1')

    def test_concern_waits_for_human_and_user_revision_keeps_original(self):
        row=self.ready();self.start(row);self.rt.tick('production-1');self.finish_review('concern')
        task=self.rt.task('production-1','produce');old=self.rt.spec(task)
        self.assertEqual(task['status'],'awaiting_user')
        self.assertTrue(self.rt.quality_review(task))
        self.rt.revise('production-1','produce','Make three units.','user')
        new=self.rt.spec(self.rt.task('production-1','produce'))
        review=self.rt.spec(self.rt.task('production-1','review'))
        self.assertEqual(len(old['design_intent_state']['entries']),1)
        self.assertEqual(new['design_intent_state']['entries'][-1]['quote'],'Make three units.')
        self.assertEqual(new['design_intent_state']['sha256'],review['design_review']['sha256'])
        c.plan({**json.loads(row['plan']),'tasks':[new,review]})

    def test_parent_revision_preserves_lineage_without_opt_in_again(self):
        first=self.ready()
        second=self.queue(2,self.action(parent_id=first['id']),text='Make three units.')
        p=json.loads(second['context'])
        self.assertEqual(p['design_intent_previous']['entries'][0]['quote'],'Use six narrow units.')
        response=self.response();change=addition(statement='Three units',quote='Make three units.');change['supersedes']=['1:n1']
        response['design_intent']=proposal([change],phase='revision')
        _,plan=planning.validate_result(json.dumps(response),second)
        self.assertEqual(plan['origin']['design_intent']['superseded'],['1:n1'])
        self.assertEqual(json.loads(first['plan'])['origin']['design_intent']['superseded'],[])

    def test_selected_preparation_does_not_establish_visual_checkpoint(self):
        row=self.ready();self.start(row);self.rt.tick('production-1');self.finish_review()
        task=self.rt.task('production-1','produce')
        art=self.state.db.execute('SELECT id FROM production_artifacts WHERE attempt=?',(task['latest'],)).fetchone()[0]
        self.rt.select('production-1','produce',art,self.rt.decision_purpose(task),'Selected preparation')
        second=self.queue(2,self.action(previous_run='production-1'),text='Develop the full design.')
        self.assertEqual(json.loads(second['context'])['design_intent_checkpoint'],[])
        response=self.response();response['design_intent']=proposal([],phase='development')
        with self.assertRaisesRegex(ValueError,'selected geometric prototype'):
            planning.validate_result(json.dumps(response),second)

    def test_exact_selected_model_and_preview_unlock_development_and_pipeline_handoff(self):
        # Text placeholders exercise identity/selection only; no CAD or images generated.
        self.queue(action=self.action(design_intent=True),text='Use six narrow units.')
        response=self.response();response['design_intent']=proposal()
        producer,review=response['plan']['tasks']
        producer['outputs']=[dict(path=p,purpose='Controlled identity fixture') for p in ('prototype.3dm','prototype.png')]
        producer['selection_outputs']=['prototype.3dm','prototype.png']
        review['inputs']=[dict(from_task='produce',output=p,path='candidate/'+p,purpose='Fixture',authority='Unaccepted') for p in producer['selection_outputs']]
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.start(row);self.rt.tick('production-1');self.finish_review()
        task=self.rt.task('production-1','produce')
        ids=[r[0] for r in self.state.db.execute('SELECT id FROM production_artifacts WHERE attempt=?',(task['latest'],))]
        self.rt.select('production-1','produce',ids[0],self.rt.decision_purpose(task),'Select controlled prototype set',artifacts=ids)
        second=self.queue(2,self.action(previous_run='production-1'),text='Develop the full design.')
        frozen=json.loads(second['context']);self.assertEqual(len(frozen['design_intent_checkpoint']),1)
        response=self.response();response['design_intent']=proposal([],phase='development')
        _,plan=planning.validate_result(json.dumps(response),second)
        self.assertEqual(plan['origin']['design_intent']['entries'][0]['id'],'1:n1')
        # Pipeline sources resolve the same exact lineage without a project-wide head.
        context=dict(options={},sources=frozen['sources'],planner_instructions='')
        intent.attach(self.state,context,None,None,dict(stage={'design_intent':True},original_request='Use six narrow units.',
            inputs={'sources':[{'artifact':aid} for aid in ids]}),'generated stage text')
        self.assertEqual(context['design_intent_previous']['sha256'],json.loads(row['plan'])['origin']['design_intent']['sha256'])
        self.assertEqual(context['design_intent_request'],'Use six narrow units.')

    def test_separate_job_does_not_inherit_another_jobs_intent(self):
        self.ready()
        fresh=self.queue(2,self.action(design_intent=True),text='Design a round table.')
        self.assertIsNone(json.loads(fresh['context'])['design_intent_previous'])


class NativeCorrectionTests(unittest.TestCase):
    from tests.test_review_corrections import Tests as _fixture
    for _name in ('tearDown','request','queue','row','click','drain','start','preparation','prepare',
                  'finish_preparation','prepared_files','select','rejected'):
        locals()[_name]=getattr(_fixture,_name)

    def setUp(self):
        self._fixture.setUp(self)
        finish=self.factory.finish
        def with_evidence(aid,*args,**kwargs):
            finish(aid,*args,**kwargs)
            frozen=self.factory.sessions[aid]['frozen']
            if frozen.get('design_review') and kwargs.get('decision')=='accept':
                path=self.factory.sessions[aid]['workspace']/'.relay/result.json'
                result=json.loads(path.read_text());result['checks'][-1]['evidence']=evidence(frozen)
                path.write_text(json.dumps(result))
        self.factory.finish=with_evidence

    def action(self,**kwargs):
        return fixture.Tests.action(self,design_intent=True,**kwargs)

    def response(self):
        value=fixture.Tests.response(self)
        entry=addition(statement='Keep Grasshopper paused',quote='keep Grasshopper paused.')
        value['design_intent']=proposal([entry])
        return value

    def host_response(self,*args):
        value=self._fixture.host_response(self,*args)
        value['design_intent']=proposal([])
        return value

    def test_quality_correction_retains_intent_and_does_not_replay_execution(self):
        from task_relay import production_review_corrections as corrections
        from orchestrator.storage import transaction
        run=self.rejected(quality=True);before=self.rt.status(run);calls=len(self.factory.calls)
        with transaction(self.state.db):ident=corrections.propose(self.state,run,feedback='Keep the height; adjust only the camera.')
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        plan=json.loads(row['plan']);record=plan['origin']['design_intent']
        self.assertEqual(record['entries'][0]['quote'],'keep Grasshopper paused.')
        self.assertEqual(record['entries'][-1]['quote'],'Keep the height; adjust only the camera.')
        self.assertEqual(plan['tasks'][1]['design_review']['sha256'],record['sha256'])
        self.assertTrue(all(not t.get('execution') for t in plan['tasks']))
        self.assertEqual(self.rt.status(run),before);self.assertEqual(len(self.factory.calls),calls)


class ReviewRecoveryTests(unittest.TestCase):
    from tests.test_presentations import PlanningTests as _fixture
    for _name in ('tearDown','request','queue','row','deck_response','check_exhausted_review_recovery'):
        locals()[_name]=getattr(_fixture,_name)

    def setUp(self):
        self._fixture.setUp(self)
        if isinstance(getattr(self,'fail',None),bool):del self.fail

    def action(self,**kwargs):
        return fixture.Tests.action(self,design_intent=True,**kwargs)

    def response(self):
        value=fixture.Tests.response(self)
        value['design_intent']=proposal([addition(statement='Do not render',quote='Do not render.')])
        return value

    def test_exhausted_review_preserves_new_feedback_and_intent(self):
        # This fixture stops at draft review: no document/native operation runs.
        self.check_exhausted_review_recovery()
        row=self.state.db.execute("SELECT plan FROM production_plans WHERE request_id<0").fetchone()
        record=json.loads(row['plan'])['origin']['design_intent']
        self.assertEqual(record['entries'][0]['quote'],'Do not render.')
        self.assertEqual(record['entries'][-1]['quote'],'Fix the reviewed draft and continue the saved workflow.')


if __name__=='__main__':unittest.main()
