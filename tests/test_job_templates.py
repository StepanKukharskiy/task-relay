"""Bundled template selection uses ordinary draft and registered graph boundaries."""
import json
import sqlite3
from contextlib import ExitStack
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

    def test_every_template_names_software_and_bundled_inputs_are_reviewable(self):
        catalog = job_templates.dispatch('node-templates', {})['items']
        self.assertEqual(len(catalog), 2)
        for item in catalog:
            self.assertTrue(item['tools'])
            self.assertEqual(len(item['tools']), len(set(item['tools'])))
            self.assertTrue(all(isinstance(tool, str) and tool.strip() for tool in item['tools']))
        selected = job_templates.dispatch('node-template', {'id':'support-first-ca'})
        self.assertFalse(selected['execution_authorized'])
        from task_relay import workflow_transfer as transfer
        manifest, workflow, assets, digest = transfer.package(selected['package']['path'])
        self.assertEqual(digest, selected['package']['sha256'])
        source = Path('examples/support-first-ca')
        self.assertEqual(manifest, json.loads((source/'manifest.json').read_text()))
        self.assertEqual(workflow, json.loads((source/'workflow.json').read_text()))
        for item in manifest['inputs']:
            self.assertEqual(assets[item['id']], (source/item['name']).read_bytes())
        raw = json.dumps(workflow)
        for private in ('/Users/', 'stepankukharskiy.com', 'baseline', 'canvas-'):
            self.assertNotIn(private, raw)
        self.assertEqual(len(workflow['tasks']), 11)
        self.assertEqual({t['id']:t for t in workflow['tasks']}['music']['model']['tools'], 'python')

    def test_bundled_input_selection_uses_atomic_import_and_independent_artifacts(self):
        from task_relay import workflow_transfer as transfer, desktop_node_files as files
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory).resolve()
            paths = SimpleNamespace(data=root, state=root/'state.sqlite')
            paths.state.touch()
            def database(writable=False):
                db = sqlite3.connect(str(paths.state) if writable else paths.state.as_uri()+'?mode=ro', uri=not writable)
                db.row_factory = sqlite3.Row
                return db
            for module in (transfer, files, desktop_node_drafts):
                stack.enter_context(patch.object(module, 'PATHS', paths))
            for module in (transfer, files):
                stack.enter_context(patch.object(module, '_database', database))
            selected = job_templates.dispatch('node-template', {'id':'support-first-ca'})
            a = transfer.import_workflow(selected['package'])
            b = transfer.import_workflow(selected['package'])
            self.assertNotEqual(a['id'], b['id'])
            self.assertEqual(a['missing_inputs'], [])
            self.assertFalse(a['execution_authorized'])
            self.assertNotEqual(a['workflow']['tasks'][0]['inputs']['script_sha256'], b['workflow']['tasks'][0]['inputs']['script_sha256'])
            with database() as db:
                rt = Runtime(root/'orchestrator', connection=db, read_only=True)
                with patch.object(execution, 'available'), patch.object(executors, 'available'), patch('task_relay.code_runtime.available', return_value={'id':'a'*64,'tools':{}}):
                    with self.assertRaisesRegex(ValueError, 'existing artifact for project_sha256'):
                        compile_plan(rt,a['workflow'],{},'template-fixture',a['title'],lookup=lambda ident:files.descriptor(rt,ident))
                    # Final rendering requires an exact completed preview, as in the saved job.
                    workflow = {**a['workflow'], 'tasks':a['workflow']['tasks'][:-1]}
                    plan = compile_plan(rt,workflow,{},'template-fixture',a['title'],lookup=lambda ident:files.descriptor(rt,ident))
                self.assertEqual(plan['paid_nodes'], ['visual'])
                self.assertEqual(db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM production_attempts').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0], 8)
