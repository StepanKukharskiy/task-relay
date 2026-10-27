"""Owner role/context boundaries and positive dispatch after bounded observation.

Real worker loop and controller; scripted models, no paid provider execution.
"""
import copy,json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from orchestrator import contracts as c,executors,working_context as ctx,job_owner
from tests import test_job_owner_loop as fixture

class RuntimeTests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    create=fixture.Tests.create
    invoke=fixture.Tests.invoke
    batch=fixture.Tests.batch

    def test_owner_gets_exact_request_and_references_workers_get_full_evidence(self):
        from tests.test_browser_screenshots import png
        source=self.root/'research.txt';source.write_text('PRIVATE WORKER DETAIL '*5000)
        image=self.root/'reference.png';image.write_bytes(png())
        refs=[]
        for path,media in [(source,'text/plain'),(image,'image/png')]:
            refs.append(dict(artifact=self.rt.register(path,'Exact evidence'),path=path.name,purpose='Evidence',authority='Unaccepted source',media_type=media,**({'visual_reference':True} if media=='image/png' else {})))
        self.grant['operations']=['pptx.create']
        self.create(request='Preserve this exact request: complete the deliverable.',inputs=refs);self.rt.tick('job')
        result,script=self.invoke([('job_catalog',dict(operations=['pptx.create'])),('job_delegate',dict(request_id='work',batch_json=c.encoded(self.batch(inputs=refs))))])
        first=script.requests[0]['contents'][0]
        self.assertEqual(len(first['parts']),1)
        initial=json.loads(first['parts'][0]['text'])
        self.assertEqual(initial['request'],'Preserve this exact request: complete the deliverable.')
        self.assertNotIn('PRIVATE WORKER DETAIL',c.encoded(script.requests))
        self.assertNotIn('report_contract',initial);self.assertNotIn('owner_grant',initial)
        self.assertNotIn('objective',initial);self.assertNotIn('source_pack',initial)
        self.assertEqual([i['artifact'] for i in initial['inputs']],[i['artifact'] for i in refs])
        catalog=script.requests[1]['contents'][-1]['parts'][0]['functionResponse']['response']
        self.assertNotIn('authoring',catalog['operations']['pptx.create'])
        self.assertIn('handoffs',catalog['operations']['pptx.create']['admission'])
        self.assertIn('parameters',catalog['operations']['pptx.create'])
        self.rt.tick('job');aid=self.rt.task('job','v1')['latest'];frozen=self.factory.sessions[aid]['frozen']
        self.assertEqual((Path(frozen['workspace'])/'research.txt').read_bytes(),source.read_bytes())
        self.assertEqual((Path(frozen['workspace'])/'reference.png').read_bytes(),image.read_bytes())
        self.assertTrue(next(i for i in frozen['inputs'] if i['path']=='reference.png')['visual_reference'])
        self.assertEqual(result['outcome'],'yielded')

    def test_read_only_exhaustion_cannot_wake_again_after_restart(self):
        from orchestrator.runtime import Runtime
        self.create();self.rt.tick('job');aid=self.rt.task('job','owner')['latest']
        with patch.object(executors,'request_limit',return_value=2):
            with self.assertRaisesRegex(ValueError,'without committing delegated work'):
                self.invoke([('job_catalog',{}),('job_catalog',{})])
        control=Path(self.factory.sessions[aid]['session']['control'])
        self.assertEqual(json.loads((control/'owner-no-progress.json').read_text())['requests'],2)
        self.assertFalse((control/'owner-session.json').exists())
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,reason='Owner observation exhausted',external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');count=len(self.factory.calls)
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        for _ in range(3):self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'blocked')
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertEqual(len(self.factory.calls),count)
        self.assertEqual(job_owner.original(self.rt,'job')['job_owner']['owner_turns'],6)

    def test_observations_then_delegation_use_same_invocation(self):
        self.create();self.rt.tick('job')
        with patch.object(executors,'request_limit',return_value=3):
            result,script=self.invoke([('job_catalog',{}),('job_catalog',{}),('job_delegate',dict(request_id='work',batch_json=c.encoded(self.batch())))])
        self.assertEqual(result['outcome'],'yielded');self.assertEqual(len(script.requests),3)
        self.rt.tick('job');self.assertEqual(self.rt.task('job','v1')['attempts'],1)
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)

