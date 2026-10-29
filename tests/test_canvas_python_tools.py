"""Explicit canvas tool profiles; synthetic admission/handoff, no provider calls."""
import copy
from unittest.mock import patch
from task_relay import desktop_node_setup as setup, desktop_node_drafts as drafts
from tests import test_canvas_node_run as canvas_tests
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory


class PythonTools(canvas_tests.Canvas):
    def test_explicit_profile_preserves_model_and_fails_closed(self):
        choice=dict(provider='codex',id='gpt-6.1-sol',reasoning='high')
        with patch('task_relay.code_runtime.available',return_value={'id':'a'*64}) as available:
            original=setup.backend(choice)
            self.assertEqual(original['type'],'codex-agent');available.assert_not_called()
            selected=setup.backend({**choice,'tools':'python'})
            self.assertEqual(selected,{**original,'type':'codex-code','runtime':'a'*64})
            self.assertEqual(setup.backend({**choice,'tools':'files'}),original)
        with patch('task_relay.code_runtime.available',side_effect=ValueError('Runtime changed')):
            with self.assertRaisesRegex(ValueError,'Runtime changed'):setup.backend({**choice,'tools':'python'})
        with self.assertRaisesRegex(ValueError,'isolated Python'):setup.backend({**choice,'tools':'shell'})

    def test_binary_handoff_saved_profile_and_unchanged_limits(self):
        from task_relay import desktop_node_runs as runs
        workflow=copy.deepcopy(self.w)
        for task in workflow['tasks']:
            task['model']=dict(provider='codex',id='gpt-6.1-sol',reasoning='high',tools='python')
        workflow['tasks'][0]['outputs'][0]['media_type']='audio/wav'
        workflow['tasks'][1]['input_definitions']['article']['media_type']='audio/wav'
        saved=drafts.dispatch('node-draft-save',dict(id=self.saved['id'],revision=self.saved['revision'],title='Audio handoff',workflow=workflow))
        self.request['revision']=saved['revision']
        self.assertEqual(drafts.dispatch('node-draft',{'id':saved['id']})['workflow'],workflow)
        with patch('task_relay.code_runtime.available',return_value={'id':'a'*64,'tools':{}}):
            p=runs.preview(self.request)
            self.assertEqual(p['paid_nodes'],[])
            self.assertEqual(len(p['plan']['tasks']),2)
            for task in p['plan']['tasks']:
                self.assertEqual(task['worker']['backend']['type'],'codex-code')
                self.assertEqual(task['limits'],runs.LIMITS)
            receipt=runs.start(self.command())
            factory=FakeFactory();rt=Runtime(self.root/'orchestrator',factory)
            try:
                rt.tick(receipt['run']);first=rt.task(receipt['run'],'write')['latest'];factory.finish(first);rt.tick(receipt['run'])
                second=rt.task(receipt['run'],'summary')['latest']
                supplied=factory.sessions[second]['frozen']
                self.assertEqual(supplied['backend']['runtime'],'a'*64)
                self.assertIn('python',supplied['tools'])
                self.assertEqual(supplied['inputs'][0]['sha256'],rt.output(receipt['run'],'write',p['plan']['tasks'][0]['outputs'][0]['path'])['sha256'])
                from task_relay.desktop_node_files import artifact_descriptor
                from orchestrator import node_spec
                artifact=rt.output(receipt['run'],'write',p['plan']['tasks'][0]['outputs'][0]['path'])
                # Historical artifacts may have a generic extension; the exact
                # producing assignment remains the authority across executions.
                rt.db.execute("UPDATE production_artifacts SET path='outputs/audio.bin' WHERE id=?",(artifact['id'],))
                row=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(first,)).fetchone()
                import json
                frozen=json.loads(row['frozen']);frozen['outputs'][0]['path']='outputs/audio.bin'
                rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),first));rt.db.commit()
                restored=artifact_descriptor(rt,artifact['id'],expected_sha256=artifact['sha256'])
                self.assertEqual(restored['media_type'],'audio/wav')
                consumer=copy.deepcopy(workflow);consumer['tasks']=consumer['tasks'][1:]
                consumer['tasks'][0]['inputs']['article']={'artifact':artifact['id']}
                node_spec.resolve_workflow(consumer,artifact=lambda aid:artifact_descriptor(rt,aid))
                consumer['tasks'][0]['input_definitions']['article']['media_type']='image/png'
                with self.assertRaisesRegex(ValueError,'Incompatible artifact media'):
                    node_spec.resolve_workflow(consumer,artifact=lambda aid:artifact_descriptor(rt,aid))
                with self.assertRaisesRegex(ValueError,'version changed'):
                    artifact_descriptor(rt,artifact['id'],expected_sha256='b'*64)
                factory.finish(second);rt.tick(receipt['run'])
                self.assertEqual(rt.status(receipt['run'])['status'],'completed')
            finally:rt.close()
