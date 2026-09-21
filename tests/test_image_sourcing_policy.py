"""Availability routing and frozen scope checks; no model calls or browsing."""
import copy
import json
import unittest
from unittest.mock import patch

from task_relay.image_sourcing_policy import describe
from task_relay import orchestrator_chat as chat, orchestrator_context
from orchestrator import worker_capabilities
from tests import test_production_planning as fixture


OPS = [{'id': name, 'available': True} for name in ('images.collect', 'images.fetch')]
BROWSER = {'enabled': True, 'available': True, 'error': None, 'manual_sign_in': False}
WORKER = worker_capabilities.entry({'type': 'gemini-browser', 'model': 'fixture'})


class PolicyTests(unittest.TestCase):
    def test_generic_default_uses_available_browser_without_mutating_catalogs(self):
        before = copy.deepcopy((OPS, WORKER, BROWSER))
        result = describe(OPS, [WORKER], BROWSER)
        self.assertEqual(result['preferred_operation'], 'images.fetch')
        self.assertEqual(len(result['search_sites']), 2)
        self.assertEqual((OPS, WORKER, BROWSER), before)

    def test_disabled_missing_or_unverified_browser_falls_back_to_commons(self):
        for browser, workers in [({'enabled': False, 'available': True}, [WORKER]),
                                 ({'enabled': True, 'available': False}, [WORKER]),
                                 (BROWSER, []), (BROWSER, [{**WORKER, 'available': False}])]:
            with self.subTest(browser=browser, workers=workers):
                result = describe(OPS, workers, browser)
                self.assertEqual(result['preferred_operation'], 'images.collect')
                self.assertEqual(result['search_sites'], [])

    def test_selected_operation_scope_cannot_gain_browser_or_generation(self):
        result = describe(OPS[:1], [WORKER], BROWSER)
        self.assertEqual(result['available_operations'], ['images.collect'])
        self.assertEqual(result['search_sites'], [])
        self.assertIsNone(describe([], [WORKER], BROWSER)['preferred_operation'])
        self.assertIsNone(describe([{**op, 'available': False} for op in OPS],
                                   [WORKER], BROWSER)['preferred_operation'])

    def test_compressed_context_retains_complete_source_choices(self):
        policy = describe(OPS, [WORKER], BROWSER)
        payload = {'snapshot': {'capabilities': {'graph_operations': OPS,
                   'graph_executors': [WORKER], 'image_sourcing': policy}},
                   'history': [{'text': 'large old context ' * 30000}],
                   'user_message': 'Find relevant photos for my research presentation.'}
        result = orchestrator_context.overview(payload)
        self.assertEqual(result['current_execution_availability']['image_sourcing'], policy)
        self.assertEqual(result['user_message'], payload['user_message'])


class PlanningTests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        del self.fail
    tearDown = fixture.Tests.tearDown
    request = fixture.Tests.request
    queue = fixture.Tests.queue
    row = fixture.Tests.row
    action = fixture.Tests.action

    def test_routing_and_planner_share_default_but_plan_stays_in_selected_scope(self):
        with patch('orchestrator.execution.catalog', return_value=OPS), \
             patch('orchestrator.executors.catalog', return_value=[{**WORKER, 'available': True}]), \
             patch('task_relay.managed_browser.status', return_value=BROWSER), \
             patch.object(worker_capabilities, 'capture', return_value=[WORKER]):
            snapshot = chat.snapshot(self.state, None)
            self.assertEqual(snapshot['capabilities']['image_sourcing']['preferred_operation'], 'images.fetch')
            text = 'Find relevant photos for my research presentation.'
            row = self.queue(action=self.action(step_capabilities=['images.fetch']), text=text)
            context = json.loads(row['context'])
            self.assertEqual(context['original_request'], text)
            self.assertEqual(context['image_sourcing']['preferred_operation'], 'images.fetch')
            self.assertEqual(context['image_sourcing']['available_operations'], ['images.fetch'])
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)
            saved = row['context']
        # Changed settings never rewrite the captured proposal or dispatch work.
        self.assertEqual(self.row()['context'], saved)

    def test_explicit_commons_scope_is_not_expanded_even_with_browser_available(self):
        text = 'Use only Wikimedia Commons for these photos; no other websites.'
        with patch('orchestrator.execution.catalog', return_value=OPS), \
             patch('task_relay.managed_browser.status', return_value=BROWSER), \
             patch.object(worker_capabilities, 'capture', return_value=[WORKER]):
            row = self.queue(action=self.action(step_capabilities=['images.collect']), text=text)
        context = json.loads(row['context'])
        self.assertEqual(context['original_request'], text)
        self.assertEqual(context['image_sourcing']['preferred_operation'], 'images.collect')
        self.assertEqual(context['image_sourcing']['search_sites'], [])
        self.assertEqual(json.loads(row['options'])['step_capabilities'], ['images.collect'])
