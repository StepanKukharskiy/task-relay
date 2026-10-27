"""Real worker/controller transitions with scripted providers and small records."""
import copy,json,unittest
from pathlib import Path
from orchestrator import contracts as c,operation_records as records
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery,local_review
from tests import test_record_completion_continuation as fixture
from tests import test_operation_session as sessions
from tests.test_operation_session import Script


def finish(decision='accept',checks=None):
    return ('finish',dict(report_json=c.encoded(dict(summary='Exact saved evidence reviewed',decision=decision,
        instruction='',findings=[],checks={} if checks is None else checks))))


def check(key):
    return ('report_check',dict(check=key,value_json=c.encoded(dict(passed=True,evidence='Exact candidate and saved item evidence inspected.'))))


def truncated():
    # Even a parseable finish must never execute from an incomplete candidate.
    return dict(candidates=[dict(finishReason='MAX_TOKENS',content=dict(parts=[dict(functionCall=dict(name='finish',args=finish()[1]))]))])


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    input=fixture.Tests.input
    option=fixture.Tests.option
    item=fixture.Tests.item
    assignment=fixture.Tests.assignment
    save=fixture.Tests.save
    native=fixture.Tests.native
    run_worker=sessions.Tests.run_worker

    def prepare(self):
        rt,old,p,s=self.native();self.rt=rt;self.factory=rt.factory
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        rt.tick('native');producer=rt.task('native','producer')['latest'];f=self.factory.sessions[producer]['frozen']
        progress=records.Store(f,self.state.db).progress()
        script=Script([('operation_submit',dict(request_key='last',revision=progress['revision'],records_json=c.encoded([self.item('item-b',0)]))),
            finish('delivered',{'c1':dict(passed=True,evidence='All requested item records saved with explicit gaps.')})])
        result,control=self.run_worker(self,producer,script);self.assertIsNotNone(result)
        rt.tick('native');aid=rt.task('native','reviewer')['latest'];self.assertIsNotNone(aid)
        return p,s,producer,aid

    def judgment(self,aid):
        store=records.Store(self.factory.sessions[aid]['frozen'],self.state.db);progress=store.progress();item=progress['next_items'][0]
        return ('operation_submit',dict(request_key=item['item'],revision=progress['revision'],records_json=c.encoded([
            dict(item=item['item'],item_sha256=item['item_sha256'],verdict='supported',reason='Observed fields are source-bound; missing alternatives are disclosed.')])) )

    def stop(self,aid):
        outer=self
        class Reviewer(Script):
            def request(self,endpoint,payload,**kw):
                if records.Store(outer.factory.sessions[aid]['frozen'],outer.state.db).progress()['remaining']:
                    self.steps=iter([outer.judgment(aid)])
                else:
                    self.steps=iter([truncated() if getattr(self,'check_saved',False) else check('c1')])
                    self.check_saved=True
                return super().request(endpoint,payload,**kw)
        script=Reviewer([])
        result,control=self.run_worker(self,aid,script);self.assertIsNone(result)
        self.rt.tick('native');return control

    def test_complete_records_survive_restart_and_finish_from_saved_checks(self):
        p,s,producer,aid=self.prepare();control=self.stop(aid)
        self.assertEqual(records.Store(self.factory.sessions[aid]['frozen'],self.state.db).progress()['remaining'],0)
        self.assertFalse((Path(self.factory.sessions[aid]['frozen']['workspace'])/'.relay/result.json').exists())
        saved=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone())
        calls=list(self.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(self.factory.calls,calls)
        self.rt=Runtime(self.rt.root,self.factory,connection=self.state.db);self.rt.tick('native')
        new=self.rt.task('native','reviewer')['latest'];self.assertNotEqual(new,aid)
        script=Script([check('c2'),finish()]);result,_=self.run_worker(self,new,script)
        self.assertIsNotNone(result);self.assertEqual(result['decision'],'accept')
        initial=json.loads(script.requests[0]['contents'][0]['parts'][0]['text'])
        self.assertEqual(len(initial['review_session']['provisional_records']),2)
        self.assertEqual(set(initial['review_session']['provisional_checks']),{'c1'})
        self.assertEqual(initial['review_session']['phase'],'finalize')
        self.rt.tick('native');self.assertEqual(self.rt.status('native')['status'],'completed')
        self.assertEqual(self.rt.task('native','producer')['latest'],producer)
        self.assertEqual(saved,dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()))
        self.assertEqual(self.factory.sessions[new]['frozen']['limits'],self.factory.sessions[aid]['frozen']['limits'])

    def test_missing_response_or_changed_records_prevent_continuation(self):
        p,s,producer,aid=self.prepare();control=self.stop(aid)
        task=self.rt.task('native','reviewer');attempt=self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(aid,)).fetchone()
        self.assertIsNotNone(local_review.proof(self.rt,task,attempt))
        response=control/'api-05.response.json';raw=response.read_bytes();response.unlink()
        self.assertIsNone(local_review.proof(self.rt,task,attempt));response.write_bytes(raw)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        row=self.state.db.execute('SELECT key,value FROM operation_records WHERE attempt=? LIMIT 1',(aid,)).fetchone()
        changed=json.loads(row['value']);changed['reason']='Changed after allocation'
        self.state.db.execute('UPDATE operation_records SET value=? WHERE attempt=? AND key=?',(c.encoded(changed),aid,row['key']))
        self.state.db.commit();calls=list(self.factory.calls);self.rt.tick('native')
        self.assertEqual(self.factory.calls,calls);self.assertEqual(self.rt.task('native','reviewer')['status'],'blocked')

    def test_saved_record_completion_does_not_skip_missing_report_checks(self):
        p,s,producer,aid=self.prepare();self.stop(aid)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        self.rt.tick('native');new=self.rt.task('native','reviewer')['latest']
        result,control=self.run_worker(self,new,Script([finish(),check('c2'),finish()]))
        self.assertIsNotNone(result)
        self.assertIn('error',json.loads((control/'tool-01-00.json').read_text())['result'])
        self.assertEqual(result['decision'],'accept')

    def last_cycle(self):
        p,s,producer,aid=self.prepare()
        blocked=('finish',dict(report_json=c.encoded(dict(summary='Saved first judgment',decision='blocked',instruction='Continue remaining judgments',
            findings=[dict(category='execution',code='budget',message='Yield within recorded authorization',evidence='One committed judgment')],checks={'c1':None,'c2':None}))))
        result,_=self.run_worker(self,aid,Script([self.judgment(aid),blocked]));self.assertEqual(result['decision'],'blocked')
        self.rt.tick('native')
        with transaction(self.state.db):
            for cycle in (2,3):self.state.db.execute('INSERT INTO completion_recoveries VALUES(?,?,?,?,?,?)',(p['id'],s['id'],'earlier-'+str(cycle),cycle,-cycle,c.encoded(dict(prior=cycle))))
            self.assertTrue(recovery.begin(self.state,p,s,'native'))
        self.rt.tick('native');current=self.rt.task('native','reviewer')['latest'];self.assertNotEqual(current,aid)
        self.stop(current)
        return p,s,producer,current

    def test_finalization_uses_existing_cycle_slot_without_adding_authorization(self):
        p,s,producer,aid=self.last_cycle();calls=list(self.factory.calls)
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM completion_recoveries')]
        with self.assertRaisesRegex(ValueError,'rollback'),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'native'));raise ValueError('rollback')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM local_review_invocations').fetchone()[0],0)
        self.assertEqual(self.factory.calls,calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(before,[tuple(r) for r in self.state.db.execute('SELECT * FROM completion_recoveries')])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recovery_extensions').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM local_review_invocations').fetchone()[0],1)
        self.rt.tick('native');new=self.rt.task('native','reviewer')['latest']
        result,_=self.run_worker(self,new,Script([check('c2'),finish()]));self.assertEqual(result['decision'],'accept')
        self.rt.tick('native');self.assertEqual(self.rt.status('native')['status'],'completed')

    def test_exhausted_cycle_slots_hold_without_additional_grant(self):
        p,s,producer,aid=self.last_cycle()
        from task_relay import pipelines
        with transaction(self.state.db):
            pipelines.event(self.state,p['id'],s['id'],'completion_continuations_queued',dict(parent='native',cycle=4,tasks=['earlier-'+str(n) for n in range(7)]))
            self.assertFalse(recovery.begin(self.state,p,s,'native'))
        self.assertEqual(self.rt.task('native','reviewer')['latest'],aid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM local_review_invocations').fetchone()[0],0)
