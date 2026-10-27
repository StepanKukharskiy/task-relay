"""Desktop intake through actual API tool loops and native PPTX delivery.

Only model replies/public sources and runtime availability are controlled. Code
inspection executes in the real host sandbox. No factory.finish, direct record
submissions, accepted-state injection, live API, browser or visual-quality claim.
"""
import json,sys,shlex,runpy
from pathlib import Path
from unittest.mock import patch
from orchestrator import contracts as c,executors,operation_contracts,operation_records as records,sourcing_contract,worker_capabilities
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from task_relay import native_code_host
from tests import test_desktop_sourcing_delivery as fixture
from tests.test_sourcing_records import CONFIG,BACKEND
from tests.test_operation_session import Script


class Tests(fixture.Tests):
    # Run two deliberate sequences, not the inherited orchestration-only cases.
    test_code_partitioned_room_reaches_delivery_with_exact_source_versions=None
    test_early_checkpoint_and_runtime_restart_still_deliver_without_new_prompt=None
    test_normal_desktop_chain_delivers_partial_pptx_with_current_composed_versions=None

    @property
    def _final_quality_seen(self):
        # This harness launches the final CLI reviewer rather than calling the
        # parent's synthetic finish helper. Inspect its collected report event.
        rows=self.state.db.execute("SELECT a.frozen,e.data FROM production_events e JOIN production_attempts a ON a.id=e.attempt WHERE e.kind='checks_recorded'")
        return any(json.loads(r['frozen']).get('final_quality') and json.loads(r['data']).get('kind')=='model_review' for r in rows)

    def proposal(self,row,context=None):
        raw,usage=super().proposal(row,context);value=json.loads(raw)
        if not getattr(self,'_bad_plan',False):self._bad_plan=True;return '{"decision":',usage
        for task in value['plan']['tasks']:
            if task['id'] in ('photos_review','queries','queries_review'):
                task['worker']=dict(executor='gemini-code',requires=['files.binary','code.execute'])
            if task['id']=='search_review':task['worker']=dict(requires=['files.text'])
        return c.encoded(value),usage

    def complete_agent(self,aid):
        session=self.factory.sessions[aid];f=session['frozen'];control=self.rt.root/'workers'/aid
        control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,f['backend'])))
        steps=[];contract=f.get('operation_contract',{}).get('id')
        if f['backend']['type'] in executors.CODE_TYPES:
            # Read every bound input and inspect every ZIP/PPTX member. A deck
            # assertion runs inside the actual declared-input sandbox.
            code='''import os,json,zipfile
from pathlib import Path
root=Path(os.environ['RELAY_INPUTS'])
for p in sorted(root.rglob('*')):
 if not p.is_file():continue
 raw=p.read_bytes()
 if p.suffix in ('.zip','.pptx'):
  with zipfile.ZipFile(p) as z:
   assert z.testzip() is None
   if p.suffix=='.pptx':
    text=''.join(z.read(n).decode() for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml'))
    assert '349.99' in text and 'VIS-001' in text
 elif p.suffix=='.json':json.loads(raw)
 print(p.name,len(raw))
print('EXACT_INPUTS_INSPECTED')
'''
            steps.append(('python_run',dict(code=code,seconds=30)))
        if contract:
            store=records.Store(f,self.state.db);revision=store.progress()['revision']
            def submit(key,rows):
                nonlocal revision
                steps.append(('operation_submit',dict(request_key=key,revision=revision,records_json=c.encoded(rows))));revision+=1
            if contract=='sourcing.inventory':
                submit('item-1',[dict(kind='item',slot=1,label='Walnut desk',category='furniture',bbox=[.1,.1,.8,.8],confidence='medium',notes='Scripted visual judgment')])
                submit('end',[dict(kind='end',count=1,notes='Controlled inventory')])
            elif contract=='operation.preparation':
                self.assertEqual(f['operation_contract']['parameters']['target'],'web.sources.prepared')
                submit('query-target',[dict(kind='append',field='targets',index=0,value=dict(id='VIS-001',queries=['walnut desk US 1'],required_options=3))])
                submit('query-end',[dict(kind='end')])
            elif contract=='sourcing.options':
                ctx=store.sourcing_context();observation=next(iter(ctx['observations']))
                fields={k:dict(status='unknown',reason='Not established') for k in sourcing_contract.FIELDS}
                for key,quote in [('name_variant','Walnut desk'),('price','USD Price $349.99'),('dimensions','Width 120 cm'),('us_context','Ships to United States'),('order_terms','Order online')]:
                    start=ctx['observations'][observation]['text'].index(quote);fields[key]=dict(status='observed',start=start,end=start+len(quote))
                for item in ctx['inventory']:submit(item,[dict(item=item,options=[dict(observation=observation,fields=fields,comparison='Scripted correspondence judgment')],gap='Only one verified synthetic option found')])
            else:
                for item_id,item in store.sourcing_context()['items'].items():submit(item_id,[dict(item=item_id,item_sha256=operation_contracts.digest(item),verdict='supported',reason='Accurate included facts and explicit advisory gap')])
        elif not f.get('review_of'):
            self.assertEqual(f['id'],'queries')
            steps.append(('file_write',dict(path='queries.json',text=c.encoded(dict(version=1,targets=[dict(id='VIS-001',queries=['walnut desk US 1'],required_options=3)])))))
        checks={key:dict(passed=True,evidence='Exact input version inspected; supported facts and target-count gaps retained') for key in f['report_contract']['schema']['properties']['checks']['properties']}
        report=dict(summary='Controlled model judgment',decision='accept' if f.get('review_of') else 'delivered',instruction='',findings=[],checks=checks)
        if getattr(self,'inject_yield',False) and f.get('evidence_context') and not getattr(self,'_yielded',None):
            self._yielded=aid
            key=next(iter(checks));steps=[('report_check',dict(check=key,value_json=c.encoded(checks[key])))]+[('finish',dict(report_json='{"decision":'))]*(executors.request_limit(f)-1)
        else:
            # Refine provisional evidence at the terminal call, including after
            # a durable continuation. No separate amend tool is required.
            for key in checks:checks[key]['evidence']+='; final wording after complete inspection'
            steps.append(('finish',dict(report_json=c.encoded(report))))
        from contextlib import ExitStack
        historical_projection=(getattr(self,'inject_projection',False) and f.get('review_of') and contract
            and not getattr(self,'_projection_stopped',None) and any(i.get('from_task')==f['review_of'] and i['path']==f['operation_contract']['parameters'].get('source_pack_path') for i in f['inputs']))
        if historical_projection:self._projection_stopped=self._yielded=aid
        script=Script(steps)
        class Model:
            def request(inner,endpoint,payload,**kwargs):
                if f.get('evidence_context'):
                    first=json.loads(payload['contents'][0]['parts'][0]['text'])
                    last=payload['contents'][-1]['parts'][0].get('functionResponse',{})
                    remaining=last.get('response',{}).get('remaining',first['review_session']['remaining'])
                    if remaining:return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(functionCall=dict(name='evidence_next',args={}))]))])
                return script.request(endpoint,payload,**kwargs)
        try:
            with ExitStack() as stack:
                stack.enter_context(patch('orchestrator.gemini_worker.emit'))
                if historical_projection:stack.enter_context(patch('orchestrator.review_inputs.candidates',lambda value:[i['path'] for i in value['inputs'] if i.get('from_task')==value['review_of']]))
                import orchestrator.gemini_worker as entry
                stack.enter_context(patch('task_relay.gemini.Client',return_value=Model()))
                stack.enter_context(patch.object(executors,'configured_worker',return_value=(CONFIG,f['backend'])))
                stack.enter_context(patch.object(sys,'argv',[entry.__file__,str(control),f['workspace']]))
                runpy.run_path(entry.__file__,run_name='__main__')
            code=0;reason=None
        except (ValueError,StopIteration,SystemExit) as exc:
            code=1;reason=json.loads((control/'agent-result.json').read_text()).get('reason') if (control/'agent-result.json').exists() else str(exc)
        session['status']=dict(status='finished',token=aid,exit_code=code,reason=reason,external_outcome='no_pending_response',pending_requests=[],api_requests=len(list(control.glob('api-*.request.json'))),tool_calls=len(list(control.glob('tool-*.json'))))
        if aid!=getattr(self,'_yielded',None):
            self.assertEqual(code,0,dict(task=f['id'],reason=reason,tools=[json.loads(p.read_text()) for p in control.glob('tool-*.json')]))
            if f['backend']['type'] in executors.CODE_TYPES:
                value=json.loads((control/'tool-01-00.json').read_text())['result']
                self.assertNotIn('error',value);self.assertIn('EXACT_INPUTS_INSPECTED',value.get('log',''))
                self.code_inspections+=1

    def run_chain(self,yielded,projection=False):
        self.inject_yield=yielded;self.code_inspections=0
        self.inject_projection=projection
        runtime=native_code_host.identity();backend=dict(type='gemini-code',model=BACKEND['model'],runtime=c.digest(runtime))
        self.additional_workers=[worker_capabilities.entry(backend)]
        from orchestrator.workers import CodexFactory
        executable=Path(self.tmp.name)/'controlled-codex'
        program=executable.with_suffix('.py')
        program.write_text('''import sys,json,zipfile,os
from pathlib import Path
from PIL import Image
os.chdir(sys.argv[sys.argv.index('-C')+1])
f=json.loads(Path('.relay/ASSIGNMENT.json').read_text())
print(json.dumps(dict(type='item.started',item=dict(type='command_execution',command='inspect exact declared native inputs'))),flush=True)
for item in f['inputs']:
 p=Path(item['path']);raw=p.read_bytes()
 if p.suffix in ('.zip','.pptx'):
  with zipfile.ZipFile(p) as z:
   assert z.testzip() is None
   if p.suffix=='.pptx':
    text=''.join(z.read(n).decode() for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml'))
    assert '349.99' in text and 'VIS-001' in text
 elif p.suffix=='.json':json.loads(raw)
 elif p.suffix=='.png':
  with Image.open(p) as image:image.load()
checks={key:dict(passed=True,evidence='Controlled independent judgment after exact native input inspection; advisory gaps retained') for key in f['report_contract']['schema']['properties']['checks']['properties']}
for number,binding in f.get('final_quality',{}).get('checks',{}).items():
 refs=[dict(path=p,location='Exact synthetic candidate and inspection companion') for p in dict.fromkeys([binding['candidate'],*binding['inspection_inputs'],*[i['path'] for i in f['inputs'] if i.get('visual_reference')]])]
 dimensions=('requirements','reference_fit','evidence','usability')
 checks['c'+number]['evidence']={d:dict(verdict='satisfied',reason='Scripted semantic fixture judgment only',inspected=refs) for d in dimensions}
report=dict(summary='Controlled native review',decision='accept',instruction='',findings=[],checks=checks)
for output in f['outputs']:
 p=Path(output['path']);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(report['summary']+'\\n'+'\\n'.join(v['evidence'] if isinstance(v['evidence'],str) else json.dumps(v['evidence']) for v in checks.values()))
Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(report))
print(json.dumps(dict(type='turn.completed',usage=dict(input_tokens=10,output_tokens=5))),flush=True)
''')
        executable.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(program))+' \"$@\"\n');executable.chmod(0o700)
        self.cli_factory=CodexFactory(executable=executable)
        create=self.factory.create
        def create_api(*args):
            session=create(*args);session['adapter']='gemini-agent';return session
        self.factory.create=create_api
        availability=dict(id=backend['runtime'],enabled=True,runtime=runtime,tools={})
        resolve=worker_capabilities.resolve
        def diagnose(task,*args):
            try:return resolve(task,*args)
            except ValueError as exc:raise ValueError(task['id']+': '+str(exc)) from exc
        # Recorded public-page metadata and image transport only. Collection,
        # identity binding, ZIP creation and PPTX embedding remain real code.
        from tests.test_image_sources import photo
        original_fetch=fixture.SourceSession.fetch
        def observed_page(session,url,*args,**kwargs):
            page=original_fetch(session,url,*args,**kwargs)
            page.update(products=[dict(name='Walnut desk')],images=[dict(url='https://store.example/desk.jpg',basis='observed-product-jsonld',product_names=['Walnut desk'])])
            return page
        def download(url,*args,**kwargs):
            self.assertEqual(url,'https://store.example/desk.jpg')
            return photo(),'image/jpeg',url
        with patch('task_relay.code_runtime.available',return_value=availability),patch.object(worker_capabilities,'resolve',side_effect=diagnose),patch('task_relay.app_access.require'),patch.object(fixture,'TEXT',fixture.TEXT*(1600 if projection else 1)),patch.object(fixture.SourceSession,'fetch',observed_page),patch('orchestrator.image_sources.download',side_effect=download):
            try:fixture.Tests.test_normal_desktop_chain_delivers_partial_pptx_with_current_composed_versions(self)
            except AssertionError:
                for log in self.rt.root.glob('workers/*/stderr.txt'):print(log.name,log.read_text())
                raise
        self.assertGreaterEqual(self.code_inspections,3)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],3)
        import hashlib,io,zipfile
        from orchestrator import image_sources
        results={row['id']:json.loads(row['result'])['deliverables'] for row in self.state.db.execute('SELECT id,result FROM relay_pipeline_steps')}
        def artifact_bytes(stage,name):return Path(self.rt.artifact(results[stage][name]['artifact'])['blob']).read_bytes()
        catalog=json.loads(artifact_bytes('catalog','catalog'))
        images,_,manifest=image_sources.unpack(artifact_bytes('catalog','photos'))
        self.assertEqual(manifest['coverage'],dict(found=1,missing=0,total=1))
        self.assertEqual(manifest['source_catalog_sha256'],hashlib.sha256(artifact_bytes('catalog','catalog')).hexdigest())
        entry=manifest['subjects'][0]
        self.assertEqual(entry['id'],catalog['items'][0]['options'][0]['option_id'])
        self.assertEqual(entry['source_url'],'https://store.example/products/desk')
        self.assertEqual(images[entry['path']],photo())
        self.assertEqual(entry['sha256'],hashlib.sha256(photo()).hexdigest())
        with zipfile.ZipFile(io.BytesIO(artifact_bytes('finish','finish'))) as deck:
            self.assertIn(photo(),[deck.read(n) for n in deck.namelist() if n.startswith('ppt/media/')])
        if yielded or projection:
            self.assertTrue(self._restarted)
            self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='local_review_session_queued'").fetchone()[0],1)
        import os,shutil
        if os.environ.get('RELAY_STAGE_PROOF_OUTPUT'):
            target=Path(os.environ['RELAY_STAGE_PROOF_OUTPUT']);target.mkdir(parents=True,exist_ok=True)
            stages=[]
            for row in self.state.db.execute('SELECT id,result FROM relay_pipeline_steps ORDER BY id'):
                result=json.loads(row['result']);files={}
                for name,detail in result.get('deliverables',{}).items():
                    artifact=self.rt.artifact(detail['artifact']);folder=target/row['id'];folder.mkdir(exist_ok=True)
                    path=folder/(name+Path(artifact['path']).suffix);shutil.copyfile(artifact['blob'],path)
                    files[name]=dict(path=str(path),artifact=artifact['id'],sha256=artifact['sha256'])
                stages.append(dict(stage=row['id'],outputs=files))
            atomic(target/'stages.json',dict(controlled=True,live_provider_calls=0,stages=stages))

    def test_actual_tool_loops_reach_native_pptx(self):self.run_chain(False)
    def test_malformed_report_yield_and_restart_reach_native_pptx(self):self.run_chain(True)
    def test_zero_dispatch_capacity_stop_recovers_composed_source_review_to_pptx(self):self.run_chain(False,projection=True)
