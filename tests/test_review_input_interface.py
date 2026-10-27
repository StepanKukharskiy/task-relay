"""Real tool-loop filtering and review recovery on small literal fixtures."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from orchestrator import contracts as c,executors,operation_records as records,storage,report_builder
from orchestrator.gemini_worker import Files,execute,definitions
from orchestrator.workers import atomic
from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery,review_budget_recovery as review,pipelines
from task_relay.bridge import State
from tests.test_universal_interfaces import Harness,CONFIGURATIONS
from tests.test_sourcing_records import CONFIG,BACKEND,response
from tests import test_record_completion_continuation as native_fixture
from tests.test_orchestrator import FakeFactory
from orchestrator.runtime import Runtime


def judgment(f,decision='accept'):
    return dict(summary='Independent synthetic candidate review',decision=decision,instruction='',findings=[],
        checks={f'c{i}':dict(passed=True,evidence='Exact candidate text and item judgments') for i in range(1,len(f['criteria'])+1)})


class WorkerTests(unittest.TestCase):
    def prepared(self,config,summary='Exact code summary',budget=8,composed_source=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        h=Harness(temp.name,config,count=2);self.addCleanup(h.db.close);(h.root/'.relay').mkdir()
        _,catalog=h.produce('producer');f=h.assignment('reviewer',catalog=catalog)
        if composed_source:
            for item in f['inputs']:
                if item['path']==f['operation_contract']['parameters']['source_pack_path']:item['from_task']='producer'
        f['inputs'][-1]['from_task']='producer'
        f['inputs'].append({**h.input('candidate-summary.md',summary),'from_task':'producer'})
        f['report_contract']=report_builder.freeze(f);f['limits'].update(tool_calls=budget,provider_requests=budget)
        h.db.execute('update production_attempts set frozen=? where id=?',(c.encoded(f),'reviewer'));h.db.commit()
        control=h.root/'control';control.mkdir();atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        units=records.Store(f,h.db).progress()['next_items'];replies=[]
        for n,item in enumerate(catalog['items']):
            replies.append(response('operation_submit',dict(request_key=str(n),revision=n,records_json=json.dumps([dict(item=item['id'],item_sha256=c.digest(item),verdict='supported',reason='Synthetic correspondence')]))))
        return h,f,control,replies

    def test_composed_source_retains_indexed_role_for_every_registered_schema(self):
        for config in CONFIGURATIONS.values():
            h,f,control,replies=self.prepared(config,budget=4,composed_source=True)
            model=Mock();model.request.side_effect=replies+[response('finish',dict(report_json=json.dumps(judgment(f))))]
            with patch('orchestrator.gemini_worker.emit'):self.assertEqual(execute(f,control,model,lambda:(CONFIG,BACKEND))['decision'],'accept')
            pack=json.loads((control/'source-pack.json').read_text())
            self.assertEqual(next(i['text'] for i in pack['files'] if i['path']=='sources.json'),(h.root/'sources.json').read_text())
            initial=json.loads(model.request.call_args_list[0].args[1]['contents'][0]['parts'][0]['text'])
            self.assertEqual(initial['review_obligations']['indexed_evidence'],['sources.json'])
            self.assertEqual(records.Store(f,h.db).progress()['remaining'],0)

    def test_configurable_review_finishes_with_actual_candidate_and_summary_bindings(self):
        for name,config in CONFIGURATIONS.items():
            with self.subTest(name=name):
                h,f,control,replies=self.prepared(config,budget=4)
                model=Mock();model.request.side_effect=replies+[response('finish',dict(report_json=json.dumps(judgment(f))))]
                with patch('orchestrator.gemini_worker.emit'):result=execute(f,control,model,lambda:(CONFIG,BACKEND))
                self.assertEqual(result['decision'],'accept');pack=json.loads((control/'source-pack.json').read_text())
                self.assertEqual({x['path'] for x in pack['files']},{'reviewer-candidate.json','candidate-summary.md','sources.json','subjects.json'})
                self.assertTrue(all(x['next_offset'] is None for x in pack['files']))
                names={t['name'] for t in model.request.call_args_list[0].args[1]['tools'][0]['functionDeclarations']}
                self.assertIn('file_read',names);self.assertFalse({'file_write','file_append','file_list'}&names)
                self.assertEqual(json.loads((control/'agent-result.json').read_text())['requests'],3)
                self.assertEqual(records.Store(f,h.db).progress()['remaining'],0)

    def test_omitted_summary_is_read_through_exposed_tool_before_finish(self):
        h,f,control,replies=self.prepared(CONFIGURATIONS['plants'],summary='Known omitted summary',budget=6)
        original=Files.source_pack
        # Scale literal initial context rather than create large test artifacts.
        with patch.object(Files,'source_pack',lambda files,max_bytes=None,paths=None:original(files,100,paths)):
            pack=Files(f).source_pack(paths={x['path'] for x in f['inputs'] if x.get('from_task')=='producer'})
            reads=[]
            for item in pack['files']:
                if item['next_offset'] is not None:
                    raw=(h.root/item['path']).read_text();offset=item['next_offset']
                    while offset<len(raw):
                        reads.append(response('file_read',dict(path=item['path'],offset=offset,limit=24000)));offset+=24000
            f['limits'].update(tool_calls=len(reads)+4,provider_requests=len(reads)+4)
            h.db.execute('update production_attempts set frozen=? where id=?',(c.encoded(f),'reviewer'));h.db.commit()
            model=Mock();model.request.side_effect=reads+replies+[response('finish',dict(report_json=json.dumps(judgment(f))))]
            with patch('orchestrator.gemini_worker.emit'):result=execute(f,control,model,lambda:(CONFIG,BACKEND))
        self.assertEqual(result['decision'],'accept')
        self.assertTrue(all('file_read' in {t['name'] for t in call.args[1]['tools'][0]['functionDeclarations']} for call in model.request.call_args_list[:len(reads)]))

    def test_candidate_omission_capacity_is_checked_before_provider(self):
        h,f,control,replies=self.prepared(CONFIGURATIONS['components'],summary='Omitted summary',budget=4)
        # Three omitted candidate files plus one batched judgment and finish
        # cannot fit four exchanges. Keep fixtures tiny; scale initial text only.
        f['inputs'].append({**h.input('addendum.md','Exact additional candidate text'),'from_task':'producer'})
        h.db.execute('update production_attempts set frozen=? where id=?',(c.encoded(f),'reviewer'));h.db.commit()
        model=Mock();original=Files.source_pack
        with patch.object(Files,'source_pack',lambda files,max_bytes=None,paths=None:original(files,100,paths)),self.assertRaisesRegex(ValueError,'candidate reads'),patch('orchestrator.gemini_worker.emit'):
            execute(f,control,model,lambda:(CONFIG,BACKEND))
        model.request.assert_not_called()

    def test_unobserved_or_changed_candidate_still_cannot_be_accepted(self):
        h,f,control,_=self.prepared(CONFIGURATIONS['furniture']);files=Files(f)
        from tests.test_gemini_executor import report
        with self.assertRaisesRegex(ValueError,'complete exact candidate'):files.validate_text_delivery(report(f))
        files.source_pack(paths={x['path'] for x in f['inputs'] if x.get('from_task')=='producer'})
        files.validate_text_delivery(report(f))
        path=h.root/'reviewer-candidate.json';path.write_text('changed')
        with self.assertRaisesRegex(ValueError,'Frozen input changed'):files.validate_text_delivery(report(f))


class RecoveryTests(unittest.TestCase):
    setUp=native_fixture.Tests.setUp
    input=native_fixture.Tests.input
    option=native_fixture.Tests.option
    item=native_fixture.Tests.item
    assignment=native_fixture.Tests.assignment
    save=native_fixture.Tests.save

    def stopped(self):
        self.state=State(self.root/'state.sqlite');self.addCleanup(self.state.db.close);pipelines.initialize(self.state.db)
        rt=Runtime(self.root/'orchestrator',FakeFactory(),connection=self.state.db)
        inputs=[{**i,'artifact':rt.register(self.root/i['path'],'Synthetic source')} for i in self.inputs]
        source=rt.artifact(inputs[1]['artifact'])
        self.state.db.execute('insert into production_attempts values(?,?,?,?,?,?,?,?,?,?)',('native-read','prior','sources','prior','completed',None,c.encoded(dict(execution=dict(capability='web.sources'))),'{}',c.encoded(dict(status='finished',operation=dict(output_sha256=source['sha256'],validation=dict(fetched=5)))),None))
        self.state.db.execute('update production_artifacts set attempt=? where id=?',('native-read',source['id']))
        tasks=[]
        for ident in ('producer','reviewer'):
            t=self.assignment(ident,ident=='reviewer')
            for k in ('assignment_id','workspace','operation_store','backend','report_contract'):t.pop(k,None)
            t.update(id=ident,role='agent',objective='Synthetic typed review',max_attempts=2,inputs=copy.deepcopy(inputs),dependencies=['producer'] if ident=='reviewer' else [])
            tasks.append(t)
        tasks[1]['inputs'] += [dict(from_task='producer',output='delivery/producer.json',path='catalog.json',purpose='Exact candidate',authority='Unaccepted'),dict(from_task='producer',output='delivery/producer.md',path='schedule.md',purpose='Exact summary',authority='Unaccepted')]
        from orchestrator.sourcing_contract import SEMANTIC_CRITERION
        tasks[1]['criteria']=copy.deepcopy(tasks[0]['criteria'])+[SEMANTIC_CRITERION]
        rt.create(dict(id='native',brief='Synthetic review boundary',backend=BACKEND,tasks=tasks));self.state.db.commit();rt.tick('native')
        parent=rt.task('native','producer')['latest'];f=rt.factory.sessions[parent]['frozen'];store=records.Store(f,self.state.db)
        store.submit(dict(request_key='a',revision=0,records=[self.item()]),None);store.submit(dict(request_key='b',revision=1,records=[self.item('item-b',0)]),None);store.export(Files(f),complete=True)
        atomic(Path(f['workspace'])/'.relay/result.json',judgment(f,'delivered'))
        rt.factory.sessions[parent]['status']=dict(status='finished',token=parent,exit_code=0,reason=None,external_outcome='no_pending_response',pending_requests=[])
        rt.tick('native');old=rt.task('native','reviewer')['latest'];f=rt.factory.sessions[old]['frozen'];control=rt.root/'workers'/old;control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        catalog=json.loads((Path(f['workspace'])/'catalog.json').read_text());replies=[]
        for n,item in enumerate(catalog['items']):replies.append(response('operation_submit',dict(request_key=str(n),revision=n,records_json=json.dumps([dict(item=item['id'],item_sha256=c.digest(item),verdict='supported',reason='Historical independent judgment')]))))
        blocked=dict(summary='Input tool unavailable',decision='blocked',instruction='Expose required candidate reads',findings=[dict(category='execution',code='FILE_READ_UNAVAILABLE',message='Input tool absent',evidence='Exact local finish error')],checks={f'c{i}':None for i in range(1,len(f['criteria'])+1)})
        model=Mock();model.request.side_effect=replies+[response('finish',dict(report_json=json.dumps(judgment(f)))),response('finish',dict(report_json=json.dumps(blocked)))]
        original=definitions
        # Reproduce historical public tool exposure and absent initial projection.
        with patch('orchestrator.gemini_worker.definitions',lambda f:[t for t in original(f) if t['name']!='file_read']),patch.object(Files,'source_pack',return_value=dict(files=[],text_bytes=0)),patch('orchestrator.gemini_worker.emit'):
            self.assertEqual(execute(f,control,model,lambda:(CONFIG,BACKEND))['decision'],'blocked')
        rt.factory.sessions[old]['status']=dict(status='finished',token=old,exit_code=0,reason=None,external_outcome='no_pending_response',pending_requests=[],api_requests=4,tool_calls=4)
        rt.tick('native');self.assertEqual(rt.task('native','reviewer')['status'],'blocked')
        with transaction(self.state.db):
            self.state.db.execute('insert into relay_pipelines values(?,?,?,?,?,?,?,?,?,?)',('p',123,'Synthetic full-run authorization','Fixture',json.dumps({'completion':{'version':1},'stages':[dict(gate='none')]}),'desktop','gemini','fixture','blocked',1))
            self.state.db.execute("insert into relay_pipeline_steps(pipeline,position,id,status,target_kind,target,error) values('p',0,'catalog','blocked','production_run','native','Production blocked; no attempts reset.')")
            self.state.db.execute('insert into completion_recovery_grants values(?,?,?)',('p','Synthetic explicit full-run grant',c.encoded(recovery.DELIVERY_POLICY)))
        return rt,parent,old,control

    def test_controller_recovery_retains_exact_history_and_consumes_original_attempt(self):
        rt,parent,old,control=self.stopped();before=dict(self.state.db.execute('select * from production_attempts where id=?',(old,)).fetchone());calls=list(rt.factory.calls)
        recovery.reconcile_changed_failures(self.state);recovery.reconcile_changed_failures(self.state)
        self.assertEqual(calls,rt.factory.calls);self.assertEqual(rt.task('native','reviewer')['status'],'queued')
        self.assertEqual(dict(self.state.db.execute('select * from production_attempts where id=?',(old,)).fetchone()),before)
        self.assertEqual(self.state.db.execute('select count(*) from completion_recoveries').fetchone()[0],1)
        rt.tick('native');new=rt.task('native','reviewer')['latest'];self.assertNotEqual(new,old)
        f=rt.factory.sessions[new]['frozen'];prior=json.loads(before['frozen']);self.assertEqual(f['limits'],prior['limits']);self.assertEqual(f['review_target'],parent)
        self.assertEqual(rt.task('native','producer')['attempts'],1);self.assertEqual(rt.task('native','reviewer')['attempts'],2)
        self.assertEqual(records.Store(prior,self.state.db).progress()['committed'],2)
        control=rt.root/'workers'/new;control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,BACKEND)))
        catalog=json.loads((Path(f['workspace'])/'catalog.json').read_text());model=Mock();replies=[]
        for n,item in enumerate(catalog['items']):replies.append(response('operation_submit',dict(request_key=str(n),revision=n,records_json=json.dumps([dict(item=item['id'],item_sha256=c.digest(item),verdict='supported',reason='Fresh independent judgment')]))))
        model.request.side_effect=replies+[response('finish',dict(report_json=json.dumps(judgment(f))))]
        with patch('orchestrator.gemini_worker.emit'):self.assertEqual(execute(f,control,model,lambda:(CONFIG,BACKEND))['decision'],'accept')
        rt.factory.sessions[new]['status']=dict(status='finished',token=new,exit_code=0,reason=None,external_outcome='no_pending_response',pending_requests=[],api_requests=3,tool_calls=3)
        rt.tick('native');self.assertEqual(rt.status('native')['status'],'completed')
        self.assertEqual(dict(self.state.db.execute('select * from production_attempts where id=?',(old,)).fetchone()),before)

    def test_changed_journal_prevents_dispatch_and_semantic_or_uncertain_stops_hold(self):
        rt,parent,old,control=self.stopped();task=rt.task('native','reviewer');attempt=self.state.db.execute('select * from production_attempts where id=?',(old,)).fetchone()
        self.assertIsNotNone(review.input_proof(rt,task,attempt))
        receipt=json.loads(attempt['receipt'])
        for change in (dict(pending_requests=['unknown']),dict(external_outcome='uncertain'),dict(exit_code=1)):
            row={**dict(attempt),'receipt':c.encoded({**receipt,**change})};self.assertIsNone(review.input_proof(rt,task,row))
        row=self.state.db.execute("select id,data from production_events where attempt=? and kind='checks_recorded' order by id desc limit 1",(old,)).fetchone();data=json.loads(row['data']);original=row['data'];data['result']['findings'][0]['category']='quality'
        self.state.db.execute('update production_events set data=? where id=?',(c.encoded(data),row['id']));self.assertIsNone(review.input_proof(rt,task,attempt))
        self.state.db.execute('update production_events set data=? where id=?',(original,row['id']));self.state.db.commit()
        recovery.reconcile_changed_failures(self.state)
        path=control/'api-03.response.json';path.write_bytes(path.read_bytes()+b' ')
        calls=list(rt.factory.calls);rt.tick('native');self.assertEqual(calls,rt.factory.calls);self.assertEqual(rt.task('native','reviewer')['status'],'blocked')

    def test_zero_effect_launch_after_runtime_change_uses_existing_cycle_worker_slot(self):
        rt,parent,old,control=self.stopped()
        # Exercise the last already authorized cycle, without granting a fifth.
        with transaction(self.state.db):
            for n in (1,2,3):self.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',('p','catalog','native',n,-n,c.encoded(dict(prior=n))))
        recovery.reconcile_changed_failures(self.state);rt.tick('native')
        new=rt.task('native','reviewer')['latest'];self.assertNotEqual(new,old)
        f=rt.factory.sessions[new]['frozen']
        # Real typed-worker startup exports registered empty projections before
        # it reaches the transport. Preserve and validate these exact drafts.
        records.Store(f,self.state.db).export(Files(f))
        f['runtime_sources']['gemini_worker.py']='0'*64
        self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(c.encoded(f),new));self.state.db.commit()
        rt.factory.sessions[new]['status']=dict(status='finished',token=new,exit_code=1,reason='Controlled launch failure',external_outcome='no_pending_response',pending_requests=[],api_requests=0,tool_calls=0)
        rt.tick('native')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id='p'")
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Production blocked; no attempts reset.' WHERE pipeline='p'")
        before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(new,)).fetchone())
        from task_relay.local_review import proof
        projection=Path(f['workspace'])/f['operation_contract']['output'];original=projection.read_bytes()
        projection.write_bytes(b'{"records":["unaccounted output"]}')
        self.assertIsNone(proof(rt,rt.task('native','reviewer'),before))
        projection.write_bytes(original)
        recovery.reconcile_changed_failures(self.state);recovery.reconcile_changed_failures(self.state)
        self.assertEqual(rt.task('native','reviewer')['status'],'queued')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],4)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM local_review_invocations').fetchone()[0],1)
        self.assertEqual(before,dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(new,)).fetchone()))
        rt.tick('native');last=rt.task('native','reviewer')['latest'];self.assertNotEqual(last,new)
        self.assertEqual(rt.task('native','producer')['latest'],parent)
        # The same failed build cannot automatically consume another slot.
        rt.factory.sessions[last]['status']=dict(status='finished',token=last,exit_code=1,reason='Same controlled failure',external_outcome='no_pending_response',pending_requests=[],api_requests=0,tool_calls=0)
        rt.tick('native')
        from task_relay.local_review import proof
        a=self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(last,)).fetchone()
        self.assertIsNone(proof(rt,rt.task('native','reviewer'),a))

    def test_billing_rejection_before_first_record_waits_for_explicit_resume(self):
        from task_relay.relay_channels import ScopedState
        from orchestrator.record_recovery import rejected_checkpoint,checkpoint
        rt,parent,old,control=self.stopped();recovery.reconcile_changed_failures(self.state);rt.tick('native')
        aid=rt.task('native','reviewer')['latest'];f=rt.factory.sessions[aid]['frozen']
        self.assertEqual(records.Store(f,self.state.db).progress()['committed'],0)
        control=rt.root/'workers'/aid;control.mkdir(parents=True,exist_ok=True)
        atomic(control/'api-01.outcome.json',dict(outcome='rejected',http_status=402))
        receipt=dict(status='finished',exit_code=1,token=aid,reason='ProviderError: Gemini request failed (402): credits depleted',api_requests=1,tool_calls=0,external_outcome='no_pending_response',pending_requests=[])
        session=json.loads(self.state.db.execute('SELECT session FROM production_attempts WHERE id=?',(aid,)).fetchone()[0])
        self.state.db.execute('UPDATE production_attempts SET session=? WHERE id=?',(c.encoded({**session,'control':str(control)}),aid));self.state.db.commit()
        rt.factory.sessions[aid]['status']=receipt;rt.tick('native')
        self.assertIsNotNone(rejected_checkpoint(f,receipt,self.state.db,authorized=False))
        self.assertIsNone(checkpoint(f,receipt,self.state.db))
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id='p'")
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Production blocked; no attempts reset.' WHERE pipeline='p'")
        before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone())
        recovery.reconcile_changed_failures(self.state)
        self.assertEqual(rt.task('native','reviewer')['status'],'blocked')
        calls=list(rt.factory.calls)
        with transaction(self.state.db):pipelines.control(ScopedState(self.state,'desktop'),'p','recover_work',request='Credits replenished; resume the saved workflow.')
        self.assertEqual(calls,rt.factory.calls)
        rt.tick('native');new=rt.task('native','reviewer')['latest'];self.assertNotEqual(new,aid)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()),before)
        self.assertEqual(rt.task('native','producer')['latest'],parent)
        self.assertEqual(records.Store(rt.factory.sessions[new]['frozen'],self.state.db).progress()['committed'],0)
