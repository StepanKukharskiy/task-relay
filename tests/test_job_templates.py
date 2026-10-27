"""Bundled template selection uses ordinary draft and registered graph boundaries."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from orchestrator import execution, executors
from orchestrator.runtime import Runtime
from task_relay import desktop_node_drafts, job_templates
from task_relay.desktop_node_runs import compile_plan


class Templates(unittest.TestCase):
    def test_select_and_copy_creates_independent_drafts_without_execution(self):
        catalog = job_templates.dispatch('node-templates', {})
        self.assertFalse(catalog['execution_authorized'])
        self.assertEqual(catalog['items'][0]['title'], 'Cellular aggregation · from Chat')
        selected = job_templates.dispatch('node-template', {'id': catalog['items'][0]['id']})
        self.assertEqual(len(selected['workflow']['tasks']), 11)
        with tempfile.TemporaryDirectory() as directory, patch.object(desktop_node_drafts, 'PATHS', SimpleNamespace(data=Path(directory))):
            values = dict(id=None, revision=None, title=selected['title'], workflow=selected['workflow'])
            a = desktop_node_drafts.dispatch('node-draft-save', values)
            b = desktop_node_drafts.dispatch('node-draft-save', values)
            self.assertNotEqual(a['id'], b['id'])
            self.assertFalse(a['execution_authorized'])
            self.assertEqual(a['missing_inputs'], [])
            self.assertFalse((Path(directory) / 'state.sqlite').exists())
            self.assertEqual(set(a)-{'id','title','workflow','revision','missing_inputs','execution_authorized'}, set())
            a['workflow']['tasks'][0]['objective'] = 'Changed research'
            desktop_node_drafts.dispatch('node-draft-save', dict(id=a['id'], revision=a['revision'], title=a['title'], workflow=a['workflow']))
            self.assertEqual(desktop_node_drafts.dispatch('node-draft', {'id':b['id']})['workflow'], selected['workflow'])
        self.assertEqual(job_templates.dispatch('node-template', {'id':'cellular-aggregation'})['workflow'], selected['workflow'])

    def test_registered_graph_compiles_with_paid_and_native_boundaries(self):
        selected = job_templates.dispatch('node-template', {'id':'cellular-aggregation'})
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            try:
                with patch.object(execution, 'available'), patch.object(executors, 'available'):
                    result = compile_plan(runtime, selected['workflow'], {}, 'template-fixture', selected['title'])
                self.assertEqual(runtime.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)
                self.assertEqual(runtime.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0], 0)
            finally:
                runtime.close()
        self.assertEqual(result['paid_nodes'], ['park_photo'])
        tasks = {t['id']:t for t in result['plan']['tasks']}
        self.assertEqual(list(tasks), [t['id'] for t in selected['workflow']['tasks']])
        self.assertEqual(tasks['build']['execution']['parameters']['permissions'], 'unrestricted_host')
        self.assertNotIn('host_code_authorization', tasks['build'])
        self.assertEqual(tasks['anim_plan']['operation_contract']['parameters']['target'], 'blender.animate')

    def test_unknown_template_and_extra_authority_are_rejected(self):
        for action, value in [('node-template', {'id':'../../private/state.sqlite'}), ('node-template', {'id': []}), ('node-template', {'id':'cellular-aggregation','run':True}), ('node-templates', {'run':True})]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                job_templates.dispatch(action, value)
