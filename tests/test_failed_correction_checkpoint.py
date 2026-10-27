"""Confirmed failed producers retain exact amendments, never review acceptance."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import operation_contracts as c
from orchestrator.operation_records import Store
from orchestrator.record_recovery import collected_checkpoint
from orchestrator.runtime import Runtime
from tests.test_correction_handoff_lifecycle import Fixtures

class Checkpoints(Fixtures,unittest.TestCase):
    schema='furniture'
    def failed(self):
        base,fragment=self.initial_catalog()
        corrected=copy.deepcopy(fragment);corrected['options'][0]['comparison']='Saved first correction; price remains unknown.'
        from tests.test_owner_intents import Script
        self.findings=[dict(category='integrity',code='REMAINING_CORRECTION',message='Saved visual corrections need an exact remaining qualification and independent review.',evidence='Synthetic checkpoint record S0')]
        def with_findings(steps):
            report=json.loads(steps[-1][1]['report_json']);report['findings']=self.findings
            steps[-1]=('finish',dict(report_json=c.encoded(report)))
            return Script(steps)
        with patch('tests.test_owner_intents.Script',side_effect=with_findings):
            catalog,pack=self.repair('failed',base,corrected,self.pack,blocked=True)
        self.assertEqual(self.rt.task('job','failed')['status'],'blocked')
        return base,corrected,catalog,pack

    def successor(self,ident,base,pack):
        self.submit(ident,[self.content(ident,pack,base)])
        frozen=self.factory.sessions[self.rt.task('job',ident)['latest']]['frozen']
        predecessor=json.loads(self.rt.db.execute('select frozen from production_attempts where id=?',(base['attempt'],)).fetchone()[0])
        self.assertEqual(frozen['limits'],predecessor['limits'])
        return frozen,Store(frozen,self.rt.db)

    def test_two_failed_corrections_restart_continue_and_exact_independent_review(self):
        base,first,catalog,pack=self.failed();original=Path(catalog['blob']).read_bytes()
        proof=collected_checkpoint(self.rt,catalog);self.assertFalse(proof['acceptance'])
        snapshot=self.session().snapshot()
        entry=next(a for a in snapshot['decision_brief']['available_inputs'] if a['ref']['artifact']==catalog['id'])
        self.assertEqual(entry['producer_status'],'blocked')
        self.assertEqual(entry['correction_checkpoint']['source'],pack['id'])
        self.assertEqual(entry['correction_checkpoint']['parent'],base['id'])
        self.assertFalse(entry['correction_checkpoint']['acceptance'])
        frozen,store=self.successor('second',catalog,pack)
        self.assertEqual(store.progress()['record_versions'],{'S0':c.digest(first)})
        self.assertEqual(store.progress()['remaining'],0)
        self.assertEqual(store.progress()['checkpoint']['unresolved_findings'],self.findings)
        self.assertEqual(self.rt.db.execute('select count(*) from operation_record_sets where attempt=?',(frozen['assignment_id'],)).fetchone()[0],0)
        second=copy.deepcopy(first);second['gap']='Saved second correction; two options still absent.'
        self.run_worker('second',lambda f:[('operation_amend',dict(request_key='second',revision=0,expected_record_sha256=c.digest(first),record=second))],decision='blocked')
        saved=self.artifact('second');pack2=self.artifact('second','delivery/retained-sources.json')
        self.assertEqual(json.loads(Path(saved['blob']).read_text())['records'],[second])
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
        f,store=self.successor('third',saved,pack2)
        self.assertEqual(store.progress()['record_versions'],{'S0':c.digest(second)})
        third=copy.deepcopy(second);third['options'][0]['comparison']+=' Final qualification.'
        with self.assertRaisesRegex(ValueError,'Stale sourcing amendment'):
            store.amend(dict(request_key='stale',revision=0,expected_record_sha256=c.digest(first),record=third),{})
        self.assertEqual(store.progress()['revision'],0)
        self.run_worker('third',lambda f:[('operation_amend',dict(request_key='third',revision=0,expected_record_sha256=c.digest(second),record=third)),('file_read',dict(path=f['operation_contract']['output'],offset=0,limit=24000))])
        self.review('third')
        self.assertEqual(json.loads(Path(self.artifact('third')['blob']).read_text())['records'],[third])
        self.assertEqual(self.rt.task('job','failed')['status'],'blocked')
        self.assertEqual(self.rt.task('job','second')['status'],'blocked')
        self.assertEqual(Path(catalog['blob']).read_bytes(),original)
        self.assertEqual(Path(pack['blob']).read_bytes(),Path(pack2['blob']).read_bytes())
        self.assertEqual(self.rt.db.execute('select count(*) from production_decisions').fetchone()[0],0)

    def test_pending_uncertain_changed_binding_and_missing_projection_fail_closed(self):
        _,_,catalog,_=self.failed();aid=catalog['attempt']
        row=self.rt.db.execute('select * from production_attempts where id=?',(aid,)).fetchone()
        receipt=json.loads(row['receipt'])
        for change in (dict(pending_requests=['unknown']),dict(external_outcome='unknown'),dict(cleanup_error='PermissionError'),dict(status='running')):
            with self.subTest(change=change):
                self.rt.db.execute('update production_attempts set receipt=? where id=?',(json.dumps({**receipt,**change}),aid))
                self.assertIsNone(collected_checkpoint(self.rt,catalog))
        self.rt.db.execute('update production_attempts set receipt=?,state=? where id=?',(row['receipt'],'uncertain',aid));self.assertIsNone(collected_checkpoint(self.rt,catalog))
        self.rt.db.execute('update production_attempts set state=? where id=?',('blocked',aid))
        self.assertIsNotNone(collected_checkpoint(self.rt,catalog))
        self.rt.db.execute('update production_attempts set frozen=? where id=?',(json.dumps({**json.loads(row['frozen']),'instruction':'changed'}),aid))
        self.assertIsNone(collected_checkpoint(self.rt,catalog))
        self.rt.db.execute('update production_attempts set frozen=? where id=?',(row['frozen'],aid))
        pack=self.artifact('failed','delivery/retained-sources.json')
        self.rt.db.execute('delete from production_artifacts where id=?',(pack['id'],));self.assertIsNone(collected_checkpoint(self.rt,catalog))

    def test_changed_existing_option_submission_is_an_atomic_error(self):
        base,fragment=self.initial_catalog();self.submit('change',[self.content('change',self.pack,base)])
        f=self.factory.sessions[self.rt.task('job','change')['latest']]['frozen'];store=Store(f,self.rt.db)
        changed=copy.deepcopy(fragment);changed['options'][0]['comparison']='A substantive new correction'
        with self.assertRaisesRegex(ValueError,'Existing option differs'):
            store.submit(dict(request_key='wrong',revision=0,records=[changed]),{})
        self.assertEqual(store.progress()['committed'],1)
        self.assertEqual(self.rt.db.execute('select count(*) from operation_submissions where attempt=?',(f['assignment_id'],)).fetchone()[0],0)
        self.run_worker('change',lambda f:[('operation_amend',dict(request_key='right',revision=0,expected_record_sha256=c.digest(fragment),record=changed))])
        self.review('change');self.assertEqual(json.loads(Path(self.artifact('change')['blob']).read_text())['records'],[changed])
