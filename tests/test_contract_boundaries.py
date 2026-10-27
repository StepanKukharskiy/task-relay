"""Shared compiler boundaries using small text fixtures; no providers or UI."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import contracts, deliverable_outputs, execution, source_verification, final_quality
from task_relay import production_planning as planning, text_evidence_planning
from tests import test_production_planning as fixtures
from tests import test_request_contract as intake
from tests import test_text_source_verification as evidence_fixture
from tests.intake_fixtures import outcome, work
from tests.test_mixed_execution import operation, upstream
from tests.test_orchestrator import pair


class OutcomeTests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    queue = intake.Tests.queue
    row = fixtures.Tests.row
    action = fixtures.Tests.action

    def draft(self, capability='text.bundle'):
        value = fixtures.Tests.response(self)
        author, review = value['plan']['tasks']
        author.pop('user_gate')
        author['outputs'][0]['media_type'] = 'text/plain'
        source = upstream('produce', 'output.txt')
        if capability == 'pptx.create':
            author['outputs'][0].update(path='slides.json', media_type='application/json')
            review['inputs'][0].update(output='slides.json', media_type='application/json')
            source.update(output='slides.json', media_type='application/json')
        assessment = upstream('review', 'review.md')
        bundle = operation('bundle', capability, [source, assessment],
                           ['produce', 'review'], user_gate='Select final bundle')
        output = 'bundle.txt'
        if capability == 'pptx.create':
            output = 'deck.pptx'
            bundle['outputs'][0].update(path=output, media_type=execution.REGISTRY[capability]['output_type'])
        bundle = contracts.assignment(bundle)
        bundle['inputs'][1].pop('media_type')
        inspector = copy.deepcopy(review)
        inspector.update(id='bundle_review', review_of='bundle', dependencies=['bundle'],
            criteria=copy.deepcopy(bundle['criteria']), inputs=[{
                'from_task': 'bundle', 'output': output, 'path': 'candidate/'+output,
                'purpose': 'Review final bundle', 'authority': 'Unaccepted result',
                'media_type': bundle['outputs'][0]['media_type']}])
        value['plan']['tasks'] += [bundle, inspector]
        value['deliverable_map'] = {'result': {'task': 'bundle', 'output': output}}
        return value

    def queued(self, capability='text.bundle'):
        contract = work([outcome('result', format='.pptx' if capability=='pptx.create' else '.txt',
            checks=['nonempty'], validation=[
            'Contains all required item IDs.', 'Labels unknown data explicitly.'])])
        return self.queue(text='Produce the requested reviewed bundle.', contract=contract,
                          action=self.action(step_capabilities=[capability]))

    def test_semantics_stay_on_independent_review_and_raw_response_is_preserved(self):
        self.queued()
        raw = json.dumps(self.draft())
        worker = planning.Worker(self.state, lambda *_: (raw, {}))
        worker.tick()
        row = self.row()
        self.assertEqual(row['status'], 'ready', row['error'])
        self.assertEqual(row['calls'], 1)
        self.assertEqual(self.state.db.execute('SELECT response FROM production_plan_calls').fetchone()[0], raw)
        plan = json.loads(row['plan'])
        bundle, inspector = plan['tasks'][-2:]
        self.assertEqual(bundle['criteria'], execution.REGISTRY['text.bundle']['criteria'])
        self.assertEqual(inspector['criteria'][1:], ['Contains all required item IDs.', 'Labels unknown data explicitly.', final_quality.criterion('result')])
        self.assertEqual(bundle['inputs'][1]['media_type'], 'text/markdown')
        execution.validate(bundle)
        contracts.plan(plan)
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)
        report = {'assignment_id': 'fixture', 'summary': 'Reviewed', 'decision': 'accept', 'instruction': '',
                  'checks': [{'criterion': n, 'passed': n != 2, 'evidence': 'Fixture inspection'}
                             for n in range(1, 5)]}
        with self.assertRaisesRegex(ValueError, 'reported failed criteria'):
            contracts.report(report, {**inspector, 'assignment_id': 'fixture'})
        weakened = copy.deepcopy(plan)
        weakened['tasks'][-1]['criteria'] = bundle['criteria']
        with self.assertRaisesRegex(ValueError, 'exact criteria|without weakening'):
            contracts.plan(weakened)
        missing = copy.deepcopy(plan)
        missing['tasks'].pop()
        with self.assertRaisesRegex(ValueError, 'independent reviewer'):
            contracts.plan(missing)
        deliverable_outputs.check_delivery(bundle, lambda _: b'Nonempty fixture bundle')

    def test_pptx_renderer_keeps_fixed_checks_and_preserves_outcome_review(self):
        with patch('orchestrator.pptx_document.available'):
            row = self.queued('pptx.create')
        _, plan = planning.validate_result(json.dumps(self.draft('pptx.create')), row)
        creator, reviewer = plan['tasks'][-2:]
        self.assertEqual(creator['criteria'], execution.REGISTRY['pptx.create']['criteria'])
        self.assertEqual(reviewer['criteria'], deliverable_outputs.review_criteria(creator)+[final_quality.criterion('result')])
        self.assertEqual(len(reviewer['criteria']), 4)
        self.assertEqual(creator['inputs'][1]['media_type'], 'text/markdown')
        execution.validate(creator)
        contracts.plan(plan)

    def test_historical_planning_context_does_not_acquire_new_policy(self):
        row = dict(self.queued())
        payload = json.loads(row['context'])
        payload.pop('outcome_review_policy_version')
        row['context'] = json.dumps(payload)
        with self.assertRaisesRegex(ValueError, 'registered operation criteria'):
            planning.validate_result(json.dumps(self.draft()), row)

    def test_versioned_validation_cannot_be_put_on_an_agent_or_malformed(self):
        assignment = {'outputs': [{'path': 'result.txt'}], 'output_contracts': [
            {'version': 2, 'path': 'result.txt', 'format': '.txt', 'checks': ['nonempty'], 'validation': ['Complete']}]}
        with self.assertRaisesRegex(ValueError, 'semantic output'):
            deliverable_outputs.validate_assignment(assignment)
        assignment['execution'] = {'capability': 'text.bundle'}
        for version in (True, 1, 3):
            assignment['output_contracts'][0]['version'] = version
            with self.assertRaisesRegex(ValueError, 'semantic output'):
                deliverable_outputs.validate_assignment(assignment)


class EvidenceTests(unittest.TestCase):
    def graph(self):
        plan = pair(gate='Select final answer', max_attempts=1)
        author, reviewer = plan['tasks']
        prep, prep_review = copy.deepcopy(author), copy.deepcopy(reviewer)
        prep.update(id='inventory', inputs=[{'artifact': 'image', 'path': 'source.jpg',
            'purpose': 'Visible objects', 'authority': 'Visual reference'}])
        prep.pop('user_gate')
        prep_review.update(id='inventory_review', review_of='inventory', dependencies=['inventory'], inputs=[
            {'from_task': 'inventory', 'output': 'output.txt', 'path': 'candidate.txt',
             'purpose': 'Inventory candidate', 'authority': 'Unaccepted'}, *copy.deepcopy(prep['inputs'])])
        author.update(dependencies=['inventory', 'inventory_review'], inputs=[
            {'from_task': 'inventory', 'output': 'output.txt', 'path': 'inventory.txt', 'purpose': 'Preparation', 'authority': 'Reviewed'},
            {'artifact': 'notes', 'path': 'source.txt', 'purpose': 'Independent documentation', 'authority': 'Supplied source'}])
        reviewer['inputs'] += [copy.deepcopy(author['inputs'][1])]
        plan['tasks'] = [prep, prep_review, author, reviewer]
        payload = {'text_evidence_policy_version': 2, 'research_choice_version': 1, 'research_mode': 'sources',
                   'sources': [{'artifact': 'image', 'path': 'source.jpg'}, {'artifact': 'notes', 'path': 'source.txt'}]}
        return plan, payload

    def test_inventory_stays_visual_and_final_answer_still_requires_source_audit(self):
        plan, payload = self.graph()
        original = copy.deepcopy(plan['tasks'][0]['criteria'])
        text_evidence_planning.bind(plan, payload)
        self.assertEqual(plan['tasks'][0]['criteria'], original)
        self.assertNotIn('source_verification', plan['tasks'][1])
        self.assertEqual(plan['tasks'][-1]['source_verification']['sources'], ['source.txt'])
        contracts.plan(plan)
        again = copy.deepcopy(plan)
        text_evidence_planning.bind(again, payload)
        self.assertEqual(again, plan)

    def test_explicit_intermediate_factual_promise_cannot_use_image_as_text_evidence(self):
        for media in (None, 'text/plain', 'image/jpeg'):
            plan, payload = self.graph()
            for task in plan['tasks'][:2]:
                task['criteria'] = ['Verify factual accuracy against independent sources.']
                if media:task['inputs'][-1]['media_type'] = media
            with self.subTest(media=media), self.assertRaisesRegex(ValueError, 'independent source inputs'):
                text_evidence_planning.bind(plan, payload)

    def test_requested_intermediate_deliverable_still_needs_factual_verification(self):
        plan, payload = self.graph()
        plan['deliverables'] = {'inventory': {'task': 'inventory', 'output': 'output.txt'}}
        with self.assertRaisesRegex(ValueError, 'independent source inputs'):
            text_evidence_planning.bind(plan, payload)

    def test_text_specification_for_a_registered_renderer_is_a_final_author(self):
        plan, payload = self.graph()
        renderer = operation('bundle', 'text.bundle', [upstream('produce', 'output.txt')], ['produce'])
        plan['tasks'][2].pop('user_gate')
        plan['tasks'].append(renderer)
        text_evidence_planning.bind(plan, payload)
        self.assertIn('source_verification', plan['tasks'][3])

    def test_binary_deliverable_with_text_companion_audits_only_text_claims(self):
        plan, payload = self.graph()
        plan['tasks'][2]['outputs'].append({'path': 'catalog.xlsx', 'purpose': 'Workbook',
            'media_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
        plan['tasks'][3]['inputs'].append({'from_task': 'produce', 'output': 'catalog.xlsx',
            'path': 'candidate.xlsx', 'purpose': 'Review workbook', 'authority': 'Unaccepted'})
        text_evidence_planning.bind(plan, payload)
        self.assertEqual(plan['tasks'][3]['source_verification']['candidates'], ['candidate.txt'])
        source_verification.validate_assignment(plan['tasks'][3])
        contracts.plan(plan)
        forged = copy.deepcopy(plan['tasks'][3])
        forged['source_verification']['sources'].append('candidate.xlsx')
        with self.assertRaisesRegex(ValueError, 'own independent source'):
            source_verification.validate_assignment(forged)

    def test_legacy_source_policy_keeps_its_original_inventory_requirement(self):
        plan, payload = self.graph()
        payload['text_evidence_policy_version'] = 1
        text_evidence_planning.bind(plan, payload)
        self.assertIn('Verify factual accuracy against independent sources.', plan['tasks'][0]['criteria'])
        self.assertEqual(plan['tasks'][1]['source_verification']['sources'], ['source.jpg'])


class VersionTwoReviewTests(evidence_fixture.ReviewTests):
    """Run the existing forgery/acceptance/recovery cases on new frozen audits."""
    def setUp(self):
        original = text_evidence_planning.bind
        with patch.object(text_evidence_planning, 'bind', side_effect=lambda plan, payload:
                          original(plan, {**payload, 'text_evidence_policy_version': 2})):
            super().setUp()


if __name__ == '__main__':
    unittest.main()
