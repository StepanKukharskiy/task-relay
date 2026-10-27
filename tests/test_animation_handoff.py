"""Named scene/manifest composition; no provider or native process runs."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import execution, executors, prepared_contract, prepared_schemas
from orchestrator.operation_definition import catalog, definition, matches_capture
from orchestrator.runtime import Runtime
from task_relay.desktop_node_runs import compile_plan
from tests import test_blender_animation as fixture


def graph():
    model=dict(provider='codex',id='gpt-6.1-sol',reasoning='high')
    return dict(schema_version=1,kind='workflow',inputs={},tasks=[
        dict(schema_version=3,id='geometry',operation='model',objective='Prepare fixture scene',model=model,
             inputs={},input_definitions={},outputs=[dict(name='data',media_type='application/json',purpose='Scene data')]),
        dict(schema_version=3,id='scene',operation='blender.scene',objective='Build fixture scene',
             inputs={'files':{'value':[dict(task='geometry',output='data')]}}),
        dict(schema_version=3,id='prepare',operation='model',objective='Prepare bounded animation',model=model,
             inputs={'scene':dict(task='scene',output='scene')},
             input_definitions={'scene':dict(type='artifact',label='Scene',media_type='application/x-blender',required=True)},
             outputs=[dict(name='manifest',media_type='application/json',purpose='Animation settings')]),
        dict(schema_version=3,id='animate',operation='blender.animate',objective='Render saved growth',
             inputs=dict(scene_sha256=dict(task='scene',output='scene'),manifest_sha256=dict(task='prepare',output='manifest')))])


class Handoff(unittest.TestCase):
    def test_graph_compiles_registered_fragments_and_exact_shared_scene(self):
        w=graph();original=copy.deepcopy(w)
        with tempfile.TemporaryDirectory() as d, patch.object(execution,'available'),patch.object(executors,'available'):
            rt=Runtime(Path(d))
            try:p=compile_plan(rt,w,{},'fixture','Fixture')['plan']
            finally:rt.close()
        self.assertEqual(w,original)
        prep=p['tasks'][2];consumer=p['tasks'][3]
        self.assertEqual(prep['operation_contract']['parameters']['target'],'blender.animate')
        scene=next(i for i in consumer['inputs'] if i['media_type']=='application/x-blender')
        self.assertEqual(scene['from_task'],'scene')
        self.assertEqual(prep['operation_contract']['parameters']['hash_bindings'],{'scene_sha256':prep['inputs'][0]['path']})
        self.assertEqual(consumer['execution']['parameters']['scene_sha256'],scene['path'])
        self.assertEqual(consumer['limits'],dict(seconds=1200,tool_calls=1,output_bytes=100000000))
        self.assertEqual(prep['limits']['seconds'],600)
        self.assertEqual(p['tasks'][1]['limits']['seconds'],600)
        self.assertEqual(consumer['max_attempts'],1)
        # Fixed/hash fields are injected by the registered writer, never authored.
        raw=b'synthetic blend';sha=hashlib.sha256(raw).hexdigest()
        frozen={**prep,'inputs':[dict(prep['inputs'][0],sha256=sha)]}
        ctx=prepared_contract.context(frozen,lambda _:raw)
        self.assertEqual(ctx['fixed'],dict(version=1,scene_sha256=sha))
        bad=copy.deepcopy(frozen);bad['inputs'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'version changed'):prepared_contract.context(bad,lambda _:raw)

    def test_catalog_exposes_authoritative_schema_without_hashes_in_fragments(self):
        row=next(r for r in catalog() if r['id']=='blender.animate')
        self.assertEqual(row['preparation']['schema'],prepared_schemas.REGISTRY['blender.animate']['schema'])
        self.assertNotIn('scene_sha256',row['preparation']['schema']['properties'])
        self.assertIn('120',row['preparation']['schema']['description'])
        self.assertEqual(row['inputs']['scene_sha256']['accepts'],['application/x-blender'])
        prior=copy.deepcopy(definition('blender.animate'));prior['inputs']['properties'].pop('scene_sha256')
        from orchestrator.contracts import digest
        self.assertTrue(matches_capture('blender.animate',digest(prior),dict(inputs={})))
        self.assertFalse(matches_capture('blender.animate',digest(prior),dict(inputs={'scene_sha256':{}})))

    def test_unstructured_binary_output_does_not_gain_code_authority(self):
        w=graph();w['tasks']=w['tasks'][:1]
        w['tasks'][0]['outputs'][0]['media_type']='application/x-blender'
        with tempfile.TemporaryDirectory() as d,patch.object(execution,'available'),patch.object(executors,'available'):
            rt=Runtime(Path(d))
            try:
                with self.assertRaisesRegex(ValueError,'No eligible worker'):compile_plan(rt,w,{},'fixture','Fixture')
            finally:rt.close()

    def test_missing_or_wrong_scene_wire_rejects_before_dispatch(self):
        for change in ('missing','wrong'):
            w=graph()
            if change=='missing':w['tasks'][-1]['inputs'].pop('scene_sha256')
            else:w['tasks'][-1]['inputs']['scene_sha256']=dict(task='prepare',output='manifest')
            with tempfile.TemporaryDirectory() as d,patch.object(execution,'available'),patch.object(executors,'available'):
                rt=Runtime(Path(d))
                try:
                    with self.assertRaises(ValueError):compile_plan(rt,w,{},'fixture','Fixture')
                    self.assertEqual(rt.db.execute('select count(*) from production_attempts').fetchone()[0],0)
                finally:rt.close()


class NamedExecution(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    frozen=fixture.Tests.frozen
    process=fixture.Tests.process

    def test_explicit_old_budget_preserved_and_new_ceiling_enforced(self):
        from orchestrator import contracts
        self.op['limits']=dict(seconds=600,tool_calls=1,output_bytes=100000000)
        original=copy.deepcopy(self.op)
        checked=contracts.assignment(self.op)
        self.assertEqual(checked['limits']['seconds'],600)
        self.assertEqual(self.op,original)
        for seconds in (1200,1201):
            candidate=copy.deepcopy(original);candidate['limits']['seconds']=seconds
            if seconds==1200:self.assertEqual(contracts.assignment(candidate)['limits']['seconds'],1200)
            else:
                with self.assertRaisesRegex(ValueError,'seconds'):contracts.assignment(candidate)

    def test_composed_future_scene_preparation_collection_and_animation(self):
        from orchestrator.operation_records import Store
        from orchestrator.gemini_worker import Files
        from orchestrator.step_runner import execute
        from tests.test_blender_operations import scene_data
        with patch.object(execution,'available'),patch.object(executors,'available'):
            plan=compile_plan(self.rt,graph(),{},'composed','Fixture')['plan']
            self.rt.create(plan);self.rt.tick('composed')
        def session(task):
            aid=self.rt.task('composed',task)['latest']
            self.assertIsNotNone(aid,self.rt.status('composed'))
            return aid,self.fake.sessions[aid]
        def prepare(task,doc):
            aid,s=session(task);f=s['frozen'];store=Store(f,self.rt.db)
            spec=prepared_schemas.REGISTRY[f['operation_contract']['parameters']['target']]
            records=[]
            for field,rule in spec['schema']['properties'].items():
                if field not in doc:continue
                value=doc[field]
                if rule.get('type')=='array':
                    records.extend(dict(kind='append',field=field,index=i,value=v) for i,v in enumerate(value))
                elif rule.get('type')=='object' and isinstance(rule.get('additionalProperties'),dict):
                    records.extend(dict(kind='entry',field=field,key=k,value=v) for k,v in value.items())
                else:records.append(dict(kind='field',field=field,value=value))
            records.append(dict(kind='end'))
            for i,record in enumerate(records):store.submit(dict(request_key=str(i),revision=i,records=[record]),{})
            self.fake.finish(aid)
            store.export(Files(f),complete=True)
            self.rt.tick('composed')
        prepare('geometry',scene_data())
        aid,s=session('scene');self.fake.finish(aid)
        (s['workspace']/'delivery/execution.json').write_text('{}')
        self.rt.tick('composed')
        source=self.rt.output('composed','scene','delivery/scene.blend')
        prepare('prepare',dict(mode='preview',frame_start=1,frame_end=3,fps=3,camera='Camera',resolution=[64,64],samples=1,tracks=[]))
        manifest=self.rt.output('composed','prepare','outputs/manifest.json')
        self.assertEqual(json.loads(Path(manifest['blob']).read_text())['scene_sha256'],source['sha256'])
        aid,s=session('animate');control=Path(s['session']['control']);control.mkdir(parents=True)
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):
            self.assertEqual(execute(s['frozen'],control)['outcome'],'completed')
        s['status']=dict(status='finished',exit_code=0)
        self.rt.tick('composed');self.rt.tick('composed')
        self.assertEqual(self.rt.status('composed')['status'],'completed')
        self.assertEqual(len(self.fake.calls),4)
        self.assertIsNotNone(self.rt.output('composed','animate','delivery/animation.mp4'))

    def test_named_aliases_execute_and_legacy_checkpoint_identity_still_matches(self):
        from orchestrator.blender_animation import bind_registered
        from orchestrator.step_runner import execute
        self.op['inputs'][0]['path']='inputs/selected.blend'
        self.op['inputs'][1]['path']='inputs/animation.json'
        self.op['execution']['parameters']=dict(scene_sha256='inputs/selected.blend',manifest_sha256='inputs/animation.json')
        self.assertEqual(bind_registered(self.rt,self.op),self.manifest)
        frozen,control=self.frozen()
        with patch('orchestrator.blender_animation.subprocess.run',side_effect=self.process):
            self.assertEqual(execute(frozen,control)['outcome'],'completed')
        original=copy.deepcopy(self.op)
        self.op['execution']['parameters']['scene_sha256']='other.blend'
        with self.assertRaisesRegex(ValueError,'binding mismatch'):bind_registered(self.rt,self.op)
        self.op=original
        # Manifest binding cannot be changed to a different exact hash.
        self.op['execution']['parameters']['manifest_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'binding mismatch'):bind_registered(self.rt,self.op)

if __name__=='__main__':unittest.main()
