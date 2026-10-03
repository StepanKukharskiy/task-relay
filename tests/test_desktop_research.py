"""Research choice identity and source visibility without provider/browser work."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from orchestrator import executors
from task_relay import desktop_plans, desktop_sources, text_evidence_planning as policy
from tests import test_desktop_plans as desktop_fixture
from tests import test_desktop_workspace as workspace_fixture
from tests import test_text_source_verification as planning_fixture


class ChoiceTests(unittest.TestCase):
    setUp = desktop_fixture.DesktopPlansTests.setUp

    def create(self, identity=None, mode='suggest'):
        return desktop_plans.create('Any ideas for an old controller?', '', None, None,
            identity or str(uuid.uuid4()), self.paths, research_mode=mode)

    def test_choice_is_atomic_and_an_unchanged_retry_never_submits_again(self):
        ident = str(uuid.uuid4())
        first = self.create(ident, 'sources')
        self.assertEqual(first['plan_id'], self.create(ident, 'sources')['plan_id'])
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError, 'different research choice'):
            self.create(ident, 'none')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM desktop_plan_requests').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT research_mode FROM desktop_plan_preferences').fetchone()[0], 'sources')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_source_choice_reaches_frozen_planning_without_rewriting_the_request(self):
        self.create(mode='sources')
        with patch('task_relay.orchestrator_chat.provider', return_value=('openai', 'fixture-model')), patch.object(executors, 'available'), patch('task_relay.gemini.read_config', return_value={'api_key': 'fixture', 'models': {'text': 'fixture-search'}}):
            desktop_plans.process_requests(self.state)
        row = self.state.db.execute('SELECT request,context FROM production_plans').fetchone()
        self.assertEqual(row['request'], 'Any ideas for an old controller?')
        context = json.loads(row['context'])
        self.assertEqual(context['research_mode'], 'sources')
        self.assertEqual(context['request_scope'], 'exploration')
        self.assertIn('source-backed answer', context['planner_instructions'])
        self.assertEqual(context['options']['optional_research_capabilities'], ['web.sources'])
        self.assertNotIn('web.sources', context['options'].get('step_capabilities', []))
        self.assertEqual(next(e for e in context['graph_operations'] if e['id']=='web.sources')['configured_model'], 'fixture-search')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_default_request_freezes_advice_but_explicit_choices_keep_authority(self):
        self.create(mode='suggest');self.create(mode='none');self.create(mode='sources')
        with patch('task_relay.orchestrator_chat.provider', return_value=('openai','fixture-model')), patch.object(executors,'available'), patch('task_relay.gemini.read_config',return_value={'api_key':'fixture','models':{'text':'fixture-search'}}):
            for _ in range(3):desktop_plans.process_requests(self.state)
        rows=self.state.db.execute('SELECT * FROM production_plans').fetchall()
        self.assertEqual(len(rows),3)
        for row in rows:
            context=json.loads(row['context']);mode=context['research_mode']
            self.assertEqual(context.get('research_advice_version')==1,mode=='suggest')
            self.assertEqual('research_advice' in context['response_contract']['schema']['required'],mode=='suggest')
            self.assertEqual(context['options'].get('optional_research_capabilities',[]),[] if mode=='none' else ['web.sources'])
            self.assertEqual(row['request'],'Any ideas for an old controller?')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plan_calls').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_legacy_receipt_defaults_to_suggestion_and_cannot_change_choice_on_retry(self):
        ident = str(uuid.uuid4())
        first = self.create(ident)
        with self.state.db:
            self.state.db.execute('DELETE FROM desktop_plan_preferences')
        self.assertEqual(first['plan_id'], self.create(ident)['plan_id'])
        with self.assertRaisesRegex(desktop_plans.DesktopPlanError, 'different research choice'):
            self.create(ident, 'sources')


class PolicyTests(unittest.TestCase):
    setUp = planning_fixture.PlanningTests.setUp
    tearDown = planning_fixture.PlanningTests.tearDown
    request = planning_fixture.PlanningTests.request
    action = planning_fixture.PlanningTests.action
    queue = planning_fixture.PlanningTests.queue
    row = planning_fixture.PlanningTests.row
    response = planning_fixture.PlanningTests.response
    supplied = planning_fixture.PlanningTests.supplied

    def test_research_choice_cannot_be_satisfied_by_disclaimers(self):
        from task_relay import production_planning as planning
        row = dict(self.queue(text='Any ideas for an old controller?'))
        context = json.loads(row['context'])
        context.update(research_choice_version=1, research_mode='sources')
        row['context'] = json.dumps(context)
        value = self.response()
        for task in value['plan']['tasks']:
            task['criteria'] = ['Offer ideas with explicit unverified limits.']
        with self.assertRaisesRegex(ValueError, 'independent source inputs'):
            planning.validate_result(json.dumps(value), row)
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_supplied_sources_satisfy_choice_without_forcing_a_browser_step(self):
        from task_relay import production_planning as planning
        row = dict(self.queue(text='Any ideas for an old controller?'))
        value = self.response()
        row = self.supplied(row, value)
        context = json.loads(row['context'])
        context.update(research_choice_version=1, research_mode='sources')
        row['context'] = json.dumps(context)
        _, plan = planning.validate_result(json.dumps(value), row)
        self.assertEqual(len(plan['tasks']), 2)
        self.assertEqual(plan['tasks'][1]['source_verification']['sources'], ['sources/manufacturer.txt'])
        self.assertEqual(plan['tasks'][0]['criteria'], plan['tasks'][1]['criteria'])
        again = copy.deepcopy(plan)
        policy.bind(again, context)
        self.assertEqual(plan, again)

    def test_no_new_research_and_legacy_choices_preserve_their_boundaries(self):
        value = self.response()['plan']
        value['tasks'][0]['browser'] = {'fixture': True}
        with self.assertRaisesRegex(ValueError, 'excludes new web research'):
            policy.bind(copy.deepcopy(value), {'text_evidence_policy_version': 1, 'research_choice_version': 1, 'research_mode': 'none'})
        # Old frozen plans have no new research-choice authority.
        legacy = self.response()['plan']
        before = copy.deepcopy(legacy)
        policy.bind(legacy, {'text_evidence_policy_version': 1, 'research_mode': 'sources'})
        self.assertEqual(legacy, before)

    def test_optional_public_search_can_feed_a_reviewed_answer_without_becoming_mandatory(self):
        from orchestrator import execution, contracts
        from task_relay import production_planning as planning, planning_contract
        row = dict(self.queue(text='Any ideas for an old controller?'))
        options = json.loads(row['options'])
        options['optional_research_capabilities'] = ['web.sources']
        context = json.loads(row['context'])
        with patch('task_relay.gemini.read_config', return_value={'api_key': 'fixture', 'models': {'text': 'fixture-search'}}):
            operation = next(e for e in execution.catalog() if e['id']=='web.sources')
        context.update(research_choice_version=1, research_mode='sources', options=options,
                       graph_operations=[operation], response_contract=planning_contract.contract(options))
        row.update(options=contracts.encoded(options), context=contracts.encoded(context))
        value = self.response()
        author, reviewer = value['plan']['tasks']
        search = copy.deepcopy(author)
        search.update(id='search', objective='Collect documentation', instruction='Read documentation for the controller.',
            execution={'capability':'web.sources','version':1,'parameters':{'queries':['controller protocol documentation'],'domains':[]}},
            inputs=[], outputs=[{'path':'delivery/source-pack.json','purpose':'Public source candidates','media_type':'application/json'}],
            criteria=copy.deepcopy(execution.REGISTRY['web.sources']['criteria']), limits={'seconds':1800,'tool_calls':1,'output_bytes':2000000}, max_attempts=1, tools=[])
        search.pop('user_gate',None)
        source={'from_task':'search','output':'delivery/source-pack.json','path':'sources/source-pack.json',
                'purpose':'Source candidates','authority':'Unverified source pack','media_type':'application/json'}
        assessment=copy.deepcopy(reviewer)
        assessment.update(id='search_review',review_of='search',dependencies=['search'],inputs=[{**source,'path':'candidate/source-pack.json'}],criteria=copy.deepcopy(search['criteria']))
        review={'from_task':'search_review','output':'review.md','path':'sources/source-review.md','purpose':'Source assessment','authority':'Independent review'}
        author.update(dependencies=['search','search_review'],inputs=[source,review])
        reviewer['dependencies']+=['search','search_review']
        reviewer['inputs']+=[source,review]
        value['plan']['tasks']=[search,assessment,author,reviewer]
        _, plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual(plan['tasks'][0]['execution']['parameters']['model'],'fixture-search')
        self.assertEqual(plan['tasks'][-1]['source_verification']['sources'],['sources/source-pack.json'])
        # Default orchestrator advice can select the same frozen, reviewed route.
        recommended=dict(row);recommended_context=copy.deepcopy(context)
        recommended_options=copy.deepcopy(options);recommended_options['research_advice_version']=1
        recommended_context.update(research_mode='suggest',research_advice_version=1,options=recommended_options,
            response_contract=planning_contract.contract(recommended_options))
        recommended.update(context=contracts.encoded(recommended_context),options=contracts.encoded(recommended_options))
        advised=copy.deepcopy(value)
        advised['research_advice']={'recommended_mode':'sources','requirement':'optional',
            'reason':'Check documented controller interfaces before recommending compatible projects.',
            'questions':['Which interfaces do supported projects require?']}
        _,recommended_plan=planning.validate_result(json.dumps(advised),recommended)
        self.assertEqual(recommended_plan['tasks'][0]['execution']['parameters']['model'],'fixture-search')
        self.assertIn('source_verification',recommended_plan['tasks'][-1])
        advised['research_advice']['recommended_mode']='none'
        for task in advised['plan']['tasks'][2:]:task['criteria']=['Verify factual accuracy against independent sources.']
        with self.assertRaisesRegex(ValueError,'not included in the planning scope'):
            planning.validate_result(json.dumps(advised),recommended)
        no_review=copy.deepcopy(value)
        no_review['plan']['tasks'][2]['inputs']=[source]
        with self.assertRaisesRegex(ValueError,'receive the independent research review'):
            planning.validate_result(json.dumps(no_review),row)
        unauthorized=dict(row);bad_context=copy.deepcopy(context);bad_context['research_mode']='suggest';unauthorized['context']=contracts.encoded(bad_context)
        bad_value=copy.deepcopy(value)
        bad_value['plan']['tasks'][2]['criteria']=['Verify factual accuracy against independent sources.']
        bad_value['plan']['tasks'][3]['criteria']=copy.deepcopy(bad_value['plan']['tasks'][2]['criteria'])
        with self.assertRaisesRegex(ValueError,'not included in the planning scope'):
            planning.validate_result(json.dumps(bad_value),unauthorized)
        self.assertEqual(self.factory.calls,[])


class AdviceTests(unittest.TestCase):
    setUp = PolicyTests.setUp
    tearDown = PolicyTests.tearDown
    request = PolicyTests.request
    action = PolicyTests.action
    queue = PolicyTests.queue
    row = PolicyTests.row
    response = PolicyTests.response
    supplied = PolicyTests.supplied
    def advised(self, mode='none', requirement='optional'):
        from task_relay import planning_contract
        row = dict(self.queue(text='Any ideas for an old handheld console?'))
        context = json.loads(row['context'])
        options = json.loads(row['options'])
        options['research_advice_version'] = 1
        context.update(research_advice_version=1, research_choice_version=1,
                       research_mode='suggest', options=options,
                       response_contract=planning_contract.contract(options))
        row.update(context=json.dumps(context), options=json.dumps(options))
        value = self.response()
        value['research_advice'] = {'recommended_mode': mode, 'requirement': requirement,
            'reason': 'Offer imaginative uses for the console; documentation can check the link protocol.',
            'questions': [] if requirement=='unnecessary' else ['Which link protocol and power limits are documented?']}
        return row, value

    def test_missing_advice_is_corrected_without_starting_workers(self):
        from task_relay import production_planning as planning
        row, value = self.advised()
        context=json.loads(row['context'])
        with self.state.db:
            self.state.db.execute('UPDATE production_plans SET options=?,context=?,context_hash=? WHERE id=?',
                (row['options'],row['context'],planning.c.digest(context),row['id']))
        missing=copy.deepcopy(value);missing.pop('research_advice')
        responses=iter([missing,value]);calls=[]
        def provider(_,payload):
            calls.append(payload)
            return json.dumps(next(responses)), {'total_tokens':1}
        worker=planning.Worker(self.state,provider)
        worker.tick();worker.tick()
        saved=self.row()
        self.assertEqual(saved['status'],'ready',saved['error'])
        self.assertEqual(len(calls),2)
        self.assertIn('research_advice',calls[1]['structural_correction']['error'])
        self.assertEqual(json.loads(saved['result'])['research_advice'],value['research_advice'])
        self.assertEqual(json.loads(saved['plan'])['origin']['research_advice'],value['research_advice'])
        self.assertIn(value['research_advice']['reason'],planning.preview(saved))
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_creative_and_optional_advice_preserve_a_quick_answer(self):
        from task_relay import production_planning as planning
        for requirement in ('optional','unnecessary'):
            row,value=self.advised(requirement=requirement)
            _,plan=planning.validate_result(json.dumps(value),row)
            self.assertEqual(len(plan['tasks']),2)
            self.assertNotIn('source_verification',plan['tasks'][1])
            self.assertEqual(plan['origin']['research_advice'],value['research_advice'])

    def test_required_sources_cannot_be_replaced_with_disclaimers(self):
        from task_relay import production_planning as planning
        row,value=self.advised('sources','required')
        with self.assertRaisesRegex(ValueError,'independent source inputs'):
            planning.validate_result(json.dumps(value),row)
        row=self.supplied(row,value)
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual(len(plan['tasks']),2)
        self.assertIn('source_verification',plan['tasks'][1])
        # Advice changes the proposed graph, never the user's saved choice/request.
        self.assertEqual(json.loads(row['context'])['research_mode'],'suggest')
        self.assertEqual(plan['origin']['research_advice']['requirement'],'required')

    def test_contradictory_advice_and_retroactive_advice_are_rejected(self):
        from task_relay import production_planning as planning
        row,value=self.advised('none','required')
        with self.assertRaisesRegex(ValueError,'must agree'):
            planning.validate_result(json.dumps(value),row)
        value['research_advice']['requirement']='unnecessary'
        with self.assertRaisesRegex(ValueError,'must agree'):
            planning.validate_result(json.dumps(value),row)
        value['research_advice']['questions']=[]
        old=dict(row);context=json.loads(row['context']);context.pop('research_advice_version')
        old['context']=json.dumps(context)
        with self.assertRaisesRegex(ValueError,'not included in the saved planning contract'):
            planning.validate_result(json.dumps(value),old)
        graph=copy.deepcopy(value['plan']);graph['tasks'][0]['browser']={'fixture':True}
        with self.assertRaisesRegex(ValueError,'excludes new web research'):
            policy.bind(graph,{**json.loads(row['context']),'recommended_research_mode':'none'})


class SourceTests(unittest.TestCase):
    setUp = workspace_fixture.WorkspaceTests.setUp

    def attempt(self):
        self.rt.tick('demo')
        return self.rt.task('demo', 'produce')['latest']

    def view(self):
        plan = json.loads(self.state.db.execute("SELECT plan FROM production_runs WHERE id='demo'").fetchone()[0])
        return desktop_sources.inspect(self.state.db, 'demo', plan)

    def browser(self, attempt, ident, status='observed', url='https://docs.example/spec'):
        from task_relay.browser_journal import Journal
        Journal(self.state.db)
        with self.state.db:
            self.state.db.execute('INSERT INTO general_browser_actions VALUES (?,?,?,?,?,?,?)',
                (attempt, ident, 'fixture', '{}', status,
                 json.dumps({'url': url, 'title': 'Specification', 'text': 'Observed spec.', 'observation': 'snapshot-one'}), 1))

    def test_model_written_links_and_declared_origins_are_not_consulted_sources(self):
        self.attempt()
        workspace = self.factory.sessions[self.rt.task('demo', 'produce')['latest']]['workspace']
        (workspace / 'output.txt').write_text('Recommended: https://docs.example/unread')
        view = self.view()
        self.assertEqual(view['pages'], [])
        self.assertEqual(view['steps'], [])
        self.assertIn('No successful page read', view['message'])
        from task_relay.desktop_workspace import detail
        self.assertEqual(detail('demo', self.paths)['research'], view)
        proposed = desktop_sources.proposal({'tasks': [{'id': 'research', 'objective': 'Read documentation', 'browser': {'allowed_origins': ['https://docs.example']}}]})
        self.assertEqual(proposed['status'], 'proposed')
        self.assertEqual(proposed['pages'], [])

    def test_only_observed_attempt_receipts_are_links_and_other_jobs_cannot_open_them(self):
        attempt = self.attempt()
        self.browser(attempt, 'observed')
        self.browser(attempt, 'uncertain', 'uncertain', 'https://docs.example/uncertain')
        self.browser('another-attempt', 'foreign', url='https://docs.example/foreign')
        self.browser(attempt, 'local', url='https://localhost/private')
        view = self.view()
        self.assertEqual([p['url'] for p in view['pages']], ['https://docs.example/spec'])
        self.assertEqual(desktop_sources.source_url('demo', view['pages'][0]['id'], self.paths)['url'], 'https://docs.example/spec')
        with self.assertRaises(desktop_plans.DesktopPlanError):
            desktop_sources.source_url('demo', '0'*64, self.paths)
        self.assertEqual(len(self.factory.calls), 1)

    def test_bad_receipts_are_visible_as_incomplete_instead_of_breaking_job_inspection(self):
        attempt = self.attempt()
        self.browser(attempt, 'invalid')
        with self.state.db:
            self.state.db.execute("UPDATE general_browser_actions SET result='bad json'")
        self.assertEqual(self.view()['pages'], [])
        self.assertTrue(self.view()['partial'])

    def test_web_sources_search_candidates_are_separate_from_fetched_pages(self):
        attempt = self.attempt()
        control = self.root / 'source-control'
        query = control / 'query-01'
        query.mkdir(parents=True)
        (query/'page-1.json').write_text(json.dumps({'ok': True, 'url': 'https://docs.example/read', 'text': 'Read spec', 'sha256': 'a'*64}))
        (query/'search-1.json').write_text(json.dumps({'status': 'responded', 'response': {'candidates': [{'groundingMetadata': {'groundingChunks': [{'web': {'uri': 'https://docs.example/search-only', 'title': 'Result'}}]}}]}}))
        with self.state.db:
            frozen = json.loads(self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?', (attempt,)).fetchone()[0])
            frozen['execution'] = {'capability': 'web.sources'}
            self.state.db.execute('UPDATE production_attempts SET frozen=?,session=? WHERE id=?', (json.dumps(frozen), json.dumps({'control': str(control)}), attempt))
        self.assertEqual({p['url']: p['kind'] for p in self.view()['pages']}, {'https://docs.example/read': 'page', 'https://docs.example/search-only': 'search_result'})

    def test_native_receipts_bind_exact_worker_and_changed_captures_are_not_links(self):
        from task_relay.computer_sessions import initialize
        attempt = self.attempt()
        initialize(self.state.db)
        folder = self.root/'native-receipt'; folder.mkdir()
        (folder/'page.txt').write_text('Observed documentation')
        (folder/'evidence.json').write_text(json.dumps({'url': 'https://docs.example/native'}))
        files = {name: {'sha256': hashlib.sha256((folder/name).read_bytes()).hexdigest()} for name in ('page.txt', 'evidence.json')}
        receipt = json.dumps({'folder': str(folder), 'files': files})
        with self.state.db:
            self.state.db.execute('INSERT INTO relay_computer_assignments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                ('native-session', 'owned-job', 'worker:'+attempt, 'Exact fixture', '{}', '{}', str(folder), 'completed', 1, 'https://docs.example/native', 2, 1))
            self.state.db.execute('INSERT INTO relay_computer_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('native-action', 'owned-job', 'native-session', 1, 0, '{}', 'completed', receipt, None, 0, 1))
        self.assertEqual(self.view()['pages'][0]['url'], 'https://docs.example/native')
        (folder/'page.txt').write_text('Changed')
        self.assertEqual(self.view()['pages'], [])
        self.assertTrue(self.view()['partial'])
