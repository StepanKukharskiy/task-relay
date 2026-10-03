"""Raw-source handoff and no-effect completion gates; no browser/provider."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import contracts
from orchestrator.gemini_worker import Files
from orchestrator.runtime import Runtime
from orchestrator.computer_review_inputs import review_input
from task_relay import computer_sessions as journal
from task_relay.computer_worker_session import Session
from tests.test_orchestrator import FakeFactory
from tests.test_gemini_executor import graph,report
from tests.test_computer_worker import policy,DynamicHelper
from tests.test_computer_sessions import SessionHelper


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.factory=FakeFactory();self.rt=Runtime(Path(self.tmp.name)/'runtime',self.factory)
        self.addCleanup(self.rt.db.close)
        p=graph();p['tasks'][0].update(tools=['files','computer'],computer=policy(),worker={'version':1,'requires':['files.text','computer.use'],'executor':'gemini-computer','backend':{'type':'gemini-computer','model':'fixture-model'}})
        self.rt.create(p);self.rt.tick('demo')
        self.aid=self.rt.task('demo','produce')['latest'];self.frozen=self.factory.sessions[self.aid]['frozen']
        self.db=self.rt.db
        self.db.execute('CREATE TABLE relay_pipelines(id TEXT PRIMARY KEY)')
        self.db.execute("INSERT INTO relay_pipelines VALUES ('job')")
        journal.initialize(self.db)
        self.ident=journal.approve(self.db,job='job',request_key='worker:'+self.aid,
            exact_request=self.frozen['instruction'],spec=policy()['spec'],helper=SessionHelper.identity,
            output_root=self.rt.root/'workers'/self.aid/'computer-evidence',actor='fixture')

    def capture(self,gap=False):
        helper=DynamicHelper(self.db) if gap else SessionHelper(self.db)
        session=Session(self.db,self.ident,helper,self.rt.root/'workers'/self.aid,'fixture')
        session.call('initial','computer_observe',{'token':''})
        if gap:session.call('navigate','computer_navigate',{'token':session.token,'url':'https://example.com/two'})
        session.close(True)
        return session

    def deliver(self):
        self.factory.finish(self.aid);self.rt.tick('demo',dispatch=False)

    def test_exact_raw_text_and_receipts_reach_reviewer_and_source_pack(self):
        self.capture();self.deliver()
        self.rt.tick('demo');rid=self.rt.task('demo','review')['latest']
        self.assertIsNotNone(rid)
        frozen=self.factory.sessions[rid]['frozen'];binding=frozen['computer_review']
        self.assertEqual(binding['producer_attempt'],self.aid)
        files=Files(frozen);pack=files.source_pack()
        source=next(f for f in pack['files'] if f['path']==binding['path'])
        raw=json.loads(source['text'])
        self.assertEqual(raw['observations'][0]['text'],'Synthetic supplier catalog issue.')
        self.assertEqual(raw['observations'][0]['observation'],journal.actions(self.db,self.ident)[0]['id'])
        self.assertEqual(source['sha256'],binding['sha256'])
        self.assertFalse((Path(frozen['workspace'])/binding['path']).stat().st_mode&0o222)
        self.assertEqual(raw['unexecuted_actions'],[])
        self.assertEqual(len(self.factory.calls),2)
        from orchestrator.gemini_worker import execute
        from orchestrator import executors
        from orchestrator.workers import atomic
        from tests.test_gemini_executor import Scripted,CONFIG
        control=self.rt.root/'workers'/rid;control.mkdir(parents=True)
        atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(CONFIG,frozen['backend'])})
        model=Scripted(frozen)
        result=execute(frozen,control,model,lambda:(CONFIG,frozen['backend']))
        self.assertEqual(result['decision'],'accept')
        payload=model.calls[0]
        self.assertIn('raw Safari captures',payload['systemInstruction']['parts'][0]['text'])
        initial=json.loads(payload['contents'][0]['parts'][0]['text'])
        self.assertIn(binding['path'],[f['path'] for f in initial['source_pack']['files']])

    def test_tampered_raw_capture_blocks_before_reviewer_attempt_or_dispatch(self):
        self.capture();self.deliver()
        a=journal.actions(self.db,self.ident)[0];p=Path(json.loads(a['receipt'])['folder'])/'page.txt'
        p.chmod(0o600);p.write_text('Changed source')
        self.rt.tick('demo')
        task=self.rt.task('demo','review')
        self.assertEqual((task['status'],task['attempts'],task['latest']),('blocked',0,None))
        self.assertEqual(self.factory.calls,[self.aid])

    def test_missing_native_binding_cannot_fall_back_to_producer_json(self):
        self.capture();self.deliver()
        self.db.execute("UPDATE relay_computer_assignments SET request_key='different-attempt' WHERE id=?",(self.ident,))
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')

    def test_supervisor_rejects_successful_report_with_unexecuted_action(self):
        self.capture(gap=True);self.deliver()
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertIsNone(self.rt.task('demo','review')['latest'])
        self.assertIn('unexecuted',self.db.execute('SELECT error FROM production_attempts WHERE id=?',(self.aid,)).fetchone()[0])

    def test_legacy_completed_attempt_gaps_are_visible_and_cannot_be_accepted(self):
        self.capture(gap=True)
        # Legacy delivered work can still be inspected; do not edit its receipts.
        spec=self.rt.spec(self.rt.task('demo','review'))
        before=[a['receipt'] for a in journal.actions(self.db,self.ident)]
        with self.rt.transaction():item=review_input(self.rt,'demo',spec)
        self.assertEqual(item['native_evidence']['unexecuted_actions'][0]['operation'],'navigate')
        frozen={**spec,'assignment_id':'review-fixture','computer_review':item['native_evidence']}
        with self.assertRaisesRegex(ValueError,'unexecuted'):contracts.report(report(frozen),frozen)
        r=report(frozen);r.update(decision='revise',instruction='Complete the unexecuted navigation.')
        self.assertEqual(contracts.report(r,frozen)['decision'],'revise')
        self.assertEqual(before,[a['receipt'] for a in journal.actions(self.db,self.ident)])

    def test_partial_raw_pack_must_be_read_before_review_acceptance(self):
        self.capture();self.deliver();self.rt.tick('demo')
        frozen=self.factory.sessions[self.rt.task('demo','review')['latest']]['frozen'];files=Files(frozen)
        files.source_pack(max_bytes=1)
        for path in files.inputs:
            if path!=frozen['computer_review']['path']:
                raw=files.read_bytes(path);files.observe(path,0,len(raw.decode()),raw)
        with self.assertRaisesRegex(ValueError,'complete exact candidate'):files.validate_text_delivery(report(frozen))
        path=frozen['computer_review']['path'];raw=files.read_bytes(path);files.observe(path,0,len(raw.decode()),raw)
        files.validate_text_delivery(report(frozen))

    def test_repeated_preflight_preserves_one_registered_pack(self):
        self.capture();spec=self.rt.spec(self.rt.task('demo','review'))
        with self.rt.transaction():
            one=review_input(self.rt,'demo',spec);two=review_input(self.rt,'demo',spec)
        self.assertEqual(one['artifact'],two['artifact'])
