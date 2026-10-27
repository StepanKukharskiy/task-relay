"""Small exact-version role fixtures; real mixed-job execution is qualified separately."""
import copy,hashlib,io,json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from orchestrator import artifact_roles as roles,pptx_render,worker_tools,visual_files,executors

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.execute('create table production_attempts(id text,frozen text,receipt text,state text)');self.artifacts={}
        self.rt=SimpleNamespace(db=self.db,artifact=lambda ident:self.artifacts[ident])
        pic=io.BytesIO();Image.new('RGB',(12,10),'red').save(pic,format='PNG');self.png=pic.getvalue()
        z=io.BytesIO()
        with zipfile.ZipFile(z,'w') as f:f.writestr('slide-001.png',self.png)
        self.inputs=[self.add('deck',b'native fixture',pptx_render.MIME,'old.pptx','build'),self.add('pdf',b'%PDF-controlled','application/pdf','preview.pdf','render'),self.add('pages',z.getvalue(),'application/zip','pages.zip','render'),self.add('report',b'{"finding":"missing image"}','application/json','review.json','review')]
        proof=dict(candidate_artifact='deck',candidate_sha256=self.artifacts['deck']['sha256'],outputs={self.artifacts[k]['path']:dict(sha256=self.artifacts[k]['sha256']) for k in ('pdf','pages')})
        self.db.execute('insert into production_attempts values(?,?,?,?)',('render',json.dumps(dict(execution=dict(capability='pptx.render'))),json.dumps(dict(operation=dict(outcome='completed',validation=proof))),'completed'))
        self.task=dict(id='make',objective='Build document',instruction='Build document',inputs=copy.deepcopy(self.inputs))
        worker_tools.configure(self.task,dict(operation='pptx.create',parameters={},content_parameters=dict(max_records=1)),dict(worker_tools_version=1,operations=['pptx.create','pptx.render'],task_limits=dict(tool_calls=24,provider_requests=24)))
        self.closure=[dict(task='make',inherited=[dict(path=i['path'],via=['artifact','report']) for i in self.inputs[:3]])]

    def add(self,ident,data,mime,path,attempt):
        target=self.root/ident;target.write_bytes(data)
        self.artifacts[ident]=dict(id=ident,attempt=attempt,blob=str(target),path=path,sha256=hashlib.sha256(data).hexdigest())
        return dict(artifact=ident,path=path,media_type=mime,purpose='Required evidence',authority='Fixture only')

    def bind(self):roles.bind(self.task,self.rt,self.closure);return self.task['artifact_roles']

    def files(self):
        inputs={i['path']:{**i,'sha256':self.artifacts[i['artifact']]['sha256']} for i in self.inputs}
        return SimpleNamespace(frozen=self.task,inputs=inputs,outputs={},written={},read_bytes=lambda path:Path(self.artifacts[inputs[path]['artifact']]['blob']).read_bytes())

    def test_exact_render_evidence_is_readable_but_not_consumed_by_build(self):
        binding=self.bind();roles.verify(self.rt,self.task)
        self.assertEqual(binding['inputs']['preview.pdf']['inspection']['path'],'pages.zip')
        self.assertTrue(all(not r['consumes'] for r in binding['inputs'].values()))
        self.assertEqual(binding['inputs']['preview.pdf']['origin']['via'],['artifact','report'])
        value=visual_files.read(self.files(),dict(path='preview.pdf',members=['slide-001.png']))
        self.assertEqual(value['_pixels'],[self.png]);self.assertEqual(value['evidence']['path'],'preview.pdf')
        self.assertEqual(visual_files.read(self.files(),dict(path='old.pptx',members=[]))['members'],['slide-001.png'])
        self.assertNotIn('application/pdf',executors.asset_policy(self.task)['media_types'])
        self.assertEqual(len(self.task['inputs']),4) # report and ancestry retained

    def test_no_linked_pages_fails_with_artifact_origin_and_runtime_remedy(self):
        self.task['inputs']=[i for i in self.inputs if i['artifact']!='pages']
        with self.assertRaises(roles.CompatibilityError) as raised:self.bind()
        d=raised.exception.diagnostic
        self.assertFalse(d['model_correctable']);self.assertEqual(d['origin']['via'],['artifact','report'])
        self.assertEqual(d['role'],'inspection_evidence');self.assertIn('representation',d['remedy'])

    def test_explicit_unreadable_input_is_model_correctable(self):
        self.task['inputs']=[self.inputs[1]];self.closure=[]
        with self.assertRaises(roles.CompatibilityError) as raised:self.bind()
        self.assertTrue(raised.exception.diagnostic['model_correctable']);self.assertEqual(raised.exception.diagnostic['artifact'],'pdf')

    def test_changed_render_or_candidate_identity_does_not_supply_representation(self):
        self.artifacts['pdf']['sha256']='0'*64
        with self.assertRaises(roles.CompatibilityError):self.bind()

    def test_granted_inspection_is_not_an_operation_input_permission(self):
        self.bind();self.task['artifact_roles']['inputs']['preview.pdf']['consumes']=['build']
        with self.assertRaises(roles.CompatibilityError) as raised:roles.validate(self.task)
        self.assertEqual(raised.exception.diagnostic['role'],'operation_input')

    def test_pdf_explicitly_submitted_to_native_renderer_names_wrong_input(self):
        from orchestrator import execution
        task=dict(execution=dict(capability='pptx.render',version=1,parameters={}),inputs=[self.inputs[1]],criteria=execution.REGISTRY['pptx.render']['criteria'])
        with self.assertRaises(roles.CompatibilityError) as raised:execution.validate(task)
        d=raised.exception.diagnostic;self.assertEqual(d['artifact'],'pdf');self.assertEqual(d['role'],'operation_input')
        self.assertTrue(d['model_correctable']);self.assertIn('pptx.render',d['failed_check'])

    def test_denied_visual_capability_and_unassigned_files_still_fail(self):
        self.bind()
        with self.assertRaises(roles.CompatibilityError):roles.compatible(self.task,{'files.text'})
        with self.assertRaisesRegex(ValueError,'assigned'):visual_files.read(self.files(),dict(path='secret.pdf',members=[]))

    def test_mutated_bound_preview_cannot_be_observed(self):
        self.bind();Path(self.artifacts['pages']['blob']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):visual_files.read(self.files(),dict(path='preview.pdf',members=['slide-001.png']))
        with self.assertRaisesRegex(ValueError,'changed'):roles.verify(self.rt,self.task)

    def test_jpeg_asset_pixels_are_exposed_without_code_permission(self):
        b=io.BytesIO();Image.new('RGB',(12,10),'blue').save(b,format='JPEG')
        item=self.add('photo',b.getvalue(),'image/jpeg','photo.jpg','source');self.inputs.append(item);self.task['inputs'].append(item);self.bind()
        value=visual_files.read(self.files(),dict(path='photo.jpg',members=[]))
        self.assertTrue(value['_pixels'][0].startswith(b'\x89PNG'));self.assertEqual(value['images'][0]['source_sha256'],hashlib.sha256(b.getvalue()).hexdigest())
        self.assertEqual(self.task['artifact_roles']['inputs']['photo.jpg']['consumes'],['build'])

    def test_record_author_reads_inherited_native_evidence_without_code_permission(self):
        from orchestrator import artifact_files,worker_capabilities
        self.task.pop('work_tools');self.task['outputs']=[dict(path='section.json',media_type='application/json',purpose='Saved section')]
        self.task['operation_contract']=dict(id='document.layout',version=1)
        bound=self.bind()
        self.assertTrue(all(not row['consumes'] for row in bound['inputs'].values()))
        backend=dict(type='codex-agent',model='fixture',reasoning='low',budget_semantics='cli-exchanges-v1')
        self.assertTrue(worker_capabilities.matches(self.task,['files.text'],backend))
        for item in self.task['inputs']:
            raw=Path(self.artifacts[item['artifact']]['blob']).read_bytes()
            (self.root/item['path']).write_bytes(raw);item['sha256']=hashlib.sha256(raw).hexdigest()
        self.task.update(workspace=str(self.root.resolve()),assignment_id='fixture',backend=backend)
        files=artifact_files.files(self.task,self.root/'control')
        route=files.call('file_read',dict(path='old.pptx',offset=0,limit=1000))
        self.assertEqual(route['inspection']['path'],'pages.zip')
        self.assertEqual(visual_files.read(files,dict(path='old.pptx',members=['slide-001.png']))['_pixels'],[self.png])
        with self.assertRaisesRegex(ValueError,'not granted'):files.call('python_run',dict(code='print(1)'))
        self.assertNotIn('native fixture',str(files.source_pack()))
        self.task['artifact_roles']['inputs']['old.pptx']['consumes']=['build']
        with self.assertRaisesRegex(ValueError,'cannot grant'):roles.validate(self.task)

    def test_local_native_bytes_do_not_consume_text_transport_capacity(self):
        self.task.pop('work_tools');self.task['outputs']=[dict(path='subjects.json',media_type='application/json',purpose='Subjects')]
        self.task['operation_contract']=dict(id='collection.subjects',version=1)
        self.bind()
        # Counts stand for exact local files; no megabyte fixture is necessary.
        items=[dict(i,bytes=8000000 if i['artifact']=='deck' else 100) for i in self.task['inputs']]
        for kind in ('codex-agent','gemini-agent','openai-agent','openrouter-agent'):
            backend=dict(type=kind)
            executors.validate_input_sizes(items,backend,self.task)
            legacy=copy.deepcopy(self.task);legacy.pop('artifact_roles')
            with self.assertRaisesRegex(ValueError,'512 KB'):executors.validate_input_sizes(items,backend,legacy)
            with self.assertRaisesRegex(ValueError,'100000000'):executors.validate_input_sizes([dict(items[0],bytes=100000001)],backend,self.task)
        self.task['artifact_roles']['inputs']['old.pptx']['inspection']['path']='unassigned'
        with self.assertRaisesRegex(ValueError,'outside'):executors.validate_input_sizes(items,dict(type='codex-agent'),self.task)

    def test_record_content_assets_exclude_historical_render_representation(self):
        self.task.pop('work_tools');self.task['outputs']=[dict(path='section.json',media_type='application/json',purpose='Section')]
        self.task['operation_contract']=dict(id='document.layout',version=1)
        photo=self.add('photo',self.png,'image/png','photo.png','source')
        self.task['inputs'].append(photo);self.bind()
        self.assertEqual(roles.content_inputs(self.task),[photo])
        self.assertTrue(all(not row['consumes'] for row in self.task['artifact_roles']['inputs'].values()))

    def test_revision_preflight_keeps_render_zip_out_of_asset_port(self):
        baseline=self.add('base',b'{}','application/json','base.json','compose')
        self.task['inputs'].append(baseline)
        self.task['work_tools']['version']=3
        self.task['work_tools']['intent']=dict(mode='revise',baseline='base.json')
        self.bind()
        native=worker_tools.native_assignment(self.task)
        self.assertEqual([i['path'] for i in native['inputs']],['base.json'])
        self.assertIn('pages.zip',[i['path'] for i in self.task['inputs']])

    def test_local_visual_references_are_bounded_reads_not_one_eager_image_pack(self):
        for n in range(2):
            item=self.add('image'+str(n),self.png,'image/png','image'+str(n)+'.png','source')
            item['visual_reference']=True;self.task['inputs'].append(item)
        self.bind()
        # Byte counts model local assets; no large generated image fixture.
        items=[dict(i,bytes=6000000 if i.get('visual_reference') else 100) for i in self.task['inputs']]
        executors.validate_input_sizes(items,dict(type='codex-agent'),self.task)
        legacy=copy.deepcopy(self.task);legacy.pop('artifact_roles')
        with self.assertRaisesRegex(ValueError,'10 MB'):executors.validate_input_sizes(items,dict(type='codex-agent'),legacy)
        self.assertEqual(roles.operation_inputs(self.task,'build'),[i for i in self.task['inputs'] if i.get('visual_reference')])
