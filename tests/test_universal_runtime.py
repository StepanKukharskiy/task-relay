"""Synthetic transport/host peers over real Relay lifecycle; never paid/native runs."""
import base64
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import agent_context, agent_transport, contracts as c, execution, worker_tools
from orchestrator.operation_adapters import Adapter
from orchestrator.operation_execution import Context, Result
from orchestrator.runtime_outcomes import Hold, UncertainOperation
from orchestrator.workers import atomic
from tests import test_worker_tools as work_fixture
from tests.test_operation_session import Script, CONFIG


class ContextTests(unittest.TestCase):
    def test_all_provider_wires_deduplicate_repeated_large_images_without_losing_journals(self):
        raw=b'large synthetic representation'*190000
        encoded=base64.b64encode(raw).decode();other=base64.b64encode(b'another image').decode()
        for provider in ('gemini','openai','qwen','deepseek','openrouter','codex'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);transport=agent_transport.Transport(provider)
                parts=lambda data:dict(inlineData=dict(mimeType='image/png',data=data)) if provider=='gemini' else dict(type='input_image',image_url='data:image/png;base64,'+data) if provider=='openai' else dict(type='image_url',image_url=dict(url='data:image/png;base64,'+data))
                field='parts' if provider=='gemini' else 'content'
                messages=[dict(role='user',**{field:[parts(encoded),dict(text='Exact original request: "quoted" \\ data')]}),dict(role='user',**{field:[parts(other)]}),dict(role='user',**{field:[parts(encoded)]}),dict(role='user',**{field:[parts(encoded)]})]
                original=copy.deepcopy(messages);payload={transport.key:messages}
                atomic(folder/'original.json',payload);before=(folder/'original.json').read_bytes()
                actual=agent_context.prepare(transport,payload,object(),folder,1)
                images=[agent_context.image_data(p) for m in actual[transport.key] for p in m[field] if agent_context.image_data(p)]
                self.assertEqual(len(images),2);self.assertEqual(messages,original)
                self.assertEqual((folder/'original.json').read_bytes(),before)
                receipt=json.loads((folder/'dispatch-context-01.json').read_text())
                self.assertGreater(receipt['logical_bytes'],16_000_000);self.assertLess(receipt['wire_bytes'],16_000_000)
                self.assertIsNone(receipt['provider_retained_tokens'])
                again=agent_context.prepare(transport,actual,object(),folder,2)
                self.assertEqual(again,actual)

    def test_distinct_old_images_are_archived_while_latest_observation_batch_is_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            messages=[dict(role='user',parts=[dict(inlineData=dict(mimeType='image/png',data=base64.b64encode(bytes([i])*1000000).decode()))]) for i in range(5)]
            original=copy.deepcopy(messages)
            projected,receipt=agent_context.project(messages,Path(tmp),max_image_bytes=3000000)
            self.assertEqual(projected[-1],messages[-1]);self.assertEqual(messages,original)
            self.assertEqual(receipt['archived_images'],3)
            self.assertLessEqual(receipt['retained_pixel_bytes'],3000000)
            self.assertEqual(len(list(Path(tmp).glob('*.json'))),5)
            # Several images requested in the newest batch are never silently
            # removed before the response that can confirm their observation.
            batch=[dict(role='user',parts=[part for m in messages for part in m['parts']])]
            protected,_=agent_context.project(batch,Path(tmp),max_image_bytes=3000000)
            self.assertEqual(batch,protected)

    def test_persistent_transport_measures_next_message_and_holds_before_dispatch(self):
        class Peer:
            def prepare_request(self,payload):return dict(method='item/tool/call',params=dict(output='confirmed small reply'))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);payload=dict(messages=[dict(role='user',content='x'*17_000_000)])
            agent_context.prepare(agent_transport.Transport('codex'),payload,Peer(),folder,1)
            self.assertLess(json.loads((folder/'dispatch-context-01.json').read_text())['wire_bytes'],1000)
            with self.assertRaises(Hold):agent_context.prepare(agent_transport.Transport('qwen'),payload,Peer(),folder,2)
            self.assertFalse(list(folder.glob('api-*.request.json')))

    def test_transport_dispatch_is_provider_specific_and_legacy_entry_is_same_loop(self):
        from orchestrator import agent_loop,gemini_worker
        self.assertIs(agent_loop,gemini_worker)
        tool=dict(name='read',description='Read',parameters=dict(type='object',properties={}))
        for provider in ('gemini','openai','qwen','deepseek','openrouter','codex'):
            t=agent_transport.Transport(provider)
            endpoint,payload=t.payload(dict(model='fixture'),'exact system',[tool],[dict(role='user',parts=[dict(text='request')])],[dict(role='user',content='request')],128)
            self.assertEqual(endpoint,'models/fixture:generateContent' if provider=='gemini' else 'responses' if provider=='openai' else 'chat/completions')
            self.assertIn(t.key,payload)
            if provider=='openrouter':self.assertFalse(payload['provider']['allow_fallbacks'])


