"""Frozen handoff bytes, publication recovery and job ownership; no browser calls."""
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from orchestrator.runtime import Runtime
from task_relay import computer_evidence as packs, computer_sessions as sessions, job_delete, workflow_files
from tests.test_computer_sessions import SessionHelper
from tests.test_computer_use import TARGET
from tests.test_job_delete import PID, OTHER


class EvidenceTests(unittest.TestCase):
    def test_cli_refuses_to_initialize_an_unrelated_database(self):
        import sqlite3
        from contextlib import redirect_stdout
        from task_relay.computer_use import main
        path = self.root/'unrelated.sqlite'
        db = sqlite3.connect(path); db.execute('CREATE TABLE unrelated(id TEXT)'); db.close()
        before = path.read_bytes()
        with redirect_stdout(io.StringIO()) as response:
            code = main(['evidence-inspect','--database',str(path),'--id','unknown'])
        self.assertEqual(code,1)
        self.assertIn('no saved Relay jobs',response.getvalue())
        self.assertEqual(path.read_bytes(),before)

    def setUp(self):
        from tests.test_job_delete import JobDeleteTests
        self.fixture = JobDeleteTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.pipeline(); self.state = self.fixture.state; self.state.channel = 'desktop'
        self.db = self.state.db; self.root = self.fixture.paths.data.resolve()
        self.state.media_dir = self.root/'media'
        self.rt = Runtime(self.root/'orchestrator',connection=self.db)
        self.ident = sessions.approve(self.db, job=PID, request_key='observe', exact_request='Read the synthetic catalog.',
            spec={'target':TARGET,'url':'https://example.com/one','allowed_urls':['https://example.com/one'],
                  'actions':[{'operation':'scroll','direction':'down'}],'capture':False,'local_fixture':False,'max_seconds':300},
            helper=SessionHelper.identity,output_root=self.root/'evidence',actor='fixture operator')
        self.helper = SessionHelper(self.db)

    def complete(self): sessions.run(self.db,self.ident,self.helper)

    def export(self, **kw):
        args = dict(assignment=self.ident,request_key='handoff',exact_request='Prepare saved observations for independent review.',actor='fixture operator',destination=self.root/'handoff.zip')
        args.update(kw)
        return packs.export(self.rt,**args)

    def test_registered_self_contained_pack_survives_source_removal_without_dispatch(self):
        self.complete(); result=self.export()
        self.assertTrue(result['verified']); self.assertEqual(result['manifest']['review_status'],'unreviewed')
        self.assertEqual(len(result['manifest']['observations']),2)
        artifact=self.rt.artifact(result['artifact']); raw=Path(artifact['blob']).read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.read('observations/000/page.txt'), (self.root/'evidence'/self.ident/sessions.actions(self.db,self.ident)[0]['id']/'page.txt').read_bytes())
        for action in sessions.actions(self.db,self.ident):
            (Path(json.loads(action['receipt'])['folder'])/'page.txt').unlink()
        before=list(self.db.iterdump())
        self.assertEqual(self.export()['artifact'],result['artifact'])
        self.assertEqual(before,list(self.db.iterdump()))
        self.assertEqual(packs.verify_bytes(raw,result['sha256'])['id'],result['id'])
        self.assertEqual(len(self.helper.calls),2)

    def test_changed_original_receipt_blocks_before_pack_intent(self):
        self.complete()
        row=sessions.actions(self.db,self.ident)[0]
        (Path(json.loads(row['receipt'])['folder'])/'page.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'): self.export()
        self.assertEqual(self.db.execute('SELECT count(*) FROM relay_computer_packs').fetchone()[0],0)
        self.assertFalse((self.root/'handoff.zip').exists())

    def test_interrupted_publication_recovers_exact_frozen_bytes(self):
        self.complete()
        def crash(path,raw):
            # Intent is visible before any output publication.
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(self.fixture.paths.state)) as reader:
                self.assertEqual(reader.execute('SELECT state FROM relay_computer_packs').fetchone()[0],'publishing')
            raise OSError('fixture full disk')
        with patch.object(packs,'write_new',side_effect=crash):
            with self.assertRaises(OSError): self.export()
        row=dict(self.db.execute('SELECT * FROM relay_computer_packs').fetchone())
        self.assertEqual(row['state'],'blocked')
        result=self.export()
        self.assertEqual(result['id'],row['id']); self.assertEqual(result['sha256'],row['sha256'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM production_artifacts WHERE task='computer_evidence'").fetchone()[0],1)

    def test_registration_crash_recovers_existing_zip_even_without_sources(self):
        self.complete()
        register = self.rt.register
        def crash(*args, **kwargs):
            register(*args, **kwargs)
            raise OSError('fixture crash after artifact insertion')
        with patch.object(self.rt,'register',side_effect=crash):
            with self.assertRaises(OSError): self.export()
        self.assertEqual(self.db.execute("SELECT count(*) FROM production_artifacts WHERE task='computer_evidence'").fetchone()[0],0)
        for action in sessions.actions(self.db,self.ident):
            (Path(json.loads(action['receipt'])['folder'])/'page.txt').unlink()
        self.assertTrue(self.export()['verified'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM production_artifacts WHERE task='computer_evidence'").fetchone()[0],1)
        self.assertEqual(len(self.helper.calls),2)

    def test_damaged_partial_export_is_never_overwritten(self):
        self.complete()
        with patch.object(self.rt,'register',side_effect=OSError('crash')):
            with self.assertRaises(OSError): self.export()
        path=self.root/'handoff.zip'; path.write_bytes(b'partial')
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(path.read_bytes(),b'partial')
        with self.assertRaises(ValueError): self.export(exact_request='Changed export request')
        self.assertEqual(self.db.execute("SELECT count(*) FROM production_artifacts WHERE task='computer_evidence'").fetchone()[0],0)

    def test_unknown_actions_block_until_reconciled_and_gaps_remain(self):
        def fail(req,count):
            if count==2: raise TimeoutError('unknown scroll')
        with self.assertRaises(TimeoutError): sessions.run(self.db,self.ident,SessionHelper(self.db,fail))
        sessions.control(self.db,self.ident,'cancel',actor='user',note='End fixture.')
        with self.assertRaisesRegex(ValueError,'reconcile'): self.export()
        sessions.resume(self.db,self.ident,current_url='https://example.com/one',actor='user',note='Preserve unknown result and stop.',abandon=True)
        result=self.export()
        self.assertEqual(result['manifest']['gaps'][0]['state'],'uncertain')
        self.assertTrue(result['manifest']['gaps'][0]['resolved'])
        self.assertEqual(len(result['manifest']['observations']),1)

    def test_changed_registered_blob_rejects_inspect_and_duplicate(self):
        self.complete(); result=self.export()
        path=Path(self.rt.artifact(result['artifact'])['blob']); path.chmod(0o600); path.write_bytes(b'changed')
        with self.assertRaises(ValueError): packs.inspect(self.rt,result['id'])
        with self.assertRaises(ValueError): self.export()
        self.assertEqual(len(self.helper.calls),2)

    def test_job_projection_ownership_and_external_consumer_block(self):
        self.complete(); result=self.export()
        report=workflow_files._snapshot(self.state,PID)
        self.assertEqual(report['computer_packs'][0]['artifact'],result['artifact'])
        self.assertIn(result['artifact'],[a['id'] for a in report['artifacts']])
        workflow_files.sync(self.state,PID)
        self.assertTrue((workflow_files.folder_path(self.state,PID)/'.relay/job.sqlite').is_file())
        self.fixture.pipeline(pid=OTHER,request=2)
        with self.db:
            self.db.execute('''INSERT INTO relay_pipeline_steps(pipeline,position,id,status,sources)
                VALUES (?,0,'review','pending',?)''',(OTHER,json.dumps([result['input']])))
        review=job_delete.preview(PID,self.fixture.paths)
        self.assertTrue(any('cites an output artifact' in b for b in review['blockers']),review['blockers'])
        with self.db: self.db.execute('DELETE FROM relay_pipeline_steps WHERE pipeline=?',(OTHER,))
        review=job_delete.preview(PID,self.fixture.paths); self.assertFalse(review['blockers'],review['blockers'])
        job_delete.delete(PID,review['digest'],self.fixture.paths)
        self.assertEqual(self.db.execute('SELECT count(*) FROM relay_computer_packs').fetchone()[0],0)
        self.assertIsNone(self.db.execute('SELECT id FROM production_artifacts WHERE id=?',(result['artifact'],)).fetchone())
        self.assertTrue((self.root/'handoff.zip').is_file())

    def test_provenance_mismatch_cannot_be_hidden_by_matching_file_hash(self):
        self.complete(); action=sessions.actions(self.db,self.ident)[0]
        receipt=json.loads(action['receipt']); path=Path(receipt['folder'])/'evidence.json'
        value=json.loads(path.read_text()); value['url']='https://example.com/other'; path.write_text(json.dumps(value))
        receipt['files']['evidence.json']=packs._info(path.read_bytes())
        with self.db: self.db.execute('UPDATE relay_computer_actions SET receipt=? WHERE id=?',(sessions.encoded(receipt),action['id']))
        with self.assertRaisesRegex(ValueError,'provenance'): self.export()
