"""Native partial download automatically reaches the existing recovery queue."""
import copy
import json
import unittest
from unittest.mock import patch
from orchestrator.adapters import ExecutionFactory
from orchestrator.storage import transaction
from orchestrator import browser_images
from task_relay import pipelines as pipe,completion_recovery as recovery
from tests import test_delivery_completion as fixtures
from tests.test_mixed_execution import LocalRegistered,Client,operation
from tests.test_orchestrator import pair,task
from tests.test_image_sources import photo,subject

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    stage=fixtures.Tests.stage
    step=fixtures.Tests.step
    create=fixtures.Tests.create
    action=fixtures.Tests.action

    def test_registered_merge_executes_and_independent_review_consumes_exact_zip(self):
        from tests.test_photo_recovery import bundle
        from orchestrator.image_sources import unpack
        inputs=[]
        for index,raw in enumerate((bundle(['one','two'],['one']),bundle(['two'],['two']))):
            path=self.rt.root/('photos-'+str(index)+'.zip');path.write_bytes(raw)
            aid=self.rt.register(path,'Exact source/recovery ZIP')
            inputs.append(dict(artifact=aid,path=path.name,purpose='Exact ZIP',authority='Unaccepted source bytes',media_type='application/zip'))
        merge=operation('merge','images.merge',inputs);merge['outputs']=[dict(path='merged.zip',purpose='Recovered ZIP',media_type='application/zip')]
        review=task('review',review_of='merge',dependencies=['merge'],inputs=[dict(from_task='merge',output='merged.zip',path='merged.zip',purpose='Inspect exact recovered ZIP',authority='Unaccepted candidate',media_type='application/zip')]);review['criteria']=merge['criteria']
        graph=pair();graph.update(id='merge-fixture',tasks=[merge,review])
        native=LocalRegistered(Client());self.rt.factory=ExecutionFactory(self.factory,native);self.rt.create(graph)
        self.rt.tick('merge-fixture');self.rt.tick('merge-fixture')
        rid=self.rt.task('merge-fixture','review')['latest'];self.assertIsNotNone(rid)
        frozen=self.factory.sessions[rid]['frozen'];source=self.rt.output('merge-fixture','merge','merged.zip')
        self.assertEqual(frozen['inputs'][0]['artifact'],source['id'])
        from pathlib import Path
        self.assertTrue(unpack(Path(source['blob']).read_bytes())[2]['complete'])
        self.factory.finish(rid,decision='accept');self.rt.tick('merge-fixture')
        self.assertEqual(self.rt.status('merge-fixture')['status'],'completed');self.assertEqual(len(native.calls),1)

    def test_partial_native_photo_zip_queues_missing_subject_recovery_without_acceptance(self):
        self.photo_case()

    def test_all_failed_confirmed_downloads_recover_from_preserved_diagnostic_zip(self):
        self.photo_case(all_failed=True)

    def test_explicit_target_photo_policy_advances_reviewed_partial_zip(self):
        self.photo_case(target=True)

    def photo_case(self,all_failed=False,target=False):
        action=self.action();first=action['stages'][0];first['capabilities']=['images.fetch']
        first['handoff']['outputs']['outline']['media_type']='application/zip'
        if target:
            action['completion']['photos']=dict(stage='outline',output='outline',count_policy='target')
            action['stages'][-1]['handoff']['inputs']=[dict(stage='outline',deliverable='outline',consumer='context',media_type='application/zip')]
        p=self.create(action=action)
        manifest=dict(schema=browser_images.SCHEMA,job='observed-fixture',subjects=[subject('one'),subject('two')],candidates=[dict(subject=i,download_url='https://images.example/'+i+'.jpg',source_url='https://store.example/'+i,observed_url='https://store.example/'+i,observation='observation-'+i,action_id='action-'+i,title='Observed photo') for i in ('one','two')])
        path=self.rt.root/'manifest.json';path.write_text(json.dumps(manifest));aid=self.rt.register(path,'Exact observed-source fixture')
        fetch=operation('photos','images.fetch',[dict(artifact=aid,path='manifest.json',purpose='Observed URLs',authority='Untrusted source data',media_type='application/json')])
        fetch['outputs']=[dict(path='photos.zip',purpose='Photo ZIP',media_type='application/zip')]
        review=task('review',review_of='photos',dependencies=['photos'],inputs=[dict(from_task='photos',output='photos.zip',path='photos.zip',purpose='Independent source identity review',authority='Unaccepted photo candidates',media_type='application/zip')])
        review['criteria']=fetch['criteria']
        graph=pair();graph.update(id='photo-fixture',tasks=[fetch,review],deliverables={'outline':dict(task='photos',output='photos.zip',description='Reviewed ZIP')})
        self.rt.create(graph)
        with transaction(self.state.db):self.state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='production_run',target='photo-fixture' WHERE pipeline=? AND id='outline'",(p['id'],))
        native=LocalRegistered(Client());self.rt.factory=ExecutionFactory(self.factory,native)
        original=browser_images.fetch_bundle
        def get(url,*_):
            if all_failed or 'two.jpg' in url:raise ValueError('Confirmed HTTP 403 fixture')
            return photo(),'image/jpeg',url
        with patch.object(browser_images,'fetch_bundle',side_effect=lambda value,**kwargs:original(value,fetch=get,**kwargs)):
            self.rt.tick('photo-fixture');self.rt.tick('photo-fixture')
        rid=self.rt.task('photo-fixture','review')['latest']
        if rid:self.factory.finish(rid,decision='accept');self.rt.tick('photo-fixture')
        self.assertEqual(self.rt.status('photo-fixture')['status'],'blocked' if all_failed else 'completed')
        pipe.tick(self.state)
        receipt=self.state.db.execute('SELECT * FROM completion_recoveries WHERE parent=?',('photo-fixture',)).fetchone()
        if target:
            self.assertIsNone(receipt)
            self.assertEqual(self.step(p,'outline')['status'],'completed',self.step(p,'outline')['error'])
            pipe.tick(self.state)
            self.assertNotEqual(self.step(p,'finish')['status'],'pending')
            self.assertIsNotNone(self.rt.db.execute("SELECT 1 FROM production_events WHERE run='photo-fixture' AND kind='delivery_photo_gap'").fetchone())
            self.assertEqual(len(native.calls),1)
            return
        self.assertIsNotNone(receipt,self.step(p,'outline')['error'])
        baseline=json.loads(receipt['baseline']);gap=baseline['gaps'][0]
        self.assertEqual(gap['kind'],'photo_download_failed' if all_failed else 'delivery_photos')
        self.assertEqual(gap['missing'],['one','two'] if all_failed else ['two'])
        self.assertEqual(self.step(p,'finish')['status'],'pending')
        self.assertEqual(len(native.calls),1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        self.assertIsNone(recovery.snapshot(self.state,'photo-fixture')) # legacy excludes image effects
        self.assertIsNotNone(recovery.snapshot(self.state,'photo-fixture',photo_recovery=True))
        with transaction(self.state.db):
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(dict(status='finished',pending_requests=['unknown'])),rid or self.rt.task('photo-fixture','photos')['latest']))
        self.assertIsNone(recovery.snapshot(self.state,'photo-fixture',photo_recovery=True))
