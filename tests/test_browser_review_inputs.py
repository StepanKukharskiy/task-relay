"""Exact browser journal handoff, without providers, media or live browser work."""
import json
import tempfile
import unittest
from pathlib import Path
from orchestrator.runtime import Runtime
from orchestrator.browser_review_inputs import review_input
from task_relay.browser_journal import Journal
from tests.test_orchestrator import FakeFactory
from tests.test_gemini_executor import graph

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.factory=FakeFactory();self.rt=Runtime(Path(self.tmp.name)/'runtime',self.factory)
        self.addCleanup(self.rt.db.close)
        self.rt.create(graph());self.rt.tick('demo')
        self.aid=self.rt.task('demo','produce')['latest']
        row=self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(self.aid,)).fetchone()
        frozen=json.loads(row['frozen']);frozen['browser']={'profile':'fixture-public','max_actions':4}
        self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),self.aid))
        self.journal=Journal(self.rt.db)
        self.factory.finish(self.aid);self.rt.tick('demo',dispatch=False)
        self.spec=self.rt.spec(self.rt.task('demo','review'))

    def record(self,status='observed',profile='fixture-public'):
        self.rt.db.execute('INSERT INTO general_browser_actions VALUES (?,?,?,?,?,?,?)',
            (self.aid,'read-1',profile,json.dumps({'name':'browser_read','arguments':{'tab':'one'}}),status,
             json.dumps({'observation':'observed-1','url':'https://example.com/item','text':'Synthetic item: $25, width 20 inches.'}),1))

    def test_exact_records_reach_readonly_reviewer_input(self):
        self.record();self.rt.tick('demo')
        rid=self.rt.task('demo','review')['latest'];self.assertIsNotNone(rid)
        frozen=self.factory.sessions[rid]['frozen']
        item=next(i for i in frozen['inputs'] if i['path'].startswith('browser-evidence/'))
        target=Path(frozen['workspace'])/item['path'];pack=json.loads(target.read_text())
        self.assertEqual(pack['producer_attempt'],self.aid)
        self.assertEqual(pack['actions'][0]['result']['observation'],'observed-1')
        self.assertEqual(pack['actions'][0]['result']['text'],'Synthetic item: $25, width 20 inches.')
        self.assertFalse(target.stat().st_mode&0o222)

    def test_missing_history_blocks_before_review_dispatch(self):
        self.rt.tick('demo');task=self.rt.task('demo','review')
        self.assertEqual((task['status'],task['attempts']),('blocked',0))
        self.assertEqual(self.factory.calls,[self.aid])

    def test_unresolved_action_blocks_without_replay(self):
        self.record(status='uncertain');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.assertEqual(self.rt.db.execute('SELECT status FROM general_browser_actions').fetchone()[0],'uncertain')

    def test_wrong_profile_cannot_substantiate_producer(self):
        self.record(profile='different');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')

    def test_repeated_preflight_preserves_one_exact_artifact(self):
        self.record()
        with self.rt.transaction():
            first=review_input(self.rt,'demo',self.spec);second=review_input(self.rt,'demo',self.spec)
        self.assertEqual(first['artifact'],second['artifact'])
        blob=first['blob'];blob.chmod(0o600);blob.write_text('changed')
        with self.rt.transaction(),self.assertRaisesRegex(ValueError,'changed'):
            review_input(self.rt,'demo',self.spec)
