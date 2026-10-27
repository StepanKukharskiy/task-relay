"""Controlled artifact correction, restart, receipt reuse and tamper checks."""
import hashlib
import io
import json
import subprocess
import sys
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import image_sources,product_photos,contracts as c
from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery,registered_revision
from tests.test_photo_projection import Tests as ProjectionFixture
from tests.test_photo_recovery import bundle


class Tests(unittest.TestCase):
    def stopped(self):
        helper=ProjectionFixture();helper.setUp();self.addCleanup(helper.doCleanups)
        f,p,s,aid,_=helper.stopped_graph(rejected=True)
        row=f.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(aid,)).fetchone()
        frozen=json.loads(row[0]);frozen['runtime_sources']['product_photos.py']=hashlib.sha256(Path(product_photos.__file__).read_bytes()).hexdigest()
        f.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(c.encoded(frozen),aid));f.state.db.commit()
        return f,p,s,aid

    def test_projection_preserves_extra_native_review_criteria(self):
        f,p,s,aid=self.stopped();baseline=recovery.snapshot(f.state,'parent',photo_recovery=True)
        evidence=registered_revision.proof(f.rt,baseline)
        # Native output validation adds independent checks beyond base criteria.
        baseline['plan']['tasks'][1]['criteria'].append('Retain every observed source identity')
        result=registered_revision.graph(baseline,dict(cycle=1,baseline=c.encoded(baseline)),evidence)
        self.assertIn('Retain every observed source identity',result['tasks'][0]['criteria'])
        self.assertEqual(result['tasks'][0]['criteria'],result['tasks'][1]['criteria'])

    def test_projection_keeps_valid_bytes_and_all_rejected_provenance(self):
        raw=bundle(['one','two','three'],['one','two'])
        projected=image_sources.revise_bundle(raw,{'two':'Independent review: wrong subject'})
        contract=dict(version=2,base_sha256=hashlib.sha256(raw).hexdigest())
        image_sources.validate_revision(raw,projected,contract)
        images,_,manifest=image_sources.unpack(projected);old_images,_,old=image_sources.unpack(raw)
        self.assertEqual(images,{'images/one.jpg':old_images['images/one.jpg']})
        self.assertEqual(manifest['subjects'][1]['rejected_evidence'],old['subjects'][1])
        self.assertEqual(manifest['subjects'][2],old['subjects'][2])
        self.assertEqual(manifest['coverage'],dict(found=1,missing=2,total=3))
        with zipfile.ZipFile(io.BytesIO(raw)) as before,zipfile.ZipFile(io.BytesIO(projected)) as after:
            self.assertEqual(set(before.namelist()),set(after.namelist()))
            for name in before.namelist():
                if name!='manifest.json':self.assertEqual(before.read(name),after.read(name))
        # Changing a product association cannot pass by keeping valid pixels.
        manifest['subjects'][0]['label']='Another product'
        tampered=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(projected)) as before,zipfile.ZipFile(tampered,'w') as after:
            for name in before.namelist():after.writestr(name,json.dumps(manifest) if name=='manifest.json' else before.read(name))
        with self.assertRaisesRegex(ValueError,'retained evidence'):
            image_sources.validate_revision(raw,tampered.getvalue(),contract)
        for invalid in ({},{'three':'No found image'},{'two':''}):
            with self.assertRaises(ValueError):image_sources.revise_bundle(raw,invalid)

    def test_historical_projection_repairs_bytes_without_restoring_usability(self):
        raw=bundle(['one','two'],['one','two']);decisions={'two':'Wrong subject'}
        old=image_sources.revise_bundle(raw,decisions,version=1)
        contract=dict(version=1,base_sha256=hashlib.sha256(raw).hexdigest())
        new_contract=image_sources.repair_revision(raw,old,contract)
        repaired=image_sources.revise_bundle(raw,decisions)
        image_sources.validate_revision(raw,repaired,new_contract)
        self.assertEqual(set(image_sources.unpack(repaired)[0]),{'images/one.jpg'})
        with zipfile.ZipFile(io.BytesIO(repaired)) as archive:self.assertIn('images/two.jpg',archive.namelist())
        changed=image_sources.revise_bundle(raw,{'one':'Different selection'})
        with self.assertRaisesRegex(ValueError,'changed rejection decisions'):
            image_sources.validate_revision(raw,changed,new_contract)
        # New-format archives cannot claim retained evidence while omitting it.
        damaged=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(repaired)) as before,zipfile.ZipFile(damaged,'w') as after:
            for name in before.namelist():
                if name!='images/two.jpg':after.writestr(name,before.read(name))
        with self.assertRaises(ValueError):image_sources.unpack(damaged.getvalue())

    def test_quarantined_originals_are_validated_but_never_exposed_to_slides(self):
        from tests.test_webp_photo_conversion import photo,manifest,rewrite
        from orchestrator import browser_images
        original=photo()
        raw,_=browser_images.fetch_bundle(manifest(),fetch=lambda *args:(original,'image/webp','https://example.com/chair.webp'))
        projected=image_sources.revise_bundle(raw,{'chair-a':'Wrong product'})
        with zipfile.ZipFile(io.BytesIO(projected)) as archive:
            self.assertEqual(archive.read('originals/chair-a.webp'),original)
            self.assertIn('images/chair-a.png',archive.namelist())
        document={'slides':[]}
        _,images=image_sources.presentation_inputs(document,{}, {'photos':projected})
        self.assertEqual(images,{})
        bad=rewrite(projected,lambda files,m:files.__setitem__('originals/chair-a.webp',b'changed'))
        with self.assertRaisesRegex(ValueError,'Source-original hash'):image_sources.unpack(bad)

    def test_rejected_projection_uses_registered_repair_after_restart(self):
        f,p,s,aid=self.stopped()
        admit=image_sources.revision_contract
        def legacy(*args):return {**admit(*args),'version':1}
        with patch.object(image_sources,'revision_contract',side_effect=legacy):
            with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
            first=f.step(p,'outline')['target'];f.rt.tick(first)
            author=f.rt.task(first,'produce')['latest'];session=f.factory.sessions[author]
            raw=(session['workspace']/'revision-base/photos.zip').read_bytes();subject=image_sources.unpack(raw)[2]['subjects'][0]['id']
            f.factory.finish(author);(session['workspace']/'photos.zip').write_bytes(image_sources.revise_bundle(raw,{subject:'Wrong subject'},version=1))
            f.rt.tick(first);f.rt.tick(first);rid=f.rt.task(first,'review')['latest']
            f.factory.finish(rid,decision='revise');report_path=f.factory.sessions[rid]['workspace']/'.relay/result.json'
            report=json.loads(report_path.read_text());report['findings']=[dict(category='integrity',code='missing_audit_bytes',message='Restore retained evidence bytes',evidence='Exact old archive members missing')]
            report_path.write_text(json.dumps(report));f.rt.tick(first)
        before=[dict(r) for r in f.state.db.execute('SELECT * FROM production_attempts ORDER BY id')]
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,f.step(p,'outline'),first))
        second=f.step(p,'outline')['target'];self.assertNotEqual(second,first);self.assertTrue(second.startswith('evidence-revision-'))
        self.assertEqual(before,[dict(r) for r in f.state.db.execute('SELECT * FROM production_attempts ORDER BY id')])
        from orchestrator.runtime import Runtime
        rt=Runtime(f.rt.root,connection=f.state.db,factory=f.factory);rt.tick(second)
        new=rt.task(second,'produce')['latest'];self.assertIsNotNone(new)
        session=f.factory.sessions[new];f.factory.finish(new)
        (session['workspace']/'rejections.json').write_text(json.dumps({subject:'Wrong subject'}))
        subprocess.run([sys.executable,'-B','.relay/revise-evidence.py','rejections.json','photos.zip'],cwd=session['workspace'],check=True,capture_output=True)
        output=(session['workspace']/'photos.zip').read_bytes()
        self.assertEqual(image_sources.unpack(output)[0],{})
        with zipfile.ZipFile(io.BytesIO(output)) as archive:self.assertGreater(len(archive.namelist()),1)
        rt.tick(second);rt.tick(second);review=rt.task(second,'review')['latest'];self.assertIsNotNone(review)
        f.factory.finish(review,decision='accept');self.assertEqual(rt.tick(second)['status'],'completed')
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)

    def test_local_projection_survives_restart_and_requires_new_independent_review(self):
        f,p,s,aid=self.stopped();prior=[dict(r) for r in f.state.db.execute('SELECT * FROM production_attempts ORDER BY id')]
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        target=f.step(p,'outline')['target'];self.assertTrue(target.startswith('evidence-revision-'))
        self.assertEqual(prior,[dict(r) for r in f.state.db.execute('SELECT * FROM production_attempts ORDER BY id')])
        from orchestrator.runtime import Runtime
        rt=Runtime(f.rt.root,connection=f.state.db,factory=f.factory)
        rt.tick(target);new=rt.task(target,'produce')['latest'];session=f.factory.sessions[new];frozen=session['frozen']
        self.assertNotIn('execution',frozen)
        raw=(session['workspace']/'revision-base/photos.zip').read_bytes()
        subject=image_sources.unpack(raw)[2]['subjects'][0]['id']
        f.factory.finish(new)
        (session['workspace']/'rejections.json').write_text(json.dumps({subject:'Wrong identity identified by original independent review'}))
        subprocess.run([sys.executable,'-B','.relay/revise-evidence.py','rejections.json','photos.zip'],cwd=session['workspace'],check=True,capture_output=True)
        rt.tick(target);rt.tick(target)
        rid=rt.task(target,'review')['latest'];self.assertIsNotNone(rid)
        self.assertEqual(f.factory.sessions[rid]['frozen']['review_target'],new)
        self.assertNotEqual(rt.status(target)['status'],'completed')
        f.factory.finish(rid,decision='accept');self.assertEqual(rt.tick(target)['status'],'completed')
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(len([x for x in f.factory.sessions.values() if x['frozen'].get('execution')]),1)

    def test_invalid_projection_cannot_reach_reviewer_even_with_success_report(self):
        f,p,s,aid=self.stopped()
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        target=f.step(p,'outline')['target'];f.rt.tick(target)
        new=f.rt.task(target,'produce')['latest'];session=f.factory.sessions[new]
        original=(session['workspace']/'revision-base/photos.zip').read_bytes()
        f.factory.finish(new);(session['workspace']/'photos.zip').write_bytes(original)
        f.rt.tick(target);f.rt.tick(target)
        self.assertEqual(f.rt.task(target,'produce')['status'],'blocked')
        self.assertIsNone(f.rt.task(target,'review')['latest'])

    def test_required_coverage_and_changed_evidence_hold(self):
        f,p,s,aid=self.stopped();baseline=recovery.snapshot(f.state,'parent',photo_recovery=True)
        self.assertIsNotNone(registered_revision.proof(f.rt,baseline))
        frozen=json.loads(f.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(aid,)).fetchone()[0])
        raw=Path(f.rt.output('parent','produce','photos.zip')['blob']).read_bytes()
        frozen['execution']['parameters']['count_policy']='required'
        self.assertIsNone(image_sources.revision_contract(frozen,raw))
        with transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        target=f.step(p,'outline')['target'];calls=list(f.factory.calls)
        artifact=f.rt.artifact(frozen['inputs'][0]['artifact']);blob=Path(artifact['blob']);blob.chmod(0o600);blob.write_bytes(b'changed source')
        f.rt.tick(target)
        self.assertEqual(f.factory.calls,calls)
        self.assertEqual(f.rt.task(target,'produce')['status'],'blocked')

    def test_billing_retry_keeps_original_recovery_allocation(self):
        from tests import test_production_planning as planning_fixtures
        from task_relay import pipelines
        f,p,s,aid=self.stopped();parent=planning_fixtures.Tests.queue(f,99)
        with transaction(f.state.db):f.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(parent['id'],))
        with patch('task_relay.registered_revision.proof',return_value=None),transaction(f.state.db):self.assertTrue(recovery.begin(f.state,p,s,'parent'))
        step=f.step(p,'outline');old=step['target'];error='Gemini request failed (402): prepaid credits depleted'
        with transaction(f.state.db):
            f.state.db.execute("UPDATE production_plans SET status='blocked',provider='gemini',calls=1,error=? WHERE id=?",(error,old))
            f.state.db.execute('INSERT INTO production_plan_calls(plan_id,number,request,response,usage,error,created) VALUES (?,1,?,NULL,NULL,?,1)',(old,'{}',error))
            f.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            f.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='outline'",(p['id'],))
            pipelines.control(f.state,p['id'],'retry_planning',request='Resume the existing run')
        new=f.step(p,'outline')['target']
        with transaction(f.state.db):
            response=json.dumps(dict(decision='blocked',message='No new discovery capability',plan=None))
            f.state.db.execute("UPDATE production_plans SET status='blocked',calls=1,result=? WHERE id=?",(response,new))
            f.state.db.execute('INSERT INTO production_plan_calls(plan_id,number,request,response,usage,error,created) VALUES (?,1,?,?,?,NULL,2)',(new,'{}',response,'{}'))
            f.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            f.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='outline'",(p['id'],))
        calls=[dict(r) for r in f.state.db.execute('SELECT * FROM production_plan_calls')]
        recovery.reconcile_stranded_local_revision(f.state)
        target=f.step(p,'outline')['target'];self.assertTrue(target.startswith('evidence-revision-'),target)
        recovery.reconcile_stranded_local_revision(f.state)
        self.assertEqual(f.step(p,'outline')['target'],target)
        self.assertEqual(calls,[dict(r) for r in f.state.db.execute('SELECT * FROM production_plan_calls')])
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
