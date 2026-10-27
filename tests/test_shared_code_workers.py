"""Provider-neutral file/code contracts. Scripted transports, no paid requests."""
import copy
from contextlib import closing
import sys
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import executors,contracts as c
from orchestrator.code_worker import CodeFiles
from orchestrator.gemini_worker import execute
from orchestrator.workers import atomic
from task_relay import code_runtime,native_code_host,api_providers as api
from tests.test_gemini_executor import graph,report

RUNTIME={'adapter':'fixture','python':'fixture','version':'3.14'}
RECEIPT={'version':1,'id':c.digest(RUNTIME),'runtime':RUNTIME,'enabled':True,'tools':{'pptx':{'available':True,'checked':'save/reopen','version':'fixture'}},'checked_at':1}


class Transport:
    def __init__(self,provider,frozen,code=False):self.provider=provider;self.frozen=frozen;self.code=code;self.requests=[]
    def request(self,path,payload,**kwargs):
        self.requests.append((path,copy.deepcopy(payload)));n=len(self.requests)
        name,args=('python_run',{'code':'fixture','seconds':5}) if self.code else ('file_write',{'path':'output.txt','text':'exact fixture'})
        if n>1:name,args='finish',report(self.frozen)
        if self.provider=='gemini':
            return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'thoughtSignature':'retained','functionCall':{'id':str(n),'name':name,'args':args}}]}}]}
        if self.provider=='openai':
            return {'status':'completed','output':[{'type':'reasoning','encrypted_content':'opaque'},
                {'type':'function_call','call_id':str(n),'name':name,'arguments':json.dumps(args)}],'usage':{'input_tokens':7,'output_tokens':3}}
        return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'reasoning_content':'retained','reasoning_details':[{'type':'fixture'}],
            'tool_calls':[{'id':str(n),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],
            'usage':{'prompt_tokens':7,'completion_tokens':3}}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.ws=self.root/'work';self.ws.mkdir();(self.ws/'.relay').mkdir()
        self.control=self.root/'control';self.control.mkdir()
        self.frozen=c.assignment(graph()['tasks'][0]);self.frozen.update(assignment_id='fixture',workspace=str(self.ws))

    def backend(self,provider,code=False):
        value={'type':provider+('-code' if code else '-agent'),'model':'fixture-model'}
        if code:value['runtime']=RECEIPT['id']
        return value

    def host_result(self,runtime,folder,code,seconds,maximum,cancelled):
        out=folder/'outputs';out.mkdir();(out/'output.txt').write_bytes(b'\x00\xffbinary fixture')
        return {'returncode':0,'log':'created fixture','outputs':str(out)}

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_every_provider_preserves_native_calls_and_uses_same_file_contract(self):
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as temporary:
                control=Path(temporary);backend=self.backend(provider);self.frozen['backend']=backend
                config={'api_key':'fixture-only'};atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
                transport=Transport(provider,self.frozen)
                result=execute(self.frozen,control,transport,lambda:(config,backend))
                self.assertEqual(result['decision'],'delivered');self.assertEqual((self.ws/'output.txt').read_text(),'exact fixture')
                path,payload=transport.requests[1]
                if provider=='gemini':self.assertEqual(payload['contents'][1]['parts'][0]['thoughtSignature'],'retained')
                elif provider=='openai':
                    self.assertEqual(path,'responses');self.assertEqual(payload['input'][1]['encrypted_content'],'opaque')
                    self.assertEqual(payload['input'][3]['call_id'],'1')
                else:
                    self.assertEqual(path,'chat/completions');self.assertEqual(payload['messages'][2]['reasoning_content'],'retained')
                    self.assertEqual(payload['messages'][3]['tool_call_id'],'1')
                    if provider=='openrouter':self.assertEqual(payload['provider'],{'allow_fallbacks':False})

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_every_provider_can_export_binary_via_qualified_python(self):
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as temporary:
                control=Path(temporary);backend=self.backend(provider,True);self.frozen['backend']=backend;self.frozen['tools']=['files','python']
                config={'api_key':'fixture-only'};atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
                transport=Transport(provider,self.frozen,True)
                with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result):
                    self.assertEqual(execute(self.frozen,control,transport,lambda:(config,backend))['decision'],'delivered')
                self.assertEqual((self.ws/'output.txt').read_bytes(),b'\x00\xffbinary fixture')
                self.assertEqual(len(list(control.glob('code-*/outcome.json'))),1)
                self.assertIn('Verified runtime tools',json.dumps(transport.requests[0]))

    def files(self):
        self.frozen['backend']=self.backend('qwen',True)
        return CodeFiles(self.frozen,self.control)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_visual_requirement_transports_selected_png_without_a_model_transport_flag(self):
        from tests.test_browser_screenshots import png
        from orchestrator import worker_capabilities
        import base64
        raw=png();(self.ws/'reference.png').write_bytes(raw)
        self.frozen['inputs']=[dict(path='reference.png',sha256=hashlib.sha256(raw).hexdigest(),media_type='image/png')]
        backend=self.backend('gemini',True)
        self.frozen['worker']=dict(requires=['files.text','images.view','code.execute'])
        self.frozen.pop('tools',None)
        worker_capabilities.resolve(self.frozen,[worker_capabilities.entry(backend)],backend)
        self.frozen['backend']=backend
        config={'api_key':'fixture-only'};atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,backend)))
        transport=Transport('gemini',self.frozen)
        with patch.object(code_runtime,'available',return_value=RECEIPT):execute(self.frozen,self.control,transport,lambda:(config,backend))
        parts=transport.requests[0][1]['contents'][0]['parts']
        self.assertEqual([base64.b64decode(p['inlineData']['data']) for p in parts if 'inlineData' in p],[raw])

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_code_worker_receives_exact_declared_visual_pixels(self):
        from tests.test_browser_screenshots import png
        import base64
        raw=png();(self.ws/'candidate.png').write_bytes(raw)
        self.frozen['inputs']=[dict(path='candidate.png',sha256=hashlib.sha256(raw).hexdigest(),visual_reference=True,media_type='image/png')]
        backend=self.backend('gemini',True);self.frozen.update(backend=backend,tools=['files','python'])
        config={'api_key':'fixture-only'};atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,backend)))
        transport=Transport('gemini',self.frozen)
        with patch.object(code_runtime,'available',return_value=RECEIPT):execute(self.frozen,self.control,transport,lambda:(config,backend))
        parts=transport.requests[0][1]['contents'][0]['parts']
        self.assertEqual([base64.b64decode(p['inlineData']['data']) for p in parts if 'inlineData' in p],[raw])

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_render_archive_pixels_reach_reviewer_and_traversal_is_rejected(self):
        from tests.test_browser_screenshots import png
        self.render_archive_observation(png())

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_large_render_preview_reaches_model_and_exact_review_without_extra_call(self):
        from tests.test_visual_review_observation import Tests
        self.render_archive_observation(Tests.large_image(self))

    def render_archive_observation(self,raw):
        from tests.test_operation_session import Script
        from orchestrator.visual_files import read
        import base64,zipfile
        with zipfile.ZipFile(self.ws/'render.zip','w') as z:z.writestr('slides/1.png',raw)
        digest=hashlib.sha256((self.ws/'render.zip').read_bytes()).hexdigest()
        self.frozen.update(inputs=[dict(path='render.zip',sha256=digest,media_type='application/zip')],review_of='producer',
            outputs=[dict(path='review.md',purpose='Independent review',media_type='text/markdown')])
        backend=self.backend('gemini',True);self.frozen.update(backend=backend,tools=['files','python'])
        config={'api_key':'fixture-only'};atomic(self.control/'launch.json',dict(credential_fingerprint=executors.fingerprint(config,backend)))
        script=Script([('image_view',dict(path='render.zip',members=['slides/1.png'])),('finish',dict(report_json=json.dumps(report(self.frozen))))])
        with patch.object(code_runtime,'available',return_value=RECEIPT):execute(self.frozen,self.control,script,lambda:(config,backend))
        pixels=[base64.b64decode(p['inlineData']['data']) for content in script.requests[1]['contents'] for p in content['parts'] if 'inlineData' in p]
        from orchestrator.image_representation import inspection_preview
        expected,_=inspection_preview(raw,'slides/1.png')
        self.assertEqual(pixels,[expected]);self.assertEqual(len(script.requests),2)
        from orchestrator.visual_files import confirmed_pixels,rendered_pixels
        self.assertEqual(confirmed_pixels(self.control),rendered_pixels((self.ws/'render.zip').read_bytes(),'application/zip'))
        with self.assertRaises(ValueError):read(CodeFiles(self.frozen,self.control),dict(path='render.zip',members=['../outside.png']))

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_every_code_provider_can_write_text_and_finish(self):
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as temporary:
                control=Path(temporary);backend=self.backend(provider,True)
                frozen={**self.frozen,'backend':backend,'tools':['files','python']}
                config={'api_key':'fixture-only'};atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
                transport=Transport(provider,frozen)
                with patch.object(code_runtime,'available',return_value=RECEIPT):
                    result=execute(frozen,control,transport,lambda:(config,backend))
                self.assertEqual(result['decision'],'delivered')
                self.assertEqual((self.ws/'output.txt').read_text(),'exact fixture')

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_code_review_finalization_saves_exact_report_without_browser_authority(self):
        from orchestrator.gemini_worker import save_review_report
        self.frozen.update(review_of='producer',outputs=[{'path':'review.md','purpose':'Independent review','media_type':'text/markdown'}])
        # A code worker must not inherit browser privileges from stray metadata.
        self.frozen['browser']={'image_sources':[{'path':'review.md','subjects':[{'id':'sample'}]}],'screenshots':['review.md']}
        files=self.files()
        result={'decision':'revise','summary':'Boundary geometry differs from the source.',
                'checks':[{'criterion':1,'passed':False,'evidence':'Three vertices missing.'}],
                'instruction':'Restore the missing source vertices.'}
        save_review_report(files,self.frozen,result)
        text=(self.ws/'review.md').read_text()
        for exact in ('Decision: revise',result['summary'],result['checks'][0]['evidence'],result['instruction']):
            self.assertIn(exact,text)
        self.assertEqual(set(files.written),{'review.md'})
        with self.assertRaisesRegex(ValueError,'No exact image-source'):
            files.image_source_ready('review.md','sample')
        with self.assertRaisesRegex(ValueError,'No declared screenshot'):
            files.capture_ready('review.md')

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_code_input_hash_and_binary_metadata_grants(self):
        (self.ws/'source.bin').write_bytes(b'\xff\x00fixture')
        self.frozen['inputs']=[{'path':'source.bin','sha256':hashlib.sha256(b'\xff\x00fixture').hexdigest()}]
        files=self.files();result=files.call('file_read',{'path':'source.bin','offset':0,'limit':100})
        self.assertNotIn('text',result);self.assertEqual(result['bytes'],9)
        with self.assertRaises(ValueError):files.call('file_read',{'path':'../private','offset':0,'limit':100})
        (self.ws/'source.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):self.files()

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_ascii_binary_formats_are_not_sent_as_text(self):
        raw=b'%PDF-fixture';(self.ws/'source.pdf').write_bytes(raw)
        self.frozen['inputs']=[{'path':'source.pdf','sha256':hashlib.sha256(raw).hexdigest()}]
        self.assertNotIn('text',self.files().call('file_read',{'path':'source.pdf','offset':0,'limit':100}))

    def test_uncertain_code_is_not_replayed_and_exports_no_files(self):
        files=self.files()
        with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=OSError('lost outcome')) as host:
            with self.assertRaises(OSError):files.run({'code':'fixture','seconds':5})
            with self.assertRaisesRegex(ValueError,'no automatic replay'):files.run({'code':'corrected','seconds':5})
            self.assertEqual(host.call_count,1)
        self.assertFalse(files.written);self.assertFalse((self.ws/'output.txt').exists())

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_known_failure_can_be_corrected_within_same_attempt(self):
        files=self.files()
        with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',return_value={'returncode':1,'log':'SyntaxError','outputs':'unused'}):
            self.assertEqual(files.run({'code':'bad','seconds':5})['returncode'],1)
        with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=self.host_result):
            self.assertEqual(files.run({'code':'corrected','seconds':5})['returncode'],0)
        self.assertEqual(len(list(self.control.glob('code-*/outcome.json'))),2)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_working_files_persist_without_becoming_deliverables(self):
        import os
        def host(runtime,folder,code,*args):
            out=folder/'outputs';out.mkdir();previous=os.getcwd()
            try:
                os.chdir(out);exec(code,{'__name__':'__main__'})
            finally:os.chdir(previous)
            return dict(returncode=0,log='',outputs=str(out))
        with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=host):
            files=self.files()
            first=files.run(dict(code="from pathlib import Path\nPath('build.py').write_text('first')",seconds=5))
            self.assertEqual(first['working_files'],1);self.assertFalse(files.written)
            self.assertFalse((self.ws/'build.py').exists())
            # Restore from committed journals, not an in-memory copy.
            files=self.files()
            files.run(dict(code="from __future__ import annotations\nfrom pathlib import Path\nassert Path('build.py').read_text()=='first'\nPath('build.py').write_text('revised')\nPath('output.txt').write_text('completed from saved script')",seconds=5))
            self.assertEqual(set(files.written),{'output.txt'})
            self.assertEqual((self.ws/'output.txt').read_text(),'completed from saved script')
            first_outcome=next(p for p in self.control.glob('code-*/outcome.json') if json.loads(p.read_text())['workspace']['build.py']['bytes']==5)
            self.assertEqual((first_outcome.parent/'outputs/build.py').read_text(),'first')
            latest,manifest=files.workspace();(latest/'build.py').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'workspace changed'):files.run(dict(code='pass',seconds=5))

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_scratch_files_obey_the_same_quota_and_link_boundaries(self):
        for mode in ('large','symlink','directory_link'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as temporary:
                files=CodeFiles({**self.frozen,'backend':self.backend('qwen',True),'limits':{**self.frozen['limits'],'output_bytes':4}},temporary)
                def host(runtime,folder,*args):
                    output=folder/'outputs';output.mkdir()
                    if mode=='large':(output/'scratch.txt').write_text('too much intermediate content')
                    elif mode=='symlink':(output/'scratch.txt').symlink_to(self.ws/'.relay')
                    else:(output/'scratch-dir').symlink_to(self.ws,target_is_directory=True)
                    return dict(returncode=0,log='',outputs=str(output))
                with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=host):
                    with self.assertRaises((ValueError,OSError)):files.run(dict(code='fixture',seconds=5))
                self.assertFalse(files.written)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX file grants; Windows denial tested separately')
    def test_export_rejects_symlinks_and_over_budget_before_writing(self):
        for mode in ('linked','large'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as temporary:
                files=CodeFiles({**self.frozen,'backend':self.backend('qwen',True),'limits':{**self.frozen['limits'],'output_bytes':4}},temporary)
                def host(runtime,folder,*args):
                    output=folder/'outputs';output.mkdir()
                    if mode=='linked':(output/'output.txt').symlink_to(self.ws/'.relay')
                    else:(output/'output.txt').write_bytes(b'large fixture')
                    return {'returncode':0,'log':'','outputs':str(output)}
                with patch.object(code_runtime,'available',return_value=RECEIPT),patch.object(native_code_host,'run',side_effect=host):
                    with self.assertRaises((ValueError,OSError)):files.run({'code':'fixture','seconds':5})
                self.assertFalse((self.ws/'output.txt').exists())

    def test_provider_verification_is_shared_key_model_bound_and_invalidated_on_failure(self):
        for provider in executors.PROVIDERS[1:]:
            with self.subTest(provider=provider):
                receipt=self.root/(provider+'.json');config={'api_key':'fixture-only','model':'fixture-model'}
                with patch.object(executors,'receipt_path',return_value=receipt),patch.object(api,'read_config',return_value=config),patch.object(api,'catalog',return_value=['fixture-model']):
                    executors.probe(provider);executors.available(self.backend(provider))
                    config['api_key']='changed'
                    with self.assertRaisesRegex(ValueError,'stale'):executors.available(self.backend(provider))
                    with patch.object(api,'catalog',side_effect=ValueError('Disconnected')):
                        with self.assertRaises(ValueError):executors.probe(provider)
                    self.assertEqual(json.loads(receipt.read_text()),{'verified_at':0})
        with self.assertRaisesRegex(ValueError,'exact OpenRouter'):executors.validate({'type':'openrouter-code','model':'openrouter/auto','runtime':RECEIPT['id']})

    def test_provider_protocols_without_native_file_access(self):
        # Also runs on Windows: isolate only the unqualified file adapter, not
        # provider request parsing, tool IDs, response continuation or receipts.
        class FixtureFiles:
            def __init__(self,frozen):self.outputs={'output.txt'};self.written={}
            def read_bytes(self,path):
                if path not in self.written:raise AssertionError('Output was not written')
                return b'exact fixture'
            def source_pack(self):return {'files':[],'text_bytes':0}
            def validate_text_delivery(self,result):pass  # File evidence is tested with the real adapter separately.
            def call(self,name,args):
                if name!='file_write' or args!={'path':'output.txt','text':'exact fixture'}:raise AssertionError('Unexpected provider call')
                self.written['output.txt']=13
                return {'path':'output.txt','bytes':13}
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory(dir=self.root) as temporary:
                control=Path(temporary);backend=self.backend(provider);self.frozen['backend']=backend
                config={'api_key':'fixture-only'};atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,backend)})
                transport=Transport(provider,self.frozen)
                with patch('orchestrator.gemini_worker.Files',FixtureFiles):
                    result=execute(self.frozen,control,transport,lambda:(config,backend))
                self.assertEqual(result['decision'],'delivered')
                _,payload=transport.requests[1]
                if provider=='gemini':self.assertEqual(payload['contents'][2]['parts'][0]['functionResponse']['id'],'1')
                elif provider=='openai':self.assertEqual(payload['input'][3]['call_id'],'1')
                else:self.assertEqual(payload['messages'][3]['tool_call_id'],'1')
                self.assertFalse((self.ws/'output.txt').exists())

    def test_failed_runtime_recheck_disables_previous_success(self):
        receipt=self.root/'runtime.json';atomic(receipt,RECEIPT)
        with patch.object(code_runtime,'path',return_value=receipt),patch.object(native_code_host,'identity',return_value=RUNTIME),patch.object(native_code_host,'run',return_value={'returncode':1}):
            code_runtime.available(RECEIPT['id'])
            with self.assertRaisesRegex(ValueError,'failed'):code_runtime.configure(True)
            self.assertFalse(code_runtime.status()['enabled'])
            with self.assertRaisesRegex(ValueError,'Enable'):code_runtime.available()

    def test_runtime_change_and_unsupported_host_never_enable_unrestricted_code(self):
        receipt=self.root/'runtime.json';atomic(receipt,RECEIPT)
        with patch.object(code_runtime,'path',return_value=receipt),patch.object(native_code_host,'identity',return_value={**RUNTIME,'version':'changed'}):
            self.assertFalse(code_runtime.status()['ready'])
            with self.assertRaisesRegex(ValueError,'changed'):code_runtime.available()
        from task_relay.host import HOST
        with patch.object(HOST,'platform','win32'):
            with self.assertRaisesRegex(ValueError,'Windows'):native_code_host.identity()

    def test_settings_actions_are_bounded_and_do_not_install(self):
        from task_relay.desktop_bridge import _dispatch
        with patch.object(code_runtime,'configure',return_value={'enabled':False}) as check:
            self.assertEqual(_dispatch('code-runtime-configure',{'enabled':False}),{'enabled':False})
            check.assert_called_once_with(False)
            with self.assertRaises(ValueError):_dispatch('code-runtime-configure',{'enabled':True,'command':'pip install'})
        with patch.object(executors,'probe',return_value={'verified':True}) as probe:
            self.assertEqual(_dispatch('worker-verify',{'provider':'qwen'}),{'verified':True});probe.assert_called_once_with('qwen')
            with self.assertRaises(ValueError):_dispatch('worker-verify',{'provider':'invented'})

    def test_usage_and_stage_templates_keep_the_actual_provider(self):
        import sqlite3
        from task_relay import usage_tracker
        from orchestrator import templates
        source=self.root/'usage-source.sqlite'
        with closing(sqlite3.connect(source)) as db, db:
            db.execute('CREATE TABLE production_attempts(id TEXT,frozen TEXT,receipt TEXT)')
            for provider in executors.PROVIDERS:
                for code in (False,True):
                    backend=self.backend(provider,code)
                    plan=templates.build('competition','fixture',[],backend)
                    self.assertEqual(plan['tasks'][0]['tools'],executors.validate(backend))
                    db.execute('INSERT INTO production_attempts VALUES (?,?,?)',(backend['type'],json.dumps({'backend':backend}),
                        json.dumps({'usage':[{'input_tokens':7,'output_tokens':4}],'finished':1})))
        ledger=sqlite3.connect(':memory:');ledger.row_factory=sqlite3.Row
        try:
            usage_tracker.initialize(ledger);usage_tracker.collect_relay(ledger,source);usage_tracker.collect_relay(ledger,source)
            rows=ledger.execute('SELECT provider,counts FROM usage_events').fetchall();self.assertEqual(len(rows),10)
            for provider in executors.PROVIDERS:self.assertEqual(sum(r['provider']==provider for r in rows),2)
            self.assertTrue(all(json.loads(r['counts'])['total_tokens']==11 for r in rows))
        finally:ledger.close()

    def test_windows_file_grants_reject_before_access(self):
        from task_relay.host import Host, UnsupportedHost
        from task_relay.filesystem import Filesystem, Grant
        files = Filesystem(Host('win32'))
        grant = Grant(self.ws, 'windows boundary', frozenset({'input.txt'}), frozenset({'output.txt'}))
        (self.ws/'input.txt').write_text('preserved')
        with self.assertRaises(UnsupportedHost): files.read(grant, 'input.txt', 100)
        with self.assertRaises(UnsupportedHost): files.write(grant, 'output.txt', b'not written')
        self.assertFalse((self.ws/'output.txt').exists())


if __name__=='__main__':unittest.main()
