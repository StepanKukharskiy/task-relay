"""Synthetic saved-page review handoffs; no live model or browser."""
import copy,json,hashlib
from pathlib import Path
from unittest.mock import patch
import unittest
from orchestrator import executors,evidence_context,execution
from orchestrator.gemini_worker import Files,execute
from orchestrator.workers import atomic
from orchestrator.browser_context import Archive
from tests import test_input_preflight,test_pipelines
from tests.test_gemini_executor import graph,CONFIG,BACKEND,report
from task_relay import input_preflight_recovery as recovery,production_control as pc
from task_relay.relay_channels import ScopedState


class Tests(unittest.TestCase):
    setUp=test_input_preflight.Tests.setUp
    tearDown=test_input_preflight.Tests.tearDown
    source=test_input_preflight.Tests.source

    def prepared(self,blocked=False,text=None,limits=None,max_attempts=1):
        value=graph();value['tasks'][0].pop('user_gate')
        producer,review=value['tasks']
        review['max_attempts']=max_attempts
        text=text if text is not None else 'Chair $125; dimensions 24 inches.\n'*200
        source=dict(version=1,kind='public_source_candidates',entries=[dict(query='chair',target_ids=['A'],pages=[dict(url='https://example.test/p/chair',text=text,sha256='a'*64)])])
        raw=json.dumps(source,ensure_ascii=False)
        producer.update(tools=[],execution=dict(capability='web.sources.rendered',version=1,parameters=dict(domains=[],max_pages=1)),inputs=[{**self.source(raw.encode(),'base.json'),'media_type':'application/json'}],outputs=[dict(path='delivery/source-pack.json',purpose='Saved candidates',media_type='application/json')],criteria=copy.deepcopy(execution.REGISTRY['web.sources.rendered']['criteria']),limits=dict(seconds=120,tool_calls=1,output_bytes=3000000))
        review.update(criteria=copy.deepcopy(producer['criteria']),limits=dict(seconds=120,tool_calls=12,output_bytes=10000),inputs=[dict(from_task='produce',output='delivery/source-pack.json',path='candidate.json',purpose='Exact pages',authority='Unaccepted')])
        if limits:review['limits'].update(limits)
        self.rt.create(value);self.rt.tick('demo');aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        ws=self.factory.sessions[aid]['workspace'];(ws/'delivery/source-pack.json').write_text(raw)
        # Simulate the previous installed admission policy, retaining zero dispatch.
        with patch.object(executors,'MAX_INPUT_BYTES',64):
            if blocked=='capacity':
                with patch('orchestrator.evidence_context.bind',side_effect=evidence_context.EvidenceCapacityError('Indexed evidence review needs 18 reads/finalization requests within 6; partition the evidence before dispatch.')):self.rt.tick('demo')
            elif blocked:
                with patch('orchestrator.evidence_context.bind',side_effect=lambda *args:None):self.rt.tick('demo')
            else:self.rt.tick('demo')
        return raw,aid

    def test_complete_literal_review_and_missing_or_changed_intervals_rejected(self):
        raw,aid=self.prepared();frozen=self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen'];files=Files(frozen)
        first=files.source_pack(max_bytes=17)
        result=report(frozen)
        with self.assertRaisesRegex(ValueError,'complete exact candidate'):files.validate_text_delivery(result)
        rebuilt=first['files'][0]['text'];batches=[]
        with patch.dict(frozen['evidence_context'],batch_bytes=2048):
            while True:
                batch=files.call('evidence_next',{});batches.append(batch)
                for part in batch['parts']:
                    self.assertEqual(raw[part['offset']:part['end']],part['text']);rebuilt+=part['text']
                if not batch['remaining']:break
        self.assertEqual(rebuilt,raw);files.validate_text_delivery(result)
        self.assertEqual(files.call('evidence_next',{})['parts'],[])
        p=Path(frozen['workspace'])/'candidate.json';p.chmod(0o600);p.write_text('changed')
        with self.assertRaisesRegex(ValueError,'Frozen input changed'):files.call('evidence_next',{})

    def test_recovery_retains_exact_history_and_consumes_first_review_once(self):
        raw,aid=self.prepared(blocked=True);before=dict(self.rt.task('demo','review'));artifact=dict(self.rt.output('demo','produce','delivery/source-pack.json'))
        with patch.object(executors,'MAX_INPUT_BYTES',64):
            with self.rt.transaction():self.assertEqual(len(recovery.requeue(self.rt,'demo')),1)
            with self.rt.transaction():self.assertEqual(recovery.requeue(self.rt,'demo'),[])
        self.assertEqual(self.rt.task('demo','review')['assignment'],before['assignment']);self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.rt.tick('demo');self.rt.tick('demo');self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(dict(self.rt.output('demo','produce','delivery/source-pack.json')),artifact);self.assertEqual(self.rt.task('demo','produce')['latest'],aid)

    def test_impossible_explicit_request_budget_does_not_dispatch(self):
        raw,aid=self.prepared(blocked=True);t=self.rt.task('demo','review');spec=self.rt.spec(t);spec['limits']['provider_requests']=1
        with self.assertRaisesRegex(ValueError,'partition the evidence'):self.rt.checked_inputs('demo',spec,BACKEND)
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)

    def test_large_exact_review_recovers_and_finishes_inside_six_original_requests(self):
        # Generated text exercises transport size without media or live calls.
        raw,aid=self.prepared(blocked='capacity',text='Plant "A"; component \\ B; размер 24.\n'*34000,
                              limits=dict(tool_calls=6,provider_requests=6))
        task=self.rt.task('demo','review');assignment=task['assignment']
        with self.rt.transaction():self.assertEqual(len(recovery.requeue(self.rt,'demo')),1)
        self.rt.tick('demo')
        frozen=self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen']
        self.assertEqual(frozen['limits']['provider_requests'],6)
        self.assertEqual(self.rt.task('demo','review')['assignment'],assignment)
        self.assertGreater(frozen['evidence_context']['batch_bytes'],evidence_context.BATCH_BYTES)
        control=Path(frozen['workspace']).parent/'adaptive-control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        received=[];requests=[]
        class Client:
            def request(inner,endpoint,payload,**kwargs):
                requests.append(payload)
                self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False).encode()),executors.MAX_INPUT_BYTES)
                initial=json.loads(payload['contents'][0]['parts'][0]['text'])
                if len(requests)==1:received.append(initial['source_pack']['files'][0]['text'])
                last=payload['contents'][-1]['parts'][0].get('functionResponse',{})
                remaining=initial['review_session']['remaining']
                if last.get('name')=='evidence_next':
                    received.extend(p['text'] for p in last['response']['parts'])
                    remaining=last['response']['remaining']
                name,args=('evidence_next',dict(notes='Provisional: retain unverified claims.')) if remaining else ('finish',dict(report_json=json.dumps(report(frozen))))
                return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(functionCall=dict(name=name,args=args))]))])
        with patch('orchestrator.gemini_worker.emit'):result=execute(frozen,control,Client(),lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'accept');self.assertLessEqual(len(requests),6)
        self.assertEqual(''.join(received),raw)
        self.assertEqual(self.rt.task('demo','produce')['latest'],aid)

    def test_historical_capacity_hold_recovers_but_other_admission_failures_do_not(self):
        raw,aid=self.prepared(blocked='capacity',limits=dict(tool_calls=6,provider_requests=6))
        row=self.rt.db.execute("SELECT id,data FROM production_events WHERE kind='input_preflight_blocked' ORDER BY id DESC LIMIT 1").fetchone()
        proof=json.loads(row['data']);self.assertEqual(proof.pop('failure'),dict(version=1,code='evidence_capacity'))
        historical=copy.deepcopy(proof)
        for changes in (dict(reason='Registered artifact content changed: candidate.json'),dict(failure=dict(version=2,code='evidence_capacity')),dict(dispatched=True),dict(assignment='foreign')):
            with self.subTest(changes=changes),self.rt.transaction():
                self.rt.db.execute('UPDATE production_events SET data=? WHERE id=?',(json.dumps({**proof,**changes}),row['id']))
                self.assertEqual(recovery.requeue(self.rt,'demo'),[])
        with self.rt.transaction():
            self.rt.db.execute('UPDATE production_events SET data=? WHERE id=?',(json.dumps(historical),row['id']))
            self.assertEqual(len(recovery.requeue(self.rt,'demo')),1)
        self.assertEqual(json.loads(self.rt.db.execute('SELECT data FROM production_events WHERE id=?',(row['id'],)).fetchone()[0]),historical)
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','review')['attempts'],1)

    def test_native_transport_accounts_for_nested_string_escaping(self):
        raw,_=self.prepared(text='Quote " and slash \\ with Unicode листья'*30)
        frozen=self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen']
        for provider in ('gemini','openai','qwen','openrouter'):
            with self.subTest(provider=provider):
                value=copy.deepcopy(frozen);value['evidence_context'].update(batch_bytes=2048,transport_provider=provider)
                files=Files(value);received=[]
                while True:
                    batch=files.call('evidence_next',{})
                    # Native provider tool output is a JSON string; Gemini uses
                    # an object. Exercise the actual response transport shape.
                    output=batch if provider=='gemini' else json.dumps(batch,ensure_ascii=False)
                    self.assertLessEqual(len(json.dumps(dict(output=output),ensure_ascii=False).encode()),2600)
                    received.extend(p['text'] for p in batch['parts'])
                    if not batch['remaining']:break
                self.assertEqual(''.join(received),raw)
                files.validate_text_delivery(report(value))

    def test_false_alias_cannot_erase_independent_read_obligations(self):
        raw,_=self.prepared();frozen=copy.deepcopy(self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen'])
        source=frozen['inputs'][0];path=Path(frozen['workspace'])/'different.json';path.write_text('different bytes')
        frozen['inputs'].append({**source,'path':'different.json','artifact':'other','sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        frozen['evidence_context']['aliases']={'different.json':source['path']}
        with self.assertRaisesRegex(ValueError,'exact original bytes'):Files(frozen).source_pack()

    def test_changed_candidate_version_after_recovery_never_dispatches(self):
        raw,aid=self.prepared(blocked=True)
        with patch.object(executors,'MAX_INPUT_BYTES',64):
            with self.rt.transaction():self.assertEqual(len(recovery.requeue(self.rt,'demo')),1)
        artifact=self.rt.output('demo','produce','delivery/source-pack.json')
        # A newly registered immutable version is distinct even with equal bytes.
        replacement=self.rt.register(artifact['blob'],'New controlled version')
        with self.rt.transaction():
            self.rt.db.execute('UPDATE production_artifacts SET attempt=?,path=? WHERE id=?',(aid,'delivery/source-pack.json',replacement))
            self.rt.db.execute('UPDATE production_artifacts SET path=? WHERE id=?',('historical/source-pack.json',artifact['id']))
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked');self.assertEqual(len(self.factory.calls),1)

    def test_provisional_notes_survive_batches_and_are_bound_to_seen_versions(self):
        raw,aid=self.prepared();frozen=self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen'];files=Files(frozen)
        files.source_pack(max_bytes=24);notes='Provisional: inspect exact price in candidate.json; coverage remains unresolved.'
        value=files.call('evidence_next',dict(notes=notes));self.assertEqual(value['review_notes'][0]['notes'],notes)
        checkpoint=files.evidence_notes[0];self.assertEqual(checkpoint['inputs'][0]['sha256'],frozen['inputs'][0]['sha256']);self.assertEqual(checkpoint['inputs'][0]['observed'],[(0,24)])
        self.assertIn(notes,files.call('evidence_next',{})['review_notes'][0]['notes'])

    def test_native_provider_views_preserve_older_exact_evidence_and_receipts(self):
        import tempfile
        value=dict(parts=[dict(path='candidate.json',offset=0,text='literal evidence '*600)],remaining=[])
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root))
            for provider,history in [('openai',[dict(type='function_call_output',call_id='one',output=json.dumps(value)),dict(type='function_call_output',call_id='two',output='{}')]),('qwen',[dict(role='tool',tool_call_id='one',content=json.dumps(value)),dict(role='tool',tool_call_id='two',content='{}')])]:
                original=copy.deepcopy(history);view=a.native_view(history,provider);self.assertEqual(history,original)
                key='output' if provider=='openai' else 'content';ref=json.loads(view[0][key]);offset=0;chunks=[]
                while True:
                    part=a.read(dict(evidence=ref['evidence'],offset=offset));chunks.append(part['text'])
                    if part['next_offset'] is None:break
                    offset=part['next_offset']
                self.assertEqual(json.loads(''.join(chunks)),value)

    def test_scripted_worker_reads_and_finishes_without_an_extra_write_request(self):
        raw,aid=self.prepared();frozen=self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen'];control=Path(frozen['workspace']).parent/'scripted-control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        class Client:
            def request(inner,endpoint,payload,**kwargs):
                self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False).encode()),executors.MAX_INPUT_BYTES)
                name='evidence_next';args={}
                turns=payload['contents'];last=turns[-1]['parts'][0].get('functionResponse',{})
                if last.get('name')=='evidence_next' and not last['response']['remaining']:name='finish';args={'report_json':json.dumps(report(frozen))}
                return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(functionCall=dict(name=name,args=args))]))])
        with patch.object(evidence_context,'BATCH_BYTES',4096):
            frozen['evidence_context']['batch_bytes']=4096
            frozen['evidence_context']['initial_bytes']=32
            result=execute(frozen,control,client=Client(),config_reader=lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'accept');self.assertTrue((Path(frozen['workspace'])/'review.md').exists())

    def test_last_invocation_turn_reads_remaining_obligations_then_resumes(self):
        from orchestrator import contracts as c
        raw,_=self.prepared();frozen=copy.deepcopy(self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen'])
        frozen['limits'].update(tool_calls=3,provider_requests=3)
        frozen['evidence_context'].update(initial_bytes=32,batch_bytes=2700)
        control=Path(frozen['workspace']).parent/'first-control';control.mkdir()
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        class Client:
            def request(inner,endpoint,payload,**kwargs):
                first=json.loads(payload['contents'][0]['parts'][0]['text'])
                last=payload['contents'][-1]['parts'][0].get('functionResponse',{})
                remaining=last.get('response',{}).get('remaining',first['review_session']['remaining'])
                name,args=('evidence_next',{}) if remaining else ('finish',dict(report_json=json.dumps(report(frozen))))
                return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(functionCall=dict(name=name,args=args))]))])
        with patch('orchestrator.gemini_worker.emit'),self.assertRaisesRegex(ValueError,'request budget'):
            execute(frozen,control,Client(),lambda:(CONFIG,BACKEND))
        self.assertEqual(json.loads((control/'tool-03-00.json').read_text())['name'],'evidence_next')
        self.assertFalse((Path(frozen['workspace'])/'.relay/result.json').exists())
        checkpoint=json.loads((control/'review-session.json').read_text())
        unread=json.loads((control/'tool-03-00.json').read_text())['result']['parts'][0]
        self.assertLessEqual(max(b for a,b in checkpoint['observed'][unread['path']]),unread['offset'])
        frozen.update(assignment_id='continued-physical-invocation',review_checkpoint=dict(data=checkpoint,sha256=c.digest(checkpoint)))
        resumed=control.with_name('second-control');resumed.mkdir()
        atomic(resumed/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        with patch('orchestrator.gemini_worker.emit'):result=execute(frozen,resumed,Client(),lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'accept')
        self.assertEqual(json.loads((resumed/'review-session.json').read_text())['identity'],checkpoint['identity'])


class PipelineTests(unittest.TestCase):
    setUp=Tests.setUp
    tearDown=Tests.tearDown
    prepared=Tests.prepared
    source=Tests.source
    request=test_pipelines.Tests.request
    create=test_pipelines.Tests.create
    stage=test_pipelines.Tests.stage
    step=test_pipelines.Tests.step

    def test_admission_uses_original_session_attempts_and_controller_resumes_after_restart(self):
        from orchestrator.runtime import Runtime
        from task_relay import completion_recovery
        from tests.test_operation_session import Tests as SessionTests
        # Small literal fixture; constrain transport to require two invocations.
        with patch.object(evidence_context,'BATCH_BYTES',20000),patch.object(evidence_context,'ENVELOPE_BYTES',executors.MAX_INPUT_BYTES-20000),patch.object(evidence_context,'INITIAL_BYTES',32):
            raw,producer=self.prepared(blocked='capacity',text='Plant A / component B.\n'*2100,
                                       limits=dict(tool_calls=3,provider_requests=3),max_attempts=2)
            task=self.rt.task('demo','review');original=copy.deepcopy(self.rt.spec(task))
            denied=copy.deepcopy(original);denied['max_attempts']=1
            with self.assertRaises(evidence_context.EvidenceCapacityError):self.rt.checked_inputs('demo',denied,BACKEND)
            denied=copy.deepcopy(original);denied['tools']=['files','shell']
            with self.assertRaises(evidence_context.EvidenceCapacityError):self.rt.checked_inputs('demo',denied,BACKEND)
            p=self.create([self.stage(route='production',caps=['web.sources.rendered']),self.stage('finish')])
            with self.state.db:
                self.state.db.execute('INSERT INTO completion_recovery_grants VALUES (?,?,?)',(p['id'],'Complete delivery',json.dumps(completion_recovery.DELIVERY_POLICY)))
                self.state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='production_run',target='demo' WHERE pipeline=? AND id='outline'",(p['id'],))
            with self.rt.transaction():self.assertEqual(len(recovery.requeue(self.rt,'demo')),1)
            self.rt.tick('demo');first=self.rt.task('demo','review')['latest'];frozen=self.factory.sessions[first]['frozen']
            self.assertGreater(frozen['evidence_context']['required_requests'],3)
            self.assertEqual(frozen['evidence_context']['logical_provider_requests'],5)
            received=[]
            class Client:
                def request(inner,endpoint,payload,**kwargs):
                    self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False).encode()),executors.MAX_INPUT_BYTES)
                    initial=json.loads(payload['contents'][0]['parts'][0]['text'])
                    received.extend(dict(path=i['path'],offset=0,end=len(i['text']),text=i['text']) for i in initial['source_pack']['files'])
                    last=payload['contents'][-1]['parts'][0].get('functionResponse',{})
                    if last.get('name')=='evidence_next':received.extend(last['response']['parts'])
                    remaining=last.get('response',{}).get('remaining',initial['review_session']['remaining'])
                    name,args=('evidence_next',dict(notes='Provisional observations only.')) if remaining else ('finish',dict(report_json=json.dumps(report(frozen))))
                    return dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(functionCall=dict(name=name,args=args))]))])
            result,control=SessionTests.run_worker(self,self,first,Client());self.assertIsNone(result)
            self.rt.tick('demo');prior=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(first,)).fetchone())
            calls=list(self.factory.calls)
            with self.rt.transaction():self.assertTrue(completion_recovery.begin(self.state,p,self.step(p,'outline'),'demo'))
            self.assertEqual(calls,self.factory.calls)
            self.rt=Runtime(self.rt.root,self.factory,connection=self.state.db);self.rt.tick('demo')
            second=self.rt.task('demo','review')['latest'];self.assertNotEqual(first,second)
            self.assertEqual(self.factory.sessions[second]['frozen']['limits'],original['limits'])
            frozen=self.factory.sessions[second]['frozen']
            result,_=SessionTests.run_worker(self,self,second,Client());self.assertIsNotNone(result,self.factory.sessions[second]['status']);self.assertEqual(result['decision'],'accept')
            self.rt.tick('demo');self.assertEqual(self.rt.status('demo')['status'],'completed')
            self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(first,)).fetchone()),prior)
            self.assertEqual(self.rt.task('demo','produce')['latest'],producer)
            self.assertEqual(self.rt.task('demo','review')['attempts'],2)
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
            # Every original byte was actually supplied in one of the invocations.
            checkpoint=json.loads((control/'review-session.json').read_text())
            self.assertFalse(checkpoint['accepted'])
            actual=[None]*len(raw)
            for part in received:
                self.assertEqual(raw[part['offset']:part['end']],part['text'])
                actual[part['offset']:part['end']]=part['text']
            self.assertEqual(''.join(actual),raw)

    def test_both_stage_binding_forms_resume_only_unchanged_authorized_graph(self):
        from task_relay import pipelines,completion_recovery
        raw,aid=self.prepared(blocked=True);value=json.loads(self.state.db.execute("select plan from production_runs where id='demo'").fetchone()[0])
        p=self.create([self.stage(route='production',caps=['web.sources.rendered']),self.stage('finish')]);c=self.state.db
        c.execute("INSERT INTO production_plans(id,request_id,channel,request,options,context,context_hash,provider,model,status,plan,run,token,expires,created) VALUES ('saved',2,?,'Exact synthetic request','{}','{}','fixture','fixture','fixture','started',?,'demo','fixture',9999999999,1)",(p['channel'],json.dumps(value)))
        c.execute('INSERT INTO completion_recovery_grants VALUES (?,?,?)',(p['id'],'Explicit complete-delivery authorization',json.dumps(completion_recovery.DELIVERY_POLICY)))
        c.commit()
        for kind,target in [('plan_production','saved'),('production_run','demo')]:
            with self.subTest(kind=kind),c:
                c.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
                c.execute("UPDATE relay_pipeline_steps SET status='blocked',target_kind=?,target=?,error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='outline'",(kind,target,p['id']))
                c.execute("UPDATE production_tasks SET status='blocked' WHERE run='demo' AND id='review'")
            with patch.object(executors,'MAX_INPUT_BYTES',64):recovery.reconcile(self.state)
            self.assertEqual(self.step(p,'outline')['status'],'running')
            self.assertEqual(self.rt.task('demo','review')['status'],'queued');self.assertEqual(self.rt.task('demo','review')['attempts'],0)
            self.assertEqual(self.rt.task('demo','produce')['latest'],aid)
        # A graph mutation and a user control epoch each hold admission.
        with c:
            c.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            c.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Production blocked; no attempts reset.' WHERE pipeline=? AND id='outline'",(p['id'],))
            c.execute("UPDATE production_tasks SET status='blocked' WHERE run='demo' AND id='review'")
            scoped=ScopedState(self.state,p['channel']);scoped.put('production-control-epoch:demo',1)
        recovery.reconcile(self.state);self.assertEqual(self.step(p,'outline')['status'],'blocked')
        with c:
            scoped.put('production-control-epoch:demo',0)
            task=self.rt.task('demo','review');spec=self.rt.spec(task);spec['instruction']='Changed scope'
            c.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),task['assignment']))
        recovery.reconcile(self.state);self.assertEqual(self.step(p,'outline')['status'],'blocked')
