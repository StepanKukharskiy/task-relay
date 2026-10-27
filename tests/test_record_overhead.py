"""Transport efficiency preserves individual authority and exact review coverage."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import operation_contracts as c,sourcing_contract
from orchestrator.operation_records import Store
from orchestrator.runtime import Runtime
from tests.test_correction_handoff_lifecycle import Fixtures
from tests.test_universal_interfaces import Harness,CONFIGURATIONS

class Continuation(Fixtures,unittest.TestCase):
    schema='furniture'
    def setUp(self):
        with patch('tests.test_correction_handoff_lifecycle.Harness',side_effect=lambda *a,**k:Harness(*a,**k,count=8)):
            super().setUp()
        self.params['max_records']=8

    def test_inherit_completed_baseline_amend_restart_and_batch_independent_review(self):
        self.submit('initial',[self.content('initial',self.pack)])
        records=[self.h.fragment(i) for i in self.h.inventory['items']]
        self.run_worker('initial',lambda f:[('operation_submit',dict(request_key=str(n),revision=n,records=[r])) for n,r in enumerate(records)])
        self.review('initial');base=self.artifact('initial');original=Path(base['blob']).read_bytes()
        self.submit('correct',[self.content('correct',self.pack,base)])
        frozen=self.factory.sessions[self.rt.task('job','correct')['latest']]['frozen'];store=Store(frozen,self.rt.db)
        self.assertEqual(store.progress()['record_versions'],{r['item']:c.digest(r) for r in records})
        self.assertEqual(store.progress()['baseline_comparison']['unchanged'],[r['item'] for r in records])
        self.assertEqual(self.rt.db.execute('select count(*) from operation_record_sets where attempt=?',(frozen['assignment_id'],)).fetchone()[0],0)
        changed=copy.deepcopy(records[0]);changed['gap']='Explicit remaining target shortfall; unknown buying fields remain disclosed.'
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        self.run_worker('correct',lambda f:[('operation_amend',dict(request_key='one',revision=0,expected_record_sha256=c.digest(records[0]),record=changed))])
        self.assertEqual(Store(frozen,self.rt.db).progress()['baseline_comparison']['changed'],['S0'])
        rid=next(t['id'] for t in self.rt.status('job')['tasks'] if self.rt.spec(t).get('review_of')=='correct')
        rf=self.factory.sessions[self.rt.task('job',rid)['latest']]['frozen']
        ctx=sourcing_contract.context(rf,lambda p:(Path(rf['workspace'])/p).read_bytes())
        verdicts=[dict(item=k,item_sha256=c.digest(v),verdict='supported',reason='Scripted independent comparison of exact item, source and original fields.') for k,v in ctx['items'].items()]
        self.run_worker(rid,lambda f:[('operation_submit',dict(request_key='all',revision=0,records=verdicts))],decision='accept')
        self.assertEqual(self.rt.task('job','correct')['status'],'completed')
        self.assertEqual(Store(rf,self.rt.db).progress()['committed'],8)
        control=Path(self.factory.sessions[rf['assignment_id']]['session']['control'])
        pack=json.loads((control/'source-pack.json').read_text())
        self.assertTrue(all(v.get('next_offset') is None for v in pack['files']))
        self.assertTrue(any(v.get('text') and v['path']==rf['operation_contract']['parameters']['catalog_path'] for v in pack['files']))
        self.assertEqual(Path(base['blob']).read_bytes(),original)
        self.assertEqual(json.loads(Path(self.artifact('correct')['blob']).read_text())['records'],[changed]+records[1:])
        for assignment in (frozen,rf):
            for key,value in assignment['limits'].items():self.assertLessEqual(value,self.grant['task_limits'][key])

class Plants(Continuation):schema='plants'
class Components(Continuation):schema='components'

class BatchSafety(unittest.TestCase):
    def test_stale_member_duplicate_oversize_and_conflicting_retry_are_atomic(self):
        with tempfile.TemporaryDirectory() as root:
            h=Harness(root,CONFIGURATIONS['furniture'],count=8);self.addCleanup(h.db.close)
            _,catalog=h.produce('producer');f=h.assignment('review',catalog=catalog);store=Store(f,h.db)
            values=[dict(item=v['id'],item_sha256=c.digest(v),verdict='supported',reason='Independent synthetic judgment') for v in catalog['items']]
            bad=copy.deepcopy(values);bad[-1]['item_sha256']='0'*64
            huge=copy.deepcopy(values)
            for v in huge:v['reason']='🧩'*1000
            for records in (bad,values[:1]*2,huge):
                with self.assertRaises(ValueError):store.submit(dict(request_key='no',revision=0,records=records),{})
                self.assertEqual(store.progress()['committed'],0)
                self.assertEqual(h.db.execute('select count(*) from operation_submissions where attempt=?',('review',)).fetchone()[0],0)
            args=dict(request_key='batch',revision=0,records=values);receipt=store.submit(args,{})
            self.assertEqual(store.submit(args,{}),receipt)
            self.assertEqual(len(receipt['record_ids']),8)
            changed=copy.deepcopy(args);changed['records'][0]['verdict']='uncertain'
            with self.assertRaisesRegex(ValueError,'Conflicting'):store.submit(changed,{})
            self.assertEqual(store.progress()['revision'],1)
            self.assertEqual(len(store._state(h.db)[1]),8)

    def test_batch_does_not_turn_uncertain_member_into_acceptance(self):
        with tempfile.TemporaryDirectory() as root:
            h=Harness(root,CONFIGURATIONS['plants'],count=3);self.addCleanup(h.db.close)
            _,catalog=h.produce('p');f=h.assignment('r',catalog=catalog);store=Store(f,h.db)
            values=[dict(item=v['id'],item_sha256=c.digest(v),verdict='uncertain' if n==1 else 'supported',reason='Unknown correspondence' if n==1 else 'Scripted judgment') for n,v in enumerate(catalog['items'])]
            store.submit(dict(request_key='all',revision=0,records=values),{})
            with self.assertRaises(ValueError):store.lifecycle.verify_result(store,values,dict(decision='accept'))
            self.assertEqual(store._state(h.db)[1],values)
