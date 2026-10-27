"""Synthetic observed manifest export; unknown model replies are never replayed."""
import copy,hashlib,json,tempfile,unittest,sqlite3
from pathlib import Path
from orchestrator.browser_review_inputs import saved_manifest
from orchestrator import browser_images
from task_relay.browser_journal import Journal
from tests.test_image_sources import subject


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        Journal(self.db)
        value=dict(schema=browser_images.SCHEMA,job='stopped',subjects=[subject('one')],candidates=[dict(
            subject='one',download_url='https://images.example/one.jpg',source_url='https://store.example/one',
            observed_url='https://store.example/one',observation='obs',action_id='read',title='Observed fixture')])
        self.raw=json.dumps(value).encode();(self.root/'sources.json').write_bytes(self.raw)
        frozen=dict(assignment_id='stopped',workspace=str(self.root),browser=dict(profile='public',max_actions=3,
            interaction_scope='Read only: public photo pages. No accounts.',uploads=[],downloads=[],
            image_sources=[dict(path='sources.json',subjects=value['subjects'])]))
        receipt=dict(status='uncertain',local_terminal=True,finished=5,external_outcome='unknown',pending_requests=['api-2'],browser=dict(uncertain_actions=[]))
        self.attempt=dict(id='stopped',state='uncertain',frozen=json.dumps(frozen),receipt=json.dumps(receipt))
        for ident,name,result in (('read','browser_read',dict(observation='obs')),('export','browser_image_source',dict(path='sources.json',sha256=hashlib.sha256(self.raw).hexdigest()))):
            self.db.execute('INSERT INTO general_browser_actions VALUES (?,?,?,?,?,?,?)',('stopped',ident,'public',json.dumps(dict(name=name)), 'observed',json.dumps(result),1 if ident=='read' else 2))

    def test_exact_observation_survives_unknown_provider_without_acceptance_or_dispatch(self):
        before=copy.deepcopy(self.attempt);raw,pack,proof=saved_manifest(self.db,self.attempt)
        self.assertEqual(raw,self.raw);self.assertEqual(self.attempt,before)
        self.assertEqual(proof['pending_requests'],['api-2']);self.assertEqual(proof['provider_outcome'],'unknown')
        self.assertFalse(proof['worker_accepted']);self.assertFalse(proof['provider_replayed'])
        self.assertEqual(len(pack['actions']),2)

    def test_unresolved_browser_action_or_changed_bytes_cannot_be_reused(self):
        self.db.execute("UPDATE general_browser_actions SET status='uncertain' WHERE id='read'")
        with self.assertRaisesRegex(ValueError,'unresolved'):saved_manifest(self.db,self.attempt)
        self.db.execute("UPDATE general_browser_actions SET status='observed' WHERE id='read'")
        (self.root/'sources.json').write_bytes(self.raw+b' ')
        with self.assertRaisesRegex(ValueError,'hash'):saved_manifest(self.db,self.attempt)

    def test_active_worker_account_scope_and_foreign_subjects_stay_held(self):
        for key in ('local_terminal','finished'):
            a=copy.deepcopy(self.attempt);r=json.loads(a['receipt']);r.pop(key);a['receipt']=json.dumps(r)
            with self.assertRaises(ValueError):saved_manifest(self.db,a)
        a=copy.deepcopy(self.attempt);f=json.loads(a['frozen']);f['browser']['interaction_scope']='Use a signed-in account';a['frozen']=json.dumps(f)
        with self.assertRaises(ValueError):saved_manifest(self.db,a)
