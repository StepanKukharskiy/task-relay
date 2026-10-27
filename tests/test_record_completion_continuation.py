"""Bounded native record continuation with no new planner and exact checkpoints."""
import copy,json,unittest
from pathlib import Path
from orchestrator import contracts as c,operation_records as records
from orchestrator.gemini_worker import Files
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from task_relay.bridge import State
from task_relay import pipelines,completion_recovery as recovery
from tests import test_sourcing_records as fixture
from tests.test_orchestrator import FakeFactory

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    input=fixture.Tests.input
    option=fixture.Tests.option
    item=fixture.Tests.item
    assignment=fixture.Tests.assignment
    save=fixture.Tests.save

    def native(self):
        self.state=State(self.root/'state.sqlite');self.addCleanup(self.state.db.close);pipelines.initialize(self.state.db)
        rt=Runtime(self.root/'orchestrator',FakeFactory(),connection=self.state.db)
        inputs=[{**i,'artifact':rt.register(self.root/i['path'],'Exact fixture source')} for i in self.inputs]
        source=rt.artifact(inputs[1]['artifact']);receipt=dict(status='finished',operation=dict(output_sha256=source['sha256'],validation=dict(fetched=5)))
        self.state.db.execute('insert into production_attempts values(?,?,?,?,?,?,?,?,?,?)',('native-read','prior','sources','prior','completed',None,c.encoded(dict(execution=dict(capability='web.sources'))),'{}',c.encoded(receipt),None));self.state.db.execute('update production_artifacts set attempt=? where id=?',('native-read',source['id']))
        producer=self.assignment('producer');reviewer=self.assignment('reviewer',True)
        for t in (producer,reviewer):
            for k in ('assignment_id','workspace','operation_store','backend','report_contract'):t.pop(k,None)
            t.update(id='reviewer' if t.get('review_of') else 'producer',role='agent',objective='Synthetic continued records',max_attempts=1,inputs=copy.deepcopy(inputs),dependencies=['producer'] if t.get('review_of') else [])
        reviewer['inputs'] += [dict(from_task='producer',output='delivery/producer.json',path='catalog.json',purpose='Exact candidate',authority='Unaccepted'),dict(from_task='producer',output='delivery/producer.md',path='schedule.md',purpose='Exact summary',authority='Unaccepted')]
        reviewer['criteria']=producer['criteria']+[fixture.sourcing.SEMANTIC_CRITERION]
        rt.create(dict(id='native',brief='Synthetic checkpoint',backend=fixture.BACKEND,tasks=[producer,reviewer]));self.state.db.commit();rt.tick('native')
        old=rt.task('native','producer')['latest'];f=rt.factory.sessions[old]['frozen'];store=records.Store(f,self.state.db);store.submit(dict(request_key='one',revision=0,records=[self.item()]),None);store.export(Files(f))
        (Path(f['workspace'])/'.relay/result.json').write_text(c.encoded(dict(summary='Budget exhausted',decision='blocked',instruction='Continue remaining records',findings=[dict(category='execution',code='budget',message='Exhausted',evidence='24 confirmed calls')],checks={'c1':None})))
        rt.factory.sessions[old]['status']=dict(status='finished',exit_code=0,reason=None,external_outcome='no_pending_response',pending_requests=[],tool_calls=24,api_requests=24)
        rt.tick('native');self.assertEqual(rt.task('native','producer')['status'],'blocked')
        with transaction(self.state.db):
            self.state.db.execute('insert into relay_pipelines values(?,?,?,?,?,?,?,?,?,?)',('p',123,'Synthetic full-run authorization','Fixture',json.dumps({'completion':{'version':1}}),'desktop','gemini','fixture','active',1))
            self.state.db.execute("insert into relay_pipeline_steps(pipeline,position,id,status,target_kind,target) values('p',0,'catalog','running','production_run','native')")
            self.state.db.execute('insert into completion_recovery_grants values(?,?,?)',('p','Synthetic explicit full-run grant',c.encoded(recovery.DELIVERY_POLICY)))
        p=self.state.db.execute("select * from relay_pipelines where id='p'").fetchone();s=self.state.db.execute("select * from relay_pipeline_steps where pipeline='p'").fetchone()
        return rt,old,p,s

    def test_existing_cycle_grant_resumes_exact_record_without_planning_or_reset(self):
        rt,old,p,s=self.native();before=dict(self.state.db.execute('select * from production_attempts where id=?',(old,)).fetchone());calls=list(rt.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(calls,rt.factory.calls);self.assertEqual(rt.task('native','producer')['attempts'],1)
        self.assertEqual(dict(self.state.db.execute('select * from production_attempts where id=?',(old,)).fetchone()),before)
        self.assertEqual(self.state.db.execute('select count(*) from orchestrator_chats').fetchone()[0],0)
        rt.tick('native');new=rt.task('native','producer')['latest'];self.assertNotEqual(old,new);self.assertEqual(rt.task('native','producer')['attempts'],2)
        f=rt.factory.sessions[new]['frozen'];store=records.Store(f,self.state.db);self.assertEqual(store.progress()['next_items'][0]['item'],'item-b')
        self.assertEqual(store.document(store._state(self.state.db)[1])['items'][0]['options'][0]['fields']['price']['amount'],'349.99')
        store.submit(dict(request_key='two',revision=store.progress()['revision'],records=[self.item('item-b',0)]),None);store.export(Files(f),complete=True)
        self.assertEqual(len(json.loads((Path(f['workspace'])/'delivery/producer.json').read_text())['items']),2)
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(self.state.db.execute('select count(*) from completion_recoveries').fetchone()[0],1)

    def test_unknown_receipt_missing_grant_and_zero_progress_cannot_add_attempt(self):
        rt,old,p,s=self.native()
        with transaction(self.state.db):self.state.db.execute("delete from completion_recovery_grants where pipeline='p'")
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(rt.task('native','producer')['attempts'],1)
        with transaction(self.state.db):self.state.db.execute('insert into completion_recovery_grants values(?,?,?)',('p','Synthetic explicit full-run grant',c.encoded(recovery.DELIVERY_POLICY)))
        original=json.loads(self.state.db.execute('select receipt from production_attempts where id=?',(old,)).fetchone()[0])
        with transaction(self.state.db):self.state.db.execute('update production_attempts set receipt=? where id=?',(c.encoded({**original,'pending_requests':['unknown-response']}),old))
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'native'))
        with transaction(self.state.db):
            self.state.db.execute('update production_attempts set receipt=? where id=?',(c.encoded(original),old))
            self.state.db.execute('delete from operation_records where attempt=?',(old,))
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(rt.task('native','producer')['attempts'],1)

    def test_early_budget_finish_continues_but_missing_input_and_no_new_progress_do_not(self):
        rt,old,p,s=self.native()
        receipt=json.loads(self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(old,)).fetchone()[0])
        with transaction(self.state.db):self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded({**receipt,'api_requests':5,'tool_calls':5}),old))
        from orchestrator.record_recovery import checkpoint
        f=json.loads(self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(old,)).fetchone()[0])
        early={**receipt,'api_requests':5,'tool_calls':5}
        self.assertIsNotNone(checkpoint(f,early,self.state.db))
        self.assertIsNotNone(checkpoint(f,early,self.state.db,dict(decision='blocked',findings=[dict(category='execution',code='REQUEST_BUDGET_INSUFFICIENT')])) )
        self.assertIsNone(checkpoint(f,early,self.state.db,dict(decision='blocked',findings=[dict(category='requirements',code='missing_image')])) )
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        rt.tick('native');new=rt.task('native','producer')['latest']
        self.assertNotEqual(old,new)
        self.assertEqual(records.Store(rt.factory.sessions[new]['frozen'],self.state.db).progress()['next_items'][0]['item'],'item-b')

    def test_new_human_request_adds_separate_grant_after_exhaustion_without_replacing_history(self):
        from task_relay.relay_channels import ScopedState
        rt,old,p,s=self.native();original=dict(self.state.db.execute("SELECT * FROM completion_recovery_grants WHERE pipeline='p'").fetchone())
        with transaction(self.state.db):
            for n in range(1,5):self.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',('p','catalog','prior-'+str(n),n,-n,c.encoded(dict(prior=n))))
            self.assertFalse(recovery.begin(self.state,p,s,'native'))
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id='p'")
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline='p'")
            pipelines.control(ScopedState(self.state,'desktop'),'p','recover_work',request='Continue this stopped workflow and preserve its records.')
        self.assertEqual(dict(self.state.db.execute("SELECT * FROM completion_recovery_grants WHERE pipeline='p'").fetchone()),original)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],5)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_extensions').fetchone()[0],1)
        self.assertEqual(rt.task('native','producer')['attempts'],1)
        detail=json.loads(self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='completion_records_continued' ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(detail['authorization'],'Continue this stopped workflow and preserve its records.')

    def test_progress_can_cross_three_lifetime_attempts_under_existing_cycle_grant(self):
        self.inventory['items'] += [dict(id='item-c',label='Chair'),dict(id='item-d',label='Rug')]
        self.inputs[0]=self.input('inventory.json',self.inventory)
        rt,old,p,s=self.native()
        for ident in ('item-b','item-c'):
            with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
            rt.tick('native');current=rt.task('native','producer')['latest'];f=rt.factory.sessions[current]['frozen']
            store=records.Store(f,self.state.db)
            store.submit(dict(request_key=ident,revision=store.progress()['revision'],records=[self.item(ident,0)]),None)
            store.export(Files(f))
            (Path(f['workspace'])/'.relay/result.json').write_text(c.encoded(dict(summary='Checkpoint',decision='blocked',instruction='Continue',findings=[dict(category='execution',code='budget',message='Yield',evidence='Confirmed progress')],checks={'c1':None})))
            rt.factory.sessions[current]['status']=dict(status='finished',exit_code=0,reason=None,external_outcome='no_pending_response',pending_requests=[],tool_calls=5,api_requests=5)
            rt.tick('native')
        self.assertEqual(rt.task('native','producer')['attempts'],3)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        rt.tick('native');current=rt.task('native','producer')['latest'];f=rt.factory.sessions[current]['frozen']
        self.assertEqual(rt.task('native','producer')['attempts'],4)
        store=records.Store(f,self.state.db)
        self.assertEqual(store.progress()['next_items'][0]['item'],'item-d')
        store.submit(dict(request_key='last',revision=store.progress()['revision'],records=[self.item('item-d',0)]),None)
        store.export(Files(f),complete=True)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_attempts WHERE run='native' AND task='producer' AND state='blocked'").fetchone()[0],3)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],3)

    def test_first_billing_rejection_requires_new_human_grant_and_resumes_inherited_checkpoint(self):
        self.billing_rejection(1)

    def test_continue_does_not_expand_exhausted_capacity_or_create_missing_grant(self):
        from task_relay.relay_channels import ScopedState
        rt,old,p,s=self.native();scoped=ScopedState(self.state,'desktop')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id='p'")
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline='p'")
            for n in range(1,5):
                self.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',('p','catalog','prior-'+str(n),n,-n,c.encoded(dict(prior=n))))
        before=dict(rt.task('native','producer'))
        with self.assertRaisesRegex(ValueError,'budget'),transaction(self.state.db):
            pipelines.control(scoped,'p','continue',request='Continue within my existing limits.')
        self.assertEqual(dict(rt.task('native','producer')),before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_extensions').fetchone()[0],0)
        with transaction(self.state.db):self.state.db.execute("DELETE FROM completion_recovery_grants WHERE pipeline='p'")
        with self.assertRaisesRegex(ValueError,'no authorized'),transaction(self.state.db):
            pipelines.control(scoped,'p','continue',request='Continue.')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_grants').fetchone()[0],0)

    def test_mid_invocation_billing_rejection_requires_complete_journals_and_new_grant(self):
        self.billing_rejection(3)

    def billing_rejection(self,requests):
        from orchestrator.record_recovery import checkpoint,rejected_checkpoint
        from task_relay.relay_channels import ScopedState
        rt,old,p,s=self.native()
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        rt.tick('native');current=rt.task('native','producer')['latest'];f=rt.factory.sessions[current]['frozen']
        control=self.root/'billing-control';control.mkdir();journal=control/f'api-{requests:02d}.outcome.json'
        journal.write_text(c.encoded(dict(outcome='rejected',http_status=402)))
        if requests>1:
            for number in range(1,requests+1):
                (control/f'api-{number:02d}.request.json').write_text(c.encoded(dict(provider='gemini',model=f['backend']['model'],payload={})))
                if number<requests:
                    (control/f'api-{number:02d}.response.json').write_text(c.encoded(dict(candidates=[])))
                    (control/f'tool-{number:02d}-00.json').write_text(c.encoded(dict(name='sourcing_source_read',result=dict(text='Exact local evidence'))))
        session=json.loads(self.state.db.execute('SELECT session FROM production_attempts WHERE id=?',(current,)).fetchone()[0])
        with transaction(self.state.db):self.state.db.execute('UPDATE production_attempts SET session=? WHERE id=?',(c.encoded({**session,'control':str(control)}),current))
        receipt=dict(status='finished',exit_code=1,reason='ProviderError: Gemini request failed (402): prepaid credits depleted',api_requests=requests,tool_calls=requests-1,external_outcome='no_pending_response',pending_requests=[])
        rt.factory.sessions[current]['status']=receipt;rt.tick('native')
        before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(current,)).fetchone())
        self.assertIsNotNone(rejected_checkpoint(f,receipt,self.state.db,authorized=False))
        self.assertIsNone(checkpoint(f,receipt,self.state.db))
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'native'))
        for changed in ({**receipt,'pending_requests':['unknown']},{**receipt,'api_requests':requests+1},{**receipt,'tool_calls':requests}):
            self.assertIsNone(rejected_checkpoint(f,changed,self.state.db,authorized=False))
        if requests>1:
            path=control/'api-01.response.json';raw=path.read_bytes();path.unlink()
            self.assertIsNone(rejected_checkpoint(f,receipt,self.state.db,authorized=False));path.write_bytes(raw)
            path=control/'api-01.request.json';raw=path.read_bytes();path.write_text(c.encoded(dict(provider='gemini',model='changed')))
            self.assertIsNone(rejected_checkpoint(f,receipt,self.state.db,authorized=False));path.write_bytes(raw)
        journal.write_text(c.encoded(dict(outcome='submitted',http_status=402)))
        self.assertIsNone(rejected_checkpoint(f,receipt,self.state.db,authorized=False))
        journal.write_text(c.encoded(dict(outcome='rejected',http_status=402)))
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id='p'")
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline='p'")
            scoped=ScopedState(self.state,'desktop')
            pipelines.dispatch(scoped,dict(prompt='Gemini is topped up; continue the saved workflow.'),
                dict(kind='pipeline_control',pipeline_id='p',verb='resume'),
                dict(pipelines=[dict(id='p',status='blocked',stages=[])]))
        self.assertEqual(self.state.db.execute("SELECT sum(cycles) FROM completion_recovery_extensions WHERE pipeline='p'").fetchone()[0],0)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(current,)).fetchone()),before)
        from orchestrator.record_recovery import parent_for
        raw=journal.read_bytes();journal.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError,'confirmed-stop'):parent_for(rt,rt.task('native','producer'))
        journal.write_bytes(raw)
        if requests>1:
            path=control/'api-01.response.json';raw=path.read_bytes();path.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'confirmed-stop'):parent_for(rt,rt.task('native','producer'))
            path.write_bytes(raw)
        rt.tick('native');latest=rt.task('native','producer')['latest']
        self.assertNotEqual(latest,current)
        self.assertEqual(rt.task('native','producer')['attempts'],3)
        store=records.Store(rt.factory.sessions[latest]['frozen'],self.state.db)
        self.assertEqual(store.progress()['committed'],1);self.assertEqual(store.progress()['next_items'][0]['item'],'item-b')
