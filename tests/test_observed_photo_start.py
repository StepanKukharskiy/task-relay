"""Evidence-only Start checks preserve unknown replies and exact reviewed inputs."""
import copy,json,unittest
from types import SimpleNamespace
from orchestrator.runtime import Runtime
from orchestrator.browser_review_inputs import saved_manifest
from task_relay.completion_recovery import check_observed_photos
from tests import test_saved_photo_evidence as fixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp

    def prepare(self):
        self.state=SimpleNamespace(db=self.db,media_dir=self.root.resolve()/'media')
        rt=Runtime(self.root.resolve()/'orchestrator',connection=self.db)
        old=dict(tasks=[dict(id='merge',execution={'capability':'images.merge'},inputs=[dict(artifact='complete-base')])])
        self.db.execute('INSERT INTO production_runs VALUES (?,?,?)',('original',json.dumps(old),'active'))
        for ident,state,frozen,receipt in (
                ('stopped','uncertain',self.attempt['frozen'],self.attempt['receipt']),
                ('fetch-a','completed','{}',json.dumps({'status':'finished'})),
                ('review-a','completed',json.dumps({'review_target':'fetch-a'}),json.dumps({'status':'finished'}))):
            self.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ident,'original',ident,ident,state,None,frozen,'{}',receipt,None))
        for ident,spec in (('fetch-a',dict(id='fetch-a')),('review-a',dict(id='review-a',review_of='fetch-a'))):
            self.db.execute('INSERT INTO production_assignments VALUES (?,?,?,?,?)',(ident,'original',ident,1,json.dumps(spec)))
            self.db.execute('INSERT INTO production_tasks(run,id,status,assignment,attempts,latest) VALUES (?,?,?,?,?,?)',('original',ident,'completed',ident,1,ident))
        zipfile=self.root/'reviewed.zip';zipfile.write_bytes(b'small text fixture for exact artifact identity')
        source=rt.artifact(rt.register(zipfile.resolve(),'Reviewed branch',run='original',task='fetch-a',attempt='fetch-a',path='photos.zip'))
        manifest=rt.register((self.root/'sources.json').resolve(),'Exact observed manifest')
        attempt=dict(self.db.execute("SELECT * FROM production_attempts WHERE id='stopped'").fetchone())
        _,_,proof=saved_manifest(self.db,attempt)
        baseline=dict(run='original',plan=old,attempts=[dict(a) for a in self.db.execute("SELECT * FROM production_attempts WHERE run='original' ORDER BY id")],
                      gaps=[dict(kind='observed_public_photo',attempt='stopped',proof=proof)],artifacts=[source])
        plan=dict(tasks=[dict(id='fetch-b',execution={'capability':'images.fetch'},inputs=[dict(artifact=manifest)]),
                         dict(id='review-b',review_of='fetch-b'),
                         dict(id='merge',execution={'capability':'images.merge'},inputs=[dict(artifact='complete-base'),dict(artifact=source['id'])]),
                         dict(id='review-merge',review_of='merge')],deliverables={'photos':dict(task='merge')})
        return dict(parent='observed-photo:stopped'),baseline,plan

    def test_start_accepts_only_exact_stopped_evidence_without_resolving_request(self):
        receipt,baseline,plan=self.prepare()
        before=copy.deepcopy(baseline['attempts'])
        check_observed_photos(self.state,receipt,baseline,plan)
        self.assertEqual(before,[dict(a) for a in self.db.execute("SELECT * FROM production_attempts WHERE run='original' ORDER BY id")])
        self.assertEqual(json.loads(before[-1]['receipt'])['pending_requests'],['api-2'])

    def test_changed_attempt_or_review_target_holds_start(self):
        receipt,baseline,plan=self.prepare()
        self.db.execute("UPDATE production_attempts SET receipt='{}' WHERE id='stopped'")
        with self.assertRaisesRegex(ValueError,'stopped attempts'):check_observed_photos(self.state,receipt,baseline,plan)
        self.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(baseline['attempts'][-1]['receipt'],'stopped'))
        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE id='review-a'")
        with self.assertRaisesRegex(ValueError,'independent ZIP review'):check_observed_photos(self.state,receipt,baseline,plan)

    def test_replay_or_wrong_manifest_or_wrong_complete_base_stays_held(self):
        receipt,baseline,plan=self.prepare()
        bad=copy.deepcopy(plan);bad['tasks'][0]['browser']={'profile':'public'}
        with self.assertRaisesRegex(ValueError,'replay'):check_observed_photos(self.state,receipt,baseline,bad)
        bad=copy.deepcopy(plan);bad['tasks'][0]['inputs'][0]['artifact']=baseline['artifacts'][0]['id']
        with self.assertRaisesRegex(ValueError,'manifest bytes'):check_observed_photos(self.state,receipt,baseline,bad)
        bad=copy.deepcopy(plan);bad['tasks'][2]['inputs'][0]['artifact']='different-base'
        with self.assertRaisesRegex(ValueError,'complete base'):check_observed_photos(self.state,receipt,baseline,bad)
