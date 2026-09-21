import json
from pathlib import Path
import unittest

from tests import test_production_planning as fixture
from tests import test_artifact_handoff as artifacts
from task_relay import production_planning as planning
from orchestrator.runtime import file_hash


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    click=fixture.Tests.click
    start=fixture.Tests.start
    artifact=artifacts.Tests.artifact

    def proposal(self,source):
        response=self.response()
        response['input_basis']={'mode':'modify_existing','artifacts':[source['artifact']]}
        response['plan']['tasks'][0]['inputs']=[{k:source[k] for k in ('artifact','path','purpose','authority')}]
        return response

    def test_omitted_baseline_can_be_selected_by_planner_and_reaches_both_workers(self):
        artifact=self.artifact('{"height":5,"width":2}')
        row=self.queue(text='Can we make it twice as tall?')
        context=json.loads(row['context']);source=next(s for s in context['available_sources'] if s['artifact']==artifact['id'])
        self.assertNotIn(artifact['id'],context['required_artifacts'])
        response=self.proposal(source)
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        plan=json.loads(row['plan'])
        for task in plan['tasks']:
            self.assertTrue(any(i.get('artifact')==artifact['id'] for i in task['inputs']))
        self.assertIn(source['path'],planning.preview(row))
        manifest=Path(self.state.db.execute('SELECT path FROM media_outbox WHERE id=?',(row['event_id']+':sources',)).fetchone()['path'])
        self.assertTrue(any(s['sha256']==artifact['sha256'] for s in json.loads(manifest.read_text())))
        self.start(row);self.rt.tick('production-1')
        frozen=self.factory.sessions[self.rt.task('production-1','produce')['latest']]['frozen']
        copy=Path(frozen['workspace'])/source['path']
        self.assertEqual(copy.read_text(),'{"height":5,"width":2}')
        self.assertEqual(file_hash(copy),artifact['sha256'])

    def test_missing_baseline_does_not_reach_ready_or_start_workers(self):
        artifact=self.artifact();row=self.queue(text='Double the previous tower height.')
        source=json.loads(row['context'])['available_sources'][0]
        for response in (self.response(),self.proposal(source)):
            if response['input_basis']['mode']=='new':response.pop('input_basis')
            else:response['plan']['tasks'][0]['inputs']=[]
            with self.assertRaisesRegex(ValueError,'input_basis|Every declared baseline'):
                planning.validate_result(json.dumps(response),row)
        response=self.proposal(source);response['input_basis']['artifacts']=[]
        with self.assertRaisesRegex(ValueError,'requires exact baseline'):
            planning.validate_result(json.dumps(response),row)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_runs WHERE id='production-1'").fetchone()[0],0)

    def test_baseline_changed_after_preview_blocks_start(self):
        artifact=self.artifact();row=self.queue(text='Revise the previous output.')
        source=json.loads(row['context'])['available_sources'][0]
        planning.Worker(self.state,lambda *_:(json.dumps(self.proposal(source)),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        path=Path(artifact['blob']);path.chmod(0o600);path.write_text('changed')
        self.start(row)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_runs WHERE id='production-1'").fetchone()[0],0)

    def test_unrelated_prior_outputs_are_not_attached_to_new_work(self):
        artifact=self.artifact();row=self.queue(text='Write a new unrelated brief.')
        _,plan=planning.validate_result(json.dumps(self.response()),row)
        self.assertFalse(any(i.get('artifact')==artifact['id'] for t in plan['tasks'] for i in t['inputs']))

    def test_plan_clarification_retains_the_selected_baseline_version(self):
        artifact=self.artifact();row=self.queue(text='Revise the previous output.')
        source=json.loads(row['context'])['available_sources'][0]
        planning.Worker(self.state,lambda *_:(json.dumps(self.proposal(source)),{})).tick()
        parent=self.row();self.assertEqual(parent['status'],'ready',parent['error'])
        child=self.queue(ident=2,action=self.action(parent_id=parent['id']),text='Keep its original width.')
        context=json.loads(child['context'])
        self.assertIn(artifact['id'],context['required_artifacts'])
        preserved=next(s for s in context['sources'] if s['artifact']==artifact['id'])
        self.assertEqual(preserved['sha256'],artifact['sha256'])


if __name__=='__main__':unittest.main()
