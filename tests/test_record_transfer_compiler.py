"""Real public owner admission, generated partitions and consumer contract checks."""
import copy,json,unittest
from unittest.mock import patch
from orchestrator import operation_contracts as c,record_transfers,job_owner
from tests import test_owner_compilation as owner

class Admission(unittest.TestCase):
    setUp=owner.Tests.setUp;create=owner.Tests.create;source=owner.Tests.source
    session=owner.Tests.session;content=owner.Tests.content;run_worker=owner.Tests.run_worker
    invoke=owner.Tests.invoke

    def test_visual_and_legacy_at_partition_thresholds(self):
        from orchestrator import execution,parameter_contracts
        for count in (9,10,11,21):
            for visual in (False,True):
                with self.subTest(count=count,visual=visual):
                    case=Admission();case.setUp()
                    try:
                        refs,task=case.content(count)
                        if visual:task['content']['parameters']['selection_policy']='visual'
                        case.grant['operations']=['records.merge'];case.grant['task_limits'].update(tool_calls=100,provider_requests=24)
                        case.create(inputs=refs);case.rt.tick('job');session=case.session();before=copy.deepcopy(session.grant)
                        receipt=session.delegate(dict(request_id='parts',tasks=[task]));self.assertEqual(session.grant,before)
                        for ident in receipt['queued']:
                            t=case.rt.spec(case.rt.task('job',ident))
                            if t.get('execution'):parameter_contracts.validate(t['execution']['parameters'],execution.parameter_schema(t['execution']['capability']))
                            if t.get('operation_contract',{}).get('id')=='collection.options':self.assertEqual(t['operation_contract']['parameters'].get('selection_policy'),'visual' if visual else None)
                        compiled=case.rt.spec(case.rt.task('job','collect'))
                        self.assertEqual(bool(compiled.get('execution')),count>10)
                        self.assertEqual(len(case.factory.calls),1)
                    finally:case.doCleanups()

    def test_new_semantic_field_requires_explicit_transfer_and_no_model_retries(self):
        refs,task=self.content(11);self.grant['operations']=['records.merge'];self.create(inputs=refs);self.rt.tick('job');s=self.session()
        interface=c.REGISTRY['collection.options',1]['planning_interface'];schema=copy.deepcopy(interface['schema']);schema['properties']['future_policy']={'type':'string'}
        args=dict(request_id='defect',tasks=[task]);before=len(self.factory.calls)
        with patch.dict(interface,schema=schema):
            with self.assertRaisesRegex(ValueError,'every declared semantic parameter') as caught:s.delegate(args)
        result=s.reject_submission(args,caught.exception)
        self.assertEqual(result['validation']['code'],'compiler_contract_incompatible');self.assertEqual(result['validation']['effect'],'none')
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(len(self.factory.calls),before)
        self.assertEqual(s.progress_hold['code'],'compiler_contract_incompatible')
        with self.assertRaisesRegex(ValueError,'every declared semantic parameter'):s.check_progress(1,1)
        self.assertEqual(s.pending_submission['rejections'],1)

    def test_generated_consumer_mismatch_is_typed_hold_without_effect(self):
        refs,task=self.content(11);self.grant['operations']=['records.merge'];self.create(inputs=refs);self.rt.tick('job');s=self.session()
        interface=c.REGISTRY['collection.options',1]['planning_interface'];transfer=copy.deepcopy(interface['merge_transfer']);transfer['parameters']['selection_policy']='parameter';task['content']['parameters']['selection_policy']='visual'
        with patch.dict(interface,merge_transfer=transfer):
            with self.assertRaisesRegex(ValueError,'registered consumer contract') as caught:s.delegate(dict(request_id='defect',tasks=[task]))
        self.assertEqual(caught.exception.outcome['code'],'compiler_contract_incompatible')
        self.assertEqual(len(self.rt.status('job')['tasks']),1);self.assertEqual(len(self.factory.calls),1)

    def test_actual_partition_review_restart_merge_visual_policy(self):
        original=self.content
        def visual(*a,**kw):
            refs,t=original(*a,**kw);t['content']['parameters']['selection_policy']='visual';return refs,t
        self.content=visual
        owner.Tests.test_partition_workers_reviews_restart_and_native_merge_complete(self)
        doc=json.loads(__import__('pathlib').Path(self.rt.output('job','collect','delivery/catalog.json')['blob']).read_text())
        self.assertEqual(doc['parameters']['selection_policy'],'visual')
        self.assertTrue(all(i['coverage']['suitable']==0 and i['coverage']['shortfall']==2 for i in doc['items']))