POLL_COUNT=0
DISPATCH_COUNT=0
INTERRUPT=False

def pending_peer(ctx):
    global DISPATCH_COUNT
    DISPATCH_COUNT+=1
    return Result(receipt=dict(outcome='pending',handle='exact-external-handle'))

def read_peer(ctx,receipt):
    global POLL_COUNT
    POLL_COUNT+=1
    if INTERRUPT:raise InterruptedError('Controlled status reader restart')
    if receipt['handle']!='exact-external-handle':raise AssertionError('Changed handle')
    for output in ctx.frozen.get('outputs',[]):
        path=ctx.workspace/output['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Synthetic reconciled output')
    return Result(receipt=dict(outcome='completed',handle=receipt['handle'],effect='confirmed'))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        global DISPATCH_COUNT,POLL_COUNT,INTERRUPT
        DISPATCH_COUNT=POLL_COUNT=0;INTERRUPT=False
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.frozen=dict(assignment_id='fixture',execution=dict(capability='blender.startup',version=1,parameters={}),inputs=[dict(path='exact',sha256='a'*64)],limits=dict(seconds=5))
        self.ctx=Context(self.frozen,self.folder,self.folder,execution.REGISTRY['blender.startup'],[])
        self.adapter=replace(execution.adapter('blender.startup'),reconcile='tests.test_universal_runtime:read_peer')
        self.addCleanup(patch.stopall)
        patch('orchestrator.execution.adapter',return_value=self.adapter).start()
        patch.object(Adapter,'execute',side_effect=pending_peer).start()

    def test_pending_restart_reconciles_exact_handle_then_reuses_terminal_without_dispatch(self):
        global INTERRUPT
        from orchestrator.operation_lifecycle import invoke
        INTERRUPT=True
        with self.assertRaises(InterruptedError):invoke(self.ctx)
        original=json.loads((self.folder/'operation-dispatch.json').read_text())
        INTERRUPT=False;self.assertEqual(invoke(self.ctx).receipt['outcome'],'completed')
        self.assertEqual(invoke(self.ctx).receipt['outcome'],'completed')
        self.assertEqual(DISPATCH_COUNT,1);self.assertEqual(POLL_COUNT,2)
        self.assertEqual(json.loads((self.folder/'operation-dispatch.json').read_text()),original)

    def test_changed_inputs_unknown_dispatch_and_expired_pending_never_resubmit(self):
        global INTERRUPT
        from orchestrator.operation_lifecycle import invoke
        INTERRUPT=True
        with self.assertRaises(InterruptedError):invoke(self.ctx)
        self.frozen['inputs'][0]['sha256']='b'*64
        with self.assertRaisesRegex(UncertainOperation,'identity changed'):invoke(self.ctx)
        self.frozen['inputs'][0]['sha256']='a'*64
        intent=json.loads((self.folder/'operation-dispatch.json').read_text());intent['deadline']=0;atomic(self.folder/'operation-dispatch.json',intent)
        INTERRUPT=False
        with self.assertRaisesRegex(UncertainOperation,'stopped waiting'):invoke(self.ctx)
        (self.folder/'operation-pending.json').unlink()
        with self.assertRaisesRegex(UncertainOperation,'no resubmission'):invoke(self.ctx)
        self.assertEqual(DISPATCH_COUNT,1);self.assertEqual(POLL_COUNT,1)

    def test_external_exception_is_uncertain_while_confirmed_failure_is_terminal(self):
        from orchestrator.operation_lifecycle import terminal
        with self.assertRaises(UncertainOperation):terminal(self.frozen,self.folder,ValueError('socket lost'))
        atomic(self.folder/'operation.json',dict(outcome='failed',effect='none',reason='Rejected before submission'))
        self.assertEqual(terminal(self.frozen,self.folder)['effect'],'none')


