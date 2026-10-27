"""Persistent owner, actual provider tool loop, scheduler and artifact handoff.

Only model replies and worker content are scripted. No live provider or service.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import contracts as c,executors,job_owner,worker_capabilities
from orchestrator.gemini_worker import execute
from orchestrator.runtime import Runtime
from orchestrator.workers import atomic
from tests.test_orchestrator import FakeFactory
from tests.test_operation_session import Script,CONFIG

BACKEND=dict(type='gemini-agent',model='fixture')


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'runtime';self.factory=FakeFactory();self.rt=Runtime(self.root,self.factory)
        self.addCleanup(lambda:self.rt.close())
        self.grant=dict(delegation_version=1,workers=[worker_capabilities.entry(BACKEND)],operations=[],deliverables={'report':'text/plain'},
            max_tasks=10,task_limits=dict(seconds=300,tool_calls=12,provider_requests=12,response_tokens=4096,output_bytes=200000),task_attempts=2,owner_turns=6)

    def create(self,run='job',request='Write a sourced text report.',inputs=None):
        return job_owner.create(self.rt,run,request,BACKEND,inputs or [],self.grant)

    def batch(self,prefix='v1',inputs=None):
        author=dict(id=prefix,objective='Complete the report',instruction='Write substantive verified content',inputs=inputs or [],
            outputs=[dict(path='report.txt',purpose='Final report',media_type='text/plain')],dependencies=[],worker=dict(requires=['files.text']),criteria=['Meets the complete request'])
        review=dict(id=prefix+'_review',objective='Review the complete final artifact',instruction='Inspect sources and exact report; reject substantive defects',
            review_of=prefix,inputs=[dict(from_task=prefix,output='report.txt',path='candidate.txt',purpose='Final candidate',authority='Unaccepted content',media_type='text/plain')],
            outputs=[dict(path='review.md',purpose='Independent final review',media_type='text/markdown')],dependencies=[prefix],worker=dict(requires=['files.text']),criteria=author['criteria'])
        return [author,review]

    def invoke(self,steps,run='job'):
        aid=self.rt.task(run,'owner')['latest'];s=self.factory.sessions[aid];control=Path(s['session']['control']);control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        script=Script(steps)
        result=execute(s['frozen'],control,client=script,config_reader=lambda:(CONFIG,BACKEND))
        s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[],api_requests=len(script.requests))
        return result,script

    def delegate(self,batch,run='job',key='batch-1'):
        return self.invoke([('job_delegate',dict(request_id=key,batch_json=c.encoded(batch)))],run)

    def finish_children(self,run='job',prefix='v1'):
        self.rt.tick(run)
        self.factory.finish(self.rt.task(run,prefix)['latest']);self.rt.tick(run)
        self.factory.finish(self.rt.task(run,prefix+'_review')['latest'],decision='accept');self.rt.tick(run)

    def test_owner_discovers_registered_input_content_without_ungranted_adapter_probes(self):
        from orchestrator import execution
        self.grant['operations']=['images.fetch']
        self.create();self.rt.tick('job')
        result,script=self.invoke([('job_catalog',dict(operations=['images.fetch'],records=True)),('job_delegate',dict(request_id='finish-fixture',batch_json=c.encoded(self.batch('next'))))])
        reply=script.requests[1]['contents'][-1]['parts'][0]['functionResponse']['response']
        self.assertEqual(set(reply['operations']),{'images.fetch'})
        self.assertNotIn('authoring',reply['operations']['images.fetch'])
        self.assertEqual(reply['operations']['images.fetch']['admission']['handoffs']['ports'][0]['kind'],'evidence')
        self.assertIn('collection.subjects',c.encoded(reply['records']))
        self.assertIn('collection.options',c.encoded(reply['records']))
        # Catalog selection must not probe or disclose unrelated connectors.
        with patch.object(execution,'adapter',side_effect=AssertionError('Unrequested adapter probe')):
            self.assertEqual(execution.catalog([]),[])
            with self.assertRaisesRegex(ValueError,'Unknown operation'):execution.catalog(['unregistered.tool'])

    def test_owner_delegates_registered_fragments_and_code_supplies_projection(self):
        from orchestrator import operation_records,operation_contracts
        for field in ('botanical_name','material','part_number'):
            run='typed_'+field;source=self.root/(field+'.txt');source.write_text('One observed subject')
            aid=self.rt.register(source,'Exact subject evidence')
            ref=dict(artifact=aid,path='source.txt',purpose='Source',authority='Observed fixture',media_type='text/plain')
            self.create(run,inputs=[ref]);self.rt.tick(run);batch=self.batch()
            producer,review=batch;producer['inputs']=[ref]
            producer['outputs']=[dict(path=p,purpose='Code-owned projection',media_type=m) for p,m in [('subjects.json','application/json'),('subjects.md','text/markdown')]]
            producer['records']=dict(family=dict(id='collection.subjects',version=1),inputs=dict(source_path={'source':aid}),parameters=dict(max_records=1,fields=[field]))
            review['inputs']=[ref,dict(from_task='v1',output='subjects.json',path='subjects.json',purpose='Candidate',authority='Unaccepted',media_type='application/json')]
            _,admission=self.invoke([('job_delegate',dict(request_id='typed',batch_json=c.encoded(batch))),('job_delegate',dict(request_id='finish-fixture',batch_json=c.encoded(self.batch('next'))))],run)
            self.assertEqual(len(admission.requests),1,c.encoded(admission.requests[-1]['contents'][-1]))
            self.rt.tick(run)
            session=self.factory.sessions[self.rt.task(run,'v1')['latest']];frozen=session['frozen']
            self.assertEqual(frozen['operation_contract']['parameters']['source_path'],'source.txt')
            control=Path(session['session']['control']);control.mkdir(parents=True,exist_ok=True)
            atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
            item=dict(kind='item',slot=1,label='Observed subject',attributes={field:None},quote='One observed subject',bbox=None,notes='Unknown attribute')
            checks={'c'+str(i):dict(passed=True,evidence='Exact source and sealed projection') for i in range(1,len(frozen['criteria'])+1)}
            script=Script([('operation_submit',dict(request_key='item',revision=0,records=[item])),
                ('operation_submit',dict(request_key='seal',revision=1,records=[dict(kind='end',count=1,notes='All source subjects covered')])),
                ('finish',dict(report_json=c.encoded(dict(summary='Projected exact subjects',decision='delivered',instruction='',findings=[],checks=checks))))])
            result=execute(frozen,control,script,lambda:(CONFIG,BACKEND))
            self.assertEqual(result['decision'],'delivered')
            raw=(Path(frozen['workspace'])/'subjects.json').read_bytes()
            operation_contracts.validate_document(raw,dict(id='collection.subjects',version=1))
            self.assertEqual(json.loads(raw)['items'][0]['attributes'],{field:None})
            declared={t['name'] for t in script.requests[0]['tools'][0]['functionDeclarations']}
            self.assertIn('operation_submit',declared)

    def test_owner_catalog_carries_qualified_runtime_without_expanding_grant(self):
        code=dict(type='gemini-code',model='fixture',runtime='a'*64)
        self.grant['workers'].append(worker_capabilities.entry(code));self.create();self.rt.tick('job')
        from task_relay import code_runtime
        with patch.object(code_runtime,'available',return_value={'tools':{'pptx':{'available':True,'checked':'save/reopen'}}}) as available:
            _,script=self.invoke([('job_catalog',{}),('job_delegate',dict(request_id='finish-fixture',batch_json=c.encoded(self.batch('next'))))])
        workers=script.requests[1]['contents'][-1]['parts'][0]['functionResponse']['response']['workers']
        self.assertEqual(workers[1]['runtime_tools']['pptx']['checked'],'save/reopen')
        available.assert_called_once_with('a'*64)
        self.assertEqual(workers[1]['backend'],code)
        self.assertNotIn('runtime_tools',job_owner.original(self.rt,'job')['job_owner']['workers'][1])

    def test_owner_collection_binds_existing_generic_contracts_for_each_field_configuration(self):
        from tests.test_universal_interfaces import Harness,CONFIGURATIONS,Tests as Compiler
        for name,config in CONFIGURATIONS.items():
            with self.subTest(configuration=name),tempfile.TemporaryDirectory() as directory:
                harness=Harness(directory,config);self.addCleanup(harness.db.close)
                plan=Compiler().proposal(config,count=1);refs={}
                for item in harness.inputs:
                    ident=self.rt.register((Path(directory)/item['path']).resolve(),'Exact generic source')
                    key='subjects' if item['path']=='subjects.json' else 'pages'
                    refs[key]=ident
                for task in plan['tasks']:
                    for key in ('tools','limits','max_attempts'):task.pop(key)
                    for item in task['inputs']:
                        if 'artifact' in item:item['artifact']=refs[item['artifact']]
                for binding in plan['tasks'][0]['records']['inputs'].values():binding['source']=refs[binding['source']]
                inputs=copy.deepcopy(plan['tasks'][0]['inputs'])
                self.create(name,inputs=inputs);self.rt.tick(name)
                _,script=self.invoke([('job_delegate',dict(request_id='collection',batch_json=c.encoded(plan['tasks']))),('job_delegate',dict(request_id='finish-fixture',batch_json=c.encoded(self.batch('next'))))],name)
                self.assertEqual(len(script.requests),1,c.encoded(script.requests[-1]['contents'][-1]))
                producer=self.rt.spec(self.rt.task(name,'collect'));review=self.rt.spec(self.rt.task(name,'review'))
                self.assertEqual(producer['operation_contract']['id'],'collection.options')
                self.assertEqual(review['operation_contract']['id'],'collection.review')
                self.assertEqual(producer['operation_contract']['parameters']['field_definitions'],config['fields'])
                self.assertEqual(producer['limits'],self.grant['task_limits'])

    def test_explicit_generation_policy_is_frozen_on_owner_and_delegated_workers(self):
        self.grant['generation_recovery']=dict(version=1,max_retries=2)
        self.create();self.rt.tick('job')
        first=self.factory.sessions[self.rt.task('job','owner')['latest']]['frozen']
        self.assertEqual(first['generation_recovery'],self.grant['generation_recovery'])
        self.delegate(self.batch());self.rt.tick('job')
        delegated=self.factory.sessions[self.rt.task('job','v1')['latest']]['frozen']
        self.assertEqual(delegated['generation_recovery'],first['generation_recovery'])
        self.assertEqual(delegated['limits']['provider_requests'],12)

    def test_full_owner_delegation_restart_completion_and_revision(self):
        self.create();self.rt.tick('job');first=self.rt.task('job','owner')['latest']
        result,_=self.delegate(self.batch());self.assertEqual(result['outcome'],'yielded')
        self.rt.tick('job');self.assertEqual(self.rt.task('job','owner')['status'],'waiting')
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.finish_children();second=self.rt.task('job','owner')['latest'];self.assertNotEqual(first,second)
        artifact=self.rt.output('job','v1','report.txt')
        result,script=self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':artifact['id']}),summary='Delivered the independently reviewed report'))])
        self.assertIn('job_delegate',c.encoded(script.requests[0]['contents']))
        self.assertEqual(self.rt.tick('job')['status'],'completed')
        original=Path(artifact['blob']).read_bytes()
        source=dict(artifact=artifact['id'],path='baseline.txt',purpose='Exact prior report',authority='Baseline for the requested revision',media_type='text/plain')
        job_owner.revise(self.rt,'job','revision','Revise the same report; retain all unaffected content.');self.rt.tick('revision')
        self.delegate(self.batch('v2',[source]),'revision');self.finish_children('revision','v2')
        revised=self.rt.output('revision','v2','report.txt')
        self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':revised['id']}),summary='Reviewed revision delivered'))],'revision')
        self.assertEqual(self.rt.tick('revision')['status'],'completed')
        self.assertEqual(Path(artifact['blob']).read_bytes(),original)
        frozen=self.factory.sessions[self.rt.task('revision','v2')['latest']]['frozen']
        self.assertEqual(frozen['inputs'][0]['sha256'],artifact['sha256'])

    def test_failed_delegate_returns_to_owner_without_a_user_recovery_gate(self):
        self.create();self.rt.tick('job');self.delegate(self.batch());self.rt.tick('job')
        failed=self.rt.task('job','v1')['latest'];self.factory.sessions[failed]['status']=dict(status='finished',exit_code=1,reason='Confirmed bad candidate')
        self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertEqual(self.rt.status('job')['status'],'active')
        self.delegate(self.batch('corrected'),key='correction');self.finish_children(prefix='corrected')
        artifact=self.rt.output('job','corrected','report.txt')
        self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':artifact['id']}),summary='Corrected artifact delivered'))])
        self.assertEqual(self.rt.tick('job')['status'],'completed')
        self.assertEqual(self.rt.task('job','v1')['latest'],failed)
        self.assertEqual(self.rt.task('job','v1')['status'],'blocked')

    def test_uncertain_delegate_never_wakes_owner_or_replays(self):
        self.create();self.rt.tick('job');self.delegate(self.batch());self.rt.tick('job')
        aid=self.rt.task('job','v1')['latest'];self.factory.sessions[aid]['status']=dict(status='uncertain',reason='No response')
        self.rt.tick('job');self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],1)
        self.assertEqual(self.rt.status('job')['status'],'uncertain')
        self.assertEqual(self.factory.calls.count(aid),1)

    def test_review_rejection_returns_findings_to_owner_without_legacy_revision(self):
        self.create();self.rt.tick('job');self.delegate(self.batch());self.rt.tick('job')
        first=self.rt.task('job','v1')['latest'];self.factory.finish(first);self.rt.tick('job')
        reviewer=self.rt.task('job','v1_review')['latest'];self.factory.finish(reviewer,decision='revise');self.rt.tick('job')
        self.assertEqual(self.rt.task('job','v1')['status'],'blocked')
        self.assertEqual(self.rt.task('job','v1')['attempts'],1)
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)
        self.assertTrue(self.rt.output('job','v1_review','review.md')['id'])
        rejected=self.rt.output('job','v1','report.txt')
        self.delegate(self.batch('corrected',[dict(artifact=rejected['id'],path='baseline.txt',purpose='Rejected candidate',authority='Unaccepted baseline',media_type='text/plain')]),key='correction')
        self.rt.tick('job');fixed=self.rt.task('job','corrected')['latest'];self.factory.finish(fixed)
        (Path(self.factory.sessions[fixed]['frozen']['workspace'])/'report.txt').write_text('Substantive corrected report, preserving the rejected baseline separately.')
        self.rt.tick('job');judge=self.rt.task('job','corrected_review')['latest'];self.factory.finish(judge,decision='accept')
        frozen=self.factory.sessions[judge]['frozen'];path=Path(frozen['workspace'])/'.relay/result.json';report=json.loads(path.read_text())
        followup=frozen['review_followup']
        report['checks'][-1]['evidence']=c.encoded({key:dict(verdict='resolved',reason='Independently inspected the substantive correction',inspected=[dict(path=followup['candidates'][0],location='Whole corrected report')]) for key in followup['findings']})
        path.write_text(c.encoded(report));self.rt.tick('job');artifact=self.rt.output('job','corrected','report.txt')
        self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':artifact['id']}),summary='Corrected and reviewed'))])
        self.assertEqual(self.rt.tick('job')['status'],'completed')
        self.assertEqual(self.rt.task('job','v1')['latest'],first)

    def test_owner_cannot_complete_without_review_and_cannot_expand_its_grant(self):
        self.create();self.rt.tick('job')
        aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        from orchestrator.job_owner import files,Session
        owner=Session(s['frozen'],Path(s['session']['control']),files(s['frozen'],Path(s['session']['control'])))
        self.addCleanup(owner.rt.close)
        for mutation in ('job_owner','backend','user_gate','revision'):
            batch=self.batch();batch[0][mutation]={}
            with self.subTest(field=mutation),self.assertRaisesRegex(ValueError,'may not supply'):
                owner.delegate(dict(request_id='bad-'+mutation,batch_json=c.encoded(batch)))
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        with self.assertRaisesRegex(ValueError,'Every requested deliverable'):owner.complete(dict(deliverables_json='{}',summary='No files'))

    def test_checkpoint_tamper_stops_before_another_model_call(self):
        self.create();self.rt.tick('job');self.delegate(self.batch());self.finish_children()
        frozen=self.factory.sessions[self.rt.task('job','owner')['latest']]['frozen']
        Path(frozen['owner_checkpoint']['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'checkpoint changed'):self.invoke([])

    def test_committed_delegation_survives_crash_before_normal_checkpoint(self):
        self.create();self.rt.tick('job')
        with patch.object(job_owner.Session,'checkpoint',side_effect=OSError('Injected process stop')):
            with self.assertRaisesRegex(OSError,'Injected'):self.delegate(self.batch())
        first=self.rt.task('job','owner')['latest']
        self.factory.sessions[first]['status']=dict(status='finished',exit_code=1,reason='Worker stopped',external_outcome='no_pending_response')
        self.rt.tick('job');self.assertEqual(self.rt.task('job','owner')['status'],'waiting')
        self.finish_children()
        artifact=self.rt.output('job','v1','report.txt')
        _,script=self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':artifact['id']}),summary='Reviewed'))])
        self.assertIn('Committed delegation',c.encoded(script.requests[0]['contents']))
        self.assertEqual(self.rt.tick('job')['status'],'completed')
        self.assertEqual(len(self.rt.status('job')['tasks']),3)
        self.assertEqual(self.factory.calls.count(first),1)

    def test_unreviewed_current_artifact_cannot_be_delivered(self):
        self.create();self.rt.tick('job');self.delegate(self.batch()[:1]);self.rt.tick('job')
        self.factory.finish(self.rt.task('job','v1')['latest']);self.rt.tick('job')
        aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        owner=job_owner.Session(s['frozen'],s['session']['control'],job_owner.files(s['frozen'],s['session']['control']))
        self.addCleanup(owner.rt.close)
        with self.assertRaisesRegex(ValueError,'independent review'):
            owner.complete(dict(deliverables_json=c.encoded({'report':self.rt.output('job','v1','report.txt')['id']}),summary='No review'))

    def test_service_grant_follows_atomic_delegation_but_rejects_unrelated_drift(self):
        self.create();self.rt.db.execute('CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT)')
        from task_relay.production_control import runtime_digest
        self.rt.db.execute('INSERT INTO kv VALUES (?,?)',('production-enabled:job',json.dumps(runtime_digest(self.rt,'job'))))
        self.rt.tick('job');self.delegate(self.batch())
        saved=json.loads(self.rt.db.execute('SELECT value FROM kv').fetchone()[0])
        self.assertEqual(saved,runtime_digest(self.rt,'job'))
        self.finish_children()
        self.rt.db.execute('UPDATE kv SET value=?',(json.dumps('unrelated-change'),))
        aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        owner=job_owner.Session(s['frozen'],s['session']['control'],job_owner.files(s['frozen'],s['session']['control']))
        self.addCleanup(owner.rt.close)
        with self.assertRaisesRegex(ValueError,'dispatch grant changed'):
            owner.delegate(dict(request_id='changed',batch_json=c.encoded(self.batch('new'))))
        self.assertEqual(len(self.rt.status('job')['tasks']),3)

    def test_registered_operation_and_agent_share_the_same_admission(self):
        self.grant['operations']=['text.bundle']
        path=Path(self.tmp.name).resolve()/'source.txt';path.write_text('Exact small source')
        with self.rt.transaction():aid=self.rt.register(path,'Source')
        source=dict(artifact=aid,path='source.txt',purpose='Source',authority='Evidence only',media_type='text/plain')
        self.create(inputs=[source]);self.rt.tick('job')
        batch=self.batch()
        batch[0].pop('worker');batch[0].update(inputs=[source],execution=dict(capability='text.bundle',version=1,parameters={}))
        self.delegate(batch)
        spec=self.rt.spec(self.rt.task('job','v1'))
        self.assertEqual(spec['tools'],[])
        self.assertEqual(spec['criteria'],self.rt.spec(self.rt.task('job','v1_review'))['criteria'])
        self.assertEqual(spec['connector_interface']['operation']['id'],'text.bundle')

    def test_owner_binary_baseline_survives_preflight_without_becoming_model_text(self):
        self.grant['working_context_version']=1
        path=Path(self.tmp.name).resolve()/'baseline.zip';path.write_bytes(b'PK\x03\x04\xff\x00binary fixture')
        with self.rt.transaction():aid=self.rt.register(path,'Prior binary artifact')
        source=dict(artifact=aid,path='baseline.zip',purpose='Prior version',authority='Baseline bytes',media_type='application/zip')
        self.create(inputs=[source]);self.rt.tick('job')
        result,script=self.invoke([('job_delegate',dict(request_id='finish-fixture',batch_json=c.encoded(self.batch('next'))))])
        self.assertEqual(result['outcome'],'yielded')
        initial=json.loads(script.requests[0]['contents'][0]['parts'][0]['text'])
        self.assertEqual(initial['source_pack']['binary_files'][0]['artifact'],aid)
        self.assertEqual(initial['source_pack']['files'],[])

    def test_visual_delivery_cannot_pass_from_structural_review_alone(self):
        code=dict(type='gemini-code',model=BACKEND['model'],runtime='a'*64)
        self.grant['workers'].append(worker_capabilities.entry(code));self.grant['deliverables']={'report':'application/pdf'}
        from orchestrator.document_authoring import capture
        self.grant['authoring_policy']=capture([] ,{'application/pdf':'Explicit synthetic custom-file review test'})
        self.create();self.rt.tick('job');batch=self.batch()
        batch[0]['authoring_fallback']={'reason':'Exercise visual acceptance independently of registered creation'}
        batch[0]['worker']={'requires':['code.execute']};batch[0]['outputs'][0].update(path='preview.pdf',media_type='application/pdf')
        batch[1]['worker']={'requires':['code.execute']};batch[1]['inputs'][0].update(output='preview.pdf',path='preview.pdf',media_type='application/pdf')
        self.delegate(batch);self.rt.tick('job')
        producer=self.rt.task('job','v1')['latest'];self.factory.finish(producer)
        from pypdf import PdfWriter
        pdf=PdfWriter();pdf.add_blank_page(100,100)
        with (Path(self.factory.sessions[producer]['frozen']['workspace'])/'preview.pdf').open('wb') as stream:pdf.write(stream)
        self.rt.tick('job');review_id=self.rt.task('job','v1_review')['latest'];self.factory.finish(review_id,decision='accept')
        session=self.factory.sessions[review_id];result_path=Path(session['frozen']['workspace'])/'.relay/result.json';report=json.loads(result_path.read_text())
        # Scripted semantic judgments do not establish actual pixel inspection.
        for number,binding in session['frozen']['final_quality']['checks'].items():
            detail={dim:dict(verdict='satisfied',reason='Synthetic reviewer judgment',inspected=[dict(path=binding['candidate'],location='page 1')]) for dim in ('requirements','reference_fit','evidence','usability')}
            report['checks'][int(number)-1]['evidence']=json.dumps(detail)
        result_path.write_text(json.dumps(report));self.rt.tick('job')
        aid=self.rt.task('job','owner')['latest'];s=self.factory.sessions[aid]
        owner=job_owner.Session(s['frozen'],s['session']['control'],job_owner.files(s['frozen'],s['session']['control']));self.addCleanup(owner.rt.close)
        artifact=self.rt.output('job','v1','preview.pdf')
        with self.assertRaisesRegex(ValueError,'rendered pixels'):
            owner.complete(dict(deliverables_json=c.encoded({'report':artifact['id']}),summary='Structure passed, pixels unseen'))

    def test_owner_request_capacity_checkpoints_without_resetting_job_allowance(self):
        self.grant['working_context_version']=1 # Historical grants retain their captured policy.
        self.create();self.rt.tick('job')
        with patch.object(executors,'request_limit',return_value=1):
            result,_=self.invoke([('job_catalog',{})])
        self.assertEqual(result['outcome'],'yielded')
        self.rt.tick('job')
        self.assertEqual(self.rt.task('job','owner')['attempts'],2)

    def test_incomplete_owner_response_recovery_uses_only_owner_tools(self):
        self.create();self.rt.tick('job')
        bad=dict(candidates=[dict(finishReason='MAX_TOKENS',content=dict(role='model',parts=[
            dict(functionCall=dict(name='job_complete',args=dict(deliverables_json='{}',summary='Do not execute')))]))])
        result,script=self.invoke([bad,('job_delegate',dict(request_id='finish-fixture',batch_json=c.encoded(self.batch('next'))))])
        self.assertEqual(result['outcome'],'yielded')
        message=script.requests[1]['contents'][-1]['parts'][0]['text']
        self.assertIn('job_delegate',message);self.assertNotIn('using file_write',message)
        events=list(self.rt.db.execute("SELECT 1 FROM production_events WHERE kind='owner_delivery_verified'"))
        self.assertEqual(events,[])
        frozen=self.factory.sessions[self.rt.task('job','owner')['latest']]['frozen']
        self.assertEqual(frozen['max_attempts'],6)
        self.assertEqual(frozen['owner_grant']['owner_turns'],6)

    def test_truncated_owner_reply_does_not_dispatch_its_parseable_delegation(self):
        self.create();self.rt.tick('job')
        call=dict(name='job_delegate',args=dict(request_id='discarded',batch_json=c.encoded(self.batch())))
        truncated=dict(candidates=[dict(finishReason='MAX_TOKENS',content=dict(parts=[dict(functionCall=call)]))])
        with patch.object(executors,'request_limit',return_value=1):result,_=self.invoke([truncated])
        self.assertEqual(result['outcome'],'yielded')
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
        self.rt.tick('job');self.assertEqual(self.rt.task('job','owner')['attempts'],2)