class ContextTests(unittest.TestCase):
    def group(self,provider,name,args,result,n):
        if provider=='gemini':return [dict(role='model',parts=[dict(functionCall=dict(name=name,args=args),thoughtSignature='sig'+str(n))]),dict(role='user',parts=[dict(functionResponse=dict(name=name,response=result))])]
        if provider=='openai':return [dict(type='reasoning',encrypted_content='opaque'+str(n)),dict(type='function_call',call_id=str(n),name=name,arguments=json.dumps(args)),dict(type='function_call_output',call_id=str(n),output=json.dumps(result))]
        return [dict(role='assistant',tool_calls=[dict(id=str(n),type='function',function=dict(name=name,arguments=json.dumps(args)))]),dict(role='tool',tool_call_id=str(n),content=json.dumps(result))]

    def test_selected_schema_stays_usable_after_reads_without_archive_reconstruction(self):
        for provider in ('gemini','openai','openrouter'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as root:
                view=ctx.WorkingView(Path(root))
                initial=dict(role='user',**({'parts':[dict(text='Exact coordination brief')]} if provider=='gemini' else {'content':'Exact coordination brief'}))
                messages=[initial]+self.group(provider,'job_catalog',dict(operations=['fixture.render']),dict(schema='REQUIRED FIELD DEFINITION'),0)
                for n in range(1,20):messages+=self.group(provider,'job_read',dict(artifact='source',offset=n*2000,limit=2000),dict(text='literal evidence '*130),n)
                before=copy.deepcopy(messages);projected=view.project(messages,provider,20000,version=2)
                self.assertEqual(messages,before);self.assertLessEqual(ctx.size(projected),20000)
                self.assertIn('REQUIRED FIELD DEFINITION',json.dumps(projected))
                last=self.group(provider,'job_read',dict(artifact='source',offset=38000,limit=2000),dict(text='literal evidence '*130),19)
                self.assertEqual(projected[-len(last):],last)
                # Stable individual records survive restart and remain exact.
                oldest=view.save(messages[3:5] if provider!='openai' else messages[4:7])
                part=ctx.WorkingView(Path(root)).read(dict(context=oldest,offset=0))
                self.assertTrue(part['text']);self.assertEqual(part['context'],oldest)
                for chunk in ctx.groups(projected[1:]):
                    calls,results=ctx.exchanges(chunk)
                    self.assertEqual(len(calls),len(results))

    def test_exact_repeated_reads_collapse_changed_evidence_and_effects_do_not(self):
        with tempfile.TemporaryDirectory() as root:
            view=ctx.WorkingView(Path(root));messages=[dict(role='user',parts=[dict(text='Exact request')])]
            for n in range(6):messages+=self.group('gemini','job_read',dict(artifact='a',offset=0),dict(text='same',sha256='one'),n)
            messages+=self.group('gemini','job_read',dict(artifact='a',offset=0),dict(text='changed',sha256='two'),6)
            for n in range(7,9):messages+=self.group('gemini','job_delegate',dict(request_id='effect'),dict(queued=True),n)
            result=view.project(messages,'gemini',20000,version=2)
            calls=[call for g in ctx.groups(result[1:]) for call in ctx.exchanges(g)[0]]
            self.assertEqual(sum(name=='job_read' for name,_ in calls),2)
            self.assertEqual(sum(name=='job_delegate' for name,_ in calls),2)
            self.assertIn('changed',json.dumps(result))
            with self.assertRaisesRegex(ValueError,'capacity'):view.project(messages,'gemini',10,version=2)

    def test_semantic_checkpoint_restore_does_not_requote_observations(self):
        for provider in ('gemini','openai','openrouter','codex'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as root:
                view=ctx.WorkingView(Path(root),semantic=True)
                initial=dict(role='user',**({'parts':[dict(text='Exact request')]} if provider=='gemini' else {'content':'Exact request'}))
                result=dict(schema={'quoted':'"\\'*4000},evidence='EXACT SOURCE',sha256='unchanged')
                original=self.group(provider,'job_catalog',{},result,0)
                # A real checkpoint contains previously projected user messages.
                retained=view.retained(original,provider)
                tail=self.group(provider,'job_delegate',dict(request_id='once'),dict(queued=['research']),1)
                messages=[initial]+retained+tail
                original_bytes=c.encoded(messages)
                previous=None
                for _ in range(12):
                    projected=view.project(messages,provider,version=2)
                    self.assertLessEqual(ctx.size(projected),ctx.MAX_TEXT_BYTES)
                    self.assertIn('EXACT SOURCE',c.encoded(projected))
                    self.assertEqual(projected[-len(tail):],tail)
                    if previous is not None:self.assertEqual(projected,previous)
                    previous=copy.deepcopy(projected)
                    # Serialize/restore just as a durable owner invocation does.
                    messages=json.loads(c.encoded(projected))
                    view=ctx.WorkingView(Path(root),semantic=True)
                self.assertEqual(c.encoded([initial]+retained+tail),original_bytes)
                self.assertEqual(view.retained(retained,provider),retained)

    def test_retention_measures_escaped_wire_and_archives_oversize_history(self):
        for provider in ('gemini','openai','openrouter','codex'):
            with self.subTest(provider=provider),tempfile.TemporaryDirectory() as root:
                view=ctx.WorkingView(Path(root),semantic=True)
                initial=dict(role='user',**({'parts':[dict(text='Exact request')]} if provider=='gemini' else {'content':'Exact request'}))
                older=self.group(provider,'job_read',{},dict(text='"\\'*9000),0)
                tail=self.group(provider,'job_delegate',dict(request_id='once'),dict(queued=True),1)
                raw_size=ctx.size(older);wire_size=ctx.size(view.retained(older,provider))
                self.assertGreater(wire_size,raw_size)
                ceiling=raw_size+ctx.size(tail)+ctx.size(initial)+7000
                self.assertGreater(wire_size,ceiling)
                before=copy.deepcopy(older)
                projected=view.project([initial]+older+tail,provider,ceiling,version=2)
                self.assertLessEqual(ctx.size(projected),ceiling)
                self.assertEqual(projected[-len(tail):],tail)
                self.assertEqual(older,before)
                self.assertEqual(json.loads((view.folder/(view.save(older)+'.json')).read_text()),older)
                paged=view.project([initial]+older,provider,ctx.size(older)-1,version=2)
                self.assertLessEqual(ctx.size(paged),ctx.size(older)-1)
                self.assertIn('relay.tool-result-pages.v1',c.encoded(paged))
                with self.assertRaisesRegex(ValueError,'Latest tool exchange exceeds'):
                    view.project([initial]+older,provider,ctx.size(older)-1,version=2,history_available=False)

class ComposedTests(unittest.TestCase):
    """Actual owner→fragments→PPTX/revision after context compaction."""
    from tests.test_document_authoring import Tests as DocumentFixture
    setUp=fixture.Tests.setUp
    create=fixture.Tests.create
    content=DocumentFixture.content
    renderer=DocumentFixture.renderer

    def prepare(self):
        from orchestrator.document_authoring import PPTX
        self.grant['operations']=['pptx.create','pptx.render'];self.grant['deliverables']={'deck':PPTX}
        source=self.root/'source.txt';source.write_text('Exact synthetic reference interval. '*6000)
        self.source_id=self.rt.register(source,'Synthetic long evidence')
        ref=dict(artifact=self.source_id,path='source.txt',purpose='Evidence',authority='Synthetic source',media_type='text/plain')
        self.create(inputs=[ref]);self.rt.tick('job')

    def invoke(self,steps):
        reads=[('job_catalog',dict(operations=['pptx.create','pptx.render']))]
        reads += [('job_read',dict(artifact=self.source_id,offset=n*24000,limit=24000)) for n in range(7)]
        result,script=fixture.Tests.invoke(self,reads+steps)
        last=script.requests[-1];text=c.encoded(last['contents'])
        self.assertIn('Historical exchanges are preserved separately',text)
        retained=[p['functionResponse'] for m in last['contents'] for p in m.get('parts',[]) if 'functionResponse' in p]
        self.assertTrue(any(r['name']=='job_catalog' and 'pptx.create' in r['response']['operations'] for r in retained))
        self.assertLessEqual(ctx.size(last['contents']),ctx.MAX_TEXT_BYTES)
        self.assertEqual(len(script.requests),9)
        return result,script

    def test_compacted_owner_reaches_native_deck_and_preserves_original_on_revision(self):
        self.DocumentFixture.test_owner_to_fragment_store_to_real_native_pptx_and_revision(self)