class WorkTests(unittest.TestCase):
    setUp=work_fixture.Tests.setUp
    create=work_fixture.Tests.create
    source=work_fixture.Tests.source
    session=work_fixture.Tests.session
    invoke=work_fixture.Tests.invoke
    admit=work_fixture.Tests.admit
    text_work=work_fixture.Tests.text_work
    report=work_fixture.Tests.report

    def test_binary_identity_evidence_is_not_decoded_or_consumed_as_text(self):
        self.grant.update(worker_tools_version=2,deliverables={'report':'text/plain'})
        text=self.source('Exact text source')
        path=self.root/'opaque.blend';path.write_bytes(b'BLENDER\x00\xff synthetic identity fixture')
        binary=dict(artifact=self.rt.register(path,'Synthetic binary evidence'),path='prior/opaque.blend',media_type='application/x-blender',purpose='Identity evidence',authority='No visual observation implied')
        self.create(inputs=[text,binary]);self.rt.tick('job')
        args=dict(request_id='identity',tasks=[dict(id='make',objective='Bundle text with retained binary provenance',inputs=[dict(artifact=i['artifact']) for i in [text,binary]],work=dict(operation='text.bundle',parameters={}))])
        self.session().delegate(args);self.rt.tick('job')
        state=self.factory.sessions[self.rt.task('job','make')['latest']];f=state['frozen']
        control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        from orchestrator import artifact_roles
        files=worker_tools.files(f,control)
        self.assertEqual(files.call('file_read',dict(path=binary['path'],offset=0,limit=100))['inspection']['tool'],'artifact_inspect')
        proof=files.call('artifact_inspect',dict(path=binary['path']))
        self.assertFalse(proof['visual_observation']);self.assertFalse(proof['semantic_acceptance'])
        self.assertEqual(proof['bytes'],len(path.read_bytes()))
        self.assertNotIn(binary['path'],[i['path'] for i in artifact_roles.operation_inputs(f,'build')])
        worker_tools.Session(files,control).run(dict(step='build',request_key='one'))
        result=(Path(f['workspace'])/f['outputs'][0]['path']).read_text()
        self.assertIn('Exact text source',result);self.assertNotIn('BLENDER',result)

    def test_operation_graph_correction_and_downstream_version_binding(self):
        # A new compatible operation requires registration only, no worker switch.
        from orchestrator.execution import ADAPTERS
        from orchestrator.owner_intents import compile
        cap='fixture.transform';spec=copy.deepcopy(execution.REGISTRY['text.bundle']);spec['parameters']={}
        with patch.dict(execution.REGISTRY,{cap:spec}),patch.dict(ADAPTERS,{cap:execution.adapter('text.bundle')}):
            self.grant['operations'].append(cap);self.grant['deliverables']={'report':'text/plain'}
            ref=self.source('Original exact source.')
            self.create(inputs=[ref]);self.rt.tick('job')
            s=self.session();s.delegate(dict(request_id='graph',tasks=[dict(id='make',objective='Compose compatible steps',inputs=[dict(artifact=ref['artifact'])],work=dict(operation='text.bundle',mode='execute',steps=[dict(id='transform',operation=cap,from_steps=['build'])]))]))
            self.rt.tick('job');state=self.factory.sessions[self.rt.task('job','make')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
            files=worker_tools.files(f,control);w=worker_tools.Session(files,control)
            # Run the real local step runner in-process so the synthetic registry is visible.
            from orchestrator.step_runner import execute
            with patch.object(worker_tools,'execute_local',side_effect=lambda sub,folder,*_:execute(sub,folder)):
                first=w.run(dict(step='build',request_key='build-1'));old=w.run(dict(step='transform',request_key='transform-1'))
                self.assertTrue(w.run(dict(step='transform',request_key='transform-1'))['reused'])
                self.assertEqual(w.validate_delivery(False)['acceptance'],False)
                # Restart retains receipts and no operation is resubmitted.
                restored=worker_tools.Session(worker_tools.files(f,control),control)
                self.assertEqual(restored.validate_delivery(False),w.validate_delivery(False))
                self.assertEqual(len(restored.receipts),2)
            self.assertTrue(any(i['path'].startswith('inputs/build/') for i in restored.current['transform'][1]['inputs']))
            native=json.loads((control/'work-operations/0002/workspace/.relay/ASSIGNMENT.json').read_text())
            for item in native['inputs']:self.assertEqual(self.rt.artifact(item['artifact'])['sha256'],item['sha256'])
            self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_artifacts WHERE task='make'").fetchone()[0],0)

    def test_registered_host_resource_sets_and_bound_step_hashes(self):
        from orchestrator.operation_lifecycle import resources
        from orchestrator.owner_intents import native_outputs,ports
        caps=('blender.startup','rhino.startup','sketchup.startup')
        task=dict(id='make',instruction='Run granted peers',inputs=[],outputs=[])
        worker_tools.configure(task,dict(operation=caps[0],steps=[dict(id='rhino',operation=caps[1]),dict(id='sketchup',operation=caps[2])]),dict(worker_tools_version=2,operations=list(caps),task_limits=dict(tool_calls=24,provider_requests=24)))
        self.assertEqual(resources(task),{'host-blender','host-rhino','host-sketchup'})
        previous=dict(operation='blender.scene',outputs=worker_tools.output_map('blender.scene','build'))
        port=next(k for k,v in ports(dict(outputs=native_outputs('blender.scene'))).items() if v['media_type']=='application/x-blender')
        step=dict(operation='blender.run_python',parameters=dict(scene_sha256=dict(step='build',output=port)),from_steps=['build'])
        worker_tools.bind_step_parameters(step,dict(build=previous))
        binding=step['parameter_bindings']['scene_sha256'][0]
        selected=dict(path='inputs/build/'+Path(binding['path']).name,media_type=binding['media_type'],sha256='a'*64)
        self.assertEqual(worker_tools.parameters(step,[selected])['scene_sha256'],'a'*64)
        selected['sha256']='b'*64
        self.assertEqual(worker_tools.parameters(step,[selected])['scene_sha256'],'b'*64)

    def test_terminal_operation_budget_does_not_spend_more_model_calls(self):
        from orchestrator.agent_loop import execute
        f,control,state=self.text_work()
        with patch.object(worker_tools.Session,'remaining',return_value=0):
            script=Script([])
            with self.assertRaises(Hold):execute(f,control,script,lambda:(CONFIG,f['backend']))
            self.assertEqual(script.requests,[])

    def test_blender_rhino_sketchup_peers_share_graph_resources_and_final_delivery(self):
        from orchestrator import executors
        from orchestrator.agent_loop import execute
        from orchestrator.step_runner import execute as native_execute
        from tests.test_owner_intents import Tests as OwnerFixture
        from orchestrator.owner_compilation import label
        caps=['blender.startup','rhino.startup','sketchup.startup','text.bundle']
        self.grant['operations']=caps;self.grant['deliverables']={'report':'text/plain'}
        ref=self.source('Synthetic host-peer request; no app launches.')
        self.create(inputs=[ref]);self.rt.tick('job')
        steps=[dict(id='rhino',operation=caps[1]),dict(id='sketchup',operation=caps[2]),dict(id='combine',operation='text.bundle',from_steps=['build','rhino','sketchup'])]
        s=self.session();s.delegate(dict(request_id='hosts',tasks=[dict(id='make',objective='Run and combine exact registered host receipts',inputs=[dict(artifact=ref['artifact'])],work=dict(operation=caps[0],mode='execute',steps=steps)),dict(id='other',objective='Use the same host resource',inputs=[dict(artifact=ref['artifact'])],work=dict(operation=caps[0],mode='execute'))]))
        freeze=Adapter.freeze
        def controlled_freeze(adapter,f,spec):
            if spec['kind']=='host':return
            return freeze(adapter,f,spec)
        calls=[]
        def host_peer(ctx):
            calls.append(ctx.frozen['execution']['capability'])
            for output in ctx.frozen['outputs']:
                (ctx.workspace/output['path']).parent.mkdir(parents=True,exist_ok=True)
                atomic(ctx.workspace/output['path'],dict(synthetic_host_peer=True,capability=ctx.frozen['execution']['capability']))
            return Result(receipt=dict(outcome='completed',effect='confirmed',synthetic=True))
        with patch.object(Adapter,'freeze',controlled_freeze),patch.object(Adapter,'check_available'),patch('orchestrator.operation_execution.native',side_effect=host_peer):
            self.rt.tick('job');self.assertIsNone(self.rt.task('job','other')['latest'])
            state=self.factory.sessions[self.rt.task('job','make')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
            atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,f['backend'])))
            script=Script([('work_run',dict(step=step,request_key=step)) for step in ['build','rhino','sketchup','combine']]+[self.report(f)])
            with patch.object(worker_tools,'execute_local',side_effect=lambda sub,folder,*_:native_execute(sub,folder)):
                execute(f,control,script,lambda:(CONFIG,f['backend']))
            self.assertEqual(calls,caps[:3]);worker_tools.verify_delivery(f,control)
            state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
            self.rt.tick('job');self.assertEqual(self.rt.task('job','make')['status'],'awaiting_review')
            self.assertIsNotNone(self.rt.task('job','other')['latest'])
            # Ordinary independent review and owner completion are exercised by
            # the real deck graph; this check ends at the exact review handoff.
            self.assertEqual(self.rt.output('job','make','outputs/work-combine/result.txt')['attempt'],f['assignment_id'])
            self.assertIsNotNone(self.rt.task('job',label('make','review')))

    def test_large_image_reinspection_real_deck_correction_restart_and_review(self):
        import io,random
        from PIL import Image
        from orchestrator.agent_loop import execute
        from orchestrator import executors
        self.grant['task_limits'].update(seconds=600)
        raw=random.Random(3).randbytes(1800*1200*3)
        path=self.root/'large.png';Image.frombytes('RGB',(1800,1200),raw).save(path)
        aid=self.rt.register(path,'Synthetic noise image; transport fixture')
        ref=dict(artifact=aid,path='prior/large.png',purpose='Synthetic reference',authority='No factual or visual quality claims',media_type='image/png')
        f,control,state=self.admit(inputs=[ref])
        page=dict(kind='page',slot=1,layout='text',content=dict(title='Initial candidate',body='Synthetic evidence'),notes='Synthetic fixture')
        revised=copy.deepcopy(page);revised['content']['title']='Corrected candidate'
        steps=[('image_view',dict(path='prior/large.png'))]*3+[
            ('operation_submit',dict(request_key='page',revision=0,records=[page])),
            ('operation_submit',dict(request_key='end',revision=1,records=[dict(kind='end',count=1)])),
            ('work_run',dict(step='build',request_key='v1')),('work_run',dict(step='inspect',request_key='view1')),
            ('image_view',dict(path='outputs/work-inspect/slide-previews.zip',members=['slide-001.png'])),
            ('operation_amend',dict(request_key='correct',revision=2,expected_record_sha256=c.digest(page),record=revised)),
            ('work_run',dict(step='build',request_key='v2')),('work_run',dict(step='inspect',request_key='view2')),
            ('image_view',dict(path='outputs/work-inspect/slide-previews.zip',members=['slide-001.png'])),self.report(f)]
        script=Script(steps);save=worker_tools.Session.save
        def interrupt(session,contents,history,requests,tools,**options):
            save(session,contents,history,requests,tools,**options)
            if requests==9 and not options.get('pending'):raise InterruptedError('Synthetic restart after correction')
        with patch.object(worker_tools.Session,'save',interrupt):
            with self.assertRaises(InterruptedError):execute(f,control,script,lambda:(CONFIG,f['backend']))
        execute(f,control,script,lambda:(CONFIG,f['backend']))
        self.assertEqual(len(script.requests),len(steps))
        self.assertTrue(all(json.loads(p.read_text())['wire_bytes']<16_000_000 for p in control.glob('dispatch-context-*.json')))
        self.assertEqual(len(list((control/'work-operations').glob('*/outcome.json'))),4)
        self.assertEqual(len(list((control/'context-images').glob('*.json'))),3)
        state['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job')
        work_fixture.Tests.review_and_complete(self,f,control)

    def test_exact_script_approval_commits_before_dispatch_and_cannot_cover_changed_bytes(self):
        from orchestrator import work_authorization,host_code
        from tests.test_blender_edit import inputs as code_inputs
        native=code_inputs(self.rt,self.root)
        for item in native['inputs']:
            if item['media_type']=='text/x-python':item['media_type']='text/plain'
        self.grant['operations']=['blender.run_python'];self.grant['deliverables']={'report':'text/plain'}
        self.create(inputs=native['inputs']);self.rt.tick('job')
        refs={i['media_type']:dict(artifact=i['artifact']) for i in native['inputs']}
        params=dict(scene_sha256=refs['application/x-blender'],script_sha256=refs['text/plain'],checks_sha256=refs['application/json'],permissions='unrestricted_host')
        self.session().delegate(dict(request_id='script',tasks=[dict(id='make',objective='Execute exact approved script',work=dict(operation='blender.run_python',mode='execute',parameters=params))]))
        with patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='synthetic')),patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/blender'}):
            self.rt.tick('job');state=self.factory.sessions[self.rt.task('job','make')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
            w=worker_tools.Session(worker_tools.files(f,control),control)
            with patch.object(worker_tools,'execute_local',side_effect=AssertionError('No script can dispatch before approval')):
                with self.assertRaisesRegex(Hold,'Exact-script'):w.run(dict(step='build',request_key='exact'))
            proposal=control/'work-operations/0001/host-proposal.json';self.assertTrue(proposal.exists())
            self.assertFalse(list(control.glob('work-operations/*/intent.json')))
            # A rolled-back decision file cannot grant execution.
            with self.assertRaisesRegex(RuntimeError,'rollback'):
                with self.rt.transaction():
                    work_authorization.authorize(self.rt,f['assignment_id'],proposal,dict(source='synthetic explicit approval'))
                    raise RuntimeError('rollback')
            with self.assertRaisesRegex(Hold,'committed'):w.run(dict(step='build',request_key='exact'))
            with self.rt.transaction():work_authorization.authorize(self.rt,f['assignment_id'],proposal,dict(source='synthetic explicit approval'))
            dispatched=[]
            def approved_peer(sub,folder,*_):
                host_code.verify_frozen(sub);dispatched.append(sub)
                for output in sub['outputs']:
                    target=Path(sub['workspace'])/output['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'synthetic operation output')
                receipt=dict(outcome='completed',effect='confirmed');atomic(folder/'operation.json',receipt);return receipt
            with patch.object(worker_tools,'execute_local',side_effect=approved_peer):
                w.run(dict(step='build',request_key='exact'))
                self.assertTrue(w.run(dict(step='build',request_key='exact'))['reused'])
            self.assertEqual(len(dispatched),1)
            changed=copy.deepcopy(dispatched[0]);changed['execution']['parameters']['script_sha256']='b'*64
            with self.assertRaises(ValueError):host_code.verify_frozen(changed)

    def test_owner_capacity_stops_after_one_reply_and_remains_terminal_on_restart(self):
        from orchestrator.agent_loop import execute
        from orchestrator import executors
        self.grant['owner_turns']=1;self.create();self.rt.tick('job')
        state=self.factory.sessions[self.rt.task('job','owner')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,f['backend'])))
        proposal=dict(request_id='last',tasks=[dict(id='make',objective='Create a report',outputs=[dict(name='result',media_type='text/plain',purpose='Report')])])
        script=Script([('job_delegate',proposal)])
        with self.assertRaises(Hold):execute(f,control,script,lambda:(CONFIG,f['backend']))
        self.assertEqual(len(script.requests),1);self.assertEqual(len(self.rt.status('job')['tasks']),1)
        terminal=json.loads((control/'execution-outcome.json').read_text());self.assertEqual(terminal['code'],'owner_capacity_exhausted')
        follow=Script([])
        with self.assertRaises((Hold,ValueError)):execute(f,control,follow,lambda:(CONFIG,f['backend']))
        self.assertEqual(follow.requests,[])

    def test_completed_child_before_parent_commit_is_reused_only_with_matching_bytes(self):
        from orchestrator.agent_loop import execute
        original=worker_tools.execute_local
        f,control,_=self.text_work()
        def interrupted(*args):
            original(*args)
            raise KeyboardInterrupt('Child completed before parent committed receipt')
        first=Script([('work_run',dict(step='build',request_key='one'))])
        with patch.object(worker_tools,'execute_local',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):execute(f,control,first,lambda:(CONFIG,f['backend']))
        receipt=control/'work-operations/0001/operation-materialized.json';self.assertTrue(receipt.exists())
        follow=Script([self.report(f)])
        execute(f,control,follow,lambda:(CONFIG,f['backend']))
        self.assertEqual(len(first.requests),1);self.assertEqual(len(follow.requests),1)
        self.assertEqual(len(list(control.glob('work-operations/*/intent.json'))),1)
        from orchestrator.step_runner import execute as child
        sub=json.loads((receipt.parent/'workspace/.relay/ASSIGNMENT.json').read_text())
        output=Path(sub['workspace'])/sub['outputs'][0]['path'];output.write_text('changed saved output')
        with self.assertRaises(UncertainOperation):child(sub,receipt.parent,reconcile=True)

    def test_new_asynchronous_operation_restarts_inside_worker_without_second_submission(self):
        global INTERRUPT,DISPATCH_COUNT,POLL_COUNT
        from orchestrator.agent_loop import execute
        from orchestrator.step_runner import execute as child
        cap='fixture.async';spec=copy.deepcopy(execution.REGISTRY['text.bundle']);spec.update(kind='host',resources=['fixture-session'])
        adapter=replace(execution.adapter('text.bundle'),handler='tests.test_universal_runtime:pending_peer',reconcile='tests.test_universal_runtime:read_peer')
        with patch.dict(execution.REGISTRY,{cap:spec}),patch.dict(execution.ADAPTERS,{cap:adapter}):
            self.grant['operations'].append(cap);self.grant['deliverables']={'report':'text/plain'}
            f,control,_=self.admit(cap,[self.source('Exact asynchronous operation input')])
            INTERRUPT=True;DISPATCH_COUNT=POLL_COUNT=0
            def local(sub,folder,_parent,_remaining,reconcile=False):return child(sub,folder,reconcile=reconcile)
            first=Script([('work_run',dict(step='build',request_key='one'))])
            with patch.object(worker_tools,'execute_local',side_effect=local):
                with self.assertRaises(UncertainOperation):execute(f,control,first,lambda:(CONFIG,f['backend']))
                before=(control/'tool-01-00.json').read_bytes();INTERRUPT=False
                follow=Script([self.report(f)]);execute(f,control,follow,lambda:(CONFIG,f['backend']))
            self.assertEqual(DISPATCH_COUNT,1);self.assertEqual(POLL_COUNT,2)
            self.assertEqual((control/'tool-01-00.json').read_bytes(),before)
            self.assertTrue((control/'tool-01-00.reconciled.json').exists())
            self.assertEqual(len(follow.requests),1);worker_tools.verify_delivery(f,control)

    def test_explicit_other_provider_worker_runs_same_registered_operation_lifecycle(self):
        from orchestrator import executors,worker_capabilities
        from orchestrator.agent_loop import execute
        for provider in ('openai','qwen','deepseek','openrouter'):
            # Separate fresh durable jobs; owner remains Gemini, worker is an
            # explicitly authorized backend, never an automatic fallback.
            fixture=WorkTests();fixture.setUp()
            try:
                fixture.grant['workers']=[worker_capabilities.entry(dict(type=provider+'-agent',model='fixture'))]
                f,control,_=fixture.text_work();self.assertEqual(f['backend']['type'],provider+'-agent')
                calls=[];steps=iter([('work_run',dict(step='build',request_key='one')),('finish',json.loads(fixture.report(f)[1]['report_json']))])
                class Peer:
                    def request(self,endpoint,payload):
                        calls.append(copy.deepcopy(payload));name,args=next(steps);ident='call'+str(len(calls))
                        if provider=='openai':return dict(status='completed',output=[dict(type='function_call',id=ident,call_id=ident,name=name,arguments=json.dumps(args))])
                        return dict(choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content=None,tool_calls=[dict(id=ident,type='function',function=dict(name=name,arguments=json.dumps(args)))]))])
                execute(f,control,Peer(),lambda:(CONFIG,f['backend']))
                self.assertEqual(len(calls),2);worker_tools.verify_delivery(f,control)
                self.assertEqual(json.loads((control/'work-operations/0001/outcome.json').read_text())['status'],'completed')
            finally:fixture.doCleanups()

    def test_external_model_operation_uses_its_own_provider_and_shared_allowance(self):
        from orchestrator.agent_loop import execute
        from orchestrator import executors
        from orchestrator.step_runner import execute as child
        self.grant['operations']=['gemini.text'];self.grant['deliverables']={'report':'text/plain'}
        self.grant['operation_backends']={'gemini.text':dict(type='gemini-agent',model='native-fixture')}
        ref=self.source('Exact native provider input');self.create(inputs=[ref]);self.rt.tick('job')
        self.session().delegate(dict(request_id='api',tasks=[dict(id='make',objective='Execute granted provider operation',inputs=[dict(artifact=ref['artifact'])],work=dict(operation='gemini.text',mode='execute',parameters=dict(max_output_tokens=128)))]))
        self.rt.tick('job');state=self.factory.sessions[self.rt.task('job','make')['latest']];f=state['frozen'];control=Path(state['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,f['backend'])))
        calls=[]
        class Peer:
            def request(self,path,payload,**kwargs):
                calls.append((path,copy.deepcopy(payload)))
                return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text='Synthetic operation result')]))],usageMetadata=dict(totalTokenCount=12))
        def local(sub,folder,*_):return child(sub,folder,client_factory=lambda _:Peer(),config_reader=lambda:CONFIG)
        with patch.object(Adapter,'check_available'),patch.object(worker_tools,'execute_local',side_effect=local):
            execute(f,control,Script([('work_run',dict(step='build',request_key='one')),self.report(f)]),lambda:(CONFIG,f['backend']))
        self.assertEqual(len(calls),1);self.assertIn('native-fixture',calls[0][0])
        folder=control/'work-operations/0001';self.assertTrue((folder/'request.json').exists());self.assertTrue((folder/'response.json').exists())
        self.assertEqual(json.loads((folder/'outcome.json').read_text())['external_request_reservation'],1)
        self.assertEqual(worker_tools.Session(worker_tools.files(f,control),control).reserved_requests(),1)


