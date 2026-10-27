"""Extensions run through the existing engine; no production transports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from orchestrator import execution, operation_contracts as c, operation_records
from orchestrator.operation_adapters import Adapter,object_schema
from orchestrator.operation_execution import Result
from orchestrator.runtime import Runtime
from orchestrator.adapters import ExecutionFactory
from tests.test_mixed_execution import LocalRegistered,Client,upstream,operation
from tests.test_orchestrator import FakeFactory,plan
from tests.test_universal_interfaces import Harness,CONFIGURATIONS
from orchestrator import subject_contract as subjects


def transform(context):
    # An unfamiliar registered operation executes without a central-runner edit.
    return Result(data='|'.join(d['text'] for d in context.documents).upper())


def pending(control,result,details):
    if (control/'extension-intent.json').exists() and not (control/'extension-result.json').exists():
        result.update(status='uncertain',external_outcome='unknown',local_terminal=True)


def uncertain_transform(context):
    (context.control/'extension-intent.json').write_text('submitted')
    raise OSError('Injected lost response')


class ExecutionTests(unittest.TestCase):
    def test_new_transport_and_observation_extension_across_restart(self):
        for unknown in (False,True):
            with self.subTest(unknown=unknown),tempfile.TemporaryDirectory() as root:
                root=Path(root).resolve();source=root/'input.txt';source.write_text('a real bound value')
                agents=FakeFactory();ops=LocalRegistered(Client());factory=ExecutionFactory(agents,ops)
                rt=Runtime(root/'runtime',factory);self.addCleanup(rt.close)
                aid=rt.register(source,'Fixture',path='input.txt')
                name='fixture.transform';spec=copy.deepcopy(execution.REGISTRY['text.bundle'])
                adapter=Adapter(object_schema({}),handler=__name__+(':uncertain_transform' if unknown else ':transform'),inspections=(__name__+':pending',))
                with patch.dict(execution.REGISTRY,{name:spec}),patch.dict(execution.ADAPTERS,{name:adapter}):
                    initial=dict(artifact=aid,path='input.txt',media_type='text/plain',purpose='Source',authority='Data')
                    rt.create(plan([operation('first',name,[initial]),operation('second','text.bundle',[upstream('first','first.txt')],['first'])]))
                    rt.tick('demo');first=rt.task('demo','first')['latest'];rt.close()
                    rt=Runtime(root/'runtime',factory);self.addCleanup(rt.close)
                    for _ in range(3):rt.tick('demo')
                    if unknown:
                        self.assertEqual(rt.status('demo')['status'],'uncertain')
                        self.assertEqual(ops.calls,[first]);self.assertIsNone(rt.task('demo','second')['latest'])
                    else:
                        self.assertEqual(rt.status('demo')['status'],'completed')
                        self.assertIn('A REAL BOUND VALUE',Path(rt.output('demo','second','second.txt')['blob']).read_text())
                        self.assertEqual(len(ops.calls),2)

    def test_native_intents_cannot_be_hidden_by_a_generic_failed_wrapper(self):
        from orchestrator.adapters import RegisteredFactory
        from orchestrator.workers import CodexFactory
        for capability in ('blender.scene','rhino.run_python','sketchup.run_ruby','media.compose','hyperframes.render','pptx.render'):
            with self.subTest(capability=capability),tempfile.TemporaryDirectory() as root:
                control=Path(root);(control/'host-intent.json').write_text('{}')
                selected=dict(capability=capability,version=1,parameters={})
                session=dict(control=root,execution=selected)
                (control/'operation.json').write_text(json.dumps(dict(outcome='failed',reason='Wrapper crashed')))
                with patch.object(CodexFactory,'inspect',return_value=dict(status='finished',exit_code=1)):
                    result=RegisteredFactory().inspect(session)
                self.assertEqual(result['status'],'uncertain')
                self.assertEqual(result['external_outcome'],'unknown')
                (control/'operation.json').write_text(json.dumps(dict(outcome='failed',execution=selected,reason='Confirmed terminal host failure')))
                with patch.object(CodexFactory,'inspect',return_value=dict(status='finished',exit_code=1)):
                    result=RegisteredFactory().inspect(session)
                self.assertEqual(result['status'],'finished')


class SubjectTests(unittest.TestCase):
    def setup_subjects(self,root,config):
        h=Harness(root,config);self.addCleanup(h.db.close)
        raw='Observed subject: '+config['identity']
        (h.root/'brief.txt').write_text(raw)
        import hashlib
        f=h.assignment('subjects')
        f['inputs']=[dict(path='brief.txt',artifact='brief',sha256=hashlib.sha256(raw.encode()).hexdigest(),media_type='text/plain',purpose='Brief',authority='Source')]
        f['operation_contract']=dict(**subjects.IDENTITY,parameters=dict(source_path='brief.txt',summary_path='subjects.md',max_records=2,fields=list(config['fields'])),output='subjects.json')
        h.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(c.encoded(f),'subjects'));h.db.commit()
        item=dict(kind='item',slot=1,label=config['identity'],attributes={k:None for k in config['fields']},quote=raw,bbox=None,notes='Unknown attributes remain null')
        return h,f,item

    def test_generic_subjects_seal_resume_and_feed_all_collection_domains(self):
        for name,config in CONFIGURATIONS.items():
            with self.subTest(domain=name),tempfile.TemporaryDirectory() as root:
                h,f,item=self.setup_subjects(root,config)
                store=operation_records.Store(f,h.db)
                request=dict(request_key='one',revision=0,records=[item]);receipt=store.submit(request,{})
                # Reopen the same durable store after losing the local submit response.
                store=operation_records.Store(f,h.db);self.assertEqual(store.submit(request,{}),receipt)
                with self.assertRaises(ValueError):store.submit(dict(request_key='out-of-order',revision=1,records=[dict(item,slot=3)]),{})
                with self.assertRaises(ValueError):store.submit(dict(request_key='wrong-seal',revision=1,records=[dict(kind='end',count=0,notes='Mismatch')]),{})
                self.assertEqual(store.progress()['committed'],1)
                store.submit(dict(request_key='end',revision=1,records=[dict(kind='end',count=1,notes='Covered')]),{})
                from orchestrator.gemini_worker import Files
                store.export(Files(f),complete=True)
                data=json.loads((h.root/'subjects.json').read_bytes());c.validate_document((h.root/'subjects.json').read_bytes(),subjects.IDENTITY)
                h.inventory=data;h.inputs[0]=h.input('subjects.json',data)
                # Empty captured-source yield remains explicit and completes downstream.
                h.pack=dict(version=1,entries=[]);h.inputs[1]=h.input('sources.json',h.pack)
                _,catalog=h.produce('catalog');self.assertEqual(catalog['items'][0]['id'],'SUB-001')
                self.assertEqual(catalog['items'][0]['options'],[])
                broken=copy.deepcopy(data);broken['items'][0]['label']='invented replacement'
                with self.assertRaises(ValueError):subjects.validate_document(broken)

    def test_wrong_evidence_and_changed_source_cannot_commit(self):
        with tempfile.TemporaryDirectory() as root:
            h,f,item=self.setup_subjects(root,CONFIGURATIONS['plants']);store=operation_records.Store(f,h.db)
            with self.assertRaisesRegex(ValueError,'literal source'):store.submit(dict(request_key='bad',revision=0,records=[dict(item,quote='Absent quote')]),{})
            (h.root/'brief.txt').write_text('Replacement source')
            with self.assertRaisesRegex(ValueError,'version changed'):store.submit(dict(request_key='changed',revision=0,records=[item]),{})
            self.assertEqual(h.db.execute("SELECT count(*) FROM operation_records WHERE attempt='subjects'").fetchone()[0],0)


class CompilerTests(unittest.TestCase):
    def test_generic_subject_interface_has_independent_review_and_legacy_scope_stays_frozen(self):
        from task_relay import record_planning,planning_contract
        from tests.test_universal_interfaces import Tests
        value=Tests().proposal(CONFIGURATIONS['plants'],count=2)
        producer,review=value['tasks']
        producer['records']=dict(family=subjects.IDENTITY.copy(),inputs=dict(source_path={'source':'subjects'}),parameters=dict(fields=['botanical_name'],max_records=2))
        with self.assertRaises(ValueError):record_planning.bind(copy.deepcopy(value),version=1)
        record_planning.bind(value,version=2)
        self.assertEqual(producer['operation_contract']['id'],'collection.subjects')
        self.assertNotIn('operation_contract',review)
        self.assertIn(subjects.CRITERION,review['criteria'])
        self.assertTrue(any(i.get('from_task')=='collect' and i.get('output')=='catalog.md' for i in review['inputs']))
        self.assertNotIn('collection.subjects',json.dumps(record_planning.schema(1)))
        self.assertIn('collection.subjects',json.dumps(record_planning.schema(2)))


class RecoveryTests(unittest.TestCase):
    def test_new_continuation_registration_reaches_controller_without_a_kind_branch(self):
        from tests.test_continuation_controller import Tests
        from orchestrator.continuation_adapters import REGISTRY
        from task_relay import completion_recovery as recovery
        from orchestrator.storage import transaction
        helper=Tests();self.addCleanup(helper.doCleanups)
        state,rt,parent,p,s,run,tid=helper.stopped('record_checkpoint')
        extended={k:v for k,v in REGISTRY.items() if k!='record_checkpoint'}
        extended['fixture_checkpoint']=REGISTRY['record_checkpoint']
        calls=list(rt.factory.calls)
        with patch.dict(REGISTRY,extended,clear=True):
            with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,run))
            self.assertEqual(rt.factory.calls,calls)
            event=json.loads(state.db.execute("SELECT data FROM production_events WHERE kind='continuation_committed'").fetchone()[0])
            self.assertEqual(event['kind'],'fixture_checkpoint')
            restarted=Runtime(rt.root,rt.factory,connection=state.db)
            restarted.tick(run);restarted.tick(run)
            self.assertEqual(restarted.task(run,tid)['attempts'],2)
            self.assertEqual(len(rt.factory.calls),len(calls)+1)

    def test_committed_continuation_rejects_registered_adapter_drift(self):
        from tests.test_continuation_controller import Tests
        from orchestrator.continuation_adapters import REGISTRY
        helper=Tests();self.addCleanup(helper.doCleanups)
        state,rt,parent,p,s,run,tid=helper.stopped('record_checkpoint')
        # Fixture's original attempts are spent; prove extension through its existing allocation.
        from task_relay import completion_recovery as recovery
        from orchestrator.storage import transaction
        with transaction(state.db):self.assertTrue(recovery.begin(state,p,s,run))
        row=state.db.execute("SELECT data FROM production_events WHERE kind='continuation_committed'").fetchone()
        detail=json.loads(row[0]);adapter=REGISTRY['record_checkpoint']
        # Drift cannot turn an already committed continuation into a new algorithm.
        with patch.dict(REGISTRY,{'record_checkpoint':replace(adapter,version=2)}):rt.tick(run)
        self.assertEqual(rt.task(run,tid)['attempts'],1)
        self.assertEqual(rt.task(run,tid)['status'],'blocked')
        self.assertEqual(detail['adapter'],adapter.manifest())

    def test_first_owned_failure_with_arbitrary_text_reaches_common_recovery_once(self):
        from tests.test_completion_recovery import Tests
        from tests import test_production_planning as planning_fixtures
        from tests.test_orchestrator import pair
        from task_relay import completion_recovery as recovery
        from orchestrator.storage import transaction
        f=Tests();f.setUp();self.addCleanup(f.tearDown)
        p,s=f.prepare();graph=pair(max_attempts=1);graph['id']='parent';f.rt.create(graph);f.rt.tick('parent')
        parent=f.rt.task('parent','produce')['latest'];f.factory.finish(parent,decision='blocked');f.rt.tick('parent')
        plan=planning_fixtures.Tests.queue(f,99)
        with transaction(f.state.db):
            f.state.db.execute("UPDATE production_plans SET status='started',run='parent' WHERE id=?",(plan['id'],))
            f.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(p['id'],))
            f.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked',error='Unfamiliar wording' WHERE pipeline=? AND id=?",(p['id'],s['id']))
        before=list(f.factory.calls)
        with patch.object(recovery,'snapshot',return_value=f.baseline()):
            recovery.reconcile_changed_failures(f.state);recovery.reconcile_changed_failures(f.state)
        self.assertEqual(f.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
        self.assertEqual(f.factory.calls,before)
        self.assertEqual(f.rt.task('parent','produce')['attempts'],1)


if __name__=='__main__':unittest.main()
