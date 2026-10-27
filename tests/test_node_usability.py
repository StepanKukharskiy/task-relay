"""Small offline node/editor boundaries; no provider or native generation."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from orchestrator import operation_definition as ops,node_spec,media_adapters,contracts,execution
from orchestrator.runtime import Runtime
from task_relay import desktop_node_runs as runs,desktop_node_files as files,desktop_node_drafts as drafts


def workflow(op,inputs):
    return dict(schema_version=1,kind='workflow',inputs={},tasks=[dict(schema_version=3,id='step',operation=op,objective='Generate',inputs={k:{'value':v} for k,v in inputs.items()})])

class Nodes(unittest.TestCase):
    def test_prompt_only_generation_uses_same_operation_without_hidden_tasks(self):
        with tempfile.TemporaryDirectory() as d, patch('orchestrator.execution.available'):
            rt=Runtime(Path(d))
            for op,model in [('gemini.image','fixture-image'),('gemini.text','fixture-text'),('openai.image','gpt-image-1'),('openrouter.image','provider/image')]:
                w=workflow(op,dict(model=model,prompt='A red chair'))
                p=runs.compile_plan(rt,w,{},'fixture','Prompt')
                self.assertEqual(len(p['plan']['tasks']),1)
                task=p['plan']['tasks'][0];self.assertEqual(task['inputs'],[])
                self.assertEqual(task['execution']['parameters']['prompt'],'A red chair')
                self.assertEqual(p['paid_nodes'],['step'])
            rt.close()
    def test_empty_prompt_rejected_and_legacy_parameters_still_validate(self):
        with tempfile.TemporaryDirectory() as d, patch('orchestrator.execution.available'):
            rt=Runtime(Path(d))
            with self.assertRaisesRegex(ValueError,'prompt'):
                runs.compile_plan(rt,workflow('gemini.image',dict(model='fixture')),{},'f','Empty')
            rt.close()
        schema=execution.parameter_schema('gemini.image')
        from orchestrator.parameter_contracts import validate
        validate(dict(model='old-model',max_output_tokens=128,aspect_ratio='1:1'),schema)
    def test_provider_payload_keeps_literal_prompt_and_reference(self):
        path,payload=media_adapters.request('gemini.image',dict(model='fixture',prompt='A literal chair',max_output_tokens=128,aspect_ratio='1:1'),'Step name',[],[('image/png',b'fake')])
        self.assertTrue(payload['contents'][0]['parts'][0]['text'].startswith('A literal chair'))
        self.assertEqual(len(payload['contents'][0]['parts']),2)
        self.assertNotIn('Step name',str(payload))
    def test_search_backend_fields_are_public_but_compiled_as_frozen_choice(self):
        for op in ('web.sources.codex','web.sources.prepared.codex'):
            self.assertTrue({'model','reasoning'}<=set(ops.definition(op)['inputs']['properties']))
        with tempfile.TemporaryDirectory() as d, patch('orchestrator.execution.available'):
            rt=Runtime(Path(d));p=runs.compile_plan(rt,workflow('web.sources.codex',dict(queries=['chair'],domains=[],model='gpt-6.1-sol',reasoning='high')),{},'s','Search');rt.close()
        self.assertEqual(p['plan']['tasks'][0]['execution']['parameters']['model'],'gpt-6.1-sol')
        self.assertEqual(p['paid_nodes'],[])
    def test_previous_image_capture_matches_exact_prior_definition(self):
        for op in ('gemini.image','openai.image','openrouter.image','gemini.text'):
            current=ops.definition(op);prior=copy.deepcopy(current)
            prior['inputs']['properties'].pop('prompt');prior['defaults']={}
            prior['inputs']['required']=list(prior['inputs']['properties']);prior['inputs']['properties']['files']['minItems']=1
            self.assertTrue(ops.matches_capture(op,contracts.digest(prior),{'inputs':{}}))
            self.assertFalse(ops.matches_capture(op,contracts.digest(prior),{'inputs':{'prompt':{'value':'new'}}}))

class Files(unittest.TestCase):
    def test_selected_files_survive_original_edit_and_compile_multiple_bindings(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();paths=SimpleNamespace(data=root,state=root/'state.sqlite')
            def db(writable=False):
                c=sqlite3.connect(paths.state);c.row_factory=sqlite3.Row;return c
            with patch.object(files,'PATHS',paths),patch.object(files,'_database',db),patch.object(drafts,'PATHS',paths),patch('orchestrator.execution.available'):
                one=root/'one.md';two=root/'two.md';one.write_text('one');two.write_text('two')
                selected=files.dispatch('node-file-import',{'paths':[str(one),str(two)]})['files']
                one.write_text('new original')
                self.assertEqual(files.lookup(selected[0]['artifact'])['sha256'],selected[0]['sha256'])
                w=workflow('text.bundle',{'files':[{'artifact':f['artifact']} for f in selected]})
                saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Files',workflow=w))
                self.assertEqual(drafts.dispatch('node-draft',{'id':saved['id']})['workflow'],w)
                with db() as c:
                    rt=Runtime(root/'orchestrator',connection=c,read_only=True)
                    p=runs.compile_plan(rt,w,{},'files','Files')
                    self.assertEqual([i['artifact'] for i in p['plan']['tasks'][0]['inputs']],[f['artifact'] for f in selected])
                    blob=Path(rt.artifact(selected[0]['artifact'])['blob']);blob.chmod(0o600);blob.write_text('tampered')
                    with self.assertRaisesRegex(ValueError,'changed'):runs.compile_plan(rt,w,{},'bad','Files')
    def test_unknown_artifact_and_symlink_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();paths=SimpleNamespace(data=root,state=root/'state.sqlite')
            def db(writable=False):
                c=sqlite3.connect(paths.state);c.row_factory=sqlite3.Row;return c
            with patch.object(files,'PATHS',paths),patch.object(files,'_database',db):
                a=root/'a';a.write_text('a');link=root/'link';link.symlink_to(a)
                with self.assertRaises(ValueError):files.dispatch('node-file-import',{'paths':[str(link)]})
                with db() as c:
                    rt=Runtime(root/'orchestrator',connection=c);ident=rt.register(a,'unrelated')
                    with self.assertRaisesRegex(ValueError,'picker'):files.descriptor(rt,ident)

class Execution(unittest.TestCase):
    def test_prompt_only_text_and_image_reach_registered_adapter_and_collect_once(self):
        import base64
        from orchestrator.adapters import ExecutionFactory
        from tests.test_mixed_execution import LocalRegistered
        from tests.test_orchestrator import FakeFactory
        from tests.test_gemini import PNG
        for op in ('gemini.text','gemini.image'):
            with self.subTest(op=op),tempfile.TemporaryDirectory() as d,patch('orchestrator.execution.available'):
                seen=[]
                class Client:
                    def request(self,path,payload,**kw):
                        seen.append(payload)
                        part={'text':'Hi'} if op=='gemini.text' else {'inlineData':{'mimeType':'image/png','data':base64.b64encode(PNG).decode()}}
                        return {'candidates':[{'finishReason':'STOP','content':{'parts':[part]}}]}
                factory=ExecutionFactory(FakeFactory(),LocalRegistered(Client()))
                rt=Runtime(Path(d).resolve(),factory)
                p=runs.compile_plan(rt,workflow(op,dict(model='fixture',prompt='Reply with Hi' if op=='gemini.text' else 'A red chair')),{},'prompt','Prompt')
                rt.create(p['plan']);rt.tick('prompt');rt.tick('prompt');rt.tick('prompt')
                self.assertEqual(rt.status('prompt')['status'],'completed')
                self.assertEqual(len(seen),1)
                self.assertIn('Reply with Hi' if op=='gemini.text' else 'A red chair',json.dumps(seen[0]))
                out=rt.output('prompt','step',p['plan']['tasks'][0]['outputs'][0]['path'])
                self.assertGreater(out['bytes'],0);rt.close()

class ReusableFiles(unittest.TestCase):
    def test_file_requested_at_run_uses_exact_artifact_binding(self):
        w=workflow('images.crop',dict(region=[0,0,1,1]))
        # Native singular image input uses a named port from another registered operation.
        w=workflow('images.gallery',{})
        w['inputs']={'photos':dict(type='artifact',label='Photos',media_type='application/zip',required=True)}
        w['tasks'][0]['inputs']={'photos':{'workflow':'photos'},'recommendations':{'artifact':'notes'}}
        lookup=lambda aid:dict(media_type='application/zip' if aid=='zip' else 'text/plain')
        self.assertFalse(node_spec.resolve_workflow(w,artifact=lookup)['ready'])
        result=node_spec.resolve_workflow(w,{'photos':{'artifact':'zip'}},artifact=lookup)
        self.assertEqual(result['tasks'][0]['inputs']['photos'],{'artifact':'zip'})
        with self.assertRaisesRegex(ValueError,'Incompatible'):node_spec.resolve_workflow(w,{'photos':{'artifact':'notes'}},artifact=lookup)
