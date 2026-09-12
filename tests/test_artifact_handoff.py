import json
from pathlib import Path
import unittest

from tests import test_task_routing as fixture
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory, plan
import production_control as pc
import routing_inputs


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

if __name__=='__main__':unittest.main()
