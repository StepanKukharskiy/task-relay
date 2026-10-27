import copy,json,unittest
from pathlib import Path
from task_relay import pipelines as pipe, production_planning as planning, production_control as pc
from orchestrator.storage import transaction


class Tests(unittest.TestCase):
    def setUp(self):
        from tests.test_pipelines import Tests as Fixture
        self.f=Fixture();self.f.setUp();self.addCleanup(self.f.tearDown)

    def stages(self):
        source=self.f.stage('report','production');source['research_mode']='none'
        final=self.f.stage('summary');final['report_source']={'stage':'report','output':'report'}
        final['handoff']['inputs']=[dict(stage='report',deliverable='report',media_type='text/plain',consumer='context')]
        return [source,final]

    def completed_source(self,body='Price: $760.\nLength 36 in; width 36 in; height 15 in.\nStock remains unverified.\n'):
        p=self.f.create(self.stages())
        with transaction(self.f.state.db):self.f.state.db.execute("UPDATE relay_pipelines SET channel='desktop' WHERE id=?",(p['id'],))
        self.f.answer(dict(kind='plan_production',template='custom',project=None,reference_pack_id=None,research_ids=[],artifact_ids=[],planning_only=False,research_mode='none',step_capabilities=[],deliverables={'report':'Exact report output'}))
        stage=self.f.step(p,'report');response=self.f.response();response['deliverable_map']={'report':{'task':'produce','output':'output.txt'}}
        for t in response['plan']['tasks']:t.pop('user_gate',None)
        planning.Worker(self.f.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        self.assertEqual(row['status'],'ready',row['error']);pipe.tick(self.f.state)
        row=self.f.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        worker=pc.Worker(self.f.state,lambda _:self.f.rt);worker.tick()
        author=self.f.rt.task(row['run'],'produce')['latest'];self.f.factory.finish(author)
        (self.f.factory.sessions[author]['workspace']/'output.txt').write_text(body)
        worker.tick();review=self.f.rt.task(row['run'],'review')['latest']
        self.f.factory.finish(review,decision='accept');worker.tick();pipe.tick(self.f.state)
        self.assertEqual(self.f.step(p,'report')['status'],'completed')
        return p,row['run'],author,review,body

    def test_native_reviewed_text_completes_without_reporting_provider_or_acceptance(self):
        p,run,author,review,body=self.completed_source()
        # Other-channel model work fills the global queue; this report needs no model slot.
        with transaction(self.f.state.db):
            for ident in range(7000,7005):
                self.f.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,status,created) VALUES (?, 'Other-channel work','fixture','fixture','queued',0)",(ident,))
        before=self.f.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        pipe.tick(self.f.state)
        final=self.f.step(p,'summary');self.assertEqual(final['status'],'completed',final['error'])
        self.assertEqual(final['result'],body);self.assertIsNone(final['request_id'])
        message=self.f.state.db.execute('SELECT text,sent FROM outbox WHERE id=?',(f'pipeline:{p["id"]}:summary:result',)).fetchone()
        self.assertTrue(message['text'].startswith(body+'\n\n'));self.assertEqual(message['sent'],0)
        self.assertEqual(self.f.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],before)
        record=json.loads(self.f.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE pipeline=? AND kind='reviewed_artifact_report'",(p['id'],)).fetchone()[0])
        self.assertEqual(record['provider_calls'],0);self.assertEqual(record['producer_attempt'],author)
        self.assertEqual(record['reviewers'][0]['attempt'],review)
        self.assertEqual(self.f.state.db.execute('SELECT count(*) FROM production_decisions WHERE run=?',(run,)).fetchone()[0],0)
        pipe.tick(self.f.state);pipe.tick(self.f.state)
        self.assertEqual(self.f.state.db.execute('SELECT status FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone()[0],'completed')
        self.assertEqual(len(self.f.factory.calls),2)
        self.assertEqual(self.f.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE pipeline=? AND kind='reviewed_artifact_report'",(p['id'],)).fetchone()[0],1)

    def test_changed_review_target_prevents_delivery(self):
        p,run,author,review,_=self.completed_source()
        with transaction(self.f.state.db):
            a=self.f.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(review,)).fetchone()
            frozen=json.loads(a[0]);frozen['review_target']='other'
            self.f.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),review))
        pipe.tick(self.f.state)
        self.assertEqual(self.f.step(p,'summary')['status'],'blocked')
        self.assertIn('independent review',self.f.step(p,'summary')['error'])
        self.assertIsNone(self.f.step(p,'summary')['result'])

    def test_report_artifact_must_be_in_the_reviewers_frozen_inputs(self):
        p,run,author,review,_=self.completed_source()
        with transaction(self.f.state.db):
            a=self.f.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(review,)).fetchone()
            frozen=json.loads(a[0]);frozen['inputs']=[]
            self.f.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),review))
        pipe.tick(self.f.state)
        final=self.f.step(p,'summary');self.assertEqual(final['status'],'blocked')
        self.assertIn('independent review',final['error']);self.assertIsNone(final['result'])

    def test_oversized_report_is_not_truncated_or_sent_to_provider(self):
        p,*_=self.completed_source('x'*10001);pipe.tick(self.f.state)
        final=self.f.step(p,'summary');self.assertEqual(final['status'],'blocked')
        self.assertIn('no truncation',final['error']);self.assertIsNone(final['result'])
        self.assertIsNone(final['request_id'])

    def test_choice_nonfinal_missing_port_and_binary_sources_are_rejected(self):
        for kind in ['choice','nonfinal','missing_port','binary','unbound']:
            stages=self.stages()
            if kind=='choice':stages[-1]['gate']='choice'
            elif kind=='nonfinal':stages.append(self.f.stage('later'))
            elif kind=='missing_port':stages[-1]['report_source']['output']='missing'
            elif kind=='binary':stages[0]['handoff']['outputs']['report']['media_type']='application/pdf'
            elif kind=='unbound':stages[-1]['handoff']['inputs']=[]
            with self.subTest(kind=kind),self.assertRaises(pipe.PipelineValidationError):pipe.validate_report_sources(stages)

    def test_pending_producer_receipt_prevents_report_without_replaying(self):
        p,run,author,_,_=self.completed_source()
        with transaction(self.f.state.db):
            receipt=json.loads(self.f.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(author,)).fetchone()[0])
            receipt['pending_requests']=['unknown-outcome']
            self.f.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),author))
        pipe.tick(self.f.state)
        final=self.f.step(p,'summary');self.assertEqual(final['status'],'blocked')
        self.assertIn('confirmed finished receipt',final['error']);self.assertIsNone(final['result'])
        self.assertEqual(len(self.f.factory.calls),2)

    def test_semantic_builder_preserves_explicit_report_binding(self):
        from task_relay import workflow_builder
        details=[]
        for stage in self.stages():
            details.append(dict(id=stage['id'],instruction=stage['instruction'],route=stage['route'],gate=stage['gate'],capabilities=[],
                outputs={k:dict(description=v,format='text') for k,v in stage['deliverables'].items()},
                uses=[dict(stage=e['stage'],output=e['deliverable'],consumer=e['consumer']) for e in stage['handoff']['inputs']],
                **({'report_source':stage['report_source']} if 'report_source' in stage else {})))
        action,_=workflow_builder.build(dict(kind='plan_pipeline',title='Reviewed report',planning_only=True,stage_details=details),{})
        pipe.validate_report_sources(action['stages'])
        self.assertEqual(action['stages'][-1]['report_source'],dict(stage='report',output='report'))
