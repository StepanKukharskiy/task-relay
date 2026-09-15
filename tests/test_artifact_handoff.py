import json
from pathlib import Path
import unittest
import time

from tests import test_task_routing as fixture
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory, plan
from task_relay import production_control as pc
from task_relay import routing_inputs
from task_relay import orchestrator_chat as chat


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    click=fixture.Tests.click

    def artifact(self, text='Exact diagnostic: SIGSEGV', blocked=True):
        fake=FakeFactory();rt=Runtime(pc.root(self.state),fake,connection=self.state.db)
        rt.create(plan());rt.tick('demo')
        attempt=rt.task('demo','produce')['latest'];fake.finish(attempt,decision='blocked' if blocked else 'delivered')
        ws=fake.sessions[attempt]['workspace'];(ws/'output.txt').write_text(text)
        rt.tick('demo')
        return dict(rt.output('demo','produce','output.txt'))

    def test_exact_blocked_report_is_frozen_with_identity_and_sent_once(self):
        a=self.artifact()
        self.request({'kind':'route_task','task_id':'t0','artifact_ids':[a['id']]},'Send this Blender report to Codex.')
        row=self.state.db.execute('select * from task_routes').fetchone()
        manifest=json.loads(row['input_manifest']);d=next(x for x in manifest if x['role']=='generated artifact')
        self.assertEqual(Path(d['path']).name,'output.txt');self.assertEqual(Path(d['path']).read_text(),'Exact diagnostic: SIGSEGV')
        self.assertEqual(d['artifact_id'],a['id']);self.assertEqual(d['attempt_state'],'blocked')
        self.worker.tick();self.worker.tick()
        self.assertEqual(len(self.calls),1);self.assertIn(d['path'],self.calls[0][1]);self.assertIn(a['sha256'],self.calls[0][1]);self.assertIn(a['attempt'],self.calls[0][1])

    def test_omitted_selection_cannot_silently_send_only_conversation(self):
        self.artifact();self.request({'kind':'route_task','task_id':'t0'},'Send this report.')
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('select count(*) from task_routes').fetchone()[0],0)

    def test_missing_or_tampered_artifact_stops_dispatch(self):
        a=self.artifact();p=Path(a['blob']);p.chmod(0o600);p.write_text('changed')
        self.request({'kind':'route_task','task_id':'t0','artifact_ids':[a['id']]})
        self.worker.tick();self.assertEqual(self.calls,[])

    def test_destination_choice_retains_selected_version(self):
        a=self.artifact();self.request({'kind':'choose_task','task_ids':['t0','t1'],'artifact_ids':[a['id']]})
        self.bridge.flush(False);self.click('1');self.worker.tick()
        self.assertEqual(self.calls[0][0],'t1');self.assertIn(a['sha256'],self.calls[0][1])

    def test_explicit_empty_selection_routes_without_generated_files(self):
        self.artifact();self.request({'kind':'route_task','task_id':'t0','artifact_ids':[]},'Unrelated code question.')
        self.worker.tick();self.assertEqual(len(self.calls),1);self.assertNotIn('generated artifact',self.calls[0][1])

    def corrected_request(self, first, second, prompt='Let’s continue with O13 then'):
        with self.state.db:
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,provider,model,created) VALUES (?,?,?,?,?)',
                                  (92,prompt,'gemini','fixture',time.time()))
        payloads=[]
        def generate(job,payload):
            payloads.append(payload)
            return json.dumps({'answer':'Choose or queue the requested work.','action':first if len(payloads)==1 else second})
        worker=chat.Worker(self.state,generate)
        worker.tick();worker.tick()
        return payloads

    def test_missing_source_field_is_corrected_without_attaching_unrelated_outputs(self):
        self.artifact()
        original='We need a desktop launcher for Task Relay installation and setup.'
        self.request(None,original)
        action={'kind':'route_task','task_id':'t0','research_ids':[]}
        payloads=self.corrected_request(action,{**action,'artifact_ids':[]})
        self.assertEqual(len(payloads),2)
        self.assertEqual(payloads[1]['user_message'],'Let’s continue with O13 then')
        self.assertEqual(payloads[1]['routing_source_correction']['missing_fields'],['artifact_ids'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],1)
        self.worker.tick();self.worker.tick()
        self.assertEqual(len(self.calls),1)
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone()
        inputs=json.loads(row['input_manifest'])
        self.assertNotIn('generated artifact',[d['role'] for d in inputs])
        conversation=next(d for d in inputs if d['name']=='conversation.json')
        self.assertIn(original,Path(conversation['path']).read_text())
        self.assertIn('Let’s continue with O13 then',self.calls[0][1])
        receipt=self.state.get('orchestrator-source-correction:92')
        self.assertEqual(json.loads(receipt['response'])['action'],action)

    def test_corrected_choice_keeps_exact_artifact_and_waits_for_destination(self):
        a=self.artifact()
        action={'kind':'choose_task','task_ids':['t0','t1']}
        self.corrected_request(action,{**action,'artifact_ids':[a['id']]},'Send this report to a Codex task.')
        self.worker.tick();self.assertEqual(self.calls,[])
        self.bridge.flush(False);self.click('1');self.worker.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][0],'t1');self.assertIn(a['sha256'],self.calls[0][1])

    def test_shared_delegate_corrects_source_selection(self):
        self.artifact()
        action={'kind':'delegate_task','task_id':'t0','provider':'codex','required_capabilities':['file_read']}
        self.corrected_request(action,{**action,'artifact_ids':[]})
        self.worker.tick();self.assertEqual(len(self.calls),1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],1)

    def test_unresolved_sources_ask_without_exposing_schema_or_looping(self):
        self.artifact()
        action={'kind':'route_task','task_id':'t0'}
        payloads=self.corrected_request(action,action,'Send the report to Codex.')
        self.assertEqual(len(payloads),2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)
        reply=self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=92').fetchone()[0]
        self.assertIn('Which files',reply);self.assertNotIn('artifact_ids',reply)

    def test_source_correction_cannot_change_destination(self):
        self.artifact()
        action={'kind':'route_task','task_id':'t0'}
        self.corrected_request(action,{'kind':'route_task','task_id':'t1','artifact_ids':[]})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=92').fetchone()[0],'failed')

    def test_source_correction_can_return_a_question_without_dispatch(self):
        self.artifact()
        self.corrected_request({'kind':'route_task','task_id':'t0'},None)
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=92').fetchone()[0],'answered')

    def test_invalid_artifact_in_correction_never_dispatches_or_retries(self):
        self.artifact()
        action={'kind':'route_task','task_id':'t0'}
        payloads=self.corrected_request(action,{**action,'artifact_ids':['invented']})
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(len(payloads),2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)

    def test_interrupted_correction_preserves_receipt_without_replaying(self):
        self.artifact()
        with self.state.db:
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,provider,model,created) VALUES (?,?,?,?,?)',
                                  (92,'Continue with O13','gemini','fixture',time.time()))
        calls=[]
        def generate(job,payload):
            calls.append(payload)
            if len(calls)==2:raise KeyboardInterrupt('fixture interruption')
            return json.dumps({'answer':'Route work','action':{'kind':'route_task','task_id':'t0'}})
        with self.assertRaises(KeyboardInterrupt):chat.Worker(self.state,generate).tick()
        self.assertIsNotNone(self.state.get('orchestrator-source-correction:92'))
        chat.Worker(self.state,generate).tick()
        self.assertEqual(len(calls),2)
        self.assertEqual(self.state.db.execute('SELECT status FROM orchestrator_chats WHERE id=92').fetchone()[0],'uncertain')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)

if __name__=='__main__':unittest.main()
