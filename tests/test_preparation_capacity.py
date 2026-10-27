"""Small offline preparation/store/consumer checks; no providers or host execution."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from orchestrator import contracts as c, prepared_contract as pc, prepared_schemas as ps, producer_binding
from orchestrator.operation_records import Store
from orchestrator.runtime import Runtime
from tests import test_producer_binding as fixtures

class Capacity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.rt=Runtime(self.root/'rt');self.addCleanup(self.rt.close)
        author=fixtures.writer('prepare');consumer=dict(id='build',execution=dict(capability='blender.run_python',parameters={}),inputs=[fixtures.ref('prepare','data.json')])
        producer_binding.compile(dict(tasks=[author,consumer],backend=fixtures.BACKEND))
        self.f={**author,'backend':fixtures.BACKEND,'assignment_id':'fixture','workspace':str(self.root)}
        self.rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',('fixture','fixture','prepare','assignment','running',None,c.encoded(self.f),'{}',None,None))
        self.store=Store(self.f,self.rt.db)
    def submit(self,records,key=None):
        revision=self.store.progress()['revision']
        return self.store.submit(dict(request_key=key or 'part'+str(revision),revision=revision,records=records),{})
    def read(self):
        with self.store.connection(write=False) as db:_,records=self.store._state(db)
        return self.store.document(records)
    def test_full_176_object_handoff_under_unchanged_limits_and_restart(self):
        names=['Beam%03d'%i for i in range(175)]+['Camera']
        records=[dict(kind='field',field='mode',value='create'),dict(kind='field',field='units',value='Meters'),
                 dict(kind='field',field='preview',value=dict(camera='Camera',resolution=[960,540],samples=16)),
                 dict(kind='entry',field='expected_dimensions',key=names[0],value=[1,1,1])]
        records += [dict(kind='extend',field='objects',index=i,values=names[i:i+32]) for i in range(0,len(names),32)]
        records += [dict(kind='end')]
        original=copy.deepcopy(self.f)
        for i in range(0,len(records),8):
            reply=self.submit(records[i:i+8]);self.store=Store(self.f,self.rt.db)
        self.assertTrue(self.store.progress()['sealed']);self.assertEqual(reply['revision'],2)
        self.assertEqual(self.store.progress()['maximum'],100)
        self.assertEqual(self.f['limits']['provider_requests'],24);self.assertEqual(self.f['limits']['tool_calls'],24)
        self.assertEqual(self.f,original);self.assertEqual(self.read()['objects'],names)
        ps.validate('blender.run_python',self.read())
        legacy=[dict(kind='append',field='objects',index=i,value=n) for i,n in enumerate(names)]
        self.assertEqual(pc.document(self.store,records[:4]+legacy+[dict(kind='end')]),self.read())
        self.assertIn('Declare every created object',pc.schema(self.f['operation_contract']['parameters'])['description'])
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],1)
    def test_failed_chunk_and_amendment_are_atomic_and_original_is_versioned(self):
        old=dict(kind='extend',field='objects',index=0,values=['A','B'])
        self.submit([old]);before=self.store.progress()
        for bad in [dict(kind='extend',field='objects',index=1,values=['C']),dict(kind='extend',field='objects',index=2,values=[5]),dict(kind='extend',field='objects',index=2,values=['C']*33)]:
            with self.assertRaises(ValueError):self.submit([bad],'bad'+str(bad))
            self.assertEqual(self.store.progress(),before)
        self.submit([dict(kind='append',field='objects',index=2,value='C')])
        args=dict(request_key='correct',revision=2,expected_record_sha256=c.digest(old),record={**old,'values':['A','D']})
        receipt=self.store.amend(args,{});self.assertEqual(self.store.amend(args,{}),receipt)
        self.assertEqual(self.read()['objects'],['A','D','C'])
        stored=json.loads(self.rt.db.execute('SELECT value FROM operation_record_versions').fetchone()[0]);self.assertEqual(stored,old)
        with self.assertRaisesRegex(ValueError,'consecutive'):
            self.store.amend(dict(request_key='length',revision=3,expected_record_sha256=c.digest(args['record']),record={**old,'values':['A']}),{})
        self.assertEqual(self.read()['objects'],['A','D','C'])
    def test_native_item_fragment_batch_and_byte_bounds_are_unchanged(self):
        for i in range(0,480,32):self.submit([dict(kind='extend',field='objects',index=i,values=['B%d'%j for j in range(i,i+32)])])
        before=self.store.progress()
        with self.assertRaisesRegex(ValueError,'item ceiling'):
            self.submit([dict(kind='extend',field='objects',index=480,values=['X%d'%i for i in range(21)])])
        self.assertEqual(self.store.progress(),before)
        with self.assertRaisesRegex(ValueError,'batch exceeds'):
            self.submit([dict(kind='end')]*9)
        huge=[dict(kind='extend',field='objects',index=i*32,values=['X'*200]*32) for i in range(3)]
        with self.assertRaisesRegex(ValueError,'byte bound'):self.submit(huge)
        self.assertEqual(self.store.progress(),before)
    def test_chunks_are_generic_scalar_only_and_preserve_small_record_ceiling(self):
        p=dict(target='rhino.run_python',max_records=1,hash_bindings={})
        fake=SimpleNamespace(contract={'parameters':p},context=lambda:dict(fixed={},assets={},hashes={}))
        values=[dict(kind='extend',field='changed_objects',index=0,values=['One','Two'])]
        self.assertEqual(pc.document(fake,values)['changed_objects'],['One','Two'])
        with self.assertRaises(ValueError):pc.record(dict(kind='extend',field='objects',index=0,values=[{}]),dict(target='rhino.document',max_records=100,hash_bindings={}))
        # Enforced by the same store, including a chunk counting as one fragment.
        frozen=copy.deepcopy(self.f);frozen['operation_contract']['parameters']['max_records']=2
        self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(c.encoded(frozen),'fixture'))
        self.store=Store(frozen,self.rt.db)
        self.submit([dict(kind='extend',field='objects',index=0,values=['A','B']),dict(kind='field',field='units',value='Meters')])
        with self.assertRaisesRegex(ValueError,'Frozen record ceiling'):self.submit([dict(kind='end')])

if __name__=='__main__':unittest.main()
