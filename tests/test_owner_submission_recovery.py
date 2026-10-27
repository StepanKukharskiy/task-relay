"""Shared owner correction loop with scripted replies; no live model requests."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import job_owner,owner_intents,parameter_contracts,gemini_worker,working_context
from orchestrator import contracts as c,executors
from orchestrator.workers import atomic
from tests import test_owner_compilation as compiled,test_owner_intents as intents
from tests.test_operation_session import Script,CONFIG


class Tests(unittest.TestCase):
    create=intents.Tests.create
    source=intents.Tests.source
    session=intents.Tests.session
    invoke=intents.Tests.invoke
    run_worker=intents.Tests.run_worker
    content=compiled.Tests.content

    def setUp(self):
        compiled.Tests.setUp(self)

    def proposal(self):
        refs,task=self.content(count=2)
        task['outputs']=[intents.output(media='application/json'),intents.output('result_summary','text/markdown')]
        return refs,dict(request_id='proposal',tasks=[task])

    def test_exhausted_task_grant_is_terminal_before_another_proposal_after_restart(self):
        self.grant['max_tasks']=2
        self.create();self.rt.tick('job');session=self.session()
        session.call('job_delegate',dict(request_id='fill',tasks=[intents.worker('work'),
            dict(id='review',objective='Review the exact work',review_of='work')]))
        self.assertEqual(len(self.rt.status('job')['tasks']),3)
        session=self.session()
        result=session.call('job_delegate',dict(request_id='new',tasks=[intents.worker('more')]))
        self.assertEqual(result['validation']['code'],'task_capacity_exhausted')
        with self.assertRaises(ValueError):session.check_progress(1,1)
        restored=self.session()
        with self.assertRaises(ValueError):restored.check_progress(1,1)
        self.assertEqual(len(self.rt.status('job')['tasks']),3)

    def test_runtime_created_evidence_gap_holds_once_and_survives_restart(self):
        from orchestrator.artifact_roles import CompatibilityError
        self.create();self.rt.tick('job');session=self.session()
        error=CompatibilityError(dict(artifact='prior-pdf',path='review/old.pdf',media_type='application/pdf'),
            'inspection_evidence',dict(kind='inherited',via=['artifact','report']),
            'No exact granted representation','Repair the registered inspection route')
        with patch.object(session,'delegate',side_effect=error):
            result=session.call('job_delegate',dict(request_id='first',tasks=[intents.worker('work')]))
        self.assertFalse(result['correction']['compatibility']['model_correctable'])
        with self.assertRaisesRegex(ValueError,'Runtime-created evidence'):session.check_progress(1,1)
        restored=self.session()
        with self.assertRaisesRegex(ValueError,'Runtime-created evidence'):restored.check_progress(1,1)
        self.assertEqual(len(self.factory.calls),1)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)

    def test_explicit_bad_evidence_selection_keeps_actionable_correction(self):
        from orchestrator.artifact_roles import CompatibilityError
        self.create();self.rt.tick('job');session=self.session()
        error=CompatibilityError(dict(artifact='pdf',path='selected.pdf',media_type='application/pdf'),
            'operation_input',dict(kind='selected'),'pptx.render requires PPTX','Choose the PPTX candidate')
        with patch.object(session,'delegate',side_effect=error):
            result=session.call('job_delegate',dict(request_id='first',tasks=[intents.worker('work')]))
        self.assertTrue(result['correction']['compatibility']['model_correctable']);self.assertIsNone(session.progress_hold)
        receipt=session.call('job_delegate',dict(request_id='corrected',tasks=[intents.worker('work')]))
        self.assertIn('work',receipt['queued']);self.assertIsNone(session.pending_submission)

    def test_canonical_wire_matches_validation_and_no_ambiguous_output_instruction(self):
        self.create();self.rt.tick('job');s=self.session()
        tool=next(t for t in job_owner.definitions(s.grant) if t['name']=='job_delegate')
        wire=next(t for t in gemini_worker.gemini_declarations([tool]))
        self.assertEqual(wire['parametersJsonSchema'],owner_intents.delegation_schema(4))
        self.assertNotIn('parameters',wire)
        for task in [intents.native('native','text.bundle'),dict(id='content',objective='Write',content=dict(family='collection.subjects',sources={},parameters={})),dict(id='review',objective='Review',review_of='work')]:
            valid=dict(request_id='a',tasks=[task]);parameter_contracts.validate(valid,wire['parametersJsonSchema'])
            task['outputs']=[intents.output()]
            with self.assertRaisesRegex(ValueError,'outputs'):owner_intents.validate_delegation(valid,4)
            with self.assertRaises(ValueError):parameter_contracts.validate(valid,wire['parametersJsonSchema'])
        self.assertIn('Omit outputs',s.frozen['instruction'])
        self.assertLess(len(s.frozen['instruction']),1500)
        # No canonical union accepts a reference with both identity modes.
        both=dict(request_id='a',tasks=[intents.worker('work',[dict(artifact='a',task='b',output='result')])])
        with self.assertRaises(ValueError):parameter_contracts.validate(both,wire['parametersJsonSchema'])

    def test_rejected_content_corrects_then_executes_and_reviews(self):
        refs,bad=self.proposal();self.grant['deliverables']={'catalog':'application/json'}
        self.create(inputs=refs);self.rt.tick('job');good=copy.deepcopy(bad);good['tasks'][0].pop('outputs')
        result,script=self.invoke([('job_delegate',bad),('job_delegate',good)])
        self.assertEqual(result,{'outcome':'yielded'})
        self.assertEqual(len(script.requests),2)
        names={t['name'] for t in script.requests[1]['tools'][0]['functionDeclarations']}
        self.assertEqual(names,{'job_delegate','job_catalog'})
        states=[m for m in script.requests[1]['contents'] if working_context.state(m)]
        state=json.loads(states[-1]['parts'][0]['text'].removeprefix(working_context.STATE_PREFIX))
        self.assertEqual(state['pending_submission']['proposal'],bad)
        self.assertIn('tasks[0].outputs',state['pending_submission']['diagnostic'])
        events=self.rt.db.execute("SELECT kind,data FROM production_events WHERE kind LIKE 'owner_submission_%' ORDER BY id").fetchall()
        self.assertEqual([e['kind'] for e in events],['owner_submission_rejected','owner_submission_resolved'])
        self.assertEqual(json.loads(events[0]['data'])['pending']['proposal'],bad)
        self.assertEqual(self.session().pending_submission,None)
        task='collect'
        self.run_worker(task,lambda f:[('operation_submit',dict(request_key='s'+str(n),revision=n,records=[dict(item='s'+str(n),options=[],gap='No supported alternative in the supplied fixture')])) for n in range(2)])
        def review(f):
            data=json.loads((Path(f['workspace'])/f['operation_contract']['parameters']['catalog_path']).read_text())
            return [('operation_submit',dict(request_key='r'+str(n),revision=n,records=[dict(item=item['id'],item_sha256=c.digest(item),verdict='supported',reason='Explicit source limitation; no unsupported option')])) for n,item in enumerate(data['items'])]
        self.run_worker(compiled.label(task,'review'),review,decision='accept')
        self.assertEqual(self.rt.task('job',task)['status'],'completed')
        artifact=self.rt.output('job',task,'outputs/result.json')
        s=self.session();s.complete(dict(deliverables_json=c.encoded(dict(catalog=artifact['id'])),summary='Reviewed catalog with disclosed gaps'))
        self.assertTrue(s.completed)

    def test_restart_retains_rejection_and_blocks_history_even_in_same_response(self):
        refs,bad=self.proposal();self.create(inputs=refs);self.rt.tick('job');s=self.session()
        s.call('job_delegate',bad);s.rt.close();s=self.session()
        self.assertEqual(s.pending_submission['proposal'],bad)
        with patch.object(s.working_view,'read',side_effect=AssertionError('History must not execute')):
            result=s.call('job_history',dict(context='invented',offset=0))
            self.assertIn('Correct the pending',result['error'])
        good=copy.deepcopy(bad);good['tasks'][0].pop('outputs')
        self.assertIn('collect',s.call('job_delegate',good)['queued'])
        self.assertIsNone(self.session().pending_submission)

    def test_ignored_corrections_stop_after_two_attempted_reads_and_survive_restart(self):
        refs,bad=self.proposal();self.create(inputs=refs);self.rt.tick('job')
        aid=self.rt.task('job','owner')['latest'];state=self.factory.sessions[aid];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,state['frozen']['backend'])))
        script=Script([('job_delegate',bad),('job_history',dict(context='a',offset=0)),('job_read',dict(artifact=refs[0]['artifact']))])
        with self.assertRaisesRegex(ValueError,'no automatic wake'):
            gemini_worker.execute(state['frozen'],control,script,lambda:(CONFIG,state['frozen']['backend']))
        self.assertEqual(len(script.requests),3)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        self.assertEqual(json.loads((control/'owner-no-progress.json').read_text())['code'],'owner_submission_recovery_exhausted')
        s=self.session()
        with self.assertRaisesRegex(ValueError,'no automatic wake'):s.check_progress(0,0)

    def test_changed_request_ids_do_not_reset_correction_capacity(self):
        refs,bad=self.proposal();self.create(inputs=refs);self.rt.tick('job');s=self.session()
        for n in range(3):
            bad['request_id']='bad'+str(n);self.assertEqual(s.call('job_delegate',bad)['validation']['effect'],'none')
        with self.assertRaisesRegex(ValueError,'no automatic wake'):s.check_progress(3,3)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        self.assertEqual(self.session().pending_submission['rejections'],3)

    def test_contract_lookup_is_bounded_but_second_lookup_allows_correction(self):
        refs,bad=self.proposal();self.create(inputs=refs);self.rt.tick('job');s=self.session();s.call('job_delegate',bad)
        for _ in range(2):s.call('job_catalog',dict(records=True))
        s=self.session();self.assertIsNone(s.progress_hold)
        good=copy.deepcopy(bad);good['tasks'][0].pop('outputs')
        self.assertIn('collect',s.call('job_delegate',good)['queued'])

    def test_committed_conflict_never_becomes_no_effect_recovery(self):
        self.create();self.rt.tick('job');s=self.session();args=dict(request_id='one',tasks=[intents.worker('work')])
        s.call('job_delegate',args)
        args['tasks'][0]['objective']='Changed intent'
        with self.assertRaisesRegex(RuntimeError,'reconciliation'):s.call('job_delegate',args)
        self.assertIsNone(s.pending_submission)

    def test_stale_owner_cannot_persist_rejection(self):
        self.create();self.rt.tick('job');s=self.session()
        self.rt.db.execute("UPDATE production_tasks SET latest='changed' WHERE run='job' AND id='owner'")
        with self.assertRaisesRegex(RuntimeError,'Stale owner'):s.call('job_delegate',{})
        self.assertFalse(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='owner_submission_rejected'").fetchone())

    def test_three_contract_lookups_hold_without_reading_a_third_catalog(self):
        refs,bad=self.proposal();self.create(inputs=refs);self.rt.tick('job');s=self.session();s.call('job_delegate',bad)
        for _ in range(2):s.call('job_catalog',dict(records=True))
        with patch.object(s,'_call',side_effect=AssertionError('Third lookup must not execute')):
            s.call('job_catalog',dict(records=True))
        with self.assertRaisesRegex(ValueError,'no automatic wake'):s.check_progress(4,4)

    def test_native_rejection_corrects_binds_and_runs_real_operation(self):
        from orchestrator import step_runner
        self.grant['operations']=['text.bundle'];self.grant['deliverables']={'report':'text/plain'}
        ref=self.source('The complete supporting evidence.');self.create(inputs=[ref]);self.rt.tick('job')
        task=intents.native('bundle','text.bundle',[dict(artifact=ref['artifact'])]);task['outputs']=[intents.output(media='text/markdown')]
        bad=dict(request_id='native',tasks=[task]);good=copy.deepcopy(bad);good['tasks'][0].pop('outputs')
        self.invoke([('job_delegate',bad),('job_delegate',good)])
        self.rt.tick('job');state=self.factory.sessions[self.rt.task('job','bundle')['latest']];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        self.assertEqual(step_runner.execute(state['frozen'],control)['outcome'],'completed')
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job')
        artifact=self.rt.output('job','bundle',state['frozen']['outputs'][0]['path'])
        self.assertIn('complete supporting evidence',Path(artifact['blob']).read_text())
        self.run_worker(compiled.label('bundle','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]+[('file_write',dict(path=f['outputs'][0]['path'],text='Verified exact evidence and bundled document.'))],decision='accept')
        s=self.session();s.complete(dict(deliverables_json=c.encoded(dict(report=artifact['id'])),summary='Verified report'))
        self.assertTrue(s.completed)

    def test_atomic_rollback_then_recovery_and_idempotent_commit(self):
        self.create();self.rt.tick('job');s=self.session();args=dict(request_id='rollback',tasks=[intents.worker('work')])
        add=s.rt.add_futures
        def interrupted(*a,**kw):
            add(*a,**kw);raise ValueError('Controlled interruption before commit')
        with patch.object(s.rt,'add_futures',side_effect=interrupted):
            result=s.call('job_delegate',args)
        self.assertEqual(result['validation']['effect'],'none')
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        self.assertFalse(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='future_tasks_added'").fetchone())
        s=self.session();receipt=s.call('job_delegate',args)
        self.assertEqual(receipt,s.call('job_delegate',args))
        self.assertEqual(len(self.rt.status('job')['tasks']),3)
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='owner_submission_resolved'").fetchone()[0],1)

    def test_pending_proposal_survives_compaction_for_supported_histories(self):
        refs,bad=self.proposal();self.create(inputs=refs);self.rt.tick('job');s=self.session();s.call('job_delegate',bad)
        for provider in ('gemini','openai','openrouter'):
            content=[dict(role='user',parts=[dict(text='Exact initial job')])]
            history=[dict(role='user',content='Exact initial job')]
            for n in range(8):
                from tests.test_owner_context_retention import ContextTests
                content+=ContextTests.group(self,'gemini','job_read',dict(artifact=str(n)),dict(text='x'*3000),n)
                history+=ContextTests.group(self,provider,'job_read',dict(artifact=str(n)),dict(text='x'*3000),n)
            s.refresh_correction(content,history)
            projected=s.working_view.project(content if provider=='gemini' else history,provider,version=2,maximum=18000,history_available=False)
            self.assertNotIn('job_history',c.encoded(projected))
            states=[m for m in projected if working_context.state(m)]
            value=states[-1]['parts'][0]['text'] if provider=='gemini' else states[-1]['content']
            self.assertEqual(json.loads(value.removeprefix(working_context.STATE_PREFIX))['pending_submission']['proposal'],bad)

    def test_invalid_container_and_ref_diagnostics_are_retained(self):
        self.create();self.rt.tick('job');s=self.session()
        value=s.call('job_delegate',[]);self.assertIn('expected object',value['error'])
        s.observe_outcome(dict(name='job_delegate',arguments=[],result=value))
        value=s.call('job_delegate',dict(request_id='badref',tasks=[intents.worker('work',[dict(artifact='a',task='x',output='result')])]))
        self.assertIn('unsupported field',value['error'])
        self.assertNotEqual(value['error'],'does not match any declared alternative')
        value=s.call('job_delegate',dict(request_id={},tasks=[]))
        self.assertIn('request_id',value['error'])
        self.assertEqual(value['validation']['effect'],'none')