class CodexImageLifecycleTests(unittest.TestCase):
    from tests.test_codex_executor import Tests as Fixture
    setUp=Fixture.setUp
    invoke=Fixture.invoke
    report=Fixture.report

    def test_large_image_repeated_views_build_correction_and_independent_review(self):
        import random
        from PIL import Image
        from orchestrator import job_owner,worker_capabilities
        from orchestrator.document_authoring import PPTX
        from tests.test_codex_executor import BACKEND
        from orchestrator.owner_compilation import label
        path=(self.root/'large.png').resolve();Image.frombytes('RGB',(1600,1050),random.Random(7).randbytes(1600*1050*3)).save(path)
        ref=dict(artifact=self.rt.register(path,'Synthetic transport pixels'),path='large.png',purpose='Synthetic reference',authority='Synthetic; no visual quality claim',media_type='image/png',visual_reference=True)
        self.grant.update(operations=['pptx.create','pptx.render'],deliverables={'deck':PPTX,'pdf':'application/pdf'})
        self.grant['task_limits']['output_bytes']=20000000
        self.grant['workers'].append(worker_capabilities.entry({**BACKEND,'type':'codex-code','runtime':'a'*64}))
        job_owner.create(self.rt,'job','Create and independently review a deck using the reference.',BACKEND,[ref],self.grant);self.rt.tick('job')
        self.invoke('owner',[('job_delegate',dict(request_id='deck',tasks=[dict(id='deck',objective='Inspect and correct a deck',inputs=[dict(artifact=ref['artifact'])],work=dict(operation='pptx.create',mode='create',content_parameters=dict(max_records=1)))]))])
        self.rt.tick('job');f=self.factory.sessions[self.rt.task('job','deck')['latest']]['frozen'];image_path=next(i['path'] for i in f['inputs'] if i['media_type']=='image/png')
        page=dict(kind='page',slot=1,layout='text',content=dict(title='Initial',body='Synthetic source'),notes='Fixture')
        corrected=copy.deepcopy(page);corrected['content']['title']='Corrected'
        steps=[('image_view',dict(path=image_path,members=[]))]*3+[
            ('operation_submit',dict(request_key='page',revision=0,records=[page])),('operation_submit',dict(request_key='end',revision=1,records=[dict(kind='end',count=1)])),
            ('work_run',dict(step='build',request_key='one')),('work_run',dict(step='inspect',request_key='inspect1')),('image_view',dict(path='outputs/work-inspect/slide-previews.zip',members=['slide-001.png'])),
            ('operation_amend',dict(request_key='correct',revision=2,expected_record_sha256=c.digest(page),record=corrected)),
            ('work_run',dict(step='build',request_key='two')),('work_run',dict(step='inspect',request_key='inspect2')),('image_view',dict(path='outputs/work-inspect/slide-previews.zip',members=['slide-001.png'])),('finish',self.report('deck'))]
        _,control,_=self.invoke('deck',steps)
        frames=[json.loads(line) for line in (control/'codex-sent.jsonl').read_text().splitlines()]
        self.assertEqual(sum(frame.get('method')=='thread/start' for frame in frames),1)
        measurements=[json.loads(line) for line in (control/'codex-wire-measurements.jsonl').read_text().splitlines()]
        self.assertTrue(all(v['bytes']<16_000_000 for v in measurements))
        sent_hashes={v['sha256'] for v in measurements}
        for p in control.glob('dispatch-context-*.json'):
            prepared=json.loads(p.read_text())
            if prepared['measurement']=='prepared_request':self.assertIn(prepared['wire_sha256'],sent_hashes)
        for p in control.glob('api-*.request.json'):
            payload=json.loads(p.read_text())['payload'];images=[part for m in payload['messages'] if isinstance(m.get('content'),list) for part in m['content'] if part.get('type')=='image_url']
            self.assertEqual(len(images),len({i['image_url']['url'] for i in images}))
        self.rt.tick('job');review=label('deck','review');review_f=self.factory.sessions[self.rt.task('job',review)['latest']]['frozen']
        preview=next(i['path'] for i in review_f['inputs'] if i['path'].endswith('slide-previews.zip'))
        reference=next(i['path'] for i in review_f['inputs'] if i.get('visual_reference'))
        review_report=self.report(review,'accept')
        for check in review_report['checks'].values():
            if isinstance(check['evidence'],dict):check['evidence']['reference_fit']['inspected'].append(dict(path=reference,location='Complete synthetic reference pixels'))
        with patch('task_relay.code_runtime.available',return_value={'tools':{}}):
            self.invoke(review,[('image_view',dict(path=reference,members=[])),('image_view',dict(path=preview,members=['slide-001.png'])),('finish',review_report)])
        self.rt.tick('job')
        outputs={key:self.rt.output('job','deck',path)['id'] for key,path in dict(deck='outputs/work-build/result.pptx',pdf='outputs/work-inspect/preview.pdf').items()}
        self.invoke('owner',[('job_complete',dict(deliverables_json=json.dumps(outputs),summary='Reviewed exact corrected fixture'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed')
