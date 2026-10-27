import json
import sqlite3
import unittest
from types import SimpleNamespace
from task_relay import external_evidence as evidence


class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE production_artifacts(id,sha256,bytes,attempt,path); CREATE TABLE production_attempts(id,frozen,receipt,state);')
        self.source=dict(artifact='selected-alias',sha256='a'*64,bytes=42,path='ordinary.json')
        self.receipt=dict(status='finished',operation=dict(output_sha256='a'*64,validation=dict(fetched=1)))
        self.db.execute('INSERT INTO production_artifacts VALUES (?,?,?,?,?)',('original','a'*64,42,'finished-read','delivery/source-pack.json'))
        self.save()

    def tearDown(self):self.db.close()

    def save(self,state='completed',capability='web.sources'):
        self.db.execute('DELETE FROM production_attempts')
        self.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?)',('finished-read',json.dumps({'execution':{'capability':capability}}),json.dumps(self.receipt),state))

    def records(self):return evidence.recorded_sources(SimpleNamespace(db=self.db),[self.source])

    def test_native_page_alias_allows_saved_evidence_without_new_lookup(self):
        records=self.records();self.assertEqual(len(records),1)
        self.assertEqual(records[0]['origin_artifact'],'original')
        payload=dict(original_request='Verify the public source catalog',sources=[self.source],recorded_external_sources=records)
        self.assertFalse(evidence.needed(payload))
        evidence.validate_plan({'tasks':[dict(id='capture',inputs=[])]},payload)
        payload['sources']=[]
        self.assertTrue(evidence.needed(payload))

    def test_summaries_pending_work_and_changed_bytes_do_not_count(self):
        for change in [dict(pending_requests=['unknown']),dict(operation=dict(output_sha256='a'*64,validation=dict(fetched=0))),dict(operation=dict(output_sha256='b'*64,validation=dict(fetched=1)))]:
            original=self.receipt.copy();self.receipt.update(change);self.save();self.assertEqual(self.records(),[]);self.receipt=original
        self.save(state='uncertain');self.assertEqual(self.records(),[])
        self.save(capability='pptx.create');self.assertEqual(self.records(),[])
        self.save();self.source['sha256']='b'*64;self.assertEqual(self.records(),[])

    def test_unrecorded_source_still_requires_research_step(self):
        payload=dict(original_request='Verify the public source catalog',sources=[self.source])
        self.assertTrue(evidence.needed(payload))
        with self.assertRaisesRegex(ValueError,'research step'):
            evidence.validate_plan({'tasks':[dict(id='capture',inputs=[])]},payload)

    def test_authored_composition_assertion_without_native_parent_receipts_is_not_provenance(self):
        frozen=dict(operation_contract=dict(id='sourcing.options',parameters=dict(source_pack_output='delivery/source-pack.json',source_pack_path='new.json',base_source_pack_path='old.json')),inputs=[])
        self.db.execute('UPDATE production_attempts SET frozen=?',(json.dumps(frozen),))
        self.assertEqual(self.records(),[])

    def test_native_catalog_join_preserves_source_ancestry_but_cannot_launder_pending_parent(self):
        self.db.execute('INSERT INTO production_artifacts VALUES(?,?,?,?,?)',('a-merged','a'*64,42,'merge','delivery/source-pack.json'))
        frozen=dict(execution=dict(capability='sourcing.merge',parameters=dict(source_pack_path='sources.json')),inputs=[dict(path='sources.json',artifact='original',sha256='a'*64)])
        self.db.execute('INSERT INTO production_attempts VALUES(?,?,?,?)',('merge',json.dumps(frozen),json.dumps(dict(status='finished',operation=dict(outcome='completed'))),'completed'))
        rt=SimpleNamespace(db=self.db,artifact=lambda ident:dict(self.db.execute('SELECT * FROM production_artifacts WHERE id=?',(ident,)).fetchone()))
        records=evidence.recorded_sources(rt,[self.source]);self.assertEqual(records[0]['attempt'],'merge')
        self.assertEqual(records[0]['native_parents'],['original'])
        self.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id='finished-read'")
        self.assertEqual(evidence.recorded_sources(rt,[self.source]),[])

    def test_new_photo_connector_reuses_only_its_finished_exact_receipt(self):
        from task_relay.completion_recovery import completed_read_operations,validate_operation_reuse
        self.receipt['operation']=dict(outcome='completed',output_sha256='a'*64,validation=dict(coverage=dict(found=1)))
        self.save(capability='images.products');records=self.records()
        self.assertEqual(records[0]['capability'],'images.products')
        baseline=dict(attempts=[dict(id='finished-read',state='completed')],tasks=[dict(id='photos',status='awaiting_review',latest='finished-read')],plan=dict(tasks=[dict(id='photos',execution=dict(capability='images.products'))]))
        completed=completed_read_operations(baseline);self.assertEqual(completed[0]['capability'],'images.products')
        payload=dict(original_request='Verify the public source catalog',sources=[self.source],recorded_external_sources=records,
                     options=dict(step_capabilities=['images.products']),completion_recovery=dict(completed_read_operations=completed))
        self.assertTrue(evidence.needed(payload))
        plan=dict(tasks=[dict(id='repair',inputs=[dict(artifact=self.source['artifact'])]),dict(id='review',review_of='repair',inputs=[dict(artifact=self.source['artifact'])])])
        validate_operation_reuse(plan,payload,{'images.products':[self.source['artifact']]})
        self.save(state='uncertain',capability='images.products');self.assertEqual(self.records(),[])

    def test_image_receipt_reuse_never_substitutes_for_fetched_page_research(self):
        self.receipt['operation']=dict(outcome='completed',output_sha256='a'*64,validation=dict(coverage=dict(found=1)))
        self.save(capability='images.fetch');records=self.records()
        self.assertEqual(records[0]['capability'],'images.fetch')
        payload=dict(original_request='Verify the public source catalog',sources=[self.source],recorded_external_sources=records)
        self.assertTrue(evidence.needed(payload))
        from task_relay.completion_recovery import validate_operation_reuse
        payload.update(options=dict(step_capabilities=['images.fetch']),completion_recovery=dict(
            completed_read_operations=[dict(attempt='finished-read',capability='images.fetch')]))
        producer=dict(id='merge',inputs=[dict(artifact=self.source['artifact'])])
        review=dict(id='review',review_of='merge',inputs=[dict(artifact=self.source['artifact'])])
        validate_operation_reuse(dict(tasks=[producer,review]),payload,{'images.fetch':[self.source['artifact']]})
        for change in ('missing_review','different_capability','pending'):
            with self.subTest(change=change):
                if change=='missing_review':
                    with self.assertRaises(ValueError):validate_operation_reuse(dict(tasks=[producer]),payload,{'images.fetch':[self.source['artifact']]})
                elif change=='different_capability':
                    payload['completion_recovery']['completed_read_operations'][0]['capability']='web.sources'
                    with self.assertRaises(ValueError):validate_operation_reuse(dict(tasks=[producer,review]),payload,{'images.fetch':[self.source['artifact']]})
                else:
                    self.receipt['pending_requests']=['unknown'];self.save(capability='images.fetch');self.assertEqual(self.records(),[])
