import json
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay import pipelines, procedures, orchestrator_chat as chat, relay_channels
from tests import test_pipelines as fixtures


class Tests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    request = fixtures.Tests.request
    answer = fixtures.Tests.answer
    result = fixtures.Tests.result
    step = fixtures.Tests.step

    def completed(self, choice=False):
        stages = [dict(id='research', instruction='Research Arizona using briefs/arizona.txt.',
                       route='conversation', gate='choice' if choice else 'none', capabilities=[],
                       deliverables={'evidence': 'Arizona evidence'}),
                  dict(id='report', instruction='Write the Arizona report using the exact selected evidence.',
                       route='conversation', gate='none', capabilities=[], deliverables={'report': 'Arizona report'})]
        action = dict(kind='plan_pipeline', title='Arizona study', planning_only=False, stages=stages)
        action['contract_version']=1
        for s in stages:s['handoff']={'inputs':[],'outputs':{k:{'media_type':'text/plain'} for k in s['deliverables']}}
        self.request(action, 'Research Arizona from briefs/arizona.txt, then write a report. Preserve source files.', 1)
        row = self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        choices = [dict(id='a', label='A', value='Old accepted approach'), dict(id='b', label='B', value='Alternative')] if choice else []
        self.answer(self.result('Old research that must never be reused.', choices))
        if choice:
            with transaction(self.state.db):pipelines.choose(self.state, row['id'], 'research', 'a')
        self.answer(self.result('Old final report.'))
        pipelines.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0], 'completed')
        return row

    def draft(self, row, **changes):
        action = dict(kind='draft_procedure', pipeline_id=row['id'], name='Research and report',
                      parameters=[dict(name='location', example='Arizona'),
                                  dict(name='brief', example='briefs/arizona.txt')])
        action.update(changes)
        self.request(action, 'Save this completed workflow with location and brief as variables.', 100)
        saved = self.state.db.execute('SELECT * FROM relay_procedures').fetchone()
        self.assertIsNotNone(saved, self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=100').fetchone()[0])
        return saved

    def approve(self, row):
        self.bridge.process({'update_id': 101, 'message': {'text': '/procedures approve ' + row['id'],
                            'from': {'id': 7}, 'chat': {'id': 7, 'type': 'private'}}})
        self.assertEqual(procedures.load(self.state, row['id'])[0]['status'], 'approved')

    def run_action(self, row, **changes):
        action = dict(kind='run_procedure', procedure_id=row['id'],
                      bindings=dict(location='Iowa', brief='briefs/iowa.txt'))
        action.update(changes)
        return action

    def test_save_review_reuse_preserves_gates_and_fresh_continuity(self):
        origin = self.completed(choice=True); saved = self.draft(origin)
        template = json.loads(saved['definition'])['template']
        self.assertEqual(template['stages'][0]['gate'], 'choice')
        self.assertIn('{{location}}', template['request'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0], 1)
        self.approve(saved)
        original = 'Run the research procedure for Iowa using briefs/iowa.txt. Keep existing files.'
        self.request(self.run_action(saved), original, 102)
        run = self.state.db.execute('SELECT * FROM relay_pipelines WHERE request_id=102').fetchone()
        self.assertIsNotNone(run)
        self.assertEqual(run['status'], 'planned')
        self.assertEqual(run['request'], original)
        self.assertEqual(run['provider'], 'gemini')  # Current request model, not a frozen executor.
        self.assertEqual(self.step(run, 'research')['sources'], '[]')
        self.assertIsNone(self.step(run, 'research')['request_id'])
        event = f"pipeline:{run['id']}:workflow:created"
        card = self.state.db.execute('SELECT text FROM outbox WHERE id=?', (event,)).fetchone()[0]
        self.assertIn('Research Iowa from briefs/iowa.txt', card)
        self.assertEqual(pipelines.controls(self.state, event)['inline_keyboard'][0][0]['text'], 'Resume workflow')
        self.assertIsNone(self.state.db.execute("SELECT 1 FROM outbox WHERE id='orchestrator:102'").fetchone())
        with transaction(self.state.db):pipelines.control(self.state, run['id'], 'resume')
        pipelines.tick(self.state)
        jobid = self.step(run, 'research')['request_id']
        ctx = pipelines.request_context(self.state, jobid)
        self.assertEqual(ctx['inputs']['sources'], [])
        self.assertEqual(ctx['inputs']['prior_results'], [])
        self.assertEqual(ctx['inputs']['procedure']['sha256'], saved['sha256'])
        prompt = self.state.db.execute('SELECT prompt FROM orchestrator_chats WHERE id=?', (jobid,)).fetchone()[0]
        self.assertIn('Iowa', prompt)
        for old in ('Arizona', 'arizona.txt', 'Old accepted approach', 'Old research', 'Old final report'):
            self.assertNotIn(old, prompt)
        seen=[]
        choices=self.result('Fresh Iowa options', [dict(id='x', label='X', value='New X'), dict(id='y', label='Y', value='New Y')])
        chat.Worker(self.state,lambda job,payload:seen.append(payload) or json.dumps({'answer':'New options','action':choices})).tick()
        self.assertNotIn('procedure_sources',seen[0]['snapshot'])
        pipelines.tick(self.state)
        self.assertEqual(self.step(run, 'research')['status'], 'awaiting_choice')
        self.assertIsNone(self.step(run, 'report')['request_id'])
        with transaction(self.state.db):pipelines.choose(self.state, run['id'], 'research', 'y')
        pipelines.tick(self.state)
        report_context = pipelines.request_context(self.state, self.step(run, 'report')['request_id'])
        self.assertIn('New Y', report_context['inputs']['prior_results'][0]['result'])
        self.answer(self.result('Fresh Iowa report')); pipelines.tick(self.state)
        self.assertEqual(procedures.catalog(self.state)[0]['completed_runs'], 1)
        from task_relay import workflow_files
        manifest=json.loads((workflow_files.folder_path(self.state,run['id'])/'manifest.json').read_text())
        self.assertEqual(manifest['procedure']['sha256'],saved['sha256'])
        self.assertEqual(manifest['procedure']['bindings']['location'],'Iowa')
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?', (origin['id'],)).fetchone()[0], 'completed')

    def test_incomplete_source_and_changed_receipts_cannot_be_approved(self):
        origin = self.completed(); saved = self.draft(origin)
        with transaction(self.state.db):
            pipelines.event(self.state, origin['id'], None, 'new_receipt', {'reason': 'changed after draft'})
        with transaction(self.state.db), self.assertRaisesRegex(ValueError, 'receipts changed'):
            procedures.approve(self.state, dict(id=7, prompt='approve'), saved['id'])
        self.assertEqual(procedures.load(self.state, saved['id'])[0]['status'], 'draft')
        with self.state.db:self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='report'", (origin['id'],))
        with self.assertRaisesRegex(ValueError, 'Every source stage'):procedures.source(self.state, origin['id'])

    def test_missing_bindings_unapproved_versions_and_cross_channel_never_queue(self):
        origin = self.completed(); saved = self.draft(origin)
        job = dict(id=102, prompt='Use the saved procedure', provider='gemini', model='fixture')
        with transaction(self.state.db), self.assertRaisesRegex(ValueError, 'approve'):
            procedures.dispatch(self.state, job, self.run_action(saved), {})
        self.approve(saved)
        for bindings in ({'location': 'Iowa'}, {'location': 'Iowa', 'brief': 'new.txt', 'extra': 'expand scope'}):
            with transaction(self.state.db), self.assertRaisesRegex(ValueError, 'every parameter'):
                procedures.dispatch(self.state, job, self.run_action(saved, bindings=bindings), {})
        other = relay_channels.ScopedState(self.state, 'messages')
        with self.assertRaisesRegex(ValueError, 'channel'):procedures.load(other, saved['id'])
        with self.assertRaisesRegex(ValueError, 'channel'):procedures.source(other, origin['id'])
        self.assertEqual(procedures.catalog(other), [])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0], 1)
        self.request(self.run_action(saved,bindings={'location':'Iowa'}),'Run in Iowa',102)
        answer=self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=102').fetchone()[0]
        self.assertIn('every parameter',answer)
        self.assertNotIn('rephrase',answer)

    def test_new_extraction_does_not_modify_an_approved_version(self):
        origin=self.completed(); saved=self.draft(origin); self.approve(saved)
        before=procedures.load(self.state,saved['id'])[1]
        action=dict(kind='draft_procedure',pipeline_id=origin['id'],name='Revised study',
                    parameters=[dict(name='place',example='Arizona')])
        with transaction(self.state.db):
            procedures.dispatch(self.state,dict(id=103,prompt='Save a different variable definition'),action,{})
        versions=procedures.catalog(self.state)
        self.assertEqual(len(versions),2)
        self.assertEqual(procedures.load(self.state,saved['id'])[1],before)
        self.assertEqual(procedures.load(self.state,saved['id'])[0]['status'],'approved')
        newer=next(v for v in versions if v['id']!=saved['id'])
        self.assertEqual(newer['status'],'draft')

    def test_approved_legacy_generation_is_preserved_in_new_reviewable_plan(self):
        origin=self.completed()
        spec=json.loads(origin['spec'])
        spec.pop('contract_version',None)
        for stage in spec['stages']:stage.pop('handoff',None)
        spec['stages'][0].update(route='image',gate='selection',instruction='Generate an Arizona concept illustration.')
        with self.state.db:self.state.db.execute('UPDATE relay_pipelines SET spec=? WHERE id=?',(json.dumps(spec),origin['id']))
        saved=self.draft(origin);self.approve(saved)
        before=procedures.load(self.state,saved['id'])[1]
        self.request(self.run_action(saved),'Reuse the approved concept procedure for Iowa.',102)
        run=self.state.db.execute('SELECT * FROM relay_pipelines WHERE request_id=102').fetchone()
        self.assertIsNotNone(run)
        self.assertEqual(run['status'],'planned')
        self.assertEqual(json.loads(run['spec'])['stages'][0]['visual_intent'],'synthetic')
        self.assertEqual(procedures.load(self.state,saved['id'])[1],before)
        text=self.state.db.execute('SELECT text FROM outbox WHERE id=?',(f"pipeline:{run['id']}:workflow:created",)).fetchone()[0]
        self.assertIn('do not source reference photos',text)
        self.assertEqual(procedures.run_context(self.state,run['id'])['legacy_generation_stages'],['research'])

    def test_duplicate_run_request_and_approval_are_idempotent(self):
        saved = self.draft(self.completed()); self.approve(saved); self.approve(saved)
        self.request(self.run_action(saved), 'Run for Iowa with briefs/iowa.txt', 102)
        self.request(self.run_action(saved), 'Run for Iowa with briefs/iowa.txt', 102)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_procedure_runs').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_procedure_events WHERE kind='approved'").fetchone()[0], 1)

    def test_atomic_run_failure_leaves_no_pipeline_or_notice(self):
        saved = self.draft(self.completed()); self.approve(saved)
        with patch.object(procedures, 'record', side_effect=ValueError('receipt storage failed')):
            self.request(self.run_action(saved), 'Run for Iowa with briefs/iowa.txt', 102)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_procedure_runs').fetchone()[0], 0)

    def test_tampered_version_and_unavailable_capabilities_block_reuse(self):
        saved = self.draft(self.completed()); self.approve(saved)
        value = json.loads(saved['definition'])
        value['template']['stages'][0]['gate'] = 'none'
        value['template']['stages'][0]['instruction'] = 'Different scope'
        with self.state.db:self.state.db.execute('UPDATE relay_procedures SET definition=?', (json.dumps(value),))
        with self.assertRaisesRegex(ValueError, 'version changed'):procedures.load(self.state, saved['id'])
        # A controlled historical native-work fixture: missing operation must be
        # checked against today's catalog, not inferred from the previous run.
        value = json.loads(saved['definition'])
        value['template']['stages'][1].update(route='production', capabilities=['rhino.run_python'], gate='selection')
        sha = procedures.digest(value); ident = 'proc-' + sha[:24]
        with self.state.db:
            self.state.db.execute('UPDATE relay_procedures SET id=?,definition=?,sha256=?', (ident, pipelines.encoded(value), sha))
        job = dict(id=103, prompt='New project', provider='gemini', model='fixture')
        with transaction(self.state.db), self.assertRaisesRegex(ValueError, 'capability'):
            procedures.dispatch(self.state, job, self.run_action({'id': ident}), {'capabilities': {'graph_operations': []}})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0], 1)

    def test_literal_parameters_do_not_change_operations_or_reexpand_bindings(self):
        origin = self.completed()
        action = dict(kind='draft_procedure', pipeline_id=origin['id'], name='Reusable study',
                      parameters=[dict(name='place', example='Arizona'), dict(name='other', example='Arizona')])
        with self.assertRaisesRegex(ValueError, 'distinct'):procedures.validate(action, {})
        action['parameters'] = [dict(name='place', example='Never occurred')]
        with transaction(self.state.db), self.assertRaisesRegex(ValueError, 'absent'):
            procedures.dispatch(self.state, dict(id=99, prompt='save'), action, {})
        saved = self.draft(origin); self.approve(saved)
        with self.assertRaises(ValueError):procedures.validate(self.run_action(saved, bindings={'location': '{{brief}}'}), {})
        self.request(self.run_action(saved, bindings=dict(location='Iowa $cost \\ area', brief='new.txt')), 'New study', 102)
        spec = json.loads(self.state.db.execute('SELECT spec FROM relay_pipelines WHERE request_id=102').fetchone()[0])
        self.assertEqual(spec['stages'][0]['id'], 'research')
        self.assertEqual(spec['stages'][0]['capabilities'], [])
        self.assertIn('Iowa $cost \\ area', spec['stages'][0]['instruction'])

    def test_location_inside_a_brief_path_is_parameterized_in_one_pass(self):
        origin=self.completed()
        with self.state.db:
            self.state.db.execute("UPDATE relay_pipelines SET request='Research Arizona using briefs/Arizona.txt' WHERE id=?",(origin['id'],))
        action=dict(kind='draft_procedure',pipeline_id=origin['id'],name='Study',parameters=[
            dict(name='location',example='Arizona'),dict(name='brief',example='briefs/Arizona.txt')])
        with transaction(self.state.db):procedures.dispatch(self.state,dict(id=100,prompt='Save this'),action,{})
        ident=procedures.catalog(self.state)[0]['id']
        self.assertEqual(procedures.load(self.state,ident)[1]['template']['request'],
                         'Research {{location}} using {{brief}}')

    def test_catalog_and_source_commands_are_read_only_without_a_provider(self):
        origin = self.completed()
        count = self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        for i, text in enumerate(('/procedures', '/procedures source ' + origin['id'])):
            self.bridge.process({'update_id': 800 + i, 'message': {'text': text, 'from': {'id': 7}, 'chat': {'id': 7, 'type': 'private'}}})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], count)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_procedures').fetchone()[0], 0)

    def test_old_output_references_must_not_become_implicit_new_inputs(self):
        origin=self.completed()
        spec=json.loads(origin['spec'])
        spec['stages'][1]['instruction']='Read old-artifact-identity to write the Arizona report.'
        with self.state.db:
            self.state.db.execute('UPDATE relay_pipelines SET spec=? WHERE id=?',(pipelines.encoded(spec),origin['id']))
            self.state.db.execute("UPDATE relay_pipeline_steps SET sources=? WHERE pipeline=? AND id='research'",
                                  (json.dumps([{'artifact':'old-artifact-identity','path':'old-output.txt'}]),origin['id']))
        action=dict(kind='draft_procedure',pipeline_id=origin['id'],name='Study',parameters=[dict(name='location',example='Arizona')])
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'old output identity'):
            procedures.dispatch(self.state,dict(id=100,prompt='Save this'),action,{})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_procedures').fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
