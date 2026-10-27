import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator import execution, executors, host_script
from orchestrator.runtime import Runtime
from task_relay import desktop_bridge
from task_relay.desktop_node_runs import compile_plan, LIMITS


class Handoff(unittest.TestCase):
    def graph(self):
        w=json.loads(Path('examples/cellular-pavilion.workflow.json').read_text())
        w['inputs']['xfigura_url']['default']='https://app.xfigura.ai/designer?nodeId=fixture'
        w['tasks'][0]['outputs'].append(dict(name='notes',media_type='text/markdown',purpose='Notes'))
        return w

    def test_full_and_single_node_share_executor_contract_without_extra_authority(self):
        w=self.graph();original=copy.deepcopy(w)
        with tempfile.TemporaryDirectory() as d, patch.object(execution,'available'), patch.object(executors,'available'):
            rt=Runtime(Path(d))
            try:
                full=compile_plan(rt,w,{},'fixture','Fixture')['plan']
                single=copy.deepcopy(w);single['tasks']=single['tasks'][:1]
                one=compile_plan(rt,single,{},'single','Fixture',schema_workflow=w)['plan']
            finally:rt.close()
        self.assertEqual(w,original)
        self.assertEqual(len(one['tasks']),1)
        for p in (full,one):
            t=p['tasks'][0]
            self.assertIn('Leave the built scene in bpy.context.scene',t['instruction'])
            runtime=json.loads(t['instruction'].split('Registered script execution context (code-owned):\n')[1])[0]['runtime']
            self.assertIn('"__main__"',runtime['entry'])
            self.assertNotIn('execution',t)
            self.assertEqual(len(t['outputs']),2)
            self.assertEqual(t['limits'],one['tasks'][0]['limits'])
            for key,ceiling in LIMITS.items():self.assertLessEqual(t['limits'][key],ceiling)
            before=t['instruction'];host_script.bind_preparers(p,graph=full)
            self.assertEqual(t['instruction'],before)
        self.assertNotIn('Registered script execution context',full['tasks'][1]['instruction'])

    def test_unrelated_and_frozen_producers_are_not_rewritten(self):
        producer=dict(id='script',instruction='original',outputs=[dict(path='source.py',media_type='text/x-python')])
        consumer=dict(id='build',execution={'capability':'blender.run_python'},inputs=[dict(from_task='script',output='source.py',media_type='text/x-python')])
        plan=dict(tasks=[producer,consumer]);original=copy.deepcopy(plan)
        host_script.bind_preparers(plan,editable={'build'})
        self.assertEqual(plan,original)
        consumer['inputs'][0]['output']='wrong.py'
        with self.assertRaisesRegex(ValueError,'binding changed'):host_script.bind_preparers(plan)

    def test_catalog_exposes_same_runtime_without_changing_saved_node_definition(self):
        from orchestrator.operation_definition import catalog,definition
        before=definition('blender.run_python')
        row=next(r for r in catalog() if r['id']=='blender.run_python')
        self.assertEqual(row['script_runtime'],host_script.preparation_context('blender.run_python'))
        self.assertEqual(before,row['definition'])

    def test_new_preparation_freezes_context_without_replaying_prior_attempt(self):
        from tests import test_orchestrator as fixture
        w=self.graph();single=copy.deepcopy(w);single['tasks']=single['tasks'][:1]
        with tempfile.TemporaryDirectory() as d, patch.object(execution,'available'), patch.object(executors,'available'):
            factory=fixture.FakeFactory();rt=Runtime(Path(d),factory)
            try:
                old=compile_plan(rt,single,{},'old','Fixture')['plan']
                rt.create(old);rt.tick('old');aid=rt.task('old','script')['latest']
                factory.finish(aid);rt.tick('old')
                prior=dict(rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone())
                corrected=compile_plan(rt,single,{},'corrected','Fixture',schema_workflow=w)['plan']
                rt.create(corrected);rt.tick('corrected');new=rt.task('corrected','script')['latest']
                frozen=factory.sessions[new]['frozen']
                self.assertIn('Registered script execution context',frozen['instruction'])
                self.assertEqual(frozen['limits'],factory.sessions[aid]['frozen']['limits'])
                factory.finish(new);rt.tick('corrected');rt.tick('corrected')
                self.assertEqual(factory.calls,[aid,new])
                self.assertEqual(dict(rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()),prior)
                self.assertEqual(rt.status('corrected')['status'],'completed')
            finally:rt.close()


class BridgeBounds(unittest.TestCase):
    def invoke(self,action,body):
        sink=io.StringIO()
        with patch.object(sys,'argv',['bridge',action]), patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(body))), patch.object(sys,'stdout',sink), patch.object(desktop_bridge,'dispatch',return_value={'fixture':True}) as dispatch:
            desktop_bridge.main()
        return json.loads(sink.getvalue()),dispatch

    def test_graph_context_above_old_bound_arrives_intact(self):
        value={'question':'Fix handoff','workflow':{'fixture':'Ж'*20000}}
        reply,dispatch=self.invoke('node-compose',json.dumps(value,ensure_ascii=False).encode())
        self.assertTrue(reply['ok']);dispatch.assert_called_once_with('node-compose',value)

    def test_bounded_bytes_and_ordinary_setup_limit_remain(self):
        for action,size in [('node-compose',500001),('node-compose-preview',500001),('provider',16385)]:
            with self.subTest(action=action):
                reply,dispatch=self.invoke(action,b' '*size)
                self.assertFalse(reply['ok']);self.assertEqual(reply['error'],'Request is too large.');dispatch.assert_not_called()
        reply,dispatch=self.invoke('node-compose',b'{}'+b' '*499998)
        self.assertTrue(reply['ok']);dispatch.assert_called_once()


if __name__=='__main__':unittest.main()
