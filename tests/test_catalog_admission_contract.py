"""Advertised work routes and early input checks, with no external dispatch."""
import copy,unittest
from unittest.mock import patch
from orchestrator import owner_intents,execution
from tests import test_owner_compilation as fixture

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp

    def test_catalog_uses_actual_work_compiler_and_exposes_native_consumption(self):
        grant=copy.deepcopy(self.grant)
        grant.update(worker_tools_version=2,operations=['web.sources.codex','blender.scene','rhino.document','text.bundle'])
        grant['task_limits'].update(provider_requests=24,tool_calls=100)
        before=copy.deepcopy(grant)
        offered=owner_intents.catalog(grant,list(grant['operations']))['operations']
        self.assertNotIn('worker_work',offered['web.sources.codex'])
        self.assertIn('cannot fit',offered['web.sources.codex']['worker_work_unavailable']['reason'])
        self.assertEqual(offered['web.sources.codex']['input_contract']['max_files'],0)
        self.assertEqual(offered['web.sources.codex']['input_contract']['max_bytes'],0)
        for cap in ('blender.scene','rhino.document'):
            self.assertEqual(offered[cap]['authoring_worker']['outputs']['count'],1)
            self.assertEqual(offered[cap]['authoring_worker']['outputs']['media_type'],'application/json')
        self.assertIn('worker_work',offered['text.bundle'])
        self.assertEqual(grant,before)

    def test_invalid_native_count_fails_before_reading_any_artifact(self):
        task=dict(id='source',execution=dict(capability='web.sources.codex'),inputs=[dict(artifact='not-read',path='context.txt',media_type='text/plain')])
        with patch.object(self.rt,'artifact',side_effect=AssertionError('No file read')):
            with self.assertRaisesRegex(ValueError,'source.*web.sources.codex.*expected 0–0, received 1'):
                self.rt.checked_inputs('fixture',task,{})
        self.assertEqual(len(self.factory.calls),0)

    def test_partial_input_check_allows_later_bound_required_data_but_not_bad_selection(self):
        task=dict(id='coverage',execution=dict(capability='web.sources.coverage'),inputs=[dict(path='inventory.json',media_type='application/json')])
        execution.validate_inputs(task,complete=False)
        with self.assertRaisesRegex(ValueError,'expected 2–2'):execution.validate_inputs(task)
        task['inputs'].append(dict(path='catalog.json',media_type='application/json'))
        execution.validate_inputs(task)
        task['inputs'][0]['media_type']='image/png'
        with self.assertRaisesRegex(ValueError,'operation_input'):execution.validate_inputs(task,complete=False)

if __name__=='__main__':unittest.main()
