"""Small text-only planning, circular-review rejection and recovery fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts, report_builder, source_verification, worker_capabilities
from orchestrator.runtime import Runtime
from task_relay import production_planning as planning, text_evidence_planning as policy
from tests import test_production_planning as fixtures
from tests.test_orchestrator import FakeFactory, pair
from tests import test_gemini_executor as api_fixture
from tests.test_general_browser import policy as browser_policy

SOURCE = 'Controller R requires external power. It has no analog output.\n'
CLAIM = 'Controller R requires external power.'


class PlanningTests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    request = fixtures.Tests.request
    action = fixtures.Tests.action
    queue = fixtures.Tests.queue
    row = fixtures.Tests.row
    response = fixtures.Tests.response

    def factual(self):
        result = self.response()
        for t in result['plan']['tasks']:
            t['criteria'] = ['Verify technical accuracy against independent sources.']
        return result

    def supplied(self, row, result):
        path = self.root / 'manufacturer.txt'
        path.write_text(SOURCE)
        ident = self.rt.register(path, 'User supplied manufacturer notes', path='sources/manufacturer.txt')
        source = planning.source_entry(self.rt, ident, 'sources/manufacturer.txt', 'Source notes', 'Supplied source material')
        payload = json.loads(row['context'])
        payload['sources'].append(source)
        row = dict(row)
        row['context'] = contracts.encoded(payload)
        row['context_hash'] = contracts.digest(payload)
        for t in result['plan']['tasks']:
            t.setdefault('inputs', []).append({'artifact': ident, 'path': 'sources/manufacturer.txt',
                                'purpose': 'Exact independent notes', 'authority': 'Supplied source material'})
        return row

    def test_exploration_does_not_become_an_implementation_plan(self):
        row = self.queue(text='What can I do with an old handheld console? Any ideas if I can make it into an assistant?')
        payload = json.loads(row['context'])
        self.assertEqual(payload['request_scope'], 'exploration')
        bad = self.response()
        bad['plan']['tasks'][0]['instruction'] = 'Write a comprehensive engineering blueprint with bill of materials and implementation phases.'
        with self.assertRaisesRegex(ValueError, 'asks for exploration'):
            planning.validate_result(json.dumps(bad), row)
        good = self.response()
        good['plan']['tasks'][0]['instruction'] = 'Offer a few useful ideas, explain feasibility and label unknowns.'
        _, plan = planning.validate_result(json.dumps(good), row)
        self.assertIn('request is exploratory', plan['tasks'][0]['instruction'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_explicit_starter_request_keeps_implementation_scope(self):
        self.assertFalse(policy.exploration('Any ideas? Build me a starter project with firmware and a wiring diagram.'))
        row = self.queue(text='Build me a starter project for an old handheld console.')
        value = self.response()
        value['plan']['tasks'][0]['instruction'] = 'Write starter project source and a bill of materials. Flag physical testing limits.'
        _, plan = planning.validate_result(json.dumps(value), row)
        self.assertNotIn('request is exploratory', plan['tasks'][0]['instruction'])

    def test_explicit_limits_and_revalidation_do_not_create_scope_expansion(self):
        row = self.queue(text='What can I do with an old handheld? Any ideas?')
        value = self.response()
        value['plan']['tasks'][0]['instruction'] = 'Suggest ideas. Do not add a bill of materials or step-by-step implementation roadmap.'
        _, plan = planning.validate_result(json.dumps(value), row)
        again = copy.deepcopy(plan)
        policy.bind(again, json.loads(row['context']))
        self.assertEqual(plan, again)

    def test_file_only_factual_promise_is_rejected_without_explicit_research_request(self):
        row = self.queue(text='Write a guide for an old handheld console.')
        self.assertFalse(json.loads(row['context'])['external_evidence_required'])
        with self.assertRaisesRegex(ValueError, 'independent source inputs'):
            planning.validate_result(json.dumps(self.factual()), row)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_unverified_feasibility_is_an_honest_deliverable_without_fake_sources(self):
        row = self.queue(text='Any ideas if I can make an old handheld into an assistant?')
        value = self.response()
        for task in value['plan']['tasks']:
            task['criteria'] = ['Describe options and label technical feasibility as unverified.']
        _, plan = planning.validate_result(json.dumps(value), row)
        self.assertNotIn('source_verification', plan['tasks'][1])
        self.assertEqual(policy.criteria({'criteria': ['Verify technical accuracy and label unverified claims.']}), [1])

    def test_supplied_sources_bind_exact_reviewer_paths_and_survive_plan_validation(self):
        row = self.queue(text='Write a technical note from supplied documentation.')
        value = self.factual()
        row = self.supplied(row, value)
        _, plan = planning.validate_result(json.dumps(value), row)
        contract = plan['tasks'][1]['source_verification']
        self.assertEqual(contract['sources'], ['sources/manufacturer.txt'])
        self.assertEqual(contract['criteria'], [1])
        self.assertEqual(contracts.plan(plan)['tasks'][1]['source_verification'], contract)
        missing = copy.deepcopy(plan)
        missing['tasks'][1]['inputs'] = [i for i in missing['tasks'][1]['inputs'] if i['path'] != 'sources/manufacturer.txt']
        with self.assertRaisesRegex(ValueError, 'independent source inputs'):
            policy.bind(missing, json.loads(row['context']))

    def test_scoped_research_can_support_factual_review_but_file_written_notes_cannot(self):
        browser = worker_capabilities.entry({'type': 'gemini-browser', 'model': 'fixture'})
        codex = worker_capabilities.entry(pair()['backend'])
        with patch.object(worker_capabilities, 'capture', return_value=[codex, browser]):
            row = self.queue(text='Write a factual technical note from public documentation.')
        value = self.factual()
        author, reviewer = value['plan']['tasks']
        research = copy.deepcopy(author)
        research.update(id='research', objective='Gather public source passages',
            instruction='Save literal source observations and URLs.',
            outputs=[{'path': 'evidence.txt', 'purpose': 'Observed source passages'}],
            criteria=['Record exact source text.'], max_attempts=1,
            browser=browser_policy(interaction_scope=''), worker={'requires': ['files.text', 'browser.use']})
        research.pop('tools', None)
        research.pop('user_gate', None)
        research_review = copy.deepcopy(reviewer)
        research_review.update(id='research_review', review_of='research', dependencies=['research'],
            criteria=research['criteria'], inputs=[{'from_task': 'research', 'output': 'evidence.txt',
                'path': 'candidate/evidence.txt', 'purpose': 'Source assessment', 'authority': 'Unaccepted research'}])
        author['dependencies'] = ['research', 'research_review']
        author['inputs'] = [{'from_task': 'research', 'output': 'evidence.txt', 'path': 'sources/evidence.txt',
            'purpose': 'Source observations', 'authority': 'Reviewed observations'},
            {'from_task': 'research_review', 'output': 'review.md', 'path': 'sources/source-review.md',
             'purpose': 'Source review', 'authority': 'Independent assessment'}]
        value['plan']['tasks'] = [research, research_review, author, reviewer]
        with self.assertRaisesRegex(ValueError, 'independent source inputs'):
            planning.validate_result(json.dumps(value), row)
        reviewer['dependencies'] += ['research', 'research_review']
        reviewer['inputs'] += copy.deepcopy(author['inputs'])
        _, plan = planning.validate_result(json.dumps(value), row)
        self.assertEqual(plan['tasks'][0]['worker']['backend']['type'], 'gemini-browser')
        self.assertEqual(plan['tasks'][-1]['source_verification']['sources'], ['sources/evidence.txt'])
        fake = copy.deepcopy(value)
        fake['plan']['tasks'][0].pop('browser')
        fake['plan']['tasks'][0]['worker'] = {'requires': ['files.text']}
        with self.assertRaisesRegex(ValueError, 'independent source inputs'):
            planning.validate_result(json.dumps(fake), row)

    def test_old_frozen_proposal_is_not_rewritten_with_new_verification(self):
        row = dict(self.queue(text='Write a technical guide.'))
        payload = json.loads(row['context'])
        payload.pop('text_evidence_policy_version')
        payload.pop('request_scope')
        row['context'] = json.dumps(payload)
        _, plan = planning.validate_result(json.dumps(self.factual()), row)
        self.assertNotIn('source_verification', plan['tasks'][1])

    def test_planner_correction_reuses_exact_request_and_does_not_dispatch(self):
        self.queue(text='What can I do with an old handheld console? Any ideas?')
        requests = []
        def generate(row, payload):
            requests.append(copy.deepcopy(payload))
            response = self.response()
            if len(requests) == 1:
                response['plan']['tasks'][0]['instruction'] = 'Write an engineering blueprint and step-by-step implementation roadmap.'
            else:
                response['plan']['tasks'][0]['instruction'] = 'Suggest three ideas with clear unverified limits.'
            return json.dumps(response), {}
        worker = planning.Worker(self.state, generate)
        worker.tick()
        worker.tick()
        self.assertEqual(self.row()['status'], 'ready', self.row()['error'])
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]['original_request'], requests[1]['original_request'])
        self.assertIn('asks for exploration', requests[1]['structural_correction']['error'])
        self.assertEqual(self.factory.calls, [])


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.factory = FakeFactory()
        self.rt = Runtime(self.root / 'runtime', self.factory)
        self.addCleanup(self.rt.db.close)
        source = self.root / 'source.txt'
        source.write_text(SOURCE)
        ident = self.rt.register(source, 'Independent fixture notes', path='source.txt')
        self.plan = pair(gate='User selects the note', max_attempts=1)
        for t in self.plan['tasks']:
            t['criteria'] = ['Verify technical accuracy against independent sources.']
            t.setdefault('inputs', []).append({'artifact': ident, 'path': 'source.txt',
                'purpose': 'Independent source', 'authority': 'User supplied documentation'})
        policy.bind(self.plan, {'text_evidence_policy_version': 1,
            'sources': [{'artifact': ident, 'path': 'source.txt'}]})
        self.rt.create(self.plan)
        self.rt.tick('demo')
        writer = self.rt.task('demo', 'produce')['latest']
        self.factory.finish(writer)
        (self.factory.sessions[writer]['workspace'] / 'output.txt').write_text(CLAIM)
        self.rt.tick('demo')
        self.aid = self.rt.task('demo', 'review')['latest']
        self.frozen = self.factory.sessions[self.aid]['frozen']
        self.ws = self.factory.sessions[self.aid]['workspace']

    def evidence(self):
        return {'claims': [{'candidate_path': 'candidate.txt', 'claim': CLAIM,
            'verdict': 'supported', 'reason': 'The source explicitly requires external power.',
            'supports': [{'path': 'source.txt', 'sha256': hashlib.sha256(SOURCE.encode()).hexdigest(), 'quote': CLAIM}]}]}

    def report(self, evidence=None, decision='accept'):
        return {'assignment_id': self.aid, 'summary': 'Source support reviewed; physical testing remains unverified.',
            'decision': decision, 'instruction': 'Correct unsupported claims.' if decision == 'revise' else '',
            'findings': [], 'checks': [{'criterion': 1, 'passed': decision == 'accept',
                'evidence': contracts.encoded(self.evidence() if evidence is None else evidence)}]}

    def finish(self, value):
        self.factory.finish(self.aid, decision=value['decision'])
        (self.ws / '.relay/result.json').write_text(json.dumps(value))
        self.rt.tick('demo', dispatch=False)

    def test_circular_section_reference_is_blocked_by_supervisor(self):
        value = self.report()
        value['checks'][0]['evidence'] = 'Section 4 provides technically accurate instructions.'
        self.finish(value)
        self.assertEqual(self.rt.task('demo', 'review')['status'], 'blocked')
        self.assertNotEqual(self.rt.task('demo', 'produce')['status'], 'awaiting_user')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0], 0)
        self.assertFalse(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='model_review_accepted'").fetchone())

    def test_exact_source_support_allows_review_but_never_user_acceptance(self):
        value = self.report()
        self.finish(value)
        self.assertEqual(self.rt.task('demo', 'produce')['status'], 'awaiting_user')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0], 0)

    def test_candidate_cannot_be_cited_as_its_own_source(self):
        data = self.evidence()
        support = data['claims'][0]['supports'][0]
        support.update(path='candidate.txt', sha256=hashlib.sha256(CLAIM.encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, 'cannot substantiate'):
            contracts.report(self.report(data), self.frozen)

    def test_forged_source_hash_quote_and_claim_are_rejected(self):
        for field, replacement, message in [('sha256', '0' * 64, 'source version'),
                ('quote', 'This controller has an analog output.', 'Support quote'),
                ('claim', 'This controller has an analog output.', 'Audited claim')]:
            with self.subTest(field=field):
                data = self.evidence()
                target = data['claims'][0] if field == 'claim' else data['claims'][0]['supports'][0]
                target[field] = replacement
                with self.assertRaisesRegex(ValueError, message):
                    contracts.report(self.report(data), self.frozen)

    def test_tampered_input_does_not_pass_even_with_an_original_hash(self):
        (self.ws / 'source.txt').chmod(0o600)
        (self.ws / 'source.txt').write_text('Different source.')
        with self.assertRaisesRegex(ValueError, 'frozen hash'):
            contracts.report(self.report(), self.frozen)

    def test_uncertain_claim_requires_revision_and_retains_original_candidate(self):
        data = self.evidence()
        data['claims'][0]['verdict'] = 'uncertain'
        with self.assertRaisesRegex(ValueError, 'Unsupported or uncertain'):
            contracts.report(self.report(data), self.frozen)
        revised = self.report(data, decision='revise')
        self.finish(revised)
        self.assertEqual(self.rt.task('demo', 'produce')['status'], 'blocked')
        self.assertEqual((self.ws / 'candidate.txt').read_text(), CLAIM)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0], 0)

    def test_typed_report_is_bound_to_same_source_contract(self):
        typed = {'summary': 'Source support audited.', 'decision': 'accept', 'instruction': '', 'findings': [],
                 'checks': {'c1': {'passed': True, 'evidence': self.evidence()}}}
        value = contracts.report(typed, self.frozen)
        self.assertEqual(json.loads(value['checks'][0]['evidence']), self.evidence())
        changed = copy.deepcopy(self.frozen)
        changed['source_verification']['sources'] = ['candidate.txt']
        with self.assertRaises(ValueError):
            source_verification.validate_assignment(changed)


class WorkerTests(unittest.TestCase):
    setUp = api_fixture.Tests.setUp
    tearDown = api_fixture.Tests.tearDown
    input = api_fixture.Tests.input

    def test_rejected_circular_finish_can_be_corrected_in_same_text_attempt(self):
        from orchestrator.gemini_worker import execute
        self.frozen['review_of'] = 'produce'
        self.frozen['outputs'] = [{'path': 'review.md', 'purpose': 'Independent review'}]
        self.input('candidate.txt', CLAIM, from_task='produce')
        self.input('source.txt', SOURCE)
        self.frozen['source_verification'] = {'version': 1, 'criteria': [1],
            'sources': ['source.txt'], 'candidates': ['candidate.txt']}
        self.frozen['report_contract'] = report_builder.freeze(self.frozen)
        report = {'summary': 'Documentation support only; physical testing unverified.', 'decision': 'accept',
            'instruction': '', 'findings': [], 'checks': {'c1': {'passed': True, 'evidence': {
                'claims': [{'candidate_path': 'candidate.txt', 'claim': CLAIM, 'verdict': 'supported',
                    'reason': 'The manufacturer notes state this requirement.', 'supports': [
                        {'path': 'source.txt', 'sha256': hashlib.sha256(SOURCE.encode()).hexdigest(), 'quote': CLAIM}]}]}}}}
        calls = []
        class Client:
            def request(_, path, payload, **kwargs):
                calls.append(copy.deepcopy(payload))
                value = copy.deepcopy(report)
                if len(calls) == 1:
                    value['checks']['c1']['evidence'] = 'Section 4 contains accurate wiring.'
                return {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [
                    {'functionCall': {'name': 'finish', 'args': {'report_json': json.dumps(value)}}}]}}]}
        result = execute(self.frozen, self.control, Client(), lambda: (api_fixture.CONFIG, api_fixture.BACKEND))
        self.assertEqual(result['decision'], 'accept')
        self.assertEqual(len(calls), 2)
        self.assertIn('structured independent source evidence', json.loads((self.control / 'tool-01-00.json').read_text())['result']['error'])
        self.assertEqual((self.ws / 'candidate.txt').read_text(), CLAIM)
        self.assertIn('Documentation support only', (self.ws / 'review.md').read_text())


if __name__ == '__main__':
    unittest.main()
